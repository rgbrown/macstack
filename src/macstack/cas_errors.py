"""CAS error normalizer, deduplicator, and source snippet builder for STACK Maxima errors."""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
from typing import Any

from macstack.xml_codec import extract_question_fields

# Upstream STACK wrapper error strings to drop when specific probed errors exist
OPAQUE_WRAPPER_PATTERNS = [
    re.compile(r"^stack_cas_keyval:\s*must validate true before compiling\.?", re.IGNORECASE),
    re.compile(r"^The variable\s+\S+\s+is not valid", re.IGNORECASE),
    re.compile(r"^stack_cas_session:\s*all commands must be valid", re.IGNORECASE),
]

# Mapping from common STACK human field descriptions to canonical field keys
PROSE_FIELD_MAP: dict[str, str] = {
    "question variables": "questionvariables",
    "question-variables": "questionvariables",
    "questionvariables": "questionvariables",
    "question text": "questiontext",
    "question-text": "questiontext",
    "questiontext": "questiontext",
    "general feedback": "generalfeedback",
    "general-feedback": "generalfeedback",
    "generalfeedback": "generalfeedback",
    "specific feedback": "specificfeedback",
    "specific-feedback": "specificfeedback",
    "specificfeedback": "specificfeedback",
    "question note": "questionnote",
    "question-note": "questionnote",
    "questionnote": "questionnote",
}


@dataclass
class CasDiagnostic:
    """Normalized STACK CAS / CASText error diagnostic."""

    field: str
    label: str
    message: str
    line: int | None = None
    col: int | None = None
    snippet: str | None = None
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "label": self.label,
            "message": self.message,
            "line": self.line,
            "col": self.col,
            "snippet": self.snippet,
            "seed": self.seed,
        }


def field_to_label(field: str) -> str:
    """Map canonical field key to human-readable label."""
    field_strip = field.strip()
    field_lower = field_strip.lower()

    if field_lower == "questionvariables":
        return "Question variables"
    if field_lower == "questiontext":
        return "Question text"
    if field_lower == "generalfeedback":
        return "General feedback"
    if field_lower == "specificfeedback":
        return "Specific feedback"
    if field_lower == "questionnote":
        return "Question note"
    if field_lower == "xml":
        return "Question XML"

    # PRT feedbackvariables: prt:<name>:feedbackvariables
    m_fv = re.match(r"^prt:([^:]+):feedbackvariables$", field_strip, re.IGNORECASE)
    if m_fv:
        return f"PRT {m_fv.group(1)} · Feedback variables"

    # PRT node: prt:<name>:node:<n>:<subf>
    m_node = re.match(r"^prt:([^:]+):node:([^:]+):([^:]+)$", field_strip, re.IGNORECASE)
    if m_node:
        prt_name, node_name, subf = m_node.groups()
        return f"PRT {prt_name} · Node {node_name} ({subf})"

    # PRT: prt:<name>
    m_prt = re.match(r"^prt:([^:]+)$", field_strip, re.IGNORECASE)
    if m_prt:
        return f"PRT {m_prt.group(1)}"

    return "Maxima CAS"


def build_code_snippet(
    source_text: str,
    line: int | None = None,
    col: int | None = None,
    highlight_substr: str | None = None,
) -> str | None:
    """Build a source-line + caret snippet from field source text.

    Example output:
      2 | b: 0;
    > 3 | c: 1 + ;
        |        ^
    """
    if not source_text:
        return highlight_substr if highlight_substr else None

    lines = source_text.splitlines()
    if not lines:
        return highlight_substr if highlight_substr else None

    # If line is None, try to locate highlight_substr in source_text
    if line is None and highlight_substr:
        clean_needle = highlight_substr.strip()
        pos = source_text.find(clean_needle)
        if pos == -1 and not clean_needle.startswith("{@"):
            pos = source_text.find(f"{{@{clean_needle}")
            if pos == -1:
                pos = source_text.find(f"{{@ {clean_needle}")
        if pos != -1:
            line = source_text[:pos].count("\n") + 1
            last_nl = source_text.rfind("\n", 0, pos)
            col = (pos - last_nl) if last_nl != -1 else (pos + 1)

    if line is None or line < 1 or line > len(lines):
        return highlight_substr if highlight_substr else None

    target_line = lines[line - 1]
    context_above = lines[line - 2] if line > 1 else None
    context_below = lines[line] if line < len(lines) else None

    max_line_num = line + (1 if context_below is not None else 0)
    width = len(str(max_line_num))

    output_lines: list[str] = []
    if context_above is not None:
        output_lines.append(f"  {line - 1:>{width}} | {context_above}")

    output_lines.append(f"> {line:>{width}} | {target_line}")

    if col is not None and col >= 1:
        clamped_col = min(col, len(target_line) + 1)
        caret_indent = " " * (clamped_col - 1)
        output_lines.append(f"  {' ' * width} | {caret_indent}^")

    if context_below is not None:
        output_lines.append(f"  {line + 1:>{width}} | {context_below}")

    return "\n".join(output_lines)


