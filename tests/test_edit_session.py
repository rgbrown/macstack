"""Unit and integration tests for EditSession and sketch CLI commands."""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from macstack.cli import app
from macstack.config import CourseConfig, find_course_config
from macstack.edit_session import EditSession
from macstack.sketch import SKETCH_SUFFIX


@pytest.fixture
def demo_course(tmp_path: Path) -> tuple[Path, Path, CourseConfig]:
    """Copy examples/demo to tmp_path and return (course_dir, xml_path, config)."""
    course_dir = tmp_path / "course"
    shutil.copytree(Path("examples/demo"), course_dir)
    xml_path = course_dir / "questions" / "calculus" / "demo-power-integral.xml"
    cfg, _ = find_course_config(xml_path)
    return course_dir, xml_path, cfg


def test_sketch_path_and_gitignore_creation(demo_course: tuple[Path, Path, CourseConfig]) -> None:
    """Test sketch path calculation and self-ignoring .macstack/.gitignore creation."""
    course_dir, xml_path, cfg = demo_course

    session = EditSession(xml_path=xml_path, config=cfg, course_root=course_dir)
    expected_sketch = (
        course_dir / ".macstack" / "edit" / "questions" / "calculus" / ("demo-power-integral" + SKETCH_SUFFIX)
    )
    assert session.sketch_path == expected_sketch
    assert not (course_dir / ".macstack").exists()

    session.start()
    assert session.sketch_path.exists()

    gitignore_path = course_dir / ".macstack" / ".gitignore"
    assert gitignore_path.exists()
    assert gitignore_path.read_text(encoding="utf-8").strip() == "*"

    # Verify user's root .gitignore was not touched or created
    assert not (course_dir / ".gitignore").exists()


def test_fallback_sketch_path_outside_root(tmp_path: Path) -> None:
    """If XML path is not under course_root, sketch path falls back to XML file name."""
    root = tmp_path / "course"
    root.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    xml_path = other / "external-question.xml"
    xml_path.write_text("<question type='stack'><name><text>Ext</text></name></question>")

    session = EditSession(xml_path=xml_path, config=CourseConfig(), course_root=root)
    assert session.sketch_path == root / ".macstack" / "edit" / ("external-question" + SKETCH_SUFFIX)


def test_clean_external_xml_change_regenerates_sketch(demo_course: tuple[Path, Path, CourseConfig]) -> None:
    """When sketch is clean (unmodified), an external XML change regenerates the sketch."""
    course_dir, xml_path, cfg = demo_course

    session = EditSession(xml_path=xml_path, config=cfg, course_root=course_dir)
    session.start()

    sketch_before = session.sketch_path.read_text(encoding="utf-8")
    assert "antiderivative" not in sketch_before

    # Modify XML externally
    xml_before = xml_path.read_text(encoding="utf-8")
    xml_after = xml_before.replace("Evaluate the indefinite integral", "Find the antiderivative")
    xml_path.write_text(xml_after, encoding="utf-8")

    session.on_xml_changed()

    sketch_after = session.sketch_path.read_text(encoding="utf-8")
    assert sketch_after != sketch_before
    assert "Find the antiderivative" in sketch_after
    assert session.synced_sketch_text == sketch_after


def test_dirty_sketch_and_external_change_merges(demo_course: tuple[Path, Path, CourseConfig]) -> None:
    """When sketch is dirty and XML changes externally, warn; next sketch save merges both."""
    course_dir, xml_path, cfg = demo_course

    messages: list[str] = []
    session = EditSession(xml_path=xml_path, config=cfg, course_root=course_dir, out=messages.append)
    session.start()

    # User edits sketch in editor (dirty sketch)
    sketch_content = session.sketch_path.read_text(encoding="utf-8")
    dirty_sketch = sketch_content.replace(
        'name = "Indefinite Integral of a Polynomial"',
        'name = "Merged Integral Title"',
    )
    session.sketch_path.write_text(dirty_sketch, encoding="utf-8")

    # External change to XML: add a new deployed seed
    xml_content = xml_path.read_text(encoding="utf-8")
    assert "<deployedseed>999999</deployedseed>" not in xml_content
    xml_with_seed = xml_content.replace("<deployedseed>", "<deployedseed>999999</deployedseed>\n    <deployedseed>")
    xml_path.write_text(xml_with_seed, encoding="utf-8")

    # Watcher detects XML change
    session.on_xml_changed()

    # Check warning was reported
    assert any("changed externally" in m for m in messages)
    # Sketch file was NOT overwritten
    assert session.sketch_path.read_text(encoding="utf-8") == dirty_sketch

    # User saves sketch (watcher detects sketch change)
    session.on_sketch_changed()

    # Final XML must contain BOTH the user edit and the externally added seed
    final_xml = xml_path.read_text(encoding="utf-8")
    assert "Merged Integral Title" in final_xml
    assert "<deployedseed>999999</deployedseed>" in final_xml


