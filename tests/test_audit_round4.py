"""Audit round 4: GM observability must cover every scenario actor. No LLM calls.

A structurally valid packet whose `observability` omitted an actor passed
`adjudication_structure_issues`; `generate_observations` then told that actor
"No significant developments observed this turn." whatever actually happened.
"""

import json

import pytest

from wargame.engine import get_all_variables
from wargame.gm import adjudication_structure_issues
from wargame.gm_session import GMSession
from wargame.turn import adjudicate_action, generate_observations

from tests.test_audit_round3 import BASE, _intent, _packet, _Scripted, _StubGM

ACTORS = {"actor_us", "actor_iran"}
VARS = {"sv_military_tension"}


def _without(packet, actor_id):
    packet.observability = [o for o in packet.observability if o.actor_id != actor_id]
    return packet


def _duplicated(packet, actor_id):
    packet.observability.append(next(o for o in packet.observability if o.actor_id == actor_id))
    return packet


def test_structure_issues_report_actor_missing_from_observability():
    issues = adjudication_structure_issues(_without(_packet(), "actor_iran"), VARS, ACTORS)
    assert any("actor_iran" in i for i in issues), issues


def test_structure_issues_report_actor_observed_twice():
    issues = adjudication_structure_issues(_duplicated(_packet(), "actor_us"), VARS, ACTORS)
    assert any("actor_us" in i for i in issues), issues


def test_complete_observability_has_no_structure_issues():
    assert adjudication_structure_issues(_packet(), VARS, ACTORS) == []


def test_missing_observer_is_rejected_before_any_state_change(spec, conn):
    before = get_all_variables(conn)
    bad = _without(_packet(transitions=[("sv_military_tension", 0.1)]), "actor_iran")
    with pytest.raises(ValueError, match="actor_iran"):
        adjudicate_action(conn, spec, _intent(["inst_us_sanctions"]), 1, {}, _StubGM(bad))
    assert get_all_variables(conn) == before
    assert conn.execute("SELECT COUNT(*) FROM action_log").fetchone()[0] == 0


def test_gm_session_retries_packet_that_observes_an_actor_twice(spec):
    rec = _Scripted(_duplicated(_packet(note="bad"), "actor_us"), _packet(note="ok"))
    s = GMSession(spec=spec, model="fake", max_budget=0, trace_id="t", call_fn=rec)
    packet = s.adjudicate(_intent(["inst_us_sanctions"]), spec.initial_state, [], BASE, turn_number=1)
    assert packet.reasoning == "ok"
    assert rec.calls == 2


def test_gm_session_rejects_packet_that_keeps_omitting_an_actor(spec):
    rec = _Scripted(*[_without(_packet(), "actor_iran") for _ in range(5)])
    s = GMSession(spec=spec, model="fake", max_budget=0, trace_id="t", call_fn=rec)
    with pytest.raises(ValueError, match="actor_iran"):
        s.adjudicate(_intent(["inst_us_sanctions"]), spec.initial_state, [], BASE, turn_number=1)
    assert s.history == []


def _log(conn, packet, actor_id="actor_us", outcome="success"):
    action = _intent(["inst_us_sanctions"], actor_id=actor_id)
    conn.execute(
        "INSERT INTO action_log (action_id, turn_number, actor_id, action_intent, adjudication_packet, realized_outcome_id, rng_roll) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("a1", 1, actor_id, action.model_dump_json(), packet.model_dump_json(), outcome, 0.5),
    )
    return [(actor_id, action)]


def test_observations_fail_loudly_when_logged_packet_omits_an_actor(spec, conn):
    turn_actions = _log(conn, _without(_packet(), "actor_iran"))
    with pytest.raises(ValueError, match="actor_iran"):
        generate_observations(conn, spec, 1, turn_actions)


def test_observations_carry_the_realized_outcome_note(spec, conn):
    turn_actions = _log(conn, _packet())
    packets = generate_observations(conn, spec, 1, turn_actions)
    assert "actor_iran sees success" in json.dumps(packets["actor_iran"])


def test_actor_with_empty_notes_still_gets_the_nothing_observed_line(spec, conn):
    packet = _packet()
    for obs in packet.observability:
        if obs.actor_id == "actor_iran":
            for entry in obs.observations:
                entry.notes = []
    turn_actions = _log(conn, packet)
    packets = generate_observations(conn, spec, 1, turn_actions)
    assert "No significant developments observed this turn." in json.dumps(packets["actor_iran"])
