"""Tests for STACK reference catalog (`macstack ref`) and answer-test lint rules."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest
from typer.testing import CliRunner

from macstack.cli import app
from macstack.linter import lint_question
from macstack.ref import (
    ANSWER_TEST_ALIASES,
    ANSWER_TEST_BY_NAME,
    ANSWER_TEST_CATEGORIES,
    ANSWER_TEST_SPECS,
    ANSWER_TESTS,
    AnswerTestSpec,
)


runner = CliRunner()


# =========================================================================== #
# 1. Programmatic Catalog Integrity & PHP Controller Parity
# =========================================================================== #


def test_answer_tests_count_and_spec_integrity() -> None:
    """ANSWER_TEST_SPECS must have exactly 41 STACK v4.11 answer tests."""
    assert len(ANSWER_TESTS) == 41
    assert len(ANSWER_TEST_SPECS) == 41
    assert len(ANSWER_TEST_BY_NAME) == 41

    raw_sans_tests = {s.name for s in ANSWER_TEST_SPECS if s.requires_raw_sans}
    assert raw_sans_tests == {"SigFigsStrict", "NumSigFigs", "NumDecPlaces", "Units", "UnitsStrict"}

    ignores_tans_tests = {s.name for s in ANSWER_TEST_SPECS if s.ignores_tans}
    assert ignores_tans_tests == {"LowestTerms", "Expanded", "SigFigsStrict", "Validator"}

    for spec in ANSWER_TEST_SPECS:
        assert spec.name in ANSWER_TESTS
        assert spec.moodle_label
        assert spec.category in ANSWER_TEST_CATEGORIES
        assert spec.options_status in ("required", "optional", "none")
        if spec.options_status != "none":
            assert spec.options_syntax, f"{spec.name} missing options_syntax"
        assert spec.summary
        assert spec.sketch_example
        assert len(spec.gotchas) > 0


def test_answer_tests_match_php_controller() -> None:
    """Compare ANSWER_TESTS and raw_sans flags with local STACK PHP controller if present."""
    php_path = Path("/Users/rgbrown/.local/share/macstack/qtype_stack/stack/answertest/controller.class.php")
    if not php_path.exists():
        pytest.skip(f"STACK controller.class.php not found at {php_path}")

    content = php_path.read_text(encoding="utf-8")

    # Match static $types = [ 'AlgEquiv' => ..., ... ];
    types_match = re.search(r"protected\s+static\s+\$types\s*=\s*\[(.*?)\];", content, re.DOTALL)
    assert types_match is not None, "Could not find $types in controller.class.php"
    php_types = set(re.findall(r"'([A-Za-z0-9_-]+)'\s*=>", types_match.group(1)))

    assert ANSWER_TESTS == php_types, f"Mismatch with PHP controller: {ANSWER_TESTS ^ php_types}"

    # Match static $pops = [ 'AlgEquiv' => [..., ..., ..., false], ... ];
    pops_match = re.search(r"protected\s+static\s+\$pops\s*=\s*\[(.*?)\];", content, re.DOTALL)
    assert pops_match is not None, "Could not find $pops in controller.class.php"

    raw_sans_php = set()
    for line in pops_match.group(1).splitlines():
        m = re.search(r"'([A-Za-z0-9_-]+)'\s*=>\s*\[([^]]+)\]", line)
        if m:
            tname = m.group(1)
            parts = [p.strip() for p in m.group(2).split(",")]
            if len(parts) >= 4 and parts[3] == "true":
                raw_sans_php.add(tname)

    raw_sans_specs = {s.name for s in ANSWER_TEST_SPECS if s.requires_raw_sans}
    assert raw_sans_specs == raw_sans_php


# =========================================================================== #
# 2. CLI `macstack ref` Tests
# =========================================================================== #


def test_cli_ref_empty_args_overview() -> None:
    """macstack ref with no args displays minimal skeleton and quick navigation."""
    res = runner.invoke(app, ["ref"])
    assert res.exit_code == 0
    assert "Minimal STACK Sketch" in res.stdout
    assert "Quick Navigation" in res.stdout
    assert "macstack ref prt" in res.stdout
    assert "macstack ref tests" in res.stdout


def test_cli_ref_prt() -> None:
    """macstack ref prt displays node grammar, branch tokens, feedbackstyle and examples."""
    res = runner.invoke(app, ["ref", "prt"])
    assert res.exit_code == 0
    assert "PRT (Potential Response Tree)" in res.stdout
    assert "Branch Modifiers & Tokens" in res.stdout
    assert "feedbackstyle Setting Codes" in res.stdout
    assert "Pattern 1: Form check" in res.stdout


def test_cli_ref_tests_all() -> None:
    """macstack ref tests lists all 41 answer tests."""
    res = runner.invoke(app, ["ref", "tests"])
    assert res.exit_code == 0
    assert "All STACK Answer Tests" in res.stdout
    assert "AlgEquiv" in res.stdout
    assert "Antidiff" in res.stdout
    assert "AddConst" in res.stdout
    assert "NumSigFigs" in res.stdout


def test_cli_ref_tests_category_filter() -> None:
    """macstack ref tests calculus filters specifically to calculus tests."""
    res = runner.invoke(app, ["ref", "tests", "calculus"])
    assert res.exit_code == 0
    assert "STACK Answer Tests: Calculus" in res.stdout
    assert "Diff" in res.stdout
    assert "Int" in res.stdout
    assert "Antidiff" in res.stdout
    assert "AddConst" in res.stdout
    assert "AlgEquiv" not in res.stdout


def test_cli_ref_category_direct() -> None:
    """macstack ref calculus displays the calculus tests table directly."""
    res = runner.invoke(app, ["ref", "calculus"])
    assert res.exit_code == 0
    assert "STACK Answer Tests: Calculus" in res.stdout
    assert "Diff" in res.stdout
    assert "Antidiff" in res.stdout


def test_cli_ref_test_exact_card() -> None:
    """macstack ref Int displays detailed panel with gotchas and example."""
    res = runner.invoke(app, ["ref", "Int"])
    assert res.exit_code == 0
    assert "Answer Test: Int" in res.stdout
    assert "Category: calculus" in res.stdout
    assert "Options: Required" in res.stdout
    assert "Gotchas & Authoring Caveats" in res.stdout
    assert "node 0: Int" in res.stdout


def test_cli_ref_test_alias_completed_square() -> None:
    """macstack ref CompletedSquare resolves to CompSquare detailed card."""
    res = runner.invoke(app, ["ref", "CompletedSquare"])
    assert res.exit_code == 0
    assert "Answer Test: CompSquare" in res.stdout
    assert "CompletedSquare" in res.stdout
    assert "node 0: CompSquare" in res.stdout


def test_cli_ref_test_alias_num_gt() -> None:
    """macstack ref num-gt resolves to GT detailed card."""
    res = runner.invoke(app, ["ref", "num-gt"])
    assert res.exit_code == 0
    assert "Answer Test: GT" in res.stdout
    assert "Num-GT" in res.stdout


def test_cli_ref_inputs() -> None:
    """macstack ref inputs displays input types and coded integer tables."""
    res = runner.invoke(app, ["ref", "inputs"])
    assert res.exit_code == 0
    assert "Input Types" in res.stdout
    assert "algebraic" in res.stdout
    assert "MCQ tans Tuple Format" in res.stdout
    assert "insertstars" in res.stdout
    assert "showvalidation" in res.stdout


def test_cli_ref_frontmatter() -> None:
    """macstack ref frontmatter displays question settings and display options."""
    res = runner.invoke(app, ["ref", "frontmatter"])
    assert res.exit_code == 0
    assert "Question Front Matter Settings" in res.stdout
    assert "multiplicationsign" in res.stdout
    assert "inversetrig" in res.stdout


def test_cli_ref_castext() -> None:
    """macstack ref castext displays CASText2 delimiters and HTML sections."""
    res = runner.invoke(app, ["ref", "castext"])
    assert res.exit_code == 0
    assert "CASText2 Delimiters" in res.stdout
    assert "{@expr@}" in res.stdout
    assert "[[input:ans1]]" in res.stdout
    assert "## Question text" in res.stdout


def test_cli_ref_keyword_search() -> None:
    """macstack ref sigfigs matches multiple tests and prints matching table."""
    res = runner.invoke(app, ["ref", "sigfigs"])
    assert res.exit_code == 0
    assert "Answer Tests Matching 'sigfigs'" in res.stdout
    assert "NumSigFigs" in res.stdout
    assert "SigFigsStrict" in res.stdout


def test_cli_ref_json_overview_and_single() -> None:
    """macstack ref --json outputs clean valid JSON."""
    res_all = runner.invoke(app, ["ref", "--json"])
    assert res_all.exit_code == 0
    data_all = json.loads(res_all.stdout)
    assert "answer_tests" in data_all
    assert len(data_all["answer_tests"]) == 41

    res_single = runner.invoke(app, ["ref", "Int", "--json"])
    assert res_single.exit_code == 0
    data_single = json.loads(res_single.stdout)
    assert data_single["name"] == "Int"
    assert data_single["category"] == "calculus"
    assert data_single["options_status"] == "required"


def test_cli_ref_unknown_query_exits_one() -> None:
    """macstack ref with an unrecognized topic/test exits with code 1."""
    res = runner.invoke(app, ["ref", "totallyUnknownTopicXYZ"])
    assert res.exit_code == 1
    assert "Unknown reference topic or answer test" in res.stdout


# =========================================================================== #
# 3. Static Linter Answer Test Checks
# =========================================================================== #


def _make_question_xml(
    answertest: str,
    sans: str = "ans1",
    tans: str = "ta1",
    testoptions: str = "",
    extra_nodes: str = "",
    has_input: bool = True,
) -> str:
    input_block = """<input>
    <name>ans1</name>
    <type>algebraic</type>
    <tans>ta1</tans>
    <boxsize>15</boxsize>
    <strict_syntax>1</strict_syntax>
    <insertstars>0</insertstars>
    <syntaxhint></syntaxhint>
    <syntaxattribute>0</syntaxattribute>
    <forbidwords></forbidwords>
    <allowwords></allowwords>
    <forbidfloat>1</forbidfloat>
    <requirelowestterms>0</requirelowestterms>
    <checkanswertype>0</checkanswertype>
    <mustverify>1</mustverify>
    <showvalidation>1</showvalidation>
    <options></options>
  </input>""" if has_input else ""

    return f"""<?xml version="1.0" encoding="utf-8"?>