def test_invalid_sketch_leaves_xml_untouched(demo_course: tuple[Path, Path, CourseConfig]) -> None:
    """A parse error in the sketch leaves the XML untouched and reports line number."""
    course_dir, xml_path, cfg = demo_course

    messages: list[str] = []
    session = EditSession(xml_path=xml_path, config=cfg, course_root=course_dir, out=messages.append)
    session.start()

    xml_before = xml_path.read_text(encoding="utf-8")

    # Introduce invalid answer test in sketch
    sketch_content = session.sketch_path.read_text(encoding="utf-8")
    bad_sketch = sketch_content.replace("Int(ans1, ta1, x)", "InvalidAnswerTestUnknown(ans1, ta1, x)")
    session.sketch_path.write_text(bad_sketch, encoding="utf-8")

    session.on_sketch_changed()

    # XML remains untouched
    assert xml_path.read_text(encoding="utf-8") == xml_before
    assert session.last_error is not None
    # Error message contains line number and sketch path
    assert any(f"{session.sketch_path}:{session.last_error.line}:" in m for m in messages)


def test_own_xml_writes_are_ignored(demo_course: tuple[Path, Path, CourseConfig]) -> None:
    """Writes made by on_sketch_changed are not treated as external changes by on_xml_changed."""
    course_dir, xml_path, cfg = demo_course

    messages: list[str] = []
    session = EditSession(xml_path=xml_path, config=cfg, course_root=course_dir, out=messages.append)
    session.start()

    sketch_content = session.sketch_path.read_text(encoding="utf-8")
    session.sketch_path.write_text(sketch_content.replace("name = \"Indefinite", "name = \"MyOwnWrite"))

    session.on_sketch_changed()
    assert "MyOwnWrite" in xml_path.read_text(encoding="utf-8")

    # on_xml_changed called right after our own write
    messages.clear()
    session.on_xml_changed()
    # No warning about external change
    assert not any("changed externally" in m for m in messages)


def test_leftover_resume_discard_abort(demo_course: tuple[Path, Path, CourseConfig]) -> None:
    """Test leftover sketch handling on start: resume, discard, and abort."""
    course_dir, xml_path, cfg = demo_course

    # Create an initial session
    s1 = EditSession(xml_path=xml_path, config=cfg, course_root=course_dir)
    s1.start()
    sketch_text = s1.sketch_path.read_text(encoding="utf-8")

    # Simulate dirty leftover sketch
    leftover_text = sketch_text.replace("name = \"Indefinite", "name = \"ResumeName")
    s1.sketch_path.write_text(leftover_text, encoding="utf-8")

    # 1. Resume
    s_resume = EditSession(
        xml_path=xml_path, config=cfg, course_root=course_dir, prompt=lambda _: "resume"
    )
    s_resume.start()
    assert "ResumeName" in xml_path.read_text(encoding="utf-8")
    assert s_resume.synced_sketch_text == leftover_text

    # Modify leftover again
    discard_text = leftover_text.replace("name = \"ResumeName", "name = \"DiscardCandidate")
    s_resume.sketch_path.write_text(discard_text, encoding="utf-8")

    # 2. Discard
    s_discard = EditSession(
        xml_path=xml_path, config=cfg, course_root=course_dir, prompt=lambda _: "discard"
    )
    s_discard.start()
    # Overwritten with fresh sketch from XML (which currently has ResumeName)
    current_sketch = s_discard.sketch_path.read_text(encoding="utf-8")
    assert "DiscardCandidate" not in current_sketch
    assert "ResumeName" in current_sketch

    # Modify leftover again
    s_discard.sketch_path.write_text(discard_text, encoding="utf-8")

    # 3. Abort
    s_abort = EditSession(
        xml_path=xml_path, config=cfg, course_root=course_dir, prompt=lambda _: "abort"
    )
    with pytest.raises(RuntimeError, match="aborted"):
        s_abort.start()


