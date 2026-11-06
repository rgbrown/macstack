"""STACK Engine client for interacting with the local PHP bridge."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Any

import httpx

from macstack.runtime import RUNTIME_DIR, ensure_php_server


def _ensure_deployed_seed_in_xml(question_xml: str, seed: int | None) -> str:
    """Ensure that question XML has the requested seed (or a default seed) in <deployedseed>

    so that upstream STACK validation does not throw api_seed_not_in_variants.
    """
    if seed is None:
        return question_xml

    pattern = rf"<deployedseed>\s*{seed}\s*</deployedseed>"
    if re.search(pattern, question_xml):
        return question_xml

    # Inject the seed inside <question> before </question>
    injection = f"  <deployedseed>{seed}</deployedseed>\n</question>"
    if "</question>" in question_xml:
        return question_xml.replace("</question>", injection, 1)

    return question_xml


class StackEngineError(RuntimeError):
    """Raised when the STACK PHP/Maxima engine returns an application or CAS error."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload or {}


class StackEngine:
    """Client for rendering, validating, grading, and inspecting STACK questions."""

    def __init__(self, base_url: str | None = None, runtime_dir: Path | None = None):
        self.runtime_dir = runtime_dir or RUNTIME_DIR
        self.base_url = (base_url or ensure_php_server()).rstrip("/")
        self.client = httpx.Client(timeout=120.0)

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Execute an HTTP request to the local STACK engine and return parsed JSON.

        Translates network, timeout, and HTTP error responses into structured StackEngineErrors.
        """
        url = f"{self.base_url}{path}"
        try:
            resp = self.client.request(method, url, **kwargs)
        except httpx.TimeoutException:
            raise StackEngineError("Maxima CAS evaluation timed out.", status_code=504)
        except httpx.RequestError as exc:
            raise StackEngineError(f"Failed to reach local STACK engine: {exc}", status_code=502)

        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = {}

            if isinstance(body, dict):
                msg = body.get("message") or body.get("error") or body.get("errors") or resp.text.strip() or f"HTTP {resp.status_code}"
            else:
                msg = resp.text.strip() or f"HTTP {resp.status_code}"

            raise StackEngineError(
                str(msg),
                status_code=resp.status_code,
                payload=body if isinstance(body, dict) else {},
            )

        try:
            return resp.json()
        except Exception as exc:
            raise StackEngineError(f"Invalid JSON response from STACK engine: {exc}", status_code=500)

    def render(
        self,
        question_xml: str,
        seed: int | None = None,
        render_inputs: str = "ans_",
        full_render: bool = False,
    ) -> dict[str, Any]:
        """Render question text, inputs, sample solutions, and plot assets."""
        xml = _ensure_deployed_seed_in_xml(question_xml, seed)
        payload = {
            "questionDefinition": xml,
            "seed": seed,
            "renderInputs": render_inputs,
            "readOnly": False,
        }
        data = self._request_json("POST", "/render", json=payload)
        if "inputs" not in data and "questioninputs" in data:
            data["inputs"] = data["questioninputs"]
        return data

    def validate(
        self,
        question_xml: str,
        input_name: str,
        answers: dict[str, str],
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Validate a student answer for a specific input field."""
        xml = _ensure_deployed_seed_in_xml(question_xml, seed)
        payload = {
            "questionDefinition": xml,
            "inputName": input_name,
            "answers": answers,
            "seed": seed,
        }
        return self._request_json("POST", "/validate", json=payload)

    def grade(
        self,
        question_xml: str,
        answers: dict[str, str],
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Grade a set of student answers through the question's PRTs."""
        xml = _ensure_deployed_seed_in_xml(question_xml, seed)
        payload = {
            "questionDefinition": xml,
            "answers": answers,
            "seed": seed,
        }
        return self._request_json("POST", "/grade", json=payload)

    def run_tests(self, question_xml: str) -> dict[str, Any]:
        """Execute all authored unit tests (<qtest>) within the question definition."""
        payload = {"questionDefinition": question_xml}
        return self._request_json("POST", "/test", json=payload)

    def inspect_vars(self, question_xml: str, seed: int | None = None) -> dict[str, Any]:
        """Inspect all defined question variables, values, and teacher answers for a given seed."""
        payload = {
            "questionDefinition": question_xml,
            "seed": seed,
        }
        return self._request_json("POST", "/macstack/vars", json=payload)

    def deploy_seeds(
        self,
        question_xml: str,
        count: int = 50,
        max_attempts: int = 250,
        existing_seeds: list[int] | None = None,
    ) -> dict[str, Any]:
        """Deploy unique valid seeds deduplicated by rendered question note."""
        payload = {
            "questionDefinition": question_xml,
            "count": count,
            "max_attempts": max_attempts,
            "seeds": existing_seeds or [],
        }
        return self._request_json("POST", "/macstack/seeds", json=payload)

    def get_plot_bytes(self, filename: str) -> tuple[bytes, str]:
        """Retrieve the binary bytes and content type for a plot file."""
        clean_name = Path(filename).name
        local_file = self.runtime_dir / "stack" / "plots" / clean_name
        if local_file.exists() and local_file.is_file():
            content_type, _ = mimetypes.guess_type(str(local_file))
            if not content_type:
                content_type = "image/svg+xml" if clean_name.endswith(".svg") else "application/octet-stream"
            return local_file.read_bytes(), content_type

        resp = self.client.get(f"{self.base_url}/plots/{clean_name}")
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/svg+xml")
        return resp.content, content_type
