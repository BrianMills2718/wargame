"""GM-facing structured output models that add rationale to engine packets."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from src.core.models import AdjudicationPacket as CoreAdjudicationPacket


class AdjudicationPacket(CoreAdjudicationPacket):
    """Capture the GM's rationale alongside the executable adjudication packet."""

    source_action: str = Field(
        min_length=1,
        description="Natural-language directive the GM interpreted into this packet.",
    )
    reasoning: str = Field(
        min_length=1,
        description="Brief explanation of why these changes and outcome weights fit the world state.",
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description="How confident the GM is that the packet matches the available evidence."
    )

    def to_engine_packet(self) -> CoreAdjudicationPacket:
        """Drop GM-only rationale fields when handing the packet to the deterministic core."""

        return CoreAdjudicationPacket.model_validate(
            self.model_dump(
                include={"packet_id", "description", "guaranteed_changes", "outcomes"}
            )
        )
