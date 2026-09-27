"""CLI argument handling. No LLM calls: anything past validation is stubbed to fail loudly."""

import sys

import pytest

import wargame.cli as cli


class _ReachedGame(Exception):
    pass


def _refuse(*a, **k):
    raise _ReachedGame("game setup reached")


@pytest.mark.parametrize("turns", [0, -1])
def test_run_game_rejects_non_positive_turns(monkeypatch, turns):
    # Before the fix, num_turns=0 was falsy and silently became the scenario's
    # full turn count; a negative count ran zero turns and then scored anyway.
    monkeypatch.setattr(cli, "load_scenario", _refuse)
    with pytest.raises(ValueError, match="num_turns"):
        cli.run_game("scenarios/does_not_matter.yaml", num_turns=turns)


def test_run_game_none_turns_uses_scenario_default(monkeypatch):
    monkeypatch.setattr(cli, "load_scenario", _refuse)
    with pytest.raises(_ReachedGame):
        cli.run_game("scenarios/does_not_matter.yaml", num_turns=None)


@pytest.mark.parametrize("turns", ["0", "-3"])
def test_cli_rejects_non_positive_turns_flag(monkeypatch, turns):
    monkeypatch.setattr(cli, "run_game", _refuse)
    monkeypatch.setattr(sys, "argv", ["wargame", "s.yaml", "--turns", turns])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_cli_accepts_positive_turns_flag(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "run_game", lambda **kw: seen.update(kw))
    monkeypatch.setattr(sys, "argv", ["wargame", "s.yaml", "--turns", "3"])
    cli.main()
    assert seen["num_turns"] == 3


# --- --play-as must name a scenario actor (audit round 2, #3) -----------------

SCENARIO = "scenarios/us_iran_2026.yaml"


@pytest.mark.parametrize("mode", ["human_vs_ai", "human_vs_human"])
def test_run_game_rejects_unknown_play_as(monkeypatch, mode):
    # Before the fix this reached the banner and crashed with StopIteration.
    monkeypatch.setattr(cli, "init_db", _refuse)
    with pytest.raises(ValueError, match="actor_typo"):
        cli.run_game(SCENARIO, mode=mode, play_as="actor_typo")


def test_run_game_ignores_play_as_in_ai_vs_ai(monkeypatch):
    monkeypatch.setattr(cli, "init_db", _refuse)
    with pytest.raises(_ReachedGame):
        cli.run_game(SCENARIO, mode="ai_vs_ai", play_as="actor_typo")


# --- AI actions get the same legality check as human orders (#1) -------------

from wargame.models import ActionIntent  # noqa: E402


def _intent(instruments):
    return ActionIntent(actor_id="wrong_id", action_category="economic",
                        target_entities=[], instruments_used=instruments,
                        intended_effect="squeeze", resource_cost=2)


class _ScriptedAI:
    def __init__(self, *intents):
        self.intents = list(intents)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.intents.pop(0), None


def test_ai_action_with_foreign_instrument_is_retried(monkeypatch, spec, conn):
    fake = _ScriptedAI(_intent(["inst_iran_proxies"]), _intent(["inst_us_sanctions"]))
    monkeypatch.setattr(cli, "call_llm_structured", fake)
    intent = cli.get_ai_action(conn, spec, "actor_us", 1, [], "t")
    assert intent.instruments_used == ["inst_us_sanctions"]
    assert intent.actor_id == "actor_us"
    assert len(fake.calls) == 2
    retry_prompt = fake.calls[1]["messages"][-1]["content"]
    assert "inst_iran_proxies" in retry_prompt


def test_ai_action_that_stays_illegal_fails_loudly(monkeypatch, spec, conn):
    fake = _ScriptedAI(*[_intent(["inst_made_up"]) for _ in range(10)])
    monkeypatch.setattr(cli, "call_llm_structured", fake)
    with pytest.raises(ValueError, match="inst_made_up"):
        cli.get_ai_action(conn, spec, "actor_us", 1, [], "t")
    assert len(fake.calls) == 3
