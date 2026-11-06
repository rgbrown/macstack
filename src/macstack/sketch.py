"""Sketch format: a compact, Markdown-shaped, lossless view of a STACK question.

A *sketch* (``.stack.md``) shows only the decisions an author makes — question
text, variables, inputs, PRTs, tests and hints — and hides everything that is
equal to the course defaults (``macstack.toml``) or is managed elsewhere
(category headers, deployed seeds).

The XML file always remains the source of truth:

* :func:`xml_to_sketch` renders a sketch from question XML.
* :func:`parse_sketch` parses sketch text into a :class:`SketchQuestion`
  (raising :class:`SketchError` with a line number on problems).
* :func:`apply_sketch` merges a parsed sketch onto the latest XML.  Fields whose
  value is unchanged are left byte-for-byte untouched, fields missing from the
  sketch are reset to their defaults, and anything the sketch does not model
  is carried through unchanged.

See ``.agents/skills/stack-authoring/references/sketch-format.md`` for the full
format reference.
"""

from __future__ import annotations

import copy
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w
from lxml import etree

from macstack.config import CourseConfig, find_course_config
from macstack.ref import ANSWER_TEST_ALIASES, ANSWER_TESTS
from macstack.xml_codec import (
    INPUT_TAG_ORDER,
    NODE_TAG_ORDER,
    _extract_element_text,
    _get_xml_root,
    _serialize_xml,
    find_stack_question,
    normalize_question_xml,
)

SKETCH_SUFFIX = ".stack.md"

# --------------------------------------------------------------------------- #
# Field tables
# --------------------------------------------------------------------------- #

#: Question-level scalar settings that may appear in the front matter.
FRONT_MATTER_FIELDS = [
    "name",
    "idnumber",
    "defaultgrade",
    "penalty",
    "hidden",
    "stackversion",
    "questionsimplify",
    "assumepositive",
    "assumereal",
    "decimals",
    "scientificnotation",
    "multiplicationsign",
    "sqrtsign",
    "complexno",
    "inversetrig",
    "logicsymbol",
    "matrixparens",
    "variantsselectionseed",
    "isbroken",
]
_FRONT_MATTER_TEXT_CHILD = {"name", "stackversion"}
_FLOAT_FIELDS = {"defaultgrade", "penalty"}
_INT_FIELDS = {"hidden", "questionsimplify", "assumepositive", "assumereal", "isbroken"}

#: (section heading, XML tag) for free-text HTML sections, in emission order.
TEXT_SECTIONS = [
    ("Question text", "questiontext"),
    ("Specific feedback", "specificfeedback"),
    ("General feedback", "generalfeedback"),
    ("Question note", "questionnote"),
    ("Question description", "questiondescription"),
    ("PRT correct", "prtcorrect"),
    ("PRT partially correct", "prtpartiallycorrect"),
    ("PRT incorrect", "prtincorrect"),
]
_TEXT_HEADING_TO_TAG = {h.lower(): t for h, t in TEXT_SECTIONS}

#: Input settings expressible as ``key=value`` (everything except name/type).
INPUT_KEYS = [t for t in INPUT_TAG_ORDER if t not in ("name", "type")]
PRT_KEYS = ["value", "autosimplify", "feedbackstyle"]

