"""Automated agent that executes a local command to generate solutions."""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Dict, List

from .base import Agent
from .utils import AgentResponse, JSONLinesLogger, resolve_target_path
from ..config import get_config
from ..core.run_context import RunContext
from ..extractors.models import UseCase


class LocalExecAgent(Agent):
    """Agent that shells out to a configurable local command."""

    def __init__(self, command_template: str | None = None) -> None:
        config = get_config()
        self._command_template = command_template or config.local_agent_command_template
        self._model = config.local_agent_model
        self._timeout = config.local_agent_timeout
        self._shell = config.local_agent_shell
        self._logger: JSONLinesLogger | None = None
        self._last_artifacts: Dict[str, Path] = {}

    @property
    def agent_type(self) -> str:
        return "cli"

    @property
    def name(self) -> str:
        return "local-exec"

    def prepare_environment(self, run_context: RunContext) -> None:
        if not self._command_template:
            raise RuntimeError("local_agent_command_template not configured")

        log_path = run_context.data_dir / "agent_logs" / f"{self.name}.jsonl"
        self._logger = JSONLinesLogger(log_path)

        run_context.metadata.setdefault("agent", {})
        run_context.metadata["agent"].update(
            {
                "name": self.name,
                "model": self._model,
                "command_template": self._command_template,
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
        if not self._command_template:
            raise RuntimeError("prepare_environment must be called before execute")

        target_dir.mkdir(parents=True, exist_ok=True)
        prompt_text = self._render_prompt(run_context, use_case, target_dir)
        prompt_path = target_dir / "prompt.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")

        output_path = resolve_target_path(target_dir, use_case.target_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        command = self._command_template.format(
            prompt_file=str(prompt_path),
            output_file=str(output_path),
            model=self._model,
            target_dir=str(target_dir),
            repo_dir=str(run_context.repo_dir),
        )

        start = time.time()
        try:
            completed = subprocess.run(
                command if self._shell else shlex.split(command),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                cwd=run_context.repo_dir,
                shell=self._shell,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Local agent timed out after {self._timeout}s") from exc

        latency = time.time() - start

        stdout_path = target_dir / "stdout.txt"
        stderr_path = target_dir / "stderr.txt"
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")

        if not output_path.exists():
            output_path.write_text((completed.stdout or "").strip() + "\n", encoding="utf-8")

        metadata = {
            "returncode": completed.returncode,
            "command": command,
            "shell": self._shell,
            "latency_seconds": latency,
        }

        metadata_path = target_dir / "execution.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        self._last_artifacts = {
            "prompt": prompt_path,
            "generated_file": output_path,
            "stdout": stdout_path,
            "stderr": stderr_path,
            "metadata": metadata_path,
        }

        if self._logger:
            self._logger.log(
                {
                    "timestamp": time.time(),
                    "event": "execution",
                    "command": command,
                    "returncode": completed.returncode,
                    "latency_seconds": latency,
                }
            )

        if completed.returncode != 0:
            error_message = f"Local agent exited with status {completed.returncode}"
            if self._logger:
                self._logger.log(
                    {
                        "timestamp": time.time(),
                        "event": "error",
                        "command": command,
                        "returncode": completed.returncode,
                    }
                )
            raise RuntimeError(error_message)

        return AgentResponse(
            content=completed.stdout or "",
            raw=metadata,
            metadata={"returncode": completed.returncode},
            latency_seconds=latency,
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
                "## Execution Notes",
                "- Execute the instructions and produce the complete solution file.",
                "- Print the full source code to stdout if not writing directly to the output file.",
                "- Ensure the code is self-contained with imports and helper functions.",
            ]
        )

        prompt = "\n".join(lines)
        prompt += "\n"
        prompt += f"\nEnsure the generated file is saved as {relative_target_file}."
        return prompt