def test_run_integration_thread(demo_course: tuple[Path, Path, CourseConfig]) -> None:
    """Run EditSession.run() in a thread without editor, edit sketch, and verify sync & cleanup."""
    course_dir, xml_path, cfg = demo_course

    session = EditSession(
        xml_path=xml_path,
        config=cfg,
        course_root=course_dir,
        open_editor=False,
    )
    stop_event = threading.Event()
    worker = threading.Thread(target=session.run, kwargs={"stop_event": stop_event})
    worker.start()

    # Wait until sketch is created
    deadline = time.time() + 3.0
    while time.time() < deadline and not session.sketch_path.exists():
        time.sleep(0.05)
    assert session.sketch_path.exists()

    # Edit sketch file on disk
    sketch_content = session.sketch_path.read_text(encoding="utf-8")
    new_sketch = sketch_content.replace(
        'name = "Indefinite Integral of a Polynomial"',
        'name = "Thread Integration Title"',
    )
    session.sketch_path.write_text(new_sketch, encoding="utf-8")

    # Poll XML until watchfiles detects change and syncs
    deadline = time.time() + 5.0
    synced = False
    while time.time() < deadline:
        if "Thread Integration Title" in xml_path.read_text(encoding="utf-8"):
            synced = True
            break
        time.sleep(0.1)

    assert synced, "XML file did not update with thread-saved sketch changes"

    # Stop session
    stop_event.set()
    worker.join(timeout=3.0)
    assert not worker.is_alive()

    # Clean exit deletes sketch file and empty edit directories
    assert not session.sketch_path.exists()


def test_cli_sketch_and_apply(demo_course: tuple[Path, Path, CourseConfig], tmp_path: Path) -> None:
    """Test macstack sketch and macstack apply CLI commands."""
    course_dir, xml_path, _ = demo_course
    runner = CliRunner()

    # 1. macstack sketch to stdout
    res = runner.invoke(app, ["sketch", str(xml_path)])
    assert res.exit_code == 0
    assert 'name = "Indefinite Integral of a Polynomial"' in res.stdout

    # 2. macstack sketch to file
    out_file = tmp_path / "exported.stack.md"
    res_file = runner.invoke(app, ["sketch", str(xml_path), "-o", str(out_file)])
    assert res_file.exit_code == 0
    assert out_file.exists()
    assert 'name = "Indefinite Integral of a Polynomial"' in out_file.read_text(encoding="utf-8")
    assert res.stdout == out_file.read_text(encoding="utf-8")

    # 3. macstack apply to XML
    sketch_text = out_file.read_text(encoding="utf-8")
    modified_sketch = sketch_text.replace(
        'name = "Indefinite Integral of a Polynomial"',
        'name = "Applied CLI Title"',
    )
    out_file.write_text(modified_sketch, encoding="utf-8")

    res = runner.invoke(app, ["apply", str(out_file), str(xml_path)])
    assert res.exit_code == 0
    assert "Applied" in res.stdout
    assert "Applied CLI Title" in xml_path.read_text(encoding="utf-8")

    # 4. macstack apply on invalid sketch fails with exit code 1 and error message on stderr
    invalid_file = tmp_path / "broken.stack.md"
    invalid_file.write_text(
        modified_sketch.replace("Int(ans1, ta1, x)", "InvalidTestBad(ans1, ta1, x)"),
        encoding="utf-8",
    )
    res_err = runner.invoke(app, ["apply", str(invalid_file), str(xml_path)])
    assert res_err.exit_code == 1
    assert "InvalidTestBad" in res_err.stderr or "InvalidTestBad" in res_err.output


