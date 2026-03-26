"""Tests for RNG-aware packet processing in the core turn engine."""

from __future__ import annotations

import random

import pytest

from src.core import (
    Actor,
    AdjudicationOutcome,
    AdjudicationPacket,
    AttributeChange,
    Nation,
    TurnEngine,
    WorldState,
)


class FixedRNG:
    """Deterministic RNG stub for testing exact outcome selection."""

    def __init__(self, value: float) -> None:
        """Store the single roll value returned by the stub."""

        self._value = value

    def random(self) -> float:
        """Return the preconfigured roll value."""

        return self._value


def build_world_state() -> WorldState:
    """Create a small canonical state used across engine tests."""

    return WorldState(
        nations={
            "us": Nation(
                entity_id="us",
                name="United States",
                attributes={"diplomatic_leverage": 50, "military_readiness": 60},
            )
        },
        actors={
            "proxy-a": Actor(
                entity_id="proxy-a",
                name="Proxy A",
                nation_id="us",
                attributes={"covert_ops_capacity": 40},
            )
        },
    )


def build_packet() -> AdjudicationPacket:
    """Create a packet with guaranteed and probabilistic state changes."""

    return AdjudicationPacket(
        packet_id="packet-1",
        description="Coordinated pressure campaign.",
        guaranteed_changes=[
            AttributeChange(
                target_type="actor",
                target_id="proxy-a",
                attribute="covert_ops_capacity",
                delta=5,
            )
        ],
        outcomes=[
            AdjudicationOutcome(
                name="success",
                weight=0.4,
                changes=[
                    AttributeChange(
                        target_type="nation",
                        target_id="us",
                        attribute="diplomatic_leverage",
                        delta=10,
                    )
                ],
            ),
            AdjudicationOutcome(
                name="partial",
                weight=0.4,
                changes=[
                    AttributeChange(
                        target_type="nation",
                        target_id="us",
                        attribute="diplomatic_leverage",
                        delta=3,
                    )
                ],
            ),
            AdjudicationOutcome(
                name="failure",
                weight=0.2,
                changes=[
                    AttributeChange(
                        target_type="nation",
                        target_id="us",
                        attribute="diplomatic_leverage",
                        delta=-4,
                    )
                ],
            ),
        ],
    )


@pytest.mark.parametrize(
    ("seed", "expected_outcome", "expected_leverage"),
    [
        (1, "success", 60),
        (5, "partial", 53),
        (0, "failure", 46),
    ],
)
def test_process_packet_with_seeded_rng_produces_predictable_state_changes(
    seed: int, expected_outcome: str, expected_leverage: int
) -> None:
    """Seeded Python RNG values should map to deterministic packet outcomes."""

    world_state = build_world_state()
    engine = TurnEngine(world_state=world_state, rng=random.Random(seed))

    result = engine.process_packet(build_packet())

    assert result.selected_outcome == expected_outcome
    assert world_state.nations["us"].attributes["diplomatic_leverage"] == expected_leverage
    assert world_state.actors["proxy-a"].attributes["covert_ops_capacity"] == 45
    assert result.turn_number == 1
    assert result.applied_changes[0].target_id == "proxy-a"


def test_process_packet_uses_injected_mock_rng_for_outcome_selection() -> None:
    """A stub RNG should let tests force a specific branch without seeding."""

    world_state = build_world_state()
    engine = TurnEngine(world_state=world_state, rng=FixedRNG(0.95))

    result = engine.process_packet(build_packet())

    assert result.roll == pytest.approx(0.95)
    assert result.selected_outcome == "failure"
    assert world_state.nations["us"].attributes["diplomatic_leverage"] == 46
    assert world_state.actors["proxy-a"].attributes["covert_ops_capacity"] == 45


def test_process_packet_mutates_engine_world_state_reference() -> None:
    """Engine state should be updated in place so callers see the new values."""

    engine = TurnEngine(world_state=build_world_state(), rng=FixedRNG(0.2))

    engine.process_packet(build_packet())

    assert engine.world_state.turn_number == 1
    assert engine.world_state.nations["us"].attributes["diplomatic_leverage"] == 60
    assert engine.world_state.actors["proxy-a"].attributes["covert_ops_capacity"] == 45


def test_process_packet_fails_loudly_when_change_would_leave_valid_range() -> None:
    """Invalid attribute updates should raise instead of silently clamping."""

    packet = AdjudicationPacket(
        packet_id="packet-2",
        description="Over-committed escalation.",
        guaranteed_changes=[
            AttributeChange(
                target_type="nation",
                target_id="us",
                attribute="military_readiness",
                delta=50,
            )
        ],
    )
    engine = TurnEngine(world_state=build_world_state(), rng=FixedRNG(0.0))

    with pytest.raises(ValueError, match="valid 0-100 range"):
        engine.process_packet(packet)
