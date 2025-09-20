from pathlib import Path
from typing import Dict

import pytest

from stackbench.agents.anthropic_cli import AnthropicCLIAgent
from stackbench.core.run_context import RunContext
from stackbench.extractors.models import UseCase


def make_use_case() -> UseCase:
    return UseCase(
        name="Claude Feature",
        elevator_pitch="Implement feature using Claude.",
        target_audience="Developers",
        functional_requirements=["Produce code"],
        user_stories=["As a dev I see generated code"],
        system_design="Rely on docs.",
        architecture_pattern="MVC",
        complexity_level="Intermediate",
        source_document=["docs/claude.md"],
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
        agent_type="anthropic-cli",
        base_data_dir=tmp_path,
    )
    context.create_directories()
    context.repo_dir.mkdir(parents=True, exist_ok=True)
    context.status.initialize_use_cases([make_use_case()])
    context.save()
    return context


def test_anthropic_cli_execute(monkeypatch, run_context: RunContext):
    agent = AnthropicCLIAgent()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    payload = {
        "content": [{"type": "text", "text": "print('claude')"}],
        "usage": {"output_tokens": 24},
    }

    monkeypatch.setattr(
        "stackbench.agents.anthropic_cli.request_with_retry",
        lambda *args, **kwargs: DummyResponse(payload),
    )

    agent.prepare_environment(run_context)
    use_case = make_use_case()
    target_dir = run_context.data_dir / "use_case_1"
    response = agent.execute(run_context, use_case, target_dir)

    artifacts = agent.collect_artifacts(run_context, use_case, target_dir, response)
    generated = artifacts["generated_file"].read_text(encoding="utf-8").strip()

    assert generated == "print('claude')"
    assert response.content.strip() == "print('claude')"
    log_path = run_context.data_dir / "agent_logs" / "anthropic-cli.jsonl"
    assert log_path.exists()
