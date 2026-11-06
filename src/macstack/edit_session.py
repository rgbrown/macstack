"""Interactive watch-mode editing session for STACK questions."""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

import watchfiles

from macstack.config import CourseConfig
from macstack.linter import lint_question
from macstack.sketch import (
    SKETCH_SUFFIX,
    SketchError,
    apply_sketch,
    parse_sketch,
    xml_to_sketch,
)


class EditSession:
    """Manages an ephemeral sketch editing session for a STACK question XML."""

    def __init__(
        self,
        xml_path: Path | str,
        config: CourseConfig,
        course_root: Path | str,
        editor_cmd: str | None = None,
        open_editor: bool = True,
        out: Callable[[str], Any] = print,
        prompt: Callable[[str], str] | None = None,
    ) -> None:
        self.xml_path = Path(xml_path).resolve()
        self.config = config
        self.course_root = Path(course_root).resolve()
        self.editor_cmd = editor_cmd
        self.open_editor = open_editor
        self.out = out
        self.prompt = prompt or (lambda msg: input(msg))

        # Compute sketch path relative to course_root
        try:
            rel_path = self.xml_path.relative_to(self.course_root)
        except ValueError:
            rel_path = Path(self.xml_path.name)

        if rel_path.name.lower().endswith(".xml"):
            rel_sketch_name = rel_path.name[:-4] + SKETCH_SUFFIX
        else:
            rel_sketch_name = rel_path.name + SKETCH_SUFFIX

        self.sketch_path = (
            self.course_root / ".macstack" / "edit" / rel_path.with_name(rel_sketch_name)
        ).resolve()

        self.synced_sketch_text: str = ""
        self.last_xml_text: str = ""
        self.last_error: SketchError | None = None

        self._buffer_output: bool = False
        self._output_buffer: list[str] = []

    def _ensure_macstack_dir(self) -> None:
        """Create .macstack/ and .macstack/.gitignore (self-ignoring) if missing."""
        macstack_dir = self.course_root / ".macstack"
        macstack_dir.mkdir(parents=True, exist_ok=True)
        gitignore = macstack_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*\n", encoding="utf-8")
        self.sketch_path.parent.mkdir(parents=True, exist_ok=True)

    def _cleanup_empty_dirs(self) -> None:
        """Remove empty parent directories up to .macstack/edit."""
        edit_root = (self.course_root / ".macstack" / "edit").resolve()
        curr = self.sketch_path.parent.resolve()
        while curr != self.course_root:
            if not curr.is_relative_to(edit_root):
                break
            try:
                curr.rmdir()
                if curr == edit_root:
                    break
                curr = curr.parent.resolve()
            except OSError:
                break

    def report(self, message: str) -> None:
        """Output a message or buffer it if a blocking terminal editor holds stdout."""
        if self._buffer_output:
            self._output_buffer.append(message)
        else:
            self.out(message)

    def resolve_editor_cmd(self) -> str | None:
        """Resolve editor command in precedence order: arg > config > $VISUAL > $EDITOR."""
        if self.editor_cmd:
            return self.editor_cmd
        if self.config.edit.get("editor"):
            return self.config.edit["editor"]
        if os.environ.get("VISUAL"):
            return os.environ["VISUAL"]
        if os.environ.get("EDITOR"):
            return os.environ["EDITOR"]
        return None

    def start(self) -> None:
        """Initialise sketch file and state. Handles leftover sketches with prompt."""
        if not self.xml_path.exists():
            raise FileNotFoundError(f"Question XML file does not exist: {self.xml_path}")

        self.last_xml_text = self.xml_path.read_text(encoding="utf-8")
        try:
            source_label = str(self.xml_path.relative_to(self.course_root))
        except ValueError:
            source_label = self.xml_path.name

        fresh_sketch = xml_to_sketch(self.last_xml_text, self.config, source_label=source_label)

        if self.sketch_path.exists():
            existing_sketch = self.sketch_path.read_text(encoding="utf-8")
            if existing_sketch != fresh_sketch:
                choice = self.prompt(
                    f"Leftover sketch found at {self.sketch_path}.\n"
                    "Resume, discard, or abort? [resume/discard/abort]: "
                )
                choice_norm = (choice or "").strip().lower()
                if choice_norm in ("resume", "r"):
                    try:
                        model = parse_sketch(existing_sketch)
                        new_xml = apply_sketch(
                            model,
                            self.last_xml_text,
                            self.config,
                            category_id=self.xml_path.parent.name,
                        )
                        if new_xml != self.last_xml_text:
                            self.xml_path.write_text(new_xml, encoding="utf-8")
                            self.last_xml_text = new_xml
                        self.synced_sketch_text = existing_sketch
                        self.last_error = None
                    except SketchError as err:
                        self.last_error = err
                        self.synced_sketch_text = ""
                        self.report(f"{self.sketch_path}:{err.line}: {err.message}")
                    return
                elif choice_norm in ("discard", "d"):
                    self._ensure_macstack_dir()
                    self.sketch_path.write_text(fresh_sketch, encoding="utf-8")
                    self.synced_sketch_text = fresh_sketch
                    self.last_error = None
                    return
                else:
                    raise RuntimeError("Edit session aborted by user.")
            else:
                self.synced_sketch_text = existing_sketch
                self.last_error = None
                return

        self._ensure_macstack_dir()
        self.sketch_path.write_text(fresh_sketch, encoding="utf-8")
        self.synced_sketch_text = fresh_sketch
        self.last_error = None

    def on_sketch_changed(self) -> None:
        """Handle modification to the sketch file on disk."""
        if not self.sketch_path.exists():
            return
        current_sketch = self.sketch_path.read_text(encoding="utf-8")
        if current_sketch == self.synced_sketch_text:
            return

        try:
            model = parse_sketch(current_sketch)
            self.last_error = None
        except SketchError as err:
            self.last_error = err
            self.report(f"{self.sketch_path}:{err.line}: {err.message}")
            return

        latest_xml = self.xml_path.read_text(encoding="utf-8") if self.xml_path.exists() else None
        new_xml = apply_sketch(model, latest_xml, self.config, category_id=self.xml_path.parent.name)
        if new_xml != latest_xml:
            self.xml_path.parent.mkdir(parents=True, exist_ok=True)
            self.xml_path.write_text(new_xml, encoding="utf-8")
        self.last_xml_text = new_xml
        self.synced_sketch_text = current_sketch

        issues = lint_question(self.xml_path)
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        self.report(f"Saved {self.xml_path.name} ({len(errors)} error(s), {len(warnings)} warning(s))")
        for err in errors:
            self.report(f"  error: {err.code}: {err.message}")

    def on_xml_changed(self) -> None:
        """Handle modification to the XML file on disk."""
        if not self.xml_path.exists():
            return
        current_xml = self.xml_path.read_text(encoding="utf-8")
        if current_xml == self.last_xml_text:
            return

        current_sketch = (
            self.sketch_path.read_text(encoding="utf-8") if self.sketch_path.exists() else ""
        )
        if current_sketch == self.synced_sketch_text:
            try:
                source_label = str(self.xml_path.relative_to(self.course_root))
            except ValueError:
                source_label = self.xml_path.name
            fresh_sketch = xml_to_sketch(current_xml, self.config, source_label=source_label)
            self.sketch_path.write_text(fresh_sketch, encoding="utf-8")
            self.synced_sketch_text = fresh_sketch
            self.last_xml_text = current_xml
        else:
            self.last_xml_text = current_xml
            self.report(
                f"Warning: {self.xml_path.name} changed externally; next save will be applied on top of latest XML."
            )

    def run(self, stop_event: threading.Event | None = None) -> None:
        """Start the edit session, launch the editor, and watch for file modifications."""
        self.start()
        if stop_event is None:
            stop_event = threading.Event()

        editor_proc: subprocess.Popen[Any] | None = None
        is_launcher = False

        resolved_cmd = self.resolve_editor_cmd()
        if self.open_editor and resolved_cmd:
            try:
                cmd_args = shlex.split(resolved_cmd) + [str(self.sketch_path)]
                editor_proc = subprocess.Popen(cmd_args)
                wait_start = time.time()
                while time.time() - wait_start < 1.5:
                    ret = editor_proc.poll()
                    if ret is not None:
                        if ret == 0:
                            is_launcher = True
                        else:
                            self.report(f"Editor exited with code {ret}")
                            editor_proc = None
                        break
                    time.sleep(0.05)

                if editor_proc is not None and editor_proc.poll() is None:
                    # Still running after 1.5s -> blocking editor
                    is_launcher = False
                    self._buffer_output = True
            except Exception as e:
                self.report(f"Failed to launch editor '{resolved_cmd}': {e}")
                editor_proc = None
                self.out(str(self.sketch_path))
        else:
            self.out(str(self.sketch_path))

        watch_dirs = {self.sketch_path.parent.resolve(), self.xml_path.parent.resolve()}
        try:
            for changes in watchfiles.watch(
                *watch_dirs,
                stop_event=stop_event,
                yield_on_timeout=True,
                rust_timeout=500,
                watch_filter=None,
            ):
                if stop_event.is_set():
                    break

                if editor_proc is not None and not is_launcher:
                    if editor_proc.poll() is not None:
                        break

                sketch_changed = False
                xml_changed = False
                for _, path_str in changes:
                    p = Path(path_str).resolve()
                    if p == self.sketch_path.resolve():
                        sketch_changed = True
                    elif p == self.xml_path.resolve():
                        xml_changed = True

                if sketch_changed:
                    self.on_sketch_changed()
                if xml_changed:
                    self.on_xml_changed()

        except KeyboardInterrupt:
            pass
        finally:
            if self._buffer_output:
                self._buffer_output = False
                for msg in self._output_buffer:
                    self.out(msg)
                self._output_buffer.clear()

            self.on_sketch_changed()

            if self.last_error is not None:
                self.out(f"Keeping sketch with errors: {self.sketch_path}")
            else:
                if self.sketch_path.exists():
                    try:
                        self.sketch_path.unlink()
                    except OSError:
                        pass
                self._cleanup_empty_dirs()
