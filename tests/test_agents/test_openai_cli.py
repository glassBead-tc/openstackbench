from pathlib import Path
from typing import Dict

import pytest

from stackbench.agents.openai_cli import OpenAICLIAgent
from stackbench.core.run_context import RunContext
from stackbench.extractors.models import UseCase


def make_use_case() -> UseCase:
    return UseCase(
        name="Example Feature",
        elevator_pitch="Implement an example feature.",
        target_audience="Developers",
        functional_requirements=["Do something"],
        user_stories=["As a dev I can do something"],
        system_design="Use built-in modules.",
        architecture_pattern="Layered",
        complexity_level="Beginner",
        source_document=["docs/example.md"],
        real_world_scenario="Demo",
        target_file="solution.py",
    )


class DummyResponse:
    def __init__(self, payload: Dict[str, object]):
        self.status_code = 200
        self._payload = payload

    def json(self) -> Dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


@pytest.fixture
def run_context(tmp_path: Path) -> RunContext:
    context = RunContext.create(
        repo_url="https://example.com/repo.git",
        agent_type="openai-cli",
        base_data_dir=tmp_path,
    )
    context.create_directories()
    context.repo_dir.mkdir(parents=True, exist_ok=True)
    context.status.initialize_use_cases([make_use_case()])
    context.save()
    return context


def test_openai_cli_execute(monkeypatch, run_context: RunContext):
    agent = OpenAICLIAgent()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    payload = {
        "choices": [{"message": {"content": "print('hello')"}}],
        "usage": {"total_tokens": 42},
    }

    monkeypatch.setattr(
        "stackbench.agents.openai_cli.request_with_retry",
        lambda *args, **kwargs: DummyResponse(payload),
    )

    agent.prepare_environment(run_context)
    use_case = make_use_case()
    target_dir = run_context.data_dir / "use_case_1"
    response = agent.execute(run_context, use_case, target_dir)

    artifacts = agent.collect_artifacts(run_context, use_case, target_dir, response)

    generated = artifacts["generated_file"].read_text(encoding="utf-8").strip()
    assert generated == "print('hello')"
    assert "prompt" in artifacts and artifacts["prompt"].exists()
    assert response.content.strip() == "print('hello')"

    log_path = run_context.data_dir / "agent_logs" / "openai-cli.jsonl"
    assert log_path.exists()
