"""Moodle STACK XML Codec: split, bundle, normalize, test cases, and seed management."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree

from macstack.config import CategorySpec, CourseConfig, find_course_config, infer_config_from_bank, save_config, slugify

HTML_CDATA_TAGS = {
    "questiontext",
    "generalfeedback",
    "specificfeedback",
    "questionnote",
    "questiondescription",
    "prtcorrect",
    "prtpartiallycorrect",
    "prtincorrect",
    "truefeedback",
    "falsefeedback",
    "hint",
    "info",
}

STACK_QUESTION_TAG_ORDER = [
    "name",
    "questiontext",
    "generalfeedback",
    "defaultgrade",
    "penalty",
    "hidden",
    "idnumber",
    "stackversion",
    "questionvariables",
    "specificfeedback",
    "questionnote",
    "questiondescription",
    "questionsimplify",
    "assumepositive",
    "assumereal",
    "prtcorrect",
    "prtpartiallycorrect",
    "prtincorrect",
    "decimals",
    "scientificnotation",
    "multiplicationsign",
    "sqrtsign",
    "complexno",
    "inversetrig",
    "logicsymbol",
    "matrixparens",
    "variantsselectionseed",
    "isbroken",
]

INPUT_TAG_ORDER = [
    "name",
    "type",
    "tans",
    "boxsize",
    "strictsyntax",
    "insertstars",
    "syntaxhint",
    "syntaxattribute",
    "forbidwords",
    "allowwords",
    "forbidfloat",
    "requirelowestterms",
    "checkanswertype",
    "mustverify",
    "showvalidation",
    "options",
]

PRT_TAG_ORDER = [
    "name",
    "value",
    "autosimplify",
    "feedbackstyle",
    "feedbackvariables",
]

NODE_TAG_ORDER = [
    "name",
    "description",
    "answertest",
    "sans",
    "tans",
    "testoptions",
    "quiet",
    "truescoremode",
    "truescore",
    "truepenalty",
    "truenextnode",
    "trueanswernote",
    "truefeedback",
    "falsescoremode",
    "falsescore",
    "falsepenalty",
    "falsenextnode",
    "falseanswernote",
    "falsefeedback",
]


@dataclass
class QuestionSummary:
    """High-level summary of a Moodle STACK question."""
    path: Path | None
    name: str
    idnumber: str
    category_path: str
    category_idnumber: str
    inputs: list[str]
    input_types: dict[str, str]
    prts: list[str]
    deployed_seeds: list[int]
    qtest_count: int
    uses_random: bool
    has_plot: bool
    hints_count: int


def _extract_element_text(elem: etree._Element | None) -> str:
    """Extract full string content from an element, handling CDATA, plain text, and nested markup."""
    if elem is None:
        return ""
    if len(elem) > 0:
        return (elem.text or "") + "".join(etree.tostring(c, encoding="unicode") for c in elem)
    return elem.text or ""


def _get_xml_root(xml_path_or_str: Path | str) -> tuple[etree._Element, Path | None]:
    """Parse XML path or string into an etree root element with CDATA preserved."""
    parser = etree.XMLParser(strip_cdata=False, recover=True)
    if isinstance(xml_path_or_str, Path) or (
        isinstance(xml_path_or_str, str)
        and not xml_path_or_str.strip().startswith("<")
        and Path(xml_path_or_str).is_file()
    ):
        path = Path(xml_path_or_str)
        tree = etree.parse(str(path), parser)
        return tree.getroot(), path
    else:
        content = xml_path_or_str.encode("utf-8") if isinstance(xml_path_or_str, str) else xml_path_or_str
        return etree.fromstring(content, parser), None


def find_stack_question(root: etree._Element) -> etree._Element | None:
    """Return the first <question type="stack"> element in a parsed document (or the root itself)."""
    if root.tag == "question" and root.get("type") == "stack":
        return root
    return root.find(".//question[@type='stack']")


def _serialize_xml(root: etree._Element) -> str:
    """Serialize element to pretty-printed UTF-8 XML string with declaration."""
    etree.indent(root, space="  ")
    raw = etree.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)
    return raw.decode("utf-8")


def _wrap_cdata_if_needed(text: str) -> etree.CDATA | str:
    """Wrap non-empty string in CDATA for HTML/text preservation."""
    if text:
        return etree.CDATA(text)
    return ""


def parse_question_summary(xml_path_or_str: Path | str) -> QuestionSummary:
    """Extract metadata and high-level summary of a STACK question."""
    root, path = _get_xml_root(xml_path_or_str)

    # Find the stack question
    q = find_stack_question(root)

    if q is None:
        raise ValueError("No <question type='stack'> element found in XML")

    # Name and ID
    name = (q.findtext("./name/text") or q.findtext("./name") or "").strip()
    idnumber = (q.findtext("./idnumber") or "").strip()

    # Category info (last category preceding question, or any category in document)
    cat_path = ""
    cat_idnumber = ""
    categories = root.findall(".//question[@type='category']")
    if categories:
        last_cat = categories[-1]
        cat_path = (last_cat.findtext("./category/text") or "").strip()
        cat_idnumber = (last_cat.findtext("./idnumber") or "").strip()

    # Inputs
    inputs: list[str] = []
    input_types: dict[str, str] = {}
    for inp in q.findall("./input"):
        inp_name = (inp.findtext("./name") or inp.get("name") or "").strip()
        if inp_name:
            inputs.append(inp_name)
            input_types[inp_name] = (inp.findtext("./type") or inp.get("type") or "").strip()

    # PRTs
    prts: list[str] = []
    for prt in q.findall("./prt"):
        prt_name = (prt.findtext("./name") or prt.get("name") or "").strip()
        if prt_name:
            prts.append(prt_name)

    # Deployed seeds
    deployed_seeds: list[int] = []
    for s in q.findall("./deployedseed"):
        val = (s.text or "").strip()
        if val and (val.isdigit() or (val.startswith("-") and val[1:].isdigit())):
            deployed_seeds.append(int(val))

    # QTests & Hints
    qtest_count = len(q.findall("./qtest"))
    hints_count = len(q.findall("./hint"))

    # Randomization and plots
    qvars = _extract_element_text(q.find("./questionvariables/text"))
    qtext = _extract_element_text(q.find("./questiontext/text"))
    uses_random = bool(re.search(r"\brand(?:_[a-z_]+)?\s*\(", qvars))
    has_plot = bool(re.search(r"\bplot\s*\(", qtext + " " + qvars))

    return QuestionSummary(
        path=path,
        name=name,
        idnumber=idnumber,
        category_path=cat_path,
        category_idnumber=cat_idnumber,
        inputs=inputs,
        input_types=input_types,
        prts=prts,
        deployed_seeds=deployed_seeds,
        qtest_count=qtest_count,
        uses_random=uses_random,
        has_plot=has_plot,
        hints_count=hints_count,
    )


def extract_question_fields(xml_path_or_str: Path | str) -> dict[str, str]:
    """Safely extract raw text of all CAS and CASText fields from a STACK question.

    Returns a mapping of canonical field keys to their raw extracted text strings.
    If the XML is invalid or contains no <question type="stack">, an empty dict is returned.
    """
    try:
        root, _ = _get_xml_root(xml_path_or_str)
        q = find_stack_question(root)
        if q is None:
            return {}
    except Exception:
        return {}

    def _field_text(parent: etree._Element, path: str) -> str:
        elem = parent.find(path)
        if elem is not None:
            return _extract_element_text(elem)
        if path.endswith("/text"):
            fallback_elem = parent.find(path[:-5])
            if fallback_elem is not None:
                return _extract_element_text(fallback_elem)
        return ""

    fields: dict[str, str] = {
        "questionvariables": _field_text(q, "./questionvariables/text"),
        "questiontext": _field_text(q, "./questiontext/text"),
        "generalfeedback": _field_text(q, "./generalfeedback/text"),
        "specificfeedback": _field_text(q, "./specificfeedback/text"),
        "questionnote": _field_text(q, "./questionnote/text"),
    }

    for prt in q.findall("./prt"):
        prt_name = (prt.findtext("./name") or prt.get("name") or "").strip()
        fields[f"prt:{prt_name}:feedbackvariables"] = _field_text(prt, "./feedbackvariables/text")
        for idx, node in enumerate(prt.findall("./node")):
            node_name = (node.findtext("./name") or str(idx)).strip()
            fields[f"prt:{prt_name}:node:{node_name}:sans"] = _field_text(node, "./sans")
            fields[f"prt:{prt_name}:node:{node_name}:tans"] = _field_text(node, "./tans")
            fields[f"prt:{prt_name}:node:{node_name}:testoptions"] = _field_text(node, "./testoptions")
            fields[f"prt:{prt_name}:node:{node_name}:truefeedback"] = _field_text(node, "./truefeedback/text")
            fields[f"prt:{prt_name}:node:{node_name}:falsefeedback"] = _field_text(node, "./falsefeedback/text")

    return fields


def split_bank(export_xml: Path, out_dir: Path) -> tuple[CourseConfig, list[Path]]:
    """Split a monolithic Moodle XML export into modular files organized by category.
    
    Infers configuration, saves macstack.toml, and splits questions into:
    `out_dir / config.questions_dir / <cat_folder> / "<idnumber_or_slug>.xml"`
    Each split question file includes its ancestor category headers.
    """
    config = infer_config_from_bank(export_xml)
    out_dir.mkdir(parents=True, exist_ok=True)
    save_config(config, out_dir / "macstack.toml")

    parser = etree.XMLParser(strip_cdata=False, recover=True)
    tree = etree.parse(str(export_xml), parser)
    root = tree.getroot()

    # Map category paths to category elements
    category_registry: dict[str, etree._Element] = {}
    active_category_path: str = config.root_category
    written_paths: list[Path] = []
    questions_base = out_dir / config.questions_dir

    for child in root:
        if not isinstance(child, etree._Element):
            continue

        qtype = child.get("type")
        if qtype == "category":
            cat_path = (child.findtext("./category/text") or "").strip()
            if cat_path:
                category_registry[cat_path] = child
                active_category_path = cat_path
        elif qtype == "stack":
            # Build ancestor category chain
            chain: list[etree._Element] = []
            for reg_path, reg_elem in category_registry.items():
                if active_category_path == reg_path or active_category_path.startswith(reg_path + "/"):
                    chain.append(reg_elem)
            chain.sort(key=lambda elem: len(elem.findtext("./category/text") or ""))

            # Find matching category spec for folder mapping
            folder = ""
            for spec in config.categories.values():
                if spec.path == active_category_path:
                    folder = spec.folder
                    break
            if not folder and active_category_path != config.root_category:
                leaf_name = active_category_path.split("/")[-1].strip()
                folder = slugify(leaf_name)

            dest_dir = questions_base / folder if folder else questions_base
            dest_dir.mkdir(parents=True, exist_ok=True)

            idnumber = (child.findtext("./idnumber") or "").strip()
            name = (child.findtext("./name/text") or child.findtext("./name") or "").strip()
            filename_stem = idnumber if idnumber else slugify(name)
            if not filename_stem:
                filename_stem = f"question_{len(written_paths) + 1}"

            dest_path = dest_dir / f"{filename_stem}.xml"

            # Build single-question quiz
            new_quiz = etree.Element("quiz")
            for cat_elem in chain:
                new_quiz.append(copy.deepcopy(cat_elem))
            new_quiz.append(copy.deepcopy(child))

            dest_path.write_text(_serialize_xml(new_quiz), encoding="utf-8")
            written_paths.append(dest_path)

    return config, written_paths


def bundle_bank(paths: list[Path], out_xml: Path, config: CourseConfig | None = None) -> int:
    """Bundle individual or directory question XML files into a single Moodle export.
    
    Category blocks are deduplicated and emitted in ancestor-first order before questions.
    Returns total count of <question type="stack"> bundled.
    """
    xml_files: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix.lower() == ".xml" and p.resolve() != out_xml.resolve():
            xml_files.append(p)
        elif p.is_dir():
            for child in p.rglob("*.xml"):
                if child.is_file() and child.resolve() != out_xml.resolve():
                    xml_files.append(child)

    xml_files.sort(key=lambda f: (str(f.parent), f.name))

    if not xml_files:
        root = etree.Element("quiz")
        out_xml.parent.mkdir(parents=True, exist_ok=True)
        out_xml.write_text(_serialize_xml(root), encoding="utf-8")
        return 0

    if config is None:
        config, _ = find_course_config(xml_files[0].parent)

    parser = etree.XMLParser(strip_cdata=False, recover=True)
    parsed_items: list[tuple[str, list[etree._Element], etree._Element]] = []

    for f in xml_files:
        try:
            tree = etree.parse(str(f), parser)
            doc_root = tree.getroot()
        except Exception:
            continue

        cats_in_file = doc_root.findall(".//question[@type='category']")
        stacks_in_file = doc_root.findall(".//question[@type='stack']")

        leaf_cat_path = ""
        chain = [copy.deepcopy(c) for c in cats_in_file]
        if cats_in_file:
            leaf_cat_path = (cats_in_file[-1].findtext("./category/text") or "").strip()
        elif config:
            parent_folder = f.parent.name
            matched_spec: CategorySpec | None = None
            for spec in config.categories.values():
                if spec.folder == parent_folder or spec.idnumber == parent_folder:
                    matched_spec = spec
                    break
            if matched_spec is None:
                for s in stacks_in_file:
                    idn = (s.findtext("./idnumber") or "").strip()
                    prefix = idn.split("-")[0]
                    if prefix in config.categories:
                        matched_spec = config.categories[prefix]
                        break
            if matched_spec:
                leaf_cat_path = matched_spec.path
                if config.root_category and config.root_category != leaf_cat_path:
                    root_elem = etree.Element("question", type="category")
                    c_tag = etree.SubElement(root_elem, "category")
                    t_tag = etree.SubElement(c_tag, "text")
                    t_tag.text = config.root_category
                    chain.append(root_elem)
                leaf_elem = etree.Element("question", type="category")
                c_tag = etree.SubElement(leaf_elem, "category")
                t_tag = etree.SubElement(c_tag, "text")
                t_tag.text = leaf_cat_path
                if matched_spec.idnumber:
                    id_tag = etree.SubElement(leaf_elem, "idnumber")
                    id_tag.text = matched_spec.idnumber
                chain.append(leaf_elem)
            else:
                leaf_cat_path = config.root_category

        for s in stacks_in_file:
            parsed_items.append((leaf_cat_path, chain, copy.deepcopy(s)))

    def item_sort_key(item: tuple[str, list[etree._Element], etree._Element]) -> tuple[str, str]:
        cat_p, _, stack_q = item
        idn = (stack_q.findtext("./idnumber") or "").strip()
        name = (stack_q.findtext("./name/text") or stack_q.findtext("./name") or "").strip()
        return (cat_p, idn or name)

    parsed_items.sort(key=item_sort_key)

    bundled_quiz = etree.Element("quiz")
    emitted_categories: set[str] = set()

    for cat_path, chain, stack_q in parsed_items:
        for cat_elem in chain:
            c_text = (cat_elem.findtext("./category/text") or "").strip()
            if c_text and c_text not in emitted_categories:
                bundled_quiz.append(copy.deepcopy(cat_elem))
                emitted_categories.add(c_text)

        bundled_quiz.append(copy.deepcopy(stack_q))

    out_xml.parent.mkdir(parents=True, exist_ok=True)
    out_xml.write_text(_serialize_xml(bundled_quiz), encoding="utf-8")
    return len(parsed_items)


def _ensure_text_subelement(
    parent: etree._Element,
    tag: str,
    default_text: str = "",
    is_cdata: bool = False,
    format_attr: str | None = None,
) -> etree._Element:
    """Ensure parent contains a child with tag that contains a <text> element."""
    elem = parent.find(f"./{tag}")
    if elem is None:
        elem = etree.SubElement(parent, tag)
    if format_attr is not None:
        elem.set("format", format_attr)

    text_elem = elem.find("./text")
    if text_elem is None:
        text_elem = etree.SubElement(elem, "text")
        if default_text:
            text_elem.text = _wrap_cdata_if_needed(default_text) if is_cdata else default_text
        else:
            text_elem.text = ""
    else:
        # If text_elem contains child elements (e.g. un-CDATA HTML draft like <p>),
        # extract the inner HTML string, clear children, and wrap in CDATA
        if len(text_elem) > 0 and is_cdata:
            inner_html = _extract_element_text(text_elem)
            text_elem.clear()
            text_elem.text = _wrap_cdata_if_needed(inner_html)
        elif is_cdata:
            current_text = text_elem.text or ""
            if current_text:
                text_elem.text = _wrap_cdata_if_needed(current_text)
    return elem


def _ensure_simple_subelement(parent: etree._Element, tag: str, default_val: str = "") -> etree._Element:
    """Ensure parent contains a simple element <tag>value</tag>."""
    elem = parent.find(f"./{tag}")
    if elem is None:
        elem = etree.SubElement(parent, tag)
        elem.text = default_val
    return elem


def normalize_question_xml(xml_str: str, config: CourseConfig, category_id: str | None = None) -> str:
    """Normalize a minimal or author-drafted STACK question XML into complete, valid Stream XML.
    
    Fills in missing defaults, adds category headers, and preserves all existing tags and data.
    """
    root, _ = _get_xml_root(xml_str)

    if root.tag == "question" and root.get("type") == "stack":
        new_quiz = etree.Element("quiz")
        new_quiz.append(root)
        root = new_quiz

    q = root.find(".//question[@type='stack']")
    if q is None:
        raise ValueError("No <question type='stack'> element found in XML")

    # 1. Resolve Category and prepend ancestor category blocks if missing
    existing_cats = root.findall(".//question[@type='category']")
    if not existing_cats:
        target_spec: CategorySpec | None = None
        idnumber_val = (q.findtext("./idnumber") or "").strip()

        if category_id:
            if category_id in config.categories:
                target_spec = config.categories[category_id]
            else:
                for s in config.categories.values():
                    if s.folder == category_id or s.idnumber == category_id:
                        target_spec = s
                        break

        if target_spec is None and "-" in idnumber_val:
            prefix = idnumber_val.split("-")[0].strip()
            if prefix in config.categories:
                target_spec = config.categories[prefix]

        if target_spec is None and idnumber_val:
            for s in config.categories.values():
                if s.idnumber and idnumber_val.startswith(s.idnumber):
                    target_spec = s
                    break

        cat_chain: list[CategorySpec] = []
        if target_spec:
            if config.root_category and target_spec.path != config.root_category:
                root_spec = CategorySpec(path=config.root_category)
                for s in config.categories.values():
                    if s.path == config.root_category:
                        root_spec = s
                        break
                cat_chain.append(root_spec)
            cat_chain.append(target_spec)
        elif config.root_category:
            cat_chain.append(CategorySpec(path=config.root_category))

        for spec in reversed(cat_chain):
            cat_elem = etree.Element("question", type="category")
            c_tag = etree.SubElement(cat_elem, "category")
            t_tag = etree.SubElement(c_tag, "text")
            t_tag.text = spec.path

            info_tag = etree.SubElement(cat_elem, "info", format="html")
            info_t = etree.SubElement(info_tag, "text")
            info_t.text = _wrap_cdata_if_needed(spec.info)

            id_tag = etree.SubElement(cat_elem, "idnumber")
            id_tag.text = spec.idnumber

            root.insert(0, cat_elem)

    # 2. Normalize question tags
    _ensure_text_subelement(q, "name", "Untitled Question")
    _ensure_text_subelement(q, "questiontext", "<p>[[input:ans1]] [[validation:ans1]]</p>", is_cdata=True, format_attr="html")
    _ensure_text_subelement(q, "generalfeedback", "", is_cdata=True, format_attr="html")
    _ensure_simple_subelement(q, "defaultgrade", config.defaults.get("defaultgrade", "1.0000000"))
    _ensure_simple_subelement(q, "penalty", config.defaults.get("penalty", "0.1000000"))
    _ensure_simple_subelement(q, "hidden", config.defaults.get("hidden", "0"))
    _ensure_simple_subelement(q, "idnumber", "")
    _ensure_text_subelement(q, "stackversion", config.stack_version)
    _ensure_text_subelement(q, "questionvariables", "")
    _ensure_text_subelement(q, "specificfeedback", "<p>[[feedback:prt1]]</p>", is_cdata=True, format_attr="html")
    _ensure_text_subelement(q, "questionnote", "", is_cdata=True, format_attr="html")
    _ensure_text_subelement(q, "questiondescription", "", is_cdata=True, format_attr="html")
    _ensure_simple_subelement(q, "questionsimplify", config.defaults.get("questionsimplify", "1"))
    _ensure_simple_subelement(q, "assumepositive", config.defaults.get("assumepositive", "0"))
    _ensure_simple_subelement(q, "assumereal", config.defaults.get("assumereal", "0"))
    _ensure_text_subelement(q, "prtcorrect", config.defaults.get("prtcorrect", '<p><i class="fa fa-check"></i> Correct answer, well done.</p>'), is_cdata=True, format_attr="html")
    _ensure_text_subelement(q, "prtpartiallycorrect", config.defaults.get("prtpartiallycorrect", '<p><i class="fa fa-adjust"></i> Your answer is partially correct.</p>'), is_cdata=True, format_attr="html")
    _ensure_text_subelement(q, "prtincorrect", config.defaults.get("prtincorrect", '<p><i class="fa fa-times"></i> Incorrect answer.</p>'), is_cdata=True, format_attr="html")
    _ensure_simple_subelement(q, "decimals", config.defaults.get("decimals", "."))
    _ensure_simple_subelement(q, "scientificnotation", config.defaults.get("scientificnotation", "*10"))
    _ensure_simple_subelement(q, "multiplicationsign", config.defaults.get("multiplicationsign", "onum"))
    _ensure_simple_subelement(q, "sqrtsign", config.defaults.get("sqrtsign", "1"))
    _ensure_simple_subelement(q, "complexno", config.defaults.get("complexno", "i"))
    _ensure_simple_subelement(q, "inversetrig", config.defaults.get("inversetrig", "cos-1"))
    _ensure_simple_subelement(q, "logicsymbol", config.defaults.get("logicsymbol", "lang"))
    _ensure_simple_subelement(q, "matrixparens", config.defaults.get("matrixparens", "["))
    _ensure_simple_subelement(q, "variantsselectionseed", "")
    _ensure_simple_subelement(q, "isbroken", "0")

    # 3. Detect and normalize Inputs
    qtext = _extract_element_text(q.find("./questiontext/text"))
    referenced_inputs = re.findall(r"\[\[input:([a-zA-Z0-9_]+)\]\]", qtext)

    existing_inputs: dict[str, etree._Element] = {}
    for inp in q.findall("./input"):
        inp_name = (inp.findtext("./name") or inp.get("name") or "").strip()
        if inp_name:
            existing_inputs[inp_name] = inp
            if "name" in inp.attrib:
                del inp.attrib["name"]

    inputs_to_ensure = referenced_inputs if referenced_inputs else (list(existing_inputs.keys()) if existing_inputs else ["ans1"])

    for idx, inp_name in enumerate(inputs_to_ensure, start=1):
        if inp_name not in existing_inputs:
            new_inp = etree.SubElement(q, "input")
            existing_inputs[inp_name] = new_inp
        else:
            new_inp = existing_inputs[inp_name]

        _ensure_simple_subelement(new_inp, "name", inp_name)
        _ensure_simple_subelement(new_inp, "type", config.input_defaults.get("type", "algebraic"))
        _ensure_simple_subelement(new_inp, "tans", f"ta{idx}")
        _ensure_simple_subelement(new_inp, "boxsize", config.input_defaults.get("boxsize", "15"))
        _ensure_simple_subelement(new_inp, "strictsyntax", config.input_defaults.get("strictsyntax", "1"))
        _ensure_simple_subelement(new_inp, "insertstars", config.input_defaults.get("insertstars", "0"))
        _ensure_simple_subelement(new_inp, "syntaxhint", config.input_defaults.get("syntaxhint", ""))
        _ensure_simple_subelement(new_inp, "syntaxattribute", config.input_defaults.get("syntaxattribute", "0"))
        _ensure_simple_subelement(new_inp, "forbidwords", config.input_defaults.get("forbidwords", ""))
        _ensure_simple_subelement(new_inp, "allowwords", config.input_defaults.get("allowwords", ""))
        _ensure_simple_subelement(new_inp, "forbidfloat", config.input_defaults.get("forbidfloat", "1"))
        _ensure_simple_subelement(new_inp, "requirelowestterms", config.input_defaults.get("requirelowestterms", "0"))
        _ensure_simple_subelement(new_inp, "checkanswertype", config.input_defaults.get("checkanswertype", "0"))
        _ensure_simple_subelement(new_inp, "mustverify", config.input_defaults.get("mustverify", "1"))
        _ensure_simple_subelement(new_inp, "showvalidation", config.input_defaults.get("showvalidation", "1"))
        _ensure_simple_subelement(new_inp, "options", config.input_defaults.get("options", ""))

    # 4. Detect and normalize PRTs
    specfb = _extract_element_text(q.find("./specificfeedback/text"))
    referenced_prts = re.findall(r"\[\[feedback:([a-zA-Z0-9_]+)\]\]", specfb + " " + qtext)
    existing_prts: dict[str, etree._Element] = {}
    for prt in q.findall("./prt"):
        prt_name = (prt.findtext("./name") or prt.get("name") or "").strip()
        if prt_name:
            existing_prts[prt_name] = prt
            if "name" in prt.attrib:
                del prt.attrib["name"]

    prts_to_ensure = referenced_prts if referenced_prts else (list(existing_prts.keys()) if existing_prts else ["prt1"])

    for idx, prt_name in enumerate(prts_to_ensure, start=1):
        if prt_name not in existing_prts:
            new_prt = etree.SubElement(q, "prt")
            existing_prts[prt_name] = new_prt
        else:
            new_prt = existing_prts[prt_name]

        _ensure_simple_subelement(new_prt, "name", prt_name)
        _ensure_simple_subelement(new_prt, "value", config.prt_defaults.get("value", "1.0000000"))
        _ensure_simple_subelement(new_prt, "autosimplify", config.prt_defaults.get("autosimplify", "1"))
        _ensure_simple_subelement(new_prt, "feedbackstyle", config.prt_defaults.get("feedbackstyle", "1"))
        _ensure_text_subelement(new_prt, "feedbackvariables", "")

        nodes = new_prt.findall("./node")
        if not nodes:
            node = etree.SubElement(new_prt, "node")
            nodes.append(node)

        for n_idx, node in enumerate(nodes):
            node_name = (node.findtext("./name") or node.get("name") or str(n_idx)).strip()
            if "name" in node.attrib:
                del node.attrib["name"]
            _ensure_simple_subelement(node, "name", node_name)
            _ensure_simple_subelement(node, "description", "")
            _ensure_simple_subelement(node, "answertest", "AlgEquiv")
            _ensure_simple_subelement(node, "sans", f"ans{idx}")
            _ensure_simple_subelement(node, "tans", f"ta{idx}")
            _ensure_simple_subelement(node, "testoptions", "")
            _ensure_simple_subelement(node, "quiet", "0")
            _ensure_simple_subelement(node, "truescoremode", "=")
            _ensure_simple_subelement(node, "truescore", "1")
            _ensure_simple_subelement(node, "truepenalty", "")
            _ensure_simple_subelement(node, "truenextnode", "-1")
            _ensure_simple_subelement(node, "trueanswernote", f"{prt_name}-{n_idx + 1}-T")
            _ensure_text_subelement(node, "truefeedback", "", is_cdata=True, format_attr="html")
            _ensure_simple_subelement(node, "falsescoremode", "=")
            _ensure_simple_subelement(node, "falsescore", "0")
            _ensure_simple_subelement(node, "falsepenalty", "")
            _ensure_simple_subelement(node, "falsenextnode", "-1")
            _ensure_simple_subelement(node, "falseanswernote", f"{prt_name}-{n_idx + 1}-F")
            _ensure_text_subelement(node, "falsefeedback", "", is_cdata=True, format_attr="html")

    # 5. Reorder tags inside <question type="stack"> to match canonical Moodle layout
    ordered_children: list[etree._Element] = []
    children_by_tag: dict[str, list[etree._Element]] = {}
    for c in list(q):
        children_by_tag.setdefault(c.tag, []).append(c)

    for tag in STACK_QUESTION_TAG_ORDER:
        if tag in children_by_tag:
            ordered_children.extend(children_by_tag.pop(tag))

    reserved_tags = {"input", "prt", "deployedseed", "qtest", "hint"}
    for tag in list(children_by_tag.keys()):
        if tag not in reserved_tags:
            ordered_children.extend(children_by_tag.pop(tag))

    for tag in ["input", "prt", "deployedseed", "qtest", "hint"]:
        if tag in children_by_tag:
            ordered_children.extend(children_by_tag.pop(tag))

    q[:] = ordered_children

    return _serialize_xml(root)


def format_question_file(path: Path, config: CourseConfig | None = None) -> None:
    """Read, normalize, and format a question XML file in-place."""
    if config is None:
        config, _ = find_course_config(path.parent)

    xml_content = path.read_text(encoding="utf-8")
    category_id = path.parent.name
    normalized = normalize_question_xml(xml_content, config, category_id=category_id)
    path.write_text(normalized, encoding="utf-8")


def scaffold_question(category_id: str, idnumber: str, name: str, config: CourseConfig) -> str:
    """Generate a clean starter randomized STACK question normalized with config."""
    minimal_xml = f"""<quiz>
  <question type="stack">
    <name>
      <text>{name}</text>
    </name>
    <idnumber>{idnumber}</idnumber>
    <questionvariables>
      <text>a : rand(5) + 1;
