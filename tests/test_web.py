"""Web API guards. No LLM calls: model calls are scripted fakes."""

import pytest
from fastapi.testclient import TestClient

import wargame.web.server as server
from wargame.models import ActionIntent


@pytest.fixture
def client():
    return TestClient(server.app)


def test_start_rejects_unknown_play_as(client, monkeypatch, tmp_path):
    def refuse(*a, **k):
        raise AssertionError("game DB created for an actor that does not exist")
    monkeypatch.setattr(server, "init_db", refuse)
    r = client.post("/api/start", json={"play_as": "actor_typo", "db_path": str(tmp_path / "g.sqlite")})
    assert r.status_code == 400
    assert "actor_typo" in r.json()["detail"]


def test_web_ai_action_with_foreign_instrument_is_retried(monkeypatch, spec, conn):
    monkeypatch.setitem(server.game, "action_histories", {"actor_us": []})
    replies = [
        ActionIntent(actor_id="actor_us", action_category="economic", target_entities=[],
                     instruments_used=["inst_iran_proxies"], intended_effect="x", resource_cost=2),
        ActionIntent(actor_id="actor_us", action_category="economic", target_entities=[],
                     instruments_used=["inst_us_sanctions"], intended_effect="x", resource_cost=2),
    ]
    calls = []

    def fake(**kw):
        calls.append(kw)
        return replies.pop(0), None
    monkeypatch.setattr(server, "call_llm_structured", fake)
    intent = server._get_ai_action(conn, spec, "actor_us", 1, "t")
    assert intent.instruments_used == ["inst_us_sanctions"]
    assert len(calls) == 2
