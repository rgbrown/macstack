"""Unit and round-trip tests for macstack sketch format."""

from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree
import pytest

from macstack.config import CourseConfig, load_config
from macstack.linter import lint_question
from macstack.sketch import (
    SketchError,
    apply_sketch,
    apply_text_to_file,
    parse_sketch,
    render_sketch,
    sketch_file,
    xml_to_sketch,
)
from macstack.xml_codec import normalize_question_xml

DEMO_DIR = Path(__file__).parent.parent / "examples" / "demo"
DEMO_CONFIG_PATH = DEMO_DIR / "macstack.toml"
DEMO_QUESTIONS = sorted((DEMO_DIR / "questions").glob("**/*.xml"))


@pytest.fixture
def demo_config() -> CourseConfig:
    return load_config(DEMO_CONFIG_PATH)


# =========================================================================== #
# 1. Round trip on all 4 demo questions
# =========================================================================== #


def test_roundtrip_all_demo_questions_byte_identical(demo_config: CourseConfig) -> None:
    """apply_sketch(parse_sketch(xml_to_sketch(x, cfg)), x, cfg, category_id)

    must be BYTE-IDENTICAL to normalize_question_xml(x, cfg, category_id),
    and xml_to_sketch(applied) == xml_to_sketch(x) (sketch idempotence).
    """
    assert len(DEMO_QUESTIONS) == 4
    for q_path in DEMO_QUESTIONS:
        raw_xml = q_path.read_text(encoding="utf-8")
        category_id = q_path.parent.name

        # 1. XML -> Sketch
        sketch = xml_to_sketch(raw_xml, demo_config, source_label=q_path.name)

        # 2. Sketch -> Model -> Apply onto original XML
        model = parse_sketch(sketch)
        applied_xml = apply_sketch(model, raw_xml, demo_config, category_id=category_id)

        # 3. Normalized XML
        expected_xml = normalize_question_xml(raw_xml, demo_config, category_id=category_id)

        assert applied_xml == expected_xml, f"Byte mismatch on {q_path.name}"

        # 4. Sketch idempotence: xml_to_sketch(applied) == xml_to_sketch(x)
        sketch_from_applied = xml_to_sketch(applied_xml, demo_config, source_label=q_path.name)
        assert sketch_from_applied == sketch, f"Sketch not idempotent on {q_path.name}"


# =========================================================================== #
# 2. Hiding defaults vs showing non-defaults
# =========================================================================== #


def test_hiding_defaults_in_demo_sketches(demo_config: CourseConfig) -> None:
    """Demo sketches contain no default settings (penalty, boxsize, forbidfloat,

    prtcorrect section, value= for PRTs, deployedseed content), but DO contain
    name, idnumber, question variables in a ```maxima fence, question text,
    inputs line, PRT nodes, tests, hints.
    """
    for q_path in DEMO_QUESTIONS:
        raw_xml = q_path.read_text(encoding="utf-8")
        sketch = xml_to_sketch(raw_xml, demo_config, source_label=q_path.name)

        # Defaults hidden
        assert "penalty =" not in sketch, f"penalty found in sketch of {q_path.name}"
        assert "boxsize" not in sketch, f"boxsize found in sketch of {q_path.name}"
        assert "forbidfloat" not in sketch, f"forbidfloat found in sketch of {q_path.name}"
        assert "prtcorrect" not in sketch.lower(), f"prtcorrect found in sketch of {q_path.name}"
        assert "value=" not in sketch, f"value= found in sketch of {q_path.name}"
        assert "<deployedseed>" not in sketch, f"deployedseed found in sketch of {q_path.name}"

        # Essential modelled sections present
        assert 'name = "' in sketch, f"name missing in sketch of {q_path.name}"
        assert 'idnumber = "' in sketch, f"idnumber missing in sketch of {q_path.name}"
        assert "## Question text" in sketch, f"Question text missing in {q_path.name}"
        assert "## Inputs" in sketch, f"Inputs missing in {q_path.name}"
        assert "## PRT " in sketch, f"PRT missing in {q_path.name}"
        assert "## Tests" in sketch, f"Tests missing in {q_path.name}"


