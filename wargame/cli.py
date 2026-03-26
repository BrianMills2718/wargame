#!/usr/bin/env python3
"""CLI interface for the geopolitical wargame.

Play modes:
  human_vs_ai  — You play one side, AI plays the other
  human_vs_human — Two humans take turns at the same terminal
  ai_vs_ai — Watch two AIs play (research mode)

Usage:
  python -m wargame.cli scenarios/us_iran_2026.yaml --mode human_vs_ai --play-as actor_us
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import uuid
from pathlib import Path

from llm_client import call_llm_structured

from wargame.ai_opponent import build_ai_opponent_messages
from wargame.engine import (
    advance_turn,
    apply_action_transitions,
    generate_action_id,
    get_all_variables,
    record_state_history,
    resolve_action,
    run_mechanical_phases,
)
from wargame.fog import (
    compute_observation_quality,
    generate_observation_packet,
    get_actor_state_estimates,
)
from wargame.gm import (
    build_gm_messages,
    compute_mechanical_base_rate,
    normalize_probabilities,
    select_relevant_domain_models,
    validate_adjudication,
)
from wargame.models import ActionIntent, AdjudicationPacket, ScenarioSpec
from wargame.parser import build_parser_messages, validate_action_intent
from wargame.scenario import init_db, load_scenario

GM_MODEL = "gemini/gemini-2.5-flash"
PARSER_MODEL = "gemini/gemini-2.5-flash"
AI_MODEL = "gemini/gemini-2.5-flash"


def print_banner(text: str, char: str = "=") -> None:
    """Print a formatted banner."""
    width = max(60, len(text) + 4)
    print(f"\n{char * width}")
    print(f"  {text}")
    print(f"{char * width}")


def print_state_summary(estimates: dict[str, float], label: str) -> None:
    """Print a formatted state summary from an actor's estimates."""
    print(f"\n  {label}:")
    for var_id in sorted(estimates):
        bar_len = int(estimates[var_id] * 20) if estimates[var_id] <= 1.0 else int(min(estimates[var_id] / 36 * 20, 20))
        bar = "█" * bar_len + "░" * (20 - bar_len)
        print(f"    {var_id.replace('sv_', ''):<30} {estimates[var_id]:>6.2f} [{bar}]")


def get_human_action(
    conn: sqlite3.Connection,
    spec: ScenarioSpec,
    actor_id: str,
    trace_id: str,
) -> ActionIntent:
    """Get and parse a human player's natural language command."""
    actor = next(a for a in spec.actors if a.id == actor_id)
    instruments = [{"id": inst.id, "midfield": inst.midfield, "target_vars": inst.target_vars} for inst in actor.instruments]
    budget = spec.resource_budget[actor_id].domains

    print(f"\n  Your instruments: {', '.join(i.id.replace('inst_', '') for i in actor.instruments)}")
    print(f"  Budget: {budget}")

    while True:
        directive = input(f"\n  [{actor.name}] Your orders: ").strip()
        if not directive:
            print("  (Enter a command, or 'quit' to exit)")
            continue
        if directive.lower() in ("quit", "exit", "q"):
            print("\n  Game ended by player.")
            sys.exit(0)

        print("  Parsing your command...")
        messages = build_parser_messages(directive, actor, instruments, budget)

        try:
            intent, _ = call_llm_structured(
                model=PARSER_MODEL,
                messages=messages,
                response_model=ActionIntent,
                task="wargame_parser",
                trace_id=trace_id,
                max_budget=0.5,
            )

            issues = validate_action_intent(intent, actor)
            if issues:
                print(f"  ⚠ Problem with your order: {issues}")
                print("  Try again.")
                continue

            print(f"  Understood: [{intent.action_category}] using {intent.instruments_used}")
            print(f"  → {intent.intended_effect}")
            confirm = input("  Confirm? (y/n): ").strip().lower()
            if confirm in ("y", "yes", ""):
                return intent
            print("  Order cancelled. Try again.")

        except Exception as e:
            print(f"  ⚠ Failed to parse: {e}")
            print("  Try rephrasing your command.")


