"""The per-turn steps shared by every front end (CLI and web).

The CLI and the web server used to carry their own copies of adjudication and
observation generation, and the copies drifted: the web path stopped validating
human orders the CLI validated. Anything that decides what reaches game state
lives here, once.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Callable

from wargame.engine import (
    apply_action_transitions,
    generate_action_id,
    get_all_variables,
    get_current_turn,
    resolve_action,
)
from wargame.fog import compute_observation_quality, generate_observation_packet
from wargame.gm import (
    adjudication_band_issues,
    adjudication_structure_issues,
    clamp_to_base_rates,
    compute_mechanical_base_rate,
    normalize_probabilities,
    select_relevant_domain_models,
)
from wargame.models import ActionIntent, AdjudicationPacket, ScenarioSpec


def turns_remaining(conn: sqlite3.Connection, total_turns: int) -> int:
    """How many turns may still be played; 0 means the game is over."""
    return max(0, total_turns - get_current_turn(conn))


def adjudicate_action(
    conn: sqlite3.Connection,
    spec: ScenarioSpec,
    action: ActionIntent,
    turn_number: int,
    mechanical_deltas: dict[str, float],
    gm_session,
    warn: Callable[[str], None] = print,
) -> tuple[dict, AdjudicationPacket]:
    """Run GM adjudication and resolve an action. Returns (chosen_outcome, packet).

    Structural defects (unknown variable or actor ids) are not repairable and
    raise before anything is written. Only probability-band violations
    (ADR-001 anti-god-moding) are repaired, by clamping.
    """
    state = get_all_variables(conn)
    dms = select_relevant_domain_models(spec, action)
    base_rates = compute_mechanical_base_rate(dms, action, state)

    packet = gm_session.adjudicate(
        action=action,
        state=state,
        relevant_domain_models=dms,
        base_rates=base_rates,
        turn_number=turn_number,
        mechanical_deltas=mechanical_deltas,
    )

    structural = adjudication_structure_issues(
        packet, {sv.id for sv in spec.state_variables}, {a.id for a in spec.actors},
    )
    if structural:
        raise ValueError(f"GM adjudication is structurally invalid: {'; '.join(structural)}")

    prob_sum = sum(o.probability for o in packet.possible_outcomes)
    if abs(prob_sum - 1.0) > 0.001:
        packet = normalize_probabilities(packet)

    band = adjudication_band_issues(packet, base_rates)
    if band:
        warn(f"  ⚠ GM adjudication outside its band, clamping: {'; '.join(band)}")
        packet = clamp_to_base_rates(packet, base_rates)

    outcomes_dicts = [
        {
            "outcome_id": o.outcome_id,
            "probability": o.probability,
            "state_transitions": [{"var_id": t.var_id, "delta": t.delta} for t in o.state_transitions],
            "narrative": o.narrative,
        }
        for o in packet.possible_outcomes
    ]
    chosen, rng_roll, _seed = resolve_action(conn, outcomes_dicts, turn_number)
    apply_action_transitions(conn, chosen["state_transitions"], turn_number)

    conn.execute(
        "INSERT INTO action_log (action_id, turn_number, actor_id, action_intent, adjudication_packet, realized_outcome_id, rng_roll) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (generate_action_id(), turn_number, action.actor_id, action.model_dump_json(),
         packet.model_dump_json(), chosen["outcome_id"], rng_roll),
    )
    return chosen, packet


def generate_observations(
    conn: sqlite3.Connection,
    spec: ScenarioSpec,
    turn_number: int,
    turn_actions: list[tuple[str, ActionIntent]],
) -> dict[str, dict]:
    """Build and store each actor's observation packet for the turn.

    Returns {actor_id: observation packet}.
    """
    packets = {}
    for actor in spec.actors:
        actor_id = actor.id
        quality = compute_observation_quality(conn, actor_id, turn_number)
        narratives = []
        for _, action in turn_actions:
            rows = conn.execute(
                "SELECT realized_outcome_id, adjudication_packet FROM action_log WHERE turn_number=? AND actor_id=?",
                (turn_number, action.actor_id),
            ).fetchall()
            for outcome_id, packet_json in rows:
                pkt = json.loads(packet_json)
                for obs_entry in pkt.get("observability", []):
                    if obs_entry.get("actor_id") == actor_id:
                        narratives.extend(
                            note
                            for entry in obs_entry.get("observations", [])
                            if entry.get("outcome_id") == outcome_id
                            for note in entry.get("notes", [])
                        )

        if not narratives:
            narratives = ["No significant developments observed this turn."]

        packets[actor_id] = generate_observation_packet(conn, actor_id, turn_number, narratives, quality)
    return packets
