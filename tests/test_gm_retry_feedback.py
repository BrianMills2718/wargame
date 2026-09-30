"""A GM retry after an invalid packet must say what was wrong (no wasted identical resend)."""

from tests.test_gm_session import BASE, _action, _packet, _session, spec  # noqa: F401


def test_retry_after_invalid_packet_carries_feedback_but_history_stays_clean(spec):
    calls = []

    def call(**kw):
        calls.append(kw["messages"])
        if len(calls) == 1:
            return _packet(actors=("actor_us", "actor_iran", "actor_oman")), None
        return _packet(), None

    s = _session(spec, call)
    s.adjudicate(_action(), spec.initial_state, [], BASE, turn_number=1)
    assert len(calls) == 2
    assert [m["role"] for m in calls[0]] == ["system", "user"]
    assert [m["role"] for m in calls[1]] == ["system", "user", "assistant", "user"]
    feedback = calls[1][-1]["content"]
    assert "actor_oman" in feedback and "actor_us" in feedback and "actor_iran" in feedback
    # The correction is not remembered as part of the game conversation.
    assert [m["role"] for m in s.messages()] == ["system", "user", "assistant"]
