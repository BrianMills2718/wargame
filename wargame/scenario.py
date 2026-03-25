"""Load a scenario YAML into an in-memory ScenarioSpec and initialize SQLite."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import yaml

from wargame.models import ScenarioSpec


def load_scenario(path: str | Path) -> ScenarioSpec:
    """Parse a scenario YAML file into a validated ScenarioSpec."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return ScenarioSpec(**raw)


def init_db(spec: ScenarioSpec, db_path: str = ":memory:") -> sqlite3.Connection:
    """Create and populate the SQLite database from a scenario spec.

    Returns an open connection with all tables created and populated.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_tables(conn)
    _populate(conn, spec)
    conn.commit()
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    """Create all game tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS actors (
            actor_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS state_variables (
            var_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            domain TEXT NOT NULL,
            timescale TEXT NOT NULL,
            range_min REAL NOT NULL,
            range_max REAL NOT NULL,
            current_value REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS causal_edges (
            edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_var TEXT NOT NULL REFERENCES state_variables(var_id),
            target_var TEXT NOT NULL REFERENCES state_variables(var_id),
            effect REAL NOT NULL,
            lag INTEGER NOT NULL DEFAULT 0,
            actor_scope TEXT,
            UNIQUE(source_var, target_var, actor_scope)
        );

        CREATE TABLE IF NOT EXISTS variable_dynamics (
            var_id TEXT PRIMARY KEY REFERENCES state_variables(var_id),
            decay_rate REAL,
            momentum REAL
        );

        CREATE TABLE IF NOT EXISTS pending_effects (
            effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_var TEXT NOT NULL REFERENCES state_variables(var_id),
            delta REAL NOT NULL,
            applies_on_turn INTEGER NOT NULL,
            source_action_id TEXT,
            actor_scope TEXT
        );

        CREATE TABLE IF NOT EXISTS state_estimates (
            actor_id TEXT NOT NULL REFERENCES actors(actor_id),
            var_id TEXT NOT NULL REFERENCES state_variables(var_id),
            estimated_value REAL NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.5,
            last_updated_turn INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (actor_id, var_id)
        );

        CREATE TABLE IF NOT EXISTS instruments (
            inst_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL REFERENCES actors(actor_id),
            name TEXT NOT NULL,
            midfield_tags TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS active_actions (
            active_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_template TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES actors(actor_id),
            started_turn INTEGER NOT NULL,
            duration INTEGER NOT NULL,
            current_step INTEGER NOT NULL DEFAULT 0,
            target_var TEXT NOT NULL REFERENCES state_variables(var_id),
            effects_per_turn TEXT NOT NULL,
            resource_cost_per_turn INTEGER NOT NULL,
            domain TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS action_log (
            action_id TEXT PRIMARY KEY,
            turn_number INTEGER NOT NULL,
            actor_id TEXT NOT NULL REFERENCES actors(actor_id),
            action_intent TEXT NOT NULL,
            adjudication_packet TEXT NOT NULL,
            realized_outcome_id TEXT NOT NULL,
            rng_roll REAL NOT NULL,
            timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS observation_log (
            obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_number INTEGER NOT NULL,
            actor_id TEXT NOT NULL REFERENCES actors(actor_id),
            observations TEXT NOT NULL,
            state_estimate_updates TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS resource_budgets (
            actor_id TEXT NOT NULL REFERENCES actors(actor_id),
            turn_number INTEGER NOT NULL,
            domain TEXT NOT NULL,
            allocated INTEGER NOT NULL,
            spent INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (actor_id, turn_number, domain)
        );

        CREATE TABLE IF NOT EXISTS state_history (
            var_id TEXT NOT NULL REFERENCES state_variables(var_id),
            turn_number INTEGER NOT NULL,
            value REAL NOT NULL,
            PRIMARY KEY (var_id, turn_number)
        );

        CREATE TABLE IF NOT EXISTS game_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)


def _populate(conn: sqlite3.Connection, spec: ScenarioSpec) -> None:
    """Insert scenario data into the database."""
    # Actors
    for actor in spec.actors:
        conn.execute(
            "INSERT INTO actors (actor_id, name, type) VALUES (?, ?, ?)",
            (actor.id, actor.name, actor.type),
        )
        # Instruments
        for inst in actor.instruments:
            conn.execute(
                "INSERT INTO instruments (inst_id, actor_id, name, midfield_tags) VALUES (?, ?, ?, ?)",
                (inst.id, actor.id, inst.id, json.dumps(inst.midfield)),
            )

    # State variables
    for sv in spec.state_variables:
        initial = spec.initial_state.get(sv.id, (sv.range[0] + sv.range[1]) / 2)
        conn.execute(
            "INSERT INTO state_variables (var_id, name, type, domain, timescale, range_min, range_max, current_value) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sv.id, sv.id, sv.type, sv.domain, sv.timescale, sv.range[0], sv.range[1], initial),
        )

    # Initial state estimates: each actor starts with the canonical values (perfect info at start)
    for actor in spec.actors:
        for sv in spec.state_variables:
            initial = spec.initial_state.get(sv.id, (sv.range[0] + sv.range[1]) / 2)
            conn.execute(
                "INSERT INTO state_estimates (actor_id, var_id, estimated_value, confidence, last_updated_turn) VALUES (?, ?, ?, ?, ?)",
                (actor.id, sv.id, initial, 0.5, 0),
            )

    # Causal edges
    for edge in spec.causal_edges:
        conn.execute(
            "INSERT INTO causal_edges (source_var, target_var, effect, lag, actor_scope) VALUES (?, ?, ?, ?, ?)",
            (edge.source, edge.target, edge.effect, edge.lag, edge.actor or None),
        )

    # Variable dynamics
    for var_id, dyn in spec.variable_dynamics.items():
        conn.execute(
            "INSERT INTO variable_dynamics (var_id, decay_rate, momentum) VALUES (?, ?, ?)",
            (var_id, dyn.decay_rate, dyn.momentum),
        )

    # Record turn 0 in state history
    for sv in spec.state_variables:
        initial = spec.initial_state.get(sv.id, (sv.range[0] + sv.range[1]) / 2)
        conn.execute(
            "INSERT INTO state_history (var_id, turn_number, value) VALUES (?, ?, ?)",
            (sv.id, 0, initial),
        )

    # Initialize game state
    conn.execute("INSERT INTO game_state (key, value) VALUES (?, ?)", ("current_turn", "0"))

    # Initialize resource budgets for turn 1
    for actor_id, budget in spec.resource_budget.items():
        for domain, amount in budget.domains.items():
            conn.execute(
                "INSERT INTO resource_budgets (actor_id, turn_number, domain, allocated, spent) VALUES (?, ?, ?, ?, ?)",
                (actor_id, 1, domain, amount, 0),
            )
