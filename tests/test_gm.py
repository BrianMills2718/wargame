"""Tests for the GM module's schema and authored prompt contract."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.core import AdjudicationOutcome, AttributeChange
from src.gm import AdjudicationPacket


def test_gm_adjudication_packet_extends_core_contract_with_reasoning() -> None:
    """GM output should carry rationale without changing the executable packet shape."""

    packet = AdjudicationPacket(
        packet_id="gm-packet-1",
        description="Back-channel pressure campaign.",
        source_action="Have our diplomats pressure regional partners to isolate Iran quietly.",
        reasoning="US diplomatic leverage is strong enough to produce incremental pressure, not a sudden collapse.",
        confidence="medium",
        guaranteed_changes=[
            AttributeChange(
                target_type="nation",
                target_id="us",
                attribute="diplomatic_leverage",
                delta=2,
            )
        ],
        outcomes=[
            AdjudicationOutcome(
                name="partners_comply",
                weight=0.6,
                changes=[
                    AttributeChange(
                        target_type="nation",
                        target_id="iran",
                        attribute="economic_stability",
                        delta=-4,
                    )
                ],
            )
        ],
    )

    engine_packet = packet.to_engine_packet()

    assert packet.reasoning.startswith("US diplomatic leverage")
    assert engine_packet.packet_id == "gm-packet-1"
    assert not hasattr(engine_packet, "reasoning")
    assert engine_packet.outcomes[0].name == "partners_comply"


def test_gm_adjudication_packet_still_fails_loudly_when_empty() -> None:
    """The GM schema should inherit the core packet requirement for executable effects."""

    with pytest.raises(ValueError, match="must define guaranteed changes, outcomes, or both"):
        AdjudicationPacket(
            packet_id="gm-packet-empty",
            description="Ambiguous political messaging.",
            source_action="Issue a vague warning.",
            reasoning="The directive is too vague to adjudicate without concrete effects.",
            confidence="low",
        )


def test_game_master_prompt_exists_and_uses_jinja_variables() -> None:
    """The authored GM prompt should remain compatible with YAML plus Jinja2 rendering."""

    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "game_master.yaml"

    prompt = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))

    assert prompt["name"] == "game_master"
    assert len(prompt["messages"]) == 2
    user_message = prompt["messages"][1]["content"]
    assert "{{ world_state_summary }}" in user_message
    assert "{{ player_action }}" in user_message
    assert "{% if recent_turn_summary %}" in user_message