#: Answer tests supported by STACK (imported from macstack.ref).

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*```")
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


class SketchError(ValueError):
    """A problem in a sketch, with the 1-based line number where it occurred."""

    def __init__(self, line: int, message: str) -> None:
        self.line = line
        self.message = message
        super().__init__(f"line {line}: {message}")


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #


@dataclass
class SketchInput:
    name: str
    type: str | None = None  # None = course default
    settings: dict[str, str] = field(default_factory=dict)


@dataclass
class SketchBranch:
    scoremode: str = "="
    score: str | None = None  # None = branch default (true: 1, false: 0)
    penalty: str = ""
    nextnode: str = "-1"
    answernote: str | None = None  # None = auto ``{prt}-{node}-{T|F}``
    feedback: str = ""
    line: int = 0


@dataclass
class SketchNode:
    name: str
    answertest: str
    sans: str
    tans: str
    testoptions: str = ""
    description: str = ""
    quiet: str = "0"
    true: SketchBranch = field(default_factory=SketchBranch)
    false: SketchBranch = field(default_factory=SketchBranch)
    line: int = 0


@dataclass
class SketchPrt:
    name: str
    settings: dict[str, str] = field(default_factory=dict)
    feedbackvariables: str = ""
    nodes: list[SketchNode] = field(default_factory=list)


@dataclass
class SketchExpected:
    prt: str
    score: str = ""
    penalty: str = "0"
    answernote: str = ""


@dataclass
class SketchTest:
    testcase: str
    description: str = ""
    inputs: list[tuple[str, str]] = field(default_factory=list)
    expected: list[SketchExpected] = field(default_factory=list)


@dataclass
class SketchQuestion:
    settings: dict[str, str] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    questionvariables: str = ""
    inputs: list[SketchInput] = field(default_factory=list)
    prts: list[SketchPrt] = field(default_factory=list)
    tests: list[SketchTest] | None = None  # None = section absent
    hints: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _same_value(a: str | None, b: str | None) -> bool:
    """Compare two scalar values, numerically when both are numbers."""
    a = (a or "").strip()
    b = (b or "").strip()
    if a == b:
        return True
    fa, fb = _as_float(a), _as_float(b)
    return fa is not None and fb is not None and fa == fb


def _same_text(a: str | None, b: str | None) -> bool:
    return (a or "").strip() == (b or "").strip()


def _fmt_num(value: str) -> str:
    """Pretty-print a numeric string for display (``1.0000000`` -> ``1``)."""
    f = _as_float(value)
    if f is None or "e" in value.lower():
        return value.strip()
    if f.is_integer():
        return str(int(f))
    return format(f, ".10g")


def _fmt_moodle_float(value: str) -> str:
    f = _as_float(value)
    return f"{f:.7f}" if f is not None else value


def _split_top_level(text: str, sep: str = ",") -> list[tuple[int, str]]:
    """Split on ``sep`` outside brackets and quotes. Returns (start offset, piece)."""
    parts: list[tuple[int, str]] = []
    depth = 0
    quote: str | None = None
    start = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == sep and depth == 0:
            parts.append((start, text[start:i]))
            start = i + 1
        i += 1
    parts.append((start, text[start:]))
    return parts


def _quote_if_needed(value: str) -> str:
    if (
        value == ""
        or value != value.strip()
        or value.startswith('"')
        or any(ch.isspace() for ch in value)
        or len(_split_top_level(value)) > 1
    ):
        return json.dumps(value, ensure_ascii=False)
    return value


def _unquote(value: str, line: int) -> str:
    value = value.strip()
    if value.startswith('"'):
        try:
            result = json.loads(value)
        except json.JSONDecodeError as e:
            raise SketchError(line, f"invalid quoted value {value!r}: {e.msg}") from None
        if not isinstance(result, str):
            raise SketchError(line, f"invalid quoted value {value!r}")
        return result
    return value


def _child_text(parent: etree._Element, tag: str) -> str:
    """Text of a simple child element, or of its <text> sub-element if present."""
    elem = parent.find(f"./{tag}")
    if elem is None:
        return ""
    text_elem = elem.find("./text")
    if text_elem is not None:
        return _extract_element_text(text_elem)
    return elem.text or ""


def _indent(text: str, prefix: str) -> str:
    return "\n".join((prefix + line) if line.strip() else "" for line in text.split("\n"))


def _auto_note(prt: str, node: str, branch: str) -> str:
    return f"{prt}-{node}-{branch}"


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #


def _question_defaults(config: CourseConfig) -> dict[str, str]:
    d = {
        "idnumber": "",
        "stackversion": config.stack_version,
        "variantsselectionseed": "",
        "isbroken": "0",
    }
    for key, value in config.defaults.items():
        d[key] = value
    return d


def _input_default(config: CourseConfig, key: str) -> str:
    return config.input_defaults.get(key, "")


def _prt_default(config: CourseConfig, key: str) -> str:
    return config.prt_defaults.get(key, "")


# --------------------------------------------------------------------------- #
# XML -> model
# --------------------------------------------------------------------------- #


def _read_branch(node: etree._Element, prefix: str) -> SketchBranch:
    return SketchBranch(
        scoremode=(node.findtext(f"./{prefix}scoremode") or "=").strip() or "=",
        score=(node.findtext(f"./{prefix}score") or "").strip(),
        penalty=(node.findtext(f"./{prefix}penalty") or "").strip(),
        nextnode=(node.findtext(f"./{prefix}nextnode") or "-1").strip() or "-1",
        answernote=(node.findtext(f"./{prefix}answernote") or "").strip(),
        feedback=_child_text(node, f"{prefix}feedback"),
    )


def read_question(q: etree._Element) -> SketchQuestion:
    """Read the modelled parts of a <question type="stack"> element."""
    model = SketchQuestion()
    for key in FRONT_MATTER_FIELDS:
        if q.find(f"./{key}") is not None:
            model.settings[key] = _child_text(q, key).strip()
    for _, tag in TEXT_SECTIONS:
        model.texts[tag] = _child_text(q, tag)
    model.questionvariables = _child_text(q, "questionvariables")

    for inp in q.findall("./input"):
        name = (inp.findtext("./name") or "").strip()
        si = SketchInput(name=name, type=(inp.findtext("./type") or "").strip())
        for key in INPUT_KEYS:
            if inp.find(f"./{key}") is not None:
                si.settings[key] = (inp.findtext(f"./{key}") or "").strip()
        model.inputs.append(si)

    for prt in q.findall("./prt"):
        sp = SketchPrt(name=(prt.findtext("./name") or "").strip())
        for key in PRT_KEYS:
            if prt.find(f"./{key}") is not None:
                sp.settings[key] = (prt.findtext(f"./{key}") or "").strip()
        sp.feedbackvariables = _child_text(prt, "feedbackvariables")
        for node in prt.findall("./node"):
            sp.nodes.append(
                SketchNode(
                    name=(node.findtext("./name") or "").strip(),
                    answertest=(node.findtext("./answertest") or "").strip(),
                    sans=(node.findtext("./sans") or "").strip(),
                    tans=(node.findtext("./tans") or "").strip(),
                    testoptions=(node.findtext("./testoptions") or "").strip(),
                    description=(node.findtext("./description") or "").strip(),
                    quiet=(node.findtext("./quiet") or "0").strip() or "0",
                    true=_read_branch(node, "true"),
                    false=_read_branch(node, "false"),
                )
            )
        model.prts.append(sp)

    model.tests = []
    for qt in q.findall("./qtest"):
        st = SketchTest(
            testcase=(qt.findtext("./testcase") or "").strip(),
            description=(qt.findtext("./description") or "").strip(),
        )
        for ti in qt.findall("./testinput"):
            st.inputs.append(((ti.findtext("./name") or "").strip(), (ti.findtext("./value") or "").strip()))
        for ex in qt.findall("./expected"):
            st.expected.append(
                SketchExpected(
                    prt=(ex.findtext("./name") or "").strip(),
                    score=(ex.findtext("./expectedscore") or "").strip(),
                    penalty=(ex.findtext("./expectedpenalty") or "").strip(),
                    answernote=(ex.findtext("./expectedanswernote") or "").strip(),
                )
            )
        model.tests.append(st)

    model.hints = [_extract_element_text(h.find("./text")) for h in q.findall("./hint")]
    return model


# --------------------------------------------------------------------------- #
# Model -> sketch text
# --------------------------------------------------------------------------- #


def _toml_value(key: str, value: str) -> object:
    if key in _FLOAT_FIELDS and _as_float(value) is not None:
        f = float(value)
        return int(f) if f.is_integer() else f
    if key in _INT_FIELDS and re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def _branch_line(kind: str, b: SketchBranch, prt: str, node: str) -> str:
    parts: list[str] = [f"{kind}:"]
    default_score = "1" if kind == "true" else "0"
    score = b.score if b.score not in (None, "") else default_score
    if kind == "true" or b.scoremode != "=" or not _same_value(score, default_score):
        parts.append(f"{b.scoremode}{_fmt_num(score)}")
    if b.nextnode.strip() not in ("-1", ""):
        parts.append(f"-> {b.nextnode.strip()}")
    if b.penalty.strip():
        parts.append(f"penalty={_fmt_num(b.penalty)}")
    note = b.answernote or ""
    if note and note != _auto_note(prt, node, "T" if kind == "true" else "F"):
        parts.append(f"note={_quote_if_needed(note) if ' ' not in note else json.dumps(note)}")
    return " ".join(parts)


def _branch_is_default(kind: str, b: SketchBranch, prt: str, node: str) -> bool:
    default_score = "1" if kind == "true" else "0"
    return (
        b.scoremode == "="
        and _same_value(b.score or default_score, default_score)
        and b.nextnode.strip() in ("-1", "")
        and not b.penalty.strip()
        and (not b.answernote or b.answernote == _auto_note(prt, node, "T" if kind == "true" else "F"))
        and not b.feedback.strip()
    )


def render_sketch(model: SketchQuestion, config: CourseConfig, header: list[str] | None = None) -> str:
    """Render a :class:`SketchQuestion` as sketch text, hiding default values."""
    out: list[str] = ["+++"]
    for line in header or []:
        out.append(f"# {line}" if line else "#")
    qdefaults = _question_defaults(config)
    for key in FRONT_MATTER_FIELDS:
        value = model.settings.get(key)
        if value is None:
            continue
        if key not in ("name",) and _same_value(value, qdefaults.get(key, "")):
            continue
        out.append(tomli_w.dumps({key: _toml_value(key, value)}).rstrip("\n"))
    out.append("+++")

    def section(title: str, body: str) -> None:
        out.append("")
        out.append(f"## {title}")
        out.append(body.strip("\n"))

    if model.questionvariables.strip():
        section("Question variables", "```maxima\n" + model.questionvariables.strip("\n") + "\n```")

    for heading, tag in TEXT_SECTIONS:
        text = model.texts.get(tag, "")
        if not text.strip():
            continue
        if tag in config.defaults and _same_text(text, config.defaults[tag]):
            continue
        section(heading, text)

    if model.inputs:
        lines = []
        for inp in model.inputs:
            tokens = [inp.type or _input_default(config, "type")]
            for key in INPUT_KEYS:
                if key not in inp.settings:
                    continue
                value = inp.settings[key]
                if key != "tans" and _same_value(value, _input_default(config, key)):
                    continue
                tokens.append(f"{key}={_quote_if_needed(value)}")
            lines.append(f"{inp.name}: " + ", ".join(tokens))
        section("Inputs", "\n".join(lines))

    for prt in model.prts:
        lines = []
        settings = [
            f"{k}={_quote_if_needed(v)}"
            for k, v in prt.settings.items()
            if not _same_value(v, _prt_default(config, k))
        ]
        if settings:
            lines.append(", ".join(settings))
        if prt.feedbackvariables.strip():
            lines.append("feedback variables:")
            lines.append("```maxima\n" + prt.feedbackvariables.strip("\n") + "\n```")
        for node in prt.nodes:
            args = [node.sans, node.tans] + ([node.testoptions] if node.testoptions else [])
            lines.append(f"node {node.name}: {node.answertest}({', '.join(args)})")
            if node.description:
                lines.append(f"  description: {node.description}")
            if node.quiet.strip() not in ("0", ""):
                lines.append("  quiet")
            for kind in ("true", "false"):
                b = node.true if kind == "true" else node.false
                if kind == "false" and _branch_is_default(kind, b, prt.name, node.name):
                    continue
                lines.append("  " + _branch_line(kind, b, prt.name, node.name))
                if b.feedback.strip():
                    lines.append(_indent(b.feedback.strip("\n"), "    "))
        section(f"PRT {prt.name}", "\n".join(lines))

    if model.tests:
        blocks = []
        for t in model.tests:
            block = [f"### Test {t.testcase}" + (f": {t.description}" if t.description else "")]
            for name, value in t.inputs:
                block.append(f"{name} = {value}")
            for ex in t.expected:
                note_str = _quote_if_needed(ex.answernote) if ex.answernote else ""
                exp = f"{ex.prt} => {_fmt_num(ex.score) if ex.score else ''}, {note_str}"
                if ex.penalty and not _same_value(ex.penalty, "0"):
                    exp += f", penalty={_fmt_num(ex.penalty)}"
                block.append(exp.rstrip(", "))
            blocks.append("\n".join(block))
        section("Tests", "\n\n".join(blocks))

    for hint in model.hints:
        section("Hint", hint)

    return "\n".join(out).rstrip("\n") + "\n"


def xml_to_sketch(xml: str | Path, config: CourseConfig | None = None, source_label: str | None = None) -> str:
    """Render the sketch for a question XML string or file."""
    root, path = _get_xml_root(xml)
    if config is None:
        config, _ = find_course_config(path.parent if path else Path.cwd())
    q = find_stack_question(root)
    if q is None:
        raise ValueError("No <question type='stack'> element found in XML")
    model = read_question(q)
    seeds = len(q.findall("./deployedseed"))
    header = [f"macstack sketch of {source_label}" if source_label else "macstack sketch"]
    header.append("Settings equal to the course defaults are hidden; delete a line to reset it.")
    if seeds:
        header.append(f"{seeds} deployed seeds are preserved (manage with `macstack deploy-seeds`).")
    return render_sketch(model, config, header)


# --------------------------------------------------------------------------- #
# Sketch text -> model
# --------------------------------------------------------------------------- #


@dataclass
class _Section:
    title: str
    line: int  # line number of the heading
    body: list[tuple[int, str]]  # (line number, text)


def _strip_blank_edges(body: list[tuple[int, str]]) -> list[tuple[int, str]]:
    start, end = 0, len(body)
    while start < end and not body[start][1].strip():
        start += 1
    while end > start and not body[end - 1][1].strip():
        end -= 1
    return body[start:end]


def _join(body: list[tuple[int, str]]) -> str:
    return "\n".join(text for _, text in _strip_blank_edges(body))


def _strip_fence(body: list[tuple[int, str]]) -> list[tuple[int, str]]:
    body = _strip_blank_edges(body)
    if len(body) >= 2 and _FENCE_RE.match(body[0][1]) and body[-1][1].strip() == "```":
        return body[1:-1]
    return body


