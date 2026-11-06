"""Course configuration and Moodle category mapping for macstack."""

from __future__ import annotations

import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree
import tomli_w


def slugify(text: str) -> str:
    """Convert text to lowercase kebab-case slug for filenames and directories."""
    s = re.sub(r"[^\w\s-]", "", text).strip().lower()
    s = re.sub(r"[-\s]+", "-", s)
    return s or "unnamed"


@dataclass
class CategorySpec:
    """Specification of a Moodle question category."""
    idnumber: str = ""
    path: str = ""
    info: str = ""
    folder: str = ""


@dataclass
class CourseConfig:
    """Configuration for a course question bank matching Moodle STACK conventions."""
    stack_version: str = "2025102100"
    root_category: str = "$course$/top/Inline questions"
    questions_dir: str = "questions"
    defaults: dict[str, str] = field(default_factory=lambda: {
        "defaultgrade": "1.0000000",
        "penalty": "0.1000000",
        "hidden": "0",
        "questionsimplify": "1",
        "assumepositive": "0",
        "assumereal": "0",
        "prtcorrect": '<p><i class="fa fa-check"></i> Correct answer, well done.</p>',
        "prtpartiallycorrect": '<p><i class="fa fa-adjust"></i> Your answer is partially correct.</p>',
        "prtincorrect": '<p><i class="fa fa-times"></i> Incorrect answer.</p>',
        "decimals": ".",
        "scientificnotation": "*10",
        "multiplicationsign": "onum",
        "sqrtsign": "1",
        "complexno": "i",
        "inversetrig": "cos-1",
        "logicsymbol": "lang",
        "matrixparens": "[",
    })
    input_defaults: dict[str, str] = field(default_factory=lambda: {
        "type": "algebraic",
        "boxsize": "15",
        "strictsyntax": "1",
        "insertstars": "0",
        "syntaxhint": "",
        "syntaxattribute": "0",
        "forbidwords": "",
        "allowwords": "",
        "forbidfloat": "1",
        "requirelowestterms": "0",
        "checkanswertype": "0",
        "mustverify": "1",
        "showvalidation": "1",
        "options": "",
    })
    prt_defaults: dict[str, str] = field(default_factory=lambda: {
        "value": "1.0000000",
        "autosimplify": "1",
        "feedbackstyle": "1",
        "feedbackvariables": "",
    })
    categories: dict[str, CategorySpec] = field(default_factory=dict)
    edit: dict[str, str] = field(default_factory=dict)


def load_config(toml_path: Path) -> CourseConfig:
    """Load CourseConfig from a macstack.toml file."""
    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    
    categories_raw = data.get("categories", {})
    categories: dict[str, CategorySpec] = {}
    for cat_id, cat_data in categories_raw.items():
        if isinstance(cat_data, dict):
            categories[cat_id] = CategorySpec(
                idnumber=str(cat_data.get("idnumber", "")),
                path=str(cat_data.get("path", "")),
                info=str(cat_data.get("info", "")),
                folder=str(cat_data.get("folder", "")),
            )
            
    defaults = dict(CourseConfig().defaults)
    defaults.update(data.get("defaults", {}))

    input_defaults = dict(CourseConfig().input_defaults)
    input_defaults.update(data.get("input_defaults", {}))

    prt_defaults = dict(CourseConfig().prt_defaults)
    prt_defaults.update(data.get("prt_defaults", {}))

    edit_raw = data.get("edit", {})
    edit = {str(k): str(v) for k, v in edit_raw.items()} if isinstance(edit_raw, dict) else {}

    return CourseConfig(
        stack_version=str(data.get("stack_version", "2025102100")),
        root_category=str(data.get("root_category", "$course$/top/Inline questions")),
        questions_dir=str(data.get("questions_dir", "questions")),
        defaults=defaults,
        input_defaults=input_defaults,
        prt_defaults=prt_defaults,
        categories=categories,
        edit=edit,
    )


