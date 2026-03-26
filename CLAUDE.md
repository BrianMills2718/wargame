# wargame — Generative AI Geopolitical Wargame

LLM-driven geopolitical simulation where players issue natural language directives,
AI sub-agents act as a bureaucracy, and a programmatic core enforces physics.

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

## In Progress

- Phase 1: Programmatic core (state model, turn engine, adjudication)

## References

- `docs/ONE_PAGER.md` — architectural brief and risk matrix
- `docs/plans/01_implementation.md` — implementation plan with phases and acceptance criteria
