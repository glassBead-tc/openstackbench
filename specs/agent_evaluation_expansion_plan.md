# Agent Evaluation Expansion Plan

## Goals
- Support automated evaluation of multiple coding agents beyond the existing Cursor IDE flow.
- Provide a consistent interface so agents can be added, configured, and executed without duplicating boilerplate.
- Capture comparable telemetry (prompts, outputs, run metadata) to feed StackBench's analyzers and metrics.
- Minimize disruption to existing runs while enabling incremental rollout of new agents.

## Current State Summary
- `src/stackbench/agents/base.py` defines the abstract `Agent` contract with helper methods for loading use cases and run context.
- `src/stackbench/agents/cursor_ide.py` implements a manual IDE agent that formats prompts but relies on humans to execute tasks.
- Agent registration/discovery is minimal; the CLI currently targets Cursor workflows and manual execution paths.
- Automation support (API orchestration, retry logic, output capture) is absent, limiting coverage to a single IDE tool.

## Design Principles
1. **Extensibility:** New agents should be drop-in modules that only need provider-specific logic.
2. **Consistency:** Execution should flow through shared utilities for API calls, logging, retries, and error handling.
3. **Reproducibility:** All agent runs must be configurable via environment variables and deterministic request payloads logged to disk.
4. **Observability:** Capture structured artifacts (request/response JSON, transcripts, file diffs) for downstream evaluators.

## Parallel Workstreams
Each workstream can be owned by a separate contributor so the plan scales to four parallel implementations. Shared interfaces and utilities will be developed first (Workstream A), then the three agent adapters (Workstreams B–D) can progress simultaneously once the foundation is available.

### Workstream A — Core Agent Infrastructure Enhancements (Owner 1)
- Refine `Agent` base class to expose optional hooks:
  - `prepare_environment(run_context)` for per-agent setup (e.g., ensuring venvs or API keys).
  - `execute(use_case, target_dir)` for automated flows; default raises `NotImplementedError` for manual agents.
  - `collect_artifacts()` to standardize outputs (logs, generated files, metadata).
- Introduce shared utilities in `src/stackbench/agents/utils.py`:
  - HTTP/API client wrappers with retry/backoff and rate-limit handling.
  - Structured logging helper that writes JSONL to `{run_context.data_dir}/agent_logs/`.
  - Normalized response object that includes completion text, cost metrics, and tool usage.
- Extend configuration (`src/stackbench/config.py`) to surface agent selection and provider credentials via env vars & CLI flags.
- Update documentation (README or docs/agent-support.md) to describe the agent plugin pattern and required environment variables.
- Deliver unit tests for the new utilities and base class hooks (pytest, using fixtures/mocks for HTTP clients).

### Workstream B — OpenAI-Compatible CLI Agent (Owner 2)
- Create `src/stackbench/agents/openai_cli.py` implementing `Agent` for OpenAI-compatible REST APIs (e.g., GPT-4.1, local OpenAI API servers).
- Responsibilities:
  - Build JSON payloads from the formatted prompt (system/instruction + use-case content).
  - Stream or poll completions; support configurable model, temperature, and tool call options.
  - Persist raw request/response plus synthesized code artifacts to the run directory.
  - Implement configurable retry/backoff and graceful handling of API quota errors.
- Add CLI wiring so the new agent can be selected via `stackbench run --agent openai-cli`.
- Provide integration test that uses a mock server (e.g., `responses` library) to validate request payloads and artifact generation.

### Workstream C — Anthropic/Claude API Agent (Owner 3)
- Add `src/stackbench/agents/anthropic_cli.py` mirroring Workstream B but targeting the Claude Messages API.
- Map StackBench prompts to Anthropic’s required format (system prompt + user content blocks).
- Capture tool use JSON when present; save as part of artifacts for later evaluation.
- Implement safety exception handling (e.g., `APIError`, `RateLimitError`) with retries/backoff consistent with Anthropic guidance.
- Extend configuration to read Anthropic API key, default model, and max tokens.
- Supply integration tests using fixtures/mocks similar to Workstream B to ensure API payload fidelity.

### Workstream D — Local Code-Execution Agent (Owner 4)
- Implement `src/stackbench/agents/local_exec.py` that drives an automated CLI agent using a local model (e.g., Llama.cpp server or `litellm` adapter).
- Responsibilities:
  - Spawn subprocesses to execute the model client (configurable command template) with the formatted prompt.
  - Capture stdout/stderr, exit codes, and generated files; enforce timeouts and cancellation.
  - Normalize artifacts into the shared JSON log schema (`collect_artifacts`).
  - Provide hooks for deterministic replay (store command invocation, prompt, environment snapshot).
- Write tests leveraging `subprocess.run` mocks to validate command construction, timeout handling, and artifact capture.
- Document setup instructions for configuring local backends (model path, server URL, etc.).

## Cross-Cutting Deliverables
- Update CLI help text and documentation to list new agents and required environment variables.
- Ensure analyzers can detect which agent produced an output (include agent metadata in run context).
- Provide sample configuration templates (`.env.example`) for new providers without leaking secrets.
- Add regression tests verifying backward compatibility for existing Cursor IDE workflows.

## Milestones & Dependencies
1. **Foundation Ready (Workstream A)** — Shared utilities, configuration hooks, and documentation scaffolding complete. Target: Day 2.
2. **Agent Implementations Complete (Workstreams B–D)** — Individual adapters functional with tests passing. Target: Day 5.
3. **Integration & Validation** — Run end-to-end dry runs for each agent, ensure artifacts feed into analyzers/metrics. Target: Day 6.
4. **Launch Checklist** — Update release notes, finalize documentation, and confirm CI coverage. Target: Day 7.

Workstreams B–D depend on the shared utilities and config changes from Workstream A. Coordination checkpoints should verify interface stability before adapter teams begin.

## Risks & Mitigations
- **API Instability:** External provider changes could break integrations. Mitigation: versioned API clients and comprehensive mocks in tests.
- **Secret Management:** Credentials may leak if mishandled. Mitigation: rely on environment variables, document secure storage, never commit secrets.
- **Artifact Volume:** Logging full transcripts may grow storage. Mitigation: compress JSONL logs and allow configurable retention limits.
- **Local Agent Flakiness:** Subprocess execution might hang. Mitigation: enforce timeouts, heartbeat logs, and kill processes on timeout.

## Open Questions
- Should agents support tool usage (file edits) beyond text generation in v1? (Impacts artifact schema.)
- How should cost/latency metrics integrate with existing analytics dashboards?
- Do we need sandboxing for local agent execution to prevent malicious code during evaluation?
