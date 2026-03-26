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
    return WorldState.model_validate(scenario_data)


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
