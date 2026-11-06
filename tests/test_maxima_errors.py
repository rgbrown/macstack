"""Comprehensive tests for STACK Maxima error handling, deduplication, diagnostics, and CLI/API integration."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from macstack.cas_errors import (
    CasDiagnostic,
    _clean_error_message,
    build_code_snippet,
    field_to_label,
    parse_and_enrich_cas_errors,
)
from macstack.cli import app
from macstack.engine import StackEngine, StackEngineError
from macstack.preview_server import create_app
from macstack.xml_codec import prepare_for_api


# ==============================================================================
# Sample XML Definitions
# ==============================================================================

XML_VALID = """<quiz>
  <question type="stack">
    <name><text>Valid Question</text></name>
    <questionvariables><text>a: 2;\nb: 3;\nta1: a + b;</text></questionvariables>
    <questiontext format="html"><text><![CDATA[<p>Calculate \\({@a@} + {{@b@}}\\): [[input:ans1]] [[validation:ans1]]</p>]]></text></questiontext>
    <questionnote><text>{@a@}+{@b@}={@ta1@}</text></questionnote>
    <input><name>ans1</name><type>algebraic</type><tans>ta1</tans></input>
    <prt>
      <name>prt1</name>
      <node>
        <name>0</name><answertest>AlgEquiv</answertest><sans>ans1</sans><tans>ta1</tans>
        <truescoremode>=</truescoremode><truescore>1</truescore><truenextnode>-1</truenextnode><trueanswernote>prt1-1-T</trueanswernote>
        <falsescoremode>=</falsescoremode><falsescore>0</falsescore><falsenextnode>-1</falsenextnode><falseanswernote>prt1-1-F</falseanswernote>
      </node>
    </prt>
  </question>
</quiz>"""

XML_QVARS_SYNTAX_ERR = """<quiz>
  <question type="stack">
    <name><text>Qvars Syntax Error</text></name>
    <questionvariables><text>a: 2;
b: 5;
c: 1 + ;</text></questionvariables>
    <questiontext format="html"><text><![CDATA[<p>Calculate: [[input:ans1]] [[validation:ans1]]</p>]]></text></questiontext>
    <input><name>ans1</name><type>algebraic</type><tans>a</tans></input>
    <prt><name>prt1</name><node><name>0</name><answertest>AlgEquiv</answertest><sans>ans1</sans><tans>a</tans></node></prt>
  </question>
</quiz>"""

XML_QVARS_DIV_ZERO = """<quiz>
  <question type="stack">
    <name><text>Qvars Division by Zero</text></name>
    <questionvariables><text>a: 4;
b: 0;
c: a/b;</text></questionvariables>
    <questiontext format="html"><text><![CDATA[<p>Calculate: [[input:ans1]] [[validation:ans1]]</p>]]></text></questiontext>
    <input><name>ans1</name><type>algebraic</type><tans>a</tans></input>
    <prt><name>prt1</name><node><name>0</name><answertest>AlgEquiv</answertest><sans>ans1</sans><tans>a</tans></node></prt>
  </question>
</quiz>"""

XML_CASTEXT_SYNTAX_ERR = """<quiz>
  <question type="stack">
    <name><text>CASText Syntax Error</text></name>
    <questionvariables><text>a: 4;</text></questionvariables>
    <questiontext format="html"><text><![CDATA[<p>{@ 1 + @} [[input:ans1]] [[validation:ans1]]</p>]]></text></questiontext>
    <input><name>ans1</name><type>algebraic</type><tans>a</tans></input>
    <prt><name>prt1</name><node><name>0</name><answertest>AlgEquiv</answertest><sans>ans1</sans><tans>a</tans></node></prt>
  </question>
