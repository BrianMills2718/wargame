"""Tests for fog-of-war observation filtering in the core engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core import (
    Actor,
    AdjudicationPacket,
    AttributeChange,
    Nation,
    Player,
    TurnEngine,
    WorldState,
    filter_observations,
    load_scenario,
)


def build_visibility_world_state() -> WorldState:
    """Create a world state with ownership, alliances, and map proximity metadata."""

    return WorldState(
        nations={
            "us": Nation(
                entity_id="us",
                name="United States",
                position="washington",
                attributes={"diplomatic_leverage": 50},
            ),
            "uk": Nation(
                entity_id="uk",
                name="United Kingdom",
                position="london",
                attributes={"diplomatic_leverage": 45},
            ),
            "iran": Nation(
                entity_id="iran",
                name="Iran",
                position="tehran",
                attributes={"diplomatic_leverage": 55},
            ),
        },
        actors={
            "proxy-a": Actor(
                entity_id="proxy-a",
                name="Proxy A",
                nation_id="iran",
                position="baghdad",
                attributes={"covert_ops_capacity": 40},
            )
        },
        players={
            "player-us": Player(
                player_id="player-us",
                nation_id="us",
                role="leader",
                position="washington",
            ),
            "player-uk": Player(
                player_id="player-uk",
                nation_id="uk",
                role="operative",
                position="london",
            ),
        },
        alliances={"us": ["uk"], "uk": ["us"], "iran": []},
        map_adjacency={
            "washington": [],
            "london": ["baghdad"],
            "baghdad": ["london", "tehran"],
            "tehran": ["baghdad"],
        },
    )


def test_filter_observations_respects_player_role_alliances_and_proximity() -> None:
    """Leaders should see allied changes, while operatives only see owned and nearby changes."""

    engine = TurnEngine(world_state=build_visibility_world_state())
    packet = AdjudicationPacket(
        packet_id="packet-visibility",
        description="Multi-theater pressure campaign.",
        guaranteed_changes=[
            AttributeChange(
                target_type="nation",
                target_id="us",
                attribute="diplomatic_leverage",
                delta=3,
            ),
            AttributeChange(
                target_type="nation",
                target_id="uk",
                attribute="diplomatic_leverage",
                delta=2,
            ),
            AttributeChange(
                target_type="actor",
                target_id="proxy-a",
                attribute="covert_ops_capacity",
                delta=4,
            ),
            AttributeChange(
                target_type="nation",
                target_id="iran",
                attribute="diplomatic_leverage",
                delta=-5,
            ),
        ],
    )

    engine.process_packet(packet)

    us_visible_targets = {
        change.target_id for change in filter_observations("player-us", engine.world_state)
    }
    uk_visible_targets = {
        change.target_id for change in filter_observations("player-uk", engine.world_state)
    }

    assert us_visible_targets == {"us", "uk"}
    assert uk_visible_targets == {"uk", "proxy-a"}
    assert {change.target_id for change in engine.filter_observations("player-uk")} == {
        "uk",
        "proxy-a",
    }


@pytest.mark.parametrize("scenario_name", ["test_scenario.json", "test_scenario.yaml"])
def test_scenario_loading(scenario_name: str) -> None:
    """Scenario documents should hydrate the canonical world state in one step."""

    scenario_path = Path(__file__).resolve().parent.parent / "scenarios" / scenario_name

    world_state = load_scenario(scenario_path)

    assert isinstance(world_state, WorldState)
    assert set(world_state.nations) == {"us", "iran"}
    assert world_state.players["player-us"].nation_id == "us"
    assert world_state.actors["irgc-navy"].position == "hormuz"
    assert world_state.map_features["strait-of-hormuz"].feature_type == "chokepoint"
    assert world_state.objectives["player-iran"] == [
        "Preserve regime stability while deterring direct escalation."
    ]


def test_scenario_loading_rejects_unsupported_file_format(tmp_path: Path) -> None:
    """Scenario loader should fail loudly when a file format is not supported."""

    unsupported_path = tmp_path / "scenario.txt"
    unsupported_path.write_text("turn_number: 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported scenario file format"):
        load_scenario(unsupported_path)