def test_resolve_editor_cmd_precedence(monkeypatch: pytest.MonkeyPatch, demo_course: tuple[Path, Path, CourseConfig]) -> None:
    """Editor resolution order: editor_cmd arg > config.edit['editor'] > $VISUAL > $EDITOR."""
    course_dir, xml_path, cfg = demo_course

    # 1. editor_cmd arg wins
    cfg_with_edit = CourseConfig(edit={"editor": "config-editor"})
    monkeypatch.setenv("VISUAL", "visual-editor")
    monkeypatch.setenv("EDITOR", "editor-env")
    s1 = EditSession(xml_path, cfg_with_edit, course_dir, editor_cmd="arg-editor")
    assert s1.resolve_editor_cmd() == "arg-editor"

    # 2. config.edit['editor'] wins over env vars
    s2 = EditSession(xml_path, cfg_with_edit, course_dir)
    assert s2.resolve_editor_cmd() == "config-editor"

    # 3. $VISUAL wins over $EDITOR
    s3 = EditSession(xml_path, CourseConfig(), course_dir)
    assert s3.resolve_editor_cmd() == "visual-editor"

    # 4. $EDITOR fallback
    monkeypatch.delenv("VISUAL")
    s4 = EditSession(xml_path, CourseConfig(), course_dir)
    assert s4.resolve_editor_cmd() == "editor-env"

    # 5. None when no editor specified
    monkeypatch.delenv("EDITOR")
    s5 = EditSession(xml_path, CourseConfig(), course_dir)
    assert s5.resolve_editor_cmd() is None


def test_exit_with_error_keeps_sketch_file(demo_course: tuple[Path, Path, CourseConfig]) -> None:
    """When session exits after a parse failure, the sketch file is kept and its path reported."""
    course_dir, xml_path, cfg = demo_course

    out_msgs: list[str] = []
    session = EditSession(
        xml_path=xml_path,
        config=cfg,
        course_root=course_dir,
        open_editor=False,
        out=out_msgs.append,
        prompt=lambda _: "resume",
    )
    stop_event = threading.Event()

    # Pre-break the sketch before exit
    session.start()
    sketch_content = session.sketch_path.read_text(encoding="utf-8")
    session.sketch_path.write_text(
        sketch_content.replace("Int(ans1, ta1, x)", "BadAnswerTest(ans1, ta1, x)"),
        encoding="utf-8",
    )
    session.on_sketch_changed()
    assert session.last_error is not None

    # Run session in thread and stop immediately
    t = threading.Thread(target=session.run, kwargs={"stop_event": stop_event})
    t.start()
    stop_event.set()
    t.join(timeout=3.0)

    # Sketch file must still exist because last parse failed
    assert session.sketch_path.exists()
    assert any(str(session.sketch_path) in m for m in out_msgs)


def test_cli_edit_scaffolds_new_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """macstack edit scaffolds new question XML if target does not exist."""
    runner = CliRunner()
    new_xml = tmp_path / "questions" / "new-calc" / "my-question.xml"
    assert not new_xml.exists()

    monkeypatch.setattr(EditSession, "run", lambda self: None)
    res = runner.invoke(app, ["edit", str(new_xml), "--no-open", "--name", "My Scaffolding"])
    assert res.exit_code == 0
    assert new_xml.exists()
    assert "<question" in new_xml.read_text(encoding="utf-8")
    assert "My Scaffolding" in new_xml.read_text(encoding="utf-8")


def test_blocking_editor_buffers_output(demo_course: tuple[Path, Path, CourseConfig]) -> None:
    """Status messages are buffered while a blocking editor is active, and flushed on exit."""
    course_dir, xml_path, cfg = demo_course

    out_msgs: list[str] = []
    session = EditSession(xml_path, cfg, course_dir, out=out_msgs.append)
    session._buffer_output = True

    session.report("message 1")
    session.report("message 2")
    assert out_msgs == []
    assert session._output_buffer == ["message 1", "message 2"]

    # When buffer turns off and flushes:
    session._buffer_output = False
    for msg in session._output_buffer:
        session.out(msg)
    session._output_buffer.clear()

    assert out_msgs == ["message 1", "message 2"]


