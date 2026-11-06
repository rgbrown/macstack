"""Comprehensive programmatic reference catalog for Moodle STACK question authoring.

Provides structured metadata for all 41 STACK v4.11 answer tests, input types,
coded integer settings, front matter options, and CASText2 tokens, along with
Rich terminal rendering and JSON export for `macstack ref`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import typer

AnswerTestCategory = Literal[
    "equivalence",
    "form",
    "rules",
    "calculus",
    "numerical",
    "units",
    "string",
    "other",
]

OptionsStatus = Literal["required", "optional", "none"]


@dataclass(frozen=True)
class AnswerTestSpec:
    """Metadata specification for a STACK answer test."""

    name: str
    moodle_label: str
    category: AnswerTestCategory
    options_status: OptionsStatus
    options_syntax: str
    requires_raw_sans: bool
    ignores_tans: bool
    summary: str
    sketch_example: str
    gotchas: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "moodle_label": self.moodle_label,
            "category": self.category,
            "options_status": self.options_status,
            "options_syntax": self.options_syntax,
            "requires_raw_sans": self.requires_raw_sans,
            "ignores_tans": self.ignores_tans,
            "summary": self.summary,
            "sketch_example": self.sketch_example,
            "gotchas": list(self.gotchas),
        }


# --------------------------------------------------------------------------- #
# All 41 STACK v4.11 Answer Test Specifications
# --------------------------------------------------------------------------- #

ANSWER_TEST_SPECS: tuple[AnswerTestSpec, ...] = (
    # Equivalence (6)
    AnswerTestSpec(
        name="AlgEquiv",
        moodle_label="AlgEquiv",
        category="equivalence",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests whether student answer and teacher answer are algebraically equivalent after CAS evaluation.",
        sketch_example="node 0: AlgEquiv(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Requires CAS simplification; differences by 0 simplify to 0.",
            "Does not check mathematical form or style, only algebraic equality.",
        ),
    ),
    AnswerTestSpec(
        name="AlgEquivNouns",
        moodle_label="AlgEquivNouns",
        category="equivalence",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests algebraic equivalence without evaluating noun operators (e.g. noun 'diff', 'integrate').",
        sketch_example="node 0: AlgEquivNouns(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Prevents students from bypassing calculation by returning unevaluated calculus nouns.",
        ),
    ),
    AnswerTestSpec(
        name="SubstEquiv",
        moodle_label="SubstEquiv",
        category="equivalence",
        options_status="optional",
        options_syntax="[fixed_vars]",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests equivalence up to consistent variable renaming, optionally holding specified variables fixed.",
        sketch_example="node 0: SubstEquiv(ans1, ta1, [x])\n  true: =1\n  false: =0",
        gotchas=(
            "Variables listed in testoptions are kept fixed and cannot be substituted.",
            "Useful when dummy integration or summation variables may vary.",
        ),
    ),
    AnswerTestSpec(
        name="CasEqual",
        moodle_label="CasEqual",
        category="equivalence",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests whether expressions are identical in Maxima without simplification.",
        sketch_example="node 0: CasEqual(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Very strict: 'x+1' and '1+x' may not match if internal representation differs.",
            "Prefer AlgEquiv or EqualComAss in most questions.",
        ),
    ),
    AnswerTestSpec(
        name="SameType",
        moodle_label="SameType",
        category="equivalence",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Checks whether student answer has the same mathematical type as teacher answer (e.g. matrix, list, set, equation).",
        sketch_example="node 0: SameType(ans1, ta1)\n  true: -> 1\n  false: =0",
        gotchas=(
            "Only checks type structure, not value or algebraic equivalence.",
        ),
    ),
    AnswerTestSpec(
        name="SysEquiv",
        moodle_label="SysEquiv",
        category="equivalence",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Checks equivalence of systems of linear or algebraic equations or inequalities.",
        sketch_example="node 0: SysEquiv(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Expects lists or sets of equations as inputs.",
        ),
    ),
    # Form (6)
    AnswerTestSpec(
        name="FacForm",
        moodle_label="FacForm",
        category="form",
        options_status="required",
        options_syntax="var (e.g. x)",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests whether an expression is factored completely with respect to the specified variable.",
        sketch_example="node 0: FacForm(ans1, ta1, x)\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions specifying variable of factorisation (e.g. x).",
            "Also checks algebraic equivalence against tans.",
        ),
    ),
    AnswerTestSpec(
        name="PartFrac",
        moodle_label="PartFrac",
        category="form",
        options_status="required",
        options_syntax="var (e.g. x)",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests whether an expression is in partial fraction form with respect to the specified variable.",
        sketch_example="node 0: PartFrac(ans1, ta1, x)\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions specifying the variable (e.g. x).",
            "Also verifies algebraic equivalence against tans.",
        ),
    ),
    AnswerTestSpec(
        name="SingleFrac",
        moodle_label="SingleFrac",
        category="form",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests whether student's answer is written as a single algebraic fraction and is equivalent to tans.",
        sketch_example="node 0: SingleFrac(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Does not require options.",
            "Pair with LowestTerms if cancelled fractions are required.",
        ),
    ),
    AnswerTestSpec(
        name="CompSquare",
        moodle_label="CompletedSquare",
        category="form",
        options_status="required",
        options_syntax="var (e.g. x)",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests whether a quadratic expression is written in completed square form a*(x+b)^2+c with respect to var.",
        sketch_example="node 0: CompSquare(ans1, ta1, x)\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions specifying variable (e.g. x).",
            "Moodle UI dropdown displays 'CompletedSquare' instead of 'CompSquare'.",
        ),
    ),
    AnswerTestSpec(
        name="Expanded",
        moodle_label="Expanded",
        category="form",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=True,
        summary="Tests whether an expression is in expanded polynomial form.",
        sketch_example="node 0: Expanded(ans1, ta1)\n  true: -> 1\n  false: =0\nnode 1: AlgEquiv(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Ignores tans! Does NOT check algebraic equivalence on its own—pair with AlgEquiv.",
        ),
    ),
    AnswerTestSpec(
        name="LowestTerms",
        moodle_label="LowestTerms",
        category="form",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=True,
        summary="Tests whether numerical and algebraic fractions in an expression are in lowest terms (cancelled).",
        sketch_example="node 0: LowestTerms(ans1, ta1)\n  true: -> 1\n  false: =0\nnode 1: AlgEquiv(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Ignores tans! Does NOT check algebraic equivalence—pair with AlgEquiv or SingleFrac.",
        ),
    ),
    # Rules (2)
    AnswerTestSpec(
        name="EqualComAss",
        moodle_label="EqualComAss",
        category="rules",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests equality up to commutativity and associativity of addition and multiplication.",
        sketch_example="node 0: EqualComAss(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Does not expand brackets or simplify fractions; useful for unsimplified form checks.",
        ),
    ),
    AnswerTestSpec(
        name="EqualComAssRules",
        moodle_label="EqualComAssRules",
        category="rules",
        options_status="required",
        options_syntax="[rule1, ...] or ID_TRANS",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests equivalence modulo specific algebraic rewrite rules (e.g. ID_TRANS, NEG_TRANS, DIV_TRANS, INT_ARITH, oneMul, negOrd, sqrtRem).",
        sketch_example="node 0: EqualComAssRules(ans1, ta1, [ID_TRANS, INT_ARITH])\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions containing rule list or preset name like ID_TRANS.",
        ),
    ),
    # Calculus (4)
    AnswerTestSpec(
        name="Diff",
        moodle_label="Diff",
        category="calculus",
        options_status="required",
        options_syntax="var (e.g. x)",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests whether sans is the derivative of tans with respect to var (i.e. sans == diff(tans, var)).",
        sketch_example="node 0: Diff(ans1, ta1, x)\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions specifying differentiation variable (e.g. x).",
            "Note argument order: sans is compared against diff(tans, var).",
        ),
    ),
    AnswerTestSpec(
        name="Int",
        moodle_label="Int",
        category="calculus",
        options_status="required",
        options_syntax="var or [var, NOCONST, FORMAL, integrand]",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests whether sans is an antiderivative of tans, allowing an arbitrary constant of integration unless NOCONST is specified.",
        sketch_example="node 0: Int(ans1, ta1, x)\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions specifying variable or option list [var, ...].",
            "Differentiates student answer and compares derivative to tans or integrand.",
        ),
    ),
    AnswerTestSpec(
        name="Antidiff",
        moodle_label="Antidiff",
        category="calculus",
        options_status="required",
        options_syntax="var (e.g. x)",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Direct antiderivative test checking diff(sans, var) == tans.",
        sketch_example="node 0: Antidiff(ans1, ta1, x)\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions specifying differentiation variable (e.g. x).",
        ),
    ),
    AnswerTestSpec(
        name="AddConst",
        moodle_label="AddConst",
        category="calculus",
        options_status="required",
        options_syntax="[var, ...] or [var, NONSTRICT]",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests whether sans differs from tans by an additive constant with respect to specified variables.",
        sketch_example="node 0: AddConst(ans1, ta1, [x])\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions specifying variable list e.g. [x].",
        ),
    ),
    # Numerical (8)
    AnswerTestSpec(
        name="NumAbsolute",
        moodle_label="NumAbsolute",
        category="numerical",
        options_status="optional",
        options_syntax="tol (default 0.05)",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Checks whether |sans - tans| <= tol.",
        sketch_example="node 0: NumAbsolute(ans1, ta1, 0.01)\n  true: =1\n  false: =0",
        gotchas=(
            "Defaults to tolerance 0.05 if options are omitted.",
        ),
    ),
    AnswerTestSpec(
        name="NumRelative",
        moodle_label="NumRelative",
        category="numerical",
        options_status="optional",
        options_syntax="tol (default 0.05)",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Checks whether |sans - tans| / |tans| <= tol.",
        sketch_example="node 0: NumRelative(ans1, ta1, 0.02)\n  true: =1\n  false: =0",
        gotchas=(
            "Defaults to tolerance 0.05 if options are omitted.",
            "Fails if tans is 0 (division by zero).",
        ),
    ),
    AnswerTestSpec(
        name="NumSigFigs",
        moodle_label="NumSigFigs",
        category="numerical",
        options_status="required",
        options_syntax="n or [n, m] or [n, -1]",
        requires_raw_sans=True,
        ignores_tans=False,
        summary="Tests whether numerical answer has the required number of significant figures n, and numerical value within tolerance.",
        sketch_example="node 0: NumSigFigs(ans1, ta1, 3)\n  true: =1\n  false: =0",
        gotchas=(
            "sans MUST be a bare input variable (e.g. ans1) so Maxima does not strip trailing zeros.",
            "Requires options specifying sig figs count or [n, display_tol].",
        ),
    ),
    AnswerTestSpec(
        name="SigFigsStrict",
        moodle_label="SigFigsStrict",
        category="numerical",
        options_status="required",
        options_syntax="n",
        requires_raw_sans=True,
        ignores_tans=True,
        summary="Strict check that student's raw input has exactly n significant figures, ignoring numerical equivalence to tans.",
        sketch_example="node 0: SigFigsStrict(ans1, ta1, 3)\n  true: -> 1\n  false: =0\nnode 1: NumAbsolute(ans1, ta1, 0.01)\n  true: =1\n  false: =0",
        gotchas=(
            "Ignores tans! Does not check numerical correctness, only significant figure count.",
            "sans MUST be a bare input variable.",
        ),
    ),
    AnswerTestSpec(
        name="NumDecPlaces",
        moodle_label="NumDecPlaces",
        category="numerical",
        options_status="required",
        options_syntax="n",
        requires_raw_sans=True,
        ignores_tans=False,
        summary="Tests whether numerical answer has exactly n decimal places and matches tans within rounding tolerance.",
        sketch_example="node 0: NumDecPlaces(ans1, ta1, 2)\n  true: =1\n  false: =0",
        gotchas=(
            "sans MUST be a bare input variable so Maxima does not strip trailing zeros.",
            "Requires options specifying integer number of decimal places.",
        ),
    ),
    AnswerTestSpec(
        name="NumDecPlacesWrong",
        moodle_label="NumDecPlacesWrong",
        category="numerical",
        options_status="required",
        options_syntax="n",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Diagnostic test checking whether student gave answer to incorrect number of decimal places n.",
        sketch_example="node 0: NumDecPlacesWrong(ans1, ta1, 3)\n  true: =0\n  false: -> 1",
        gotchas=(
            "Used on feedback branches to detect students giving wrong precision.",
        ),
    ),
    AnswerTestSpec(
        name="GT",
        moodle_label="Num-GT",
        category="numerical",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests whether sans > tans numerically.",
        sketch_example="node 0: GT(ans1, 0)\n  true: =1\n  false: =0",
        gotchas=(
            "Moodle UI dropdown displays 'Num-GT'.",
            "Does not take options.",
        ),
    ),
    AnswerTestSpec(
        name="GTE",
        moodle_label="Num-GTE",
        category="numerical",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests whether sans >= tans numerically.",
        sketch_example="node 0: GTE(ans1, 0)\n  true: =1\n  false: =0",
        gotchas=(
            "Moodle UI dropdown displays 'Num-GTE'.",
            "Does not take options.",
        ),
    ),
    # Units (6)
    AnswerTestSpec(
        name="Units",
        moodle_label="UnitsSigFigs",
        category="units",
        options_status="required",
        options_syntax="n or [n, m]",
        requires_raw_sans=True,
        ignores_tans=False,
        summary="Tests physical quantities with units for numerical equivalence, unit compatibility, and significant figures.",
        sketch_example="node 0: Units(ans1, ta1, 3)\n  true: =1\n  false: =0",
        gotchas=(
            "Moodle UI dropdown displays 'UnitsSigFigs'.",
            "sans MUST be a bare input variable so unit strings and trailing zeros are preserved.",
        ),
    ),
    AnswerTestSpec(
        name="UnitsStrict",
        moodle_label="UnitsStrictSigFigs",
        category="units",
        options_status="required",
        options_syntax="n or [n, m]",
        requires_raw_sans=True,
        ignores_tans=False,
        summary="Strict units test requiring exact specified unit prefixes and significant figures.",
        sketch_example="node 0: UnitsStrict(ans1, ta1, 3)\n  true: =1\n  false: =0",
        gotchas=(
            "Moodle UI dropdown displays 'UnitsStrictSigFigs'.",
            "sans MUST be a bare input variable.",
        ),
    ),
    AnswerTestSpec(
        name="UnitsAbsolute",
        moodle_label="UnitsAbsolute",
        category="units",
        options_status="required",
        options_syntax="tol",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests quantity with units within absolute numerical tolerance tol.",
        sketch_example="node 0: UnitsAbsolute(ans1, ta1, 0.05)\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions specifying numerical tolerance.",
        ),
    ),
    AnswerTestSpec(
        name="UnitsStrictAbsolute",
        moodle_label="UnitsStrictAbsolute",
        category="units",
        options_status="required",
        options_syntax="tol",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests quantity with units within absolute numerical tolerance, rejecting unsimplified units.",
        sketch_example="node 0: UnitsStrictAbsolute(ans1, ta1, 0.05)\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions specifying numerical tolerance.",
        ),
    ),
    AnswerTestSpec(
        name="UnitsRelative",
        moodle_label="UnitsRelative",
        category="units",
        options_status="required",
        options_syntax="tol",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests quantity with units within relative numerical tolerance tol.",
        sketch_example="node 0: UnitsRelative(ans1, ta1, 0.02)\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions specifying relative tolerance (e.g. 0.02 for 2%).",
        ),
    ),
    AnswerTestSpec(
        name="UnitsStrictRelative",
        moodle_label="UnitsStrictRelative",
        category="units",
        options_status="required",
        options_syntax="tol",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests quantity with units within relative numerical tolerance, rejecting unsimplified or unreduced units.",
        sketch_example="node 0: UnitsStrictRelative(ans1, ta1, 0.02)\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions specifying relative tolerance.",
        ),
    ),
    # String (4)
    AnswerTestSpec(
        name="String",
        moodle_label="String",
        category="string",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests exact string equality including case and whitespace.",
        sketch_example="node 0: String(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Strict string matching; strips leading and trailing whitespace from answers.",
        ),
    ),
    AnswerTestSpec(
        name="StringSloppy",
        moodle_label="StringSloppy",
        category="string",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests case-insensitive string equality with normalised internal whitespace.",
        sketch_example="node 0: StringSloppy(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Normalises repeated spaces and ignores case.",
        ),
    ),
    AnswerTestSpec(
        name="Levenshtein",
        moodle_label="Levenshtein",
        category="string",
        options_status="required",
        options_syntax="tol or [tol, CASE, WHITESPACE]",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests string edit distance within an integer threshold, allowing typo tolerance.",
        sketch_example="node 0: Levenshtein(ans1, ta1, 2)\n  true: =1\n  false: =0",
        gotchas=(
            "Requires testoptions specifying max edit distance (integer).",
            "tans can be [allow_list, deny_list] for fine-grained spell check.",
        ),
    ),
    AnswerTestSpec(
        name="SRegExp",
        moodle_label="SRegExp",
        category="string",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests student string against regular expression in tans.",
        sketch_example='node 0: SRegExp(ans1, "^[a-z]+$")\n  true: =1\n  false: =0',
        gotchas=(
            "Replaced legacy RegExp in STACK 4.3.",
            "tans is treated as the regex pattern.",
        ),
    ),
    # Other (5)
    AnswerTestSpec(
        name="Sets",
        moodle_label="Sets",
        category="other",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests set equality ignoring element order and duplicate entries.",
        sketch_example="node 0: Sets(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Expects Maxima set notation {a, b, c}.",
        ),
    ),
    AnswerTestSpec(
        name="PropLogic",
        moodle_label="PropositionalLogic",
        category="other",
        options_status="none",
        options_syntax="",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Tests logical equivalence of boolean propositional expressions.",
        sketch_example="node 0: PropLogic(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Moodle UI dropdown displays 'PropositionalLogic'.",
            "Uses Maxima logic package.",
        ),
    ),
    AnswerTestSpec(
        name="Equiv",
        moodle_label="EquivReasoning",
        category="other",
        options_status="optional",
        options_syntax="[opt, ...]",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Validates multi-line step-by-step equivalence reasoning chains.",
        sketch_example="node 0: Equiv(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Moodle UI dropdown displays 'EquivReasoning'.",
            "Requires equiv input type.",
        ),
    ),
    AnswerTestSpec(
        name="EquivFirst",
        moodle_label="EquivFirst",
        category="other",
        options_status="optional",
        options_syntax="[opt, ...]",
        requires_raw_sans=False,
        ignores_tans=False,
        summary="Validates equivalence reasoning chain against first step of tans.",
        sketch_example="node 0: EquivFirst(ans1, ta1)\n  true: =1\n  false: =0",
        gotchas=(
            "Similar to Equiv but anchors to first step of reasoning.",
        ),
    ),
    AnswerTestSpec(
        name="Validator",
        moodle_label="Validator",
        category="other",
        options_status="required",
        options_syntax="validator_fn",
        requires_raw_sans=False,
        ignores_tans=True,
        summary="Runs custom Maxima predicate function in testoptions against sans.",
        sketch_example="node 0: Validator(ans1, none, is_prime)\n  true: =1\n  false: =0",
        gotchas=(
            "Ignores tans! Put 'none' or any dummy value for tans.",
            "Requires testoptions containing the custom predicate function name.",
        ),
    ),
)

#: All 41 answer test names supported by STACK 4.11.
ANSWER_TESTS: frozenset[str] = frozenset(s.name for s in ANSWER_TEST_SPECS)

#: Map from canonical answer test name to specification.
ANSWER_TEST_BY_NAME: dict[str, AnswerTestSpec] = {s.name: s for s in ANSWER_TEST_SPECS}

#: Aliases mapping lowercase alias to (canonical_name, reason).
ANSWER_TEST_ALIASES: dict[str, tuple[str, str]] = {
    "completedsquare": ("CompSquare", "Moodle UI dropdown label"),
    "propositionallogic": ("PropLogic", "Moodle UI dropdown label"),
    "equivreasoning": ("Equiv", "Moodle UI dropdown label"),
    "equivfirstlast": ("EquivFirst", "STACK documentation alias"),
    "unitssigfigs": ("Units", "Moodle UI dropdown label"),
    "unitsstrictsigfigs": ("UnitsStrict", "Moodle UI dropdown label"),
    "num-gt": ("GT", "Moodle UI dropdown label"),
    "num-gte": ("GTE", "Moodle UI dropdown label"),
    "strictsigfigs": ("SigFigsStrict", "STACK documentation alias"),
    "regexp": ("SRegExp", "removed in STACK 4.3; replaced by SRegExp"),
}

ANSWER_TEST_CATEGORIES: tuple[AnswerTestCategory, ...] = (
    "equivalence",
    "form",
    "rules",
    "calculus",
    "numerical",
    "units",
    "string",
    "other",
)


# --------------------------------------------------------------------------- #
# Reference Tables for Inputs, Coded Options, Front Matter, and CASText2
# --------------------------------------------------------------------------- #

INPUT_TYPES_SPEC = [
    {
        "type": "algebraic",
        "description": "Standard mathematical expression evaluated by Maxima CAS",
        "default_boxsize": 15,
        "sample": "ans1: algebraic, boxsize=15",
    },
    {
        "type": "numerical",
        "description": "Real or complex numbers (forbids algebraic operations unless allowed)",
        "default_boxsize": 10,
        "sample": "ans1: numerical, boxsize=10",
    },
    {
        "type": "units",
        "description": "Numerical quantity paired with physical SI or custom units",
        "default_boxsize": 15,
        "sample": "ans1: units, boxsize=15",
    },
    {
        "type": "matrix",
        "description": "Grid of inputs arranged in matrix rows/columns matching dimensions of tans",
        "default_boxsize": 5,
        "sample": "ans1: matrix, boxsize=5",
    },
    {
        "type": "varmatrix",
        "description": "Matrix with variable dimensions specified by student or parameters",
        "default_boxsize": 5,
        "sample": "ans1: varmatrix",
    },
    {
        "type": "dropdown",
        "description": "Single-selection drop-down menu",
        "default_boxsize": 0,
        "sample": "ans1: dropdown",
    },
    {
        "type": "radio",
        "description": "Radio button group for single selection",
        "default_boxsize": 0,
        "sample": "ans1: radio",
    },
    {
        "type": "checkbox",
        "description": "Checkbox group for multiple selection",
        "default_boxsize": 0,
        "sample": "ans1: checkbox",
    },
    {
        "type": "boolean",
        "description": "True/false boolean selector",
        "default_boxsize": 0,
        "sample": "ans1: boolean",
    },
    {
        "type": "equiv",
        "description": "Multi-line step-by-step reasoning chain",
        "default_boxsize": 30,
        "sample": "ans1: equiv",
    },
    {
        "type": "string",
        "description": "Raw string text input",
        "default_boxsize": 20,
        "sample": "ans1: string",
    },
    {
        "type": "textarea",
        "description": "Multi-line text area",
        "default_boxsize": 30,
        "sample": "ans1: textarea",
    },
    {
        "type": "notes",
        "description": "Read-only / teacher notes input",
        "default_boxsize": 0,
        "sample": "ans1: notes",
    },
    {
        "type": "singlechar",
        "description": "Single character input (e.g. variable name)",
        "default_boxsize": 1,
        "sample": "ans1: singlechar",
    },
]

CODED_INTEGER_OPTIONS = {
    "insertstars": [
        ("0", "Don't insert stars"),
        ("1", "Implied mult only"),
        ("2", "Single-char vars"),
        ("3", "Spaces only"),
        ("4", "Implied + spaces"),
        ("5", "Single-char + implied + spaces"),
        ("6", "Implied + spaces + no user-functions"),
        ("7", "Single-char + implied + spaces + no user-functions"),
    ],
    "showvalidation": [
        ("0", "No"),
        ("1", "Yes, with variable list"),
        ("2", "Yes, without variable list"),
        ("3", "Yes, compact"),
    ],
    "syntaxattribute": [
        ("0", "Editable value"),
        ("1", "Placeholder"),
    ],
    "feedbackstyle": [
        ("0", "Formative"),
        ("1", "Standard"),
        ("2", "Compact"),
        ("3", "Symbol only"),
    ],
}

FRONT_MATTER_SPEC = [
    {"field": "name", "type": "string", "default": '""', "description": "Question display name"},
    {"field": "idnumber", "type": "string", "default": '""', "description": "Question ID number (for tracking / course sync)"},
    {"field": "defaultgrade", "type": "float", "default": "1.0", "description": "Total default grade awarded for the question"},
    {"field": "penalty", "type": "float", "default": "0.1", "description": "Penalty fraction deducted per incorrect attempt"},
    {"field": "hidden", "type": "int (0/1)", "default": "0", "description": "Whether question is hidden in Moodle bank"},
    {"field": "questionsimplify", "type": "int (0/1)", "default": "1", "description": "Global simplification flag (simp:true/false in CAS)"},
    {"field": "assumepositive", "type": "int (0/1)", "default": "0", "description": "Assume variables are positive in Maxima (assume_pos)"},
    {"field": "assumereal", "type": "int (0/1)", "default": "0", "description": "Assume variables are real in Maxima (assume_real)"},
    {"field": "sqrtsign", "type": "int (0/1)", "default": "1", "description": "Display square roots using radical surd symbol"},
]

DISPLAY_OPTIONS_SPEC = [
    {
        "setting": "multiplicationsign",
        "default": "dot",
        "choices": ["dot", "cross", "onum", "none", "space"],
        "description": "Symbol used for multiplication in LaTeX rendering",
    },
    {
        "setting": "inversetrig",
        "default": "cos-1",
        "choices": ["cos-1", "acos", "arccos", "arsinh"],
        "description": "Notation style for inverse trigonometric functions",
    },
    {
        "setting": "complexno",
        "default": "i",
        "choices": ["i", "j", "symi", "symj"],
        "description": "Symbol for imaginary unit in complex numbers",
    },
    {
        "setting": "matrixparens",
        "default": "[",
        "choices": ["[", "(", "''", "{", "|"],
        "description": "Delimiter enclosing matrix expressions",
    },
    {
        "setting": "scientificnotation",
        "default": "*10",
        "choices": ["*10", "E"],
        "description": "Scientific notation exponent rendering (*10^n vs En)",
    },
    {
        "setting": "logicsymbol",
        "default": "lang",
        "choices": ["lang", "symbol"],
        "description": "Rendering for logical connectives (words vs formal symbols)",
    },
    {
        "setting": "decimals",
        "default": ".",
        "choices": [".", ","],
        "description": "Decimal separator symbol",
    },
]

CASTEXT_SPEC = {
    "delimiters": [
        ("{@expr@}", "CAS evaluation with LaTeX mathematical typesetting (math mode)"),
        ("{#expr#}", "CAS evaluation formatted as raw string/HTML (not LaTeX math)"),
        ("[[input:ans1]]", "Placement marker for input field widget ans1"),
        ("[[validation:ans1]]", "Placement marker for validation feedback of ans1"),
        ("[[feedback:prt1]]", "Placement marker for feedback from PRT prt1"),
    ],
    "sections": [
        ("## Question text", "Primary question body and task presented to the student"),
        ("## Specific feedback", "Feedback displayed after submission (contains [[feedback:prt]])"),
        ("## General feedback", "Worked solution / model answer revealed after attempt completion"),
        ("## Question note", "CAS expression string representing the randomized variant signature"),
        ("## Question description", "Internal teacher / author documentation"),
        ("## PRT correct", "Default feedback text when answer is completely correct"),
        ("## PRT partially correct", "Default feedback text when answer is partially correct"),
        ("## PRT incorrect", "Default feedback text when answer is completely incorrect"),
    ],
}


# --------------------------------------------------------------------------- #
# Rich Rendering Functions
# --------------------------------------------------------------------------- #


def _render_overview(console: Console) -> None:
    skeleton = """[bold cyan]---[/bold cyan]
