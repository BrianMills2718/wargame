"""Causal state engine — the mechanical layer of the wargame.

All operations here are deterministic (or stochastic via RNG). No LLM calls.
Responsible for: causal propagation, decay/momentum, clamping, multi-turn
action progression, base rate computation, state history recording.
"""

from __future__ import annotations

import json
import random
import sqlite3
import uuid
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_current_turn(conn: sqlite3.Connection) -> int:
    """Return the current turn number."""
    row = conn.execute("SELECT value FROM game_state WHERE key='current_turn'").fetchone()
    return int(row[0])


def get_variable(conn: sqlite3.Connection, var_id: str) -> float:
    """Return the canonical value of a state variable."""
    row = conn.execute("SELECT current_value FROM state_variables WHERE var_id=?", (var_id,)).fetchone()
    if row is None:
        raise KeyError(f"Unknown variable: {var_id}")
    return row[0]


def get_all_variables(conn: sqlite3.Connection) -> dict[str, float]:
    """Return all canonical state variable values."""
    rows = conn.execute("SELECT var_id, current_value FROM state_variables").fetchall()
    return {r[0]: r[1] for r in rows}


def get_variable_meta(conn: sqlite3.Connection, var_id: str) -> dict:
    """Return metadata for a state variable."""
    row = conn.execute(
        "SELECT var_id, type, domain, timescale, range_min, range_max, current_value FROM state_variables WHERE var_id=?",
        (var_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Unknown variable: {var_id}")
    return {
        "var_id": row[0], "type": row[1], "domain": row[2],
        "timescale": row[3], "range_min": row[4], "range_max": row[5],
        "current_value": row[6],
    }


# ---------------------------------------------------------------------------
# State mutation
# ---------------------------------------------------------------------------

def apply_delta(conn: sqlite3.Connection, var_id: str, delta: float, *, respect_rate_limits: bool = True) -> float:
    """Apply a delta to a state variable, enforcing clamping and rate limits.

    Returns the actual delta applied (may differ from requested due to clamping/limits).
    """
    meta = get_variable_meta(conn, var_id)
    current = meta["current_value"]

    # Rate limit: structural variables limited to ±0.05 per application
    if respect_rate_limits and meta["type"] == "structural":
        delta = max(-0.05, min(0.05, delta))

    new_value = current + delta
    # Clamp to range
    new_value = max(meta["range_min"], min(meta["range_max"], new_value))
    actual_delta = new_value - current

    conn.execute("UPDATE state_variables SET current_value=? WHERE var_id=?", (new_value, var_id))
    return actual_delta


def apply_decay_and_momentum(conn: sqlite3.Connection) -> dict[str, float]:
    """Apply per-variable decay and momentum. Returns deltas applied.

    Decay moves a variable toward 0 (or its range minimum for positive-only vars).
    Momentum is an autonomous per-turn change (e.g., nuclear program advancing).
    """
    deltas = {}
    rows = conn.execute(
        "SELECT vd.var_id, vd.decay_rate, vd.momentum FROM variable_dynamics vd"
    ).fetchall()

    for var_id, decay_rate, momentum in rows:
        total_delta = 0.0

        if decay_rate is not None:
            current = get_variable(conn, var_id)
            # Decay toward 0 (or range_min if positive-only)
            if current > 0:
                d = max(decay_rate, -current)  # don't overshoot past 0
            elif current < 0:
                d = min(-decay_rate, -current)
            else:
                d = 0.0
            total_delta += d

        if momentum is not None:
            total_delta += momentum

        if total_delta != 0.0:
            actual = apply_delta(conn, var_id, total_delta, respect_rate_limits=False)
            if actual != 0.0:
                deltas[var_id] = actual

    return deltas


def propagate_causal_edges(
    conn: sqlite3.Connection,
    source_deltas: dict[str, float],
    current_turn: int,
    source_action_id: str | None = None,
) -> dict[str, float]:
    """Propagate causal effects from source variable changes.

    Immediate effects (lag=0) are applied now. Lagged effects are queued
    in pending_effects. Returns the immediate deltas applied.
    """
    immediate_deltas: dict[str, float] = {}

    for source_var, source_delta in source_deltas.items():
        edges = conn.execute(
            "SELECT target_var, effect, lag, actor_scope FROM causal_edges WHERE source_var=?",
            (source_var,),
        ).fetchall()

        for target_var, effect, lag, actor_scope in edges:
            propagated_delta = effect * source_delta

            if lag == 0:
                actual = apply_delta(conn, target_var, propagated_delta)
                if actual != 0.0:
                    immediate_deltas[target_var] = immediate_deltas.get(target_var, 0.0) + actual
            else:
                # Queue for future turn
                conn.execute(
                    "INSERT INTO pending_effects (target_var, delta, applies_on_turn, source_action_id, actor_scope) VALUES (?, ?, ?, ?, ?)",
                    (target_var, propagated_delta, current_turn + lag, source_action_id, actor_scope),
                )

    return immediate_deltas


def apply_pending_effects(conn: sqlite3.Connection, current_turn: int) -> dict[str, float]:
    """Apply any pending lagged causal effects for this turn.

    Returns deltas applied.
    """
    rows = conn.execute(
        "SELECT effect_id, target_var, delta FROM pending_effects WHERE applies_on_turn=?",
        (current_turn,),
    ).fetchall()

    deltas: dict[str, float] = {}
    for effect_id, target_var, delta in rows:
        actual = apply_delta(conn, target_var, delta)
        if actual != 0.0:
            deltas[target_var] = deltas.get(target_var, 0.0) + actual

    # Clean up applied effects
    conn.execute("DELETE FROM pending_effects WHERE applies_on_turn=?", (current_turn,))

    return deltas


# ---------------------------------------------------------------------------
# Multi-turn actions
# ---------------------------------------------------------------------------

def advance_multi_turn_actions(conn: sqlite3.Connection, current_turn: int) -> dict[str, float]:
    """Advance all active multi-turn actions by one step.

    Per ADR-002: checks disruption conditions. If the target variable has moved
    by >0.2 since the action started (due to opponent actions or other dynamics),
    the remaining effects are halved.

    Returns deltas applied.
    """
    deltas: dict[str, float] = {}

    rows = conn.execute(
        "SELECT active_id, action_template, actor_id, current_step, duration, target_var, effects_per_turn, resource_cost_per_turn, domain, completed, started_turn "
        "FROM active_actions WHERE completed=0"
    ).fetchall()

    for active_id, template, actor_id, step, duration, target_var, effects_json, cost, domain, _, started_turn in rows:
        effects = json.loads(effects_json)

        if step >= len(effects):
            # Action complete
            conn.execute("UPDATE active_actions SET completed=1 WHERE active_id=?", (active_id,))
            continue

        # Disruption check (ADR-002): if target_var has moved significantly since
        # the action started, halve remaining effects
        disruption_factor = 1.0
        start_value = conn.execute(
            "SELECT value FROM state_history WHERE var_id=? AND turn_number=?",
            (target_var, started_turn),
        ).fetchone()
        if start_value is not None:
            current_value = get_variable(conn, target_var)
            drift = abs(current_value - start_value[0])
            if drift > 0.2:
                disruption_factor = 0.5

        # Apply this step's effect (potentially disrupted)
        effect = effects[step] * disruption_factor
        actual = apply_delta(conn, target_var, effect)
        if actual != 0.0:
            deltas[target_var] = deltas.get(target_var, 0.0) + actual

        # Advance step
        conn.execute(
            "UPDATE active_actions SET current_step=? WHERE active_id=?",
            (step + 1, active_id),
        )

        # Mark completed if final step
        if step + 1 >= len(effects) and str(duration) != "ongoing":
            conn.execute("UPDATE active_actions SET completed=1 WHERE active_id=?", (active_id,))

    return deltas


def start_multi_turn_action(
    conn: sqlite3.Connection,
    template_name: str,
    actor_id: str,
    current_turn: int,
    target_var: str,
    effects_per_turn: list[float],
    duration: int,
    resource_cost_per_turn: int,
    domain: str,
) -> int:
    """Start a new multi-turn action. Returns the active_id."""
    cursor = conn.execute(
        "INSERT INTO active_actions (action_template, actor_id, started_turn, duration, current_step, target_var, effects_per_turn, resource_cost_per_turn, domain, completed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (template_name, actor_id, current_turn, duration, 0, target_var, json.dumps(effects_per_turn), resource_cost_per_turn, domain, 0),
    )
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# State history
# ---------------------------------------------------------------------------

def record_state_history(conn: sqlite3.Connection, turn_number: int) -> None:
    """Snapshot all current variable values for this turn."""
    rows = conn.execute("SELECT var_id, current_value FROM state_variables").fetchall()
    for var_id, value in rows:
        conn.execute(
            "INSERT OR REPLACE INTO state_history (var_id, turn_number, value) VALUES (?, ?, ?)",
            (var_id, turn_number, value),
        )


def get_state_history(conn: sqlite3.Connection) -> dict[str, list[tuple[int, float]]]:
    """Return full state history as {var_id: [(turn, value), ...]}."""
    rows = conn.execute("SELECT var_id, turn_number, value FROM state_history ORDER BY var_id, turn_number").fetchall()
    history: dict[str, list[tuple[int, float]]] = {}
    for var_id, turn, value in rows:
        history.setdefault(var_id, []).append((turn, value))
    return history


# ---------------------------------------------------------------------------
# Turn management
# ---------------------------------------------------------------------------

def advance_turn(conn: sqlite3.Connection) -> int:
    """Advance to the next turn. Returns the new turn number."""
    current = get_current_turn(conn)
    new_turn = current + 1
    conn.execute("UPDATE game_state SET value=? WHERE key='current_turn'", (str(new_turn),))
    return new_turn


@dataclass
class TurnPhaseResult:
    """Results from running the mechanical phases of a turn."""
    turn_number: int
    decay_deltas: dict[str, float]
    multi_turn_deltas: dict[str, float]
    pending_deltas: dict[str, float]
    all_mechanical_deltas: dict[str, float]


def run_mechanical_phases(conn: sqlite3.Connection) -> TurnPhaseResult:
    """Run all mechanical phases for the current turn (steps 1-3 of the turn loop).

    1. Apply decay/momentum
    2. Advance multi-turn actions
    3. Apply pending lagged effects

    Returns a TurnPhaseResult with all deltas applied.
    """
    turn = advance_turn(conn)

    # Phase 1: Decay and momentum
    decay_deltas = apply_decay_and_momentum(conn)

    # Phase 2: Multi-turn action progression
    mt_deltas = advance_multi_turn_actions(conn, turn)

    # Phase 3: Pending lagged causal effects
    pending_deltas = apply_pending_effects(conn, turn)

    # Propagate causal effects from all mechanical changes
    all_mechanical = {}
    for d in [decay_deltas, mt_deltas, pending_deltas]:
        for k, v in d.items():
            all_mechanical[k] = all_mechanical.get(k, 0.0) + v

    if all_mechanical:
        cascaded = propagate_causal_edges(conn, all_mechanical, turn)
        for k, v in cascaded.items():
            all_mechanical[k] = all_mechanical.get(k, 0.0) + v

    # Record state snapshot
    record_state_history(conn, turn)

    conn.commit()

    return TurnPhaseResult(
        turn_number=turn,
        decay_deltas=decay_deltas,
        multi_turn_deltas=mt_deltas,
        pending_deltas=pending_deltas,
        all_mechanical_deltas=all_mechanical,
    )


# ---------------------------------------------------------------------------
# RNG / Resolution
# ---------------------------------------------------------------------------

def resolve_action(
    conn: sqlite3.Connection,
    outcomes: list[dict],
    turn_number: int,
    seed: int | None = None,
) -> tuple[dict, float]:
    """Roll RNG against outcome probabilities. Returns (chosen_outcome, rng_roll).

    outcomes: list of dicts with at least 'outcome_id', 'probability', 'state_transitions'.
    """
    if seed is not None:
        rng = random.Random(seed)
    else:
        rng = random.Random()

    ids = [o["outcome_id"] for o in outcomes]
    weights = [o["probability"] for o in outcomes]
    roll = rng.random()

    # Select outcome
    chosen_id = rng.choices(ids, weights=weights, k=1)[0]
    chosen = next(o for o in outcomes if o["outcome_id"] == chosen_id)

    return chosen, roll


def apply_action_transitions(
    conn: sqlite3.Connection,
    transitions: list[dict],
    turn_number: int,
    action_id: str | None = None,
) -> dict[str, float]:
    """Apply state transitions from a resolved action.

    Returns the deltas actually applied (after clamping/limits).
    Also propagates causal effects.
    """
    direct_deltas: dict[str, float] = {}
    for t in transitions:
        actual = apply_delta(conn, t["var_id"], t["delta"])
        if actual != 0.0:
            direct_deltas[t["var_id"]] = direct_deltas.get(t["var_id"], 0.0) + actual

    # Propagate causal effects from action-caused changes
    if direct_deltas:
        cascaded = propagate_causal_edges(conn, direct_deltas, turn_number, action_id)
        for k, v in cascaded.items():
            direct_deltas[k] = direct_deltas.get(k, 0.0) + v

    # Record updated state
    record_state_history(conn, turn_number)
    conn.commit()

    return direct_deltas


def generate_action_id() -> str:
    """Generate a unique action ID (engine-assigned, not LLM-generated)."""
    return f"act_{uuid.uuid4().hex[:8]}"
