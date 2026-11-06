# STACK Question Sketch Format (`.stack.md`)

An authoritative reference for the `.stack.md` sketch format, converter semantics, and the `macstack edit`, `macstack sketch`, and `macstack apply` workflows.

---

## 1. Overview & Purpose

Moodle STACK question XML files are verbose: a standard question averages ~230 lines of XML, of which roughly ~30 lines carry actual author decisions (question text, variables, inputs, PRT logic, and tests). The remainder consists of boilerplate tags and default options.

The **sketch format** (`.stack.md`) provides a compact, human-readable, Markdown-shaped view of a STACK question:

- **XML is the single source of truth**: The `.xml` file is always canonical. Sketches are ephemeral, lossless views generated on demand or during live edit sessions.
- **Course defaults are hidden**: Any setting matching `macstack.toml` (or built-in STACK defaults) is omitted from the sketch. Deleting a line in the sketch resets that property to its course default.
- **Round-trip fidelity**: `apply(sketch(x), x)` produces XML that is byte-for-byte identical to running `macstack format x`.
- **Lossless preservation**: Anything not modelled by the sketch—such as `<question type="category">` category headers, `<deployedseed>` tags, and unrecognised XML attributes or tags—is preserved untouched from the existing XML.
- **Minimal git diffs**: If a field's value in the sketch matches the XML value modulo leading or trailing whitespace, the XML content is left completely untouched.

---

## 2. Worked Example

Below is the sketch of `examples/demo/questions/calculus/demo-power-integral.xml` generated against `examples/demo/macstack.toml`:

````markdown
+++
# macstack sketch of demo-power-integral.xml
# Settings equal to the course defaults are hidden; delete a line to reset it.
# 20 deployed seeds are preserved (manage with `macstack deploy-seeds`).
name = "Indefinite Integral of a Polynomial"
idnumber = "demo-power-integral"
+++

## Question variables
```maxima
/* Indefinite integral using the power rule */
a: rand([2, 3, 4, 5, 6]);
b: rand([2, 4, 6, 8]);
n: rand([2, 3, 4]);

integrand: a*x^n + b*x;
ta1: a*x^(n+1)/(n+1) + (b/2)*x^2 + c;

/* Common misconceptions */
ans_diff: diff(integrand, x);
ans_no_c: a*x^(n+1)/(n+1) + (b/2)*x^2;
```

## Question text
<p>Evaluate the indefinite integral:</p>
\[ \int \left( {@integrand@} \right) \, dx \]
<p><em>Use \(c\) for the constant of integration.</em></p>
<p>[[input:ans1]] [[validation:ans1]]</p>

## Specific feedback
[[feedback:prt1]]

## General feedback
<p>Apply the power rule for integration term by term:</p>
\[ \int x^k \, dx = \frac{x^{k+1}}{k+1} + c \quad (k \neq -1) \]
<p>For the given integrand:</p>
\[ \int \left( {@integrand@} \right) \, dx = {@a@} \cdot \frac{x^{{@n+1@}}}{{@n+1@}} + {@b@} \cdot \frac{x^2}{2} + c \]
\[ = {@ta1@} \]

## Question note
{@ta1@}

## Inputs
ans1: algebraic, tans=ta1

## PRT prt1
node 0: Int(ans1, ta1, x)
  true: =1
    <p>Correct! You correctly applied the power rule and included the constant of integration.</p>
  false: -> 1
node 1: AlgEquiv(ans1, ans_diff)
  true: =0
    <p>It appears you differentiated the integrand rather than integrating it. Remember that \(\int x^n \, dx = \frac{x^{n+1}}{n+1} + c\).</p>

## Tests
### Test 1: Model Answer
ans1 = ta1
prt1 => 1, prt1-0-T

### Test 2: Differentiated Integrand
ans1 = ans_diff
prt1 => 0, prt1-1-T, penalty=0.1

### Test 3: Missing Constant of Integration
ans1 = ans_no_c
prt1 => 0, prt1-1-F, penalty=0.1

## Hint
<p>Integrate each power term using \(\int x^n \, dx = \frac{x^{n+1}}{n+1}\) and don't forget to add \(+ c\).</p>
````

---

## 3. Section Reference & Syntax

A sketch consists of TOML front matter followed by top-level Markdown sections introduced by `## <Section Name>`.

### 3.1 Front Matter (`+++`)