</quiz>"""

XML_PRT_SYNTAX_ERR = """<quiz>
  <question type="stack">
    <name><text>PRT Syntax Error</text></name>
    <questionvariables><text>a: 10;</text></questionvariables>
    <questiontext format="html"><text><![CDATA[<p>Calculate: [[input:ans1]] [[validation:ans1]]</p>]]></text></questiontext>
    <input><name>ans1</name><type>algebraic</type><tans>a</tans></input>
    <prt>
      <name>prt1</name>
      <feedbackvariables><text>bad: 1 + ;</text></feedbackvariables>
      <node><name>0</name><answertest>AlgEquiv</answertest><sans>ans1</sans><tans>a</tans></node>
    </prt>
  </question>
</quiz>"""

XML_PRT_RUNTIME_ERR = """<quiz>
  <question type="stack">
    <name><text>PRT Runtime Error</text></name>
    <questionvariables><text>a: 10;</text></questionvariables>
    <questiontext format="html"><text><![CDATA[<p>Calculate: [[input:ans1]] [[validation:ans1]]</p>]]></text></questiontext>
    <input><name>ans1</name><type>algebraic</type><tans>a</tans></input>
    <prt>
      <name>prt1</name>
      <feedbackvariables><text>bad: 1/0;</text></feedbackvariables>
      <node><name>0</name><answertest>AlgEquiv</answertest><sans>ans1</sans><tans>a</tans></node>
    </prt>
  </question>
</quiz>"""


# ==============================================================================
# 1. Unit Tests (cas_errors.py)
# ==============================================================================

def test_deduplicate_doubled_runtime_error() -> None:
    """STACK's doubled runtime string is deduplicated into a single clean CasDiagnostic."""
    doubled_str = 'Division by zero.\nThe field ""Question variables"" generated the following error: Division by zero.'
    diags = parse_and_enrich_cas_errors(doubled_str, xml_str=XML_QVARS_DIV_ZERO)
    assert len(diags) == 1
    d = diags[0]
    assert d.field == "questionvariables"
    assert d.label == "Question variables"
    assert d.message == "Division by zero."


def test_clean_coordinates_and_compact_parser_error() -> None:
    """Parser lists with ~35 tokens are compacted into user-friendly message with line/col extracted."""
    verbose_err = (
        'Expected "#pm#", "%not ", "\'", "\'\'", "(", "+", "+-", "-", "? ", "?", "?? ", "[", '
        '"do", "for", "from", "if", "in", "next", "not ", "not", "nounnot ", "nounnot", "nounsub ", '
        '"step", "thru", "unless", "while", "{", "|", boolean, float, identifier, integer, string '
        'or whitespace but ";" found. (At about line 3 character 8.)'
    )
    clean_msg, line, col, highlight = _clean_error_message(verbose_err)
    assert line == 3
    assert col == 8
    assert "unexpected ;" in clean_msg
    assert "Expected" not in clean_msg
    assert "boolean, float, identifier" not in clean_msg


def test_clean_syntax_example_span_and_locate_in_questiontext() -> None:
    """<span class="stacksyntaxexample"> is safely converted to backticks and located in questiontext."""
    raw_span_err = 'Error(s) in question-text: \'+\' is an invalid final character in <span class="stacksyntaxexample">1 +</span>'
    diags = parse_and_enrich_cas_errors(raw_span_err, xml_str=XML_CASTEXT_SYNTAX_ERR)
    assert len(diags) == 1
    d = diags[0]
    assert d.field == "questiontext"
    assert d.label == "Question text"
    assert "<span" not in d.message
    assert "`1 +`" in d.message
    assert d.snippet is not None
    assert "> 1 | <p>{@ 1 + @}" in d.snippet
    assert "^" in d.snippet