def save_config(config: CourseConfig, toml_path: Path) -> None:
    """Save CourseConfig to a macstack.toml file."""
    raw_dict: dict[str, Any] = {
        "stack_version": config.stack_version,
        "root_category": config.root_category,
        "questions_dir": config.questions_dir,
        "defaults": config.defaults,
        "input_defaults": config.input_defaults,
        "prt_defaults": config.prt_defaults,
        "categories": {
            cat_id: asdict(cat_spec)
            for cat_id, cat_spec in config.categories.items()
        },
    }
    if config.edit:
        raw_dict["edit"] = config.edit
    toml_str = tomli_w.dumps(raw_dict)
    toml_path.parent.mkdir(parents=True, exist_ok=True)
    toml_path.write_text(toml_str, encoding="utf-8")


def find_course_config(start_path: Path) -> tuple[CourseConfig, Path | None]:
    """Walk up parent directories looking for macstack.toml.
    
    Returns (CourseConfig, Path) if found, or (CourseConfig(), None) if not found.
    """
    resolved = start_path.resolve()
    candidates = [resolved] if resolved.is_dir() else [resolved.parent]
    candidates.extend(candidates[0].parents)

    for p in candidates:
        candidate_file = p / "macstack.toml"
        if candidate_file.is_file():
            try:
                return load_config(candidate_file), candidate_file
            except Exception:
                continue

    return CourseConfig(), None


def infer_config_from_bank(xml_path: Path) -> CourseConfig:
    """Infer CourseConfig from an existing Moodle XML export.
    
    Scans <question type="category"> elements and detects most frequent
    question settings across <question type="stack"> blocks.
    """
    parser = etree.XMLParser(strip_cdata=False, recover=True)
    tree = etree.parse(str(xml_path), parser)
    root = tree.getroot()

    # Discover categories
    cat_elements = root.findall(".//question[@type='category']")
    root_category = "$course$/top/Inline questions"
    if cat_elements:
        first_path = cat_elements[0].findtext("./category/text")
        if first_path:
            root_category = first_path.strip()

    categories: dict[str, CategorySpec] = {}
    for c in cat_elements:
        path_text = (c.findtext("./category/text") or "").strip()
        idnumber = (c.findtext("./idnumber") or "").strip()
        info_text = (c.findtext("./info/text") or "").strip()
        
        if not path_text:
            continue

        if path_text == root_category:
            folder = ""
            key = idnumber if idnumber else "root"
        else:
            leaf = path_text.split("/")[-1].strip()
            folder = idnumber if idnumber else slugify(leaf)
            key = idnumber if idnumber else folder

        categories[key] = CategorySpec(
            idnumber=idnumber,
            path=path_text,
            info=info_text,
            folder=folder,
        )

    # Detect most-frequent defaults across stack questions
    stack_elements = root.findall(".//question[@type='stack']")
    defaults = dict(CourseConfig().defaults)
    stack_version = CourseConfig().stack_version

    if stack_elements:
        from collections import Counter

        for field_name in [
            "defaultgrade",
            "penalty",
            "hidden",
            "questionsimplify",
            "assumepositive",
            "assumereal",
            "decimals",
            "scientificnotation",
            "multiplicationsign",
            "sqrtsign",
            "complexno",
            "inversetrig",
            "logicsymbol",
            "matrixparens",
        ]:
            counts: Counter[str] = Counter()
            for q in stack_elements:
                val = q.findtext(f"./{field_name}")
                if val is not None:
                    counts[val.strip()] += 1
            if counts:
                defaults[field_name] = counts.most_common(1)[0][0]

        # Check feedback texts
        for fb_field in ["prtcorrect", "prtpartiallycorrect", "prtincorrect"]:
            counts: Counter[str] = Counter()
            for q in stack_elements:
                txt = q.findtext(f"./{fb_field}/text")
                if txt is not None:
                    counts[txt.strip()] += 1
            if counts:
                defaults[fb_field] = counts.most_common(1)[0][0]

        # Check stackversion
        v_counts: Counter[str] = Counter()
        for q in stack_elements:
            v = q.findtext("./stackversion/text") or q.findtext("./stackversion")
            if v:
                v_counts[v.strip()] += 1
        if v_counts:
            stack_version = v_counts.most_common(1)[0][0]

    return CourseConfig(
        stack_version=stack_version,
        root_category=root_category,
        questions_dir="questions",
        defaults=defaults,
        categories=categories,
    )