Front matter is written in standard TOML enclosed between lines containing only `+++`. Comments starting with `#` are ignored on parse.

```toml
+++
name = "Indefinite Integral of a Polynomial"
idnumber = "demo-power-integral"
penalty = 0.2
+++
```

#### Fields & Types
- `name` (**required**): The question display title (string). Always emitted.
- `idnumber`: Question identifier slug (string).
- `defaultgrade`: Maximum mark for the question (float/integer, e.g. `1.0` or `2`).
- `penalty`: Penalty fraction per incorrect attempt (float/integer, e.g. `0.1`).
- `hidden`: Whether the question is hidden (integer `0` or `1`, or boolean).
- `stackversion`: STACK release version string (e.g. `"2025102100"`).
- `questionsimplify`: Global simplification flag (`1` or `0`).
- `assumepositive`: Assume variables $> 0$ in CAS (`0` or `1`).
- `assumereal`: Assume variables $\in \mathbb{R}$ in CAS (`0` or `1`).
- `decimals`: Decimal separator symbol (`"."` or `","`).
- `scientificnotation`: Scientific notation format (`"*10"`).
- `multiplicationsign`: Multiplication symbol (`"onum"`, `"dot"`, `"cross"`).
- `sqrtsign`: Square root rendering style (`"1"` or `"0"`).
- `complexno`: Imaginary unit symbol (`"i"` or `"j"`).
- `inversetrig`: Inverse trigonometric notation (`"cos-1"` or `"arccos"`).
- `logicsymbol`: Logic symbols format (`"lang"` or `"symbol"`).
- `matrixparens`: Matrix enclosing delimiters (`"["`, `"("`, etc.).
- `variantsselectionseed`: Specific variant seed string.
- `isbroken`: Mark question broken (`0` or `1`).

#### Rules
- Numeric settings are compared numerically (`0.1` equals `0.1000000`).
- Values matching the course configuration in `macstack.toml` (or built-in defaults) are omitted.
- Unknown front-matter keys trigger a line-numbered `SketchError`.

---

### 3.2 Rich Text Sections (Verbatim HTML)

Recognised section headings (case-insensitive):
- `## Question text` (`<questiontext>`)
- `## Specific feedback` (`<specificfeedback>`)
- `## General feedback` (`<generalfeedback>`)
- `## Question note` (`<questionnote>`)
- `## Question description` (`<questiondescription>`)
- `## PRT correct` (`<prtcorrect>`)
- `## PRT partially correct` (`<prtpartiallycorrect>`)
- `## PRT incorrect` (`<prtincorrect>`)

#### Syntax & Behavior
- The section body is **verbatim HTML** along with standard STACK CASText2 tags (`{@expr@}`, `{#expr#}`, `[[input:ans1]]`, `[[validation:ans1]]`, `[[feedback:prt1]]`).
- No CDATA tags or XML entity escaping (`&lt;`, `&amp;`) are needed; write raw HTML elements (`<p>`, `<div>`, `<ul>`, etc.) and MathJax math (`\(...\)`, `\[...\]`).
- Empty sections or sections matching `macstack.toml` defaults (such as standard `<prtcorrect>` feedback) are omitted on render.

---

### 3.3 CAS Sections

- `## Question variables`: Contains Maxima variable definitions.
- Per-PRT `feedback variables:`: Contains feedback-stage Maxima calculations.

#### Syntax
```markdown
## Question variables
```maxima
a: rand(5) + 2;
b: rand([2, 4, 6]);
ta1: a*x + b;
```
```

- Maxima code is enclosed in a ```` ```maxima ```` code fence. (The fence is optional when parsing, but always rendered by `macstack sketch`).
- Semicolons are required at the end of Maxima statements as usual.

---

### 3.4 Inputs Section (`## Inputs`)

Defines all input elements for the question, one per line:

```markdown
## Inputs
ans1: algebraic, tans=ta1, boxsize=15, forbidfloat=1
ans2: matrix, tans=M1, options="allowempty"
```

