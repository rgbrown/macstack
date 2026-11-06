"""Comprehensive automated verification test suite for macstack."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from lxml import etree
import pytest
from starlette.testclient import TestClient

from macstack.engine import StackEngine
from macstack.linter import lint_question
from macstack.preview_server import create_app
from macstack.runtime import doctor
from macstack.xml_codec import (
    bundle_bank,
    prepare_for_api,
    split_bank,
)

DEMO_DIR = Path(__file__).parent.parent / "examples" / "demo"


def _extract_model_answers(render_inputs: dict) -> dict[str, str]:
    """Helper to convert render['inputs'] samplesolution into answers map for grading."""
    answers: dict[str, str] = {}
    for name, input_def in render_inputs.items():
        samples = input_def.get("samplesolution") or {}
        for subkey, val in samples.items():
            if subkey == "":
                answers[name] = str(val)
            elif subkey.startswith("_"):
                answers[f"{name}{subkey}"] = str(val)
            elif subkey.startswith(f"{name}_"):
                answers[subkey] = str(val)
            else:
                answers[f"{name}_{subkey}"] = str(val)
    return answers


def test_doctor() -> None:
    """1. Full runtime healthcheck passes and reports healthy state."""
    status = doctor()
    assert status["ok"] is True, f"Doctor checks failed: {status}"
    assert status.get("cas_latency_ms", 9999) < 1000.0


def test_demo_questions_lint_clean() -> None:
    """2. Verifies examples/demo questions all pass static linter with 0 errors and 0 warnings."""
    assert (DEMO_DIR / "macstack.toml").exists()
    questions = sorted((DEMO_DIR / "questions").glob("**/*.xml"))
    assert len(questions) == 4, f"Expected 4 showcase demo questions, found {len(questions)}"

    for q_file in questions:
        issues = lint_question(q_file)
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        assert len(errors) == 0, f"Linter errors in {q_file.name}: {errors}"
        assert len(warnings) == 0, f"Linter warnings in {q_file.name}: {warnings}"


def test_demo_questions_render_grade_and_plots() -> None:
    """3. Renders demo questions, verifies plot SVG bytes, and tests PRT grading including misconception branches."""
    engine = StackEngine()
    questions = sorted((DEMO_DIR / "questions").glob("**/*.xml"))
    assert len(questions) == 4

    # 1. demo-quadratic-graph: SVG plot and 3-branch PRT
    quad_file = DEMO_DIR / "questions" / "algebra" / "demo-quadratic-graph.xml"
    api_xml, seed, _ = prepare_for_api(quad_file.read_text(encoding="utf-8"), seed_override=1)
    rendered = engine.render(api_xml, seed=seed)
    assets = rendered.get("questionassets", {})
    assert len(assets) >= 1, "Expected SVG plot asset in demo-quadratic-graph"
    for _, fname in assets.items():
        data, ctype = engine.get_plot_bytes(fname)
        assert len(data) > 0
        assert b"<svg" in data or b"<?xml" in data

    # Model answer -> score 1.0
    ans_model = _extract_model_answers(rendered.get("inputs", {}))
    res_model = engine.grade(api_xml, answers=ans_model, seed=seed)
    assert res_model.get("score") == pytest.approx(1.0, abs=1e-4)

    # Forgot scale factor a -> score 0.5 (Node 1)
    # At seed 1: a = -2, h = 3, k = -4. ans_no_a = (x - 3)^2 - 4
    res_no_a = engine.grade(api_xml, answers={"ans1": "(x - 3)^2 - 4"}, seed=seed)
    assert res_no_a.get("score") == pytest.approx(0.5, abs=1e-4)

    # Horizontal sign flip -> score 0.0 (Node 2)
    res_sign = engine.grade(api_xml, answers={"ans1": "-2*(x + 3)^2 - 4"}, seed=seed)
    assert res_sign.get("score") == pytest.approx(0.0, abs=1e-4)

    # 2. demo-power-integral: Indefinite integral Int test
    int_file = DEMO_DIR / "questions" / "calculus" / "demo-power-integral.xml"
    api_xml_int, seed_int, _ = prepare_for_api(int_file.read_text(encoding="utf-8"), seed_override=1)
    rend_int = engine.render(api_xml_int, seed=seed_int)
    ans_int_model = _extract_model_answers(rend_int.get("inputs", {}))
    res_int = engine.grade(api_xml_int, answers=ans_int_model, seed=seed_int)
    assert res_int.get("score") == pytest.approx(1.0, abs=1e-4)

    # 3. demo-linear-system-matrix: 2x2 matrix input
    mat_file = DEMO_DIR / "questions" / "algebra" / "demo-linear-system-matrix.xml"
    api_xml_mat, seed_mat, _ = prepare_for_api(mat_file.read_text(encoding="utf-8"), seed_override=1)
    rend_mat = engine.render(api_xml_mat, seed=seed_mat)
    ans_mat_model = _extract_model_answers(rend_mat.get("inputs", {}))
    res_mat = engine.grade(api_xml_mat, answers=ans_mat_model, seed=seed_mat)
    assert res_mat.get("score") == pytest.approx(1.0, abs=1e-4)
    assert "prtresults" in res_mat and "prt1" in res_mat["prtresults"]
    assert "prt1-0-T" in res_mat["prtresults"]["prt1"]["answernotes"]
    assert len(res_mat["prtresults"]["prt1"]["trace"]) > 0

    # Swapped coordinates -> score 0.0, node 1 trueanswernote prt1-1-T
    res_swapped = engine.grade(
        api_xml_mat,
        answers={"ans1_sub_0_0": "-1", "ans1_sub_1_0": "2"},
        seed=seed_mat,
    )
    assert res_swapped.get("score") == pytest.approx(0.0, abs=1e-4)
    assert "prtresults" in res_swapped and "prt1" in res_swapped["prtresults"]
    assert "prt1-1-T" in res_swapped["prtresults"]["prt1"]["answernotes"]
    assert "prt1-0-F" in res_swapped["prtresults"]["prt1"]["answernotes"]

    # 4. demo-stationary-point-radio: multiple choice radio input
    radio_file = DEMO_DIR / "questions" / "calculus" / "demo-stationary-point-radio.xml"
    api_xml_radio, seed_radio, _ = prepare_for_api(radio_file.read_text(encoding="utf-8"), seed_override=1)
    rend_radio = engine.render(api_xml_radio, seed=seed_radio)
    ans_radio_model = _extract_model_answers(rend_radio.get("inputs", {}))
    res_radio = engine.grade(api_xml_radio, answers=ans_radio_model, seed=seed_radio)
    assert res_radio.get("score") == pytest.approx(1.0, abs=1e-4)


def test_demo_qtest_suite_passes() -> None:
    """4. macstack test runs all <qtest> regression suites across deployed seeds with 100% pass rate."""
    res = subprocess.run(
        ["macstack", "test", str(DEMO_DIR / "questions"), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert data["fails"] == 0
    assert data["passes"] >= 200, f"Expected >= 200 passed tests across 4 questions, got {data['passes']}"


def test_bundle_and_split_roundtrip(tmp_path: Path) -> None:
    """5. Bundles examples/demo/questions into XML bundle, splits it losslessly, and verifies structure."""
    out_bundle = tmp_path / "bundled_demo.xml"
    count = bundle_bank([DEMO_DIR / "questions"], out_bundle)
    assert count == 4
    assert out_bundle.exists()

    tree = etree.parse(str(out_bundle))
    root = tree.getroot()
    categories = root.findall(".//question[@type='category']")
    stack_questions = root.findall(".//question[@type='stack']")

    assert len(categories) == 3  # Root Demo Course, Algebra, Calculus
    assert len(stack_questions) == 4

    # Split into clean directory
    split_dir = tmp_path / "split_output"
    config, split_files = split_bank(out_bundle, split_dir)
    assert len(split_files) == 4
    assert (split_dir / "macstack.toml").exists()

    split_questions = sorted((split_dir / "questions").glob("**/*.xml"))
    assert len(split_questions) == 4
    split_names = {q.name for q in split_questions}
    expected_names = {
        "demo-quadratic-graph.xml",
        "demo-power-integral.xml",
        "demo-linear-system-matrix.xml",
        "demo-stationary-point-radio.xml",
    }
    assert split_names == expected_names


def test_linter_catches_syntax_and_graph_bugs() -> None:
    """6. Static linter catches castext-orphan-close, missing-validation, prt-cycle, and missing-deployed-seeds."""
    # 1. Orphan closing delimiter
    orphan_xml = """<quiz><question type="stack"><name><text>T1</text></name><idnumber>t1</idnumber>
    <questionvariables><text>ta1: 5;</text></questionvariables>
    <questiontext format="html"><text><![CDATA[<p>@ta1@} [[input:ans1]] [[validation:ans1]]</p>]]></text></questiontext>
    <questionnote><text>1</text></questionnote>
    <input><name>ans1</name><type>algebraic</type><tans>ta1</tans></input>
    <prt><name>prt1</name><node><name>0</name><answertest>AlgEquiv</answertest><sans>ans1</sans><tans>ta1</tans>
    <truescoremode>=</truescoremode><truescore>1</truescore><truenextnode>-1</truenextnode><trueanswernote>T</trueanswernote>
    <falsescoremode>=</falsescoremode><falsescore>0</falsescore><falsenextnode>-1</falsenextnode><falseanswernote>F</falseanswernote></node></prt>
    <specificfeedback format="html"><text>[[feedback:prt1]]</text></specificfeedback>
    </question></quiz>"""
    issues1 = lint_question(orphan_xml)
    assert any(i.code == "castext-orphan-close" for i in issues1)

    # 2. Missing validation placeholder
    missing_val_xml = """<quiz><question type="stack"><name><text>T2</text></name><idnumber>t2</idnumber>
    <questionvariables><text>ta1: 5;</text></questionvariables>
    <questiontext format="html"><text><![CDATA[<p>Calculate: [[input:ans1]]</p>]]></text></questiontext>
    <questionnote><text>1</text></questionnote>
    <input><name>ans1</name><type>algebraic</type><tans>ta1</tans><showvalidation>1</showvalidation></input>
    <prt><name>prt1</name><node><name>0</name><answertest>AlgEquiv</answertest><sans>ans1</sans><tans>ta1</tans>
    <truescoremode>=</truescoremode><truescore>1</truescore><truenextnode>-1</truenextnode><trueanswernote>T</trueanswernote>
    <falsescoremode>=</falsescoremode><falsescore>0</falsescore><falsenextnode>-1</falsenextnode><falseanswernote>F</falseanswernote></node></prt>
    <specificfeedback format="html"><text>[[feedback:prt1]]</text></specificfeedback>
    </question></quiz>"""
    issues2 = lint_question(missing_val_xml)
    assert any(i.code == "missing-validation" for i in issues2)

    # 3. PRT cycle
    cycle_xml = """<quiz><question type="stack"><name><text>T3</text></name><idnumber>t3</idnumber>
    <questionvariables><text>ta1: 5;</text></questionvariables>
    <questiontext format="html"><text><![CDATA[<p>[[input:ans1]] [[validation:ans1]]</p>]]></text></questiontext>
    <questionnote><text>1</text></questionnote>
    <input><name>ans1</name><type>algebraic</type><tans>ta1</tans></input>
    <prt><name>prt1</name>
      <node><name>0</name><answertest>AlgEquiv</answertest><sans>ans1</sans><tans>ta1</tans>
        <truenextnode>1</truenextnode><falsenextnode>-1</falsenextnode></node>
      <node><name>1</name><answertest>AlgEquiv</answertest><sans>ans1</sans><tans>ta1</tans>
        <truenextnode>0</truenextnode><falsenextnode>-1</falsenextnode></node>
    </prt>
    <specificfeedback format="html"><text>[[feedback:prt1]]</text></specificfeedback>
    </question></quiz>"""
    issues3 = lint_question(cycle_xml)
    assert any(i.code == "prt-cycle" for i in issues3)

    # 4. Randomized question without deployed seeds
    unseeded_xml = """<quiz><question type="stack"><name><text>T4</text></name><idnumber>t4</idnumber>
    <questionvariables><text>a: rand(10); ta1: a;</text></questionvariables>
    <questiontext format="html"><text><![CDATA[<p>[[input:ans1]] [[validation:ans1]]</p>]]></text></questiontext>
    <questionnote><text>{@a@}</text></questionnote>
    <input><name>ans1</name><type>algebraic</type><tans>ta1</tans></input>
    <prt><name>prt1</name><node><name>0</name><answertest>AlgEquiv</answertest><sans>ans1</sans><tans>ta1</tans>
    <truenextnode>-1</truenextnode><falsenextnode>-1</falsenextnode></node></prt>
    <specificfeedback format="html"><text>[[feedback:prt1]]</text></specificfeedback>
    </question></quiz>"""
    issues4 = lint_question(unseeded_xml)
    assert any(i.code == "missing-deployed-seeds" for i in issues4)


def test_authoring_workflow_end_to_end(tmp_path: Path) -> None:
    """7. End-to-end authoring: init, scaffold, format, deploy-seeds, add-test, and test pass rate."""
    # 1. macstack init
    subprocess.run(["macstack", "init", str(tmp_path)], capture_output=True, text=True, check=True)
    assert (tmp_path / "macstack.toml").exists()

    # 2. Write minimal randomized STACK question XML
    q_file = tmp_path / "questions" / "q_test.xml"
    q_file.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<quiz>
  <question type="stack">
    <name><text>End-to-End Workflow Test</text></name>
    <idnumber>e2e-workflow-test</idnumber>
    <questionvariables><text>a: rand(50) + 2; ta1: a;</text></questionvariables>
    <questiontext format="html"><text><![CDATA[<p>Enter the value: [[input:ans1]] [[validation:ans1]]</p>]]></text></questiontext>
    <questionnote><text>{@a@}</text></questionnote>
    <specificfeedback format="html"><text>[[feedback:prt1]]</text></specificfeedback>
    <input><name>ans1</name><type>algebraic</type><tans>ta1</tans></input>
    <prt><name>prt1</name>
      <node><name>0</name><answertest>AlgEquiv</answertest><sans>ans1</sans><tans>ta1</tans>
        <truescoremode>=</truescoremode><truescore>1.0</truescore><truenextnode>-1</truenextnode><trueanswernote>prt1-0-T</trueanswernote>
        <falsescoremode>=</falsescoremode><falsescore>0.0</falsescore><falsenextnode>-1</falsenextnode><falseanswernote>prt1-0-F</falseanswernote>
      </node>
    </prt>
  </question>
</quiz>""", encoding="utf-8")

    # 3. macstack format
    subprocess.run(["macstack", "format", str(q_file)], capture_output=True, text=True, check=True)

    # 4. macstack deploy-seeds -n 8
    subprocess.run(["macstack", "deploy-seeds", str(q_file), "-n", "8"], capture_output=True, text=True, check=True)

    # 5. macstack add-test (model answer ta1 and incorrect answer ta1+1)
    subprocess.run(["macstack", "add-test", str(q_file), "-a", "ans1=ta1", "-d", "Correct Answer"], capture_output=True, text=True, check=True)
    subprocess.run(["macstack", "add-test", str(q_file), "-a", "ans1=ta1+1", "-d", "Off By One"], capture_output=True, text=True, check=True)

    # 6. macstack test --json across all 8 seeds
    res_test = subprocess.run(["macstack", "test", str(q_file), "--json"], capture_output=True, text=True, check=True)
    test_data = json.loads(res_test.stdout)
    assert test_data["ok"] is True
    assert test_data["fails"] == 0
    assert test_data["passes"] == 16  # 2 tests * 8 deployed seeds