def test_build_code_snippet_caret_accuracy() -> None:
    """Snippets accurately place '>' on target line and '^' under the error column."""
    # 1. questionvariables
    source_qvars = "a: 2;\nb: 5;\nc: 1 + ;"
    col_semi = source_qvars.splitlines()[2].index(";") + 1  # 1-based col 8
    snippet_qv = build_code_snippet(source_qvars, line=3, col=col_semi)
    assert snippet_qv is not None
    lines_qv = snippet_qv.splitlines()
    assert lines_qv[0].strip() == "2 | b: 5;"
    assert lines_qv[1].strip() == "> 3 | c: 1 + ;"
    assert lines_qv[2].endswith("^")
    assert lines_qv[2].index("^") == lines_qv[1].index(";")

    # 2. PRT feedbackvariables
    source_prt = "bad: 1 + ;"
    col_prt_semi = source_prt.index(";") + 1
    snippet_prt = build_code_snippet(source_prt, line=1, col=col_prt_semi)
    assert snippet_prt is not None
    lines_prt = snippet_prt.splitlines()
    assert lines_prt[0].strip() == "> 1 | bad: 1 + ;"
    assert lines_prt[1].index("^") == lines_prt[0].index(";")


def test_probed_errors_priority_and_drop_opaque_keyval_error() -> None:
    """Probed errors take precedence and drop opaque 'must validate true before compiling'."""
    raw_opaque = ["stack_cas_keyval: must validate true before compiling."]
    probed = [{
        "field": "prt:prt1:feedbackvariables",
        "message": 'Expected "..." but ";" found. (At about line 1 character 9.)',
        "line": 1,
        "col": 9,
    }]
    diags = parse_and_enrich_cas_errors(
        raw_opaque,
        xml_str=XML_PRT_SYNTAX_ERR,
        probed_errors=probed,
    )
    assert len(diags) == 1
    d = diags[0]
    assert d.field == "prt:prt1:feedbackvariables"
    assert d.label == "PRT prt1 · Feedback variables"
    assert "must validate true before compiling" not in d.message


# ==============================================================================
# 2. Engine & PHP Bridge Integration Tests
# ==============================================================================

def test_engine_questionvariables_syntax_error_partial_vars() -> None:
    """Syntax error on line 3 raises in render(), inspect_vars() yields partial evaluated variables."""
    engine = StackEngine()
    api_xml, seed, _ = prepare_for_api(XML_QVARS_SYNTAX_ERR)

    with pytest.raises(StackEngineError) as exc_info:
        engine.render(api_xml, seed=seed)
    assert "question-variables" in exc_info.value.message or "Expected" in exc_info.value.message

    vars_res = engine.inspect_vars(api_xml, seed=seed)
    # Partial evaluation: variables 'a' and 'b' evaluated despite error on line 3
    var_names = [v["name"] for v in vars_res.get("variables", [])]
    assert "a" in var_names
    assert "b" in var_names
    assert "c" not in var_names

    # Probed errors captured
    probed = vars_res.get("probed_errors", [])
    assert len(probed) > 0
    assert probed[0]["field"] == "questionvariables"
    assert probed[0]["line"] == 3


def test_engine_questionvariables_division_by_zero() -> None:
    """Runtime division by zero raises in render(), inspect_vars() captures preceding evaluated variables."""
    engine = StackEngine()
    api_xml, seed, _ = prepare_for_api(XML_QVARS_DIV_ZERO)

    with pytest.raises(StackEngineError) as exc_info:
        engine.render(api_xml, seed=seed)
    assert "Division by zero" in exc_info.value.message

    vars_res = engine.inspect_vars(api_xml, seed=seed)
    assert "Division by zero" in vars_res.get("errors", "")
    var_map = {v["name"]: v["value"] for v in vars_res.get("variables", [])}
    assert var_map.get("a") == "4"
    assert var_map.get("b") == "0"


def test_engine_castext_syntax_error() -> None:
    """CASText error in questiontext is probed with line or substring location."""
    engine = StackEngine()
    api_xml, seed, _ = prepare_for_api(XML_CASTEXT_SYNTAX_ERR)

    with pytest.raises(StackEngineError) as exc_info:
        engine.render(api_xml, seed=seed)
    assert "question-text" in exc_info.value.message or "+" in exc_info.value.message

    vars_res = engine.inspect_vars(api_xml, seed=seed)
    probed = vars_res.get("probed_errors", [])
    assert any(p["field"] == "questiontext" for p in probed)


