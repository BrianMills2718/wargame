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
python -m src.core.engine            # run a test turn (when implemented)
```

## Principles

- **Programmatic core is source of truth** — LLMs advise, core decides
- **Strict structured outputs** — Pydantic schemas for all LLM boundaries
- **Thin spine dictionary** — 15-20 predefined state variables, no ontological drift
- **RNG friction** — no covert action >60% success without overwhelming capability
- **Fog of war** — players see filtered observations, never raw state
- **Fail loud** — invalid LLM output raises, doesn't silently degrade
- **Commit early and often** — every passing test suite gets a commit

## Current State

Phase 1 partially built (3/6 criteria checked in plan):
- src/core/models.py — `WorldState`, state entities, and adjudication models
- src/core/engine.py — turn processing plus fog-of-war observation filtering
- src/core/scenario_loader.py — JSON/YAML scenario loading into validated world state
- tests/ — 10 passing pytest cases across engine, observation, and scenario loading

Remaining Phase 1 per `docs/plans/01_implementation.md`:
- State model acceptance item
- Turn engine acceptance item
- CLI smoke test

## References

- `docs/ONE_PAGER.md` — architectural brief and risk matrix
- `docs/plans/01_implementation.md` — implementation plan with phases and acceptance criteria