name = "Derivative of a quadratic"
[bold cyan]---[/bold cyan]

[bold yellow]## Question variables[/bold yellow]
```maxima
a: rand(5) + 2;
ta1: 2*a*x;
```

[bold yellow]## Question text[/bold yellow]
Differentiate \\({@a*x^2@}\\) with respect to \\(x\\): [[input:ans1]] [[validation:ans1]]
[[feedback:prt1]]

[bold yellow]## Inputs[/bold yellow]
ans1: algebraic, boxsize=15

[bold yellow]## PRT prt1[/bold yellow]
node 0: AlgEquiv(ans1, ta1)
  true: =1 -> end
  false: =0 -> end

[bold yellow]## Tests[/bold yellow]
### Test 1
ans1 = ta1
prt1 => 1, "prt1-0-T"
"""

    console.print(
        Panel(
            Text.from_markup(skeleton),
            title="[bold green]Minimal STACK Sketch (.stack.md) Skeleton[/bold green]",
            border_style="green",
        )
    )

    table = Table(title="macstack ref Quick Navigation", border_style="cyan")
    table.add_column("Command", style="bold yellow")
    table.add_column("Description")

    table.add_row("macstack ref prt", "PRT node grammar, branching tokens (=1, -> end), feedback, examples")
    table.add_row("macstack ref tests", "Catalog of all 41 STACK answer tests grouped by category")
    table.add_row("macstack ref tests <cat>", "Answer tests filtered by category (calculus, numerical, form, etc.)")
    table.add_row("macstack ref <TestName>", "Detailed card for any test (e.g. macstack ref Int, FacForm, NumSigFigs)")
    table.add_row("macstack ref inputs", "Input types, MCQ tans format, options, and integer setting codes")
    table.add_row("macstack ref frontmatter", "Front matter settings, default values, and display option choices")
    table.add_row("macstack ref castext", "CASText2 delimiters ({@...@}, [[input:...]]) and HTML section headers")

    console.print(table)


def _render_prt_ref(console: Console) -> None:
    intro = """[bold cyan]PRT (Potential Response Tree) Architecture[/bold cyan]

