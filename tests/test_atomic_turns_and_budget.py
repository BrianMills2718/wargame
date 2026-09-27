"""A turn is all-or-nothing, and actions must fit the actor's resource budget.

No LLM calls: every model reply is scripted.

1. A failure partway through a turn (AI generation, GM adjudication, engine
   apply) used to leave the game partly applied, because the engine committed
   after the mechanical phases and after every action. The turn counter
   advanced and earlier actions stuck even though the turn never finished.
2. `resource_cost` and the scenario's `resource_budget` were declared but never
   checked (ADR-001: "Actions rejected if insufficient budget in the relevant
   domain"), so any action could spend any amount.
"""

import sqlite3

import pytest

import wargame.turn as turn_mod
import wargame.web.server as server
from wargame.ai_opponent import request_valid_ai_action
from wargame.engine import get_all_variables, get_current_turn
from wargame.gm_session import GMSession
from wargame.parser import validate_action_intent

from tests.test_audit_round3 import _fake_models, _intent, _packet, _refuse, client, started  # noqa: F401


def _db():
    return sqlite3.connect(server.game["db_path"])


def _snapshot(conn):
    """Everything a turn can write, so 'unchanged' is checked table by table."""
    return {
        "turn": get_current_turn(conn),
        "vars": get_all_variables(conn),
        "history": conn.execute("SELECT * FROM state_history ORDER BY var_id, turn_number").fetchall(),
        "actions": conn.execute("SELECT COUNT(*) FROM action_log").fetchone()[0],
        "observations": conn.execute("SELECT COUNT(*) FROM observation_log").fetchone()[0],
        "estimates": conn.execute("SELECT * FROM state_estimates ORDER BY 1, 2").fetchall(),
        "pending": conn.execute("SELECT * FROM pending_effects ORDER BY 1").fetchall(),
        "active": conn.execute("SELECT * FROM active_actions ORDER BY 1").fetchall(),
    }


class _GMFailingOnCall:
    """Valid packets until call number `fail_on`, which raises."""

    def __init__(self, fail_on):
        self.fail_on = fail_on
        self.calls = 0

    def __call__(self, **kw):
        self.calls += 1
        if self.calls == self.fail_on:
            raise RuntimeError("GM provider outage")
        return _packet(transitions=[("sv_military_tension", 0.05)]), None


def _ok_gm(**kw):
    return _packet(transitions=[("sv_military_tension", 0.05)]), None


# --- 1. atomic turns: web ------------------------------------------------------

def _assert_web_turn_rolled_back(before, histories_before):
    assert _snapshot(_db()) == before
    assert server.game["turn_log"] == []
    assert server.game["action_histories"] == histories_before
    assert server.game["gm_session"].history == []
    assert server.game["gm_session"].adjudications == 0


def _next_turn_is_clean(started, monkeypatch):
    """After a rolled-back turn the game plays on as if it never happened."""
    monkeypatch.setitem(server.game, "gm_session", GMSession(
        spec=server.game["spec"], model="fake", max_budget=0, trace_id="t", call_fn=_ok_gm))
    monkeypatch.setattr(server, "call_llm_structured", _fake_models(_intent(["inst_us_sanctions"])))
    r = started.post("/api/command", json={"directive": "sanction their bank"})
    assert r.status_code == 200, r.text
    assert r.json()["turn_result"]["turn"] == 1
    db = _db()
    assert get_current_turn(db) == 1
    assert db.execute("SELECT COUNT(*) FROM action_log").fetchone()[0] == 2


def test_web_gm_failure_after_first_action_rolls_back_whole_turn(started, monkeypatch):
    before = _snapshot(_db())
    histories_before = {k: list(v) for k, v in server.game["action_histories"].items()}
    monkeypatch.setattr(server, "call_llm_structured", _fake_models(_intent(["inst_us_sanctions"])))
    monkeypatch.setitem(server.game, "gm_session", GMSession(
        spec=server.game["spec"], model="fake", max_budget=0, trace_id="t", call_fn=_GMFailingOnCall(2)))

    r = started.post("/api/command", json={"directive": "sanction their bank"})
    assert r.status_code == 500, r.text
    _assert_web_turn_rolled_back(before, histories_before)
    _next_turn_is_clean(started, monkeypatch)


