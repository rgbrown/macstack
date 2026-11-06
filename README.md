# macstack

> **Status: Alpha** — Under active development and testing.

**macstack** is a local plain-text authoring, testing, live-reload preview workbench, and Maxima CAS toolkit for Moodle STACK math questions, designed for university educators.

---

## Key Features

- **Plain-Text XML Authoring**: Author questions in your favorite editor (VS Code, Cursor, Neovim) without navigating complex Moodle web forms.
- **Instant Live-Reload Workbench**: Interactive split-pane browser environment with authentic Moodle fidelity, MathJax 3 rendering, and SSE hot reload on file save.
- **Rigorous Verification & Quality Gates**: Command-line linter, CAS variable evaluator, PRT response grader, and `<qtest>` regression test runner across randomized variants.
- **Seed Deployment**: One-command sampling and deduplication of 50+ random variants directly into `<deployedseed>` tags.
- **Interactive Maxima REPL (`rmaxima`)**: Launch Maxima with STACK's evaluation environment and question variables pre-loaded for quick CAS debugging.
- **Single-File & Bundle Moodle Import**: Every XML file includes its parent category hierarchy for direct drag-and-drop import into Moodle's Question Bank, or bundle an entire course/week in one step.
- **Human-Readable Sketch Editing (`.stack.md`)**: Author questions in a concise, Markdown-shaped sketch format that hides default boilerplate (~30 lines vs ~230 lines of XML), paired with live watch-mode editing (`macstack edit`) that syncs back to canonical XML on save.
- **AI Agent Skill**: Built-in `.agents/skills/stack-authoring/` empowering AI pair programmers to author and verify STACK questions adhering to best practices.

---

## Quickstart

### 1. Installation

