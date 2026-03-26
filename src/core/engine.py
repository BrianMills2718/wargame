"""Turn engine that applies adjudication packets to the canonical world state."""

from __future__ import annotations

import random
from typing import Protocol

from src.core.models import (
    Actor,
    AdjudicationOutcome,
    AdjudicationPacket,
    AppliedChange,
    AttributeChange,
    Nation,
    TurnResult,
    WorldState,
)


class RandomSource(Protocol):
    """Interface for RNG injection so outcome selection remains testable."""

    def random(self) -> float:
        """Return a floating-point sample in the inclusive 0-1 range."""


class TurnEngine:
    """Apply adjudication packets to the canonical world state via RNG."""

    def __init__(self, world_state: WorldState, rng: RandomSource | None = None) -> None:
        """Store mutable game state and an injectable RNG implementation."""

        self._world_state = world_state
        self._rng = rng if rng is not None else random.Random()

    @property
    def world_state(self) -> WorldState:
        """Expose the mutable canonical state managed by the engine."""

        return self._world_state

    def process_packet(self, packet: AdjudicationPacket) -> TurnResult:
        """Mutate canonical state for one adjudicated action and return the result."""

        applied_changes = [self._apply_change(change) for change in packet.guaranteed_changes]
        selected_outcome: str | None = None
        roll: float | None = None

        if packet.outcomes:
            roll = self._rng.random()
            outcome = self._select_outcome(packet.outcomes, roll)
            selected_outcome = outcome.name
            applied_changes.extend(self._apply_change(change) for change in outcome.changes)

        self._world_state.turn_number += 1
        return TurnResult(
            packet_id=packet.packet_id,
            turn_number=self._world_state.turn_number,
            roll=roll,
            selected_outcome=selected_outcome,
            applied_changes=applied_changes,
        )

    def _select_outcome(
        self, outcomes: list[AdjudicationOutcome], roll: float
    ) -> AdjudicationOutcome:
        """Map a raw RNG roll onto the packet's weighted outcomes."""

        total_weight = sum(outcome.weight for outcome in outcomes)
        threshold = roll * total_weight
        cumulative_weight = 0.0

        for outcome in outcomes:
            cumulative_weight += outcome.weight
            if threshold < cumulative_weight:
                return outcome

        return outcomes[-1]

    def _apply_change(self, change: AttributeChange) -> AppliedChange:
        """Mutate a single state attribute and fail loudly on invalid updates."""

        target = self._resolve_target(change.target_type, change.target_id)
        old_value = target.attributes.get(change.attribute, 0)
        new_value = old_value + change.delta

        if not 0 <= new_value <= 100:
            msg = (
                f"Applying {change.delta} to {change.target_type} '{change.target_id}' "
                f"attribute '{change.attribute}' would leave the valid 0-100 range."
            )
            raise ValueError(msg)

        target.attributes[change.attribute] = new_value
        return AppliedChange(
            target_type=change.target_type,
            target_id=change.target_id,
            attribute=change.attribute,
            old_value=old_value,
            new_value=new_value,
            delta=change.delta,
        )

    def _resolve_target(self, target_type: str, target_id: str) -> Nation | Actor:
        """Resolve a packet target to a canonical state entity."""

        if target_type == "nation":
            try:
                return self._world_state.nations[target_id]
            except KeyError as exc:
                msg = f"Unknown nation target '{target_id}'."
                raise KeyError(msg) from exc

        try:
            return self._world_state.actors[target_id]
        except KeyError as exc:
            msg = f"Unknown actor target '{target_id}'."
            raise KeyError(msg) from exc
