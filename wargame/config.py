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

from typing import Any

# Primary route for all three call sites.
# The GM runs on the Claude subscription via the claude-code agent route, not
# on metered tokens: a probe returned cost 0.0. It is the most reasoning-heavy
# call in the system and the one whose quality decides whether the game is any
# good, so it is the one worth spending the subscription on. Everything else
# stays on a metered route because each claude-code call spawns a Claude Code
# process (~34s observed on a trivial call) and a parser call sits directly in
# front of a waiting human.
GM_MODEL = "claude-code/haiku"
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
GM_CALL_DEFAULTS: dict[str, Any] = {
    "model_justification": (
        "Wargame GM adjudication on the Claude subscription via the claude-code "
        "agent route (observed cost 0.0). It is the most reasoning-heavy call in "
        "the system and runs as one long conversation per game."
    ),
}

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
