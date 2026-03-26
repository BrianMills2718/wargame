"""CLI smoke tests for the package entry point and authored scenario format."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pytest import CaptureFixture

from src.core.__main__ import run_cli
from src.core import WorldState, load_scenario


def test_load_scenario_normalizes_us_iran_authored_format() -> None:
    """The authored list-based US-Iran scenario should load into canonical state objects."""

    scenario_path = Path(__file__).resolve().parent.parent / "scenarios" / "us_iran.yaml"

    world_state = load_scenario(scenario_path)

    assert isinstance(world_state, WorldState)
    assert set(world_state.nations) == {"us", "iran"}
    assert set(world_state.players) == {"player_1", "player_2"}
    assert world_state.players["player_1"].nation_id == "us"
    assert world_state.players["player_2"].nation_id == "iran"
    assert world_state.actors["irgc"].nation_id == "iran"
    assert world_state.objectives["player_1"][0].startswith("Contain Iranian influence")
    assert world_state.objectives["player_2"][0].startswith("Survive with dignity")


def test_python_m_src_core_runs_smoke_test_against_us_iran_scenario() -> None:
    """The package entry point should load the default scenario and print player observations."""

    repo_root = Path(__file__).resolve().parent.parent

    result = subprocess.run(
        [sys.executable, "-m", "src.core"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Filtered observations:" in result.stdout
    assert "  - player_1:" in result.stdout
    assert "  - player_2:" in result.stdout
    assert "nation:us military_readiness 85->89 (delta +4)" in result.stdout
    assert "nation:iran regime_stability 70->68 (delta -2)" in result.stdout


def test_run_cli_returns_turn_result_and_prints_filtered_observations(
    capsys: CaptureFixture[str],
) -> None:
    """The entrypoint helper should process one hardcoded packet against the default scenario."""

    result = run_cli()
    captured = capsys.readouterr()

    assert result.packet_id == "cli-smoke-test"
    assert result.turn_number == 1
    assert result.selected_outcome == "contained"
    assert "Filtered observations:" in captured.out
    assert "  - player_1:" in captured.out
    assert "  - player_2:" in captured.out
