"""Static linter for Moodle STACK questions.

Checks XML schema validity, CASText delimiters, input/validation/feedback placeholders,
PRT directed node graph integrity, and randomization/testing hygiene.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from lxml import etree


@dataclass
class LintIssue:
    """A single diagnostic issue found by the linter."""
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    field: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "field": self.field,
        }


def _extract_element_text(elem: etree._Element | None) -> str:
    """Extract full string content from an element, handling CDATA, plain text, and nested markup."""
    if elem is None:
        return ""
    if len(elem) > 0:
        return (elem.text or "") + "".join(etree.tostring(c, encoding="unicode") for c in elem)
    return elem.text or ""


def _check_castext_delimiters(text: str, field_name: str) -> list[LintIssue]:
    """Inspect text for CASText syntax errors, unbalanced delimiters, and missing braces/ats."""
    issues: list[LintIssue] = []
    if not text:
        return issues

    # 1. Detect orphan closing @... @} where opening brace is missing (e.g. "@ta1@}")
    # Regex looks for @ followed by an identifier or expression and closing @}, not preceded by {
    for m in re.finditer(r"(?<!\{)(@[a-zA-Z0-9_().+\-*/\s]+?@\})", text):
        issues.append(LintIssue(
            severity="error",
            code="castext-orphan-close",
            message=f"Orphan closing delimiter with missing opening brace '{{': {m.group(1)!r}",
            field=field_name,
        ))

    # 2. Detect {@ ... } where @ is missing before closing brace (e.g. "{@expr}")
    # Matches {@ followed by characters not containing @ and ending with } without @
    for m in re.finditer(r"\{@([^@]*?)\}(?!@)", text):
        issues.append(LintIssue(
            severity="error",
            code="castext-missing-at",
            message=f"CASText delimiter has missing '@' before closing brace '}}': {m.group(0)!r}",
            field=field_name,
        ))

    # 3. Strip all valid balanced {@ ... @} and {# ... #} blocks
    clean = re.sub(r"\{@.*?@\}", "", text, flags=re.DOTALL)
    clean = re.sub(r"\{#.*?#\}", "", clean, flags=re.DOTALL)

    # 4. Check for unclosed opening tags or stray closing tags in remaining text
    if "{@" in clean and not any(i.code == "castext-missing-at" for i in issues):
        issues.append(LintIssue(
            severity="error",
            code="castext-unclosed-delimiter",
            message="Unclosed opening delimiter '{@' without matching '@}'",
            field=field_name,
        ))
    if "{#" in clean:
        issues.append(LintIssue(
            severity="error",
            code="castext-unclosed-delimiter",
            message="Unclosed opening delimiter '{#' without matching '#}'",
            field=field_name,
        ))
    if "@}" in clean and not any(i.code == "castext-orphan-close" for i in issues):
        issues.append(LintIssue(
            severity="error",
            code="castext-stray-delimiter",
            message="Stray closing delimiter '@}' without matching '{@'",
            field=field_name,
        ))
    if "#}" in clean:
        issues.append(LintIssue(
            severity="error",
            code="castext-stray-delimiter",
            message="Stray closing delimiter '#}' without matching '{#'",
            field=field_name,
        ))

    return issues


def lint_question(xml_path_or_str: Path | str) -> list[LintIssue]:
    """Perform comprehensive static analysis on a STACK question XML."""
    issues: list[LintIssue] = []

    # 1. XML parseability check
    parser = etree.XMLParser(strip_cdata=False, recover=False)
    try:
        if isinstance(xml_path_or_str, Path) or (
            isinstance(xml_path_or_str, str)
            and not xml_path_or_str.strip().startswith("<")
            and Path(xml_path_or_str).is_file()
        ):
            tree = etree.parse(str(xml_path_or_str), parser)
            root = tree.getroot()
        else:
            raw_bytes = xml_path_or_str.encode("utf-8") if isinstance(xml_path_or_str, str) else xml_path_or_str
            root = etree.fromstring(raw_bytes, parser)
    except Exception as err:
        return [
            LintIssue(
                severity="error",
                code="xml-syntax-error",
                message=f"Failed to parse XML: {err}",
            )
        ]

    # 2. Check for question elements
    stacks = root.findall(".//question[@type='stack']")
    if not stacks and root.tag == "question" and root.get("type") == "stack":
        stacks = [root]

    if not stacks:
        return [
            LintIssue(
                severity="error",
                code="missing-stack-question",
                message="No <question type='stack'> element found in XML",
            )
        ]

    if len(stacks) > 1:
        issues.append(
            LintIssue(
                severity="warning",
                code="multiple-stack-questions",
                message=f"Found {len(stacks)} stack questions, expected exactly 1 per file",
            )
        )

    q = stacks[0]

    # 3. Check name and idnumber
    name = (q.findtext("./name/text") or q.findtext("./name") or "").strip()
    if not name:
        issues.append(
            LintIssue(
                severity="error",
                code="missing-name",
                message="Question <name> is missing or empty",
                field="name",
            )
        )

    idnumber = (q.findtext("./idnumber") or "").strip()
    if not idnumber:
        issues.append(
            LintIssue(
                severity="warning",
                code="missing-idnumber",
                message="Question <idnumber> is missing or empty",
                field="idnumber",
            )
        )

    # 4. Check CASText delimiters across all CASText fields
    castext_fields = [
        ("questiontext", _extract_element_text(q.find("./questiontext/text"))),
        ("generalfeedback", _extract_element_text(q.find("./generalfeedback/text"))),
        ("specificfeedback", _extract_element_text(q.find("./specificfeedback/text"))),
        ("questionnote", _extract_element_text(q.find("./questionnote/text"))),
        ("questiondescription", _extract_element_text(q.find("./questiondescription/text"))),
        ("prtcorrect", _extract_element_text(q.find("./prtcorrect/text"))),
        ("prtpartiallycorrect", _extract_element_text(q.find("./prtpartiallycorrect/text"))),
        ("prtincorrect", _extract_element_text(q.find("./prtincorrect/text"))),
    ]

    for field_name, field_val in castext_fields:
        issues.extend(_check_castext_delimiters(field_val, field_name))

    for prt in q.findall("./prt"):
        prt_name = (prt.findtext("./name") or "unknown").strip()
        for node in prt.findall("./node"):
            node_name = (node.findtext("./name") or "0").strip()
            true_fb = _extract_element_text(node.find("./truefeedback/text"))
            false_fb = _extract_element_text(node.find("./falsefeedback/text"))
            issues.extend(_check_castext_delimiters(true_fb, f"prt:{prt_name}:node:{node_name}:truefeedback"))
            issues.extend(_check_castext_delimiters(false_fb, f"prt:{prt_name}:node:{node_name}:falsefeedback"))

    for idx, hint in enumerate(q.findall("./hint")):
        hint_text = _extract_element_text(hint.find("./text"))
        issues.extend(_check_castext_delimiters(hint_text, f"hint:{idx}"))

    # 5. Input and Validation placeholder checks
    qtext = _extract_element_text(q.find("./questiontext/text"))
    inputs_in_qtext = set(re.findall(r"\[\[input:([a-zA-Z0-9_]+)\]\]", qtext))
    validations_in_qtext = set(re.findall(r"\[\[validation:([a-zA-Z0-9_]+)\]\]", qtext))

    defined_inputs: dict[str, etree._Element] = {}
    for inp in q.findall("./input"):
        inp_name = (inp.findtext("./name") or inp.get("name") or "").strip()
        if inp_name:
            defined_inputs[inp_name] = inp

    # Undefined input referenced in questiontext
    for inp_ref in sorted((inputs_in_qtext | validations_in_qtext) - set(defined_inputs.keys())):
        issues.append(
            LintIssue(
                severity="error",
                code="undefined-input",
                message=f"Input '{inp_ref}' is referenced in questiontext but not defined in <input>",
                field="questiontext",
            )
        )

    # Defined input never placed in questiontext
    for inp_name in sorted(set(defined_inputs.keys()) - inputs_in_qtext):
        issues.append(
            LintIssue(
                severity="warning",
                code="unused-input",
                message=f"Input '{inp_name}' is defined in <input> but never placed in questiontext via [[input:{inp_name}]]",
                field="input",
            )
        )

    # Missing [[validation:X]] when showvalidation is active
    for inp_name, inp_elem in defined_inputs.items():
        if inp_name in inputs_in_qtext:
            showval = (inp_elem.findtext("./showvalidation") or "1").strip()
            if showval != "0" and inp_name not in validations_in_qtext:
                issues.append(
                    LintIssue(
                        severity="warning",
                        code="missing-validation",
                        message=f"Input '{inp_name}' has showvalidation enabled but [[validation:{inp_name}]] is missing in questiontext",
                        field="questiontext",
                    )
                )

    # 6. Feedback placeholder checks
    specfb = _extract_element_text(q.find("./specificfeedback/text"))
    feedbacks_in_text = set(re.findall(r"\[\[feedback:([a-zA-Z0-9_]+)\]\]", specfb + " " + qtext))
    defined_prts: set[str] = {
        (prt.findtext("./name") or prt.get("name") or "").strip()
        for prt in q.findall("./prt")
        if (prt.findtext("./name") or prt.get("name") or "").strip()
    }

    # Undefined PRT referenced
    for prt_ref in sorted(feedbacks_in_text - defined_prts):
        issues.append(
            LintIssue(
                severity="error",
                code="undefined-prt",
                message=f"PRT '{prt_ref}' is referenced in [[feedback:{prt_ref}]] but not defined in <prt>",
                field="specificfeedback",
            )
        )

    # Defined PRT has no feedback placeholder
    for prt_name in sorted(defined_prts - feedbacks_in_text):
        issues.append(
            LintIssue(
                severity="warning",
                code="unused-prt",
                message=f"PRT '{prt_name}' is defined in <prt> but has no [[feedback:{prt_name}]] placeholder in specificfeedback or questiontext",
                field="specificfeedback",
            )
        )

    # 7. PRT Node Graph integrity checks
    for prt in q.findall("./prt"):
        prt_name = (prt.findtext("./name") or "unknown").strip()
        nodes = prt.findall("./node")
        if not nodes:
            issues.append(
                LintIssue(
                    severity="error",
                    code="empty-prt",
                    message=f"PRT '{prt_name}' has no <node> elements",
                    field=f"prt:{prt_name}",
                )
            )
            continue

        node_names = [(node.findtext("./name") or "").strip() for node in nodes]
        node_names_set = set(node_names)
        adj: dict[str, list[str]] = {n: [] for n in node_names if n}

        for node in nodes:
            n_name = (node.findtext("./name") or "").strip()
            truenext = (node.findtext("./truenextnode") or "-1").strip()
            falsenext = (node.findtext("./falsenextnode") or "-1").strip()

            if truenext != "-1":
                if truenext not in node_names_set:
                    issues.append(
                        LintIssue(
                            severity="error",
                            code="invalid-next-node",
                            message=f"PRT '{prt_name}' node '{n_name}' truenextnode points to non-existent node '{truenext}'",
                            field=f"prt:{prt_name}",
                        )
                    )
                else:
                    adj[n_name].append(truenext)

            if falsenext != "-1":
                if falsenext not in node_names_set:
                    issues.append(
                        LintIssue(
                            severity="error",
                            code="invalid-next-node",
                            message=f"PRT '{prt_name}' node '{n_name}' falsenextnode points to non-existent node '{falsenext}'",
                            field=f"prt:{prt_name}",
                        )
                    )
                else:
                    adj[n_name].append(falsenext)

        # Directed graph cycle detection (DFS with coloring)
        visited: dict[str, int] = {}  # 0: visiting, 1: visited
        has_cycle = False

        def dfs_cycle(u: str) -> bool:
            visited[u] = 0
            for v in adj.get(u, []):
                if visited.get(v) == 0:
                    return True
                elif v not in visited:
                    if dfs_cycle(v):
                        return True
            visited[u] = 1
            return False

        for n in node_names:
            if n and n not in visited:
                if dfs_cycle(n):
                    has_cycle = True
                    break

        if has_cycle:
            issues.append(
                LintIssue(
                    severity="error",
                    code="prt-cycle",
                    message=f"PRT '{prt_name}' contains a cycle in its node transition graph",
                    field=f"prt:{prt_name}",
                )
            )

        # Reachability from root node (first node in XML)
        root_node = node_names[0] if node_names else None
        if root_node:
            reachable: set[str] = set()
            stack = [root_node]
            while stack:
                curr = stack.pop()
                if curr not in reachable:
                    reachable.add(curr)
                    stack.extend(adj.get(curr, []))

            unreachable = node_names_set - reachable
            for unreach_node in sorted(unreachable):
                issues.append(
                    LintIssue(
                        severity="warning",
                        code="unreachable-node",
                        message=f"PRT '{prt_name}' node '{unreach_node}' is unreachable from root node '{root_node}'",
                        field=f"prt:{prt_name}",
                    )
                )

    # 8. Randomization and Question Test checks
    qvars = _extract_element_text(q.find("./questionvariables/text"))
    uses_rand = bool(re.search(r"\brand(?:_[a-z_]+)?\s*\(", qvars))
    qnote = _extract_element_text(q.find("./questionnote/text")).strip()

    if uses_rand and not qnote:
        issues.append(
            LintIssue(
                severity="error",
                code="missing-question-note",
                message="Question uses randomization (rand*) but has an empty <questionnote>. STACK requires a question note to deploy variants.",
                field="questionnote",
            )
        )

    seeds = q.findall("./deployedseed")
    if uses_rand and len(seeds) == 0:
        issues.append(
            LintIssue(
                severity="warning",
                code="missing-deployed-seeds",
                message="Question uses randomization but has no deployed seeds",
                field="deployedseed",
            )
        )

    qtests = q.findall("./qtest")
    if len(qtests) == 0:
        issues.append(
            LintIssue(
                severity="info",
                code="no-qtests",
                message="Question has no question tests (<qtest>)",
                field="qtest",
            )
        )

    return issues