def test_engine_prt_feedbackvariables_syntax_error() -> None:
    """PRT feedbackvariables syntax error is isolated, valid questionvariables still evaluate."""
    engine = StackEngine()
    api_xml, seed, _ = prepare_for_api(XML_PRT_SYNTAX_ERR)

    vars_res = engine.inspect_vars(api_xml, seed=seed)
    # Valid questionvariables evaluated
    var_names = [v["name"] for v in vars_res.get("variables", [])]
    assert "a" in var_names

    # Probed error pinpoints feedbackvariables
    probed = vars_res.get("probed_errors", [])
    assert any("prt:prt1:feedbackvariables" in p["field"] for p in probed)


def test_engine_prt_runtime_error_and_empty_answers() -> None:
    """PRT runtime error during grade() returns has_prt_errors: True; empty input returns isgradable: False."""
    engine = StackEngine()
    api_xml, seed, _ = prepare_for_api(XML_PRT_RUNTIME_ERR)

    # Empty answers: ungradable, no PRT error flag
    res_empty = engine.grade(api_xml, answers={}, seed=seed)
    assert res_empty.get("isgradable") is False
    assert res_empty.get("has_prt_errors") is False

    # Submitted answer: triggers PRT evaluation -> runtime error captured
    res_graded = engine.grade(api_xml, answers={"ans1": "10"}, seed=seed)
    assert res_graded.get("isgradable") is True
    assert res_graded.get("has_prt_errors") is True
    assert res_graded.get("score") is None
    prt1 = res_graded["prtresults"]["prt1"]
    assert prt1["has_errors"] is True
    assert "Division by zero" in prt1["errors"]


def test_engine_deploy_seeds_on_broken_questionvariables() -> None:
    """deploy_seeds on broken question returns count == 0 and populated first_error / probed_errors."""
    engine = StackEngine()
    api_xml, _, _ = prepare_for_api(XML_QVARS_SYNTAX_ERR)

    res = engine.deploy_seeds(api_xml, count=10)
    assert res.get("count") == 0
    assert "question-variables" in res.get("first_error", "") or "Expected" in res.get("first_error", "")
    assert len(res.get("probed_errors", [])) > 0


# ==============================================================================
# 3. Preview Server Starlette TestClient Tests
# ==============================================================================

def test_preview_api_question_valid(tmp_path: Path) -> None:
    """GET /api/question on valid question returns render_failed: False and cas_errors: []."""
    q_file = tmp_path / "valid.xml"
    q_file.write_text(XML_VALID, encoding="utf-8")

    app = create_app(tmp_path)
    client = TestClient(app)

    r = client.get("/api/question?path=valid.xml")
    assert r.status_code == 200
    data = r.json()
    assert data["render_failed"] is False
    assert data["cas_errors"] == []
    assert "questionrender" in data["render"]
    assert len(data["vars"]["variables"]) == 3


def test_preview_api_question_errors_and_malformed_xml(tmp_path: Path) -> None:
    """GET /api/question returns HTTP 200, render_failed: True, and cas_errors across error variants."""
    files = {
        "qvars_syntax.xml": XML_QVARS_SYNTAX_ERR,
        "div_zero.xml": XML_QVARS_DIV_ZERO,
        "castext_err.xml": XML_CASTEXT_SYNTAX_ERR,
        "prt_syntax.xml": XML_PRT_SYNTAX_ERR,
        "malformed.xml": "<quiz><not_stack>Hello</not_stack></quiz>",
    }
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    app = create_app(tmp_path)
    client = TestClient(app)

    # 1. Question variables syntax error
    r1 = client.get("/api/question?path=qvars_syntax.xml")
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["render_failed"] is True
    assert len(d1["cas_errors"]) > 0
    assert d1["cas_errors"][0]["field"] == "questionvariables"
    assert d1["cas_errors"][0]["snippet"] is not None
    assert len(d1["vars"]["variables"]) >= 2  # Partial variables preserved

    # 2. Division by zero
    r2 = client.get("/api/question?path=div_zero.xml")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["render_failed"] is True
    assert any("Division by zero" in e["message"] for e in d2["cas_errors"])

    # 3. CASText syntax error
    r3 = client.get("/api/question?path=castext_err.xml")
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["render_failed"] is True
    assert any(e["field"] == "questiontext" for e in d3["cas_errors"])
    assert d3["raw_questiontext"] != ""

    # 4. PRT syntax error
    r4 = client.get("/api/question?path=prt_syntax.xml")
    assert r4.status_code == 200
    d4 = r4.json()
    assert any("prt:prt1:feedbackvariables" in e["field"] for e in d4["cas_errors"])

    # 5. Malformed / non-stack XML
    r5 = client.get("/api/question?path=malformed.xml")
    assert r5.status_code == 200
    d5 = r5.json()
    assert d5["render_failed"] is True
    assert d5["cas_errors"][0]["field"] == "xml"


