"""Central LLM call configuration for the wargame.

Every `llm_client` call in this package routes through the constants here, so
the model chain, reasoning effort, justification and fallbacks are declared in
one place instead of being duplicated across the CLI and the web server.

Context for the values below (verified 2026-09-02):

* `openrouter/openai/gpt-5.6-luna` is llm_client's DEFAULT_EXECUTION_MODEL.
* llm_client requires an explicit `reasoning_effort` for configurable-reasoning
  models; provider defaults are refused. Both models in the chain support
  "low".
* A chain containing any non-default model requires `model_justification`.
* Without a fallback, a single provider 503 aborts the turn loop and, because
  the game database was in-memory, destroyed the whole run.
"""

from __future__ import annotations

import os
from typing import Any

# Primary route for all three call sites.
# GM routing. Measured on identical code, same scenario, 6 adjudications each:
#
#   route                       quality                     latency    cost/20-turn game
#   openrouter/.../gpt-5.6-luna odds spread 0.07            14s/call   $0.09
#   claude-code/haiku           odds spread 0.23            116s/call  $0.00 (subscription)
#
# Haiku is the better adjudicator on this evidence -- it discriminates between
# situations roughly three times as much, writes four times the reasoning, and
# references the running conversation more often. It is also eight times slower,
# because each call spawns a Claude Code process. 116s per adjudication means
# about four minutes of waiting per turn for a human player and 77 minutes of GM
# time in a 20-turn game, which is not playable.
#
# So the route is chosen by what the game is for, not by which model is better:
# the fast metered route for anything a human waits on, the free subscription
# route for unattended AI-vs-AI runs where 500 games cost nothing instead of $45.
# Override with WARGAME_GM_MODEL, or --gm-model on the CLI.
GM_MODEL_INTERACTIVE = "openrouter/openai/gpt-5.6-luna"
GM_MODEL_BATCH = "claude-code/haiku"
GM_MODEL = os.environ.get("WARGAME_GM_MODEL", GM_MODEL_INTERACTIVE)


def gm_call_defaults(model: str) -> dict[str, Any]:
    """Call kwargs for a GM route.

    Agent routes (claude-code/*) take no fallback chain: a mixed agent/non-agent
    chain silently drops agent-only kwargs on the non-agent leg, and a
    subscription route has no spend to protect.
    """
    if model.startswith(("claude-code", "codex", "openai-agents")):
        return {
            "model_justification": (
                "Wargame GM adjudication on the Claude subscription via the "
                "claude-code agent route (observed cost 0.0). Used for unattended "
                "AI-vs-AI runs where latency does not matter."
            ),
        }
    return dict(LLM_CALL_DEFAULTS)


PARSER_MODEL = "openrouter/openai/gpt-5.6-luna"
AI_MODEL = "openrouter/openai/gpt-5.6-luna"
ADVISOR_MODEL = "openrouter/openai/gpt-5.6-luna"
SCORER_MODEL = "openrouter/openai/gpt-5.6-luna"

# Secondary route. Must support the same reasoning effort as the primary.
FALLBACK_MODELS = ["openrouter/openai/gpt-5.6-sol"]

REASONING_EFFORT = "low"

MODEL_JUSTIFICATION = (
    "Wargame turn loop: parser, GM adjudication and AI opponent are short "
    "structured-output calls. gpt-5.6-sol is declared as a fallback so one "
    "provider outage does not destroy an in-progress game."
)

# Spread into every call_llm_structured() invocation in this package.
# The GM route needs no fallback_models: a mixed agent/non-agent chain silently
# drops agent-only kwargs on the non-agent leg, and the subscription route has
# no spend to protect.

LLM_CALL_DEFAULTS: dict[str, Any] = {
    "reasoning_effort": REASONING_EFFORT,
    "fallback_models": FALLBACK_MODELS,
    "model_justification": MODEL_JUSTIFICATION,
}

# Per-call-site budget ceilings, in USD.
GM_MAX_BUDGET = 1.0
PARSER_MAX_BUDGET = 0.5
AI_MAX_BUDGET = 0.5
ADVISOR_MAX_BUDGET = 0.5
SCORER_MAX_BUDGET = 0.5

# Where finished/in-progress games are written. A file-backed database means a
# crashed run leaves a full forensic record instead of vanishing.
DEFAULT_DB_DIR = "games"
