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


class StackEngine:
    """Client for rendering, validating, grading, and inspecting STACK questions."""

    def __init__(self, base_url: str | None = None, runtime_dir: Path | None = None):
        self.runtime_dir = runtime_dir or RUNTIME_DIR
        self.base_url = (base_url or ensure_php_server()).rstrip("/")
        self.client = httpx.Client(timeout=120.0)

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
        resp = self.client.post(f"{self.base_url}/render", json=payload)
        resp.raise_for_status()
        data = resp.json()
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
        resp = self.client.post(f"{self.base_url}/validate", json=payload)
        resp.raise_for_status()
        return resp.json()

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
        resp = self.client.post(f"{self.base_url}/grade", json=payload)
        resp.raise_for_status()
        return resp.json()

    def run_tests(self, question_xml: str) -> dict[str, Any]:
        """Execute all authored unit tests (<qtest>) within the question definition."""
        payload = {"questionDefinition": question_xml}
        resp = self.client.post(f"{self.base_url}/test", json=payload)
        resp.raise_for_status()
        return resp.json()

    def inspect_vars(self, question_xml: str, seed: int | None = None) -> dict[str, Any]:
        """Inspect all defined question variables, values, and teacher answers for a given seed."""
        payload = {
            "questionDefinition": question_xml,
            "seed": seed,
        }
        resp = self.client.post(f"{self.base_url}/macstack/vars", json=payload)
        resp.raise_for_status()
        return resp.json()

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
        resp = self.client.post(f"{self.base_url}/macstack/seeds", json=payload)
        resp.raise_for_status()
        return resp.json()

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
