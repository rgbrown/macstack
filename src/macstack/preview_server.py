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
from macstack.cas_errors import CasDiagnostic, parse_and_enrich_cas_errors
from macstack.engine import StackEngine, StackEngineError
from macstack.linter import lint_question
from macstack.xml_codec import (
    extract_hints,
    extract_question_fields,
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
            rel = xml_file.relative_to(root_dir)
            if any(part.startswith(".") for part in rel.parts):
                continue
        except ValueError:
            pass
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
        fields = extract_question_fields(xml_str)
        raw_qtext = fields.get("questiontext", "")

        try:
            api_xml, effective_seed, had_deployed_seeds = prepare_for_api(
                xml_str,
                seed_override=seed_override,
            )
            summary = parse_question_summary(file_path)
        except Exception as xml_exc:
            relpath = str(file_path.name)
            try:
                relpath = str(file_path.relative_to(root_dir))
            except ValueError:
                pass
            return JSONResponse({
                "summary": {
                    "path": str(file_path),
                    "relpath": relpath,
                    "name": file_path.stem,
                    "idnumber": file_path.stem,
                    "category_path": "",
                    "category_idnumber": "",
                    "inputs": [],
                    "input_types": {},
                    "prts": [],
                    "deployed_seeds": [],
                    "qtest_count": 0,
                    "uses_random": False,
                    "has_plot": False,
                    "hints_count": 0,
                },
                "effective_seed": seed_override or 1,
                "had_deployed_seeds": False,
                "render": {},
                "render_failed": True,
                "raw_questiontext": raw_qtext,
                "cas_errors": [
                    CasDiagnostic(
                        field="xml",
                        label="Question XML",
                        message=str(xml_exc),
                        seed=seed_override or 1,
                    ).to_dict()
                ],
                "hints": [],
                "vars": {"variables": [], "errors": ""},
                "lint": [i.to_dict() for i in lint_question(file_path)],
            })

        render_failed = False
        render_err_msg = ""
        render_res: dict[str, Any] = {}
        try:
            render_res = stack_engine.render(api_xml, seed=effective_seed, render_inputs="ans_")
        except StackEngineError as render_exc:
            render_failed = True
            render_res = {}
            render_err_msg = render_exc.message

        try:
            vars_res = stack_engine.inspect_vars(api_xml, seed=effective_seed)
        except StackEngineError as vars_exc:
            vars_res = {
                "seed": effective_seed,
                "questionnote": "",
                "variables": [],
                "inputs": {},
                "errors": vars_exc.message,
                "probed_errors": [],
            }

        raw_errs = [e for e in [render_err_msg, vars_res.get("errors", "")] if e]
        probed_errors = vars_res.get("probed_errors") or []
        cas_diagnostics: list[CasDiagnostic] = []
        if render_failed or raw_errs or probed_errors:
            cas_diagnostics = parse_and_enrich_cas_errors(
                raw_errs,
                xml_str=xml_str,
                probed_errors=probed_errors,
                seed=effective_seed,
            )

        lint_issues = lint_question(file_path)
        hints = extract_hints(xml_str)

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
            "render_failed": render_failed,
            "raw_questiontext": raw_qtext,
            "cas_errors": [d.to_dict() for d in cas_diagnostics],
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

        try:
            res = stack_engine.validate(
                api_xml,
                input_name=input_name,
                answers=answers,
                seed=effective_seed,
            )
            validation_html = res.get("Validation", res.get("validation", ""))
            return JSONResponse({"validation": validation_html, **res})
        except StackEngineError as exc:
            diags = parse_and_enrich_cas_errors(exc.message, xml_str=xml_str, seed=effective_seed)
            return JSONResponse({
                "validation": "",
                "error": exc.message,
                "cas_errors": [d.to_dict() for d in diags],
            })

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

        try:
            res = stack_engine.grade(api_xml, answers=answers, seed=effective_seed)
        except StackEngineError as exc:
            diags = parse_and_enrich_cas_errors(exc.message, xml_str=xml_str, seed=effective_seed)
            return JSONResponse({
                "isgradable": False,
                "has_prt_errors": False,
                "has_cas_error": True,
                "error": exc.message,
                "cas_errors": [d.to_dict() for d in diags],
            })

        cas_diags: list[CasDiagnostic] = []
        if res.get("has_cas_error"):
            diags = parse_and_enrich_cas_errors(
                res.get("error", ""),
                xml_str=xml_str,
                probed_errors=res.get("probed_errors"),
                seed=effective_seed,
            )
            cas_diags.extend(diags)

        if res.get("has_prt_errors") or res.get("prtresults"):
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

        if cas_diags or "cas_errors" not in res:
            res["cas_errors"] = [d.to_dict() for d in cas_diags]

        return JSONResponse(res)

    async def api_test(request: Request) -> JSONResponse:
        body = await request.json()
        path_val = body.get("path")
        if not path_val:
            return JSONResponse({"error": "Missing 'path'"}, status_code=400)

        file_path = resolve_question_path(root_dir, path_val)
        xml_str = file_path.read_text(encoding="utf-8")
        api_xml, _, _ = prepare_for_api(xml_str)

        try:
            res = stack_engine.run_tests(api_xml)
            cas_diags: list[CasDiagnostic] = []
            results = res.get("results") or {}
            probed = None
            for s_key, s_data in results.items():
                if isinstance(s_data, dict):
                    msg = s_data.get("messages", "")
                    if "error" in msg.lower() or "must validate true before compiling" in msg:
                        if "must validate true before compiling" in msg and probed is None:
                            try:
                                v = stack_engine.inspect_vars(api_xml)
                                probed = v.get("probed_errors")
                            except Exception:
                                pass
                        cas_diags.extend(parse_and_enrich_cas_errors(
                            msg,
                            xml_str=xml_str,
                            probed_errors=probed,
                        ))
            if cas_diags:
                res["cas_errors"] = [d.to_dict() for d in cas_diags]
            return JSONResponse(res)
        except StackEngineError as exc:
            probed = None
            if "must validate true before compiling" in exc.message:
                try:
                    v = stack_engine.inspect_vars(api_xml)
                    probed = v.get("probed_errors")
                except Exception:
                    pass
            diags = parse_and_enrich_cas_errors(
                exc.message,
                xml_str=xml_str,
                probed_errors=probed,
            )
            return JSONResponse({
                "error": exc.message,
                "cas_errors": [d.to_dict() for d in diags],
                "results": {},
            })

    async def api_deploy_seeds(request: Request) -> JSONResponse:
        body = await request.json()
        path_val = body.get("path")
        if not path_val:
            return JSONResponse({"error": "Missing 'path'"}, status_code=400)

        file_path = resolve_question_path(root_dir, path_val)
        count = int(body.get("count", 50))

        xml_str = file_path.read_text(encoding="utf-8")
        api_xml, _, _ = prepare_for_api(xml_str)

        try:
            res = stack_engine.deploy_seeds(api_xml, count=count)
        except StackEngineError as exc:
            diags = parse_and_enrich_cas_errors(exc.message, xml_str=xml_str)
            return JSONResponse({
                "seeds": [],
                "count": 0,
                "variants": [],
                "error": exc.message,
                "cas_errors": [d.to_dict() for d in diags],
            })

        seeds = res.get("seeds", [])
        if seeds:
            set_deployed_seeds(file_path, seeds)
            return JSONResponse({
                "seeds": seeds,
                "count": len(seeds),
                "variants": res.get("variants", []),
            })
        else:
            diags = parse_and_enrich_cas_errors(
                res.get("first_error", ""),
                xml_str=xml_str,
                probed_errors=res.get("probed_errors"),
                seed=1,
            )
            first_err_msg = diags[0].message if diags else (res.get("first_error") or "No valid error-free seeds could be generated.")
            return JSONResponse({
                "seeds": [],
                "count": 0,
                "variants": [],
                "error": first_err_msg,
                "cas_errors": [d.to_dict() for d in diags],
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