def _clean_error_message(text: str) -> tuple[str, int | None, int | None, str | None]:
    """Clean a STACK CAS error message.

    Extracts:
    - (line, col) from '(At about line L character C.)'
    - highlight_substr from '<span class="stacksyntaxexample">...</span>'
    - comparts verbose 35-token Maxima parser errors
    - strips HTML markup and unescapes entities
    """
    msg = text.strip()
    line: int | None = None
    col: int | None = None
    highlight_substr: str | None = None

    # 1. Extract position: (At about line L character C.)
    m_pos = re.search(r"\(At about line\s+(\d+)\s+character\s+(\d+)\.?\)", msg, re.IGNORECASE)
    if m_pos:
        line = int(m_pos.group(1))
        col = int(m_pos.group(2))
        msg = re.sub(r"\s*\(At about line\s+\d+\s+character\s+\d+\.?\)", "", msg, flags=re.IGNORECASE)

    # 2. Extract syntax example: <span class="stacksyntaxexample">...</span>
    m_span = re.search(r'<span class="stacksyntaxexample">(.*?)</span>', msg, re.IGNORECASE | re.DOTALL)
    if m_span:
        raw_ex = m_span.group(1)
        highlight_substr = html.unescape(raw_ex).strip()
        msg = re.sub(r'<span class="stacksyntaxexample">.*?</span>', f"`{highlight_substr}`", msg, flags=re.IGNORECASE | re.DOTALL)

    # 3. Strip remaining HTML tags
    if "<" in msg and ">" in msg:
        msg = re.sub(r"<[^>]+>", "", msg)

    # 4. Unescape HTML entities
    msg = html.unescape(msg).strip()

    # 5. Compact verbose Maxima parser grammar list:
    # Expected "#pm#", "%not ", ... but "<tok>" found.
    m_expected = re.match(
        r"^Expected\s+(.+?)\s+but\s+[\"']?([^\"'\s]+)[\"']?\s+found\.?$",
        msg,
        re.IGNORECASE | re.DOTALL,
    )
    if m_expected:
        token_list_raw = m_expected.group(1)
        found_tok = m_expected.group(2)
        tokens = [t.strip() for t in token_list_raw.split(",") if t.strip()]
        if len(tokens) > 4:
            msg = f"Syntax error: unexpected {found_tok} (incomplete or malformed Maxima expression)."

    return msg, line, col, highlight_substr