def get_ai_action(
    conn: sqlite3.Connection,
    spec: ScenarioSpec,
    actor_id: str,
    turn_number: int,
    action_history: list[str],
    trace_id: str,
) -> ActionIntent:
    """Get an AI opponent's action."""
    actor = next(a for a in spec.actors if a.id == actor_id)
    estimates = get_actor_state_estimates(conn, actor_id)
    budget = spec.resource_budget[actor_id].domains

    # Get recent observations
    rows = conn.execute(
        "SELECT observations FROM observation_log WHERE actor_id=? ORDER BY turn_number DESC LIMIT 3",
        (actor_id,),
    ).fetchall()
    recent_obs = []
    for r in rows:
        recent_obs.extend(json.loads(r[0]))

    messages = build_ai_opponent_messages(
        actor=actor,
        state_estimates=estimates,
        observations=recent_obs,
        action_history=action_history,
        turn_number=turn_number,
        resource_budget=budget,
    )

    intent, _ = call_llm_structured(
        model=AI_MODEL,
        messages=messages,
        response_model=ActionIntent,
        task="wargame_ai_opponent",
        trace_id=trace_id,
        max_budget=0.5,
    )

    # Fix actor_id if AI got it wrong
    intent.actor_id = actor_id

    return intent


def adjudicate_action(
    conn: sqlite3.Connection,
    spec: ScenarioSpec,
    action: ActionIntent,
    turn_number: int,
    mechanical_deltas: dict[str, float],
    trace_id: str,
) -> tuple[dict, AdjudicationPacket]:
    """Run GM adjudication and resolve an action. Returns (chosen_outcome, packet)."""
    valid_var_ids = {sv.id for sv in spec.state_variables}
    valid_actor_ids = {a.id for a in spec.actors}

    state = get_all_variables(conn)
    dms = select_relevant_domain_models(spec, action)
    base_rates = compute_mechanical_base_rate(dms, action, state)

    messages = build_gm_messages(
        action=action,
        state=state,
        domain_models=dms,
        base_rates=base_rates,
        actor_ids=list(valid_actor_ids),
        variable_ids=list(valid_var_ids),
        mechanical_deltas=mechanical_deltas,
    )

    packet, _ = call_llm_structured(
        model=GM_MODEL,
        messages=messages,
        response_model=AdjudicationPacket,
        task="wargame_gm_adjudication",
        trace_id=trace_id,
        max_budget=1.0,
    )

    # Normalize
    prob_sum = sum(o.probability for o in packet.possible_outcomes)
    if abs(prob_sum - 1.0) > 0.001:
        packet = normalize_probabilities(packet)

    # Resolve
    outcomes_dicts = [
        {
            "outcome_id": o.outcome_id,
            "probability": o.probability,
            "state_transitions": [{"var_id": t.var_id, "delta": t.delta} for t in o.state_transitions],
            "narrative": o.narrative,
        }
        for o in packet.possible_outcomes
    ]
    chosen, rng_roll, seed = resolve_action(conn, outcomes_dicts, turn_number)

    # Apply transitions
    apply_action_transitions(conn, chosen["state_transitions"], turn_number)

    # Log
    action_id = generate_action_id()
    conn.execute(
        "INSERT INTO action_log (action_id, turn_number, actor_id, action_intent, adjudication_packet, realized_outcome_id, rng_roll) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (action_id, turn_number, action.actor_id, action.model_dump_json(), packet.model_dump_json(), chosen["outcome_id"], rng_roll),
    )

    return chosen, packet


