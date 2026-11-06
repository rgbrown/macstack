"""macstack Command-Line Interface (CLI)."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any, NoReturn

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
import typer

from macstack.cas_errors import CasDiagnostic, parse_and_enrich_cas_errors
from macstack.config import (
    CourseConfig,
    find_course_config,
    save_config,
    slugify,
)
from macstack.edit_session import EditSession
from macstack.engine import StackEngine, StackEngineError
from macstack.linter import LintIssue, lint_question
from macstack.preview_server import run_preview
from macstack.repl import launch_repl
from macstack.runtime import (
    doctor as run_doctor,
    setup_runtime,
    stop_php_server as do_stop_php_server,
)
from macstack.sketch import (
    SketchError,
    apply_sketch,
    parse_sketch,
    sketch_file,
)
from macstack.xml_codec import (
    bundle_bank,
    format_question_file,
    parse_question_summary,
    prepare_for_api,
    scaffold_question,
    set_deployed_seeds,
    split_bank,
    upsert_qtest,
)

app = typer.Typer(
    name="macstack",
    help="macstack — Local Moodle STACK question workbench, testing, and Maxima CAS toolkit.",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)


def _parse_key_val_options(pairs: list[str]) -> dict[str, str]:
    """Parse repeatable -a key=val options into a dictionary."""
    out: dict[str, str] = {}
    for p in pairs:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out[p.strip()] = ""
    return out


def _extract_model_answers(render_inputs: dict[str, Any]) -> dict[str, str]:
    """Convert STACK render['inputs'] samplesolution into standard grade answers map."""
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


def _find_xml_files(paths: list[Path]) -> list[Path]:
    """Find all STACK question XML files within a list of files or directories."""
    files: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix.lower() == ".xml":
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(p.glob("**/*.xml")))
    return sorted(set(files))


def _render_cas_diagnostics_panel(diags: list[CasDiagnostic], title: str = "Maxima Evaluation Error") -> Panel:
    """Format CasDiagnostic list into a styled Rich Panel with escaped Maxima expressions."""
    lines: list[str] = []
    for d in diags:
        header = f"[bold red]• {escape(d.label)}[/bold red]"
        if d.line is not None:
            pos = f" (line {d.line}" + (f", col {d.col}" if d.col is not None else "") + ")"
            header += f" [dim]{escape(pos)}[/dim]"
        lines.append(header)
        lines.append(f"  {escape(d.message)}")
        if d.snippet:
            lines.append("")
            for s_line in d.snippet.splitlines():
                lines.append(f"    [dim]{escape(s_line)}[/dim]")
            lines.append("")

    content = "\n".join(lines).strip()
    return Panel(content or "[red]Unknown Maxima error[/red]", title=title, border_style="red")


def _handle_cli_cas_error(
    raw_err: str,
    xml_str: str,
    engine: StackEngine | None = None,
    api_xml: str | None = None,
    seed: int | None = None,
    as_json: bool = False,
    probed_errors: list[dict[str, Any]] | None = None,
) -> NoReturn:
    """Enrich a raw Maxima error or StackEngineError and terminate the CLI with exit code 1."""
    if "must validate true before compiling" in raw_err and probed_errors is None and engine and api_xml:
        try:
            v = engine.inspect_vars(api_xml, seed=seed)
            probed_errors = v.get("probed_errors")
        except Exception:
            pass

    diags = parse_and_enrich_cas_errors(
        raw_err,
        xml_str=xml_str,
        probed_errors=probed_errors,
        seed=seed,
    )

    if as_json:
        console.print_json(json.dumps({
            "ok": False,
            "error": diags[0].message if diags else raw_err,
            "cas_errors": [d.to_dict() for d in diags],
        }))
        raise typer.Exit(code=1)

    err_console.print(_render_cas_diagnostics_panel(diags))
    raise typer.Exit(code=1)


# ==============================================================================
# Commands
# ==============================================================================

@app.command()
def setup(
    force: bool = typer.Option(False, "--force", "-f", help="Recompile core and re-download assets"),
) -> None:
    """Setup local STACK runtime, precompiled Maxima image, and agent skills."""
    with console.status("[bold green]Setting up macstack runtime..."):
        res = setup_runtime(force=force, install_skill=True)

    console.print(Panel(
        f"[bold green]Setup Completed Successfully[/bold green]\n\n"
        f"• Runtime Directory: {res['runtime_dir']}\n"
        f"• PHP Version:       {res['php_version']}\n"
        f"• Maxima Version:    {res['maxima_version']}\n"
        f"• STACK Version:     {res['stack_version']}\n"
        f"• Optimised Core:    {res['optimised_image']}\n"
        f"• Skill Symlink:     {'Installed' if res.get('skill_installed') else 'Skipped'}",
        title="macstack setup",
        border_style="green",
    ))


@app.command()
def doctor(
    as_json: bool = typer.Option(False, "--json", help="Output healthcheck in JSON format"),
) -> None:
    """Run full diagnostic healthcheck of STACK binaries, PHP bridge, and CAS."""
    data = run_doctor()

    if as_json:
        console.print_json(json.dumps(data))
        if not data.get("ok"):
            raise typer.Exit(code=1)
        return

    table = Table(title="macstack System Healthcheck", border_style="blue")
    table.add_column("Component", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    for check in data.get("checks", []):
        status = "[green]✓ PASS[/green]" if check["passed"] else "[red]✗ FAIL[/red]"
        table.add_row(check["name"], status, check["details"])

    console.print(table)
    console.print(f"CAS Latency: [bold]{data.get('cas_latency_ms', 0):.2f} ms[/bold]")

    if not data.get("ok"):
        console.print("[bold red]One or more healthchecks failed.[/bold red]")
        raise typer.Exit(code=1)


@app.command("stop-server")
def stop_server() -> None:
    """Stop the background PHP bridge server process."""
    stopped = do_stop_php_server()
    if stopped:
        console.print("[green]PHP bridge server stopped.[/green]")
    else:
        console.print("[dim]No running PHP bridge server found.[/dim]")


@app.command()
def init(
    directory: Path = typer.Argument(Path("."), help="Project root directory"),
) -> None:
    """Initialize a new STACK question course workspace."""
    d = directory.resolve()
    q_dir = d / "questions"
    q_dir.mkdir(parents=True, exist_ok=True)

    toml_path = d / "macstack.toml"
    if not toml_path.exists():
        cfg = CourseConfig()
        save_config(cfg, toml_path)
        console.print(f"[green]Created {toml_path}[/green]")
    else:
        console.print(f"[yellow]{toml_path} already exists[/yellow]")

    console.print(f"[green]Created questions directory at {q_dir}[/green]")


@app.command()
def split(
    export_xml: Path = typer.Argument(..., help="Path to Moodle XML export file"),
    out_dir: Path = typer.Option(Path("."), "--out-dir", "-o", help="Output directory"),
) -> None:
    """Split a Moodle STACK XML export file into discrete questions and macstack.toml."""
    if not export_xml.exists():
        err_console.print(f"[red]File not found: {export_xml}[/red]")
        raise typer.Exit(code=1)

    with console.status(f"[bold cyan]Splitting {export_xml.name}..."):
        cfg, files = split_bank(export_xml, out_dir)

    console.print(Panel(
        f"[bold green]Successfully Split Bank[/bold green]\n\n"
        f"• Export Source:  {export_xml}\n"
        f"• Questions:      {len(files)} files created\n"
        f"• Output Root:    {out_dir}\n"
        f"• Config File:    {out_dir / 'macstack.toml'}",
        title="macstack split",
        border_style="green",
    ))


@app.command()
def bundle(
    paths: list[Path] = typer.Argument(..., help="Files or directories to bundle"),
    output: Path = typer.Option(..., "--output", "-o", help="Target output .xml file"),
) -> None:
    """Bundle question files or directories into a single deduplicated Moodle XML file."""
    with console.status("[bold cyan]Bundling STACK questions..."):
        count = bundle_bank(paths, output)

    console.print(f"[green]Bundled {count} questions into {output}[/green]")


def scaffold_new_question(
    target: str | Path,
    name: str = "",
    category: str = "",
) -> Path:
    """Scaffold a new STACK question XML with full category headers and defaults."""
    target_path = Path(target)
    if not str(target).endswith(".xml"):
        target_path = Path(str(target) + ".xml")

    # If target has a parent directory, use that as category hint
    config, _ = find_course_config(target_path.resolve())

    cat_id = ""
    if category:
        cat_id = slugify(category.split("::")[-1].split("/")[-1])
        if cat_id not in config.categories:
            config.categories[cat_id] = CourseConfig().categories.get(cat_id) or CourseConfig.default_category(
                idnumber=cat_id,
                path=category.replace("::", "/"),
            ) if hasattr(CourseConfig, "default_category") else None  # type: ignore

    idnumber = target_path.stem
    q_name = name or idnumber

    xml_content = scaffold_question(cat_id, idnumber, q_name, config)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(xml_content, encoding="utf-8")

    format_question_file(target_path, config)
    return target_path


@app.command()
def new(
    target: str = typer.Argument(..., help="Target question path or idnumber"),
    name: str = typer.Option("", "--name", "-n", help="Human-readable question name"),
    category: str = typer.Option("", "--category", "-c", help="Stream/Moodle category path"),
) -> None:
    """Scaffold a new STACK question XML with full category headers and defaults."""
    target_path = scaffold_new_question(target, name=name, category=category)
    console.print(f"[green]Scaffolded question at {escape(str(target_path))}[/green]")


@app.command()
def edit(
    target: Path = typer.Argument(..., help="Path to STACK question XML"),
    editor: str | None = typer.Option(None, "--editor", "-e", help="Editor command to use"),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open an editor, just watch"),
    name: str = typer.Option("", "--name", "-n", help="Question name if scaffolding a new file"),
    category: str = typer.Option("", "--category", "-c", help="Category path if scaffolding a new file"),
) -> None:
    """Live-edit a STACK question via an ephemeral synced sketch file."""
    target_path = target
    if not str(target).endswith(".xml"):
        target_path = Path(str(target) + ".xml")

    if not target_path.exists():
        target_path = scaffold_new_question(target_path, name=name, category=category)
        console.print(f"[green]Scaffolded question at {escape(str(target_path))}[/green]")

    config, toml_path = find_course_config(target_path.resolve())
    course_root = toml_path.parent.resolve() if toml_path else target_path.resolve().parent

    session = EditSession(
        xml_path=target_path,
        config=config,
        course_root=course_root,
        editor_cmd=editor,
        open_editor=not no_open,
        out=lambda msg: console.print(escape(str(msg))),
        prompt=lambda msg: typer.prompt(msg, default="resume"),
    )
    try:
        session.run()
    except RuntimeError as e:
        console.print(f"[yellow]{escape(str(e))}[/yellow]")


@app.command()
def sketch(
    xml_path: Path = typer.Argument(..., help="Path to STACK question XML file"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Target output .stack.md file"),
) -> None:
    """Export a STACK question XML to a compact sketch (.stack.md)."""
    if not xml_path.exists():
        err_console.print(f"[red]File not found: {escape(str(xml_path))}[/red]")
        raise typer.Exit(code=1)

    config, _ = find_course_config(xml_path.resolve().parent)
    text = sketch_file(xml_path, config=config)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    else:
        typer.echo(text, nl=False)


@app.command()
def apply(
    sketch_path: Path = typer.Argument(..., help="Path to sketch (.stack.md) file"),
    xml_path: Path = typer.Argument(..., help="Path to target STACK question XML file"),
) -> None:
    """Apply a sketch file to a STACK question XML (created if missing)."""
    if not sketch_path.exists():
        err_console.print(f"[red]File not found: {escape(str(sketch_path))}[/red]")
        raise typer.Exit(code=1)

    sketch_text = sketch_path.read_text(encoding="utf-8")
    try:
        model = parse_sketch(sketch_text)
    except SketchError as e:
        typer.echo(f"{sketch_path}:{e.line}: {e.message}", err=True)
        raise typer.Exit(code=1)

    config, _ = find_course_config(xml_path.resolve().parent)
    base = xml_path.read_text(encoding="utf-8") if xml_path.exists() else None
    new_xml = apply_sketch(model, base, config, category_id=xml_path.parent.name)
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(new_xml, encoding="utf-8")

    issues = lint_question(xml_path)
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    console.print(
        f"Applied {escape(str(sketch_path))} -> {escape(str(xml_path))} "
        f"({len(errors)} error(s), {len(warnings)} warning(s))"
    )
    for err in errors:
        console.print(f"  [red]error[/red]: {escape(err.code)}: {escape(err.message)}")


@app.command()
def format(
    paths: list[Path] = typer.Argument(..., help="Question XML files or directories to format"),
) -> None:
    """Format STACK XML files, expanding defaults and category headers in-place."""
    xml_files = _find_xml_files(paths)
    if not xml_files:
        console.print("[yellow]No XML files found to format.[/yellow]")
        return

    count = 0
    for f in xml_files:
        try:
            format_question_file(f)
            count += 1
        except Exception as e:
            err_console.print(f"[red]Error formatting {f}: {e}[/red]")

    console.print(f"[green]Formatted {count} question file(s).[/green]")


@app.command()
def lint(
    paths: list[Path] = typer.Argument(..., help="Question XML files or directories to lint"),
    as_json: bool = typer.Option(False, "--json", help="Output diagnostics in JSON"),
    strict: bool = typer.Option(False, "--strict", help="Exit non-zero on warnings as well as errors"),
) -> None:
    """Run static linter across question XML files checking CASText, PRT, inputs & hygiene."""
    xml_files = _find_xml_files(paths)
    if not xml_files:
        console.print("[yellow]No XML files found to lint.[/yellow]")
        return

    all_issues: dict[str, list[LintIssue]] = {}
    total_errors = 0
    total_warnings = 0

    for f in xml_files:
        issues = lint_question(f)
        if issues:
            all_issues[str(f)] = issues
            for i in issues:
                if i.severity == "error":
                    total_errors += 1
                elif i.severity == "warning":
                    total_warnings += 1

    if as_json:
        out = {
            f: [i.to_dict() for i in issues]
            for f, issues in all_issues.items()
        }
        console.print_json(json.dumps(out))
        if total_errors > 0 or (strict and total_warnings > 0):
            raise typer.Exit(code=1)
        return

    if not all_issues:
        console.print(f"[green]✓ Lint passed cleanly across {len(xml_files)} question file(s).[/green]")
        return

    tree = Tree("[bold]Lint Diagnostics[/bold]")
    for f, issues in all_issues.items():
        file_branch = tree.add(f"[bold blue]{f}[/bold blue]")
        for i in issues:
            color = "red" if i.severity == "error" else ("yellow" if i.severity == "warning" else "dim")
            file_branch.add(f"[{color}][{i.severity.upper()}][/] [bold]{i.code}[/]: {i.message} ({i.field})")

    console.print(tree)
    console.print(f"\n[bold]{total_errors}[/bold] error(s), [bold]{total_warnings}[/bold] warning(s).")

    if total_errors > 0 or (strict and total_warnings > 0):
        raise typer.Exit(code=1)


@app.command()
def vars(
    question_xml: Path = typer.Argument(..., help="Question XML file"),
    seed: int | None = typer.Option(None, "--seed", "-s", help="Random seed to evaluate"),
    as_json: bool = typer.Option(False, "--json", help="Output variables in JSON"),
) -> None:
    """Evaluate and display question variables, teacher answers, and questionnote."""
    if not question_xml.exists():
        err_console.print(f"[red]File not found: {question_xml}[/red]")
        raise typer.Exit(code=1)

    engine = StackEngine()
    xml_str = question_xml.read_text(encoding="utf-8")
    api_xml, effective_seed, _ = prepare_for_api(xml_str, seed_override=seed)

    try:
        res = engine.inspect_vars(api_xml, seed=effective_seed)
    except StackEngineError as exc:
        _handle_cli_cas_error(exc.message, xml_str, engine=engine, api_xml=api_xml, seed=effective_seed, as_json=as_json)

    has_errors = bool(res.get("errors") or res.get("probed_errors"))
    diags: list[CasDiagnostic] = []
    if has_errors:
        diags = parse_and_enrich_cas_errors(
            res.get("errors", ""),
            xml_str=xml_str,
            probed_errors=res.get("probed_errors"),
            seed=effective_seed,
        )
        res["cas_errors"] = [d.to_dict() for d in diags]

    if as_json:
        console.print_json(json.dumps(res))
        if has_errors:
            raise typer.Exit(code=1)
        return

    table = Table(title=f"Question Variables (Seed: {res.get('seed', effective_seed)})", border_style="cyan")
    table.add_column("Variable", style="bold green")
    table.add_column("Evaluated Value", style="white")
    table.add_column("Definition Expression", style="dim")

    qvars = res.get("variables", [])
    if isinstance(qvars, list):
        for item in qvars:
            if isinstance(item, dict):
                table.add_row(
                    item.get("name", ""),
                    str(item.get("value", "")),
                    str(item.get("expr", "")),
                )
            else:
                table.add_row(str(item), "", "")
    elif isinstance(qvars, dict):
        for k, v in qvars.items():
            table.add_row(str(k), str(v), "")

    console.print(table)
    if res.get("questionnote"):
        console.print(Panel(res["questionnote"], title="Evaluated Question Note", border_style="green"))

    if has_errors:
        err_console.print(_render_cas_diagnostics_panel(diags))
        raise typer.Exit(code=1)


@app.command()
def render(
    question_xml: Path = typer.Argument(..., help="Question XML file"),
    seed: int | None = typer.Option(None, "--seed", "-s", help="Random seed to evaluate"),
    as_json: bool = typer.Option(False, "--json", help="Output render result in JSON"),
) -> None:
    """Render question CASText, inputs, sample solutions, and plot assets."""
    if not question_xml.exists():
        err_console.print(f"[red]File not found: {question_xml}[/red]")
        raise typer.Exit(code=1)

    engine = StackEngine()
    xml_str = question_xml.read_text(encoding="utf-8")
    api_xml, effective_seed, _ = prepare_for_api(xml_str, seed_override=seed)

    try:
        res = engine.render(api_xml, seed=effective_seed)
    except StackEngineError as exc:
        _handle_cli_cas_error(exc.message, xml_str, engine=engine, api_xml=api_xml, seed=effective_seed, as_json=as_json)

    if as_json:
        console.print_json(json.dumps(res))
        return

    console.print(Panel(res.get("questionrender", ""), title="Rendered Question Formulation", border_style="blue"))
    if res.get("questionsamplesolutiontext"):
        console.print(Panel(res["questionsamplesolutiontext"], title="Model Solution / Feedback", border_style="green"))


@app.command()
def validate(
    question_xml: Path = typer.Argument(..., help="Question XML file"),
    input_name: str = typer.Option(..., "--input", "-i", help="Input name (e.g. ans1)"),
    answer: list[str] = typer.Option([], "--answer", "-a", help="Student answer pair (e.g. -a ans1=3/4)"),
    seed: int | None = typer.Option(None, "--seed", "-s", help="Random seed to evaluate"),
    as_json: bool = typer.Option(False, "--json", help="Output validation result in JSON"),
) -> None:
    """Validate student input for syntax errors, typing, and forbidden words."""
    if not question_xml.exists():
        err_console.print(f"[red]File not found: {question_xml}[/red]")
        raise typer.Exit(code=1)

    answers_map = _parse_key_val_options(answer)
    engine = StackEngine()
    xml_str = question_xml.read_text(encoding="utf-8")
    api_xml, effective_seed, _ = prepare_for_api(xml_str, seed_override=seed)

    try:
        res = engine.validate(api_xml, input_name=input_name, answers=answers_map, seed=effective_seed)
    except StackEngineError as exc:
        _handle_cli_cas_error(exc.message, xml_str, engine=engine, api_xml=api_xml, seed=effective_seed, as_json=as_json)

    if as_json:
        console.print_json(json.dumps(res))
        return

    val_text = res.get("validation", res.get("Validation", ""))
    console.print(Panel(val_text or "[dim](empty validation)[/dim]", title=f"Validation: {input_name}", border_style="cyan"))


@app.command()
def grade(
    question_xml: Path = typer.Argument(..., help="Question XML file"),
    answer: list[str] = typer.Option([], "--answer", "-a", help="Student answer pair (e.g. -a ans1=3/4)"),
    use_tans: bool = typer.Option(False, "--tans", help="Automatically use teacher's model answer (tans)"),
    seed: int | None = typer.Option(None, "--seed", "-s", help="Random seed to evaluate"),
    as_json: bool = typer.Option(False, "--json", help="Output grade result in JSON"),
) -> None:
    """Grade student answers through the question PRTs."""
    if not question_xml.exists():
        err_console.print(f"[red]File not found: {question_xml}[/red]")
        raise typer.Exit(code=1)

    engine = StackEngine()
    xml_str = question_xml.read_text(encoding="utf-8")
    api_xml, effective_seed, _ = prepare_for_api(xml_str, seed_override=seed)

    student_answers = _parse_key_val_options(answer)

    if use_tans or not student_answers:
        try:
            rendered = engine.render(api_xml, seed=effective_seed)
        except StackEngineError as exc:
            _handle_cli_cas_error(exc.message, xml_str, engine=engine, api_xml=api_xml, seed=effective_seed, as_json=as_json)
        model_answers = _extract_model_answers(rendered.get("inputs", {}))
        final_answers = {**model_answers, **student_answers}
    else:
        final_answers = student_answers

    try:
        res = engine.grade(api_xml, answers=final_answers, seed=effective_seed)
    except StackEngineError as exc:
        _handle_cli_cas_error(exc.message, xml_str, engine=engine, api_xml=api_xml, seed=effective_seed, as_json=as_json)

    has_cas_err = bool(res.get("has_cas_error"))
    has_prt_err = bool(res.get("has_prt_errors"))

    if has_cas_err or has_prt_err:
        cas_diags: list[CasDiagnostic] = []
        if has_cas_err:
            cas_diags.extend(parse_and_enrich_cas_errors(
                res.get("error", ""),
                xml_str=xml_str,
                probed_errors=res.get("probed_errors"),
                seed=effective_seed,
            ))
        if has_prt_err:
            prtresults = res.get("prtresults") or {}
            for prt_name, prt_res in prtresults.items():
                if isinstance(prt_res, dict) and prt_res.get("errors"):
                    prt_diags = parse_and_enrich_cas_errors(
                        prt_res["errors"],
                        xml_str=xml_str,
                        probed_errors=res.get("probed_errors"),
                        seed=effective_seed,
                        default_field=f"prt:{prt_name}:feedbackvariables",
                    )
                    prt_res["diagnostics"] = [d.to_dict() for d in prt_diags]
                    cas_diags.extend(prt_diags)
        res["cas_errors"] = [d.to_dict() for d in cas_diags]

        if as_json:
            console.print_json(json.dumps(res))
            raise typer.Exit(code=1)

        title = "Maxima CAS Error" if has_cas_err else "PRT Grading Error (CAS)"
        err_console.print(_render_cas_diagnostics_panel(cas_diags, title=title))
        for prt_name, prt_res in (res.get("prtresults") or {}).items():
            if isinstance(prt_res, dict) and (prt_res.get("answernotes") or prt_res.get("trace")):
                notes_str = "\n".join(f"  • {n}" for n in prt_res.get("answernotes", []))
                trace_str = "\n".join(f"  > {t}" for t in prt_res.get("trace", []))
                body = ""
                if notes_str:
                    body += f"[bold]Answer Notes:[/bold]\n{escape(notes_str)}\n"
                if trace_str:
                    body += f"[bold]Trace:[/bold]\n{escape(trace_str)}"
                if body:
                    err_console.print(Panel(body, title=f"PRT {escape(prt_name)} Diagnostics", border_style="yellow"))
        raise typer.Exit(code=1)

    if as_json:
        console.print_json(json.dumps(res))
        return

    score = res.get("score")
    is_gradable = res.get("isgradable", True)

    color = "green" if score is not None and score >= 0.999 else ("yellow" if score and score > 0 else "red")
    console.print(Panel(
        f"[bold {color}]Score: {score if score is not None else 0.0:.2f} / 1.00[/bold {color}]\n"
        f"Gradable: {is_gradable}\n"
        f"Answers Submitted: {json.dumps(final_answers)}",
        title="Grade Result",
        border_style=color,
    ))


@app.command("deploy-seeds")
def deploy_seeds(
    question_xml: Path = typer.Argument(..., help="Question XML file"),
    count: int = typer.Option(50, "--count", "-n", help="Target number of unique seeds to deploy"),
    max_attempts: int = typer.Option(250, "--max-attempts", help="Maximum candidate seeds to evaluate"),
    as_json: bool = typer.Option(False, "--json", help="Output deployed seeds in JSON"),
) -> None:
    """Generate and write deduplicated error-free random seeds into <deployedseed> tags."""
    if not question_xml.exists():
        err_console.print(f"[red]File not found: {question_xml}[/red]")
        raise typer.Exit(code=1)

    engine = StackEngine()
    xml_str = question_xml.read_text(encoding="utf-8")
    api_xml, _, _ = prepare_for_api(xml_str)

    with console.status(f"[bold cyan]Deploying {count} unique seeds for {question_xml.name}..."):
        try:
            res = engine.deploy_seeds(api_xml, count=count, max_attempts=max_attempts)
        except StackEngineError as exc:
            _handle_cli_cas_error(exc.message, xml_str, engine=engine, api_xml=api_xml, as_json=as_json)

    seeds: list[int] = res.get("seeds", [])
    if seeds:
        set_deployed_seeds(question_xml, seeds)
        if as_json:
            console.print_json(json.dumps({"seeds": seeds, "count": len(seeds)}))
            return
        console.print(f"[green]Successfully deployed {len(seeds)} unique seed(s) to {question_xml}[/green]")
        return

    first_err = res.get("first_error") or "Failed to generate any error-free seeds."
    _handle_cli_cas_error(
        first_err,
        xml_str=xml_str,
        engine=engine,
        api_xml=api_xml,
        as_json=as_json,
        probed_errors=res.get("probed_errors"),
    )


@app.command("add-test")
def add_test(
    question_xml: Path = typer.Argument(..., help="Question XML file"),
    answer: list[str] = typer.Option([], "--answer", "-a", help="Input expression (e.g. -a ans1=tans)"),
    description: str = typer.Option("", "--description", "-d", help="Testcase description"),
    testcase: int | None = typer.Option(None, "--testcase", "-t", help="Testcase number (auto-assigned if omitted)"),
    expect: list[str] = typer.Option([], "--expect", "-e", help="Expected PRT outcome (e.g. -e prt1=1.0:0.0:prt1-1-T)"),
    seed: int | None = typer.Option(None, "--seed", "-s", help="Seed used for auto-recording expectations"),
    as_json: bool = typer.Option(False, "--json", help="Output added testcase in JSON"),
) -> None:
    """Add or update a <qtest> regression test in a question XML file."""
    if not question_xml.exists():
        err_console.print(f"[red]File not found: {question_xml}[/red]")
        raise typer.Exit(code=1)

    inputs_map = _parse_key_val_options(answer)
    expected_dict: dict[str, dict[str, str]] = {}

    if expect:
        for item in expect:
            if "=" in item:
                prt_name, exp_str = item.split("=", 1)
                parts = exp_str.split(":")
                score = parts[0] if len(parts) > 0 else "1.0000000"
                penalty = parts[1] if len(parts) > 1 else "0.0000000"
                note = parts[2] if len(parts) > 2 else ""
                expected_dict[prt_name.strip()] = {
                    "expectedscore": f"{float(score):.7f}",
                    "expectedpenalty": f"{float(penalty):.7f}",
                    "expectedanswernote": note.strip(),
                }
    else:
        # Auto-record expectations by running a provisional test in the engine
        engine = StackEngine()
        xml_str = question_xml.read_text(encoding="utf-8")
        summary = parse_question_summary(question_xml)

        provisional_tc = testcase or (summary.qtest_count + 1)
        provisional_expected = {
            prt: {"expectedscore": "0.0000000", "expectedpenalty": "0.0000000", "expectedanswernote": ""}
            for prt in summary.prts
        }

        # Build in-memory XML with provisional qtest
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as tf:
            tf.write(xml_str)
            tmp_path = Path(tf.name)

        try:
            upsert_qtest(tmp_path, testcase=provisional_tc, description=description, inputs=inputs_map, expected=provisional_expected)
            provisional_seed = seed
            if provisional_seed is None and summary.deployed_seeds:
                provisional_seed = summary.deployed_seeds[0]
            elif provisional_seed is None:
                provisional_seed = 1
            api_xml, eff_seed, _ = prepare_for_api(tmp_path.read_text(encoding="utf-8"), seed_override=provisional_seed)
            try:
                test_res = engine.run_tests(api_xml)
            except StackEngineError as exc:
                _handle_cli_cas_error(exc.message, xml_str=xml_str, engine=engine, api_xml=api_xml, seed=provisional_seed, as_json=as_json)

            # Extract actual outcomes
            results = test_res.get("results", {})
            seed_key = str(eff_seed) if (eff_seed is not None and str(eff_seed) in results) else ("noseed" if "noseed" in results else next(iter(results.keys()), None))
            if seed_key and seed_key in results:
                tc_data = results[seed_key].get("outcomes", {}).get(str(provisional_tc), {})
                actual_prt_outcomes = tc_data.get("outcomes", {})
                for prt_name, o in actual_prt_outcomes.items():
                    act_score = o.get("score", 0.0)
                    act_penalty = o.get("penalty", 0.0)
                    act_note = o.get("answernote", "").strip()
                    if "|" in act_note:
                        act_note = act_note.split("|")[-1].strip()
                    expected_dict[prt_name] = {
                        "expectedscore": f"{float(act_score):.7f}",
                        "expectedpenalty": f"{float(act_penalty):.7f}",
                        "expectedanswernote": act_note,
                    }
        finally:
            tmp_path.unlink(missing_ok=True)

    assigned_tc = upsert_qtest(
        question_xml,
        testcase=testcase,
        description=description,
        inputs=inputs_map,
        expected=expected_dict,
    )

    if as_json:
        console.print_json(json.dumps({
            "testcase": assigned_tc,
            "description": description,
            "inputs": inputs_map,
            "expected": expected_dict,
        }))
        return

    console.print(Panel(
        f"[bold green]Successfully Added <qtest> #{assigned_tc}[/bold green]\n\n"
        f"• Description: {description or '(none)'}\n"
        f"• Inputs:      {json.dumps(inputs_map)}\n"
        f"• Expected:    {json.dumps(expected_dict, indent=2)}",
        title="macstack add-test",
        border_style="green",
    ))


@app.command()
def test(
    paths: list[Path] = typer.Argument(..., help="Question XML files or directories to test"),
    seed: int | None = typer.Option(None, "--seed", "-s", help="Specific seed to evaluate"),
    as_json: bool = typer.Option(False, "--json", help="Output test results in JSON"),
) -> None:
    """Run all <qtest> test suites across deployed seeds for one or multiple questions."""
    xml_files = _find_xml_files(paths)
    if not xml_files:
        console.print("[yellow]No XML files found to test.[/yellow]")
        return

    engine = StackEngine()
    total_passes = 0
    total_fails = 0
    failures: list[dict[str, Any]] = []
    file_results: dict[str, Any] = {}

    for f in xml_files:
        try:
            xml_str = f.read_text(encoding="utf-8")
            api_xml, eff_seed, _ = prepare_for_api(xml_str, seed_override=seed)

            # If seed was explicitly requested, restrict deployed seeds in api_xml to just that seed
            if seed is not None:
                api_xml = re.sub(r"<deployedseed>.*?</deployedseed>", "", api_xml, flags=re.DOTALL)
                api_xml = api_xml.replace("</question>", f"  <deployedseed>{seed}</deployedseed>\n</question>", 1)

            res = engine.run_tests(api_xml)
            file_results[str(f)] = res

            if res.get("isupgradeerror"):
                failures.append({"file": str(f), "error": res.get("messages", "Upgrade error")})
                total_fails += 1
                continue

            results = res.get("results", {})
            for s_key, s_data in results.items():
                p = s_data.get("passes", 0) or 0
                fl = s_data.get("fails", 0) or 0
                s_msg = s_data.get("messages", "") if isinstance(s_data, dict) else ""
                has_msg_err = bool(s_msg and ("error" in s_msg.lower() or "must validate true before compiling" in s_msg))
                if has_msg_err:
                    fl += 1
                total_passes += p
                total_fails += fl
                if fl > 0:
                    fail_entry: dict[str, Any] = {"file": str(f), "seed": s_key, "data": s_data}
                    if has_msg_err:
                        probed = None
                        if "must validate true before compiling" in s_msg:
                            try:
                                v = engine.inspect_vars(api_xml, seed=seed)
                                probed = v.get("probed_errors")
                            except Exception:
                                pass
                        diags = parse_and_enrich_cas_errors(s_msg, xml_str=xml_str, probed_errors=probed, seed=seed)
                        fail_entry["error"] = diags[0].message if diags else s_msg
                        fail_entry["cas_errors"] = [d.to_dict() for d in diags]
                    failures.append(fail_entry)
        except StackEngineError as exc:
            total_fails += 1
            probed = None
            if "must validate true before compiling" in exc.message:
                try:
                    v = engine.inspect_vars(api_xml, seed=seed)
                    probed = v.get("probed_errors")
                except Exception:
                    pass
            diags = parse_and_enrich_cas_errors(
                exc.message,
                xml_str=xml_str,
                probed_errors=probed,
                seed=seed,
            )
            err_msg = diags[0].message if diags else exc.message
            failures.append({
                "file": str(f),
                "error": err_msg,
                "cas_errors": [d.to_dict() for d in diags],
            })
        except Exception as e:
            total_fails += 1
            failures.append({"file": str(f), "error": str(e)})

    if as_json:
        console.print_json(json.dumps({
            "ok": total_fails == 0,
            "passes": total_passes,
            "fails": total_fails,
            "failures": failures,
            "results": file_results,
        }))
        if total_fails > 0:
            raise typer.Exit(code=1)
        return

    if total_fails == 0:
        console.print(Panel(
            f"[bold green]All {total_passes} test cases passed cleanly across {len(xml_files)} file(s)![/bold green]",
            title="macstack test",
            border_style="green",
        ))
    else:
        table = Table(title="Test Failures", border_style="red")
        table.add_column("File", style="bold red")
        table.add_column("Seed / Reason")

        for fail in failures:
            table.add_row(fail["file"], str(fail.get("error", fail.get("seed", ""))))

        console.print(table)
        console.print(f"[bold red]Total Failures: {total_fails}[/bold red] (Passed: {total_passes})")
        raise typer.Exit(code=1)


@app.command()
def maxima(
    question_xml: Path | None = typer.Argument(None, help="Optional STACK question XML file"),
    seed: int | None = typer.Option(None, "--seed", "-s", help="Random seed to load"),
    eval_expr: list[str] = typer.Option([], "--eval", "-e", help="CAS expressions to evaluate in batch"),
) -> None:
    """Launch interactive rmaxima REPL or run batch expressions with STACK preloaded."""
    xml_content: str | None = None
    if question_xml is not None:
        if not question_xml.exists():
            err_console.print(f"[red]File not found: {question_xml}[/red]")
            raise typer.Exit(code=1)
        xml_content = question_xml.read_text(encoding="utf-8")

    if eval_expr:
        output = launch_repl(
            question_xml=xml_content,
            seed=seed,
            batch_commands=eval_expr,
        )
        print(output)
    else:
        sys.exit(launch_repl(question_xml=xml_content, seed=seed))


@app.command()
def preview(
    path: Path = typer.Argument(Path("."), help="Workspace directory or single question XML file"),
    port: int = typer.Option(8765, "--port", "-p", help="Port to serve workbench on"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open browser automatically"),
) -> None:
    """Start local live-reload STACK preview server and workbench."""
    console.print(f"[bold cyan]Starting macstack preview workbench at http://127.0.0.1:{port}...[/bold cyan]")
    run_preview(path, port=port, open_browser=not no_browser)


if __name__ == "__main__":
    app()
