# wargame — Generative AI Geopolitical Wargame

LLM-driven geopolitical simulation where players issue natural language directives,
AI sub-agents act as a bureaucracy, and a programmatic core enforces physics.

## AUTONOMOUS EXECUTION DIRECTIVE

**This project is under continuous autonomous development. DO NOT STOP.**

When working on this project:
1. Read `docs/plans/01_implementation.md` and find the next unchecked acceptance criterion
2. Implement it fully with tests
3. Run `python -m pytest tests/ -q` to verify
4. Commit with `[Plan #1]` prefix
5. Move to the next criterion. DO NOT STOP between criteria.
6. If blocked, log the blocker in a `## Blockers` section of the plan file and move
   to the next unblocked criterion. NEVER STOP for uncertainty — log it and continue.
7. When all Phase N criteria are checked, move to Phase N+1.
8. Continue through all 5 phases until the game is playable.

**Error handling**: If tests fail, fix them. If an approach doesn't work, try another.
After 3 failed attempts at the same criterion, log it as blocked and move on.
Do not ask for human input. Make reasonable decisions and document them.

## Architecture

Hybrid model: **Programmatic Core** (Python) for rigid physics + **LLMs** for
semantic translation, psychology, and open-ended action resolution.

| Component | Role | Implementation |
|-----------|------|---------------|
| Programmatic Core | Source of truth: state, RNG, turn sequence, observation filtering | Python + SQLite |
| Player Interface | Natural language directives, resource allocation, delegation | CLI (Phase 1), web (later) |
| Sub-Agent LLMs | Bureaucracy: Intel Chief, Diplomatic Envoy, etc. | llm_client structured output |
| Game Master LLM | Translation engine: NL actions → JSON adjudication packets | llm_client structured output |
| Strategic Expert LLM | Scoring engine: asymmetric value realization | llm_client structured output |

## Commands

```bash
python -m pytest tests/ -q          # run tests
python -m src.core                   # run a test turn through the package CLI
```

## Principles

- **Programmatic core is source of truth** — LLMs advise, core decides
- **Strict structured outputs** — Pydantic schemas for all LLM boundaries
- **Thin spine dictionary** — 15-20 predefined state variables, no ontological drift
- **RNG friction** — no covert action >60% success without overwhelming capability
- **Fog of war** — players see filtered observations, never raw state
- **Fail loud** — invalid LLM output raises, doesn't silently degrade
- **Commit early and often** — every passing test suite gets a commit

## How to Use llm_client (REQUIRED for Phases 2-5)

llm_client is installed in the venv (`pip install -e ~/projects/llm_client`).
**Every LLM call must use these patterns exactly.**

### Structured output (use for GM, sub-agents, scoring)

```python
from llm_client import call_llm_structured
from pydantic import BaseModel, Field

class MyResponse(BaseModel):
    """Describe what the LLM should output."""
    field_one: str = Field(description="What this field means")
    field_two: int = Field(description="What this field means")
    items: list[str] = Field(description="A list of things")

messages = [{"role": "user", "content": "Your prompt here"}]

result, meta = call_llm_structured(
    "gemini/gemini-2.5-flash",     # model name
    messages,                       # list of message dicts
    response_model=MyResponse,     # Pydantic class (NOT an instance)
    task="gm_adjudication",        # task name for observability
    trace_id="wargame.gm.turn_1",  # trace ID for cost tracking
    max_budget=1.0,                # max USD for this call
)
# result is a MyResponse instance (already validated)
# meta.cost is the USD cost of the call
print(result.field_one)
```

### Plain text output (use for narrative generation, reports)

```python
from llm_client import acall_llm  # async version

import asyncio

async def generate_report():
    result = await acall_llm(
        "gemini/gemini-2.5-flash",
        [{"role": "user", "content": "Write a briefing..."}],
        task="sub_agent_briefing",
        trace_id="wargame.agent.intel.turn_1",
        max_budget=0.5,
    )
    return result.content  # plain text string
```

### Prompt templates (YAML/Jinja2)

```python
from llm_client import render_prompt
from pathlib import Path

messages = render_prompt(
    Path("prompts/game_master.yaml"),
    world_state=world_state_text,
    player_action=action_text,
)
# Pass directly to call_llm_structured as the messages arg
```

### Key rules

- **Required kwargs on EVERY call**: `task=`, `trace_id=`, `max_budget=`
- **Always use `call_llm_structured` with `response_model=`** for structured output
  (NOT `call_llm` with `response_format`)
- **Model for bulk/fast work**: `gemini/gemini-2.5-flash`
- **Do NOT set max output tokens or request timeouts**
- **Pydantic Field descriptions** constrain LLM behavior at decode time — always include them

## Current State

Phase 1 partially built (4/6 criteria checked in plan):
- src/core/models.py — `WorldState`, state entities, and adjudication models
- src/core/engine.py — turn processing plus fog-of-war observation filtering
- src/core/scenario_loader.py — JSON/YAML scenario loading into validated world state
- src/core/__main__.py — package CLI smoke test loading `scenarios/us_iran.yaml`
- tests/ — pytest coverage across engine, observation, scenario loading, and CLI smoke execution

Remaining Phase 1 per `docs/plans/01_implementation.md`:
- State model acceptance item
- Turn engine acceptance item

## Phase 1 Component Documentation Status

All core modules have comprehensive docstrings covering module purpose,
class responsibilities, method contracts (args/returns/raises), and
architectural context.

| Module | Documentation | Notes |
|--------|--------------|-------|
| `src/core/models.py` | ✅ Complete | Module docstring with full entity/adjudication hierarchy; class, field, and validator docstrings |
| `src/core/engine.py` | ✅ Complete | Module docstring with turn-processing and fog-of-war visibility rules; all functions and methods documented with args/returns/raises |
| `src/core/scenario_loader.py` | ✅ Complete | Module docstring with format descriptions and normalisation pipeline; all functions documented with args/returns/raises |
| `src/core/__main__.py` | ✅ Complete | Module docstring explaining CLI smoke test purpose and usage; all helper functions documented |
| `tests/` | ✅ Adequate | 21 tests across 7 files covering engine, observation, scenario loading, GM schema, and CLI smoke execution |

## References

- `docs/ONE_PAGER.md` — architectural brief and risk matrix
- `docs/plans/01_implementation.md` — implementation plan with phases and acceptance criteria

## Workflow

Use `docs/plans/` for implementation plans. Run `make test` before committing.