b : rand(5) + 1;
ta1 : a + b;</text>
    </questionvariables>
    <questiontext format="html">
      <text><![CDATA[<p>Calculate \\({{@a@}} + {{@b@}}\\):</p>
<p>[[input:ans1]] [[validation:ans1]]</p>]]></text>
    </questiontext>
    <questionnote format="html">
      <text><![CDATA[<p>{{@a@}}+{{@b@}}={{@ta1@}}</p>]]></text>
    </questionnote>
  </question>
</quiz>"""
    return normalize_question_xml(minimal_xml, config, category_id=category_id)


def prepare_for_api(xml_str: str, seed_override: int | None = None) -> tuple[str, int | None, bool]:
    """Prepare a question XML for Moodle / PHP API evaluation.
    
    Strips category questions, inspects seeds and randomization, applies seed overrides,
    and returns (clean_xml_str, effective_seed, had_deployed_seeds).
    """
    root, _ = _get_xml_root(xml_str)

    # Remove all category elements in-memory
    for cat in root.findall(".//question[@type='category']"):
        parent = cat.getparent()
        if parent is not None:
            parent.remove(cat)

    q = root.find(".//question[@type='stack']")
    if q is None and root.tag == "question" and root.get("type") == "stack":
        new_quiz = etree.Element("quiz")
        new_quiz.append(root)
        root = new_quiz
        q = root.find(".//question[@type='stack']")

    if q is None:
        raise ValueError("No <question type='stack'> found in XML")

    seeds: list[int] = []
    for s in q.findall("./deployedseed"):
        val = (s.text or "").strip()
        if val and (val.isdigit() or (val.startswith("-") and val[1:].isdigit())):
            seeds.append(int(val))

    had_deployed_seeds = len(seeds) > 0

    qvars = _extract_element_text(q.find("./questionvariables/text"))
    uses_random = bool(re.search(r"\brand(?:_[a-z_]+)?\s*\(", qvars))

    effective_seed: int | None = None

    if seed_override is not None:
        effective_seed = seed_override
        for s in q.findall("./deployedseed"):
            q.remove(s)
        s_elem = etree.SubElement(q, "deployedseed")
        s_elem.text = str(seed_override)
    elif had_deployed_seeds:
        effective_seed = seeds[0]
    elif uses_random:
        effective_seed = 12345
        s_elem = etree.SubElement(q, "deployedseed")
        s_elem.text = "12345"
    else:
        effective_seed = None

    clean_xml_str = _serialize_xml(root)
    return clean_xml_str, effective_seed, had_deployed_seeds


def set_deployed_seeds(xml_path: Path, seeds: list[int]) -> None:
    """Replace all <deployedseed> elements in a question XML file cleanly."""
    root, _ = _get_xml_root(xml_path)
    q = find_stack_question(root)

    if q is None:
        raise ValueError("No <question type='stack'> found in XML")

    for s in q.findall("./deployedseed"):
        q.remove(s)

    if seeds:
        insert_idx = len(q)
        for i, child in enumerate(q):
            if child.tag in ("qtest", "hint"):
                insert_idx = i
                break

        for seed in seeds:
            s_elem = etree.Element("deployedseed")
            s_elem.text = str(seed)
            q.insert(insert_idx, s_elem)
            insert_idx += 1

    xml_path.write_text(_serialize_xml(root), encoding="utf-8")


def upsert_qtest(
    xml_path: Path,
    testcase: int | None,
    description: str,
    inputs: dict[str, str],
    expected: dict[str, dict[str, str]],
) -> int:
    """Add or update a <qtest> element in xml_path. Returns the assigned testcase number."""
    root, _ = _get_xml_root(xml_path)
    q = find_stack_question(root)

    if q is None:
        raise ValueError("No <question type='stack'> found in XML")

    existing_qtests = q.findall("./qtest")

    if testcase is None:
        existing_tc_nums: list[int] = []
        for qt in existing_qtests:
            tc_str = qt.findtext("./testcase") or ""
            if tc_str.isdigit():
                existing_tc_nums.append(int(tc_str))
        assigned_tc = (max(existing_tc_nums) + 1) if existing_tc_nums else 1
        target_qtest = None
    else:
        assigned_tc = testcase
        target_qtest = None
        for qt in existing_qtests:
            if qt.findtext("./testcase") == str(assigned_tc):
                target_qtest = qt
                break

    if target_qtest is None:
        target_qtest = etree.Element("qtest")
        insert_idx = len(q)
        for i, child in enumerate(q):
            if child.tag == "hint":
                insert_idx = i
                break
        q.insert(insert_idx, target_qtest)
    else:
        target_qtest.clear()

    tc_elem = etree.SubElement(target_qtest, "testcase")
    tc_elem.text = str(assigned_tc)

    desc_elem = etree.SubElement(target_qtest, "description")
    desc_elem.text = description

    for inp_name, inp_val in inputs.items():
        ti = etree.SubElement(target_qtest, "testinput")
        n_elem = etree.SubElement(ti, "name")
        n_elem.text = inp_name
        v_elem = etree.SubElement(ti, "value")
        v_elem.text = inp_val

    for prt_name, exp_dict in expected.items():
        exp = etree.SubElement(target_qtest, "expected")
        n_elem = etree.SubElement(exp, "name")
        n_elem.text = prt_name
        s_elem = etree.SubElement(exp, "expectedscore")
        s_elem.text = exp_dict.get("expectedscore", "1.0000000")
        p_elem = etree.SubElement(exp, "expectedpenalty")
        p_elem.text = exp_dict.get("expectedpenalty", "0.0000000")
        an_elem = etree.SubElement(exp, "expectedanswernote")
        an_elem.text = exp_dict.get("expectedanswernote", "")

    xml_path.write_text(_serialize_xml(root), encoding="utf-8")
    return assigned_tc


def extract_hints(xml_str: str) -> list[str]:
    """Extract HTML hint strings from <hint><text> elements."""
    root, _ = _get_xml_root(xml_str)
    hints: list[str] = []
    for h in root.findall(".//hint"):
        t = _extract_element_text(h.find("./text"))
        hints.append(t)
    return hints
