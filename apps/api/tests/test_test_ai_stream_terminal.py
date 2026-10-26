"""R70 focused SSE completion checks; no live network, provider or normal DB."""
import asyncio
from contextlib import nullcontext
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest

from tire_api import ai_stream_routes as routes
from test_test_ai_grounding_review import (
    api, private_guards, submit, terminal,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Reader:
    def __init__(self, disconnect=()):
        self.disconnect = list(disconnect)

    async def is_disconnected(self):
        return self.disconnect.pop(0) if self.disconnect else False


def row(sequence):
    return {"sequence": sequence, "cursor": f"cursor-{sequence}", "type": "completed", "payload": {}}


def page(*items, terminal=False, has_more=False):
    return {"items": list(items), "has_more": has_more,
            "execution": {"terminal": terminal}}


def parse_frames(text):
    frames = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        fields["data"] = json.loads(fields["data"])
        frames.append(fields)
    return frames


def fake_reader(monkeypatch, pages, *, request=None, read_advance=0):
    clock = FakeClock()
    calls = []
    remaining = list(pages)

    def event_page(_db, request_id, session_id, *, after, limit):
        calls.append({"request_id": request_id, "session_id": session_id,
                      "after": after, "limit": limit})
        clock.now += read_advance
        selected = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(selected, Exception):
            raise selected
        return selected

    async def in_process(work):
        return work()

    monkeypatch.setattr(routes, "time", SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(routes, "asyncio", SimpleNamespace(to_thread=in_process, sleep=clock.sleep))
    monkeypatch.setattr(routes.store, "event_page", event_page)
    database = SimpleNamespace(sessions=lambda: nullcontext(object()))

    async def collect(after="cursor-0"):
        chunks = [part async for part in routes.stream_events(
            database, request or Reader(), "synthetic-request", "synthetic-owner", after)]
        return parse_frames("".join(chunks))

    return collect, clock, calls


@pytest.mark.parametrize("items", [[], [row(1), row(2)]])
def test_terminal_exhausted_page_ends_without_polling_or_heartbeat(monkeypatch, items):
    collect, clock, calls = fake_reader(monkeypatch, [page(*items, terminal=True)], read_advance=10)
    frames = asyncio.run(collect())
    assert [f["event"] for f in frames] == ["ai_event"] * len(items) + ["stream_end"]
    assert frames[-1]["data"]["reason"] == "window_complete"
    assert frames[-1]["data"]["cursor"] == ("cursor-2" if items else "cursor-0")
    assert len(calls) == 1 and clock.sleeps == []


def test_terminal_with_more_pages_delivers_every_page_and_advances_cursor(monkeypatch):
    collect, clock, calls = fake_reader(monkeypatch, [
        page(row(1), row(2), terminal=True, has_more=True),
        page(row(3), terminal=True, has_more=True),
        page(row(4), row(5), terminal=True, has_more=False),
    ])
    frames = asyncio.run(collect())
    assert [f["data"]["sequence"] for f in frames if f["event"] == "ai_event"] == [1, 2, 3, 4, 5]
    assert [c["after"] for c in calls] == ["cursor-0", "cursor-2", "cursor-3"]
    assert all(c["limit"] == 100 and c["session_id"] == "synthetic-owner" for c in calls)
    assert frames[-1]["data"]["cursor"] == "cursor-5" and clock.sleeps == []


def test_pending_reader_keeps_25_second_window_and_10_second_heartbeat(monkeypatch):
    collect, clock, calls = fake_reader(monkeypatch, [page(terminal=False)])
    frames = asyncio.run(collect())
    assert clock.now == 25.0 and clock.sleeps == [1.0] * 25
    assert len(calls) == 25
    assert [f["event"] for f in frames] == ["heartbeat", "heartbeat", "stream_end"]
    assert frames[-1]["data"]["cursor"] == "cursor-0"


def test_pending_to_terminal_sends_final_page_then_stops(monkeypatch):
    collect, clock, calls = fake_reader(monkeypatch, [
        page(row(1), terminal=False), page(row(2), terminal=True),
    ])
    frames = asyncio.run(collect())
    assert [f["event"] for f in frames] == ["ai_event", "ai_event", "stream_end"]
    assert [c["after"] for c in calls] == ["cursor-0", "cursor-1"]
    assert clock.sleeps == [1.0] and frames[-1]["data"]["cursor"] == "cursor-2"


@pytest.mark.parametrize("terminal_state", [False, True])
def test_event_cap_preserves_last_sent_cursor_without_sending_remaining_rows(monkeypatch, terminal_state):
    monkeypatch.setattr(routes, "MAX_STREAM_EVENTS", 3)
    collect, clock, calls = fake_reader(monkeypatch, [
        page(*(row(i) for i in range(1, 8)), terminal=terminal_state, has_more=True),
    ])
    frames = asyncio.run(collect())
    assert [f["data"]["sequence"] for f in frames if f["event"] == "ai_event"] == [1, 2, 3]
    assert len(calls) == 1 and clock.sleeps == []
    assert frames[-1]["data"]["cursor"] == "cursor-3"


@pytest.mark.parametrize("status", [404, 409])
def test_scope_and_cursor_reset_still_terminate_without_stream_end(monkeypatch, status):
    collect, clock, calls = fake_reader(monkeypatch, [HTTPException(status)])
    frames = asyncio.run(collect())
    assert len(calls) == 1 and clock.sleeps == []
    assert [f["event"] for f in frames] == ["reset"]
    assert frames[0]["data"]["code"] == "ai_stream_cursor_reset_required"


def test_unexpected_page_error_propagates_instead_of_becoming_reset(monkeypatch):
    collect, _clock, _calls = fake_reader(monkeypatch, [HTTPException(503)])
    with pytest.raises(HTTPException) as error:
        asyncio.run(collect())
    assert error.value.status_code == 503


def test_disconnected_reader_does_not_read_or_emit_end(monkeypatch):
    collect, clock, calls = fake_reader(monkeypatch, [page(terminal=True)], request=Reader([True]))
    assert asyncio.run(collect()) == []
    assert not calls and not clock.sleeps


def test_real_private_sse_terminal_body_finishes_without_sleep_or_restarting_provider(api, monkeypatch):
    client, _app, model, pack, _event, _refs = api
    run, _execution = terminal(client, submit(client, pack, "stream", str(uuid4())), "stream")
    assert run["state"] == "completed" and model.calls == 1

    async def forbidden_terminal_sleep(_seconds):
        raise AssertionError("An exhausted terminal SSE must not wait for the 25-second window")

    monkeypatch.setattr(routes, "asyncio", SimpleNamespace(to_thread=asyncio.to_thread, sleep=forbidden_terminal_sleep))
    endpoint = f'/v1/ai/analysis-streams/{run["id"]}/events'
    expected = client.get(endpoint).json()["items"]
    response = client.get(endpoint + "/stream")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    frames = parse_frames(response.text)
    assert [f["data"] for f in frames if f["event"] == "ai_event"] == expected
    assert frames[-1]["event"] == "stream_end" and frames[-1]["data"]["reason"] == "window_complete"
    assert frames[-1]["data"]["cursor"] == expected[-1]["cursor"]
    assert not any(f["event"] == "heartbeat" for f in frames) and model.calls == 1
    # A reconnect after the terminal event carries no duplicate event body.
    response = client.get(endpoint + "/stream", params={"cursor": expected[-1]["cursor"]})
    frames = parse_frames(response.text)
    assert [f["event"] for f in frames] == ["stream_end"] and model.calls == 1
    assert client.get(endpoint + "/stream?cursor=invalid").status_code == 409
