from pathlib import Path
"""Public hosting mode and per-visitor sessions. No LLM calls: replies are scripted."""

import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

import wargame.web.server as server
import wargame.web.sessions as sessions
from wargame.gm_session import GMSession

from tests.test_audit_round3 import _fake_models, _intent, _packet


def _ok_gm(**kw):
    return _packet(transitions=[("sv_military_tension", 0.05)]), None


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch):
    """Each test gets an empty session store and no leftover env."""
    for var in ("WARGAME_PUBLIC", "WARGAME_MAX_SESSIONS", "WARGAME_SESSION_TTL_MIN",
                "WARGAME_PUBLIC_MAX_TURNS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sessions, "STORE", sessions.SessionStore())
    yield
    sessions.STORE.close_all()


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setenv("WARGAME_PUBLIC", "1")


def _client():
    # One portal thread per client: sqlite connections are bound to their creating thread.
    return TestClient(server.app, raise_server_exceptions=False)


# --- sessions are isolated ------------------------------------------------------

def test_two_visitors_have_separate_games(tmp_path):
    with _client() as a, _client() as b:
        ra = a.post("/api/start", json={"play_as": "actor_us", "db_path": str(tmp_path / "a.sqlite")})
        assert ra.status_code == 200, ra.text
        # B has not started: A's game must not be visible to B.
        assert b.get("/api/state").status_code == 400
        rb = b.post("/api/start", json={"play_as": "actor_iran", "db_path": str(tmp_path / "b.sqlite")})
        assert rb.status_code == 200, rb.text
        assert ra.json()["trace_id"] != rb.json()["trace_id"]
        assert ra.json()["play_as"] == "actor_us" and rb.json()["play_as"] == "actor_iran"
        # Each still sees its own game after the other started.
        assert a.get("/api/state").status_code == 200
        assert a.cookies.get("wg_session") != b.cookies.get("wg_session")


def test_session_cookie_flags():
    with _client() as c:
        r = c.get("/api/state")
        cookie = r.headers["set-cookie"]
        assert cookie.startswith("wg_session=")
        assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" not in cookie
        # Cookie is reused, not reissued.
        assert "set-cookie" not in c.get("/api/state").headers
        r2 = TestClient(server.app).get("/api/state", headers={"X-Forwarded-Proto": "https"})
        assert "Secure" in r2.headers["set-cookie"]
        r3 = TestClient(server.app).get("/api/state", headers={"CF-Visitor": '{"scheme":"https"}'})
        assert "Secure" in r3.headers["set-cookie"]


# --- public mode: paths ---------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "/etc/passwd", "../etc/passwd", "scenarios/../pyproject.toml", "..", "",
    "scenarios/", str(Path(__file__).resolve().parent.parent / "scenarios" / "us_iran_2026.yaml"),
    "nonexistent", "us_iran_2026.yaml/../x", "\\windows\\x", ".hidden.yaml",
])
def test_public_rejects_bad_scenario_paths(public, bad):
    with _client() as c:
        r = c.post("/api/start", json={"scenario_path": bad})
        assert r.status_code == 400, (bad, r.text)
        assert "/" not in r.json()["detail"].replace("scenarios/", "")
        assert "Traceback" not in r.text


