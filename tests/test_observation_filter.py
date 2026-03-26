"""Focused tests for observation filtering against a mocked turn result."""

from __future__ import annotations

from src.core import (
    Actor,
    AppliedChange,
    Nation,
    Player,
    TurnResult,
    WorldState,
    filter_observations,
)


def build_world_state_with_raw_observation() -> tuple[WorldState, list[AppliedChange]]:
    """Create a game state whose latest turn result mixes visible and hidden changes."""

    raw_observation = [
        AppliedChange(
            target_type="nation",
            target_id="us",
            attribute="diplomatic_leverage",
            old_value=50,
            new_value=55,
            delta=5,
        ),
        AppliedChange(
            target_type="nation",
            target_id="uk",
            attribute="public_opinion_international",
            old_value=60,
            new_value=64,
            delta=4,
        ),
        AppliedChange(
            target_type="actor",
            target_id="border-proxy",
            attribute="covert_ops_capacity",
            old_value=35,
            new_value=39,
            delta=4,
        ),
        AppliedChange(
            target_type="nation",
            target_id="iran",
            attribute="regime_stability",
            old_value=70,
            new_value=66,
            delta=-4,
        ),
    ]
    world_state = WorldState(
        turn_number=2,
        nations={
            "us": Nation(
                entity_id="us",
                name="United States",
                position="london",
                attributes={"diplomatic_leverage": 55},
            ),
            "uk": Nation(
                entity_id="uk",
                name="United Kingdom",
                position="paris",
                attributes={"public_opinion_international": 64},
            ),
            "iran": Nation(
                entity_id="iran",
                name="Iran",
                position="tehran",
                attributes={"regime_stability": 66},
            ),
        },
        actors={
            "border-proxy": Actor(
                entity_id="border-proxy",
                name="Border Proxy",
                nation_id="iran",
                position="paris",
                attributes={"covert_ops_capacity": 39},
            )
        },
        players={
            "player-us": Player(
                player_id="player-us",
                nation_id="us",
                role="leader",
                position="london",
            )
        },
        alliances={"us": ["uk"], "uk": ["us"], "iran": []},
        map_adjacency={
            "london": ["paris"],
            "paris": ["london", "tehran"],
            "tehran": ["paris"],
        },
        latest_turn_result=TurnResult(
            packet_id="packet-observation-filter",
            turn_number=2,
            applied_changes=raw_observation,
        ),
    )
    return world_state, raw_observation


def test_filter_observations_hides_changes_outside_player_visibility_rules() -> None:
    """The filter should keep controlled, allied, and local changes while hiding distant ones."""

    world_state, raw_observation = build_world_state_with_raw_observation()

    filtered_observation = filter_observations("player-us", world_state)

    assert filtered_observation == raw_observation[:3]
    assert [change.target_id for change in filtered_observation] == ["us", "uk", "border-proxy"]
    assert all(change.target_id != "iran" for change in filtered_observation)
