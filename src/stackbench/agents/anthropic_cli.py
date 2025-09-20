"""Automated agent for the Anthropic Claude Messages API."""

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


class AnthropicCLIAgent(Agent):
    """Agent that talks to Anthropic's Claude Messages API."""

    def __init__(self, model: str | None = None) -> None:
        config = get_config()
        self._model = model or config.anthropic_model
        self._api_url = config.anthropic_api_url
        self._api_version = config.anthropic_api_version
        self._temperature = config.anthropic_temperature
        self._max_tokens = config.anthropic_max_tokens
        self._timeout = config.anthropic_request_timeout
        self._retry = RetryConfig(
            max_attempts=config.anthropic_max_retries,
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
        return "anthropic-cli"

    def prepare_environment(self, run_context: RunContext) -> None:
        self._api_key = os.getenv("ANTHROPIC_API_KEY") or get_config().anthropic_api_key
        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")

        log_path = run_context.data_dir / "agent_logs" / f"{self.name}.jsonl"
        self._logger = JSONLinesLogger(log_path)

        run_context.metadata.setdefault("agent", {})
        run_context.metadata["agent"].update(
            {
                "name": self.name,
                "model": self._model,
                "api_url": self._api_url,
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
            "max_tokens": self._max_tokens,
            "system": self._build_system_prompt(run_context),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt_text,
                        }
                    ],
                }
            ],
        }

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self._api_version,
            "content-type": "application/json",
        }

        start = time.time()
        response = request_with_retry(
            "POST",
            self._api_url,
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
                    "request": {"model": self._model, "temperature": self._temperature},
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
            metadata={"model": self._model},
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
                "## Safety & Output Requirements",
                "- Follow the repository's documented practices and avoid speculative APIs.",
                "- Respond with executable code for the target file only.",
                "- Omit explanations unless necessary for code clarity as comments.",
            ]
        )

        prompt = "\n".join(lines)
        prompt += "\n"
        prompt += f"\nEnsure the generated file is saved as {relative_target_file}."
        return prompt

    def _build_system_prompt(self, run_context: RunContext) -> str:
        return (
            "You are an autonomous software engineer responsible for implementing "
            "complete solutions that adhere to documented requirements. Use the "
            f"repository documentation located at {run_context.repo_dir} as the source "
            "of truth and produce the final code for the requested file."
        )

    def _extract_completion_text(self, data: Dict[str, object]) -> str:
        content = data.get("content", [])
        if not content:
            return ""
        first = content[0] or {}
        if isinstance(first, dict):
            return str(first.get("text", ""))
        return str(first)