def _is_known_heading(title: str) -> bool:
    t = title.lower()
    return (
        t in _TEXT_HEADING_TO_TAG
        or t in ("question variables", "inputs", "tests", "hint")
        or bool(re.fullmatch(r"prt\s+\S+", t))
    )


def _split_sections(lines: list[str], first_line: int) -> tuple[list[tuple[int, str]], list[_Section]]:
    preamble: list[tuple[int, str]] = []
    sections: list[_Section] = []
    in_fence = False
    for offset, text in enumerate(lines):
        lineno = first_line + offset
        if _FENCE_RE.match(text):
            in_fence = not in_fence
        m = None if in_fence else _SECTION_RE.match(text)
        if m and _is_known_heading(m.group(1)):
            sections.append(_Section(m.group(1), lineno, []))
        elif sections:
            sections[-1].body.append((lineno, text))
        else:
            preamble.append((lineno, text))
    return preamble, sections


def _parse_front_matter(lines: list[str]) -> tuple[dict[str, str], int]:
    """Parse the ``+++`` TOML block. Returns (settings, index of first body line)."""
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines) or lines[idx].strip() != "+++":
        return {}, 0
    start = idx
    end = None
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == "+++":
            end = j
            break
    if end is None:
        raise SketchError(start + 1, "front matter opened with '+++' but never closed")
    toml_text = "\n".join(lines[start + 1 : end])
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as e:
        m = re.search(r"line (\d+)", str(e))
        line = start + 1 + (int(m.group(1)) if m else max(1, end - start - 1))
        raise SketchError(line, f"invalid front matter: {e}") from None

    settings: dict[str, str] = {}
    for key, value in data.items():
        line = start + 1
        for j in range(start + 1, end):
            if re.match(rf"\s*{re.escape(key)}\s*=", lines[j]):
                line = j + 1
                break
        if key not in FRONT_MATTER_FIELDS:
            raise SketchError(line, f"unknown setting {key!r} (allowed: {', '.join(FRONT_MATTER_FIELDS)})")
        if isinstance(value, bool):
            value = "1" if value else "0"
        if isinstance(value, (dict, list)):
            raise SketchError(line, f"setting {key!r} must be a single value")
        settings[key] = str(value)
    return settings, end + 1


