"""Granola source adapter — REST API behavior (paginated list + detail fetch)."""

from __future__ import annotations

import pytest
import requests as _requests_module

from meeting_hive.sources import SourceAuthError
from meeting_hive.sources.granola import GranolaSource


class _StubResponse:
    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _requests_module.HTTPError(f"{self.status_code}")


def test_missing_api_key_raises_source_auth_error_on_construction(monkeypatch):
    """Fail fast at adapter construction — no point reaching list_meetings."""
    monkeypatch.delenv("GRANOLA_API_KEY", raising=False)
    with pytest.raises(SourceAuthError, match="GRANOLA_API_KEY"):
        GranolaSource()


def test_list_meetings_fetches_detail_and_maps_fields(monkeypatch):
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_test")

    list_resp = _StubResponse(
        200,
        {
            "notes": [
                {"id": "n1", "title": "First", "created_at": "2026-05-20T15:00:00Z"},
                {"id": "n2", "title": "Second", "created_at": "2026-05-20T14:00:00Z"},
            ],
            "hasMore": False,
            "cursor": None,
        },
    )
    detail_n1 = _StubResponse(
        200,
        {
            "id": "n1",
            "title": "First",
            "created_at": "2026-05-20T15:00:00Z",
            "owner": {"name": "Me", "email": "me@x.com"},
            "attendees": [{"name": "Alice", "email": "alice@x.com"}],
            "transcript": [{"text": "Hello", "start_time": "2026-05-20T15:00:00Z"}],
            "summary_markdown": "## Summary\nFirst meeting summary",
        },
    )
    detail_n2 = _StubResponse(
        200,
        {
            "id": "n2",
            "title": "Second",
            "created_at": "2026-05-20T14:00:00Z",
            "owner": {"name": "Me", "email": "me@x.com"},
            "attendees": [],
            "transcript": [],
            "summary_markdown": None,
        },
    )

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/v1/notes"):
            return list_resp
        if "/v1/notes/n1" in url:
            return detail_n1
        if "/v1/notes/n2" in url:
            return detail_n2
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("meeting_hive.sources.granola.requests.get", fake_get)

    src = GranolaSource()
    meetings = src.list_meetings(since_days=7)

    assert len(meetings) == 2
    # Sort key is created_at — n2 (14:00) comes before n1 (15:00).
    assert meetings[0].title == "Second"
    assert meetings[1].title == "First"
    assert meetings[1].attendees == ["alice@x.com", "me@x.com"]  # owner appended
    assert meetings[1].reference_summary == "## Summary\nFirst meeting summary"
    assert meetings[0].reference_summary is None


def test_get_transcript_serves_from_cache_after_list(monkeypatch):
    """list_meetings already fetches detail; get_transcript must not re-hit the API."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_test")
    list_resp = _StubResponse(
        200,
        {
            "notes": [{"id": "n1", "title": "X", "created_at": "2026-05-20T15:00:00Z"}],
            "hasMore": False,
        },
    )
    detail_resp = _StubResponse(
        200,
        {
            "id": "n1",
            "title": "X",
            "created_at": "2026-05-20T15:00:00Z",
            "attendees": [],
            "transcript": [
                {"text": "Hello", "start_time": "2026-05-20T15:00:00Z"},
                {"text": "World", "start_time": "2026-05-20T15:00:05Z"},
            ],
        },
    )

    call_count = {"detail": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/v1/notes"):
            return list_resp
        if "/v1/notes/n1" in url:
            call_count["detail"] += 1
            return detail_resp
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("meeting_hive.sources.granola.requests.get", fake_get)

    src = GranolaSource()
    src.list_meetings(since_days=7)
    transcript = src.get_transcript("n1")

    assert call_count["detail"] == 1  # one detail call total, not two
    assert "Hello" in transcript
    assert "World" in transcript


def test_pagination_follows_cursor(monkeypatch):
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_test")

    page1 = _StubResponse(
        200,
        {
            "notes": [{"id": "n1", "title": "P1", "created_at": "2026-05-20T15:00:00Z"}],
            "hasMore": True,
            "cursor": "page2-cursor",
        },
    )
    page2 = _StubResponse(
        200,
        {
            "notes": [{"id": "n2", "title": "P2", "created_at": "2026-05-20T14:00:00Z"}],
            "hasMore": False,
            "cursor": None,
        },
    )
    detail = _StubResponse(
        200,
        {
            "id": "n",
            "title": "x",
            "created_at": "2026-05-20T15:00:00Z",
            "attendees": [],
            "transcript": [],
        },
    )

    page_calls = {"count": 0}
    cursor_seen = {"value": None}

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/v1/notes"):
            page_calls["count"] += 1
            if page_calls["count"] == 2:
                cursor_seen["value"] = (params or {}).get("cursor")
            return page1 if page_calls["count"] == 1 else page2
        if "/v1/notes/" in url:
            return detail
        raise AssertionError(url)

    monkeypatch.setattr("meeting_hive.sources.granola.requests.get", fake_get)

    src = GranolaSource()
    meetings = src.list_meetings(since_days=7)

    assert len(meetings) == 2
    assert page_calls["count"] == 2
    assert cursor_seen["value"] == "page2-cursor"


def test_401_raises_source_auth_error(monkeypatch):
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_bad")
    unauth = _StubResponse(401)
    monkeypatch.setattr(
        "meeting_hive.sources.granola.requests.get",
        lambda *a, **kw: unauth,
    )

    src = GranolaSource()
    with pytest.raises(SourceAuthError, match="401"):
        src.list_meetings(since_days=7)


def test_429_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_test")
    success = _StubResponse(200, {"notes": [], "hasMore": False, "cursor": None})
    responses = [_StubResponse(429), _StubResponse(429), success]
    idx = {"i": 0}

    def fake_get(*a, **kw):
        i = idx["i"]
        idx["i"] += 1
        return responses[min(i, len(responses) - 1)]

    monkeypatch.setattr("meeting_hive.sources.granola.requests.get", fake_get)
    monkeypatch.setattr("meeting_hive.sources.granola.time.sleep", lambda *_: None)

    src = GranolaSource()
    meetings = src.list_meetings(since_days=7)
    assert meetings == []
    assert idx["i"] >= 3  # 2 x 429 + 1 x 200


def test_empty_transcript_returns_none(monkeypatch):
    """A meeting that exists but whose transcript is not ready yet — get_transcript → None."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_test")
    list_resp = _StubResponse(
        200,
        {
            "notes": [{"id": "n1", "title": "X", "created_at": "2026-05-20T15:00:00Z"}],
            "hasMore": False,
        },
    )
    detail_resp = _StubResponse(
        200,
        {
            "id": "n1",
            "title": "X",
            "created_at": "2026-05-20T15:00:00Z",
            "attendees": [],
            "transcript": [],
        },
    )

    def fake_get(url, **kw):
        return list_resp if url.endswith("/v1/notes") else detail_resp

    monkeypatch.setattr("meeting_hive.sources.granola.requests.get", fake_get)

    src = GranolaSource()
    src.list_meetings(since_days=7)
    assert src.get_transcript("n1") is None