def test_hiding_changes_when_course_config_defaults_change(demo_config: CourseConfig) -> None:
    """Changing a default in CourseConfig (e.g. input_defaults boxsize) changes what's shown."""
    q_path = DEMO_DIR / "questions" / "calculus" / "demo-power-integral.xml"
    raw_xml = q_path.read_text(encoding="utf-8")

    # With default boxsize=15, boxsize is hidden
    s1 = xml_to_sketch(raw_xml, demo_config)
    assert "boxsize" not in s1

    # Change course default boxsize to 20; now the XML's boxsize=15 is non-default and must appear
    cfg_modified = copy.deepcopy(demo_config)
    cfg_modified.input_defaults["boxsize"] = "20"
    s2 = xml_to_sketch(raw_xml, cfg_modified)
    assert "boxsize=15" in s2

    # Change default penalty to 0.2; XML's penalty=0.1 must now appear in front matter
    cfg_modified.defaults["penalty"] = "0.2000000"
    s3 = xml_to_sketch(raw_xml, cfg_modified)
    assert "penalty = 0.1" in s3

    # Change prt value default to 2.0; XML's value=1.0 must appear
    cfg_modified.prt_defaults["value"] = "2.0000000"
    s4 = xml_to_sketch(raw_xml, cfg_modified)
    assert "value=1" in s4


# =========================================================================== #
# 3. Edits via sketch text manipulation then apply
# =========================================================================== #


def test_edit_node_true_score(demo_config: CourseConfig) -> None:
    """Changing a node true score updates <truescore> in XML."""
    q_path = DEMO_DIR / "questions" / "calculus" / "demo-power-integral.xml"
    raw_xml = q_path.read_text(encoding="utf-8")
    sketch = xml_to_sketch(raw_xml, demo_config)

    # Change node 0 true score from =1 to =0.75
    assert "true: =1" in sketch
    edited_sketch = sketch.replace("true: =1", "true: =0.75", 1)

    applied_xml = apply_sketch(parse_sketch(edited_sketch), raw_xml, demo_config, category_id="calculus")
    root = etree.fromstring(applied_xml.encode("utf-8"))
    node0 = root.find(".//question[@type='stack']/prt[name='prt1']/node[name='0']")
    assert node0 is not None
    assert node0.findtext("truescore") == "0.75"


def test_edit_add_node_branch_and_test(demo_config: CourseConfig) -> None:
    """Adding a new node, branching false: -> 2, and adding a new test reflects in XML."""
    q_path = DEMO_DIR / "questions" / "calculus" / "demo-power-integral.xml"
    raw_xml = q_path.read_text(encoding="utf-8")
    sketch = xml_to_sketch(raw_xml, demo_config)

    # In node 1, change default false to branch -> 2
    old_node1 = r"""node 1: AlgEquiv(ans1, ans_diff)
  true: =0
    <p>It appears you differentiated the integrand rather than integrating it. Remember that \(\int x^n \, dx = \frac{x^{n+1}}{n+1} + c\).</p>"""

    new_node1_and_2 = r"""node 1: AlgEquiv(ans1, ans_diff)
  true: =0
    <p>It appears you differentiated the integrand rather than integrating it. Remember that \(\int x^n \, dx = \frac{x^{n+1}}{n+1} + c\).</p>
  false: -> 2
node 2: AlgEquiv(ans1, ans_no_c)
  true: =0
    <p>Missing constant of integration.</p>"""

    assert old_node1 in sketch
    edited_sketch = sketch.replace(old_node1, new_node1_and_2)

    # Add a test 4 into the ## Tests section (before ## Hint)
    new_test = """### Test 4: New test
ans1 = ans_no_c
prt1 => 0, prt1-2-T

"""
    assert "## Hint" in edited_sketch
    edited_sketch = edited_sketch.replace("## Hint", new_test + "## Hint")

    applied_xml = apply_sketch(parse_sketch(edited_sketch), raw_xml, demo_config, category_id="calculus")
    root = etree.fromstring(applied_xml.encode("utf-8"))

    # Verify node 1 falsenextnode is 2
    node1 = root.find(".//question[@type='stack']/prt[name='prt1']/node[name='1']")
    assert node1 is not None
    assert node1.findtext("falsenextnode") == "2"

    # Verify node 2 exists
    node2 = root.find(".//question[@type='stack']/prt[name='prt1']/node[name='2']")
    assert node2 is not None
    assert node2.findtext("answertest") == "AlgEquiv"
    assert node2.findtext("tans") == "ans_no_c"

    # Verify Test 4 exists
    qtest4 = root.find(".//question[@type='stack']/qtest[testcase='4']")
    assert qtest4 is not None
    assert qtest4.findtext("description") == "New test"
    assert qtest4.findtext("./expected/expectedanswernote") == "prt1-2-T"