def test_preview_server_endpoints() -> None:
    """8. Live preview workbench Starlette endpoints: static assets, discovery, inspect, validate, grade, plots."""
    app = create_app(DEMO_DIR)
    client = TestClient(app)

    # 1. Static HTML/CSS/JS
    r_index = client.get("/")
    assert r_index.status_code == 200
    assert "macstack" in r_index.text

    r_css = client.get("/styles.css")
    assert r_css.status_code == 200
    assert "workbench-layout" in r_css.text

    r_js = client.get("/app.js")
    assert r_js.status_code == 200
    assert "loadQuestions" in r_js.text

    # 2. GET /api/questions
    r_q = client.get("/api/questions")
    assert r_q.status_code == 200
    q_data = r_q.json()
    assert len(q_data["questions"]) == 4
    active_path = q_data["active"]
    assert active_path is not None

    # 3. GET /api/question?path=...
    r_single = client.get(f"/api/question?path={active_path}")
    assert r_single.status_code == 200
    single_data = r_single.json()
    assert "render" in single_data
    assert "vars" in single_data
    assert "lint" in single_data

    # 4. POST /api/validate
    r_val = client.post("/api/validate", json={
        "path": active_path,
        "inputName": "ans1",
        "answers": {"ans1": "3/4"},
    })
    assert r_val.status_code == 200
    val_data = r_val.json()
    assert "validation" in val_data

    # 5. POST /api/grade
    r_grade = client.post("/api/grade", json={
        "path": active_path,
        "answers": {"ans1": "3/4"},
    })
    assert r_grade.status_code == 200
    grade_payload = r_grade.json()
    assert "prtresults" in grade_payload
    assert "isgradable" in grade_payload

    # 6. GET /plots/{filename} on question with plot
    plot_q_relpath = None
    for q in q_data["questions"]:
        if "quadratic-graph" in q["relpath"]:
            plot_q_relpath = q["relpath"]
            break

    assert plot_q_relpath is not None
    r_pq = client.get(f"/api/question?path={plot_q_relpath}")
    assert r_pq.status_code == 200
    assets = r_pq.json()["render"].get("questionassets", {})
    assert len(assets) > 0
    for _, fname in assets.items():
        r_plot = client.get(f"/plots/{fname}")
        assert r_plot.status_code == 200
        assert len(r_plot.content) > 0
        assert b"<svg" in r_plot.content or b"<?xml" in r_plot.content


def test_maxima_repl_batch() -> None:
    """9. Batch Maxima REPL execution evaluating question variables."""
    q_path = DEMO_DIR / "questions" / "algebra" / "demo-quadratic-graph.xml"
    res = subprocess.run(
        ["macstack", "maxima", str(q_path), "--seed", "1", "-e", "f_x;"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Identify Quadratic Function from Graph" in res.stdout
    assert "-(2*(x-3)^2)-4" in res.stdout