def run_game(
    scenario_path: str,
    mode: str = "human_vs_ai",
    play_as: str = "actor_us",
    num_turns: int | None = None,
) -> None:
    """Run the main game loop."""
    spec = load_scenario(scenario_path)
    conn = init_db(spec)
    trace_id = f"wargame_{uuid.uuid4().hex[:8]}"
    total_turns = num_turns or spec.meta.turns
    actor_ids = [a.id for a in spec.actors]

    human_actor = play_as if mode != "ai_vs_ai" else None
    ai_actors = [a for a in actor_ids if a != human_actor] if mode == "human_vs_ai" else actor_ids if mode == "ai_vs_ai" else []

    # Track action history per actor for AI context
    action_histories: dict[str, list[str]] = {a: [] for a in actor_ids}

    print_banner(f"WARGAME: {spec.meta.name}")
    print(f"  Mode: {mode}")
    print(f"  Turns: {total_turns}")
    if human_actor:
        actor_name = next(a.name for a in spec.actors if a.id == human_actor)
        print(f"  You are: {actor_name}")
    print(f"  Trace ID: {trace_id}")

    for turn_idx in range(total_turns):
        # Run mechanical phases
        mech = run_mechanical_phases(conn)
        turn = mech.turn_number

        print_banner(f"TURN {turn} / {total_turns} ({spec.meta.time_per_turn})", "─")

        if mech.all_mechanical_deltas:
            print(f"\n  World dynamics this turn:")
            for var_id, delta in sorted(mech.all_mechanical_deltas.items()):
                if abs(delta) > 0.005:
                    print(f"    {var_id.replace('sv_', '')}: {delta:+.3f}")

        # Collect actions from all actors
        turn_actions: list[tuple[str, ActionIntent]] = []

        for actor_id in actor_ids:
            is_human = (actor_id == human_actor)

            # Show this actor's world view
            estimates = get_actor_state_estimates(conn, actor_id)
            actor_name = next(a.name for a in spec.actors if a.id == actor_id)

            if is_human:
                print_state_summary(estimates, f"Your intelligence picture ({actor_name})")
                action = get_human_action(conn, spec, actor_id, trace_id)
            elif actor_id in ai_actors:
                if mode != "ai_vs_ai":
                    print(f"\n  {actor_name} is deciding...")
                action = get_ai_action(conn, spec, actor_id, turn, action_histories[actor_id], trace_id)
                if mode == "ai_vs_ai":
                    print(f"\n  [{actor_name}] {action.action_category}: {action.intended_effect[:80]}")
            else:
                # Human vs human: other human's turn
                print_state_summary(estimates, f"Intelligence picture ({actor_name})")
                action = get_human_action(conn, spec, actor_id, trace_id)

            turn_actions.append((actor_id, action))
            action_histories[actor_id].append(
                f"Turn {turn}: [{action.action_category}] {action.intended_effect[:60]}"
            )

        # Adjudicate all actions
        for actor_id, action in turn_actions:
            actor_name = next(a.name for a in spec.actors if a.id == actor_id)
            print(f"\n  Adjudicating {actor_name}'s action...")

            chosen, packet = adjudicate_action(
                conn, spec, action, turn, mech.all_mechanical_deltas, trace_id,
            )

            print(f"  Result: {chosen['outcome_id'].upper()}")
            print(f"  {chosen['narrative']}")

        # Generate observation packets
        for actor_id in actor_ids:
            quality = compute_observation_quality(conn, actor_id, turn)

            # Collect narrative observations from adjudication results
            # For now, use the realized narrative from each action's outcome
            narratives = []
            for _, action in turn_actions:
                rows = conn.execute(
                    "SELECT realized_outcome_id, adjudication_packet FROM action_log WHERE turn_number=? AND actor_id=?",
                    (turn, action.actor_id),
                ).fetchall()
                for outcome_id, packet_json in rows:
                    pkt = json.loads(packet_json)
                    for obs_entry in pkt.get("observability", []):
                        if obs_entry.get("actor_id") == actor_id:
                            obs_for_outcome = obs_entry.get("observations", {}).get(outcome_id, [])
                            narratives.extend(obs_for_outcome)

            if not narratives:
                narratives = ["No significant developments observed this turn."]

            obs_packet = generate_observation_packet(conn, actor_id, turn, narratives, quality)

            is_human = (actor_id == human_actor)
            if is_human or mode == "ai_vs_ai":
                actor_name = next(a.name for a in spec.actors if a.id == actor_id)
                print(f"\n  📡 Intelligence briefing ({actor_name}):")
                for obs in obs_packet["observations"]:
                    print(f"    • {obs}")

        record_state_history(conn, turn)
        conn.commit()

    # End of game
    print_banner("GAME OVER")
    final = get_all_variables(conn)
    initial = spec.initial_state
    print(f"\n  Final state vs initial:")
    print(f"  {'Variable':<30} {'Initial':>8} {'Final':>8} {'Change':>8}")
    print(f"  {'-' * 60}")
    for var_id in sorted(final):
        init_val = initial.get(var_id, 0)
        change = final[var_id] - init_val
        if abs(change) > 0.01:
            print(f"  {var_id.replace('sv_', ''):<30} {init_val:>8.2f} {final[var_id]:>8.2f} {change:>+8.2f}")

    # Cost summary
    try:
        from llm_client import get_cost
        cost = get_cost(trace_id=trace_id)
        print(f"\n  Total LLM cost: ${cost:.4f}")
    except Exception:
        pass

    print(f"\n  Trace ID: {trace_id}")
    print(f"  Thanks for playing!\n")


def main() -> None:
    """Entry point for the CLI."""
    parser = argparse.ArgumentParser(description="Geopolitical Wargame CLI")
    parser.add_argument("scenario", type=str, help="Path to scenario YAML file")
    parser.add_argument("--mode", choices=["human_vs_ai", "human_vs_human", "ai_vs_ai"], default="human_vs_ai")
    parser.add_argument("--play-as", type=str, default="actor_us", help="Actor ID to play as (human_vs_ai mode)")
    parser.add_argument("--turns", type=int, default=None, help="Override number of turns")
    args = parser.parse_args()

    run_game(
        scenario_path=args.scenario,
        mode=args.mode,
        play_as=args.play_as,
        num_turns=args.turns,
    )


if __name__ == "__main__":
    main()
