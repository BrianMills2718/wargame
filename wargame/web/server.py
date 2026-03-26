"""FastAPI backend for the wargame web UI.

Wraps the game engine in an HTTP API. Manages a single active game session.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from llm_client import call_llm_structured

from wargame.ai_opponent import build_ai_opponent_messages
from wargame.engine import (
    apply_action_transitions,
    generate_action_id,
    get_all_variables,
    get_state_history,
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
from wargame.models import ActionIntent, AdjudicationPacket
from wargame.parser import build_parser_messages, validate_action_intent
from wargame.scenario import init_db, load_scenario

GM_MODEL = "gemini/gemini-2.5-flash"
PARSER_MODEL = "gemini/gemini-2.5-flash"
AI_MODEL = "gemini/gemini-2.5-flash"

app = FastAPI(title="Geopolitical Wargame")

# Game state (single session for now)
game = {
    "conn": None,
    "spec": None,
    "trace_id": None,
    "turn_log": [],
    "action_histories": {},
    "human_actor": None,
    "ai_actors": [],
}

WEB_DIR = Path(__file__).parent


class StartGameRequest(BaseModel):
    scenario_path: str = "scenarios/us_iran_2026.yaml"
    play_as: str = "actor_us"
    mode: str = "human_vs_ai"


class CommandRequest(BaseModel):
    directive: str


@app.get("/")
async def index():
    """Serve the main UI."""
    return FileResponse(WEB_DIR / "index.html")


@app.post("/api/start")
async def start_game(req: StartGameRequest):
    """Initialize a new game."""
    spec = load_scenario(req.scenario_path)
    conn = init_db(spec)
    trace_id = f"wargame_{uuid.uuid4().hex[:8]}"

    actor_ids = [a.id for a in spec.actors]
    human_actor = req.play_as if req.mode != "ai_vs_ai" else None
    ai_actors = [a for a in actor_ids if a != human_actor]

    game["conn"] = conn
    game["spec"] = spec
    game["trace_id"] = trace_id
    game["turn_log"] = []
    game["action_histories"] = {a: [] for a in actor_ids}
    game["human_actor"] = human_actor
    game["ai_actors"] = ai_actors
    game["mode"] = req.mode

    actor_names = {a.id: a.name for a in spec.actors}
    return {
        "status": "started",
        "scenario": spec.meta.name,
        "turns": spec.meta.turns,
        "play_as": human_actor,
        "actor_names": actor_names,
        "trace_id": trace_id,
        "state": get_all_variables(conn),
        "estimates": get_actor_state_estimates(conn, human_actor) if human_actor else get_all_variables(conn),
    }


@app.get("/api/state")
async def get_state():
    """Get the current game state from the human player's perspective."""
    if game["conn"] is None:
        raise HTTPException(400, "No game in progress")

    conn = game["conn"]
    human = game["human_actor"]

    estimates = get_actor_state_estimates(conn, human) if human else get_all_variables(conn)
    history = get_state_history(conn)

    # Format history for JSON
    hist_json = {}
    for var_id, points in history.items():
        hist_json[var_id] = [{"turn": t, "value": v} for t, v in points]

    return {
        "estimates": estimates,
        "history": hist_json,
        "turn_log": game["turn_log"],
    }


