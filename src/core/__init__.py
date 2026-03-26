"""Core game engine — state, turns, adjudication, observation filtering."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "Actor",
    "AdjudicationOutcome",
    "AdjudicationPacket",
    "AppliedChange",
    "AttributeChange",
    "MapFeature",
    "Nation",
    "Player",
    "TurnEngine",
    "TurnResult",
    "WorldState",
    "filter_observations",
    "load_scenario",
]

_MODEL_EXPORTS = {
    "Actor",
    "AdjudicationOutcome",
    "AdjudicationPacket",
    "AppliedChange",
    "AttributeChange",
    "MapFeature",
    "Nation",
    "Player",
    "TurnResult",
    "WorldState",
}
_ENGINE_EXPORTS = {"TurnEngine", "filter_observations"}
_SCENARIO_EXPORTS = {"load_scenario"}


def __getattr__(name: str) -> object:
    """Lazy-load core exports so module execution does not re-import submodules."""

    if name in _MODEL_EXPORTS:
        return getattr(import_module("src.core.models"), name)
    if name in _ENGINE_EXPORTS:
        return getattr(import_module("src.core.engine"), name)
    if name in _SCENARIO_EXPORTS:
        return getattr(import_module("src.core.scenario_loader"), name)
    msg = f"module 'src.core' has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    """Expose lazy-loaded exports to interactive tooling."""

    return sorted(__all__)
