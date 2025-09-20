import json
from pathlib import Path
from unittest import mock

import pytest

from stackbench.agents.utils import JSONLinesLogger, RetryConfig, request_with_retry


class DummyResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:  # pragma: no cover - used in retries
        if 400 <= self.status_code:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_request_with_retry_success(monkeypatch):
    session = mock.Mock()
    first = DummyResponse(500)
    second = DummyResponse(200, {"ok": True})
    session.request.side_effect = [first, second]

    result = request_with_retry(
        "GET",
        "https://example.com",
        session=session,
        retry=RetryConfig(max_attempts=2, backoff_factor=0),
    )

    assert result is second
    assert session.request.call_count == 2


def test_request_with_retry_raises_after_failures():
    session = mock.Mock()
    session.request.return_value = DummyResponse(500)

    with pytest.raises(RuntimeError):
        request_with_retry(
            "POST",
            "https://example.com",
            session=session,
            retry=RetryConfig(max_attempts=1, backoff_factor=0),
        )


def test_json_lines_logger(tmp_path: Path):
    log_path = tmp_path / "logs" / "agent.jsonl"
    logger = JSONLinesLogger(log_path)
    logger.log({"event": "test", "value": 1})
    logger.log({"event": "test", "value": 2})

    content = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 2
    rows = [json.loads(line) for line in content]
    assert rows[0]["value"] == 1
    assert rows[1]["value"] == 2