def _parse_inputs(section: _Section) -> list[SketchInput]:
    inputs: list[SketchInput] = []
    seen: set[str] = set()
    for lineno, text in section.body:
        if not text.strip():
            continue
        m = re.match(rf"^\s*({_IDENT})\s*:\s*(.*)$", text)
        if not m:
            raise SketchError(lineno, "expected an input line like 'ans1: algebraic, tans=ta1'")
        name, rest = m.group(1), m.group(2)
        if name in seen:
            raise SketchError(lineno, f"duplicate input {name!r}")
        seen.add(name)
        inp = SketchInput(name=name)
        for _, token in _split_top_level(rest):
            token = token.strip()
            if not token:
                continue
            km = re.match(rf"^({_IDENT})\s*=\s*(.*)$", token, re.S)
            if not km:
                if inp.type is not None:
                    raise SketchError(lineno, f"unexpected {token!r}; settings must be written key=value")
                inp.type = _unquote(token, lineno)
                continue
            key, value = km.group(1), _unquote(km.group(2), lineno)
            if key == "type":
                inp.type = value
            elif key in INPUT_KEYS:
                inp.settings[key] = value
            else:
                raise SketchError(lineno, f"unknown input setting {key!r} (allowed: type, {', '.join(INPUT_KEYS)})")
        inputs.append(inp)
    return inputs