A PRT evaluates student answers through a directed acyclic graph of test nodes.
Each node executes an answer test comparing [bold]sans[/bold] against [bold]tans[/bold],
then branches along [green]true[/green] or [red]false[/red] paths.

[bold yellow]Node Grammar:[/bold yellow]
  node <name>: <AnswerTest>(<sans>, <tans>[, <testoptions>])
    [description: <text>]
    [quiet]
    true: [=Score] [-> NextNode] [penalty=P] [note="..."]
        <p>Indented 4-space HTML feedback</p>
    false: [=Score] [-> NextNode] [penalty=P] [note="..."]
        <p>Indented 4-space HTML feedback</p>
"""
    console.print(Panel(Text.from_markup(intro), title="macstack ref prt", border_style="cyan"))

    tokens_table = Table(title="Branch Modifiers & Tokens", border_style="green")
    tokens_table.add_column("Token", style="bold yellow")
    tokens_table.add_column("Effect")
    tokens_table.add_column("Example")

    tokens_table.add_row("=S", "Set absolute node score to S (range 0.0 .. 1.0)", "=1, =0, =0.5")
    tokens_table.add_row("+S", "Add score S to running PRT score", "+0.5")
    tokens_table.add_row("-S", "Subtract score S from running PRT score", "-0.25")
    tokens_table.add_row("-> N", "Transition to node N", "-> 1, -> step2")
    tokens_table.add_row("-> end", "Terminate PRT evaluation (nextnode = -1)", "-> end")
    tokens_table.add_row("penalty=P", "Override penalty fraction for this branch", "penalty=0.1")
    tokens_table.add_row('note="..."', "Custom answer note for question tests and stats", 'note="ans1-factored"')
    tokens_table.add_row("    <html...>", "Indented 4-space HTML feedback block", "    <p>Good job!</p>")

    console.print(tokens_table)

    fb_table = Table(title="PRT feedbackstyle Setting Codes", border_style="magenta")
    fb_table.add_column("Code", style="bold yellow")
    fb_table.add_column("Style Name")
    fb_table.add_column("Behavior")
    for code, label in CODED_INTEGER_OPTIONS["feedbackstyle"]:
        desc = {
            "0": "Shows formative feedback messages without symbols",
            "1": "Standard display with checkmarks, score, and messages",
            "2": "Compact single-line feedback representation",
            "3": "Only displays checkmark / cross symbol without text",
        }.get(code, "")
        fb_table.add_row(code, label, desc)
    console.print(fb_table)

    ex1 = """node 0: FacForm(ans1, ta1, x)
  true: -> 1
  false: =0 -> 1
    <p>Your answer is not in factored form.</p>
