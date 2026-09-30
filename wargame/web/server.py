"""FastAPI backend for the wargame web UI.

Wraps the game engine in an HTTP API. Manages a single active game session.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import shutil
import tempfile
import uuid
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from llm_client import call_llm_structured

from wargame.ai_opponent import build_ai_opponent_messages, request_valid_ai_action
from wargame.engine import (
    get_all_variables,
    get_state_history,
    record_state_history,
    run_mechanical_phases,
)
from wargame.fog import (
    get_actor_state_estimates,
)
from wargame.gm_session import GMSession
from wargame.models import ActionIntent
from wargame.parser import build_parser_messages, validate_action_intent
from wargame.scenario import init_db, load_scenario
import wargame.web.sessions as sessions_mod
from wargame.web.sessions import (
    SessionMiddleware,
    TEMP_DIR_PREFIX,
    discard_game,
    game,
    public_max_turns,
    public_mode,
    resolve_bundled_scenario,
    sweep_stale_temp_dirs,
)
from wargame.turn import adjudicate_action, atomic_turn, generate_observations, turns_remaining
from wargame.config import (
    gm_call_defaults,
    AI_MAX_BUDGET,
    AI_MODEL,
    DEFAULT_DB_DIR,
    GM_MAX_BUDGET,
    GM_MODEL,
    LLM_CALL_DEFAULTS,
    PARSER_MAX_BUDGET,
    PARSER_MODEL,
)

@contextlib.asynccontextmanager
async def _lifespan(_app):
    yield
    # uvicorn re-raises SIGTERM after shutdown, which skips atexit, so clean up
    # here: close every session and remove this process's temp db dir.
    global _public_db_dir
    sessions_mod.STORE.close_all()
    if _public_db_dir is not None:
        shutil.rmtree(_public_db_dir, ignore_errors=True)
        _public_db_dir = None


app = FastAPI(title="Geopolitical Wargame", lifespan=_lifespan)

# Per-visitor game state: `game` resolves to the current request's session dict
# (see wargame/web/sessions.py). Same keys as before.
app.add_middleware(SessionMiddleware)

_public_db_dir: str | None = None


def _public_db_path(trace_id: str) -> str:
    """Server-chosen db path in a per-process temp dir, named only from the trace id."""
    global _public_db_dir
    if _public_db_dir is None:
        sweep_stale_temp_dirs()  # leftovers from earlier hard-killed processes
        _public_db_dir = tempfile.mkdtemp(prefix=TEMP_DIR_PREFIX)
        atexit.register(shutil.rmtree, _public_db_dir, ignore_errors=True)
    return str(Path(_public_db_dir) / f"{trace_id}.sqlite")


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    if public_mode():
        return JSONResponse({"detail": "The request was not understood."}, status_code=400)
    return await request_validation_exception_handler(request, exc)


WEB_DIR = Path(__file__).parent


def _find_actor(spec, actor_id):
    """Safely find an actor by ID. Returns None if not found."""
    for a in spec.actors:
        if a.id == actor_id:
            return a
    return None


def _get_actor_name(spec, actor_id):
    """Get actor display name."""
    actor = _find_actor(spec, actor_id)
    return actor.name if actor else actor_id


class StartGameRequest(BaseModel):
    scenario_path: str = "scenarios/us_iran_2026.yaml"
    play_as: str = "actor_us"
    # human_vs_human is CLI-only (hot-seat at one terminal); the web UI takes one
    # directive per turn, so it cannot collect a second human's orders.
    mode: Literal["human_vs_ai", "ai_vs_ai"] = "human_vs_ai"
    db_path: str | None = None


class CommandRequest(BaseModel):
    directive: str


@app.get("/api/config")
def public_config():
    """What the page needs to tell a public visitor (model in use, turn cap, sample orders)."""
    from wargame.config import GM_MODEL
    public = os.environ.get("WARGAME_PUBLIC") == "1"
    return {
        "public": public,
        "model": GM_MODEL.split("/", 1)[-1] if "/" in GM_MODEL else GM_MODEL,
        "max_turns": int(os.environ.get("WARGAME_PUBLIC_MAX_TURNS", "8")) if public else None,
        "example_orders": [
            "Tighten sanctions on Iranian oil exports and offer talks through Oman.",
            "Move a carrier strike group into the Gulf and reassure our allies.",
            "Propose a limited deal: sanctions relief for capped enrichment.",
        ],
    }


@app.get("/")
async def index():
    """Serve the main UI."""
    return FileResponse(WEB_DIR / "index.html")


@contextlib.contextmanager
def _exclusive():
    """Hold this visitor's game lock; a second concurrent request gets a plain 409.

    Endpoints are plain `def`, so FastAPI runs them in its threadpool: other
    visitors are served while this one waits on the LLM.
    """
    lock = game["lock"]
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "Your last order is still being processed.")
    try:
        yield
    finally:
        lock.release()


@app.post("/api/start")
def start_game(req: StartGameRequest):
    """Initialize a new game."""
    with _exclusive():
        return _start_game(req)


def _start_game(req: StartGameRequest):
    public = public_mode()
    scenario_path = req.scenario_path
    if public:
        if req.mode == "ai_vs_ai":
            raise HTTPException(400, "AI-vs-AI games are not available on this server.")
        try:
            scenario_path = resolve_bundled_scenario(scenario_path)
        except ValueError as e:
            raise HTTPException(400, str(e))
    spec = load_scenario(scenario_path)
    if req.mode != "ai_vs_ai" and _find_actor(spec, req.play_as) is None:
        raise HTTPException(400, f"Unknown actor: {req.play_as}")
    trace_id = f"wargame_{uuid.uuid4().hex[:8]}"
    db_path = req.db_path
    if public:
        db_path = _public_db_path(trace_id)  # client-supplied db_path is ignored
    elif db_path is None:
        Path(DEFAULT_DB_DIR).mkdir(parents=True, exist_ok=True)
        db_path = str(Path(DEFAULT_DB_DIR) / f"{trace_id}.sqlite")
    conn = init_db(spec, db_path)

    actor_ids = [a.id for a in spec.actors]
    human_actor = req.play_as if req.mode != "ai_vs_ai" else None
    ai_actors = [a for a in actor_ids if a != human_actor] if human_actor else actor_ids

    # Starting over in the same session releases the previous game's connection
    # (and, in public mode only, its server-owned db file).
    discard_game(game, delete_db=public)
    game["conn"] = conn
    game["spec"] = spec
    game["trace_id"] = trace_id
    game["turn_log"] = []
    game["action_histories"] = {a: [] for a in actor_ids}
    game["human_actor"] = human_actor
    game["ai_actors"] = ai_actors
    game["mode"] = req.mode
    game["db_path"] = db_path
    game["gm_session"] = GMSession(
        spec=spec, model=GM_MODEL, max_budget=GM_MAX_BUDGET,
        trace_id=trace_id, call_defaults=gm_call_defaults(GM_MODEL),
    )

    actor_names = {a.id: a.name for a in spec.actors}
    return {
        "status": "started",
        "scenario": spec.meta.name,
        "turns": spec.meta.turns,
        "play_as": human_actor,
        "actor_names": actor_names,
        "trace_id": trace_id,
        "db_path": None if public else db_path,
        "state": get_all_variables(conn),
        "estimates": get_actor_state_estimates(conn, human_actor) if human_actor else get_all_variables(conn),
    }


@app.get("/api/state")
def get_state():
    """Get current game state."""
    with _exclusive():
        return _get_state()


def _get_state():
    if game["conn"] is None:
        raise HTTPException(400, "No game in progress")

    conn = game["conn"]
    human = game["human_actor"]
    estimates = get_actor_state_estimates(conn, human) if human else get_all_variables(conn)
    history = get_state_history(conn)
    hist_json = {var_id: [{"turn": t, "value": v} for t, v in points] for var_id, points in history.items()}

    return {"estimates": estimates, "history": hist_json, "turn_log": game["turn_log"]}


def _get_ai_action(conn, spec, actor_id, turn_number, trace_id):
    """Generate an AI action for the given actor."""
    actor = _find_actor(spec, actor_id)
    if actor is None:
        raise ValueError(f"Unknown actor: {actor_id}")

    estimates = get_actor_state_estimates(conn, actor_id)
    budget = spec.resource_budget[actor_id].domains

    rows = conn.execute(
        "SELECT observations FROM observation_log WHERE actor_id=? ORDER BY turn_number DESC LIMIT 3",
        (actor_id,),
    ).fetchall()
    recent_obs = []
    for r in rows:
        recent_obs.extend(json.loads(r[0]))

    messages = build_ai_opponent_messages(
        actor=actor, state_estimates=estimates, observations=recent_obs,
        action_history=game["action_histories"].get(actor_id, []),
        turn_number=turn_number, resource_budget=budget,
    )
    return request_valid_ai_action(
        call_llm_structured, actor, spec.resource_budget[actor_id], messages,
        model=AI_MODEL, task="wargame_ai_opponent", trace_id=trace_id,
        max_budget=AI_MAX_BUDGET, **LLM_CALL_DEFAULTS,
    )


@app.post("/api/command")
def submit_command(req: CommandRequest):
    """Submit a command and run a full turn (one at a time per visitor)."""
    with _exclusive():
        return _submit_command(req)


def _submit_command(req: CommandRequest):
    """Run a full turn.

    For human_vs_ai: parses the human command + generates AI action.
    For ai_vs_ai: generates actions for both sides (directive is ignored).
    """
    if game["conn"] is None:
        raise HTTPException(400, "No game in progress")

    conn = game["conn"]
    spec = game["spec"]
    trace_id = game["trace_id"]
    human_actor = game["human_actor"]
    mode = game["mode"]

    if turns_remaining(conn, spec.meta.turns) == 0:
        raise HTTPException(409, f"Game over: all {spec.meta.turns} turns have been played")
    if public_mode() and len(game["turn_log"]) >= public_max_turns():
        raise HTTPException(
            409, f"This demo is limited to {public_max_turns()} turns per game. Start a new game to keep playing."
        )

    # Parse and validate the human order before anything touches game state, so
    # a rejected order does not advance the turn or apply world dynamics.
    human_intent = None
    if human_actor and mode != "ai_vs_ai":
        actor = _find_actor(spec, human_actor)
        if actor is None:
            raise HTTPException(400, f"Unknown actor: {human_actor}")

        instruments = [{"id": i.id, "midfield": i.midfield, "target_vars": i.target_vars} for i in actor.instruments]
        budget = spec.resource_budget[human_actor].domains

        messages = build_parser_messages(req.directive, actor, instruments, budget)
        human_intent, _ = call_llm_structured(
            model=PARSER_MODEL, messages=messages, response_model=ActionIntent,
            task="wargame_parser", trace_id=trace_id, max_budget=PARSER_MAX_BUDGET,
            **LLM_CALL_DEFAULTS,
        )
        human_intent.actor_id = human_actor
        issues = validate_action_intent(human_intent, actor, spec.resource_budget[human_actor])
        if issues:
            raise HTTPException(400, f"Invalid order: {'; '.join(issues)}")

    # All of the turn lands or none of it: a failure anywhere (AI, GM, engine)
    # rolls back to the state before the turn began.
    with atomic_turn(conn, game["gm_session"], game["action_histories"]):
        # Run mechanical phases
        mech = run_mechanical_phases(conn)
        turn = mech.turn_number

        turn_result = {
            "turn": turn,
            "mechanical_deltas": {k: round(v, 4) for k, v in mech.all_mechanical_deltas.items() if abs(v) > 0.005},
            "actions": [],
            "observations": {},
        }

        turn_actions = []
        if human_intent is not None:
            turn_actions.append((human_actor, human_intent))
            game["action_histories"][human_actor].append(
                f"Turn {turn}: [{human_intent.action_category}] {human_intent.intended_effect[:60]}"
            )

        # AI actions
        for ai_id in game["ai_actors"]:
            ai_intent = _get_ai_action(conn, spec, ai_id, turn, trace_id)
            turn_actions.append((ai_id, ai_intent))
            game["action_histories"][ai_id].append(
                f"Turn {turn}: [{ai_intent.action_category}] {ai_intent.intended_effect[:60]}"
            )

        # Adjudicate all actions
        for actor_id, action in turn_actions:
            chosen, packet = adjudicate_action(
                conn, spec, action, turn, mech.all_mechanical_deltas, game["gm_session"],
            )

            # Build probability table for spectator view
            prob_table = [
                {"outcome": o.outcome_id, "probability": round(o.probability, 2),
                 "transitions": [{"var": t.var_id, "delta": round(t.delta, 3)} for t in o.state_transitions]}
                for o in packet.possible_outcomes
            ]

            turn_result["actions"].append({
                "actor": _get_actor_name(spec, actor_id),
                "actor_id": actor_id,
                "is_human": actor_id == human_actor,
                "category": action.action_category,
                "instruments": action.instruments_used,
                "intent": action.intended_effect,
                "outcome": chosen["outcome_id"],
                "narrative": chosen["narrative"],
                "gm_reasoning": packet.reasoning,
                "probability_table": prob_table,
                "gm_transitions": [{"var": t["var_id"], "delta": round(t["delta"], 3)} for t in chosen["state_transitions"]],
            })

        # Generate observations
        turn_result["observations"] = {
            actor_id: packet["observations"]
            for actor_id, packet in generate_observations(conn, spec, turn, turn_actions).items()
        }

        record_state_history(conn, turn)
    game["turn_log"].append(turn_result)

    # Return updated state
    canonical = get_all_variables(conn)
    estimates = get_actor_state_estimates(conn, human_actor) if human_actor else canonical
    history = get_state_history(conn)
    hist_json = {var_id: [{"turn": t, "value": v} for t, v in points] for var_id, points in history.items()}

    remaining = turns_remaining(conn, spec.meta.turns)
    response = {
        "turn_result": turn_result,
        "estimates": estimates,
        "history": hist_json,
        "turns_remaining": remaining,
        "game_over": remaining == 0,
    }

    # Spectator/god-mode: include canonical state and per-actor estimates
    if mode == "ai_vs_ai" or not human_actor:
        actor_estimates = {}
        for a in spec.actors:
            actor_estimates[a.id] = get_actor_state_estimates(conn, a.id)
        response["canonical"] = canonical
        response["actor_estimates"] = actor_estimates

    return response