#### Syntax
```
<name>: [type], [key=value, ...]
```
- `<name>`: The input identifier (e.g. `ans1`). Must match an identifier token (`[A-Za-z_][A-Za-z0-9_]*`).
- `[type]`: Optional positional type or explicit `type=<name>`. If omitted, defaults to the `type` setting in `macstack.toml` (typically `algebraic`).
- `key=value` tokens: Any valid STACK input setting:
  - `tans`: Model teacher answer (required for each input).
  - `boxsize`: Width of the input box in characters (e.g. `15`).
  - `strictsyntax`: Require strict mathematical syntax (`1` or `0`).
  - `insertstars`: Auto-insert multiplication asterisks (`0`, `1`, `2`, `3`).
  - `syntaxhint`: Placeholder text shown in the input box.
  - `syntaxattribute`: Syntax hint behavior (`0` or `1`).
  - `forbidwords`: Comma-separated forbidden functions/words.
  - `allowwords`: Allowed words list.
  - `forbidfloat`: Reject floating-point numbers (`1` or `0`).
  - `requirelowestterms`: Require fractions in lowest terms (`1` or `0`).
  - `checkanswertype`: Verify student answer matches type of `tans` (`1` or `0`).
  - `mustverify`: Require student verification before grading (`1` or `0`).
  - `showvalidation`: Display parsed expression widget (`1`, `2`, `3`, or `0`).
  - `options`: Extra input options string.

#### Value Formatting & Escaping
- **Bracket-Aware Splitting**: Commas inside brackets, parentheses, or braces (`[...]`, `(...)`, `{...}`) do not split options. Expressions like `tans=[[1, true], [2, false]]` work without quoting.
- **JSON Quoting**: Values containing spaces, leading/trailing whitespace, or top-level commas outside brackets must be JSON-quoted (e.g. `options="align:left"`).

---

### 3.5 Potential Response Trees (`## PRT <name>`)

Each PRT begins with a `## PRT <name>` heading (e.g. `## PRT prt1`).

```markdown
## PRT prt1
value=1.0, autosimplify=1

feedback variables:
```maxima
err_diff: diff(ans1, x);
```

node 0: Int(ans1, ta1, x)
  description: Check integration with constant
  quiet
  true: =1 -> end penalty=0 note="CORRECT"
    <p>Well done!</p>
  false: -> 1
node 1: AlgEquiv(ans1, err_diff)
  true: =0 note=prt1-1-T
    <p>You differentiated instead of integrating.</p>
```

#### PRT Settings Line (Optional)
Directly beneath `## PRT <name>`, before any node or feedback variables:
```
value=1, autosimplify=1, feedbackstyle=1
```
Allowed keys: `value`, `autosimplify`, `feedbackstyle`. Defaults from `macstack.toml` are omitted.

#### Feedback Variables (Optional)
```markdown
feedback variables:
```maxima
/* Maxima statements executed only during PRT grading */
diff_ans: diff(ans1, x);
```
```

#### Node Definition
```
node <id>: <AnswerTest>(<sans>, <tans>[, <testoptions>])
```
- `<id>`: Unique node name within the PRT (typically integer `0`, `1`, `2`, ...).
- `<AnswerTest>`: STACK answer test. Validated against known tests (all 41 supported in STACK v4.11):
  `AlgEquiv`, `AlgEquivNouns`, `EqualComAss`, `EqualComAssRules`, `CasEqual`, `SameType`, `SubstEquiv`, `SysEquiv`, `Sets`, `Expanded`, `FacForm`, `SingleFrac`, `PartFrac`, `CompSquare`, `PropLogic`, `Equiv`, `EquivFirst`, `Diff`, `Int`, `Antidiff`, `AddConst`, `GT`, `GTE`, `NumAbsolute`, `NumRelative`, `NumSigFigs`, `NumDecPlaces`, `NumDecPlacesWrong`, `SigFigsStrict`, `Units`, `UnitsStrict`, `UnitsAbsolute`, `UnitsStrictAbsolute`, `UnitsRelative`, `UnitsStrictRelative`, `String`, `StringSloppy`, `Levenshtein`, `SRegExp`, `LowestTerms`, `Validator`.
  *(Typo detection provides helpful suggestions on unrecognized names, e.g. `AlgEquv` $\rightarrow$ `AlgEquiv`, `CompletedSquare` $\rightarrow$ `CompSquare`).*
  
  For complete documentation of test signatures, option lists, PRT design recipes, and common pitfalls, see the [STACK Question Sketch Authoring Guide & Answer Test Glossary](../../../../docs/sketch-authoring-guide.md).
- `<sans>`: Student answer expression or input variable name (e.g. `ans1`).
- `<tans>`: Teacher answer expression or variable (e.g. `ta1`).
- `<testoptions>`: Optional arguments (everything following the 2nd top-level comma).