def test_web_engine_apply_failure_on_second_action_rolls_back_whole_turn(started, monkeypatch):
    before = _snapshot(_db())
    histories_before = {k: list(v) for k, v in server.game["action_histories"].items()}
    monkeypatch.setattr(server, "call_llm_structured", _fake_models(_intent(["inst_us_sanctions"])))
    monkeypatch.setitem(server.game, "gm_session", GMSession(
        spec=server.game["spec"], model="fake", max_budget=0, trace_id="t", call_fn=_ok_gm))
    real_apply = turn_mod.apply_action_transitions
    calls = []

    def apply_then_fail(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("engine apply failed")
        return real_apply(*a, **k)
    monkeypatch.setattr(turn_mod, "apply_action_transitions", apply_then_fail)

    r = started.post("/api/command", json={"directive": "sanction their bank"})
    assert r.status_code == 500, r.text
    assert len(calls) == 2
    # The GM adjudicated both actions before the apply failed; it must forget both.
    _assert_web_turn_rolled_back(before, histories_before)
    monkeypatch.setattr(turn_mod, "apply_action_transitions", real_apply)
    _next_turn_is_clean(started, monkeypatch)


def test_web_ai_generation_failure_rolls_back_mechanical_phases(started, monkeypatch):
    before = _snapshot(_db())
    histories_before = {k: list(v) for k, v in server.game["action_histories"].items()}
    human = _intent(["inst_us_sanctions"])

    def fake(**kw):
        if kw["task"] == "wargame_parser":
            return human, None
        raise RuntimeError("AI provider outage")
    monkeypatch.setattr(server, "call_llm_structured", fake)

    r = started.post("/api/command", json={"directive": "sanction their bank"})
    assert r.status_code == 500, r.text
    _assert_web_turn_rolled_back(before, histories_before)
    _next_turn_is_clean(started, monkeypatch)


# --- 1. atomic turns: CLI ------------------------------------------------------

def test_cli_gm_failure_after_first_action_rolls_back_whole_turn(monkeypatch, tmp_path):
    import wargame.cli as cli
    monkeypatch.setattr(cli, "call_llm_structured", _fake_models())
    real = cli.GMSession
    # Turn 1 adjudicates two actions (calls 1-2); turn 2 fails on its second (call 4).
    gm = _GMFailingOnCall(4)
    monkeypatch.setattr(cli, "GMSession", lambda **kw: real(**{**kw, "call_fn": gm}))
    db = tmp_path / "g.sqlite"

    snapshots = {}
    real_record = cli.record_state_history

    def record_and_snapshot(conn, turn):
        real_record(conn, turn)
        conn.commit()  # make it visible for the snapshot; the turn is over by now
        snapshots[turn] = _snapshot(sqlite3.connect(db))
    monkeypatch.setattr(cli, "record_state_history", record_and_snapshot)

    with pytest.raises(RuntimeError, match="GM provider outage"):
        cli.run_game("scenarios/us_iran_2026.yaml", mode="ai_vs_ai", num_turns=2, db_path=str(db))
    assert gm.calls == 4
    assert list(snapshots) == [1]
    assert _snapshot(sqlite3.connect(db)) == snapshots[1]


def test_cli_gm_failure_in_first_turn_leaves_initial_state(monkeypatch, tmp_path, spec):
    import wargame.cli as cli
    monkeypatch.setattr(cli, "call_llm_structured", _fake_models())
    real = cli.GMSession
    monkeypatch.setattr(cli, "GMSession", lambda **kw: real(**{**kw, "call_fn": _GMFailingOnCall(2)}))
    db = tmp_path / "g.sqlite"
    with pytest.raises(RuntimeError, match="GM provider outage"):
        cli.run_game("scenarios/us_iran_2026.yaml", mode="ai_vs_ai", num_turns=1, db_path=str(db))
    conn = sqlite3.connect(db)
    assert get_current_turn(conn) == 0
    assert get_all_variables(conn) == pytest.approx(spec.initial_state)
    assert conn.execute("SELECT COUNT(*) FROM action_log").fetchone()[0] == 0


# --- 2. resource budget --------------------------------------------------------

def _us(spec):
    return next(a for a in spec.actors if a.id == "actor_us"), spec.resource_budget["actor_us"]


def _costed(instruments, cost):
    i = _intent(instruments)
    i.resource_cost = cost
    return i


def test_action_within_domain_budget_is_valid(spec):
    actor, budget = _us(spec)
    # sanctions draws on finance (2); cyber on intelligence (2) + military (3).
    assert validate_action_intent(_costed(["inst_us_sanctions"], 2), actor, budget) == []
    assert validate_action_intent(_costed(["inst_us_cyber"], 5), actor, budget) == []


def test_action_over_its_domain_budget_is_rejected(spec):
    actor, budget = _us(spec)
    issues = validate_action_intent(_costed(["inst_us_sanctions"], 3), actor, budget)
    assert len(issues) == 1 and "finance" in issues[0] and "3" in issues[0]
    assert validate_action_intent(_costed(["inst_us_cyber"], 6), actor, budget) != []


def test_action_over_per_turn_budget_is_rejected(spec):
    actor, budget = _us(spec)
    issues = validate_action_intent(_costed([], budget.per_turn + 1), actor, budget)
    assert any("per-turn" in s for s in issues)


def test_ai_over_budget_action_is_retried(spec):
    actor, budget = _us(spec)
    replies = [_costed(["inst_us_sanctions"], 5), _costed(["inst_us_sanctions"], 2)]
    seen = []

    def fake(**kw):
        seen.append(kw["messages"])
        return replies.pop(0), None

    intent = request_valid_ai_action(fake, actor, budget, [{"role": "user", "content": "go"}])
    assert intent.resource_cost == 2
    assert "finance" in seen[1][-1]["content"]


def test_web_rejects_over_budget_human_order_before_turn(started, monkeypatch):
    before = _snapshot(_db())
    replies = [_costed(["inst_us_sanctions"], 4)]

    def fake(**kw):
        if kw["task"] != "wargame_parser":
            raise AssertionError(f"unexpected {kw['task']} call after an invalid order")
        return replies.pop(0), None
    monkeypatch.setattr(server, "call_llm_structured", fake)

    r = started.post("/api/command", json={"directive": "all-out financial war"})
    assert r.status_code == 400, r.text
    assert "budget" in r.json()["detail"]
    assert _snapshot(_db()) == before