def test_edit_delete_input_setting_resets_to_default(demo_config: CourseConfig) -> None:
    """Deleting a non-default input setting line/token resets it to course default."""
    q_path = DEMO_DIR / "questions" / "calculus" / "demo-power-integral.xml"
    raw_xml = q_path.read_text(encoding="utf-8")

    # In base XML, give ans1 a custom boxsize of 40
    root = etree.fromstring(raw_xml.encode("utf-8"))
    inp = root.find(".//question[@type='stack']/input[name='ans1']")
    assert inp is not None
    inp.find("boxsize").text = "40"
    xml_with_boxsize = etree.tostring(root, encoding="utf-8").decode("utf-8")

    # Sketch shows boxsize=40 because it differs from course default 15
    sketch = xml_to_sketch(xml_with_boxsize, demo_config)
    assert "boxsize=40" in sketch

    # Delete boxsize=40 from sketch
    edited_sketch = sketch.replace(", boxsize=40", "")
    assert "boxsize=40" not in edited_sketch

    # Apply back onto xml_with_boxsize
    applied_xml = apply_sketch(parse_sketch(edited_sketch), xml_with_boxsize, demo_config, category_id="calculus")
    applied_root = etree.fromstring(applied_xml.encode("utf-8"))
    applied_inp = applied_root.find(".//question[@type='stack']/input[name='ans1']")
    assert applied_inp is not None
    # boxsize must reset to course default "15"
    assert applied_inp.findtext("boxsize") == "15"


def test_edit_feedback_html(demo_config: CourseConfig) -> None:
    """Editing feedback HTML in sketch updates feedback text in XML."""
    q_path = DEMO_DIR / "questions" / "calculus" / "demo-power-integral.xml"
    raw_xml = q_path.read_text(encoding="utf-8")
    sketch = xml_to_sketch(raw_xml, demo_config)

    old_fb = "<p>Correct! You correctly applied the power rule and included the constant of integration.</p>"
    new_fb = "<p>Outstanding work! Power rule mastered.</p>"
    assert old_fb in sketch

    edited_sketch = sketch.replace(old_fb, new_fb)
    applied_xml = apply_sketch(parse_sketch(edited_sketch), raw_xml, demo_config, category_id="calculus")

    root = etree.fromstring(applied_xml.encode("utf-8"))
    node0 = root.find(".//question[@type='stack']/prt[name='prt1']/node[name='0']")
    assert node0 is not None
    assert new_fb in node0.findtext("./truefeedback/text")


def test_edit_add_second_input(demo_config: CourseConfig) -> None:
    """Adding a second input in sketch adds <input> element to XML."""
    q_path = DEMO_DIR / "questions" / "calculus" / "demo-power-integral.xml"
    raw_xml = q_path.read_text(encoding="utf-8")
    sketch = xml_to_sketch(raw_xml, demo_config)

    old_inp = "ans1: algebraic, tans=ta1"
    new_inps = "ans1: algebraic, tans=ta1\nans2: numerical, tans=42"
    assert old_inp in sketch

    edited_sketch = sketch.replace(old_inp, new_inps)
    applied_xml = apply_sketch(parse_sketch(edited_sketch), raw_xml, demo_config, category_id="calculus")

    root = etree.fromstring(applied_xml.encode("utf-8"))
    q = root.find(".//question[@type='stack']")
    assert q is not None
    inps = q.findall("./input")
    assert len(inps) == 2
    assert inps[0].findtext("name") == "ans1"
    assert inps[1].findtext("name") == "ans2"
    assert inps[1].findtext("type") == "numerical"
    assert inps[1].findtext("tans") == "42"


def test_edit_remove_hint(demo_config: CourseConfig) -> None:
    """Removing the ## Hint section removes <hint> elements from XML."""
    q_path = DEMO_DIR / "questions" / "calculus" / "demo-power-integral.xml"
    raw_xml = q_path.read_text(encoding="utf-8")
    sketch = xml_to_sketch(raw_xml, demo_config)

    assert "## Hint" in sketch
    parts = sketch.split("## Hint")
    edited_sketch = parts[0]  # remove ## Hint and its text

    applied_xml = apply_sketch(parse_sketch(edited_sketch), raw_xml, demo_config, category_id="calculus")
    root = etree.fromstring(applied_xml.encode("utf-8"))
    assert len(root.findall(".//question[@type='stack']/hint")) == 0