<quiz>
<question type="stack">
  <name><text>Test Question</text></name>
  <questiontext format="html"><text><![CDATA[Prompt: [[input:ans1]] [[validation:ans1]]]]></text></questiontext>
  <generalfeedback format="html"><text></text></generalfeedback>
  <defaultgrade>1.0</defaultgrade>
  <penalty>0.1</penalty>
  <hidden>0</hidden>
  <specificfeedback format="html"><text><![CDATA[[[feedback:prt1]]]]></text></specificfeedback>
  <questionnote><text>Note</text></questionnote>
  <questionvariables><text>ta1: 5;</text></questionvariables>
  {input_block}
  <prt>
    <name>prt1</name>
    <value>1.0</value>
    <autosimplify>1</autosimplify>
    <feedbackstyle>1</feedbackstyle>
    <feedbackvariables><text></text></feedbackvariables>
    <node>
      <name>0</name>
      <answertest>{answertest}</answertest>
      <sans>{sans}</sans>
      <tans>{tans}</tans>
      <testoptions>{testoptions}</testoptions>
      <quiet>0</quiet>
      <truescoremode>=</truescoremode>
      <truescore>1.0</truescore>
      <truepenalty>0.0</truepenalty>
      <truenextnode>-1</truenextnode>
      <trueanswernote>prt1-0-T</trueanswernote>
      <truefeedback format="html"><text></text></truefeedback>
      <falsescoremode>=</falsescoremode>
      <falsescore>0.0</falsescore>
      <falsepenalty>0.0</falsepenalty>
      <falsenextnode>-1</falsenextnode>
      <falseanswernote>prt1-0-F</falseanswernote>
      <falsefeedback format="html"><text></text></falsefeedback>
    </node>
    {extra_nodes}
  </prt>
  <qtest><testcase>1</testcase><testinput><name>ans1</name><value>ta1</value></testinput><expected><name>prt1</name><expectedscore>1.0</expectedscore><expectedpenalty>0.0</expectedpenalty><expectedanswernote>prt1-0-T</expectedanswernote></expected></qtest>
