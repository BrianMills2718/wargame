"""Pydantic models for canonical world state and adjudication packets.

This module defines the complete data schema for the wargame's deterministic core.
All state mutations flow through these models, ensuring strict validation at every
boundary.

**Entity hierarchy** (thin-spine state carriers):

- :class:`StateEntity` — base class with ``attributes`` dict (0-100 integers)
- :class:`Nation` — a sovereign nation controlled by a player
- :class:`Actor` — a non-sovereign actor aligned with a nation (e.g. military,
  intelligence, diplomatic corps)
- :class:`Player` — metadata for observation filtering (role + position)
- :class:`MapFeature` — static scenario geography retained for proximity rules

**World state**:

- :class:`WorldState` — canonical mutable state mutated by the turn engine, with
  referential-integrity validators that enforce key/ID consistency and cross-entity
  references

**Adjudication pipeline** (GM → Core):

- :class:`AttributeChange` — a single signed delta to one entity attribute
- :class:`AdjudicationOutcome` — a weighted branch the RNG can select
- :class:`AdjudicationPacket` — the structured instruction set emitted by the GM
  boundary, containing guaranteed changes and probabilistic outcomes
- :class:`AppliedChange` — the concrete mutation record after processing
- :class:`TurnResult` — full record of how a packet changed the world state,
  including the RNG roll and selected outcome
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StateEntity(BaseModel):
    """Canonical entity whose thin-spine attributes can change between turns."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(min_length=1, description="Stable identifier for the entity.")
    name: str = Field(min_length=1, description="Human-readable entity name.")
    attributes: dict[str, int] = Field(
        default_factory=dict,
        description="Thin-spine state variables stored as 0-100 integer values.",
    )
    position: str | None = Field(
        default=None,
        description="Current map node or theater used for proximity-based observation filtering.",
    )

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, attributes: dict[str, int]) -> dict[str, int]:
        """Reject attribute values that violate the canonical 0-100 range."""

        for key, value in attributes.items():
            if not 0 <= value <= 100:
                msg = f"Attribute '{key}' must remain within 0-100; got {value}."
                raise ValueError(msg)
        return attributes


class Nation(StateEntity):
    """A player-controlled nation in the canonical world state."""


class Actor(StateEntity):
    """A non-sovereign actor that can still affect the geopolitical state."""

    nation_id: str = Field(
        min_length=1,
        description="Identifier of the nation the actor is aligned with.",
    )


class Player(BaseModel):
    """Player metadata used by the engine to filter observations."""

    model_config = ConfigDict(extra="forbid")

    player_id: str = Field(min_length=1, description="Stable identifier for the player.")
    nation_id: str = Field(
        min_length=1,
        description="Nation controlled by the player for alliance and ownership checks.",
    )
    role: Literal["leader", "operative", "observer"] = Field(
        description="Observation role that determines how much distant activity is visible."
    )
    position: str | None = Field(
        default=None,
        description="Current theater or map node where the player is operating.",
    )


