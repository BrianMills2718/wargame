"""Tests for the running GM conversation.

The conversation is the GM's memory, so the properties that matter are that it
grows append-only, that the cacheable system prefix never changes, and that a
failed call cannot leave the turn structure misaligned.
"""

import json

import pytest

from wargame.gm_session import GMSession
from wargame.models import (
    ActionIntent,
    AdjudicationPacket,
    OutcomeBranch,
)
from wargame.scenario import load_scenario

BASE = {"critical_success": 0.05, "success": 0.20, "partial": 0.40,
        "failure": 0.25, "critical_failure": 0.10}


def _packet(note="n"):
    return AdjudicationPacket(
        reasoning=note,
        possible_outcomes=[
            OutcomeBranch(outcome_id=k, narrative=note, probability=v, state_transitions=[])
            for k, v in BASE.items()
        ],
        observability=[],
    )


def _action(effect="squeeze"):
    return ActionIntent(actor_id="actor_us", action_category="economic",
                        target_entities=[], instruments_used=["inst_us_sanctions"],
                        intended_effect=effect, resource_cost=2)


@pytest.fixture
def spec():
    return load_scenario("scenarios/us_iran_2026.yaml")


class Recorder:
    """Stands in for the model, capturing what it was sent."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise RuntimeError("provider exploded")
        return _packet(f"call {len(self.calls)}"), None


def _session(spec, rec, **kw):
    return GMSession(spec=spec, model="test-model", max_budget=1.0,
                     trace_id="t", call_fn=rec, **kw)


class TestConversationGrows:
    def test_first_call_sends_system_plus_one_user_turn(self, spec):
        rec = Recorder()
        s = _session(spec, rec)
        s.adjudicate(_action(), spec.initial_state, [], BASE, turn_number=1)
        sent = rec.calls[0]["messages"]
        assert [m["role"] for m in sent] == ["system", "user"]

    def test_each_turn_appends_a_user_and_an_assistant_message(self, spec):
        rec = Recorder()
        s = _session(spec, rec)
        for turn in range(1, 4):
            s.adjudicate(_action(), spec.initial_state, [], BASE, turn_number=turn)
        # system + 3 * (user, assistant)
        assert [m["role"] for m in s.messages()] == [
            "system", "user", "assistant", "user", "assistant", "user", "assistant"
        ]
        assert s.adjudications == 3

    def test_the_gms_own_answer_is_what_it_remembers(self, spec):
        """The assistant turn must carry the packet, not a placeholder."""
        rec = Recorder()
        s = _session(spec, rec)
        s.adjudicate(_action(), spec.initial_state, [], BASE, turn_number=1)
        assistant = s.history[1]
        assert assistant["role"] == "assistant"
        parsed = json.loads(assistant["content"])
        assert parsed["reasoning"] == "call 1"

    def test_later_calls_carry_the_earlier_turns(self, spec):
        rec = Recorder()
        s = _session(spec, rec)
        s.adjudicate(_action("first thing"), spec.initial_state, [], BASE, turn_number=1)
        s.adjudicate(_action("second thing"), spec.initial_state, [], BASE, turn_number=2)
        second_call = "\n".join(m["content"] for m in rec.calls[1]["messages"])
        assert "first thing" in second_call, "turn 2 must still see turn 1"
        assert "second thing" in second_call


class TestCacheablePrefix:
    def test_system_prompt_is_byte_identical_across_turns(self, spec):
        """Any drift in the prefix would silently destroy prompt caching."""
        rec = Recorder()
        s = _session(spec, rec)
        for turn in range(1, 4):
            s.adjudicate(_action(), spec.initial_state, [], BASE, turn_number=turn)
        prefixes = {c["messages"][0]["content"] for c in rec.calls}
        assert len(prefixes) == 1

    def test_history_is_append_only(self, spec):
        """Earlier turns must never be rewritten, or the cached prefix breaks."""
        rec = Recorder()
        s = _session(spec, rec)
        s.adjudicate(_action(), spec.initial_state, [], BASE, turn_number=1)
        snapshot = list(s.history)
        s.adjudicate(_action(), spec.initial_state, [], BASE, turn_number=2)
        assert s.history[: len(snapshot)] == snapshot


class TestFailureHandling:
    def test_a_failed_call_does_not_leave_a_dangling_user_turn(self, spec):
        """Two user messages in a row would misalign every later turn."""
        rec = Recorder(fail_on=2)
        s = _session(spec, rec)
        s.adjudicate(_action(), spec.initial_state, [], BASE, turn_number=1)
        with pytest.raises(RuntimeError):
            s.adjudicate(_action(), spec.initial_state, [], BASE, turn_number=2)
        roles = [m["role"] for m in s.history]
        assert roles == ["user", "assistant"], f"history misaligned: {roles}"
        # and the session is still usable
        s.adjudicate(_action(), spec.initial_state, [], BASE, turn_number=3)
        assert [m["role"] for m in s.history] == ["user", "assistant", "user", "assistant"]


class TestBounding:
    def test_history_can_be_bounded_for_very_long_games(self, spec):
        rec = Recorder()
        s = _session(spec, rec, max_history_pairs=2)
        for turn in range(1, 6):
            s.adjudicate(_action(f"turn {turn}"), spec.initial_state, [], BASE, turn_number=turn)
        assert len(s.history) == 4  # 2 pairs
        assert "turn 1" not in "\n".join(m["content"] for m in s.history)

    def test_unbounded_by_default(self, spec):
        rec = Recorder()
        s = _session(spec, rec)
        for turn in range(1, 6):
            s.adjudicate(_action(), spec.initial_state, [], BASE, turn_number=turn)
        assert len(s.history) == 10
