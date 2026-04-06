# wargame — Generative AI Geopolitical Wargame

<!-- GENERATED FILE: DO NOT EDIT DIRECTLY -->
<!-- generated_by: scripts/meta/render_agents_md.py -->
<!-- canonical_claude: CLAUDE.md -->
<!-- canonical_relationships: scripts/relationships.yaml -->
<!-- canonical_relationships_sha256: 840b164dcfa4 -->
<!-- sync_check: python scripts/meta/check_agents_sync.py --check -->

This file is a generated Codex-oriented projection of repo governance.
Edit the canonical sources instead of editing this file directly.

Canonical governance sources:
- `CLAUDE.md` — human-readable project rules, workflow, and references
- `scripts/relationships.yaml` — machine-readable ADR, coupling, and required-reading graph

## Purpose

LLM-driven geopolitical simulation where players issue natural language directives,
AI sub-agents act as a bureaucracy, and a programmatic core enforces physics.

## Commands

```bash
python -m pytest tests/ -q          # run tests
python -m src.core                   # run a test turn through the package CLI
```

## Operating Rules

This projection keeps the highest-signal rules in always-on Codex context.
For full project structure, detailed terminology, and any rule omitted here,
read `CLAUDE.md` directly.

### Principles

- **Programmatic core is source of truth** — LLMs advise, core decides
- **Strict structured outputs** — Pydantic schemas for all LLM boundaries
- **Thin spine dictionary** — 15-20 predefined state variables, no ontological drift
- **RNG friction** — no covert action >60% success without overwhelming capability
- **Fog of war** — players see filtered observations, never raw state
- **Fail loud** — invalid LLM output raises, doesn't silently degrade
- **Commit early and often** — every passing test suite gets a commit

### Workflow

Use `docs/plans/` for implementation plans. Run `make test` before committing.

## Machine-Readable Governance

`scripts/relationships.yaml` is the source of truth for machine-readable governance in this repo: ADR coupling, required-reading edges, and doc-code linkage. This generated file does not inline that graph; it records the canonical path and sync marker, then points operators and validators back to the source graph. Prefer deterministic validators over prompt-only memory when those scripts are available.

## References

- `docs/ONE_PAGER.md` — architectural brief and risk matrix
- `docs/plans/01_implementation.md` — implementation plan with phases and acceptance criteria
