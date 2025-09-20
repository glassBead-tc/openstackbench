"""Automated agent that targets OpenAI compatible chat completion APIs."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List

from .base import Agent
from .utils import (
    AgentResponse,
    JSONLinesLogger,
    RetryConfig,
    request_with_retry,
    resolve_target_path,
)
from ..config import get_config
from ..core.run_context import RunContext
from ..extractors.models import UseCase


class OpenAICLIAgent(Agent):
    """Agent that issues chat completion requests to OpenAI compatible APIs."""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        config = get_config()
        self._model = model or config.openai_model
        self._base_url = (base_url or config.openai_api_base).rstrip("/")
        self._temperature = config.openai_temperature
        self._timeout = config.openai_request_timeout
        self._retry = RetryConfig(
            max_attempts=config.openai_max_retries,
            backoff_factor=0.5,
            status_forcelist=(408, 409, 429, 500, 502, 503, 504),
        )
        self._logger: JSONLinesLogger | None = None
        self._api_key: str | None = None
        self._last_artifacts: Dict[str, Path] = {}

    @property
    def agent_type(self) -> str:
        return "cli"

    @property
    def name(self) -> str:
        return "openai-cli"

    def prepare_environment(self, run_context: RunContext) -> None:
        self._api_key = os.getenv("OPENAI_API_KEY") or get_config().openai_api_key
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")

        log_path = run_context.data_dir / "agent_logs" / f"{self.name}.jsonl"
        self._logger = JSONLinesLogger(log_path)

        run_context.metadata.setdefault("agent", {})
        run_context.metadata["agent"].update(
            {
                "name": self.name,
                "model": self._model,
                "api_base": self._base_url,
            }
        )
        run_context.save()

    def format_prompt(self, run_id: str, use_case_number: int) -> str:
        context = self.get_run_context(run_id)
        use_case = self.load_use_case(run_id, use_case_number)
        target_dir = self.get_target_directory(run_id, use_case_number)
        return self._render_prompt(context, use_case, target_dir)

    def execute(
        self,
        run_context: RunContext,
        use_case: UseCase,
        target_dir: Path,
    ) -> AgentResponse:
        if self._api_key is None:
            raise RuntimeError("prepare_environment must be called before execute")

        target_dir.mkdir(parents=True, exist_ok=True)
        prompt_text = self._render_prompt(run_context, use_case, target_dir)
        prompt_path = target_dir / "prompt.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")

        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "messages": self._build_messages(run_context, prompt_text),
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        start = time.time()
        response = request_with_retry(
            "POST",
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=self._timeout,
            retry=self._retry,
        )
        latency = time.time() - start
        response.raise_for_status()
        data = response.json()

        completion_text = self._extract_completion_text(data)

        completion_path = resolve_target_path(target_dir, use_case.target_file)
        completion_path.parent.mkdir(parents=True, exist_ok=True)
        completion_path.write_text(completion_text.strip() + "\n", encoding="utf-8")

        response_path = target_dir / "completion.json"
        response_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        if self._logger:
            self._logger.log(
                {
                    "timestamp": time.time(),
                    "event": "completion",
                    "request": {"model": payload["model"], "temperature": payload["temperature"]},
                    "usage": data.get("usage", {}),
                    "latency_seconds": latency,
                }
            )

        self._last_artifacts = {
            "prompt": prompt_path,
            "response_json": response_path,
            "generated_file": completion_path,
        }

        return AgentResponse(
            content=completion_text,
            raw=data,
            usage=data.get("usage", {}),
            latency_seconds=latency,
            metadata={"model": data.get("model", self._model)},
        )

    def collect_artifacts(
        self,
        run_context: RunContext,
        use_case: UseCase,
        target_dir: Path,
        response: AgentResponse | None = None,
    ) -> Dict[str, Path]:
        return dict(self._last_artifacts)

    def _render_prompt(
        self, run_context: RunContext, use_case: UseCase, target_dir: Path
    ) -> str:
        resolved_output = resolve_target_path(target_dir, use_case.target_file)

        try:
            relative_target_file = resolved_output.relative_to(target_dir.resolve())
        except ValueError:
            relative_target_file = Path(use_case.target_file)

        lines: List[str] = [
            f"# {use_case.name}",
            "",
            "## Objective",
            use_case.elevator_pitch,
            "",
            "## Target Environment",
            f"- Repository documentation root: {run_context.repo_dir}",
            f"- Working directory for this solution: {target_dir}",
            f"- Output file: {resolved_output}",
            "",
            "## Functional Requirements",
        ]

        for idx, req in enumerate(use_case.functional_requirements, 1):
            lines.append(f"{idx}. {req}")

        lines.extend(["", "## User Stories"])
        for idx, story in enumerate(use_case.user_stories, 1):
            lines.append(f"{idx}. {story}")

        lines.extend(
            [
                "",
                "## System Design",
                use_case.system_design,
                "",
                "## Architecture Pattern",
                use_case.architecture_pattern,
                "",
                "## Additional Guidance",
                "- Base your answer strictly on the repository documentation.",
                "- Produce only the code that should go into the target file.",
                "- Include necessary imports and helper functions inline.",
            ]
        )

        prompt = "\n".join(lines)
        prompt += "\n"
        prompt += f"\nEnsure the generated file is saved as {relative_target_file}."
        return prompt

    def _build_messages(self, run_context: RunContext, prompt_text: str) -> List[Dict[str, str]]:
        system_prompt = (
            "You are an autonomous software engineer generating complete, executable "
            "solutions that align with repository documentation. Respond with the "
            "final code for the requested file only."
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_text},
        ]

    def _extract_completion_text(self, data: Dict[str, object]) -> str:
        choices = data.get("choices", [])
        if not choices:
            return ""
        first = choices[0] or {}
        message = first.get("message", {})
        return str(message.get("content", ""))
