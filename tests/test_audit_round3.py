"""Audit round 3: web/CLI turn-pipeline correctness. No LLM calls.

1. The web path adjudicated human orders without the legality check the CLI runs.
2. The web accepted any `mode` string; anything but ai_vs_ai silently made every
   other actor AI-controlled.
3. The web kept playing past the scenario's final turn.
4. A GM packet naming an unknown state variable reached state application
   (only the probability band was repaired).
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

import wargame.web.server as server
from wargame.engine import get_all_variables, get_current_turn
from wargame.gm import compute_mechanical_base_rate, select_relevant_domain_models
from wargame.gm_session import GMSession
from wargame.models import (
    OUTCOME_IDS,
    ActionIntent,
    AdjudicationPacket,
    OutcomeBranch,
    OutcomeObservation,
    PerActorObservation,
    StateTransition,
)
from wargame.turn import adjudicate_action

BASE = {"critical_success": 0.05, "success": 0.20, "partial": 0.40,
        "failure": 0.25, "critical_failure": 0.10}
ACTORS = ("actor_us", "actor_iran")


def _packet(transitions=(), note="n"):
    return AdjudicationPacket(
        reasoning=note,
        possible_outcomes=[
            OutcomeBranch(outcome_id=k, narrative=note, probability=v,
                          state_transitions=[StateTransition(var_id=var, delta=d) for var, d in transitions])
            for k, v in BASE.items()
        ],
        observability=[
            PerActorObservation(actor_id=a, observations=[
                OutcomeObservation(outcome_id=o, notes=[f"{a} sees {o}"]) for o in OUTCOME_IDS
            ])
            for a in ACTORS
        ],
    )


def _intent(instruments, actor_id="actor_us"):
    return ActionIntent(actor_id=actor_id, action_category="economic", target_entities=[],
                        instruments_used=instruments, intended_effect="squeeze", resource_cost=2)


def _refuse(**kw):
    raise AssertionError("no model call expected here")


@pytest.fixture
def client():
    # One portal thread for the whole test: the game's sqlite connection is
    # bound to the thread that created it, as it is under uvicorn's event loop.
    with TestClient(server.app, raise_server_exceptions=False) as c:
        yield c


def _db():
    """A test-thread connection to the running game's database, for reads."""
    return sqlite3.connect(server.game["db_path"])


@pytest.fixture
def started(client, tmp_path, monkeypatch):
    r = client.post("/api/start", json={"play_as": "actor_us", "mode": "human_vs_ai",
                                        "db_path": str(tmp_path / "g.sqlite")})
    assert r.status_code == 200, r.text
    # GM must never be reached in these tests unless a test replaces it.
    monkeypatch.setitem(server.game, "gm_session", GMSession(
        spec=server.game["spec"], model="fake", max_budget=0, trace_id="t", call_fn=_refuse))
    return client


# --- 1. human orders are validated on the web path too ------------------------

def test_web_rejects_human_order_with_foreign_instrument(started, monkeypatch):
    before_state = get_all_variables(_db())
    replies = [_intent(["inst_iran_proxies"])]

    def fake(**kw):
        if kw["task"] != "wargame_parser":
            raise AssertionError(f"unexpected {kw['task']} call after an invalid order")
        return replies.pop(0), None
    monkeypatch.setattr(server, "call_llm_structured", fake)

    r = started.post("/api/command", json={"directive": "use their proxies"})
    assert r.status_code == 400, r.text
    assert "inst_iran_proxies" in r.json()["detail"]
    # The rejected order must not have started a turn.
    assert get_current_turn(_db()) == 0
    assert get_all_variables(_db()) == before_state
    assert server.game["turn_log"] == []


# --- 2. only supported modes are accepted --------------------------------------

@pytest.mark.parametrize("mode", ["human_vs_human", "hvh", ""])
def test_web_start_rejects_unsupported_mode(client, tmp_path, monkeypatch, mode):
    def refuse(*a, **k):
        raise AssertionError("game DB created for an unsupported mode")
    monkeypatch.setattr(server, "init_db", refuse)
    r = client.post("/api/start", json={"mode": mode, "db_path": str(tmp_path / "g.sqlite")})
    assert r.status_code == 422, r.text


def test_cli_run_game_rejects_unknown_mode(monkeypatch):
    import wargame.cli as cli

    def refuse(*a, **k):
        raise AssertionError("game DB created for an unknown mode")
    monkeypatch.setattr(cli, "init_db", refuse)
    with pytest.raises(ValueError, match="hvh"):
        cli.run_game("scenarios/us_iran_2026.yaml", mode="hvh")


# --- 3. no turns after the scenario's final turn --------------------------------

def test_web_rejects_command_after_final_turn(started, monkeypatch):
    final = server.game["spec"].meta.turns
    with _db() as db:
        db.execute("UPDATE game_state SET value=? WHERE key='current_turn'", (str(final),))
    monkeypatch.setattr(server, "call_llm_structured", _refuse)

    r = started.post("/api/command", json={"directive": "one more"})
    assert r.status_code == 409, r.text
    assert get_current_turn(_db()) == final


# --- 4. structurally invalid GM packets never reach state -----------------------

class _StubGM:
    """A GM whose packet skipped validation (defence in depth for the pipeline)."""

    def __init__(self, packet):
        self.packet = packet

    def adjudicate(self, **kw):
        return self.packet