_NODE_RE = re.compile(r"^node\s+(\S+?)\s*:\s*([A-Za-z][A-Za-z0-9_-]*)\s*\((.*)\)\s*$")
_BRANCH_RE = re.compile(r"^(true|false)\s*:\s*(.*)$")


def _parse_branch(text: str, lineno: int) -> SketchBranch:
    b = SketchBranch(line=lineno)
    rest = text
    m = re.search(r'note\s*=\s*("(?:[^"\\]|\\.)*"|\S+)', rest)
    if m:
        b.answernote = _unquote(m.group(1), lineno)
        rest = rest[: m.start()] + rest[m.end():]
    saw_arrow = False
    for token in rest.split():
        if saw_arrow:
            b.nextnode = token
            saw_arrow = False
            continue
        if token == "->":
            saw_arrow = True
            continue
        if token.startswith("->"):
            b.nextnode = token[2:]
            continue
        if token.startswith("penalty="):
            b.penalty = token.split("=", 1)[1]
            continue
        if token[0] in "=+-" and _as_float(token[1:]) is not None:
            b.scoremode, b.score = token[0], token[1:]
            continue
        raise SketchError(lineno, f"unexpected {token!r} in branch (use =1, +0.5, -> 2, penalty=0.1, note=...)")
    if saw_arrow:
        raise SketchError(lineno, "expected node name after '->'")
    if b.nextnode == "end":
        b.nextnode = "-1"
    if b.penalty and _as_float(b.penalty) is None:
        raise SketchError(lineno, f"penalty must be a number, got {b.penalty!r}")
    return b


def _parse_prt(section: _Section, name: str) -> SketchPrt:
    prt = SketchPrt(name=name)
    body = section.body
    i = 0
    node: SketchNode | None = None
    branch: SketchBranch | None = None
    feedback: list[str] = []

    def flush_feedback() -> None:
        nonlocal feedback
        if branch is not None:
            while feedback and not feedback[-1].strip():
                feedback.pop()
            while feedback and not feedback[0].strip():
                feedback.pop(0)
            branch.feedback = "\n".join(feedback)
        feedback = []

    while i < len(body):
        lineno, text = body[i]
        stripped = text.strip()
        indent = len(text) - len(text.lstrip(" "))
        if branch is not None and (not stripped or indent >= 4):
            feedback.append(text[4:] if text.startswith("    ") else text.lstrip())
            i += 1
            continue
        if not stripped:
            i += 1
            continue
        flush_feedback()
        branch = None

        if node is None and stripped.lower().rstrip(":") == "feedback variables":
            fence: list[tuple[int, str]] = []
            i += 1
            while i < len(body) and not body[i][1].strip():
                i += 1
            if i < len(body) and _FENCE_RE.match(body[i][1]):
                i += 1
                while i < len(body) and body[i][1].strip() != "```":
                    fence.append(body[i])
                    i += 1
                if i >= len(body):
                    raise SketchError(lineno, "unclosed ``` fence in feedback variables")
                i += 1
            prt.feedbackvariables = _join(fence)
            continue

        m = _NODE_RE.match(stripped)
        if m and indent == 0:
            args = _split_top_level(m.group(3))
            if len(args) < 2:
                raise SketchError(lineno, "node needs at least (student answer, teacher answer)")
            test = m.group(2)
            if test not in ANSWER_TESTS:
                test_lower = test.lower()
                if test_lower in ANSWER_TEST_ALIASES:
                    canonical, reason = ANSWER_TEST_ALIASES[test_lower]
                    hint = f" (did you mean {canonical!r}? {reason})"
                else:
                    import difflib

                    close = [t for t in ANSWER_TESTS if t.lower() == test_lower]
                    if not close:
                        close = difflib.get_close_matches(test, ANSWER_TESTS, n=1, cutoff=0.6)
                    hint = f" (did you mean {close[0]!r}?)" if close else ""
                raise SketchError(lineno, f"unknown answer test {test!r}{hint}")
            opts = m.group(3)[args[2][0]:].strip() if len(args) > 2 else ""
            node = SketchNode(
                name=m.group(1),
                answertest=test,
                sans=args[0][1].strip(),
                tans=args[1][1].strip(),
                testoptions=opts,
                line=lineno,
            )
            if any(n.name == node.name for n in prt.nodes):
                raise SketchError(lineno, f"duplicate node {node.name!r} in {name}")
            prt.nodes.append(node)
            i += 1
            continue

        if node is None:
            if indent == 0 and "=" in stripped:
                for _, token in _split_top_level(stripped):
                    km = re.match(rf"^\s*({_IDENT})\s*=\s*(.*?)\s*$", token)
                    if not km or km.group(1) not in PRT_KEYS:
                        raise SketchError(lineno, f"expected PRT settings ({', '.join(PRT_KEYS)}) or 'node N: Test(sans, tans)'")
                    prt.settings[km.group(1)] = _unquote(km.group(2), lineno)
                i += 1
                continue
            raise SketchError(lineno, "expected 'node N: Test(sans, tans[, options])'")

        bm = _BRANCH_RE.match(stripped)
        if bm and indent > 0:
            branch = _parse_branch(bm.group(2), lineno)
            if bm.group(1) == "true":
                node.true = branch
            else:
                node.false = branch
            i += 1
            continue
        if indent > 0 and stripped.startswith("description:"):
            node.description = stripped.split(":", 1)[1].strip()
            i += 1
            continue
        if indent > 0 and re.fullmatch(r"quiet(\s*=\s*[01])?", stripped):
            node.quiet = "0" if stripped.endswith("0") else "1"
            i += 1
            continue
        raise SketchError(lineno, f"unexpected line in {name}: {stripped!r}")

    flush_feedback()

    names = {n.name for n in prt.nodes}
    for n in prt.nodes:
        for b in (n.true, n.false):
            if b.nextnode not in ("-1", "") and b.nextnode not in names:
                raise SketchError(b.line or n.line, f"node {n.name} branches to node {b.nextnode}, which does not exist in {name}")
    return prt