Install and run using [`uv`](https://docs.astral.sh/uv/) (recommended):

```bash
cd /Users/rgbrown/work/teaching/macstack
uv sync
```

Or install in editable mode:
```bash
pip install -e .
```

Ensure Maxima is installed on macOS (e.g., via Homebrew):
```bash
brew install maxima
```

### 2. Scaffold a New Question

```bash
# Create a new question with category header
macstack new questions/w01/w01-add-fractions.xml \
  --name "Add/subtract fractions" \
  --category "MATH101::Week 1::Fractions"
```

### 3. Launch the Live-Reload Preview Workbench

```bash
macstack preview
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser. As you edit XML files in `questions/`, the workbench automatically reloads, preserving your test answers and grading state.

---

## CLI Command Reference

| Command | Description | Example |
| :--- | :--- | :--- |
| `macstack new` | Scaffold a new STACK question XML with defaults | `macstack new questions/w01/q1.xml` |
| `macstack edit` | Start live watch-mode editing session in any editor | `macstack edit questions/w01/q1.xml` |
| `macstack ref` | Look up .stack.md syntax, PRT rules, and Answer Tests | `macstack ref Int` |
| `macstack sketch` | Export question XML to human-readable `.stack.md` sketch | `macstack sketch questions/w01/q1.xml` |
| `macstack apply` | Apply a `.stack.md` sketch back to question XML | `macstack apply q1.stack.md questions/w01/q1.xml` |
| `macstack format` | Format XML, indent cleanly, and expand category headers | `macstack format questions/w01/q1.xml` |
| `macstack lint` | Check XML structure, CAS syntax, and deployed seeds | `macstack lint questions/w01/q1.xml` |
| `macstack vars` | Evaluate and display question variables and note | `macstack vars questions/w01/q1.xml --seed 123` |
| `macstack grade` | Simulate grading student answers against PRTs | `macstack grade questions/w01/q1.xml -a ans1="3/4"` |
| `macstack test` | Execute `<qtest>` suite across all deployed seeds | `macstack test questions/w01/q1.xml --json` |
| `macstack deploy-seeds` | Generate and write 50 deduplicated random variants | `macstack deploy-seeds questions/w01/q1.xml -n 50` |
| `macstack bundle` | Combine questions in a folder into a single XML file | `macstack bundle questions/w01/ -o dist/w01.xml` |
| `macstack maxima` | Start an interactive Maxima REPL with question loaded | `macstack maxima questions/w01/q1.xml` |
| `macstack preview` | Start local HTTP preview server with live SSE reload | `macstack preview [path.xml] --port 8000` |

---

## Live-Reload Browser Workbench

The workbench (`src/macstack/web/`) provides a clean, academic-grade developer UI:

- **Split-Pane Layout**:
  - **Left Sidebar**: Question bank navigator, search filtering, and variant/test/warning status badges.
  - **Center Canvas**: Authentic Moodle question card rendering with MathJax 3 LaTeX, dynamic gnuplot SVG plots, interactive input widgets, live validation feedback, and PRT score banners.
  - **Right Inspector Drawer**:
    - **Variables**: Evaluated CAS variables (`{#...#}`) and LaTeX displays (`{@...@}`).
    - **PRT Trace**: Step-by-step decision tree execution and answer note chips (`prt1-1-T`, `prt1-1-F`).
    - **Diagnostics**: Real-time lint warnings and CAS runtime error messages.
    - **Tests**: One-click `<qtest>` test execution across all deployed seeds.
- **Toolbar Utilities**:
  - **Seed Selector & Roll**: Switch between deployed seeds or roll random variants.
  - **Deploy 50 Seeds**: Automatically sample and write 50 variants to XML without leaving the browser.
  - **Fill Model Answer (`tans`)**: One-click auto-fill of correct solutions for rapid PRT testing.

---

## Sketch Editing (`.stack.md`)

Raw STACK XML files are verbose (~230 lines for a typical question, with ~30 lines carrying author decisions). The `.stack.md` sketch format provides a compact, human-readable view hiding course defaults while keeping the XML as the canonical source of truth:

````markdown
+++
name = "Indefinite Integral of a Polynomial"
idnumber = "demo-power-integral"
+++

## Question variables
```maxima
a: rand([2, 3, 4, 5, 6]);
b: rand([2, 4, 6, 8]);
integrand: a*x^2 + b*x;
ta1: a*x^3/3 + (b/2)*x^2 + c;
ans_diff: diff(integrand, x);
```

## Question text
<p>Evaluate the indefinite integral:</p>
\[ \int \left( {@integrand@} \right) \, dx \]
<p>[[input:ans1]] [[validation:ans1]]</p>

## Inputs
ans1: algebraic, tans=ta1

## PRT prt1
node 0: Int(ans1, ta1, x)
  true: =1
    <p>Correct! You integrated correctly and included \(c\).</p>
  false: -> 1
node 1: AlgEquiv(ans1, ans_diff)
  true: =0
    <p>You differentiated the integrand rather than integrating it.</p>

## Tests
### Test 1: Model Answer
ans1 = ta1
prt1 => 1, prt1-0-T
````

### Side-by-Side Live Edit & Preview Workflow

Run `macstack edit` alongside `macstack preview` for an instant feedback loop:

1. **Terminal 1**: Launch the live preview workbench:
   ```bash
   macstack preview questions/w01/
   ```
2. **Terminal 2**: Start an edit session in your preferred editor (VS Code, Cursor, Neovim, etc.):
   ```bash
   macstack edit questions/w01/w01-add-fractions.xml --editor code
   ```
3. **Save and preview**: Every time you save the sketch in your editor, `macstack edit` validates syntax and synchronizes changes back to the XML. The browser workbench reloads instantly via Server-Sent Events (SSE). If a parse error occurs, the line-numbered error is shown in the terminal while your XML remains untouched.

For an instructor-friendly, practical guide covering PRT design recipes, input widgets, and a comprehensive glossary of all 41 answer tests, see the [Sketch Authoring Guide & Answer Test Glossary](./docs/sketch-authoring-guide.md). You can also look up quick syntax and test cards in the terminal anytime using `macstack ref` (e.g. `macstack ref prt`, `macstack ref inputs`, `macstack ref Int`).

For the underlying format specification, see the [STACK Question Sketch Format Reference](./.agents/skills/stack-authoring/references/sketch-format.md).

---

## Interactive Maxima REPL (`rmaxima`)

To debug complex CAS logic, randomized domains, or controlled simplification (`simp:false`):

```bash
macstack maxima questions/w01/w01-add-fractions.xml
```

This starts `rmaxima` (with arrow-key history support) and pre-populates all variables defined in `<questionvariables>`. You can run Maxima functions interactively, inspect variable types, and test PRT logic directly in the CAS environment.

---

## Moodle Upload Workflow

### 1. Single Question Upload
Because each XML file formatted by `macstack` includes its full category path chain (e.g. `$course$/top/MATH101/Week 1`), you can upload any single `.xml` directly to Moodle without extra configuration:
1. Navigate to **Course $\rightarrow$ Question Bank $\rightarrow$ Import** in Moodle.
2. Select **Moodle XML format**.
3. Drag and drop `questions/w01/w01-add-fractions.xml` into the upload box and click **Import**.

### 2. Multi-Question Bundle
To export an entire week or assignment into a single file:
```bash
macstack bundle questions/w01/ -o dist/week-01-all-questions.xml
```

---

## AI Collaboration & Skill Usage

The repository includes a dedicated Antigravity agent skill located at:
```
.agents/skills/stack-authoring/
├── SKILL.md
└── references/
    ├── sketch-format.md
    └── stack-xml-and-maxima-guide.md
```

When pairing with an AI coding assistant, the agent automatically activates this skill to scaffold questions, design PRT branches with targeted feedback for common student misconceptions, deploy random seeds, and guarantee 100% test pass rates across all variants.