node 1: AlgEquiv(ans1, ta1)
  true: =1 -> end
  false: =0 -> end"""

    ex2 = """node 0: NumSigFigs(ans1, ta1, 3)
  true: =1 -> end
  false: -> 1
node 1: NumAbsolute(ans1, ta1, 0.05)
  true: =1 penalty=0.2 -> end
    <p>Value is correct, but check your significant figures (expected 3).</p>
  false: =0 -> end"""

    console.print(Panel(ex1, title="Pattern 1: Form check + Algebraic equivalence", border_style="yellow"))
    console.print(Panel(ex2, title="Pattern 2: Precision check with penalty fallback", border_style="yellow"))


def _render_test_card(spec: AnswerTestSpec, console: Console) -> None:
    opt_part = f", {spec.options_syntax}" if spec.options_status != "none" else ""
    signature = f"{spec.name}(sans, tans{opt_part})"

    flags: list[str] = []
    if spec.requires_raw_sans:
        flags.append("[bold red]REQUIRES RAW SANS[/bold red] (bare input variable e.g. ans1; no Maxima expressions)")
    if spec.ignores_tans:
        flags.append("[bold yellow]IGNORES TANS[/bold yellow] (does NOT check equivalence alone—pair with AlgEquiv!)")
    if not flags:
        flags.append("[dim]Standard evaluation[/dim]")

    moodle_info = (
        f"[yellow]{escape(spec.moodle_label)}[/yellow] (differs from sketch name!)"
        if spec.moodle_label != spec.name
        else f"[dim]{escape(spec.name)}[/dim]"
    )

    opt_syntax_str = f" ({escape(spec.options_syntax)})" if spec.options_syntax else ""

    body = [
        f"[bold]Category:[/bold] {spec.category}",
        f"[bold]Moodle UI Label:[/bold] {moodle_info}",
        f"[bold]Signature:[/bold] [green]{escape(signature)}[/green]",
        f"[bold]Options:[/bold] {spec.options_status.capitalize()}{opt_syntax_str}",
        f"[bold]Flags:[/bold] {' | '.join(flags)}",
        "",
        f"[bold]Summary:[/bold]\n{spec.summary}",
        "",
        "[bold]Sketch Example (.stack.md):[/bold]",
        escape(spec.sketch_example),
        "",
        "[bold]Gotchas & Authoring Caveats:[/bold]",
    ]
    for g in spec.gotchas:
        body.append(f"  • {escape(g)}")

    console.print(
        Panel(
            "\n".join(body),
            title=f"[bold green]Answer Test: {spec.name}[/bold green]",
            border_style="green",
        )
    )


def _render_tests_table(specs: list[AnswerTestSpec], console: Console, title: str = "STACK Answer Tests") -> None:
    table = Table(title=title, border_style="cyan")
    table.add_column("Answer Test", style="bold yellow", no_wrap=True)
    table.add_column("Category", style="cyan")
    table.add_column("Options")
    table.add_column("Moodle UI Label")
    table.add_column("Flags")
    table.add_column("Summary")

    for spec in specs:
        esc_opts = escape(spec.options_syntax)
        opt_str = {
            "required": f"[bold red]req:[/bold red] {esc_opts}",
            "optional": f"[yellow]opt:[/yellow] {esc_opts}",
            "none": "[dim]—[/dim]",
        }[spec.options_status]

        moodle = escape(spec.moodle_label) if spec.moodle_label != spec.name else "[dim]—[/dim]"

        flags: list[str] = []
        if spec.requires_raw_sans:
            flags.append("[red]raw-sans[/red]")
        if spec.ignores_tans:
            flags.append("[yellow]ignores-tans[/yellow]")
        flag_str = " ".join(flags) if flags else "[dim]—[/dim]"

        table.add_row(
            spec.name,
            spec.category,
            opt_str,
            moodle,
            flag_str,
            spec.summary,
        )

    console.print(table)


def _render_inputs_ref(console: Console) -> None:
    intro = """[bold cyan]STACK Inputs Reference[/bold cyan]