def _parse_tests(section: _Section) -> list[SketchTest]:
    tests: list[SketchTest] = []
    current: SketchTest | None = None
    for lineno, text in section.body:
        stripped = text.strip()
        if not stripped:
            continue
        hm = re.match(r"^###\s+Test\s+(\S+?)(?:\s*:\s*(.*))?$", stripped, re.I)
        if hm:
            current = SketchTest(testcase=hm.group(1), description=(hm.group(2) or "").strip())
            if any(t.testcase == current.testcase for t in tests):
                raise SketchError(lineno, f"duplicate test {current.testcase!r}")
            tests.append(current)
            continue
        if current is None:
            raise SketchError(lineno, "expected a test heading like '### Test 1: Model answer'")
        em = re.match(rf"^({_IDENT})\s*=>\s*(.*)$", stripped)
        if em:
            pieces = [p.strip() for _, p in _split_top_level(em.group(2))]
            ex = SketchExpected(prt=em.group(1), score=pieces[0] if pieces else "")
            for piece in pieces[1:]:
                if piece.startswith("penalty="):
                    ex.penalty = piece.split("=", 1)[1].strip()
                elif not ex.answernote:
                    ex.answernote = _unquote(piece, lineno)
                else:
                    raise SketchError(lineno, f"unexpected {piece!r}; expected 'prt => score, note[, penalty=x]'")
            if ex.score and _as_float(ex.score) is None:
                raise SketchError(lineno, f"expected score must be a number, got {ex.score!r}")
            if ex.penalty and _as_float(ex.penalty) is None:
                raise SketchError(lineno, f"expected penalty must be a number, got {ex.penalty!r}")
            current.expected.append(ex)
            continue
        im = re.match(rf"^({_IDENT})\s*=\s?(.*)$", stripped)
        if im:
            current.inputs.append((im.group(1), im.group(2).strip()))
            continue
        raise SketchError(lineno, "expected 'input = value' or 'prt => score, note'")
    return tests


def parse_sketch(text: str) -> SketchQuestion:
    """Parse sketch text into a :class:`SketchQuestion`."""
    lines = text.replace("\r\n", "\n").split("\n")
    settings, body_start = _parse_front_matter(lines)
    preamble, sections = _split_sections(lines[body_start:], body_start + 1)
    for lineno, line in preamble:
        if line.strip() and not line.strip().startswith("<!--"):
            raise SketchError(lineno, "content before the first '## Section' heading")

    model = SketchQuestion(settings=settings)
    seen: set[str] = set()
    for sec in sections:
        title = sec.title.lower()
        if title != "hint":
            if title in seen:
                raise SketchError(sec.line, f"section '## {sec.title}' appears twice")
            seen.add(title)
        if title in _TEXT_HEADING_TO_TAG:
            model.texts[_TEXT_HEADING_TO_TAG[title]] = _join(sec.body)
        elif title == "question variables":
            model.questionvariables = _join(_strip_fence(sec.body))
        elif title == "hint":
            model.hints.append(_join(sec.body))
        elif title == "inputs":
            model.inputs = _parse_inputs(sec)
        elif title == "tests":
            model.tests = _parse_tests(sec)
        else:  # PRT
            name = sec.title.split(None, 1)[1].strip()
            if not re.fullmatch(_IDENT, name):
                raise SketchError(sec.line, f"invalid PRT name {name!r}")
            model.prts.append(_parse_prt(sec, name))
    if "name" not in settings:
        raise SketchError(1, "front matter must set the question name, e.g. name = \"My question\"")
    return model


# --------------------------------------------------------------------------- #
# Apply model -> XML
# --------------------------------------------------------------------------- #


def _cdata_or_text(value: str) -> etree.CDATA | str | None:
    if not value:
        return None
    if "]]>" in value:
        return value
    return etree.CDATA(value)


def _set_simple(parent: etree._Element, tag: str, value: str, numeric: bool = False, fmt=None) -> None:
    elem = parent.find(f"./{tag}")
    current = (elem.text or "") if elem is not None else None
    if current is not None:
        same = _same_value(current, value) if numeric else current.strip() == value.strip()
        if same:
            return
    if elem is None:
        elem = etree.SubElement(parent, tag)
    elem.text = (fmt(value) if fmt else value) or None


def _set_text_child(parent: etree._Element, tag: str, value: str, cdata: bool, html: bool = False) -> None:
    elem = parent.find(f"./{tag}")
    if elem is None:
        elem = etree.SubElement(parent, tag)
    if html and elem.get("format") is None:
        elem.set("format", "html")
    text_elem = elem.find("./text")
    if text_elem is None:
        text_elem = etree.SubElement(elem, "text")
    elif _same_text(_extract_element_text(text_elem), value):
        return
    for child in list(text_elem):
        text_elem.remove(child)
    text_elem.text = _cdata_or_text(value) if cdata else (value or None)


