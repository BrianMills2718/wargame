"""CLI smoke test for the deterministic core engine.

This module serves as the ``python -m src.core`` entry point, exercising the full
Phase 1 pipeline without any LLM calls:

1. Loads a scenario from disk via :func:`~src.core.scenario_loader.load_scenario`.
2. Builds a hardcoded :class:`~src.core.models.AdjudicationPacket` that modifies
   US military readiness (+4) and Iran regime stability (−2).
3. Processes one turn through :class:`~src.core.engine.TurnEngine` with a seeded
   RNG for reproducibility.
4. Prints the initial world state, the turn result, per-player fog-of-war filtered
   observations, and the updated world state.

Usage::

    python -m src.core                        # default scenario
    python -m src.core --scenario path.yaml   # custom scenario

The module also exposes :func:`run_cli` and :func:`main` for programmatic and
test-harness invocation respectively.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from src.core.engine import TurnEngine
from src.core.models import AdjudicationOutcome, AdjudicationPacket, AttributeChange, TurnResult
from src.core.scenario_loader import load_scenario

DEFAULT_SCENARIO_PATH = Path(__file__).resolve().parents[2] / "scenarios" / "us_iran.yaml"


def build_smoke_test_packet() -> AdjudicationPacket:
    """Create a deterministic packet that exercises one turn of core mechanics."""

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
                    )
                ],
            )
        ],
    )


def format_world_state(engine: TurnEngine) -> str:
    """Render a compact world-state summary suitable for smoke-test output."""

    lines = [f"Turn: {engine.world_state.turn_number}", "Nations:"]
    for nation in engine.world_state.nations.values():
        attributes = ", ".join(
            f"{attribute}={value}" for attribute, value in sorted(nation.attributes.items())
        )
        lines.append(f"  - {nation.name} ({nation.entity_id}): {attributes}")

    if engine.world_state.actors:
        lines.append("Actors:")
        for actor in engine.world_state.actors.values():
            attributes = ", ".join(
                f"{attribute}={value}" for attribute, value in sorted(actor.attributes.items())
            )
            if not attributes:
                attributes = "no tracked attributes"
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
    """Load the scenario, process one packet, and print the per-player observations."""

    game_state = load_scenario(scenario_path)
    engine = TurnEngine(world_state=game_state, rng=random.Random(0))
    print("Initial world state")
    print(format_world_state(engine))

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
    print(format_world_state(engine))
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
