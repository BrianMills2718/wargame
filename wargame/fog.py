"""Fog of war — observation filtering and per-actor state estimate updates.

Enforces the information barrier: actors only see what they're allowed to see.
Perceptual variables are visible only to their holder. Other variables are
observed with noise proportional to the actor's intelligence investment.

State estimates update via a simple Bayesian-inspired rule:
  new_estimate = old_estimate + observation_quality * (canonical - old_estimate)
where observation_quality depends on intelligence resource allocation.
"""

from __future__ import annotations

import sqlite3

from wargame.engine import get_all_variables, get_variable_meta


def get_actor_state_estimates(conn: sqlite3.Connection, actor_id: str) -> dict[str, float]:
    """Return all state estimates for a specific actor."""
    rows = conn.execute(
        "SELECT var_id, estimated_value FROM state_estimates WHERE actor_id=?",
        (actor_id,),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def get_observable_variables(
    conn: sqlite3.Connection,
    actor_id: str,
    all_actor_ids: list[str],
) -> set[str]:
    """Determine which variables an actor can observe.

    Rules:
    - Non-perceptual variables: visible to all actors (with noise)
    - Perceptual variables: visible ONLY to the holding actor
    """
    observable = set()
    rows = conn.execute(
        "SELECT var_id, type FROM state_variables"
    ).fetchall()

    for var_id, var_type in rows:
        if var_type == "perceptual":
            # Check if this actor holds this perceptual variable
            # Convention: perceptual vars for actor_iran contain "iran" or have holder metadata
            # More robust: check the scenario spec's holder field
            # For now, use a heuristic based on the causal_edges actor_scope
            scope = conn.execute(
                "SELECT actor_scope FROM causal_edges WHERE target_var=? AND actor_scope IS NOT NULL LIMIT 1",
                (var_id,),
            ).fetchone()
            if scope and scope[0] == actor_id:
                observable.add(var_id)
            elif not scope:
                # No scoped edge — might be globally visible perceptual var
                # Check if var name contains actor hint
                if actor_id.replace("actor_", "") in var_id:
                    observable.add(var_id)
        else:
            observable.add(var_id)

    return observable


def compute_observation_quality(
    conn: sqlite3.Connection,
    actor_id: str,
    turn_number: int,
    base_quality: float = 0.3,
) -> float:
    """Compute observation quality for an actor based on intelligence investment.

    Higher intelligence resource allocation → better observation quality.
    Returns a value between 0.0 (blind) and 1.0 (perfect).
    """
    # Check intelligence budget allocation for this turn
    row = conn.execute(
        "SELECT allocated, spent FROM resource_budgets WHERE actor_id=? AND turn_number=? AND domain='intelligence'",
        (actor_id, turn_number),
    ).fetchone()

    if row is None:
        return base_quality

    allocated = row[0]
    # More intelligence allocation → better quality
    # Scale: 0 allocated → base_quality, 3+ allocated → base_quality + 0.4
    quality = base_quality + min(allocated, 3) * 0.13
    return min(1.0, quality)


def update_state_estimates(
    conn: sqlite3.Connection,
    actor_id: str,
    turn_number: int,
    observation_quality: float,
) -> dict[str, float]:
    """Update an actor's state estimates via Bayesian-inspired rule.

    For each observable variable:
      new_estimate = old_estimate + quality * (canonical - old_estimate)

    Returns dict of {var_id: new_estimate} for variables that changed.

    Per ADR-002: deception actions can corrupt observation_quality to
    near-zero or negative, making updates push AWAY from truth.
    """
    canonical = get_all_variables(conn)
    observable = get_observable_variables(conn, actor_id, [])
    updates = {}

    for var_id in observable:
        if var_id not in canonical:
            continue

        row = conn.execute(
            "SELECT estimated_value, confidence FROM state_estimates WHERE actor_id=? AND var_id=?",
            (actor_id, var_id),
        ).fetchone()

        if row is None:
            continue

        old_estimate = row[0]
        old_confidence = row[1]

        true_value = canonical[var_id]
        # Bayesian update: pull estimate toward truth proportional to quality
        new_estimate = old_estimate + observation_quality * (true_value - old_estimate)
        # Confidence increases with observation quality
        new_confidence = min(1.0, old_confidence + observation_quality * 0.1)

        conn.execute(
            "UPDATE state_estimates SET estimated_value=?, confidence=?, last_updated_turn=? WHERE actor_id=? AND var_id=?",
            (new_estimate, new_confidence, turn_number, actor_id, var_id),
        )

        if abs(new_estimate - old_estimate) > 0.001:
            updates[var_id] = new_estimate

    return updates


def generate_observation_packet(
    conn: sqlite3.Connection,
    actor_id: str,
    turn_number: int,
    narrative_observations: list[str],
    observation_quality: float,
) -> dict:
    """Generate a complete observation packet for an actor.

    Combines narrative observations (from GM) with state estimate updates.
    Logs to observation_log.
    """
    import json

    # Update state estimates
    estimate_updates = update_state_estimates(conn, actor_id, turn_number, observation_quality)

    # Build packet
    packet = {
        "turn_number": turn_number,
        "actor_id": actor_id,
        "observations": narrative_observations,
        "state_estimate_updates": estimate_updates,
    }

    # Log
    conn.execute(
        "INSERT INTO observation_log (turn_number, actor_id, observations, state_estimate_updates) VALUES (?, ?, ?, ?)",
        (turn_number, actor_id, json.dumps(narrative_observations), json.dumps(estimate_updates)),
    )

    return packet


def check_information_barrier(
    conn: sqlite3.Connection,
    actor_id: str,
    observation_packet: dict,
    all_actor_ids: list[str],
) -> list[str]:
    """Verify no information leaks in an observation packet.

    Checks that:
    1. No state estimate updates reference variables the actor can't observe
    2. No perceptual variables of OTHER actors are included

    Returns list of violations (empty = clean).
    """
    observable = get_observable_variables(conn, actor_id, all_actor_ids)
    violations = []

    for var_id in observation_packet.get("state_estimate_updates", {}):
        if var_id not in observable:
            violations.append(f"LEAK: {actor_id} received update for non-observable variable {var_id}")

    return violations