def _apply_branch(node: etree._Element, prefix: str, b: SketchBranch, prt: str, node_name: str) -> None:
    default_score = "1" if prefix == "true" else "0"
    _set_simple(node, f"{prefix}scoremode", b.scoremode or "=")
    _set_simple(node, f"{prefix}score", b.score if b.score not in (None, "") else default_score, numeric=True)
    _set_simple(node, f"{prefix}penalty", b.penalty, numeric=True)
    _set_simple(node, f"{prefix}nextnode", b.nextnode or "-1")
    note = b.answernote or _auto_note(prt, node_name, "T" if prefix == "true" else "F")
    _set_simple(node, f"{prefix}answernote", note)
    _set_text_child(node, f"{prefix}feedback", b.feedback, cdata=True, html=True)


def _apply_node(node: etree._Element, sn: SketchNode, prt: str) -> None:
    _set_simple(node, "name", sn.name)
    _set_simple(node, "answertest", sn.answertest)
    _set_simple(node, "sans", sn.sans)
    _set_simple(node, "tans", sn.tans)
    _set_simple(node, "testoptions", sn.testoptions)
    _set_simple(node, "description", sn.description)
    _set_simple(node, "quiet", sn.quiet or "0")
    _apply_branch(node, "true", sn.true, prt, sn.name)
    _apply_branch(node, "false", sn.false, prt, sn.name)


def _new_node(sn: SketchNode) -> etree._Element:
    node = etree.Element("node")
    for tag in NODE_TAG_ORDER:
        if tag.endswith("feedback"):
            fb = etree.SubElement(node, tag, format="html")
            etree.SubElement(fb, "text")
        else:
            etree.SubElement(node, tag)
    return node


def _reorder(parent: etree._Element, tag: str, ordered: list[etree._Element]) -> None:
    """Place ``ordered`` children (all with ``tag``) in the slots of existing ``tag`` children."""
    existing = parent.findall(f"./{tag}")
    if existing == ordered:
        return
    if existing:
        anchor_index = list(parent).index(existing[0])
        for e in existing:
            parent.remove(e)
    else:
        anchor_index = len(parent)
    for offset, e in enumerate(ordered):
        parent.insert(anchor_index + offset, e)


def _insert_before_tail(q: etree._Element, elem: etree._Element, before_tags: tuple[str, ...]) -> None:
    for i, child in enumerate(q):
        if child.tag in before_tags:
            q.insert(i, elem)
            return
    q.append(elem)


def _expected_same(ex_elem: etree._Element, ex: SketchExpected) -> bool:
    return (
        (ex_elem.findtext("./name") or "").strip() == ex.prt
        and _same_value(ex_elem.findtext("./expectedscore"), ex.score)
        and _same_value(ex_elem.findtext("./expectedpenalty") or "0", ex.penalty or "0")
        and (ex_elem.findtext("./expectedanswernote") or "").strip() == ex.answernote
    )


def _qtest_same(qt: etree._Element, st: SketchTest) -> bool:
    if (qt.findtext("./description") or "").strip() != st.description:
        return False
    inputs = [((t.findtext("./name") or "").strip(), (t.findtext("./value") or "").strip()) for t in qt.findall("./testinput")]
    if inputs != st.inputs:
        return False
    expected = qt.findall("./expected")
    return len(expected) == len(st.expected) and all(_expected_same(e, x) for e, x in zip(expected, st.expected))


def _build_qtest(st: SketchTest) -> etree._Element:
    qt = etree.Element("qtest")
    etree.SubElement(qt, "testcase").text = st.testcase
    etree.SubElement(qt, "description").text = st.description or None
    for name, value in st.inputs:
        ti = etree.SubElement(qt, "testinput")
        etree.SubElement(ti, "name").text = name
        etree.SubElement(ti, "value").text = value or None
    for ex in st.expected:
        e = etree.SubElement(qt, "expected")
        etree.SubElement(e, "name").text = ex.prt
        etree.SubElement(e, "expectedscore").text = _fmt_moodle_float(ex.score) if ex.score else None
        etree.SubElement(e, "expectedpenalty").text = _fmt_moodle_float(ex.penalty or "0")
        etree.SubElement(e, "expectedanswernote").text = ex.answernote or None
    return qt


