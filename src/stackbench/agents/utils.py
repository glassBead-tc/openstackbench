"""Utility helpers shared by automated StackBench agents."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import requests
from requests import Response, Session

__all__ = [
    "AgentResponse",
    "JSONLinesLogger",
    "RetryConfig",
    "request_with_retry",
    "resolve_target_path",
]


@dataclass
class AgentResponse:
    """Normalized response returned by automated agents."""

    content: str
    raw: Dict[str, Any] = field(default_factory=dict)
    usage: Dict[str, Any] = field(default_factory=dict)
    cost: Optional[float] = None
    latency_seconds: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetryConfig:
    """Configuration for HTTP retries with exponential backoff."""

    max_attempts: int = 3
    backoff_factor: float = 0.5
    status_forcelist: Iterable[int] = (429, 500, 502, 503, 504)


class JSONLinesLogger:
    """Append-only JSONL logger for agent transcripts and metadata."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, record: Dict[str, Any]) -> None:
        """Append a JSON serializable record to the log file."""

        serializable = _ensure_json_serializable(record)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(serializable, ensure_ascii=False) + "\n")


def request_with_retry(
    method: str,
    url: str,
    *,
    session: Optional[Session] = None,
    retry: Optional[RetryConfig] = None,
    **kwargs: Any,
) -> Response:
    """Execute an HTTP request with retry/backoff handling."""

    retry = retry or RetryConfig()
    attempts = 0
    last_exception: Optional[Exception] = None

    if session is None:
        session = requests.Session()

    retry_status = {int(code) for code in retry.status_forcelist}

    while attempts < retry.max_attempts:
        attempts += 1
        try:
            response = session.request(method, url, **kwargs)
        except requests.RequestException as exc:  # pragma: no cover - network errors
            last_exception = exc
            response = None
        else:
            if response.status_code not in retry_status:
                return response

        if attempts >= retry.max_attempts:
            if response is not None:
                response.raise_for_status()
            if last_exception is not None:
                raise last_exception
            raise RuntimeError("HTTP request failed without response")

        sleep_seconds = retry.backoff_factor * (2 ** (attempts - 1))
        time.sleep(sleep_seconds)

    # The loop either returns or raises above; this line should never execute
    raise RuntimeError("Failed to execute HTTP request with retry")


def _ensure_json_serializable(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort conversion of values to JSON serializable types."""

    def convert(value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [convert(v) for v in value]
        return repr(value)

    return {key: convert(value) for key, value in obj.items()}


def resolve_target_path(target_dir: Path, target_file: str) -> Path:
    """Resolve a use case target file relative to its directory."""

    path = Path(target_file)
    if path.is_absolute():
        return path

    parts = path.parts
    if parts and parts[0].startswith("use_case_"):
        path = Path(*parts[1:]) if len(parts) > 1 else Path(parts[0])

    return (target_dir / path).resolve()
