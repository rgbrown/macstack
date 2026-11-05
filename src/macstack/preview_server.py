"""Live-reload preview server and workbench for STACK questions."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import logging
from pathlib import Path
import threading
from typing import Any
import webbrowser

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
import uvicorn
import watchfiles

from macstack.config import find_course_config
from macstack.engine import StackEngine
from macstack.linter import lint_question
from macstack.xml_codec import (
    extract_hints,
    parse_question_summary,
    prepare_for_api,
    set_deployed_seeds,
)

logger = logging.getLogger("macstack.preview")
WEB_DIR = Path(__file__).parent / "web"


def resolve_question_path(root_dir: Path, rel_or_abs: str) -> Path:
    """Resolve a relative or absolute question path securely against root_dir."""
    p = Path(rel_or_abs)
    if p.is_absolute():
        return p.resolve()
    return (root_dir / p).resolve()


def discover_stack_questions(root_dir: Path) -> list[dict[str, Any]]:
    """Scan root_dir recursively for STACK XML files and extract summary info."""
    questions: list[dict[str, Any]] = []

    for xml_file in sorted(root_dir.glob("**/*.xml")):
        if not xml_file.is_file():
            continue
        try:
            content = xml_file.read_text(encoding="utf-8", errors="ignore")
            if "<question" not in content or 'type="stack"' not in content:
                continue

            summary = parse_question_summary(xml_file)
            issues = lint_question(xml_file)

            # Determine leaf category
            if summary.category_path:
                category = summary.category_path.split("/")[-1].strip()
            elif xml_file.parent != root_dir:
                category = xml_file.parent.name
            else:
                category = "General"

            questions.append({
                "relpath": str(xml_file.relative_to(root_dir)),
                "name": summary.name or xml_file.stem,
                "idnumber": summary.idnumber or xml_file.stem,
                "category": category or "General",
                "deployed_seeds_count": len(summary.deployed_seeds),
                "qtest_count": summary.qtest_count,
                "error_count": sum(1 for i in issues if i.severity == "error"),
                "warning_count": sum(1 for i in issues if i.severity == "warning"),
            })
        except Exception as e:
            logger.warning("Failed to parse question XML %s: %s", xml_file, e)

    questions.sort(key=lambda q: (q["category"], q["relpath"]))
    return questions


def create_app(
    workspace_or_file: Path,
    engine: StackEngine | None = None,
) -> Starlette:
    """Create and configure the Starlette preview workbench application."""
    target = workspace_or_file.resolve()

    if target.is_file():
        # Attempt to find course config root, otherwise use parent directory
        _, toml_path = find_course_config(target)
        root_dir = toml_path.parent.resolve() if toml_path else target.parent.resolve()
        try:
            active_relpath: str | None = str(target.relative_to(root_dir))
        except ValueError:
            root_dir = target.parent.resolve()
            active_relpath = target.name
    else:
        root_dir = target
        active_relpath = None

    stack_engine = engine or StackEngine()

    # Route Handlers
    async def handle_index(request: Request) -> Response:
        index_file = WEB_DIR / "index.html"
        return Response(content=index_file.read_bytes(), media_type="text/html")

    async def handle_styles(request: Request) -> Response:
        css_file = WEB_DIR / "styles.css"
        return Response(content=css_file.read_bytes(), media_type="text/css")

    async def handle_app_js(request: Request) -> Response:
        js_file = WEB_DIR / "app.js"
        return Response(content=js_file.read_bytes(), media_type="application/javascript")

    async def api_questions(request: Request) -> JSONResponse:
        q_list = discover_stack_questions(root_dir)
        effective_active = active_relpath
        if not effective_active or not any(q["relpath"] == effective_active for q in q_list):
            effective_active = q_list[0]["relpath"] if q_list else None

        return JSONResponse({
            "root": str(root_dir),
            "active": effective_active,
            "questions": q_list,
        })

    async def api_question(request: Request) -> Response:
        path_param = request.query_params.get("path")
        if not path_param:
            return JSONResponse({"error": "Missing 'path' query parameter"}, status_code=400)

        file_path = resolve_question_path(root_dir, path_param)
        if not file_path.exists():
            return JSONResponse({"error": f"Question file not found: {path_param}"}, status_code=404)

        seed_param = request.query_params.get("seed")
        seed_override: int | None = None
        if seed_param is not None and seed_param != "":
            try:
                seed_override = int(seed_param)
            except ValueError:
                seed_override = None

        xml_str = file_path.read_text(encoding="utf-8")
        api_xml, effective_seed, had_deployed_seeds = prepare_for_api(
            xml_str,
            seed_override=seed_override,
        )

        render_res = stack_engine.render(api_xml, seed=effective_seed, render_inputs="ans_")
        vars_res = stack_engine.inspect_vars(api_xml, seed=effective_seed)
        lint_issues = lint_question(file_path)
        hints = extract_hints(xml_str)
        summary = parse_question_summary(file_path)

        summary_dict = asdict(summary)
        summary_dict["path"] = str(file_path)
        try:
            summary_dict["relpath"] = str(file_path.relative_to(root_dir))
        except ValueError:
            summary_dict["relpath"] = file_path.name

        return JSONResponse({
            "summary": summary_dict,
            "effective_seed": effective_seed,
            "had_deployed_seeds": had_deployed_seeds,
            "render": render_res,
            "hints": hints,
            "vars": vars_res,
            "lint": [i.to_dict() for i in lint_issues],
        })

    async def api_validate(request: Request) -> JSONResponse:
        body = await request.json()
        path_val = body.get("path")
        if not path_val:
            return JSONResponse({"error": "Missing 'path'"}, status_code=400)

        file_path = resolve_question_path(root_dir, path_val)
        seed = body.get("seed")
        input_name = body.get("inputName", "")
        answers = body.get("answers", {})

        xml_str = file_path.read_text(encoding="utf-8")
        api_xml, effective_seed, _ = prepare_for_api(xml_str, seed_override=seed)

        res = stack_engine.validate(
            api_xml,
            input_name=input_name,
            answers=answers,
            seed=effective_seed,
        )

        validation_html = res.get("Validation", res.get("validation", ""))
        return JSONResponse({"validation": validation_html, **res})

    async def api_grade(request: Request) -> JSONResponse:
        body = await request.json()
        path_val = body.get("path")
        if not path_val:
            return JSONResponse({"error": "Missing 'path'"}, status_code=400)

        file_path = resolve_question_path(root_dir, path_val)
        seed = body.get("seed")
        answers = body.get("answers", {})

        xml_str = file_path.read_text(encoding="utf-8")
        api_xml, effective_seed, _ = prepare_for_api(xml_str, seed_override=seed)

        res = stack_engine.grade(api_xml, answers=answers, seed=effective_seed)
        return JSONResponse(res)

    async def api_test(request: Request) -> JSONResponse:
        body = await request.json()
        path_val = body.get("path")
        if not path_val:
            return JSONResponse({"error": "Missing 'path'"}, status_code=400)

        file_path = resolve_question_path(root_dir, path_val)
        xml_str = file_path.read_text(encoding="utf-8")
        api_xml, _, _ = prepare_for_api(xml_str)

        res = stack_engine.run_tests(api_xml)
        return JSONResponse(res)

    async def api_deploy_seeds(request: Request) -> JSONResponse:
        body = await request.json()
        path_val = body.get("path")
        if not path_val:
            return JSONResponse({"error": "Missing 'path'"}, status_code=400)

        file_path = resolve_question_path(root_dir, path_val)
        count = int(body.get("count", 50))

        xml_str = file_path.read_text(encoding="utf-8")
        api_xml, _, _ = prepare_for_api(xml_str)

        res = stack_engine.deploy_seeds(api_xml, count=count)
        seeds = res.get("seeds", [])
        if seeds:
            set_deployed_seeds(file_path, seeds)

        return JSONResponse({
            "seeds": seeds,
            "count": len(seeds),
            "variants": res.get("variants", []),
        })

    async def handle_plot(request: Request) -> Response:
        filename = request.path_params.get("filename", "")
        data, content_type = stack_engine.get_plot_bytes(filename)
        return Response(content=data, media_type=content_type)

    async def api_events(request: Request) -> StreamingResponse:
        async def event_generator():
            yield ": connected\n\n"
            watcher = watchfiles.awatch(root_dir)
            watcher_iter = watcher.__aiter__()
            while True:
                try:
                    changes = await asyncio.wait_for(watcher_iter.__anext__(), timeout=15.0)
                    relevant = [
                        str(p) for _, p in changes
                        if p.endswith((".xml", ".toml", ".css", ".js", ".html"))
                    ]
                    if relevant:
                        payload = json.dumps({"paths": relevant})
                        yield f"event: reload\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                except (asyncio.CancelledError, GeneratorExit, StopAsyncIteration):
                    break

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    routes = [
        Route("/", handle_index, methods=["GET"]),
        Route("/styles.css", handle_styles, methods=["GET"]),
        Route("/app.js", handle_app_js, methods=["GET"]),
        Route("/api/questions", api_questions, methods=["GET"]),
        Route("/api/question", api_question, methods=["GET"]),
        Route("/api/validate", api_validate, methods=["POST"]),
        Route("/api/grade", api_grade, methods=["POST"]),
        Route("/api/test", api_test, methods=["POST"]),
        Route("/api/deploy-seeds", api_deploy_seeds, methods=["POST"]),
        Route("/plots/{filename:path}", handle_plot, methods=["GET"]),
        Route("/api/events", api_events, methods=["GET"]),
    ]

    return Starlette(routes=routes)


def run_preview(
    workspace_or_file: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Run uvicorn development preview server."""
    app = create_app(workspace_or_file)

    if open_browser:
        url = f"http://{host}:{port}"
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="info")
