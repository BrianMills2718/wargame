#!/usr/bin/env python3
"""Play the geopolitical wargame interactively.

Usage:
    python play.py
    python play.py --scenario scenarios/us_iran.yaml
    python play.py --model gemini/gemini-2.5-flash
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.core.models import WorldState
from src.core.engine import TurnEngine
from src.core.scenario_loader import load_scenario
from src.gm.adjudicator import adjudicate_player_action


def _print_state(world: WorldState, player_id: str) -> None:
    """Print what this player can see."""
    # Find which nation this player controls
    player = world.players.get(player_id)
    if not player:
        print(f"  (unknown player {player_id})")
        return
    nation_id = player.nation_id
    nation = world.nations.get(nation_id)
    if nation:
        print(f"\n  Your nation: {nation.name}")
        print(f"  Attributes:")
        for k, v in sorted(nation.attributes.items()):
            print(f"    {k}: {v}")

    # Show actors belonging to this nation
    my_actors = [a for a in world.actors.values() if a.nation_id == nation_id]
    if my_actors:
        print(f"  Your agents:")
        for a in my_actors:
            print(f"    - {a.name} ({a.entity_id})")


def _print_observations(engine: TurnEngine, result, player_id: str) -> None:
    """Print filtered observations for this player."""
    obs = engine.filter_observations(result, player_id)
    if not obs:
        print("  (no observable changes this turn)")
        return
    for o in obs:
        print(f"  {o}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Play the geopolitical wargame")
    parser.add_argument("--scenario", default="scenarios/us_iran.yaml",
                        help="Path to scenario YAML file")
    parser.add_argument("--model", default="gemini/gemini-2.5-flash",
                        help="LLM model for the Game Master")
    parser.add_argument("--budget", type=float, default=2.0,
                        help="Max USD per GM call")
    parser.add_argument("--turns", type=int, default=10,
                        help="Max turns before game ends")
    args = parser.parse_args()

    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"Scenario not found: {scenario_path}")
        sys.exit(1)

    world = load_scenario(scenario_path)
    engine = TurnEngine(world)

    # Get player IDs from the scenario
    player_ids = list(world.players.keys())
    if len(player_ids) < 2:
        print(f"Need at least 2 players, found {len(player_ids)}")
        sys.exit(1)

    print("=" * 60)
    print("  GEOPOLITICAL WARGAME")
    print("=" * 60)
    print(f"\nScenario: {scenario_path.stem}")
    print(f"Players: {', '.join(player_ids)}")
    print(f"Model: {args.model}")
    print(f"Max turns: {args.turns}")
    print("\nType your directive in natural language.")
    print("Type 'quit' to exit, 'status' to see your state.\n")

    last_summary: str | None = None

    for turn in range(1, args.turns + 1):
        for player_id in player_ids:
            player = world.players[player_id]
            nation = world.nations[player.nation_id]

            print(f"\n{'─' * 60}")
            print(f"  Turn {turn} — {nation.name} ({player_id})")
            print(f"{'─' * 60}")

            while True:
                directive = input("\n> ").strip()
                if not directive:
                    continue
                if directive.lower() == "quit":
                    print("\nGame ended by player.")
                    return
                if directive.lower() == "status":
                    _print_state(world, player_id)
                    continue
                break

            print(f"\n  [GM is adjudicating...]")
            try:
                gm_packet = adjudicate_player_action(
                    world,
                    player_id,
                    directive,
                    model=args.model,
                    trace_id=f"wargame.play.turn_{turn}.{player_id}",
                    max_budget=args.budget,
                    recent_turn_summary=last_summary,
                )
                print(f"  GM reasoning: {gm_packet.reasoning}")
                print(f"  GM confidence: {gm_packet.confidence}")

                # Convert to engine packet and process
                core_packet = gm_packet.to_engine_packet()
                result = engine.process_turn(core_packet)

                print(f"\n  [Dice rolled — outcome: {result.selected_outcome}]")
                print(f"\n  What you observe:")
                _print_observations(engine, result, player_id)

                last_summary = (
                    f"Turn {turn}: {nation.name} — {directive}. "
                    f"Outcome: {result.selected_outcome}."
                )

            except Exception as e:
                print(f"\n  [GM error: {e}]")
                print(f"  (Turn skipped — try a different directive)")

        print(f"\n  End of turn {turn}.")

    print("\n" + "=" * 60)
    print("  GAME OVER — Max turns reached")
    print("=" * 60)
    print("\nFinal state:")
    for pid in player_ids:
        _print_state(world, pid)


if __name__ == "__main__":
    main()