Inputs capture student responses and supply them to PRTs.
In `.stack.md`, define inputs under `## Inputs`:
  ans1: <type>, key=value, ..."""
    console.print(Panel(Text.from_markup(intro), title="macstack ref inputs", border_style="cyan"))

    types_table = Table(title="Input Types", border_style="green")
    types_table.add_column("Type", style="bold yellow")
    types_table.add_column("Default Box", justify="right")
    types_table.add_column("Description")
    types_table.add_column("Example")

    for item in INPUT_TYPES_SPEC:
        box = str(item["default_boxsize"]) if item["default_boxsize"] else "[dim]—[/dim]"
        types_table.add_row(item["type"], box, item["description"], item["sample"])
    console.print(types_table)

    mcq_text = """Multiple-choice inputs (dropdown, radio, checkbox) evaluate teacher answers formatted
as a Maxima list of tuples:
  ta1: [[val1, true/false, "Option Label 1"], [val2, true/false, "Option Label 2"], ...]

Example:
  ```maxima
  ta1: [[1, true, "Stable equilibrium"], [2, false, "Unstable equilibrium"], [3, false, "Neutral"]];
  ```"""
    console.print(Panel(mcq_text, title="MCQ tans Tuple Format", border_style="yellow"))

    for opt_name, rows in CODED_INTEGER_OPTIONS.items():
        if opt_name == "feedbackstyle":
            continue
        tbl = Table(title=f"Integer Setting: {opt_name}", border_style="magenta")
        tbl.add_column("Code", style="bold yellow")
        tbl.add_column("Meaning")
        for code, label in rows:
            tbl.add_row(code, label)
        console.print(tbl)


def _render_frontmatter_ref(console: Console) -> None:
    tbl = Table(title="Question Front Matter Settings (macstack.toml / .stack.md)", border_style="cyan")
    tbl.add_column("Field", style="bold yellow", no_wrap=True)
    tbl.add_column("Type")
    tbl.add_column("Default")
    tbl.add_column("Description")

    for item in FRONT_MATTER_SPEC:
        tbl.add_row(item["field"], item["type"], item["default"], item["description"])
    console.print(tbl)

    disp_tbl = Table(title="Display Option Values", border_style="green")
    disp_tbl.add_column("Display Setting", style="bold yellow", no_wrap=True)
    disp_tbl.add_column("Default")
    disp_tbl.add_column("Allowed Choices")
    disp_tbl.add_column("Description")

    for item in DISPLAY_OPTIONS_SPEC:
        disp_tbl.add_row(
            item["setting"],
            item["default"],
            escape(", ".join(item["choices"])),
            item["description"],
        )
    console.print(disp_tbl)


def _render_castext_ref(console: Console) -> None:
    delims_table = Table(title="CASText2 Delimiters", border_style="cyan")
    delims_table.add_column("Delimiter", style="bold yellow")
    delims_table.add_column("Meaning / Usage")
    for delim, desc in CASTEXT_SPEC["delimiters"]:
        delims_table.add_row(escape(delim), escape(desc))
    console.print(delims_table)

    sec_table = Table(title="Free-Text HTML Sections", border_style="green")
    sec_table.add_column("Section Heading", style="bold yellow")
    sec_table.add_column("Purpose")
    for heading, desc in CASTEXT_SPEC["sections"]:
        sec_table.add_row(heading, escape(desc))
    console.print(sec_table)


# --------------------------------------------------------------------------- #
# CLI Dispatcher
# --------------------------------------------------------------------------- #


def render_ref_cli(
    query: list[str] | None = None,
    as_json: bool = False,
    console: Console | None = None,
) -> None:
    """Execute the `macstack ref` command, rendering Rich terminal UI or JSON."""
    if console is None:
        console = Console()

    # 1. No query: Overview
    if not query:
        if as_json:
            data = {
                "answer_tests": [s.to_dict() for s in ANSWER_TEST_SPECS],
                "input_types": INPUT_TYPES_SPEC,
                "coded_options": CODED_INTEGER_OPTIONS,
                "frontmatter": FRONT_MATTER_SPEC,
                "display_options": DISPLAY_OPTIONS_SPEC,
                "castext": CASTEXT_SPEC,
            }
            print(json.dumps(data, indent=2))
            return
        _render_overview(console)
        return

    # Normalize query tokens
    q_str = " ".join(query).strip()
    first = query[0].lower().strip()
    second = query[1].lower().strip() if len(query) > 1 else ""

    # 2. Topic: PRT
    if first == "prt":
        if as_json:
            print(json.dumps({
                "topic": "prt",
                "branch_modifiers": ["=Score", "+Score", "-Score", "-> NextNode", "-> end", "penalty=P", 'note="..."'],
                "feedbackstyle": CODED_INTEGER_OPTIONS["feedbackstyle"],
            }, indent=2))
            return
        _render_prt_ref(console)
        return

    # 3. Topic: Inputs
    if first in ("input", "inputs"):
        if as_json:
            print(json.dumps({
                "topic": "inputs",
                "input_types": INPUT_TYPES_SPEC,
                "insertstars": CODED_INTEGER_OPTIONS["insertstars"],
                "showvalidation": CODED_INTEGER_OPTIONS["showvalidation"],
                "syntaxattribute": CODED_INTEGER_OPTIONS["syntaxattribute"],
            }, indent=2))
            return
        _render_inputs_ref(console)
        return

    # 4. Topic: Front Matter / Settings
    if first in ("frontmatter", "settings", "toml"):
        if as_json:
            print(json.dumps({
                "topic": "frontmatter",
                "fields": FRONT_MATTER_SPEC,
                "display_options": DISPLAY_OPTIONS_SPEC,
            }, indent=2))
            return
        _render_frontmatter_ref(console)
        return

    # 5. Topic: CASText2 / HTML
    if first in ("castext", "html"):
        if as_json:
            print(json.dumps({
                "topic": "castext",
                "delimiters": CASTEXT_SPEC["delimiters"],
                "sections": CASTEXT_SPEC["sections"],
            }, indent=2))
            return
        _render_castext_ref(console)
        return

    # 6. Topic: Tests (optionally filtered by category e.g. `macstack ref tests calculus`)
    if first in ("test", "tests"):
        cat_filter = second if second else (query[0].split(":", 1)[1].lower() if ":" in query[0] else "")
        if cat_filter:
            matched = [s for s in ANSWER_TEST_SPECS if s.category == cat_filter]
            if matched:
                if as_json:
                    print(json.dumps([s.to_dict() for s in matched], indent=2))
                    return
                _render_tests_table(matched, console, title=f"STACK Answer Tests: {cat_filter.capitalize()}")
                return
            console.print(f"[bold red]Unknown category:[/bold red] {cat_filter!r}. Available: {', '.join(ANSWER_TEST_CATEGORIES)}")
            raise typer.Exit(code=1)

        if as_json:
            print(json.dumps([s.to_dict() for s in ANSWER_TEST_SPECS], indent=2))
            return
        _render_tests_table(list(ANSWER_TEST_SPECS), console, title="All STACK Answer Tests (v4.11)")
        return

    # 7. Category name directly (e.g. `macstack ref calculus`, `macstack ref units`)
    if first in ANSWER_TEST_CATEGORIES:
        matched = [s for s in ANSWER_TEST_SPECS if s.category == first]
        if as_json:
            print(json.dumps([s.to_dict() for s in matched], indent=2))
            return
        _render_tests_table(matched, console, title=f"STACK Answer Tests: {first.capitalize()}")
        return

    # 8. Exact match by Answer Test Name or Alias
    exact_spec: AnswerTestSpec | None = None
    target_name = first

    if target_name in ANSWER_TEST_ALIASES:
        canonical_name, _ = ANSWER_TEST_ALIASES[target_name]
        exact_spec = ANSWER_TEST_BY_NAME.get(canonical_name)
    else:
        for s in ANSWER_TEST_SPECS:
            if s.name.lower() == target_name or s.moodle_label.lower() == target_name:
                exact_spec = s
                break

    if exact_spec is not None:
        if as_json:
            print(json.dumps(exact_spec.to_dict(), indent=2))
            return
        _render_test_card(exact_spec, console)
        return

    # 9. Keyword fallback search
    q_lower = q_str.lower()
    search_matches: list[AnswerTestSpec] = []
    for s in ANSWER_TEST_SPECS:
        text_corpus = f"{s.name} {s.moodle_label} {s.category} {s.summary} {s.options_syntax} {' '.join(s.gotchas)}".lower()
        if q_lower in text_corpus:
            search_matches.append(s)

    if len(search_matches) == 1:
        if as_json:
            print(json.dumps(search_matches[0].to_dict(), indent=2))
            return
        _render_test_card(search_matches[0], console)
        return
    elif len(search_matches) > 1:
        if as_json:
            print(json.dumps([s.to_dict() for s in search_matches], indent=2))
            return
        _render_tests_table(search_matches, console, title=f"Answer Tests Matching '{q_str}'")
        return

    # 10. No match: exit code 1 with helpful message
    console.print(f"[bold red]Unknown reference topic or answer test:[/bold red] '{q_str}'")
    console.print("Try [bold yellow]macstack ref[/bold yellow] for an overview, or [bold yellow]macstack ref tests[/bold yellow] to list all 41 answer tests.")
    raise typer.Exit(code=1)