def test_edit_set_penalty_in_front_matter(demo_config: CourseConfig) -> None:
    """Setting penalty = 0.2 in front matter formats XML as 0.2000000."""
    q_path = DEMO_DIR / "questions" / "calculus" / "demo-power-integral.xml"
    raw_xml = q_path.read_text(encoding="utf-8")
    sketch = xml_to_sketch(raw_xml, demo_config)

    # Insert penalty = 0.2 into front matter
    edited_sketch = sketch.replace('idnumber = "demo-power-integral"', 'idnumber = "demo-power-integral"\npenalty = 0.2')

    applied_xml = apply_sketch(parse_sketch(edited_sketch), raw_xml, demo_config, category_id="calculus")
    root = etree.fromstring(applied_xml.encode("utf-8"))
    q = root.find(".//question[@type='stack']")
    assert q is not None
    assert q.findtext("penalty") == "0.2000000"


# =========================================================================== #
# 4. Preservation of unknown tags, deployed seeds, and category headers
# =========================================================================== #


def test_preservation_survives_apply_unchanged(demo_config: CourseConfig) -> None:
    """Unknown tag inside <question> and inside <input>, plus all <deployedseed>

    elements and category headers, survive apply unchanged.
    """
    q_path = DEMO_DIR / "questions" / "calculus" / "demo-power-integral.xml"
    raw_xml = q_path.read_text(encoding="utf-8")

    # Inject unknown tags into XML
    root = etree.fromstring(raw_xml.encode("utf-8"))
    q = root.find(".//question[@type='stack']")
    assert q is not None
    etree.SubElement(q, "custom_question_tag").text = "preserve_me_q"

    inp = q.find("./input")
    assert inp is not None
    etree.SubElement(inp, "custom_input_tag").text = "preserve_me_inp"

    xml_with_custom = etree.tostring(root, encoding="utf-8").decode("utf-8")
    orig_seeds = [s.text for s in q.findall("./deployedseed")]
    orig_cats = [c.findtext("./category/text") for c in root.findall(".//question[@type='category']")]

    assert len(orig_seeds) == 20
    assert len(orig_cats) == 2

    # Round trip through sketch
    sketch = xml_to_sketch(xml_with_custom, demo_config)
    applied_xml = apply_sketch(parse_sketch(sketch), xml_with_custom, demo_config, category_id="calculus")

    applied_root = etree.fromstring(applied_xml.encode("utf-8"))
    applied_q = applied_root.find(".//question[@type='stack']")
    assert applied_q is not None

    # Verify custom tags survived
    assert applied_q.findtext("custom_question_tag") == "preserve_me_q"
    applied_inp = applied_q.find("./input")
    assert applied_inp is not None
    assert applied_inp.findtext("custom_input_tag") == "preserve_me_inp"

    # Verify all 20 deployed seeds survived
    new_seeds = [s.text for s in applied_q.findall("./deployedseed")]
    assert new_seeds == orig_seeds

    # Verify category headers survived
    new_cats = [c.findtext("./category/text") for c in applied_root.findall(".//question[@type='category']")]
    assert new_cats == orig_cats


# =========================================================================== #
# 5. Errors raise SketchError with correct .line
# =========================================================================== #


def test_error_missing_name() -> None:
    """Missing question name raises SketchError with line=1."""
    sketch = """+++
idnumber = "test"
+++

## Question text
<p>Solve: [[input:ans1]]</p>
"""
    with pytest.raises(SketchError) as exc_info:
        parse_sketch(sketch)
    assert exc_info.value.line == 1
    assert "front matter must set the question name" in exc_info.value.message


def test_error_invalid_toml_front_matter() -> None:
    """Invalid TOML in front matter raises SketchError with exact line."""
    sketch = """+++
name = "Test"
penalty = [
+++
"""
    with pytest.raises(SketchError) as exc_info:
        parse_sketch(sketch)
    assert exc_info.value.line == 3
    assert "invalid front matter" in exc_info.value.message


