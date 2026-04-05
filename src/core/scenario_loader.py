"""Scenario document loader for initializing canonical world state from disk.

This module reads scenario files (JSON or YAML) and produces a validated
:class:`~src.core.models.WorldState` instance ready for the turn engine.

Two scenario formats are supported:

1. **Canonical format** — the file contains a flat dict-of-dicts that maps
   directly onto the ``WorldState`` Pydantic schema.  Used by minimal test
   fixtures (e.g. ``scenarios/test_scenario.json``).

2. **Authored format** — the file uses a more human-friendly list-based
   structure where nations contain nested actor lists, and victory conditions
   are expressed declaratively.  The loader normalises this into canonical form
   before validation.  Used by full scenarios (e.g. ``scenarios/us_iran.yaml``).

The normalisation pipeline:

.. code-block:: text

   disk file  ──▸  _parse_scenario_file  ──▸  raw dict
   raw dict   ──▸  _normalize_scenario_data ──▸  canonical dict
   canonical  ──▸  WorldState.model_validate ──▸  validated WorldState

Errors are raised eagerly (fail loud) for unsupported formats, parse failures,
and Pydantic validation failures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from src.core.models import WorldState


def load_scenario(filepath: str | Path) -> WorldState:
    """Load a scenario document from disk into a validated canonical world state.

    This is the main public entry point for scenario loading.  It parses the
    file, normalises the data (handling both canonical and authored formats),
    and returns a fully validated :class:`~src.core.models.WorldState`.

    Args:
        filepath: Path to a ``.json``, ``.yaml``, or ``.yml`` scenario file.

    Returns:
        A validated :class:`WorldState` ready for the turn engine.

    Raises:
        FileNotFoundError: If the scenario file does not exist.
        ValueError: If the file format is unsupported or contains invalid data.
        pydantic.ValidationError: If the normalised data fails schema validation.
    """

    scenario_path = Path(filepath)
    scenario_data = _parse_scenario_file(scenario_path)
    normalized_data = _normalize_scenario_data(scenario_data)
    return WorldState.model_validate(normalized_data)


def _parse_scenario_file(filepath: Path) -> dict[str, Any]:
    """Parse a scenario file (JSON or YAML) into a raw Python dict.

    Args:
        filepath: Absolute or relative path to the scenario document.

    Returns:
        A top-level mapping parsed from the file contents.

    Raises:
        FileNotFoundError: If the file does not exist on disk.
        ValueError: If the suffix is unsupported, the file contains invalid
            JSON/YAML, or the top-level structure is not a mapping.
    """

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
    """Detect scenario format and normalise to the canonical WorldState schema.

    If ``nations`` is a list, the data is treated as an authored-format scenario
    and translated via :func:`_normalize_authored_scenario`.  Otherwise, the data
    is assumed to already be in canonical dict-of-dicts form and is returned
    unchanged.

    Args:
        scenario_data: Raw parsed mapping from the scenario file.

    Returns:
        A dict suitable for ``WorldState.model_validate()``.
    """

    nations = scenario_data.get("nations")
    if isinstance(nations, list):
        return _normalize_authored_scenario(scenario_data)
    return scenario_data


def _normalize_authored_scenario(scenario_data: dict[str, Any]) -> dict[str, Any]:
    """Flatten the authored list-based scenario format into canonical WorldState dicts.

    The authored format allows scenario designers to write nations as a list with
    nested actor lists and declarative victory conditions.  This function:

    - Converts ``nations[]`` into ``nations{}`` keyed by ``id``.
    - Extracts nested ``actors[]`` into a flat ``actors{}`` dict.
    - Auto-generates ``players{}`` entries (one leader per nation).
    - Initialises empty ``alliances{}`` and ``map_adjacency{}`` registries.
    - Translates ``victory_conditions`` into ``objectives{}`` via
      :func:`_build_objectives`.

    Args:
        scenario_data: Raw parsed mapping with a list-typed ``nations`` key.

    Returns:
        A canonical dict ready for ``WorldState.model_validate()``.
    """

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
    """Convert authored victory conditions into human-readable objective strings.

    Each metric is formatted as ``"Metric: <attribute> <target>"`` (or with
    ``on <nation>`` for cross-nation metrics).  The description field, if
    present, is prepended as the first objective.

    Args:
        nation_id: Default nation for metrics that omit the ``nation`` field.
        victory_condition: Authored victory condition dict with optional
            ``description`` (str) and ``metrics`` (list of metric dicts).

    Returns:
        A list of human-readable objective strings.
    """

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
