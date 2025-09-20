# StackBench Agent Support

StackBench now ships with both manual IDE agents and automated CLI agents. The
CLI adapters share a common execution contract and structured logging so new
providers can plug into the benchmark with minimal boilerplate.

## Agent Types

| Agent            | Category | Description |
| ---------------- | -------- | ----------- |
| `cursor`         | IDE      | Manual IDE workflow with rich prompts. |
| `openai-cli`     | CLI      | Uses the OpenAI compatible Chat Completions API. |
| `anthropic-cli`  | CLI      | Targets the Anthropic Claude Messages API. |
| `local-exec`     | CLI      | Runs a configurable local command (e.g., llama.cpp client). |

Agents are created via `stackbench.agents.create_agent` which consults the
registry in `stackbench/agents/__init__.py`. CLI agents expose three key hooks:

* `prepare_environment(run_context)` – verify credentials, create log
  directories, and persist metadata to the run context.
* `execute(run_context, use_case, target_dir)` – produce a normalized
  `AgentResponse` while writing the target file and JSON transcript.
* `collect_artifacts(...)` – return a dictionary of important artifact paths for
  downstream analyzers.

All automated agents write JSONL logs to `<run>/data/agent_logs/<agent>.jsonl`
and persist raw responses alongside generated code. The `RunContext` tracks
execution metadata and automatically marks the execution phase as completed when
all use cases finish.

## Configuration

Environment variables can override any `Config` fields. The most relevant keys
for automated agents are:

```bash
OPENAI_API_KEY=...          # Required for openai-cli
OPENAI_API_BASE=https://api.openai.com/v1  # Optional override

ANTHROPIC_API_KEY=...       # Required for anthropic-cli
ANTHROPIC_API_URL=https://api.anthropic.com/v1/messages
ANTHROPIC_API_VERSION=2023-06-01

STACKBENCH_LOCAL_AGENT_COMMAND_TEMPLATE="python -m my_agent --prompt {prompt_file} --output {output_file}"
STACKBENCH_LOCAL_AGENT_TIMEOUT=180
```

`Config` also includes knobs for retry counts, request timeouts, and default
models (`openai_model`, `anthropic_model`, and `local_agent_model`). These
values can be supplied via `.env` or environment variables using the
`STACKBENCH_<FIELD>` naming convention accepted by Pydantic.

## CLI Workflows

* `stackbench run <repo> --agent openai-cli` – clones the repository, extracts
  use cases, executes them with the chosen agent, and saves artifacts.
* `stackbench execute <run-id> --agent anthropic-cli` – replays execution for an
  existing run without recloning or re-extracting use cases.

After execution completes, run `stackbench analyze <run-id>` to feed artifacts
into the Claude-based analysis pipeline.
