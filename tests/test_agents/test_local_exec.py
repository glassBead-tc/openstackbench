from pathlib import Path

import pytest

from stackbench.agents.local_exec import LocalExecAgent
from stackbench.core.run_context import RunContext
from stackbench.extractors.models import UseCase


def make_use_case() -> UseCase:
    return UseCase(
        name="Local Feature",
        elevator_pitch="Implement feature using local command.",
        target_audience="Developers",
        functional_requirements=["Produce local code"],
        user_stories=["As a dev I run a local tool"],
        system_design="Leverage CLI tool.",
        architecture_pattern="Microservice",
        complexity_level="Intermediate",
        source_document=["docs/local.md"],
        real_world_scenario="Demo",
        target_file="solution.py",
    )


@pytest.fixture
def run_context(tmp_path: Path) -> RunContext:
    context = RunContext.create(
        repo_url="https://example.com/repo.git",
        agent_type="local-exec",
        base_data_dir=tmp_path,
    )
    context.create_directories()
    context.repo_dir.mkdir(parents=True, exist_ok=True)
    context.status.initialize_use_cases([make_use_case()])
    context.save()
    return context


def test_local_exec_execute(monkeypatch, run_context: RunContext):
    agent = LocalExecAgent(command_template="tool --prompt {prompt_file} --output {output_file}")

    class DummyCompletedProcess:
        def __init__(self):
            self.returncode = 0
            self.stdout = "print('local')"
            self.stderr = ""

    def fake_run(cmd, capture_output, text, timeout, cwd, shell):
        assert "--prompt" in cmd
        return DummyCompletedProcess()

    monkeypatch.setattr("subprocess.run", fake_run)

    agent.prepare_environment(run_context)
    use_case = make_use_case()
    target_dir = run_context.data_dir / "use_case_1"
    response = agent.execute(run_context, use_case, target_dir)

    artifacts = agent.collect_artifacts(run_context, use_case, target_dir, response)

    generated = artifacts["generated_file"].read_text(encoding="utf-8").strip()
    assert generated == "print('local')"
    assert artifacts["stdout"].read_text(encoding="utf-8").strip() == "print('local')"
    assert response.metadata["returncode"] == 0


def test_local_exec_nonzero_exit(monkeypatch, run_context: RunContext):
    agent = LocalExecAgent(command_template="tool --prompt {prompt_file} --output {output_file}")

    class DummyCompletedProcess:
        def __init__(self):
            self.returncode = 17
            self.stdout = "partial output"
            self.stderr = "boom"

    def fake_run(cmd, capture_output, text, timeout, cwd, shell):
        return DummyCompletedProcess()

    monkeypatch.setattr("subprocess.run", fake_run)

    agent.prepare_environment(run_context)
    use_case = make_use_case()
    target_dir = run_context.data_dir / "use_case_1"

    with pytest.raises(RuntimeError) as exc:
        agent.execute(run_context, use_case, target_dir)

    assert "status 17" in str(exc.value)

    artifacts = agent.collect_artifacts(run_context, use_case, target_dir)
    assert artifacts["stderr"].read_text(encoding="utf-8").strip() == "boom"
