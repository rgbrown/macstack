---
name: stack-authoring
description: Use when creating, editing, debugging, converting, testing, linting, or bundling Moodle STACK math questions or Moodle XML question banks. Covers authoring Maxima question variables, CASText2, PRTs (Potential Response Trees), input widgets, question test suites (<qtest>), deployed random seeds, and Moodle packaging.
---

# STACK Question Authoring with `macstack`

This skill provides an authoritative, end-to-end workflow for authoring, verifying, testing, and packaging computer-aided assessment questions for the **Moodle STACK** engine.

---

## 1. Workspace Discovery & Layout

Always inspect the current project root before creating or editing questions:

```bash
# Check project configuration and directory layout
ls -la questions/
cat macstack.toml 2>/dev/null || true
```

Standard workspace conventions:
- **Questions**: Plain-text XML files located at `questions/<category-slug>/<idnumber>.xml` (e.g. `questions/w01/w01-add-fractions.xml`).
- **Configuration**: `macstack.toml` sets the default Moodle category prefix, default Maxima timeout, and local dev preview port.
- **Single Question XML**: Each question `.xml` file contains its parent `<question type="category">` tag, making it self-contained and immediately importable into Moodle on its own.

---

## 2. Scaffolding & Editing Plain-Text XML

### Option A: Scaffold via CLI
```bash
macstack new questions/w02/w02-calc-derivative.xml \
  --name "Product Rule Derivative" \
  --category "MATH101::Week 2::Calculus"
```

### Option B: Author Minimal XML Directly
Write minimal STACK XML without boilerplate. Then run `macstack format` to auto-expand missing Moodle/STACK defaults:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<quiz>
  <question type="category">
    <category>
      <text>$course$/top/MATH101/Week 1/Fractions</text>
    </category>
  </question>
  <question type="stack">
    <name><text>Add/subtract fractions</text></name>
    <idnumber>w01-add-fractions</idnumber>
    <questionvariables>
      <text><![CDATA[
n1: rand([1, 2, 3, 5]);
d1: rand([2, 3, 4, 5, 7]);
n2: rand([1, 2, 3, 5]);
d2: rand_with_prohib(2, 7, [d1]);

f1: n1 / d1;
f2: n2 / d2;
tans: f1 + f2;
      ]]></text>
    </questionvariables>
    <questiontext format="html">
      <text><![CDATA[
<p>Calculate the exact sum of the following fractions, giving your answer in lowest terms:</p>
<p>\[ {@f1@} + {@f2@} \]</p>
<p>Answer: [[input:ans1]] [[validation:ans1]]</p>
      ]]></text>
    </questiontext>
    <generalfeedback format="html">
      <text><![CDATA[
<p>To add {@f1@} and {@f2@}, find the common denominator and simplify:</p>
<p>\[ {@f1@} + {@f2@} = {@tans@} \]</p>
      ]]></text>
    </generalfeedback>
    <questionnote>
      <text>{@f1@} + {@f2@} = {@tans@}</text>
    </questionnote>
    <input name="ans1">
      <type>algebraic</type>
      <tans>tans</tans>
      <boxsize>12</boxsize>
      <requirelowestterms>1</requirelowestterms>
    </input>
    <prt name="prt1">
      <node name="0">
        <answertest>LowestTerms</answertest>
        <sans>ans1</sans>
        <tans>tans</tans>
        <truescoremode>=</truescoremode>
        <truescore>1.0</truescore>
        <truenextnode>-1</truenextnode>
        <trueanswernote>prt1-1-T</trueanswernote>
        <truefeedback format="html">
          <text><![CDATA[<p>Correct! Well done.</p>]]></text>
        </truefeedback>
        <falsescoremode>=</falsescoremode>
        <falsescore>0.0</falsescore>
        <falsenextnode>1</falsenextnode>
        <falseanswernote>prt1-1-F</falseanswernote>
      </node>
      <node name="1">
        <answertest>AlgEquiv</answertest>
        <sans>ans1</sans>
        <tans>tans</tans>
        <truescoremode>=</truescoremode>
        <truescore>0.5</truescore>
        <truenextnode>-1</truenextnode>
        <trueanswernote>prt1-2-T</trueanswernote>
        <truefeedback format="html">
          <text><![CDATA[<p>Your answer is equivalent, but not in lowest terms. Please reduce your fraction.</p>]]></text>
        </truefeedback>
        <falsescoremode>=</falsescoremode>
        <falsescore>0.0</falsescore>
        <falsenextnode>-1</falsenextnode>
        <falseanswernote>prt1-2-F</falseanswernote>
      </node>
    </prt>
  </question>
