"""Turn engine plus a minimal CLI smoke test for the canonical world state."""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Protocol

from src.core.models import (
    Actor,
    AdjudicationOutcome,
    AdjudicationPacket,
    AppliedChange,
    AttributeChange,
    Nation,
    Player,
    TurnResult,
    WorldState,
)
from src.core.scenario_loader import load_scenario

DEFAULT_SCENARIO_PATH = Path(__file__).resolve().parents[2] / "scenarios" / "test_scenario.yaml"


class RandomSource(Protocol):
    """Interface for RNG injection so outcome selection remains testable."""

    def random(self) -> float:
        """Return a floating-point sample in the inclusive 0-1 range."""


class TurnEngine:
    """Apply adjudication packets to the canonical world state via RNG."""

    def __init__(self, world_state: WorldState, rng: RandomSource | None = None) -> None:
        """Store mutable game state and an injectable RNG implementation."""

        self._world_state = world_state
        self._rng = rng if rng is not None else random.Random()

    @property
    def world_state(self) -> WorldState:
        """Expose the mutable canonical state managed by the engine."""

        return self._world_state

    def process_packet(self, packet: AdjudicationPacket) -> TurnResult:
        """Mutate canonical state for one adjudicated action and return the result."""

        applied_changes = [self._apply_change(change) for change in packet.guaranteed_changes]
        selected_outcome: str | None = None
        roll: float | None = None

        if packet.outcomes:
            roll = self._rng.random()
            outcome = self._select_outcome(packet.outcomes, roll)
            selected_outcome = outcome.name
            applied_changes.extend(self._apply_change(change) for change in outcome.changes)

        self._world_state.turn_number += 1
        result = TurnResult(
            packet_id=packet.packet_id,
            turn_number=self._world_state.turn_number,
            roll=roll,
            selected_outcome=selected_outcome,
            applied_changes=applied_changes,
        )
        self._world_state.latest_turn_result = result
        return result

    def filter_observations(self, player_id: str) -> list[AppliedChange]:
        """Return only the latest observations visible to the requested player."""

        return filter_observations(player_id=player_id, game_state=self._world_state)

    def _select_outcome(
        self, outcomes: list[AdjudicationOutcome], roll: float
    ) -> AdjudicationOutcome:
        """Map a raw RNG roll onto the packet's weighted outcomes."""

        total_weight = sum(outcome.weight for outcome in outcomes)
        threshold = roll * total_weight
        cumulative_weight = 0.0

        for outcome in outcomes:
            cumulative_weight += outcome.weight
            if threshold < cumulative_weight:
                return outcome

        return outcomes[-1]

    def _apply_change(self, change: AttributeChange) -> AppliedChange:
        """Mutate a single state attribute and fail loudly on invalid updates."""

        target = self._resolve_target(change.target_type, change.target_id)
        old_value = target.attributes.get(change.attribute, 0)
        new_value = old_value + change.delta

        if not 0 <= new_value <= 100:
            msg = (
                f"Applying {change.delta} to {change.target_type} '{change.target_id}' "
                f"attribute '{change.attribute}' would leave the valid 0-100 range."
            )
            raise ValueError(msg)

        target.attributes[change.attribute] = new_value
        return AppliedChange(
            target_type=change.target_type,
            target_id=change.target_id,
            attribute=change.attribute,
            old_value=old_value,
            new_value=new_value,
            delta=change.delta,
        )

    def _resolve_target(self, target_type: str, target_id: str) -> Nation | Actor:
        """Resolve a packet target to a canonical state entity."""

        if target_type == "nation":
            try:
                return self._world_state.nations[target_id]
            except KeyError as exc:
                msg = f"Unknown nation target '{target_id}'."
                raise KeyError(msg) from exc

        try:
            return self._world_state.actors[target_id]
        except KeyError as exc:
            msg = f"Unknown actor target '{target_id}'."
            raise KeyError(msg) from exc


def filter_observations(player_id: str, game_state: WorldState) -> list[AppliedChange]:
    """Filter the latest applied changes down to what the player can currently see."""

    try:
        player = game_state.players[player_id]
    except KeyError as exc:
        msg = f"Unknown player '{player_id}'."
        raise KeyError(msg) from exc

    if game_state.latest_turn_result is None:
        return []

    visible_changes: list[AppliedChange] = []
    allied_nations = set(game_state.alliances.get(player.nation_id, []))

    for change in game_state.latest_turn_result.applied_changes:
        if _change_is_visible(change, player, allied_nations, game_state):
            visible_changes.append(change)

    return visible_changes