</question>
</quiz>"""


def test_lint_missing_test_options() -> None:
    """Error when a test requiring options (like Diff or FacForm) is missing testoptions."""
    xml = _make_question_xml("Diff", testoptions="")
    issues = lint_question(xml)
    missing_opts = [i for i in issues if i.code == "missing-test-options"]
    assert len(missing_opts) == 1
    assert missing_opts[0].severity == "error"
    assert "PRT 'prt1' node '0' uses 'Diff', which requires testoptions" in missing_opts[0].message
    assert missing_opts[0].field == "prt:prt1:node:0"


def test_lint_unexpected_test_options() -> None:
    """Warning when a test taking no options (like AlgEquiv) is given testoptions."""
    xml = _make_question_xml("AlgEquiv", testoptions="x")
    issues = lint_question(xml)
    unexpected = [i for i in issues if i.code == "unexpected-test-options"]
    assert len(unexpected) == 1
    assert unexpected[0].severity == "warning"
    assert "passes testoptions 'x' to 'AlgEquiv', which does not accept options" in unexpected[0].message
    assert unexpected[0].field == "prt:prt1:node:0"


def test_lint_raw_input_required() -> None:
    """Warning when raw sans test (NumSigFigs) gets an expression rather than raw input variable."""
    # Expression instead of bare input
    xml_expr = _make_question_xml("NumSigFigs", sans="ans1 + 1", testoptions="3")
    issues = lint_question(xml_expr)
    raw_issues = [i for i in issues if i.code == "raw-input-required"]
    assert len(raw_issues) == 1
    assert raw_issues[0].severity == "warning"
    assert "requires a raw input variable in <sans> (got 'ans1 + 1')" in raw_issues[0].message

    # Bare input passes cleanly
    xml_valid = _make_question_xml("NumSigFigs", sans="ans1", testoptions="3")
    issues_valid = lint_question(xml_valid)
    assert not any(i.code == "raw-input-required" for i in issues_valid)


def test_lint_tans_ignored_single_node() -> None:
    """Warning when single-node PRT uses a test that ignores tans (e.g. Expanded, LowestTerms)."""
    # Single node with LowestTerms
    xml_single = _make_question_xml("LowestTerms")
    issues = lint_question(xml_single)
    ignored = [i for i in issues if i.code == "tans-ignored-single-node"]
    assert len(ignored) == 1
    assert ignored[0].severity == "warning"
    assert "only runs 'LowestTerms', which ignores <tans>" in ignored[0].message

    # Multi-node PRT paired with AlgEquiv passes cleanly
    extra = """<node>
      <name>1</name>
      <answertest>AlgEquiv</answertest>
      <sans>ans1</sans>
      <tans>ta1</tans>
      <testoptions></testoptions>
      <quiet>0</quiet>
      <truescoremode>=</truescoremode>
      <truescore>1.0</truescore>
      <truepenalty>0.0</truepenalty>
      <truenextnode>-1</truenextnode>
      <trueanswernote>prt1-1-T</trueanswernote>
      <truefeedback format="html"><text></text></truefeedback>
      <falsescoremode>=</falsescoremode>
      <falsescore>0.0</falsescore>
      <falsepenalty>0.0</falsepenalty>
      <falsenextnode>-1</falsenextnode>
      <falseanswernote>prt1-1-F</falseanswernote>
      <falsefeedback format="html"><text></text></falsefeedback>
    </node>"""
    xml_multi = _make_question_xml("LowestTerms", extra_nodes=extra)
    issues_multi = lint_question(xml_multi)
    assert not any(i.code == "tans-ignored-single-node" for i in issues_multi)

    # Validator ignores tans but is excluded from the single-node warning
    xml_val = _make_question_xml("Validator", testoptions="is_prime")
    issues_val = lint_question(xml_val)
    assert not any(i.code == "tans-ignored-single-node" for i in issues_val)