class MapFeature(BaseModel):
    """Static scenario feature retained in state for geography-aware rules and objectives."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str = Field(min_length=1, description="Stable identifier for the map feature.")
    name: str = Field(min_length=1, description="Human-readable name for the map feature.")
    feature_type: str = Field(
        min_length=1,
        description="Scenario-defined classification such as chokepoint or city.",
    )
    position: str = Field(
        min_length=1,
        description="Map node where the feature is located for proximity checks.",
    )
    properties: dict[str, str | int | bool] = Field(
        default_factory=dict,
        description="Structured scenario metadata used by future rules and UI surfaces.",
    )


class WorldState(BaseModel):
    """Canonical world state mutated by the turn engine."""

    model_config = ConfigDict(extra="forbid")

    turn_number: int = Field(
        default=0,
        ge=0,
        description="Current turn number before the next packet is applied.",
    )
    nations: dict[str, Nation] = Field(
        default_factory=dict,
        description="Nation entities keyed by their stable identifiers.",
    )
    actors: dict[str, Actor] = Field(
        default_factory=dict,
        description="Actor entities keyed by their stable identifiers.",
    )
    players: dict[str, Player] = Field(
        default_factory=dict,
        description="Player metadata keyed by player identifier for fog-of-war filtering.",
    )
    alliances: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Nation-to-nation alliance map used by observation filtering.",
    )
    map_adjacency: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Map node adjacency used to determine local observation proximity.",
    )
    map_features: dict[str, MapFeature] = Field(
        default_factory=dict,
        description="Static map features keyed by feature identifier.",
    )
    objectives: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Initial scenario objectives keyed by player or nation identifier.",
    )
    latest_turn_result: TurnResult | None = Field(
        default=None,
        description="Most recent processed turn result cached for observation filtering.",
    )

    @model_validator(mode="after")
    def validate_entity_keys(self) -> "WorldState":
        """Ensure dictionary keys match the entity identifiers they store."""

        for entity_id, nation in self.nations.items():
            if entity_id != nation.entity_id:
                msg = f"Nation key '{entity_id}' does not match entity_id '{nation.entity_id}'."
                raise ValueError(msg)
        for entity_id, actor in self.actors.items():
            if entity_id != actor.entity_id:
                msg = f"Actor key '{entity_id}' does not match entity_id '{actor.entity_id}'."
                raise ValueError(msg)
        for player_id, player in self.players.items():
            if player_id != player.player_id:
                msg = f"Player key '{player_id}' does not match player_id '{player.player_id}'."
                raise ValueError(msg)
            if player.nation_id not in self.nations:
                msg = f"Player '{player_id}' references unknown nation '{player.nation_id}'."
                raise ValueError(msg)
        for nation_id, allied_nations in self.alliances.items():
            if nation_id not in self.nations:
                msg = f"Alliance source '{nation_id}' is not a known nation."
                raise ValueError(msg)
            unknown_allies = [ally_id for ally_id in allied_nations if ally_id not in self.nations]
            if unknown_allies:
                msg = (
                    f"Alliance source '{nation_id}' references unknown allies "
                    f"{', '.join(sorted(unknown_allies))}."
                )
                raise ValueError(msg)
        for feature_id, feature in self.map_features.items():
            if feature_id != feature.feature_id:
                msg = (
                    f"Map feature key '{feature_id}' does not match feature_id "
                    f"'{feature.feature_id}'."
                )
                raise ValueError(msg)
        for objective_owner in self.objectives:
            if objective_owner not in self.players and objective_owner not in self.nations:
                msg = (
                    f"Objective owner '{objective_owner}' must reference a known player "
                    "or nation."
                )
                raise ValueError(msg)
        return self


class AttributeChange(BaseModel):
    """A direct change to a single nation or actor attribute."""

    model_config = ConfigDict(extra="forbid")

    target_type: Literal["nation", "actor"] = Field(
        description="Whether the change targets a nation or an actor."
    )
    target_id: str = Field(min_length=1, description="Identifier of the target entity.")
    attribute: str = Field(
        min_length=1,
        description="Thin-spine attribute name to update on the target entity.",
    )
    delta: int = Field(description="Signed amount to add to the attribute value.")


class AdjudicationOutcome(BaseModel):
    """A weighted outcome the engine can select after rolling RNG."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Outcome label returned in the turn result.")
    weight: float = Field(
        gt=0,
        description="Relative weight used when sampling this outcome.",
    )
    changes: list[AttributeChange] = Field(
        default_factory=list,
        description="Attribute changes applied if this outcome is selected.",
    )


class AdjudicationPacket(BaseModel):
    """Structured adjudication instructions emitted by the GM boundary."""

    model_config = ConfigDict(extra="forbid")

    packet_id: str = Field(min_length=1, description="Stable identifier for the packet.")
    description: str = Field(
        min_length=1,
        description="Human-readable summary of the action being adjudicated.",
    )
    guaranteed_changes: list[AttributeChange] = Field(
        default_factory=list,
        description="Changes that always happen regardless of the RNG outcome.",
    )
    outcomes: list[AdjudicationOutcome] = Field(
        default_factory=list,
        description="Weighted outcomes considered after the engine rolls RNG.",
    )

    @model_validator(mode="after")
    def validate_contents(self) -> "AdjudicationPacket":
        """Reject empty packets that would not change the world state."""

        if not self.guaranteed_changes and not self.outcomes:
            msg = "AdjudicationPacket must define guaranteed changes, outcomes, or both."
            raise ValueError(msg)
        return self


class AppliedChange(BaseModel):
    """Observed canonical state mutation produced by packet processing."""

    model_config = ConfigDict(extra="forbid")

    target_type: Literal["nation", "actor"] = Field(
        description="Whether the change targeted a nation or an actor."
    )
    target_id: str = Field(min_length=1, description="Identifier of the mutated entity.")
    attribute: str = Field(
        min_length=1,
        description="Thin-spine attribute name that was changed.",
    )
    old_value: int = Field(ge=0, le=100, description="Value before the change.")
    new_value: int = Field(ge=0, le=100, description="Value after the change.")
    delta: int = Field(description="Signed amount applied to the attribute.")


class TurnResult(BaseModel):
    """Structured record of how a packet changed the world state."""

    model_config = ConfigDict(extra="forbid")

    packet_id: str = Field(min_length=1, description="Identifier of the processed packet.")
    turn_number: int = Field(ge=1, description="Turn number after the packet was applied.")
    roll: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Raw RNG roll used to select an outcome, if any.",
    )
    selected_outcome: str | None = Field(
        default=None,
        description="Outcome name selected by the RNG, if any.",
    )
    applied_changes: list[AppliedChange] = Field(
        default_factory=list,
        description="Concrete state mutations applied while processing the packet.",
    )


WorldState.model_rebuild()