def test_public_rejects_symlink_out_of_scenarios(public, monkeypatch, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.yaml").write_text("x: 1\n")
    scen = tmp_path / "scenarios"
    scen.mkdir()
    (scen / "evil.yaml").symlink_to(outside / "evil.yaml")
    monkeypatch.setattr(sessions, "SCENARIOS_DIR", scen)
    with pytest.raises(ValueError):
        sessions.resolve_bundled_scenario("evil")


def test_public_accepts_bundled_names_and_ignores_db_path(public, tmp_path):
    with _client() as c:
        for name in ("us_iran_2026", "us_iran_2026.yaml", "scenarios/us_iran_2026.yaml"):
            r = c.post("/api/start", json={"scenario_path": name, "db_path": "/tmp/x_should_be_ignored"})
            assert r.status_code == 200, (name, r.text)
            body = r.json()
            assert body["db_path"] is None
            assert not os.path.exists("/tmp/x_should_be_ignored")
        db = server.game["db_path"]
        assert os.path.basename(db) == f"{body['trace_id']}.sqlite"
        assert os.path.exists(db)


def test_public_restart_removes_previous_db(public):
    with _client() as c:
        c.post("/api/start", json={})
        first = server.game["db_path"]
        c.post("/api/start", json={})
        assert not os.path.exists(first)
        assert os.path.exists(server.game["db_path"])


def test_public_ai_vs_ai_refused(public):
    with _client() as c:
        r = c.post("/api/start", json={"mode": "ai_vs_ai"})
        assert r.status_code == 400
        assert "not available" in r.json()["detail"]
        assert c.get("/api/state").status_code == 400  # nothing was created


def test_public_errors_are_plain_sentences(public):
    with _client() as c:
        r = c.post("/api/start", json={"mode": "bogus"})
        assert r.status_code == 400
        assert r.json() == {"detail": "The request was not understood."}


def test_public_unexpected_error_hides_details(public, monkeypatch):
    def boom(path):
        raise RuntimeError("secret /home/x/file.py detail")
    monkeypatch.setattr(server, "load_scenario", boom)
    with _client() as c:
        r = c.post("/api/start", json={})
        assert r.status_code == 500
        assert r.json() == {"detail": "Something went wrong on the server. Please try again."}
        assert "secret" not in r.text and "/home" not in r.text


# --- public mode: turn cap ------------------------------------------------------

def test_public_turn_cap_enforced(public, monkeypatch):
    monkeypatch.setenv("WARGAME_PUBLIC_MAX_TURNS", "2")
    monkeypatch.setattr(server, "call_llm_structured", _fake_models(_intent(["inst_us_sanctions"])))
    with _client() as c:
        assert c.post("/api/start", json={}).status_code == 200
        server.game["gm_session"] = GMSession(
            spec=server.game["spec"], model="fake", max_budget=0, trace_id="t", call_fn=_ok_gm)
        for _ in range(2):
            r = c.post("/api/command", json={"directive": "sanction"})
            assert r.status_code == 200, r.text
        r = c.post("/api/command", json={"directive": "sanction"})
        assert r.status_code == 409
        assert "limited to 2 turns" in r.json()["detail"]


def test_default_mode_has_no_turn_cap_and_keeps_db_path_and_ai_vs_ai(tmp_path, monkeypatch):
    monkeypatch.setenv("WARGAME_PUBLIC_MAX_TURNS", "1")  # ignored unless WARGAME_PUBLIC=1
    monkeypatch.setattr(server, "call_llm_structured", _fake_models(_intent(["inst_us_sanctions"])))
    db = tmp_path / "mine.sqlite"
    with _client() as c:
        r = c.post("/api/start", json={"db_path": str(db)})
        assert r.status_code == 200
        assert r.json()["db_path"] == str(db) and db.exists()
        server.game["gm_session"] = GMSession(
            spec=server.game["spec"], model="fake", max_budget=0, trace_id="t", call_fn=_ok_gm)
        for _ in range(2):
            assert c.post("/api/command", json={"directive": "x"}).status_code == 200
        assert c.post("/api/start", json={"mode": "ai_vs_ai", "db_path": str(tmp_path / "s.sqlite")}).status_code == 200
        # Validation errors keep FastAPI's default shape outside public mode.
        assert isinstance(c.post("/api/start", json={"mode": "bogus"}).json()["detail"], list)
    # A client-chosen db file is never deleted by the server outside public mode.
    sessions.STORE.close_all()
    assert db.exists()


# --- eviction -------------------------------------------------------------------

def _game_with_db(store, sid, tmp_path):
    sid, state, _ = store.get(sid)
    path = tmp_path / f"{len(store)}_{sid[:6]}.sqlite"
    state["conn"] = sqlite3.connect(str(path))
    state["conn"].execute("create table t(x)")
    state["db_path"] = str(path)
    return sid, state, path


def test_ttl_expiry_closes_connection_and_deletes_file(public, monkeypatch, tmp_path):
    monkeypatch.setenv("WARGAME_SESSION_TTL_MIN", "1")
    now = [1000.0]
    store = sessions.SessionStore(clock=lambda: now[0])
    sid, state, path = _game_with_db(store, None, tmp_path)
    conn = state["conn"]
    now[0] += 59
    store.sweep()
    assert path.exists() and len(store) == 1
    now[0] += 2
    store.sweep()
    assert len(store) == 0 and not path.exists()
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("select 1")
    # An expired id gets a fresh, empty session.
    new_sid, new_state, created = store.get(sid)
    assert created and new_sid != sid and new_state["conn"] is None


def test_max_sessions_evicts_and_cleans_up(public, monkeypatch, tmp_path):
    monkeypatch.setenv("WARGAME_MAX_SESSIONS", "2")
    store = sessions.SessionStore()
    s1, g1, p1 = _game_with_db(store, None, tmp_path)
    s2, g2, p2 = _game_with_db(store, None, tmp_path)
    c1 = g1["conn"]
    store.get(None)  # third visitor: evicts the idlest (s1)
    assert len(store) == 2
    assert not p1.exists() and p2.exists()
    with pytest.raises(sqlite3.ProgrammingError):
        c1.execute("select 1")


def test_max_sessions_prefers_evicting_visitors_without_a_game(public, monkeypatch, tmp_path):
    monkeypatch.setenv("WARGAME_MAX_SESSIONS", "2")
    store = sessions.SessionStore()
    s1, g1, p1 = _game_with_db(store, None, tmp_path)   # oldest, but has a game
    s2, _, _ = store.get(None)                          # idle visitor, no game
    store.get(None)
    assert p1.exists() and store.get(s1)[2] is False


def test_bad_env_values_fail_loudly(monkeypatch):
    monkeypatch.setenv("WARGAME_MAX_SESSIONS", "lots")
    with pytest.raises(RuntimeError, match="WARGAME_MAX_SESSIONS"):
        sessions.max_sessions()
    monkeypatch.setenv("WARGAME_PUBLIC_MAX_TURNS", "0")
    with pytest.raises(RuntimeError, match="WARGAME_PUBLIC_MAX_TURNS"):
        sessions.public_max_turns()
