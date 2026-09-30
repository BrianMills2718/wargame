"""One running GM conversation for a whole game.

The GM used to be re-prompted from scratch for every adjudication, which meant
it had no memory. That was patched by pasting a few recent turns into the
prompt; this replaces that with the real thing — a single conversation the GM
stays inside for the length of the game, so turn 20 is informed by turn 1
rather than by a four-turn window.

Shape matters for cost as much as for quality. The system prompt holds
everything invariant (rules, every domain model, the variable and actor lists)
so it is a stable cacheable prefix; each turn appends only what changed. The
conversation therefore grows append-only, which is the pattern prompt caching
rewards and the pattern that lets a provider reuse the prefix.

The engine still owns all state. The GM proposes; Python decides and writes.
"""

from __future__ import annotations

from typing import Any, Callable

from wargame.gm import (
    adjudication_structure_issues,
    build_gm_system_prompt,
    build_gm_turn_message,
)
from wargame.models import (
    ActionIntent,
    AdjudicationPacket,
    DomainModel,
    ScenarioSpec,
)


# A packet that omits an actor's observability, or names a state variable or
# actor the scenario lacks, is re-requested this many times in total before the
# adjudication is rejected outright.
MAX_GM_ATTEMPTS = 3


class GMSession:
    """A stateful GM. Create one per game; call adjudicate() once per action."""

    def __init__(
        self,
        spec: ScenarioSpec,
        model: str,
        max_budget: float,
        trace_id: str,
        call_defaults: dict[str, Any] | None = None,
        call_fn: Callable[..., tuple[AdjudicationPacket, Any]] | None = None,
        max_history_pairs: int | None = None,
    ) -> None:
        """`call_fn` is injectable so the conversation can be tested without spend.

        `max_history_pairs` bounds the conversation if a scenario ever runs long
        enough to matter. Left as None it keeps the whole game, which for a
        20-turn scenario peaks around 100k tokens — comfortably inside a modern
        context window, so there is nothing to compact.
        """
        self.spec = spec
        self.model = model
        self.max_budget = max_budget
        self.trace_id = trace_id
        self.call_defaults = dict(call_defaults or {})
        self.max_history_pairs = max_history_pairs

        if call_fn is None:
            from llm_client import call_llm_structured as _default_call
            call_fn = _default_call
        self._call = call_fn

        self.system_prompt = build_gm_system_prompt(spec)
        # Alternating user/assistant turns, oldest first. Never rewritten.
        self.history: list[dict[str, str]] = []
        self.adjudications = 0

    def messages(self) -> list[dict[str, str]]:
        """The full message list as it will be sent."""
        return [{"role": "system", "content": self.system_prompt}, *self.history]

    def checkpoint(self) -> tuple[list[dict[str, str]], int]:
        """Snapshot the conversation so a failed turn can be forgotten."""
        return list(self.history), self.adjudications

    def restore(self, checkpoint: tuple[list[dict[str, str]], int]) -> None:
        """Return to a checkpoint. A rolled-back turn must not stay in the GM's
        memory: it would remember adjudicating actions the game never applied."""
        history, adjudications = checkpoint
        self.history = list(history)
        self.adjudications = adjudications

    def _trim(self) -> None:
        if self.max_history_pairs is None:
            return
        keep = self.max_history_pairs * 2
        if len(self.history) > keep:
            del self.history[: len(self.history) - keep]

    def adjudicate(
        self,
        action: ActionIntent,
        state: dict[str, float],
        relevant_domain_models: list[DomainModel],
        base_rates: dict[str, float],
        turn_number: int,
        mechanical_deltas: dict[str, float] | None = None,
    ) -> AdjudicationPacket:
        """Adjudicate one action inside the running conversation."""
        turn_message = build_gm_turn_message(
            action=action,
            state=state,
            relevant_domain_models=relevant_domain_models,
            base_rates=base_rates,
            turn_number=turn_number,
            mechanical_deltas=mechanical_deltas,
        )
        self.history.append({"role": "user", "content": turn_message})

        expected = {a.id for a in self.spec.actors}
        valid_var_ids = {sv.id for sv in self.spec.state_variables}
        try:
            retry_feedback: list[dict[str, str]] = []
            for _ in range(MAX_GM_ATTEMPTS):
                packet, _ = self._call(
                    model=self.model,
                    messages=self.messages() + retry_feedback,
                    response_model=AdjudicationPacket,
                    task="wargame_gm_adjudication",
                    trace_id=self.trace_id,
                    max_budget=self.max_budget,
                    **self.call_defaults,
                )
                problems = adjudication_structure_issues(packet, valid_var_ids, expected)
                if not problems:
                    break
                # Tell the model what was wrong. Resending the identical request
                # wasted a full call each time and repeated the same mistake.
                # The feedback is not kept in the conversation history.
                retry_feedback = [
                    {"role": "assistant", "content": packet.model_dump_json()},
                    {"role": "user", "content": (
                        f"That packet is invalid: {'; '.join(problems)}. Reissue the full packet. "
                        f"Observability must have exactly one entry per actor, using only these "
                        f"actor_ids: {', '.join(sorted(expected))}."
                    )},
                ]
            else:
                raise ValueError(
                    f"GM packet still invalid after {MAX_GM_ATTEMPTS} attempts: {'; '.join(problems)}"
                )
        except Exception:
            # Do not leave a dangling user turn: the next call would send two
            # user messages in a row and the conversation would misalign.
            self.history.pop()
            raise

        # The GM's own answer becomes part of what it remembers.
        self.history.append({"role": "assistant", "content": packet.model_dump_json()})
        self.adjudications += 1
        self._trim()
        return packet
