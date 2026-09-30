"""Concurrency, docs lockdown and temp-dir sweep for public hosting. No real LLM calls."""

import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

import wargame.web.server as server
import wargame.web.sessions as sessions
from wargame.gm_session import GMSession

from tests.test_audit_round3 import _fake_models, _intent, _packet
from tests.test_public_hosting import _fresh_store, _game_with_db, public  # noqa: F401


def _ok_gm():
    return _packet(transitions=[("sv_military_tension", 0.05)]), None


def _slow_models(delay, entered=None, release=None):
    """Scripted models that sleep `delay` per call; optionally signal/wait."""
    fake = _fake_models(_intent(["inst_us_sanctions"]))

    def slow(**kw):
        if entered is not None:
            entered.set()
        if release is not None:
            assert release.wait(10)
        time.sleep(delay)
        return fake(**kw)
    return slow


def _slow_gm_factory(delay):
    real = GMSession

    def slow_gm(**kw):
        time.sleep(delay)
        return _ok_gm()
    return lambda **kw: real(**{**kw, "call_fn": slow_gm})


def test_two_visitors_turns_run_concurrently(monkeypatch):
    delay = 0.5  # one turn = parser + AI + 2 GM calls = 4 sleeps = ~2.0s
    monkeypatch.setattr(server, "call_llm_structured", _slow_models(delay))
    monkeypatch.setattr(server, "GMSession", _slow_gm_factory(delay))
    clients = [TestClient(server.app, raise_server_exceptions=False) for _ in range(2)]
    for c in clients:
        assert c.post("/api/start", json={}).status_code == 200
    results = [None, None]

    def play(i):
        results[i] = clients[i].post("/api/command", json={"directive": "sanction"})

    t0 = time.monotonic()
    threads = [threading.Thread(target=play, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t0
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    assert elapsed < 3.0, f"turns ran serially: {elapsed:.2f}s (one turn is ~2.0s)"
    assert results[0].json()["turn_result"]["turn"] == 1
    assert results[1].json()["turn_result"]["turn"] == 1


def test_same_visitor_concurrent_commands_get_409(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(server, "call_llm_structured", _slow_models(0, entered, release))
    monkeypatch.setattr(server, "GMSession", _slow_gm_factory(0))
    c = TestClient(server.app, raise_server_exceptions=False)
    assert c.post("/api/start", json={}).status_code == 200
    first = []
    t = threading.Thread(target=lambda: first.append(c.post("/api/command", json={"directive": "a"})))
    t.start()
    assert entered.wait(10)
    second = c.post("/api/command", json={"directive": "b"})
    assert second.status_code == 409
    assert second.json()["detail"] == "Your last order is still being processed."
    assert c.post("/api/start", json={}).status_code == 409  # cannot restart mid-turn either
    release.set()
    t.join()
    assert first[0].status_code == 200
    # After it finishes the visitor can play again.
    assert c.post("/api/command", json={"directive": "c"}).status_code == 200
    assert c.post("/api/command", json={"directive": "d"}).json()["turn_result"]["turn"] == 3


def test_busy_session_is_not_evicted(monkeypatch, tmp_path):
    monkeypatch.setenv("WARGAME_MAX_SESSIONS", "1")
    store = sessions.SessionStore()
    sid, state, path = _game_with_db(store, None, tmp_path)
    held, done = threading.Event(), threading.Event()

    def hold():  # another request thread holds this visitor's lock (RLock is per-thread)
        with state["lock"]:
            held.set()
            done.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    assert held.wait(10)
    try:
        store.get(None)  # cap is 1, but the only session is mid-request
        assert state["conn"] is not None and len(store) == 2
    finally:
        done.set()
        t.join()


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_public_mode_hides_api_docs(public, path):  # noqa: F811
    assert TestClient(server.app).get(path).status_code == 404


def test_docs_available_by_default():
    assert TestClient(server.app).get("/openapi.json").status_code == 200


def test_sweep_removes_only_old_prefixed_dirs(tmp_path):
    old = tmp_path / "wargame_games_old"
    new = tmp_path / "wargame_games_new"
    other = tmp_path / "other_old"
    afile = tmp_path / "wargame_games_file"
    for d in (old, new, other):
        d.mkdir()
    afile.write_text("x")
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "wargame_games_link").symlink_to(target)
    long_ago = time.time() - 7200
    for p in (old, other, afile):
        os.utime(p, (long_ago, long_ago))
    removed = sessions.sweep_stale_temp_dirs(str(tmp_path))
    assert removed == [str(old)]
    assert not old.exists() and new.exists() and other.exists() and afile.exists() and target.exists()


def test_public_db_dir_removed_on_shutdown(public):  # noqa: F811
    with TestClient(server.app) as c:
        assert c.post("/api/start", json={}).status_code == 200
        db_dir = os.path.dirname(server.game["db_path"])
        assert os.path.isdir(db_dir)
    assert not os.path.exists(db_dir)