def test_error_unknown_front_matter_key() -> None:
    """Unknown front-matter key raises SketchError with exact line."""
    sketch = """+++
name = "Test"
nonexistent_setting = 123
+++
"""
    with pytest.raises(SketchError) as exc_info:
        parse_sketch(sketch)
    assert exc_info.value.line == 3
    assert "unknown setting 'nonexistent_setting'" in exc_info.value.message


def test_error_unknown_input_setting() -> None:
    """Unknown input setting raises SketchError with exact line."""
    sketch = """+++
name = "Test"
+++

## Question text
<p>[[input:ans1]]</p>

## Inputs
ans1: algebraic, tans=1, bogus_opt=true
"""
    with pytest.raises(SketchError) as exc_info:
        parse_sketch(sketch)
    assert exc_info.value.line == 9
    assert "unknown input setting 'bogus_opt'" in exc_info.value.message


def test_error_malformed_node_line() -> None:
    """Malformed node line raises SketchError with exact line."""
    sketch = """+++
name = "Test"
+++

## PRT prt1
node 0 without parens or colon
"""
    with pytest.raises(SketchError) as exc_info:
        parse_sketch(sketch)
    assert exc_info.value.line == 6
    assert "expected 'node N: Test" in exc_info.value.message


def test_error_unknown_answer_test_suggests_close_match() -> None:
    """Unknown answer test AlgEquv raises SketchError with close match AlgEquiv."""
    sketch = """+++
name = "Test"
+++

## PRT prt1
node 0: AlgEquv(ans1, ta1)
  true: =1
"""
    with pytest.raises(SketchError) as exc_info:
        parse_sketch(sketch)
    assert exc_info.value.line == 6
    assert "unknown answer test 'AlgEquv'" in exc_info.value.message
    assert "did you mean 'AlgEquiv'?" in exc_info.value.message


def test_error_unknown_answer_test_no_match() -> None:
    """Unknown answer test with no close match raises SketchError without suggestion."""
    sketch = """+++
name = "Test"
+++

## PRT prt1
node 0: CompletelyBogusTestName(ans1, ta1)
  true: =1
"""
    with pytest.raises(SketchError) as exc_info:
        parse_sketch(sketch)
    assert exc_info.value.line == 6
    assert "unknown answer test 'CompletelyBogusTestName'" in exc_info.value.message
    assert "did you mean" not in exc_info.value.message


def test_error_missing_node_reference() -> None:
    """-> 9 referencing a missing node raises SketchError with exact line."""
    sketch = """+++
name = "Test"
+++

## PRT prt1
node 0: AlgEquiv(ans1, ta1)
  true: =1
  false: -> 9
"""
    with pytest.raises(SketchError) as exc_info:
        parse_sketch(sketch)
    # The branch line with `false: -> 9` is line 8
    assert exc_info.value.line == 8
    assert "node 0 branches to node 9, which does not exist in prt1" in exc_info.value.message


# =========================================================================== #
# 6. Edge cases
# =========================================================================== #


def test_edge_case_html_special_chars(demo_config: CourseConfig) -> None:
    """HTML containing ]]>, <, & round trips without corruption."""
    sketch = """+++
name = "HTML Edge Cases"
+++

## Question text
<p>Inequality: 0 < x && x < 10 &amp; special tag <br/> and CDATA closing marker ]]> verbatim.</p>
<p>[[input:ans1]] [[validation:ans1]]</p>

## Inputs
ans1: algebraic, tans=5

## PRT prt1
node 0: AlgEquiv(ans1, 5)
  true: =1
"""
    model = parse_sketch(sketch)
    xml = apply_sketch(model, None, demo_config, category_id="calculus")

    # Round trip back to sketch
    sketch2 = xml_to_sketch(xml, demo_config)
    assert "<p>Inequality: 0 < x && x < 10 &amp; special tag <br/> and CDATA closing marker ]]> verbatim.</p>" in sketch2