def test_unknown_var_id_is_rejected_before_any_state_change(spec, conn):
    before = get_all_variables(conn)
    bad = _packet(transitions=[("sv_military_tension", 0.1), ("sv_made_up", 0.2)])
    with pytest.raises(ValueError, match="sv_made_up"):
        adjudicate_action(conn, spec, _intent(["inst_us_sanctions"]), 1, {}, _StubGM(bad))
    assert get_all_variables(conn) == before
    assert conn.execute("SELECT COUNT(*) FROM action_log").fetchone()[0] == 0


def test_band_violation_is_still_clamped_not_rejected(spec, conn):
    greedy = _packet(transitions=[("sv_military_tension", 0.1)])
    for o in greedy.possible_outcomes:
        o.probability = {"critical_success": 0.6, "success": 0.1, "partial": 0.1,
                         "failure": 0.1, "critical_failure": 0.1}[o.outcome_id]
    action = _intent(["inst_us_sanctions"])
    base = compute_mechanical_base_rate(
        select_relevant_domain_models(spec, action), action, get_all_variables(conn))
    _, packet = adjudicate_action(conn, spec, action, 1, {}, _StubGM(greedy))
    for o in packet.possible_outcomes:
        assert abs(o.probability - base[o.outcome_id]) <= 0.15 + 1e-9


class _Scripted:
    def __init__(self, *packets):
        self.packets = list(packets)
        self.calls = 0

    def __call__(self, **kw):
        self.calls += 1
        return self.packets.pop(0), None


def test_gm_session_retries_packet_with_unknown_var_id(spec):
    rec = _Scripted(_packet([("sv_made_up", 0.1)], note="bad"), _packet([("sv_military_tension", 0.1)], note="ok"))
    s = GMSession(spec=spec, model="fake", max_budget=0, trace_id="t", call_fn=rec)
    packet = s.adjudicate(_intent(["inst_us_sanctions"]), spec.initial_state, [], BASE, turn_number=1)
    assert packet.reasoning == "ok"
    assert rec.calls == 2
    assert [m["role"] for m in s.history] == ["user", "assistant"]


def test_gm_session_rejects_packet_that_keeps_unknown_var_id(spec):
    rec = _Scripted(*[_packet([("sv_made_up", 0.1)]) for _ in range(5)])
    s = GMSession(spec=spec, model="fake", max_budget=0, trace_id="t", call_fn=rec)
    with pytest.raises(ValueError, match="sv_made_up"):
        s.adjudicate(_intent(["inst_us_sanctions"]), spec.initial_state, [], BASE, turn_number=1)
    assert rec.calls == 3
    assert s.history == []


# --- the shared pipeline still plays a full turn through both front ends ------

def _fake_models(parser_intent=None):
    """Scripted parser/AI/scorer replies keyed by task; never a real model."""
    from wargame.models import ActorScore

    def fake(**kw):
        task = kw["task"]
        if task == "wargame_parser":
            return parser_intent, None
        if task == "wargame_ai_opponent":
            # Each AI is prompted with its own instruments; answer in kind.
            mine = "inst_us_sanctions" if "inst_us_sanctions" in str(kw["messages"]) else "inst_iran_proxies"
            return _intent([mine]), None
        if task == "wargame_scorer":
            return ActorScore.model_construct(), None
        raise AssertionError(f"unexpected task {task}")
    return fake


def _fake_gm(**kw):
    return _packet(transitions=[("sv_military_tension", 0.05)]), None


def test_web_full_turn_through_shared_pipeline(started, monkeypatch):
    monkeypatch.setattr(server, "call_llm_structured", _fake_models(_intent(["inst_us_sanctions"])))
    monkeypatch.setitem(server.game, "gm_session", GMSession(
        spec=server.game["spec"], model="fake", max_budget=0, trace_id="t", call_fn=_fake_gm))
    r = started.post("/api/command", json={"directive": "sanction their bank"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["turn_result"]["turn"] == 1
    assert [a["actor_id"] for a in body["turn_result"]["actions"]] == ["actor_us", "actor_iran"]
    assert "actor_us sees" in " ".join(body["turn_result"]["observations"]["actor_us"])
    assert body["turns_remaining"] == server.game["spec"].meta.turns - 1
    assert body["game_over"] is False
    assert get_current_turn(_db()) == 1


def test_cli_full_game_through_shared_pipeline(monkeypatch, tmp_path, capsys):
    import wargame.cli as cli
    monkeypatch.setattr(cli, "call_llm_structured", _fake_models())
    monkeypatch.setattr(cli, "to_scored_actor", lambda actor, score: None)
    monkeypatch.setattr(cli, "format_scoreboard", lambda scored: "")
    real = cli.GMSession
    monkeypatch.setattr(cli, "GMSession", lambda **kw: real(**{**kw, "call_fn": _fake_gm}))
    db = tmp_path / "g.sqlite"
    cli.run_game("scenarios/us_iran_2026.yaml", mode="ai_vs_ai", num_turns=2, db_path=str(db))
    out = capsys.readouterr().out
    assert "GAME OVER" in out
    assert "actor_us sees" in out
    assert get_current_turn(sqlite3.connect(db)) == 2