def parse_and_enrich_cas_errors(
    raw_errors: list[str] | str | None,
    xml_str: str = "",
    probed_errors: list[dict[str, Any]] | None = None,
    seed: int | None = None,
    default_field: str = "cas",
) -> list[CasDiagnostic]:
    """Parse, deduplicate, and enrich STACK CAS error messages into structured CasDiagnostics."""
    fields = extract_question_fields(xml_str) if xml_str else {}
    diagnostics: list[CasDiagnostic] = []

    has_specific_probed = False

    # 1. Process PHP probed errors first
    if probed_errors:
        for pe in probed_errors:
            if not isinstance(pe, dict):
                continue
            p_field = str(pe.get("field") or default_field).strip()
            p_msg_raw = str(pe.get("message") or "").strip()
            if not p_msg_raw:
                continue

            clean_msg, line, col, highlight = _clean_error_message(p_msg_raw)
            # Override line/col if explicitly provided in dict
            if pe.get("line") is not None:
                try:
                    line = int(pe["line"])
                except (ValueError, TypeError):
                    pass
            if pe.get("col") is not None:
                try:
                    col = int(pe["col"])
                except (ValueError, TypeError):
                    pass

            snippet = build_code_snippet(
                fields.get(p_field, ""),
                line=line,
                col=col,
                highlight_substr=highlight,
            )

            diagnostics.append(CasDiagnostic(
                field=p_field,
                label=field_to_label(p_field),
                message=clean_msg,
                line=line,
                col=col,
                snippet=snippet,
                seed=seed,
            ))
            has_specific_probed = True

    # 2. Process raw_errors
    error_list: list[str] = []
    if isinstance(raw_errors, str):
        error_list = [raw_errors]
    elif isinstance(raw_errors, list):
        error_list = [str(e) for e in raw_errors if e]

    for err_item in error_list:
        if not err_item.strip():
            continue

        # If we have specific probed errors, drop generic wrappers
        if has_specific_probed:
            if any(pat.search(err_item.strip()) for pat in OPAQUE_WRAPPER_PATTERNS):
                continue

        # Check STACK doubled runtime format:
        # e.g. "Division by zero.\nThe field \"\"Question variables\"\" generated the following error: Division by zero."
        m_doubled = re.search(
            r'The field\s+(?:""|\'|")(?P<f>[^"\'\n]+)(?:""|\'|")\s+generated the following error:\s*(?P<m>.+)',
            err_item,
            re.IGNORECASE | re.DOTALL,
        )
        if m_doubled:
            prose_field = m_doubled.group("f").strip()
            field_key = PROSE_FIELD_MAP.get(prose_field.lower(), default_field)
            clean_msg, line, col, highlight = _clean_error_message(m_doubled.group("m"))
            snippet = build_code_snippet(
                fields.get(field_key, ""),
                line=line,
                col=col,
                highlight_substr=highlight,
            )
            diagnostics.append(CasDiagnostic(
                field=field_key,
                label=field_to_label(field_key),
                message=clean_msg,
                line=line,
                col=col,
                snippet=snippet,
                seed=seed,
            ))
            continue

        # Check STACK compilation prefixes:
        # e.g. "Error(s) in question-variables: ..."
        m_prefix = re.match(
            r"^Error(?:\(s\)|s)?\s+in\s+([a-zA-Z0-9_\-]+)\s*:\s*(.*)$",
            err_item.strip(),
            re.IGNORECASE | re.DOTALL,
        )
        if m_prefix:
            prose_field = m_prefix.group(1).strip()
            field_key = PROSE_FIELD_MAP.get(prose_field.lower(), default_field)
            clean_msg, line, col, highlight = _clean_error_message(m_prefix.group(2))
            snippet = build_code_snippet(
                fields.get(field_key, ""),
                line=line,
                col=col,
                highlight_substr=highlight,
            )
            diagnostics.append(CasDiagnostic(
                field=field_key,
                label=field_to_label(field_key),
                message=clean_msg,
                line=line,
                col=col,
                snippet=snippet,
                seed=seed,
            ))
            continue

        # Split multiple lines if present
        sub_lines = [l.strip() for l in err_item.split("\n") if l.strip()]
        for line_str in sub_lines:
            if has_specific_probed and any(pat.search(line_str) for pat in OPAQUE_WRAPPER_PATTERNS):
                continue

            clean_msg, line, col, highlight = _clean_error_message(line_str)
            snippet = build_code_snippet(
                fields.get(default_field, ""),
                line=line,
                col=col,
                highlight_substr=highlight,
            )
            diagnostics.append(CasDiagnostic(
                field=default_field,
                label=field_to_label(default_field),
                message=clean_msg,
                line=line,
                col=col,
                snippet=snippet,
                seed=seed,
            ))

    # 3. Deduplicate while preserving order
    deduped: list[CasDiagnostic] = []
    seen: set[tuple[str, str, int | None, int | None]] = set()
    for d in diagnostics:
        key = (d.field, d.message, d.line, d.col)
        if key not in seen:
            seen.add(key)
            deduped.append(d)

    return deduped