def test_edge_case_maxima_hash_lines(demo_config: CourseConfig) -> None:
    """Maxima containing a line starting with '## ' inside the fence is not treated as section heading."""
    sketch = r"""+++
name = "Maxima Hash Line"
+++

## Question variables
```maxima
/* Maxima comment */
## line starting with double hash inside fence
x: 10;
y: 20;
```

## Question text
<p>Compute \(x+y\): [[input:ans1]] [[validation:ans1]]</p>

## Inputs
ans1: algebraic, tans=30

## PRT prt1
node 0: AlgEquiv(ans1, 30)
  true: =1
"""
    model = parse_sketch(sketch)
    assert "## line starting with double hash inside fence" in model.questionvariables
    assert len(model.prts) == 1

    xml = apply_sketch(model, None, demo_config, category_id="calculus")
    sketch2 = xml_to_sketch(xml, demo_config)
    assert "## line starting with double hash inside fence" in sketch2


def test_edge_case_input_commas_brackets_and_options_quoted(demo_config: CourseConfig) -> None:
    """Input value with commas/brackets (tans=[[1,true],[2,false]]) unquoted,

    and options value with spaces/commas JSON-quoted and round tripping.
    """
    sketch = """+++
name = "Complex Input Settings"
+++

## Question text
<p>Match the pairs: [[input:ans1]] [[validation:ans1]]</p>

## Inputs
ans1: checkbox, tans=[[1,true],[2,false]], options="align: left, size: 20"

## PRT prt1
node 0: AlgEquiv(ans1, 1)
  true: =1
"""
    model = parse_sketch(sketch)
    assert len(model.inputs) == 1
    inp = model.inputs[0]
    assert inp.name == "ans1"
    assert inp.type == "checkbox"
    assert inp.settings["tans"] == "[[1,true],[2,false]]"
    assert inp.settings["options"] == "align: left, size: 20"

    xml = apply_sketch(model, None, demo_config, category_id="calculus")
    sketch2 = xml_to_sketch(xml, demo_config)

    assert "tans=[[1,true],[2,false]]" in sketch2
    assert 'options="align: left, size: 20"' in sketch2


def test_edge_case_test_input_equation(demo_config: CourseConfig) -> None:
    """Test input that is an equation like ans1 = y=2*x parses and round trips."""
    sketch = """+++
name = "Equation Test Input"
+++

## Question text
<p>Find the equation: [[input:ans1]] [[validation:ans1]]</p>

## Inputs
ans1: algebraic, tans=y=2*x

## PRT prt1
node 0: AlgEquiv(ans1, y=2*x)
  true: =1

## Tests
### Test 1: Equation answer
ans1 = y=2*x
prt1 => 1, prt1-0-T
"""
    model = parse_sketch(sketch)
    assert model.tests is not None
    assert len(model.tests) == 1
    assert model.tests[0].inputs == [("ans1", "y=2*x")]

    xml = apply_sketch(model, None, demo_config, category_id="calculus")
    root = etree.fromstring(xml.encode("utf-8"))
    ti_val = root.findtext(".//question[@type='stack']/qtest/testinput[name='ans1']/value")
    assert ti_val == "y=2*x"

    sketch2 = xml_to_sketch(xml, demo_config)
    assert "ans1 = y=2*x" in sketch2


def test_edge_case_custom_answernote_with_spaces(demo_config: CourseConfig) -> None:
    """Custom answer note with spaces in PRT node and test round trips."""
    sketch = """+++
name = "Custom Answer Note"
+++

## Question text
<p>Solve: [[input:ans1]] [[validation:ans1]]</p>

## Inputs
ans1: algebraic, tans=1

## PRT prt1
node 0: AlgEquiv(ans1, 1)
  true: =1 note="custom note with spaces"

## Tests
### Test 1: Model answer
ans1 = 1
prt1 => 1, "custom note with spaces"
"""
    model = parse_sketch(sketch)
    assert model.prts[0].nodes[0].true.answernote == "custom note with spaces"
    assert model.tests is not None
    assert model.tests[0].expected[0].answernote == "custom note with spaces"

    xml = apply_sketch(model, None, demo_config, category_id="calculus")
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.findtext(".//question[@type='stack']/prt/node/trueanswernote") == "custom note with spaces"
    assert root.findtext(".//question[@type='stack']/qtest/expected/expectedanswernote") == "custom note with spaces"

    sketch2 = xml_to_sketch(xml, demo_config)
    assert 'note="custom note with spaces"' in sketch2
    assert 'prt1 => 1, "custom note with spaces"' in sketch2


