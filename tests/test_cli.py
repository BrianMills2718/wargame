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
