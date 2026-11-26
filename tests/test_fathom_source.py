"""Fathom source adapter — REST API retry behavior."""

from __future__ import annotations

import pytest
import requests as _requests_module

from meeting_hive.sources import SourceAuthError, SourceUnavailable
from meeting_hive.sources.fathom import FathomSource


class _StubResponse:
    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _requests_module.HTTPError(f"{self.status_code}")


def test_connection_error_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("FATHOM_API_KEY", "fth_test")
    success = _StubResponse(200, {"items": [], "next_cursor": None})
    calls = {"count": 0}

    def fake_get(*a, **kw):
        calls["count"] += 1
        if calls["count"] < 3:
            raise _requests_module.ConnectionError("network down")
        return success

    monkeypatch.setattr("meeting_hive.sources.fathom.requests.get", fake_get)
    monkeypatch.setattr("meeting_hive.sources.fathom.time.sleep", lambda *_: None)

    src = FathomSource()
    assert src.list_meetings(since_days=7) == []
    assert calls["count"] == 3


def test_timeout_on_every_attempt_raises_source_unavailable(monkeypatch):
    monkeypatch.setenv("FATHOM_API_KEY", "fth_test")
    calls = {"count": 0}

    def fake_get(*a, **kw):
        calls["count"] += 1
        raise _requests_module.Timeout("read timed out")

    monkeypatch.setattr("meeting_hive.sources.fathom.requests.get", fake_get)
    monkeypatch.setattr("meeting_hive.sources.fathom.time.sleep", lambda *_: None)

    src = FathomSource()
    with pytest.raises(SourceUnavailable, match="Cannot reach Fathom"):
        src.list_meetings(since_days=7)
    assert calls["count"] == 3


def test_transcript_fetch_unreachable_raises_source_unavailable(monkeypatch):
    monkeypatch.setenv("FATHOM_API_KEY", "fth_test")

    def fake_get(*a, **kw):
        raise _requests_module.ConnectionError("network down")

    monkeypatch.setattr("meeting_hive.sources.fathom.requests.get", fake_get)
    monkeypatch.setattr("meeting_hive.sources.fathom.time.sleep", lambda *_: None)

    src = FathomSource()
    with pytest.raises(SourceUnavailable, match="Cannot reach Fathom"):
        src.get_transcript("rec1")


def test_transcript_fetch_rejected_key_raises_source_auth_error(monkeypatch):
    monkeypatch.setenv("FATHOM_API_KEY", "fth_test")
    monkeypatch.setattr(
        "meeting_hive.sources.fathom.requests.get",
        lambda *a, **kw: _StubResponse(401),
    )

    src = FathomSource()
    with pytest.raises(SourceAuthError, match="401"):
        src.get_transcript("rec1")