def _change_is_visible(
    change: AppliedChange,
    player: Player,
    allied_nations: set[str],
    game_state: WorldState,
) -> bool:
    """Apply role, alliance, and proximity rules to one observed change."""

    target = _resolve_observation_target(change.target_type, change.target_id, game_state)
    target_nation_id = target.entity_id if isinstance(target, Nation) else target.nation_id
    is_controlled = target_nation_id == player.nation_id
    is_allied = target_nation_id in allied_nations
    is_local = _positions_are_visible(
        observer_position=player.position,
        target_position=target.position,
        map_adjacency=game_state.map_adjacency,
    )

    if player.role == "leader":
        return is_controlled or is_allied or is_local
    if player.role == "operative":
        return is_controlled or is_local
    return is_local


def _positions_are_visible(
    observer_position: str | None,
    target_position: str | None,
    map_adjacency: dict[str, list[str]],
) -> bool:
    """Return whether the target position is co-located with or adjacent to the observer."""

    if observer_position is None or target_position is None:
        return False
    if observer_position == target_position:
        return True
    return target_position in map_adjacency.get(observer_position, [])


def _resolve_observation_target(
    target_type: str, target_id: str, game_state: WorldState
) -> Nation | Actor:
    """Resolve a change target for visibility checks without mutating the state."""

    if target_type == "nation":
        try:
            return game_state.nations[target_id]
        except KeyError as exc:
            msg = f"Unknown nation target '{target_id}' in observation filter."
            raise KeyError(msg) from exc

    try:
        return game_state.actors[target_id]
    except KeyError as exc:
        msg = f"Unknown actor target '{target_id}' in observation filter."
        raise KeyError(msg) from exc


def build_smoke_test_packet() -> AdjudicationPacket:
    """Create a deterministic packet that exercises a single turn of core mechanics."""

    return AdjudicationPacket(
        packet_id="cli-smoke-test",
        description="US naval signaling increases readiness while Iran hardens regional posture.",
        guaranteed_changes=[
            AttributeChange(
                target_type="nation",
                target_id="us",
                attribute="military_readiness",
                delta=4,
            )
        ],
        outcomes=[
            AdjudicationOutcome(
                name="contained",
                weight=1.0,
                changes=[
                    AttributeChange(
                        target_type="nation",
                        target_id="iran",
                        attribute="regime_stability",
                        delta=-2,
                    ),
                    AttributeChange(
                        target_type="actor",
                        target_id="irgc-navy",
                        attribute="covert_ops_capacity",
                        delta=3,
                    ),
                ],
            )
        ],
    )


def format_world_state(game_state: WorldState) -> str:
    """Render a compact world-state summary suitable for smoke-test output."""

    lines = [f"Turn: {game_state.turn_number}", "Nations:"]
    for nation in game_state.nations.values():
        attributes = ", ".join(
            f"{attribute}={value}" for attribute, value in sorted(nation.attributes.items())
        )
        lines.append(f"  - {nation.name} ({nation.entity_id}): {attributes}")

    if game_state.actors:
        lines.append("Actors:")
        for actor in game_state.actors.values():
            attributes = ", ".join(
                f"{attribute}={value}" for attribute, value in sorted(actor.attributes.items())
            )
            lines.append(f"  - {actor.name} ({actor.entity_id}): {attributes}")

    return "\n".join(lines)


def format_observations(engine: TurnEngine) -> str:
    """Render the most recent per-player observations after one processed packet."""

    lines = ["Filtered observations:"]
    for player_id in sorted(engine.world_state.players):
        visible_changes = engine.filter_observations(player_id)
        if not visible_changes:
            lines.append(f"  - {player_id}: no visible changes")
            continue

        lines.append(f"  - {player_id}:")
        for change in visible_changes:
            lines.append(
                "      "
                f"{change.target_type}:{change.target_id} {change.attribute} "
                f"{change.old_value}->{change.new_value} (delta {change.delta:+d})"
            )

    return "\n".join(lines)


def run_cli(scenario_path: str | Path = DEFAULT_SCENARIO_PATH) -> TurnResult:
    """Load a scenario, process one hardcoded packet, and print the smoke-test summary."""

    game_state = load_scenario(scenario_path)
    engine = TurnEngine(world_state=game_state, rng=random.Random(0))
    print("Initial world state")
    print(format_world_state(engine.world_state))

    packet = build_smoke_test_packet()
    print(f"\nProcessing packet: {packet.description}")
    result = engine.process_packet(packet)

    print(
        "\nTurn result"
        f"\n  packet_id={result.packet_id}"
        f"\n  selected_outcome={result.selected_outcome}"
        f"\n  roll={result.roll}"
    )
    print(f"\n{format_observations(engine)}")
    print("\nUpdated world state")
    print(format_world_state(engine.world_state))
    return result


def main(argv: list[str] | None = None) -> int:
    """Run the CLI smoke test from the command line."""

    parser = argparse.ArgumentParser(
        description="Load a scenario and execute one deterministic smoke-test turn."
    )
    parser.add_argument(
        "--scenario",
        default=str(DEFAULT_SCENARIO_PATH),
        help="Path to a scenario YAML or JSON file. Defaults to the bundled smoke-test scenario.",
    )
    args = parser.parse_args(argv)
    run_cli(args.scenario)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
