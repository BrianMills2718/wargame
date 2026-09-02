"""Tests for the player advisor, ADR-004's reliable out-of-game analyst.

The load-bearing property is the information barrier. The advisor is the one
component that sees the player's picture and talks back to them in plain
language, so if it is ever built from canonical state it silently hands the
player the answers and fog of war stops meaning anything.
"""

import pytest

from wargame.advisor import build_advisor_messages
from wargame.scenario import load_scenario


@pytest.fixture
def spec():
    return load_scenario("scenarios/us_iran_2026.yaml")


def _prompt_text(spec, estimates, question="what should I do?"):
    actor = next(a for a in spec.actors if a.id == "actor_us")
    messages = build_advisor_messages(
        actor=actor,
        domain_models=spec.domain_models,
        estimates=estimates,
        budget=spec.resource_budget["actor_us"].domains,
        recent_observations=[],
        action_history=[],
        turn_number=1,
        total_turns=20,
        question=question,
    )
    return "\n".join(m["content"] for m in messages)


class TestInformationBarrier:
    def test_advisor_sees_the_estimate_not_the_truth(self, spec):
        """Feeding the player's estimate must not surface the canonical value.

        This is the regression guard: swap `get_actor_state_estimates` for
        `get_all_variables` at the call site and this test fails.
        """
        estimates = {"sv_internal_legitimacy": 0.11}
        text = _prompt_text(spec, estimates)

        assert "0.11" in text, "the player's own estimate should reach the advisor"
        # The canonical value in the scenario is 0.50. It must not appear as
        # this variable's value anywhere in the prompt.
        legitimacy_lines = [ln for ln in text.splitlines() if "internal_legitimacy:" in ln]
        assert legitimacy_lines, "the variable should be shown to the advisor"
        for line in legitimacy_lines:
            assert "0.50" not in line, f"canonical value leaked into: {line!r}"

    def test_advisor_is_given_only_the_players_instruments(self, spec):
        """Iran's instruments must never appear in the US player's advisor prompt."""
        text = _prompt_text(spec, {"sv_military_tension": 0.4})
        iran = next(a for a in spec.actors if a.id == "actor_iran")
        for inst in iran.instruments:
            assert inst.id not in text, f"opponent instrument leaked: {inst.id}"

    def test_advisor_receives_no_variable_the_caller_did_not_pass(self, spec):
        """The advisor cannot invent state: it only sees the dict it is handed."""
        text = _prompt_text(spec, {"sv_military_tension": 0.4})
        assert "elite_cohesion" not in text.split("HOW THIS WORLD WORKS")[0].split("INTELLIGENCE PICTURE")[-1]


class TestMechanicsAreExplained:
    def test_prompt_states_the_real_baseline_odds(self, spec):
        """ADR-004: the advisor knows it is a game and may explain the mechanics."""
        text = _prompt_text(spec, {"sv_military_tension": 0.4})
        # dm_diplomatic_engagement is 0.05 + 0.25 = 30%
        assert "30%" in text, "baseline odds should be stated as a percentage"

    def test_prompt_states_the_state_conditions(self, spec):
        """The advisor should be able to say why the odds move."""
        text = _prompt_text(spec, {"sv_military_tension": 0.4})
        assert "in a hot crisis a deterrent signal reads as preparation to strike" in text

    def test_question_reaches_the_advisor_verbatim(self, spec):
        text = _prompt_text(spec, {"sv_military_tension": 0.4}, question="should I bomb Natanz?")
        assert "should I bomb Natanz?" in text


class TestCallSiteBarrier:
    """The tests above check build_advisor_messages in isolation, which cannot
    catch the failure that actually matters: the CLI passing canonical state
    into it. This drives the real call path with a stubbed model."""

    def test_ask_advisor_sends_the_estimate_not_the_canonical_value(self, monkeypatch):
        import wargame.cli as cli
        from wargame.engine import apply_delta, get_variable
        from wargame.scenario import init_db, load_scenario

        spec = load_scenario("scenarios/us_iran_2026.yaml")
        conn = init_db(spec)

        # Diverge the world from what the US believes about it: the canonical
        # value moves, the US estimate is left stale at its starting value.
        apply_delta(conn, "sv_internal_legitimacy", -0.37, respect_rate_limits=False)
        canonical = get_variable(conn, "sv_internal_legitimacy")
        stale_estimate = conn.execute(
            "SELECT estimated_value FROM state_estimates WHERE actor_id='actor_us' AND var_id='sv_internal_legitimacy'"
        ).fetchone()[0]
        assert abs(canonical - stale_estimate) > 0.3, "the fixture must actually diverge"

        captured = {}

        class _Reply:
            answer = "stub"
            options: list = []
            uncertainty = ""

        def fake_call(*, messages, **kwargs):
            captured["text"] = "\n".join(m["content"] for m in messages)
            return _Reply(), None

        monkeypatch.setattr(cli, "call_llm_structured", fake_call)
        cli.ask_advisor(conn, spec, "actor_us", "how is Iran holding up?", 1, [], 20, "trace_test")
        conn.close()

        lines = [ln for ln in captured["text"].splitlines() if "internal_legitimacy:" in ln]
        assert lines, "the variable should be shown to the advisor"
        shown = lines[0]
        assert f"{stale_estimate:.2f}" in shown, f"expected the stale estimate in {shown!r}"
        assert f"{canonical:.2f}" not in shown, (
            f"canonical value {canonical:.2f} reached the advisor: {shown!r}"
        )