def test_edge_case_node_testoptions_with_commas(demo_config: CourseConfig) -> None:
    """Node with testoptions containing commas preserves options."""
    sketch = """+++
name = "Testoptions with Commas"
+++

## Question text
<p>Solve: [[input:ans1]] [[validation:ans1]]</p>

## Inputs
ans1: algebraic, tans=1

## PRT prt1
node 0: NumRelative(ans1, 1, 0.05, true)
  true: =1
"""
    model = parse_sketch(sketch)
    node = model.prts[0].nodes[0]
    assert node.answertest == "NumRelative"
    assert node.sans == "ans1"
    assert node.tans == "1"
    assert node.testoptions == "0.05, true"

    xml = apply_sketch(model, None, demo_config, category_id="calculus")
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.findtext(".//question[@type='stack']/prt/node/testoptions") == "0.05, true"

    sketch2 = xml_to_sketch(xml, demo_config)
    assert "node 0: NumRelative(ans1, 1, 0.05, true)" in sketch2


def test_edge_case_quiet_node(demo_config: CourseConfig) -> None:
    """Node with 'quiet' keyword sets <quiet>1</quiet> in XML and round trips."""
    sketch = """+++
name = "Quiet Node"
+++

## Question text
<p>Solve: [[input:ans1]] [[validation:ans1]]</p>

## Inputs
ans1: algebraic, tans=1

## PRT prt1
node 0: AlgEquiv(ans1, 1)
  quiet
  true: =1
"""
    model = parse_sketch(sketch)
    assert model.prts[0].nodes[0].quiet == "1"

    xml = apply_sketch(model, None, demo_config, category_id="calculus")
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.findtext(".//question[@type='stack']/prt/node/quiet") == "1"

    sketch2 = xml_to_sketch(xml, demo_config)
    assert "  quiet" in sketch2


def test_edge_case_multi_prt_question(demo_config: CourseConfig) -> None:
    """Question with multiple PRTs renders, parses, applies and tests cleanly."""
    sketch = """+++
name = "Multi PRT Question"
+++

## Question text
<p>Part 1: [[input:ans1]] [[validation:ans1]]</p>
<p>Part 2: [[input:ans2]] [[validation:ans2]]</p>

## Specific feedback
<p>[[feedback:prt1]]</p>
<p>[[feedback:prt2]]</p>

## Inputs
ans1: algebraic, tans=1
ans2: algebraic, tans=2

## PRT prt1
node 0: AlgEquiv(ans1, 1)
  true: =1

## PRT prt2
node 0: AlgEquiv(ans2, 2)
  true: =1

## Tests
### Test 1: Both correct
ans1 = 1
ans2 = 2
prt1 => 1, prt1-0-T
prt2 => 1, prt2-0-T
"""
    model = parse_sketch(sketch)
    assert len(model.prts) == 2
    assert model.prts[0].name == "prt1"
    assert model.prts[1].name == "prt2"

    xml = apply_sketch(model, None, demo_config, category_id="calculus")
    root = etree.fromstring(xml.encode("utf-8"))
    prt_elems = root.findall(".//question[@type='stack']/prt")
    assert len(prt_elems) == 2
    assert prt_elems[0].findtext("name") == "prt1"
    assert prt_elems[1].findtext("name") == "prt2"

    sketch2 = xml_to_sketch(xml, demo_config)
    assert "## PRT prt1" in sketch2
    assert "## PRT prt2" in sketch2
    assert "prt1 => 1, prt1-0-T" in sketch2
    assert "prt2 => 1, prt2-0-T" in sketch2


def test_edge_case_new_question_from_sketch_base_xml_none(demo_config: CourseConfig) -> None:
    """New question from sketch with base_xml=None passes linter with no errors

    and has category headers.
    """
    sketch = r"""+++
name = "Brand New Question"
idnumber = "calc-brand-new"
+++

## Question variables
```maxima
a: rand(5) + 1;
ta1: a^2;
```

## Question text
<p>Calculate \({@a@}^2\):</p>
<p>[[input:ans1]] [[validation:ans1]]</p>

## Specific feedback
[[feedback:prt1]]

## Question note
{@a@}^2 = {@ta1@}

## Inputs
ans1: algebraic, tans=ta1

## PRT prt1
node 0: AlgEquiv(ans1, ta1)
  true: =1
    <p>Well done!</p>
  false: =0
    <p>Try again.</p>

## Tests
### Test 1: Model answer
ans1 = ta1
prt1 => 1, prt1-0-T
"""
    model = parse_sketch(sketch)
    xml = apply_sketch(model, None, demo_config, category_id="calculus")

    # 1. Passes static linter with 0 errors
    issues = lint_question(xml)
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 0, f"Lint errors: {errors}"

    # 2. Contains category headers
    root = etree.fromstring(xml.encode("utf-8"))
    cat_elems = root.findall(".//question[@type='category']")
    assert len(cat_elems) >= 1
    cat_texts = [c.findtext("./category/text") for c in cat_elems]
    assert any("Calculus" in t for t in cat_texts)


