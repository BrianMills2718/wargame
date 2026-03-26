"""Tests for llm_client-backed GM adjudication."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.core import Nation, Player, WorldState
from src.gm import AdjudicationPacket, adjudicate_player_action
import src.gm.adjudicator as gm_adjudicator
import llm_client


@dataclass
class _FakeLLMResult:
    """Minimal stand-in for llm_client's text result object."""

    content: str


def test_adjudicate_player_action_returns_valid_packet(monkeypatch: Any) -> None:
    """GM adjudication should call llm_client and return a validated packet."""

    captured: dict[str, Any] = {}
    world_state = WorldState(
        turn_number=3,
        nations={
            "us": Nation(
                entity_id="us",
                name="United States",
                position="washington",
                attributes={
                    "diplomatic_leverage": 62,
                    "economic_stability": 78,
                },
            ),
            "iran": Nation(
                entity_id="iran",
                name="Iran",
                position="tehran",
                attributes={
                    "diplomatic_leverage": 55,
                    "economic_stability": 48,
                },
            ),
        },
        players={
            "player-us": Player(
                player_id="player-us",
                nation_id="us",
                role="leader",
                position="washington",
            )
        },
        alliances={"us": [], "iran": []},
    )

    def fake_call_llm(
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> _FakeLLMResult:
        """Capture the GM llm_client contract and return JSON for validation."""

        captured["model"] = model
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return _FakeLLMResult(
            content=json.dumps(
                {
                    "packet_id": "gm-packet-7",
                    "description": "US diplomatic pressure campaign against Iran.",
                    "source_action": "Pressure regional partners to tighten sanctions on Iran.",
                    "reasoning": "US leverage is high enough to create incremental pressure on Iran's economy.",
                    "confidence": "medium",
                    "guaranteed_changes": [
                        {
                            "target_type": "nation",
                            "target_id": "us",
                            "attribute": "diplomatic_leverage",
                            "delta": 2,
                        }
                    ],
                    "outcomes": [
                        {
                            "name": "partners_comply",
                            "weight": 0.65,
                            "changes": [
                                {
                                    "target_type": "nation",
                                    "target_id": "iran",
                                    "attribute": "economic_stability",
                                    "delta": -4,
                                }
                            ],
                        }
                    ],
                }
            )
        )

    monkeypatch.setattr(llm_client, "call_llm", fake_call_llm)

    packet = adjudicate_player_action(
        world_state,
        "player-us",
        "Pressure regional partners to tighten sanctions on Iran.",
        model="gemini/gemini-2.5-flash-lite",
        task="gm_adjudication_test",
        trace_id="tests/gm/adjudication",
        max_budget=0.25,
        recent_turn_summary="Iran weathered prior sanctions but remains economically strained.",
    )

    assert isinstance(packet, AdjudicationPacket)
    assert packet.packet_id == "gm-packet-7"
    assert packet.outcomes[0].changes[0].target_id == "iran"
    assert captured["model"] == "gemini/gemini-2.5-flash-lite"
    assert captured["kwargs"]["task"] == "gm_adjudication_test"
    assert captured["kwargs"]["trace_id"] == "tests/gm/adjudication"
    assert captured["kwargs"]["max_budget"] == 0.25
    assert set(captured["kwargs"]) == {"response_format", "task", "trace_id", "max_budget"}
    assert captured["kwargs"]["response_format"] == {
        "type": "json_schema",
        "schema": AdjudicationPacket.model_json_schema(),
    }
    assert "Pressure regional partners to tighten sanctions on Iran." in captured["messages"][1][
        "content"
    ]


def test_gm_response_format_matches_acceptance_contract() -> None:
    """The GM boundary should define the requested flat json-schema response format."""

    assert gm_adjudicator._adjudication_response_format() == {
        "type": "json_schema",
        "schema": AdjudicationPacket.model_json_schema(),
    }
