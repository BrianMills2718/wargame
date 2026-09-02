"""Tests for the turn history the GM now receives.

The GM previously adjudicated every action with no knowledge that any earlier
turn had happened. These cover the read, the rendering, and the fact that it
reaches the prompt at all.
"""

import json

import pytest

from wargame.engine import get_recent_turn_history
from wargame.gm import build_gm_messages, format_turn_history
from wargame.models import ActionIntent
from wargame.scenario import init_db, load_scenario


@pytest.fixture
def spec():
    return load_scenario("scenarios/us_iran_2026.yaml")


@pytest.fixture
def conn(spec):
    c = init_db(spec)
    yield c
    c.close()


def _log(conn, turn, actor, outcome, narrative, intent="do a thing"):
    packet = {"reasoning": "r", "possible_outcomes": [
        {"outcome_id": outcome, "narrative": narrative, "probability": 1.0, "state_transitions": []}
    ], "observability": []}
    conn.execute(
        "INSERT INTO action_log (action_id, turn_number, actor_id, action_intent, "
        "adjudication_packet, realized_outcome_id, rng_roll) VALUES (?,?,?,?,?,?,?)",
        (f"act_{turn}_{actor}", turn, actor,
         json.dumps({"action_category": "economic", "instruments_used": ["inst_us_sanctions"],
                     "intended_effect": intent}),
         json.dumps(packet), outcome, 0.5),
    )


class TestReadingHistory:
    def test_first_turn_has_no_history(self, conn):
        assert get_recent_turn_history(conn, current_turn=1) == []

    def test_returns_prior_turns_oldest_first(self, conn):
        _log(conn, 1, "actor_us", "success", "First thing happened.")
        _log(conn, 2, "actor_us", "failure", "Second thing failed.")
        h = get_recent_turn_history(conn, current_turn=3)
        assert [e["turn"] for e in h] == [1, 2]
        assert h[0]["outcome"] == "success"
        assert h[1]["narrative"] == "Second thing failed."

    def test_excludes_the_current_turn(self, conn):
        """A turn being adjudicated must not appear in its own history."""
        _log(conn, 1, "actor_us", "success", "Earlier.")
        _log(conn, 2, "actor_us", "success", "This very turn.")
        h = get_recent_turn_history(conn, current_turn=2)
        assert [e["turn"] for e in h] == [1]

    def test_window_is_bounded(self, conn):
        for t in range(1, 9):
            _log(conn, t, "actor_us", "partial", f"Turn {t}.")
        h = get_recent_turn_history(conn, current_turn=9, max_turns=3)
        assert [e["turn"] for e in h] == [6, 7, 8]

    def test_carries_the_realized_outcome_narrative_not_another_branch(self, conn):
        """Only the branch that actually happened should be reported."""
        packet = {"reasoning": "r", "observability": [], "possible_outcomes": [
            {"outcome_id": "success", "narrative": "DID NOT HAPPEN", "probability": 0.5, "state_transitions": []},
            {"outcome_id": "failure", "narrative": "THIS HAPPENED", "probability": 0.5, "state_transitions": []},
        ]}
        conn.execute(
            "INSERT INTO action_log (action_id, turn_number, actor_id, action_intent, "
            "adjudication_packet, realized_outcome_id, rng_roll) VALUES (?,?,?,?,?,?,?)",
            ("act_x", 1, "actor_us", json.dumps({"action_category": "economic",
             "instruments_used": [], "intended_effect": "i"}), json.dumps(packet), "failure", 0.9),
        )
        h = get_recent_turn_history(conn, current_turn=2)
        assert h[0]["narrative"] == "THIS HAPPENED"


class TestRendering:
    def test_empty_history_says_so_explicitly(self):
        assert "first turn" in format_turn_history([]).lower()

    def test_render_names_actor_outcome_and_result(self):
        text = format_turn_history([{
            "turn": 2, "actor_id": "actor_iran", "category": "kinetic",
            "instruments": ["inst_iran_proxies"], "intent": "raise the cost",
            "outcome": "critical_failure", "narrative": "It went badly wrong.",
        }])
        assert "Turn 2" in text
        assert "actor_iran" in text
        assert "CRITICAL_FAILURE" in text
        assert "It went badly wrong." in text


class TestReachesThePrompt:
    def _prompt(self, spec, history):
        action = ActionIntent(actor_id="actor_us", action_category="economic",
                              target_entities=[], instruments_used=["inst_us_sanctions"],
                              intended_effect="squeeze", resource_cost=2)
        msgs = build_gm_messages(
            action=action, state=spec.initial_state, domain_models=spec.domain_models,
            base_rates={"critical_success": 0.05, "success": 0.20, "partial": 0.40,
                        "failure": 0.25, "critical_failure": 0.10},
            actor_ids=["actor_us"], variable_ids=list(spec.initial_state),
            turn_history=history,
        )
        return "\n".join(m["content"] for m in msgs)

    def test_history_appears_in_the_prompt(self, spec):
        text = self._prompt(spec, [{
            "turn": 1, "actor_id": "actor_us", "category": "diplomatic",
            "instruments": ["inst_us_diplomacy"], "intent": "open a channel",
            "outcome": "failure", "narrative": "Iran refused to engage.",
        }])
        assert "Iran refused to engage." in text
        assert "What Has Already Happened" in text

    def test_prompt_instructs_the_gm_to_use_the_sequence(self, spec):
        text = self._prompt(spec, [])
        assert "sequence" in text.lower()

    def test_no_history_still_produces_a_valid_prompt(self, spec):
        text = self._prompt(spec, None)
        assert "first turn" in text.lower()