@app.post("/api/command")
async def submit_command(req: CommandRequest):
    """Submit a human player command and run a full turn."""
    if game["conn"] is None:
        raise HTTPException(400, "No game in progress")

    conn = game["conn"]
    spec = game["spec"]
    trace_id = game["trace_id"]
    human_actor = game["human_actor"]
    actor_ids = [a.id for a in spec.actors]
    valid_var_ids = {sv.id for sv in spec.state_variables}
    valid_actor_ids = {a.id for a in spec.actors}

    # Run mechanical phases
    mech = run_mechanical_phases(conn)
    turn = mech.turn_number

    turn_result = {
        "turn": turn,
        "mechanical_deltas": {k: round(v, 4) for k, v in mech.all_mechanical_deltas.items() if abs(v) > 0.005},
        "actions": [],
        "observations": {},
    }

    # Parse human command
    actor = next(a for a in spec.actors if a.id == human_actor)
    instruments = [{"id": i.id, "midfield": i.midfield, "target_vars": i.target_vars} for i in actor.instruments]
    budget = spec.resource_budget[human_actor].domains

    messages = build_parser_messages(req.directive, actor, instruments, budget)
    human_intent, _ = call_llm_structured(
        model=PARSER_MODEL, messages=messages, response_model=ActionIntent,
        task="wargame_parser", trace_id=trace_id, max_budget=0.5,
    )
    human_intent.actor_id = human_actor

    # Collect all actions (human + AI)
    turn_actions = [(human_actor, human_intent)]
    game["action_histories"][human_actor].append(
        f"Turn {turn}: [{human_intent.action_category}] {human_intent.intended_effect[:60]}"
    )

    # AI opponent actions
    for ai_id in game["ai_actors"]:
        ai_actor = next(a for a in spec.actors if a.id == ai_id)
        ai_estimates = get_actor_state_estimates(conn, ai_id)
        ai_budget = spec.resource_budget[ai_id].domains

        rows = conn.execute(
            "SELECT observations FROM observation_log WHERE actor_id=? ORDER BY turn_number DESC LIMIT 3",
            (ai_id,),
        ).fetchall()
        recent_obs = []
        for r in rows:
            recent_obs.extend(json.loads(r[0]))

        ai_messages = build_ai_opponent_messages(
            actor=ai_actor, state_estimates=ai_estimates, observations=recent_obs,
            action_history=game["action_histories"][ai_id], turn_number=turn,
            resource_budget=ai_budget,
        )
        ai_intent, _ = call_llm_structured(
            model=AI_MODEL, messages=ai_messages, response_model=ActionIntent,
            task="wargame_ai_opponent", trace_id=trace_id, max_budget=0.5,
        )
        ai_intent.actor_id = ai_id
        turn_actions.append((ai_id, ai_intent))
        game["action_histories"][ai_id].append(
            f"Turn {turn}: [{ai_intent.action_category}] {ai_intent.intended_effect[:60]}"
        )

    # Adjudicate all actions
    for actor_id, action in turn_actions:
        state = get_all_variables(conn)
        dms = select_relevant_domain_models(spec, action)
        base_rates = compute_mechanical_base_rate(dms, action, state)

        gm_messages = build_gm_messages(
            action=action, state=state, domain_models=dms, base_rates=base_rates,
            actor_ids=list(valid_actor_ids), variable_ids=list(valid_var_ids),
            mechanical_deltas=mech.all_mechanical_deltas,
        )
        packet, _ = call_llm_structured(
            model=GM_MODEL, messages=gm_messages, response_model=AdjudicationPacket,
            task="wargame_gm_adjudication", trace_id=trace_id, max_budget=1.0,
        )

        prob_sum = sum(o.probability for o in packet.possible_outcomes)
        if abs(prob_sum - 1.0) > 0.001:
            packet = normalize_probabilities(packet)

        outcomes_dicts = [
            {"outcome_id": o.outcome_id, "probability": o.probability,
             "state_transitions": [{"var_id": t.var_id, "delta": t.delta} for t in o.state_transitions],
             "narrative": o.narrative}
            for o in packet.possible_outcomes
        ]
        chosen, rng_roll, seed = resolve_action(conn, outcomes_dicts, turn)
        apply_action_transitions(conn, chosen["state_transitions"], turn)

        action_id = generate_action_id()
        conn.execute(
            "INSERT INTO action_log (action_id, turn_number, actor_id, action_intent, adjudication_packet, realized_outcome_id, rng_roll) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (action_id, turn, actor_id, action.model_dump_json(), packet.model_dump_json(), chosen["outcome_id"], rng_roll),
        )

        actor_name = next(a.name for a in spec.actors if a.id == actor_id)
        is_human = (actor_id == human_actor)
        turn_result["actions"].append({
            "actor": actor_name,
            "actor_id": actor_id,
            "is_human": is_human,
            "category": action.action_category,
            "intent": action.intended_effect,
            "outcome": chosen["outcome_id"],
            "narrative": chosen["narrative"],
        })

    # Generate observation packets
    for actor_id in actor_ids:
        quality = compute_observation_quality(conn, actor_id, turn)
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
        turn_result["observations"][actor_id] = narratives

    record_state_history(conn, turn)
    conn.commit()

    game["turn_log"].append(turn_result)

    # Return updated state
    estimates = get_actor_state_estimates(conn, human_actor) if human_actor else get_all_variables(conn)
    history = get_state_history(conn)
    hist_json = {}
    for var_id, points in history.items():
        hist_json[var_id] = [{"turn": t, "value": v} for t, v in points]

    return {
        "turn_result": turn_result,
        "estimates": estimates,
        "history": hist_json,
    }