#### Node Modifiers (Indented 2 Spaces)
- `description: <text>`: Author documentation note for this node.
- `quiet` or `quiet=1`: Suppress STACK's automatic test feedback banner.

#### Branches (`true:` and `false:`)
Indented 2 spaces under the node line:
```markdown
  true: =1 -> end penalty=0.1 note=custom_note
    <p>Branch feedback HTML indented 4 spaces.</p>
  false: -> 1
```

Branch tokens (in any order):
- **Score Mode & Value**: `=1`, `+0.5`, `-0.5`, `=0`.
  - Default for `true:` is `=1`.
  - Default for `false:` is `=0`.
- **Next Node Target**: `-> <target>` (e.g. `-> 1`, `-> end`).
  - Target must exist in the PRT, or be `end` (translated to `-1` in XML).
- **Penalty**: `penalty=<num>` (e.g. `penalty=0.1`).
- **Answer Note**: `note=<token>` or `note="quoted string"`.
  - If omitted, defaults to STACK standard `{prt}-{node}-T` (for `true:`) or `{prt}-{node}-F` (for `false:`).
  - Standard notes are omitted on sketch render and reconstructed automatically.
- **Branch Feedback**: Verbatim HTML indented **4 spaces** directly under the branch line. Stripped and dedented on parse.
- **Omission of Default Branches**: If a `false:` branch has default settings (`=0`, `-> end`, no penalty, default note, and no feedback), it can be omitted entirely from the sketch.

---

### 3.6 Tests Section (`## Tests`)

Defines `<qtest>` automated test cases for verifying question logic:

```markdown
## Tests
### Test 1: Model Answer
ans1 = ta1
prt1 => 1, prt1-0-T

### Test 2: Differentiated Integrand
ans1 = ans_diff
prt1 => 0, prt1-1-T, penalty=0.1

### Test 3: Custom Equation Test
ans1 = y = 2*x + 1
prt1 => 1, prt1-0-T
```

#### Syntax
- `### Test <case>[: <description>]`: Begins a test case.
- `<input_name> = <value>`: Specifies test inputs. The line splits on the *first* `=` after the variable identifier, correctly allowing mathematical equation answers (e.g. `ans1 = y = 2*x`).
- `<prt_name> => <score>, <note>[, penalty=<val>]`: Specifies expected PRT outcome:
  - `<score>`: Expected score (e.g. `1`, `0`, `0.5`).
  - `<note>`: Expected answer note (e.g. `prt1-0-T`).
  - `penalty=<val>`: Optional expected penalty (omitted if `0`).

---

### 3.7 Hints (`## Hint`)

Repeatable section for adding student hints:

```markdown
## Hint
<p>First find the common denominator.</p>

## Hint
<p>Remember to reduce your final fraction to lowest terms.</p>
```

Each `## Hint` section maps to a `<hint format="html">` element in the XML in positional order.

---

## 4. Round-Trip Semantics & Guarantees

1. **Idempotence**:
   Applying a sketch to its original XML produces an output that matches `macstack format <file.xml>` byte-for-byte:
   $$\text{apply}(\text{sketch}(X), X) \equiv \text{format}(X)$$
2. **Absent = Default**:
   Any setting, text section, or branch omitted from the sketch is reset to the default specified in `macstack.toml` (or STACK built-ins). Deleting a line in `.stack.md` restores that default.
3. **Preservation of Unmodelled XML**:
   Elements not exposed in the sketch format are carried through untouched from the base XML:
   - `<question type="category">` categories and descriptions.
   - `<deployedseed>` tags generated by `macstack deploy-seeds`.
   - Custom XML attributes, unknown tags, or unmodelled child tags of inputs/nodes.
4. **Minimal Diffs**:
   If a text field in the sketch matches the XML content after stripping leading and trailing whitespace, the existing XML text node and CDATA block are retained byte-for-byte.

---

## 5. CLI Workflows

### 5.1 `macstack sketch`

Export a question XML file to a sketch:

```bash
# Output to stdout
macstack sketch questions/calculus/demo-power-integral.xml

# Save to a sketch file
macstack sketch questions/calculus/demo-power-integral.xml -o questions/calculus/demo-power-integral.stack.md
```

### 5.2 `macstack apply`

Apply a sketch file onto an XML file (updating existing XML or creating a new file):

```bash
macstack apply questions/calculus/demo-power-integral.stack.md questions/calculus/demo-power-integral.xml
```

