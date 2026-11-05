"""Interactive and batch STACK Maxima REPL (via rmaxima or optimised SBCL)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from macstack.runtime import RUNTIME_DIR


def _parse_question_xml(xml_content: str) -> tuple[str, bool, str, list[int]]:
    """Parse question XML to extract name, simplify setting, questionvariables, and deployed seeds."""
    try:
        root = ET.fromstring(xml_content)
        q = root.find(".//question[@type='stack']")
        if q is None and root.tag == "question" and root.get("type") == "stack":
            q = root
        if q is None:
            q = root.find(".//question") if root.tag != "question" else root
        if q is None:
            return "STACK Question", True, "", []

        name_elem = q.find("./name/text")
        if name_elem is None:
            name_elem = q.find("./name")
        name = name_elem.text.strip() if name_elem is not None and name_elem.text else "STACK Question"

        simp_elem = q.find("./questionsimplify")
        simp = True
        if simp_elem is not None and simp_elem.text and simp_elem.text.strip() == "0":
            simp = False

        vars_elem = q.find("./questionvariables/text")
        if vars_elem is None:
            vars_elem = q.find("./questionvariables")
        qv = vars_elem.text.strip() if vars_elem is not None and vars_elem.text else ""

        seeds: list[int] = []
        for s in q.findall(".//deployedseed"):
            if s.text and s.text.strip().isdigit():
                seeds.append(int(s.text.strip()))

        return name, simp, qv, seeds
    except Exception:
        return "STACK Question", True, "", []


def _find_variable_names(qv_code: str) -> list[str]:
    """Find assigned variable names in Maxima code."""
    names: list[str] = []
    # Match assignment statements var: expr;
    for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*:", qv_code):
        var = m.group(1)
        if var not in names and var not in ("matrix", "list", "block"):
            names.append(var)
    return names


def launch_repl(
    question_xml: str | None = None,
    seed: int | None = None,
    batch_commands: list[str] | None = None,
    runtime_dir: Path | None = None,
) -> int | str:
    """Launch interactive rmaxima session or run batch commands against STACK Maxima environment.

    - If batch_commands is provided, executes them non-interactively and returns stdout string.
    - Otherwise, launches interactive rmaxima and returns process exit code.
    """
    rdir = runtime_dir or RUNTIME_DIR
    maximalocal = (rdir / "stack" / "maximalocal.mac").resolve()
    maxima_opt = (rdir / "stack" / "maxima-optimised").resolve()

    q_name = "STACK Session"
    simp = True
    qv_code = ""
    seeds: list[int] = []

    if question_xml:
        q_name, simp, qv_code, seeds = _parse_question_xml(question_xml)

    active_seed = seed
    if active_seed is None and seeds:
        active_seed = seeds[0]

    var_names = _find_variable_names(qv_code)
    var_str = ", ".join(var_names) if var_names else "(none)"

    # Build startup script
    lines = [
        f'load("{maximalocal}")$',
        f'simp: {"true" if simp else "false"}$',
    ]
    if active_seed is not None:
        lines.append(f"stack_randseed({active_seed})$")

    if qv_code:
        # Strip trailing dollar/semicolon if present and format safely
        cleaned_qv = qv_code.strip()
        lines.append(cleaned_qv)

    # Banner
    clean_title = q_name.replace('"', '\\"')
    seed_disp = str(active_seed) if active_seed is not None else "default"
    banner = [
        'print("==================================================")$',
        'print("STACK Maxima REPL")$',
        f'print("Question: {clean_title}")$',
        f'print("Seed: {seed_disp}")$',
        f'print("Variables defined: {var_str}")$',
        'print("==================================================")$',
    ]
    lines.extend(banner)

    init_script_content = "\n".join(lines) + "\n"

    with tempfile.NamedTemporaryFile("w", suffix=".mac", delete=False) as f:
        f.write(init_script_content)
        init_file = f.name

    try:
        env = os.environ.copy()
        if "/opt/homebrew/bin" not in env.get("PATH", ""):
            env["PATH"] = f"/opt/homebrew/bin:{env.get('PATH', '')}"

        if batch_commands is not None:
            # Batch non-interactive execution
            cmd_lines = [f'load("{init_file}")$']
            for cmd in batch_commands:
                c = cmd.strip()
                if not (c.endswith(";") or c.endswith("$")):
                    c += ";"
                cmd_lines.append(c)
            cmd_lines.append("quit();")

            runner = str(maxima_opt) if maxima_opt.exists() else "maxima"
            input_data = "\n".join(cmd_lines) + "\n"

            proc = subprocess.run(
                [runner],
                input=input_data,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            return proc.stdout

        # Interactive REPL
        rmaxima_bin = shutil.which("rmaxima") or "/opt/homebrew/bin/rmaxima"
        if not os.path.exists(rmaxima_bin):
            rmaxima_bin = shutil.which("maxima") or "/opt/homebrew/bin/maxima"

        cmd = [rmaxima_bin, "-p", init_file]
        return subprocess.call(cmd, env=env)

    finally:
        try:
            os.remove(init_file)
        except OSError:
            pass