def test_sketch_file_and_apply_text_to_file(tmp_path: Path, demo_config: CourseConfig) -> None:
    """Convenience helpers sketch_file and apply_text_to_file work on filesystem."""
    q_path = DEMO_DIR / "questions" / "calculus" / "demo-power-integral.xml"
    sketch_str = sketch_file(q_path, demo_config)
    assert 'name = "Indefinite Integral of a Polynomial"' in sketch_str

    target_file = tmp_path / "calculus" / "test-applied.xml"
    changed = apply_text_to_file(sketch_str, target_file, demo_config)
    assert changed is True
    assert target_file.exists()

    # Second apply without changes returns False
    changed_again = apply_text_to_file(sketch_str, target_file, demo_config)
    assert changed_again is False


def test_answer_test_moodle_aliases_suggestions() -> None:
    """Moodle UI dropdown labels and aliases suggest the canonical STACK answer test."""
    cases = [
        ("CompletedSquare", "CompSquare", "Moodle UI dropdown label"),
        ("Num-GT", "GT", "Moodle UI dropdown label"),
        ("UnitsSigFigs", "Units", "Moodle UI dropdown label"),
        ("StrictSigFigs", "SigFigsStrict", "STACK documentation alias"),
    ]
    for alias, canonical, reason in cases:
        sketch = f"""+++
name = "Test"
+++

## PRT prt1
node 0: {alias}(ans1, ta1)
  true: =1
"""
        with pytest.raises(SketchError) as exc_info:
            parse_sketch(sketch)
        msg = exc_info.value.message
        assert f"unknown answer test '{alias}'" in msg
        assert f"did you mean '{canonical}'?" in msg
        assert reason in msg


def test_antidiff_and_addconst_roundtrip(demo_config: CourseConfig) -> None:
    """Antidiff and AddConst answer tests parse, serialize, and round-trip cleanly."""
    sketch = """+++
name = "Calculus Tests"
idnumber = "calc-roundtrip"
+++

## Question variables
```maxima
ta1: x^2/2;
```

## Question text
Antiderivative: [[input:ans1]] [[validation:ans1]]
[[feedback:prt1]]
[[feedback:prt2]]

## Specific feedback
[[feedback:prt1]]
[[feedback:prt2]]

## Inputs
ans1: algebraic, tans=ta1

## PRT prt1
node 0: Antidiff(ans1, ta1, x)
  true: =1 -> end
  false: =0 -> end

## PRT prt2
node 0: AddConst(ans1, ta1, [x])
  true: =1 -> end
  false: =0 -> end
"""
    model = parse_sketch(sketch)
    assert len(model.prts) == 2
    assert model.prts[0].nodes[0].answertest == "Antidiff"
    assert model.prts[0].nodes[0].testoptions == "x"
    assert model.prts[1].nodes[0].answertest == "AddConst"
    assert model.prts[1].nodes[0].testoptions == "[x]"

    xml = apply_sketch(model, None, demo_config, category_id="calculus")
    root = etree.fromstring(xml.encode("utf-8"))
    nodes = root.findall(".//question[@type='stack']/prt/node")
    assert len(nodes) == 2
    assert nodes[0].findtext("answertest") == "Antidiff"
    assert nodes[0].findtext("testoptions") == "x"
    assert nodes[1].findtext("answertest") == "AddConst"
    assert nodes[1].findtext("testoptions") == "[x]"

    sketch2 = xml_to_sketch(xml, demo_config)
    assert "node 0: Antidiff(ans1, ta1, x)" in sketch2
    assert "node 0: AddConst(ans1, ta1, [x])" in sketch2

    model2 = parse_sketch(sketch2)
    assert model2.prts[0].nodes[0].answertest == "Antidiff"
    assert model2.prts[1].nodes[0].answertest == "AddConst"

