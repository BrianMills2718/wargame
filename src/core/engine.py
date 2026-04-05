"""Turn engine and fog-of-war observation filtering for the canonical world state.

This module contains the deterministic core that processes adjudication packets
and filters the resulting state changes into per-player observations.

**Turn processing** (:class:`TurnEngine`):

1. Guaranteed changes from the packet are applied unconditionally.
2. If the packet contains weighted outcomes, the engine rolls RNG and selects one
   probabilistically; the selected outcome's changes are then applied.
3. All attribute mutations are validated to stay within the canonical 0-100 range
   (fail loud — invalid updates raise immediately).
4. The turn number increments and the result is cached for observation filtering.

**Observation filtering** (:func:`filter_observations`):

Visibility is determined by a combination of player role, alliance status, and
map proximity:

- **Leader**: sees changes to controlled entities, allied nations, and locally
  adjacent entities.
- **Operative**: sees changes to controlled entities and locally adjacent entities.
- **Observer**: sees only locally adjacent changes.

Proximity is computed from ``WorldState.map_adjacency``: an entity is "local" if
its position is co-located with or adjacent to the player's position.
"""

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
    Player,
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
        """Mutate canonical state for one adjudicated action and return the result.

        Applies guaranteed changes first, then (if outcomes exist) rolls RNG to
        select a probabilistic outcome and applies its changes.  Increments the
        turn number and caches the result on ``WorldState.latest_turn_result``
        so that :meth:`filter_observations` can access it.

        Args:
            packet: Validated adjudication packet from the GM boundary.

        Returns:
            A :class:`TurnResult` recording the RNG roll, selected outcome,
            and all concrete attribute mutations.

        Raises:
            ValueError: If any attribute mutation would leave the 0-100 range.
            KeyError: If a packet references an unknown nation or actor.
        """

        applied_changes = [self._apply_change(change) for change in packet.guaranteed_changes]
        selected_outcome: str | None = None
        roll: float | None = None

        if packet.outcomes:
            roll = self._rng.random()
            outcome = self._select_outcome(packet.outcomes, roll)
            selected_outcome = outcome.name
            applied_changes.extend(self._apply_change(change) for change in outcome.changes)

        self._world_state.turn_number += 1
        result = TurnResult(
            packet_id=packet.packet_id,
            turn_number=self._world_state.turn_number,
            roll=roll,
            selected_outcome=selected_outcome,
            applied_changes=applied_changes,
        )
        self._world_state.latest_turn_result = result
        return result

    def filter_observations(self, player_id: str) -> list[AppliedChange]:
        """Return only the latest observations visible to the requested player.

        Delegates to the module-level :func:`filter_observations` function,
        passing the engine's current world state.

        Args:
            player_id: Identifier of the player whose fog-of-war view is needed.

        Returns:
            A list of :class:`AppliedChange` instances that the player can see.

        Raises:
            KeyError: If *player_id* does not exist in the world state.
        """

        return filter_observations(player_id=player_id, game_state=self._world_state)

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


def filter_observations(player_id: str, game_state: WorldState) -> list[AppliedChange]:
    """Filter the latest applied changes down to what the player can currently see.

    Iterates over every :class:`AppliedChange` in
    ``game_state.latest_turn_result`` and keeps only those that pass the
    role/alliance/proximity visibility rules defined in :func:`_change_is_visible`.

    Args:
        player_id: Identifier of the observing player.
        game_state: The current canonical world state (must contain the player).

    Returns:
        Subset of applied changes visible to the player under fog-of-war rules.

    Raises:
        KeyError: If *player_id* is not present in ``game_state.players``.
    """

    try:
        player = game_state.players[player_id]
    except KeyError as exc:
        msg = f"Unknown player '{player_id}'."
        raise KeyError(msg) from exc

    if game_state.latest_turn_result is None:
        return []

    visible_changes: list[AppliedChange] = []
    allied_nations = set(game_state.alliances.get(player.nation_id, []))

    for change in game_state.latest_turn_result.applied_changes:
        if _change_is_visible(change, player, allied_nations, game_state):
            visible_changes.append(change)

    return visible_changes


def _change_is_visible(
    change: AppliedChange,
    player: Player,
    allied_nations: set[str],
    game_state: WorldState,
) -> bool:
    """Apply role, alliance, and proximity rules to one observed change.

    Visibility matrix by role:

    - **leader**: ``is_controlled OR is_allied OR is_local``
    - **operative**: ``is_controlled OR is_local``
    - **observer**: ``is_local`` only

    Args:
        change: A single applied attribute mutation to evaluate.
        player: The observing player's metadata (role, nation, position).
        allied_nations: Pre-computed set of nation IDs allied with the player.
        game_state: Full world state for entity and adjacency lookups.

    Returns:
        ``True`` if the change should be included in the player's observation.
    """

    target = _resolve_observation_target(change.target_type, change.target_id, game_state)
    target_nation_id = target.entity_id if isinstance(target, Nation) else target.nation_id
    is_controlled = target_nation_id == player.nation_id
    is_allied = target_nation_id in allied_nations
    is_local = _positions_are_visible(
        observer_position=player.position,
        target_position=target.position,
        map_adjacency=game_state.map_adjacency,
    )

    if player.role == "leader":
        return is_controlled or is_allied or is_local
    if player.role == "operative":
        return is_controlled or is_local
    return is_local


def _positions_are_visible(
    observer_position: str | None,
    target_position: str | None,
    map_adjacency: dict[str, list[str]],
) -> bool:
    """Return whether the target position is co-located with or adjacent to the observer.

    Returns ``False`` immediately if either position is ``None`` (entities
    without a map presence are invisible to proximity checks).

    Args:
        observer_position: Map node of the observing player (may be ``None``).
        target_position: Map node of the target entity (may be ``None``).
        map_adjacency: Adjacency list mapping each node to its neighbours.
    """

    if observer_position is None or target_position is None:
        return False
    if observer_position == target_position:
        return True
    return target_position in map_adjacency.get(observer_position, [])


def _resolve_observation_target(
    target_type: str, target_id: str, game_state: WorldState
) -> Nation | Actor:
    """Resolve a change target for visibility checks without mutating the state.

    Args:
        target_type: Either ``"nation"`` or ``"actor"``.
        target_id: Identifier of the target entity.
        game_state: World state containing the entity registries.

    Returns:
        The resolved :class:`Nation` or :class:`Actor` instance.

    Raises:
        KeyError: If the target is not found in the appropriate registry.
    """

    if target_type == "nation":
        try:
            return game_state.nations[target_id]
        except KeyError as exc:
            msg = f"Unknown nation target '{target_id}' in observation filter."
            raise KeyError(msg) from exc

    try:
        return game_state.actors[target_id]
    except KeyError as exc:
        msg = f"Unknown actor target '{target_id}' in observation filter."
        raise KeyError(msg) from exc
