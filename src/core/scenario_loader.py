"""Scenario document loader for initializing canonical world state from disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from src.core.models import WorldState


def load_scenario(filepath: str | Path) -> WorldState:
    """Load a checked-in scenario document into validated canonical world state."""

    scenario_path = Path(filepath)
    scenario_data = _parse_scenario_file(scenario_path)
    normalized_data = _normalize_scenario_data(scenario_data)
    return WorldState.model_validate(normalized_data)


def _parse_scenario_file(filepath: Path) -> dict[str, Any]:
    """Parse supported scenario file formats into a mapping for model validation."""

    suffix = filepath.suffix.lower()

    try:
        raw_text = filepath.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise

    try:
        if suffix == ".json":
            parsed_data = json.loads(raw_text)
        elif suffix in {".yaml", ".yml"}:
            parsed_data = yaml.safe_load(raw_text)
        else:
            msg = (
                f"Unsupported scenario file format '{filepath.suffix}'. "
                "Use .json, .yaml, or .yml."
            )
            raise ValueError(msg)
    except json.JSONDecodeError as exc:
        msg = f"Scenario file '{filepath}' contains invalid JSON: {exc.msg}."
        raise ValueError(msg) from exc
    except yaml.YAMLError as exc:
        msg = f"Scenario file '{filepath}' contains invalid YAML."
        raise ValueError(msg) from exc

    if not isinstance(parsed_data, dict):
        msg = f"Scenario file '{filepath}' must contain a top-level mapping."
        raise ValueError(msg)

    return parsed_data


def _normalize_scenario_data(scenario_data: dict[str, Any]) -> dict[str, Any]:
    """Translate authored scenario variants into the strict canonical state schema."""

    nations = scenario_data.get("nations")
    if isinstance(nations, list):
        return _normalize_authored_scenario(scenario_data)
    return scenario_data


def _normalize_authored_scenario(scenario_data: dict[str, Any]) -> dict[str, Any]:
    """Flatten the authored list-based scenario format into WorldState dictionaries."""

    normalized_nations: dict[str, dict[str, Any]] = {}
    normalized_actors: dict[str, dict[str, Any]] = {}
    normalized_players: dict[str, dict[str, Any]] = {}
    normalized_alliances: dict[str, list[str]] = {}
    normalized_map_adjacency: dict[str, list[str]] = {}
    normalized_objectives: dict[str, list[str]] = {}
    victory_conditions = scenario_data.get("victory_conditions", {})

    for nation_data in scenario_data["nations"]:
        nation_id = nation_data["id"]
        position = nation_data.get("position", nation_id)
        player_id = nation_data.get("player_id", f"player-{nation_id}")

        normalized_nations[nation_id] = {
            "entity_id": nation_id,
            "name": nation_data["name"],
            "attributes": nation_data.get("attributes", {}),
            "position": position,
        }
        normalized_players[player_id] = {
            "player_id": player_id,
            "nation_id": nation_id,
            "role": "leader",
            "position": position,
        }
        normalized_alliances[nation_id] = []
        normalized_map_adjacency.setdefault(position, [])
        normalized_objectives[player_id] = _build_objectives(
            nation_id=nation_id,
            victory_condition=victory_conditions.get(nation_id, {}),
        )

        for actor_data in nation_data.get("actors", []):
            actor_id = actor_data["id"]
            actor_position = actor_data.get("position", position)
            normalized_actors[actor_id] = {
                "entity_id": actor_id,
                "name": actor_data["name"],
                "nation_id": nation_id,
                "position": actor_position,
                "attributes": actor_data.get("attributes", {}),
            }
            normalized_map_adjacency.setdefault(actor_position, [])

    return {
        "turn_number": scenario_data.get("turn_number", 0),
        "nations": normalized_nations,
        "actors": normalized_actors,
        "players": normalized_players,
        "alliances": normalized_alliances,
        "map_adjacency": normalized_map_adjacency,
        "objectives": normalized_objectives,
    }


def _build_objectives(nation_id: str, victory_condition: dict[str, Any]) -> list[str]:
    """Preserve authored victory conditions as readable scenario objectives."""

    objectives: list[str] = []
    description = victory_condition.get("description")
    if isinstance(description, str) and description:
        objectives.append(description)

    for metric in victory_condition.get("metrics", []):
        attribute = metric["attribute"]
        target = metric["target"]
        metric_nation = metric.get("nation", nation_id)
        if metric_nation == nation_id:
            objectives.append(f"Metric: {attribute} {target}")
            continue
        objectives.append(f"Metric: {attribute} on {metric_nation} {target}")

    return objectives