def apply_sketch(
    model: SketchQuestion,
    base_xml: str | None,
    config: CourseConfig,
    category_id: str | None = None,
) -> str:
    """Merge a parsed sketch onto ``base_xml`` (or a new question) and return normalized XML."""
    if base_xml and base_xml.strip():
        root, _ = _get_xml_root(base_xml)
        root = copy.deepcopy(root)
    else:
        root = etree.Element("quiz")
        etree.SubElement(root, "question", type="stack")
    q = find_stack_question(root)
    if q is None:
        raise ValueError("No <question type='stack'> element found in XML")

    # 1. Front matter settings (absent => course default).
    qdefaults = _question_defaults(config)
    for key in FRONT_MATTER_FIELDS:
        if key == "name":
            _set_text_child(q, "name", model.settings.get("name", ""), cdata=False)
            continue
        value = model.settings.get(key, qdefaults.get(key, ""))
        if key in _FRONT_MATTER_TEXT_CHILD:
            elem = q.find(f"./{key}")
            if elem is not None and _same_value(_child_text(q, key), value):
                continue
            _set_text_child(q, key, value, cdata=False)
        else:
            fmt = _fmt_moodle_float if key in _FLOAT_FIELDS else None
            _set_simple(q, key, value, numeric=True, fmt=fmt)

    # 2. Free text and CAS sections (absent => empty or course default).
    for _, tag in TEXT_SECTIONS:
        value = model.texts.get(tag)
        if value is None or (not value.strip() and tag in config.defaults):
            value = config.defaults.get(tag, "")
        _set_text_child(q, tag, value, cdata=True, html=True)
    _set_text_child(q, "questionvariables", model.questionvariables, cdata=True)

    # 3. Inputs (matched by name; removed inputs are deleted).
    existing_inputs = {(e.findtext("./name") or "").strip(): e for e in q.findall("./input")}
    ordered_inputs: list[etree._Element] = []
    for si in model.inputs:
        elem = existing_inputs.pop(si.name, None)
        if elem is None:
            elem = etree.Element("input")
            for tag in INPUT_TAG_ORDER:
                etree.SubElement(elem, tag)
        _set_simple(elem, "name", si.name)
        _set_simple(elem, "type", si.type or _input_default(config, "type"))
        for key in INPUT_KEYS:
            value = si.settings.get(key)
            if value is None:
                value = _input_default(config, key)
                if key == "tans":
                    value = (elem.findtext("./tans") or "").strip() or value
            _set_simple(elem, key, value, numeric=True)
        ordered_inputs.append(elem)
    for orphan in existing_inputs.values():
        q.remove(orphan)
    for elem in ordered_inputs:
        if elem.getparent() is None:
            _insert_before_tail(q, elem, ("prt", "deployedseed", "qtest", "hint"))
    _reorder(q, "input", ordered_inputs)

    # 4. PRTs (matched by name; nodes matched by node name).
    existing_prts = {(e.findtext("./name") or "").strip(): e for e in q.findall("./prt")}
    ordered_prts: list[etree._Element] = []
    for sp in model.prts:
        prt = existing_prts.pop(sp.name, None)
        if prt is None:
            prt = etree.Element("prt")
            etree.SubElement(prt, "name")
        _set_simple(prt, "name", sp.name)
        existing_nodes = {(n.findtext("./name") or "").strip(): n for n in prt.findall("./node")}
        ordered_nodes: list[etree._Element] = []
        for sn in sp.nodes:
            node = existing_nodes.pop(sn.name, None)
            if node is None:
                node = _new_node(sn)
            _apply_node(node, sn, sp.name)
            ordered_nodes.append(node)
        for orphan in existing_nodes.values():
            prt.remove(orphan)
        for node in ordered_nodes:
            if node.getparent() is None:
                after = prt.findall("./node")
                if after:
                    after[-1].addnext(node)
                else:
                    prt.find("./name").addnext(node)
        _reorder(prt, "node", ordered_nodes)
        for key in PRT_KEYS:
            fmt = _fmt_moodle_float if key == "value" else None
            _set_simple(prt, key, sp.settings.get(key, _prt_default(config, key)), numeric=True, fmt=fmt)
        _set_text_child(prt, "feedbackvariables", sp.feedbackvariables, cdata=True)
        ordered_prts.append(prt)
    for orphan in existing_prts.values():
        q.remove(orphan)
    for prt in ordered_prts:
        if prt.getparent() is None:
            _insert_before_tail(q, prt, ("deployedseed", "qtest", "hint"))
    _reorder(q, "prt", ordered_prts)

    # 5. Tests (only when a Tests section is present or tests were removed).
    tests = model.tests if model.tests is not None else []
    existing_tests = {(e.findtext("./testcase") or "").strip(): e for e in q.findall("./qtest")}
    ordered_tests: list[etree._Element] = []
    for st in tests:
        qt = existing_tests.pop(st.testcase, None)
        if qt is None or not _qtest_same(qt, st):
            new_qt = _build_qtest(st)
            if qt is not None:
                qt.addprevious(new_qt)
                q.remove(qt)
            qt = new_qt
        ordered_tests.append(qt)
    for orphan in existing_tests.values():
        q.remove(orphan)
    for qt in ordered_tests:
        if qt.getparent() is None:
            _insert_before_tail(q, qt, ("hint",))
    _reorder(q, "qtest", ordered_tests)

    # 6. Hints (positional).
    hint_elems = q.findall("./hint")
    for i, text in enumerate(model.hints):
        if i < len(hint_elems):
            h = hint_elems[i]
            t = h.find("./text")
            if t is None:
                t = etree.SubElement(h, "text")
            if not _same_text(_extract_element_text(t), text):
                for child in list(t):
                    t.remove(child)
                t.text = _cdata_or_text(text)
        else:
            h = etree.SubElement(q, "hint", format="html")
            etree.SubElement(h, "text").text = _cdata_or_text(text)
    for extra in hint_elems[len(model.hints):]:
        q.remove(extra)

    normalized = normalize_question_xml(_serialize_xml(root), config, category_id=category_id)
    re_root, _ = _get_xml_root(normalized)
    return _serialize_xml(re_root)


# --------------------------------------------------------------------------- #
# File-level conveniences
# --------------------------------------------------------------------------- #


def sketch_file(xml_path: Path, config: CourseConfig | None = None, source_label: str | None = None) -> str:
    """Render the sketch for an XML file."""
    if config is None:
        config, _ = find_course_config(xml_path.resolve().parent)
    return xml_to_sketch(xml_path.read_text(encoding="utf-8"), config, source_label or xml_path.name)


def apply_text_to_file(sketch_text: str, xml_path: Path, config: CourseConfig | None = None) -> bool:
    """Parse ``sketch_text`` and merge it into ``xml_path`` (created if missing).

    Returns True if the XML file changed. Raises :class:`SketchError` on parse problems.
    """
    if config is None:
        config, _ = find_course_config(xml_path.resolve().parent)
    model = parse_sketch(sketch_text)
    base = xml_path.read_text(encoding="utf-8") if xml_path.exists() else None
    new_xml = apply_sketch(model, base, config, category_id=xml_path.parent.name)
    if base == new_xml:
        return False
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(new_xml, encoding="utf-8")
    return True