def test_preview_api_grade_prt_runtime_error_and_empty_input(tmp_path: Path) -> None:
    """POST /api/grade returns structured PRT diagnostics on runtime error, ungradable on empty input."""
    q_file = tmp_path / "prt_runtime.xml"
    q_file.write_text(XML_PRT_RUNTIME_ERR, encoding="utf-8")

    app = create_app(tmp_path)
    client = TestClient(app)

    # Empty input
    r_empty = client.post("/api/grade", json={"path": "prt_runtime.xml", "answers": {}})
    assert r_empty.status_code == 200
    d_empty = r_empty.json()
    assert d_empty["isgradable"] is False
    assert d_empty["has_prt_errors"] is False

    # With answer -> PRT runtime error
    r_grade = client.post("/api/grade", json={"path": "prt_runtime.xml", "answers": {"ans1": "10"}})
    assert r_grade.status_code == 200
    d_grade = r_grade.json()
    assert d_grade["has_prt_errors"] is True
    assert "prt1" in d_grade["prtresults"]
    assert d_grade["prtresults"]["prt1"]["has_errors"] is True
    assert len(d_grade["prtresults"]["prt1"]["diagnostics"]) > 0
    assert len(d_grade["cas_errors"]) > 0


def test_preview_api_validate_test_and_deploy_seeds_on_broken_xml(tmp_path: Path) -> None:
    """POST /api/validate, /api/test, and /api/deploy-seeds return 200 with structured cas_errors; XML unmodified."""
    q_file = tmp_path / "broken.xml"
    q_file.write_text(XML_QVARS_SYNTAX_ERR, encoding="utf-8")
    initial_content = q_file.read_text(encoding="utf-8")

    app = create_app(tmp_path)
    client = TestClient(app)

    # 1. validate
    r_val = client.post("/api/validate", json={"path": "broken.xml", "inputName": "ans1", "answers": {"ans1": "1"}})
    assert r_val.status_code == 200
    assert len(r_val.json().get("cas_errors", [])) > 0

    # 2. test
    r_test = client.post("/api/test", json={"path": "broken.xml"})
    assert r_test.status_code == 200
    assert len(r_test.json().get("cas_errors", [])) > 0

    # 3. deploy-seeds
    r_seeds = client.post("/api/deploy-seeds", json={"path": "broken.xml", "count": 10})
    assert r_seeds.status_code == 200
    d_seeds = r_seeds.json()
    assert d_seeds["count"] == 0
    assert len(d_seeds.get("cas_errors", [])) > 0

    # Verify XML file on disk was NOT modified when 0 seeds succeeded
    assert q_file.read_text(encoding="utf-8") == initial_content


# ==============================================================================
# 4. CLI (Typer CliRunner) Tests
# ==============================================================================

