"""Game Master service for translating player directives into adjudication packets."""

from __future__ import annotations

import json
from pathlib import Path
from src.core import WorldState
from src.gm.models import AdjudicationPacket


PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "game_master.yaml"


def adjudicate_player_action(
    world_state: WorldState,
    acting_player_id: str,
    player_action: str,
    *,
    model: str,
    trace_id: str,
    max_budget: float,
    task: str = "gm_adjudication",
    recent_turn_summary: str | None = None,
) -> AdjudicationPacket:
    """Translate one player directive into a validated GM adjudication packet."""

    from llm_client import call_llm_structured

    messages = _render_game_master_prompt(
        world_state=world_state,
        acting_player_id=acting_player_id,
        player_action=player_action,
        recent_turn_summary=recent_turn_summary,
    )
    result, _meta = call_llm_structured(
        model,
        messages,
        response_model=AdjudicationPacket,
        task=task,
        trace_id=trace_id,
        max_budget=max_budget,
    )
    return result


def _render_game_master_prompt(
    *,
    world_state: WorldState,
    acting_player_id: str,
    player_action: str,
    recent_turn_summary: str | None,
) -> list[dict[str, str]]:
    """Render the authored GM YAML prompt with a compact world-state summary."""

    from llm_client import render_prompt

    return render_prompt(
        PROMPT_PATH,
        turn_number=world_state.turn_number,
        acting_player_id=acting_player_id,
        world_state_summary=_summarize_world_state(world_state),
        recent_turn_summary=recent_turn_summary,
        player_action=player_action,
    )


def _summarize_world_state(world_state: WorldState) -> str:
    """Serialize the GM-visible world state into deterministic JSON text."""

    summary = {
        "turn_number": world_state.turn_number,
        "nations": {
            nation_id: {
                "name": nation.name,
                "position": nation.position,
                "attributes": nation.attributes,
            }
            for nation_id, nation in sorted(world_state.nations.items())
        },
        "actors": {
            actor_id: {
                "name": actor.name,
                "nation_id": actor.nation_id,
                "position": actor.position,
                "attributes": actor.attributes,
            }
            for actor_id, actor in sorted(world_state.actors.items())
        },
        "players": {
            player_id: {
                "nation_id": player.nation_id,
                "role": player.role,
                "position": player.position,
            }
            for player_id, player in sorted(world_state.players.items())
        },
        "alliances": world_state.alliances,
        "latest_turn_result": (
            world_state.latest_turn_result.model_dump(mode="json")
            if world_state.latest_turn_result is not None
            else None
        ),
    }
    return json.dumps(summary, indent=2, sort_keys=True)


def _parse_adjudication_packet(content: str) -> AdjudicationPacket:
    """Validate raw LLM JSON output as a GM adjudication packet."""

    payload = json.loads(_strip_json_fences(content))
    return AdjudicationPacket.model_validate(payload)


def _strip_json_fences(content: str) -> str:
    """Remove optional Markdown JSON fences before parsing."""

    cleaned = content.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline == -1:
            return cleaned.strip("`")
        cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    return cleaned.strip()