</quiz>
```

Format and expand defaults:
```bash
macstack format questions/w01/w01-add-fractions.xml
```

---

## 3. Human-Readable Question Sketches (`macstack sketch` & `macstack apply`)

While STACK XML remains the canonical source of truth for repository storage and automated workflows, AI pair programmers should leverage the `.stack.md` sketch format when collaborating with human authors:

- **Presenting Questions for Human Review or Showing Diffs**:
  Use `macstack sketch` to produce a concise, Markdown-shaped view of a question. Because it hides XML boilerplate and course defaults (~30 lines vs ~230 lines of XML), it is ideal for reviewing question structure, explaining PRT logic, or presenting clean before/after diffs in chat:
  ```bash
  macstack sketch questions/w01/w01-add-fractions.xml
  ```
- **Applying User-Edited Sketches**:
  When a user provides edits, new PRT branches, or whole question drafts in `.stack.md` format, apply them back to the canonical XML file using `macstack apply`:
  ```bash
  macstack apply question.stack.md questions/w01/w01-add-fractions.xml
  ```
  `apply` validates answer test names, branch targets, and input options before updating the XML, while preserving all categories, deployed seeds, and unmodelled XML elements.

- **Terminal Quick Reference (`macstack ref`)**:
  Look up PRT branch syntax, input options, and all 41 answer test signatures without leaving the terminal:
  ```bash
  macstack ref prt          # PRT branch syntax, score modes, modifiers
  macstack ref inputs       # Input widgets, boxsize, options
  macstack ref tests        # All 41 answer tests grouped by category
  macstack ref Int          # Detailed signature and options for Int
  ```

> **Note**: Always maintain XML-first fidelity. The XML file is the canonical source of truth; sketches are ephemeral authoring and review views.

For full format syntax, grammar rules, PRT design recipes, and the complete Answer Tests glossary, consult:
- [STACK Question Sketch Authoring Guide & Answer Test Glossary](../../../docs/sketch-authoring-guide.md)
- [STACK Question Sketch Format Reference](./references/sketch-format.md)

---

## 4. Fast Verification Loop

Run fast command-line checks without launching a browser:

```bash
# 1. Lint the XML structure, variables, and PRT references
macstack lint questions/w01/w01-add-fractions.xml

# 2. Inspect evaluated CAS variables & questionnote
macstack vars questions/w01/w01-add-fractions.xml --seed 12345 --json

# 3. Simulate grading student input against the PRTs
# Full mark:
macstack grade questions/w01/w01-add-fractions.xml --seed 12345 -a ans1="3/4" --json
# Targeted misconception (e.g. not reduced):
macstack grade questions/w01/w01-add-fractions.xml --seed 12345 -a ans1="6/8" --json

# 4. Debug CAS expressions in interactive Maxima with STACK library preloaded
macstack maxima questions/w01/w01-add-fractions.xml
```

---

## 5. Mandatory Quality Gate

Before marking any STACK question complete, complete this 3-step quality checklist:

### Step 1: Add Comprehensive `<qtest>` Cases
Every STACK question **must** have authoring tests defined in `<qtest>`. Use `macstack add-test` or write them into XML:
- Test 1: Teacher's model answer (`tans`) $\rightarrow$ expected score `1.0`, expected note `prt1-1-T`.
- Test 2..N: Targeted misconceptions / common errors (e.g., forgotten constant of integration, unreduced fraction, sign error, inverted fraction) $\rightarrow$ expected score `0.0` or partial score, with exact expected note (e.g., `prt1-1-F`, `prt1-2-T`).

Example XML block:
```xml
<qtest>
  <testcase>1</testcase>
  <testinput>
    <name>ans1</name>
    <value>tans</value>
  </testinput>
  <expected>
    <name>prt1</name>
    <expectedscore>1.0000000</expectedscore>
    <expectedpenalty>0.0000000</expectedpenalty>
    <expectedanswernote>prt1-1-T</expectedanswernote>
  </expected>
</qtest>
```

### Step 2: Deploy Deduplicated Random Variants
If the question uses random variables (`rand`, `rand_with_step`, etc.), deploy at least **50 deduplicated variants**:

```bash
macstack deploy-seeds questions/w01/w01-add-fractions.xml --count 50
```

This samples 50 distinct seeds evaluated through Maxima, checks `questionnote` uniqueness to prevent duplicate variants, and writes `<deployedseed>` tags directly into the XML.

### Step 3: Run Full Test Suite Across All Deployed Seeds
Verify that no seed causes a division-by-zero, domain error, or PRT crash, and that all test cases pass:

```bash
macstack test questions/w01/w01-add-fractions.xml --json
```

**Target**: `0` CAS runtime errors, `100%` test pass rate across all deployed seeds.

---

## 6. Live-Reload Browser Preview

Launch the visual workbench to test the authentic student and teacher experience:

```bash
macstack preview
# or preview a specific question directly:
macstack preview questions/w01/w01-add-fractions.xml
```

Key workbench features:
- **Hot Reload**: Editing the `.xml` in your editor instantly refreshes the browser view via Server-Sent Events, preserving your currently typed answers and test states.
- **Roll / Select Seeds**: Test different randomized variants and edge cases with one click.
- **Fill Correct (`tans`)**: Instantly populates student inputs with the teacher's model answer.
- **Author Inspector**: Inspect evaluated Maxima variables, step-by-step PRT trace notes, lint diagnostics, and `<qtest>` suite outcomes.

---

## 7. Packaging for Moodle

### Single Question Import
Because each XML file formatted by `macstack` includes its category path header, you can upload any single `.xml` directly to Moodle:
- Navigate to **Course $\rightarrow$ Question Bank $\rightarrow$ Import**.
- Choose format: **Moodle XML format**.
- Select the `.xml` file and click **Import**.

### Course or Week Bundle
To combine all questions in a folder or week into a single uploadable `.xml` archive:

```bash
macstack bundle questions/w01/ -o dist/week-01-all-questions.xml
```

---

## Reference Guides
For deep syntax rules on Maxima functions, `simp:false` patterns, CASText2 tokens, input types, and PRT answer tests, consult:
- [STACK Question Sketch Authoring Guide & Answer Test Glossary](../../../docs/sketch-authoring-guide.md)
- [STACK XML and Maxima Reference Guide](./references/stack-xml-and-maxima-guide.md)
- [STACK Question Sketch Format Reference](./references/sketch-format.md)