def test_cli_vars_broken_question_human_and_json(tmp_path: Path) -> None:
    """macstack vars on broken question exits with code 1, renders partial vars, no traceback."""
    q_file = tmp_path / "broken_vars.xml"
    q_file.write_text(XML_QVARS_SYNTAX_ERR, encoding="utf-8")

    runner = CliRunner()

    # Human output
    r_human = runner.invoke(app, ["vars", str(q_file)])
    assert r_human.exit_code == 1
    assert "Traceback" not in r_human.output
    assert "Question variables" in r_human.output
    assert "a" in r_human.output
    assert "b" in r_human.output

    # JSON output
    r_json = runner.invoke(app, ["vars", str(q_file), "--json"])
    assert r_json.exit_code == 1
    d = json.loads(r_json.output)
    assert len(d["variables"]) >= 2
    assert len(d["cas_errors"]) > 0


def test_cli_commands_clean_exit_code_1_on_broken_questions(tmp_path: Path) -> None:
    """macstack render, validate, grade, deploy-seeds, and test exit 1 without tracebacks."""
    q_qvars = tmp_path / "broken_qvars.xml"
    q_qvars.write_text(XML_QVARS_SYNTAX_ERR, encoding="utf-8")

    q_prt = tmp_path / "broken_prt.xml"
    q_prt.write_text(XML_PRT_RUNTIME_ERR, encoding="utf-8")

    runner = CliRunner()

    # 1. macstack render
    r_render = runner.invoke(app, ["render", str(q_qvars)])
    assert r_render.exit_code == 1
    assert "Traceback" not in r_render.output
    r_render_j = runner.invoke(app, ["render", str(q_qvars), "--json"])
    assert r_render_j.exit_code == 1
    assert json.loads(r_render_j.output)["ok"] is False

    # 2. macstack validate
    r_val = runner.invoke(app, ["validate", str(q_qvars), "-i", "ans1", "-a", "ans1=1"])
    assert r_val.exit_code == 1
    assert "Traceback" not in r_val.output
    r_val_j = runner.invoke(app, ["validate", str(q_qvars), "-i", "ans1", "-a", "ans1=1", "--json"])
    assert r_val_j.exit_code == 1
    assert json.loads(r_val_j.output)["ok"] is False

    # 3. macstack grade (question-level error)
    r_grade1 = runner.invoke(app, ["grade", str(q_qvars), "-a", "ans1=1"])
    assert r_grade1.exit_code == 1
    assert "Traceback" not in r_grade1.output
    r_grade1_j = runner.invoke(app, ["grade", str(q_qvars), "-a", "ans1=1", "--json"])
    assert r_grade1_j.exit_code == 1
    assert "cas_errors" in json.loads(r_grade1_j.output)

    # 4. macstack grade (PRT runtime error)
    r_grade2 = runner.invoke(app, ["grade", str(q_prt), "-a", "ans1=10"])
    assert r_grade2.exit_code == 1
    assert "Traceback" not in r_grade2.output
    assert "PRT Grading Error" in r_grade2.output or "Maxima" in r_grade2.output
    r_grade2_j = runner.invoke(app, ["grade", str(q_prt), "-a", "ans1=10", "--json"])
    assert r_grade2_j.exit_code == 1
    assert json.loads(r_grade2_j.output)["has_prt_errors"] is True

    # 5. macstack deploy-seeds
    r_seeds = runner.invoke(app, ["deploy-seeds", str(q_qvars), "-n", "5"])
    assert r_seeds.exit_code == 1
    assert "Traceback" not in r_seeds.output
    r_seeds_j = runner.invoke(app, ["deploy-seeds", str(q_qvars), "-n", "5", "--json"])
    assert r_seeds_j.exit_code == 1
    assert json.loads(r_seeds_j.output)["ok"] is False

    # 6. macstack test
    r_test = runner.invoke(app, ["test", str(q_qvars)])
    assert r_test.exit_code == 1
    assert "Traceback" not in r_test.output
    r_test_j = runner.invoke(app, ["test", str(q_qvars), "--json"])
    assert r_test_j.exit_code == 1
    assert json.loads(r_test_j.output)["ok"] is False