- Parses the sketch, validates syntax, answer test names, and PRT node jump references.
- On error: prints `file:line: error message` and exits with code `1`. The target XML file is **never modified** if a parse error occurs.
- On success: updates the XML file with clean formatting and outputs a lint summary.

### 5.3 `macstack edit` (Interactive Live Session)

Launch a live, watch-mode editing session in your editor of choice:

```bash
macstack edit questions/calculus/demo-power-integral.xml
```

#### Session Flow
```
User / Editor              macstack edit             Target XML            macstack preview
     │                           │                        │                       │
     │ ──── Launches ──────────> │                        │                       │
     │                           │ ── Reads XML ────────> │                       │
     │ <── Opens .stack.md ───── │                        │                       │
     │                           │                        │                       │
     │ ──── Saves sketch ──────> │                        │                       │
     │                           │ ── Applies edits ────> │                       │
     │                           │                        │ ── SSE Hot Reload ──> │
     │                           │                        │                       │
     │ ──── Ctrl-C / Exit ─────> │                        │                       │
     │                           │ ── Cleans .stack.md ─> │                       │
```

#### Behavior & Features
1. **Session File Location**:
   The sketch is placed under `<course-root>/.macstack/edit/<relative-path>.stack.md`.
   When the `.macstack/` directory is created, `macstack` automatically writes a self-ignoring `.macstack/.gitignore` containing `*` (without modifying the project's root `.gitignore`).
2. **Editor Resolution Precedence**:
   1. Command-line flag: `--editor <cmd>` or `-e <cmd>`.
   2. Course config: `[edit] editor = "..."` in `macstack.toml`.
   3. Environment variable `$VISUAL`.
   4. Environment variable `$EDITOR`.
   5. If none configured, prints the absolute sketch file path and monitors it.
   *(Use `--no-open` to avoid launching an editor process while keeping the watcher active).*
3. **Blocking vs Launcher Editors**:
   - **Launchers** (e.g. `code`, `subl`, `open`): If the editor command returns within ~1.5 seconds with exit code `0`, `macstack edit` treats it as a background launcher and keeps the watch loop running until the user presses `Ctrl-C`.
   - **Blocking/Terminal Editors** (e.g. `vim`, `nano`, `code --wait`): The session runs until the editor exits. Terminal output is buffered during the editor session to prevent screen corruption.
4. **Live Preview Sync**:
   Every save of the `.stack.md` file triggers an immediate parse and update of the XML file. If `macstack preview` is running in another terminal or browser tab, the question reloads instantly via Server-Sent Events (SSE).
5. **Robust Error & Conflict Handling**:
   - **Syntax Errors**: If you save an invalid sketch (e.g. a typo in an answer test name or a missing parenthesis), `macstack edit` prints the exact line number and error message. **The target XML file is left untouched**.
   - **External XML Changes**: If the XML is modified externally (e.g. by running `macstack deploy-seeds` or a git pull):
     - If the sketch has no unsaved changes, it is automatically regenerated.
     - If the sketch has pending edits, a warning is printed, and your next save will apply on top of the latest XML.
6. **Leftover Sketch Detection**:
   If an existing session file is found at startup (due to a previous crash or concurrent session), `macstack edit` prompts whether to **resume** (apply existing sketch), **discard** (overwrite with XML), or **abort**.
7. **Clean Exit**:
   On session exit (Ctrl-C or editor quit), a final sync is performed and the temporary session sketch is deleted (unless the last save had a parse error, in which case the sketch is kept so work is not lost).

---

## 6. Current Limitations

- **Verbatim HTML (No Markdown $\rightarrow$ HTML conversion)**: Text sections (`Question text`, feedback, hints) contain verbatim HTML and CASText2 expressions. This ensures exact, lossless round-tripping of Moodle HTML, tags, and MathJax delimiters.
- **Categories Not Editable in Sketch**: Category hierarchies (`<question type="category">`) are managed at the XML and course level, not within individual question sketches.
- **One Question Per Sketch**: Each `.stack.md` file models a single `<question type="stack">`. Multi-question banks are combined or split using `macstack bundle` and `macstack split`.
- **Reserved Heading Syntax**: Lines starting with `## ` that match recognized section headings (`## Question text`, `## Inputs`, etc.) inside text content are interpreted as section headers. If a literal `## ` is needed in HTML, write it with an HTML entity or avoid leading `#` on a new line.
