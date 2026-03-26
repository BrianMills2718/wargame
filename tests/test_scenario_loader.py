"""Tests for scenario document loading into canonical engine state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core import TurnEngine, WorldState, load_scenario


def write_scenario_fixture(path: Path) -> Path:
    """Write a minimal valid scenario file used to exercise the loader contract."""

    scenario_data = {
        "turn_number": 0,
        "nations": {
            "us": {
                "entity_id": "us",
                "name": "United States",
                "position": "gulf",
                "attributes": {
                    "military_readiness": 65,
                    "diplomatic_leverage": 58,
                },
            },
            "iran": {
                "entity_id": "iran",
                "name": "Iran",
                "position": "tehran",
                "attributes": {
                    "military_readiness": 61,
                    "regime_stability": 63,
                },
            },
        },
        "actors": {
            "irgc-navy": {
                "entity_id": "irgc-navy",
                "name": "IRGC Navy",
                "nation_id": "iran",
                "position": "hormuz",
                "attributes": {
                    "covert_ops_capacity": 54,
                },
            }
        },
        "players": {
            "player-us": {
                "player_id": "player-us",
                "nation_id": "us",
                "role": "leader",
                "position": "gulf",
            },
            "player-iran": {
                "player_id": "player-iran",
                "nation_id": "iran",
                "role": "leader",
                "position": "tehran",
            },
        },
        "alliances": {
            "us": [],
            "iran": [],
        },
        "map_adjacency": {
            "gulf": ["hormuz"],
            "hormuz": ["gulf", "tehran"],
            "tehran": ["hormuz"],
        },
        "map_features": {
            "strait-of-hormuz": {
                "feature_id": "strait-of-hormuz",
                "name": "Strait of Hormuz",
                "feature_type": "chokepoint",
                "position": "hormuz",
                "properties": {
                    "contested": True,
                },
            }
        },
        "objectives": {
            "player-us": [
                "Maintain freedom of navigation through the Strait of Hormuz."
            ],
            "player-iran": [
                "Preserve regime stability while deterring direct escalation."
            ],
        },
    }
    path.write_text(json.dumps(scenario_data, indent=2), encoding="utf-8")
    return path


def test_load_scenario_parses_scenario_data_for_engine_access(tmp_path: Path) -> None:
    """Loaded scenario state should be validated and immediately usable by the engine."""

    scenario_path = write_scenario_fixture(tmp_path / "scenario_test.json")

    world_state = load_scenario(scenario_path)
    engine = TurnEngine(world_state=world_state)

    assert isinstance(world_state, WorldState)
    assert engine.world_state.turn_number == 0
    assert engine.world_state.nations["us"].attributes["military_readiness"] == 65
    assert engine.world_state.actors["irgc-navy"].position == "hormuz"
    assert engine.world_state.map_features["strait-of-hormuz"].feature_type == "chokepoint"
    assert engine.world_state.objectives["player-iran"] == [
        "Preserve regime stability while deterring direct escalation."
    ]


def test_scenario_loading_rejects_unsupported_file_format(tmp_path: Path) -> None:
    """Scenario loader should fail loudly when a file format is not supported."""

    unsupported_path = tmp_path / "scenario.txt"
    unsupported_path.write_text("turn_number: 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported scenario file format"):
        load_scenario(unsupported_path)
