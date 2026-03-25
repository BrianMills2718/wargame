# Wargame

Generative AI geopolitical wargame. Hybrid architecture: programmatic state engine + LLM adjudication.

**Product vision:** Infinite action space + internally coherent world. Players command in natural language — anything goes, including absurd actions. The world responds coherently through the mechanical engine and GM adjudication. The fun is discovering what works through play, not reading a rulebook.

**Long-term aspiration:** Start as a fun, accessible game. Move toward serious wargaming calibrated against real geopolitical dynamics, usable by think tanks and military planners.

## Key Documents

- `ROADMAP.md` — milestones, gates, uncertainty tracker
- `claude_code_planning/PLAN.md` — full vision, acceptance criteria, pre-made decisions
- `claude_code_planning/ADR-*.md` — architectural decisions (001-004)
- `chatgpt_initial_discussion/` — 107k-token ontology conversation (chunked into 5 parts)
- `gemini_planning_based_on_chatgpt_discussion/` — historical artifacts (superseded, see README)

## Architecture

- **State Engine** (Python/SQLite): canonical state, causal graph, decay/momentum, RNG, fog of war
- **GM LLM**: translates ActionIntent + state + domain models → AdjudicationPacket (probabilities). Mechanical base rates anchor the GM; it adjusts ±0.15 with justification. (ADR-001, ADR-002)
- **Parser LLM**: natural language → ActionIntent (structured)
- **In-game NPCs**: unreliable narrators inside the simulation (Intel Chief, Military Advisor). Part of fog of war. Can be fooled by deception. (ADR-004)
- **Out-of-game Helper**: reliable analyst per player. Knows it's a game. Sees everything the player sees + game mechanics. Cannot see behind fog of war. The accessibility layer — how players without IR expertise make informed decisions. (ADR-004)
- **AI Opponents**: LLM-driven actors with character models (realistic or probabilistic mode)
- **Scorer LLM**: end-of-game asymmetric evaluation
- **Dynamic transient agents**: GM can instantiate agents (public opinion, allied reactions) when phenomena become relevant. (ADR-003)

LLMs never touch the database. They suggest; Python decides.

## Infrastructure

- All LLM calls via `llm_client` (`task=`, `trace_id=`, `max_budget=` required)
- Structured output via `call_llm_structured()` with Pydantic → `json_schema` response format
- System-assigned IDs excluded from LLM schemas; generated in Python
- Prompts currently inline (to be migrated to YAML/Jinja2 when stabilized)

## Scenario Spec

Scenarios are YAML files in `scenarios/`. A scenario defines: actors, values, classification rules, domain models, character models, instruments, state variables, causal edges, variable dynamics, initial state, resource budgets. The engine is general; the scenario is specific.

## Architectural Decisions

| ADR | Decision |
|-----|----------|
| ADR-001 | Mechanical engine (causal graph, decay, base rates) vs LLM judgment (creative adjustment). Engine provides structural tendencies; LLM provides narrative exceptions. |
| ADR-002 | Additive layers. Mechanical phase runs first (S0→S1). GM sees post-mechanical state and outputs deltas from there. No implicit algebra. |
| ADR-003 | Dynamic agent population. GM can instantiate transient agents when phenomena become relevant. Mechanical backbone + dynamic agents, not a fixed model library. |
| ADR-004 | NPC vs helper agent distinction. NPCs are unreliable in-game characters (part of fog of war). Helper is a reliable out-of-game analyst (accessibility layer). |

## Key Design Principles

1. **Infinite action space.** Players are not constrained to menus. They command in natural language. The world responds coherently through the mechanical engine + GM, even to absurd actions.
2. **Sub-agents are core product.** NPCs and the helper agent are not optional — they are how the game handles the complexity gap between a deeply modeled world and a human who wants to have fun. Without them, only IR experts can play well.
3. **Domain models vs character models.** Domain models (how sanctions/deterrence/proxy dynamics actually work) ground the GM's adjudication for ALL actions. Character models (risk posture, doctrine, biases) drive AI opponent behavior only.
4. **No privileged truth.** Engine holds a privileged state estimate for adjudication, not metaphysical truth. Per-actor estimates can diverge.
5. **Variables are model-anchored.** A variable exists only if at least one domain model uses it.
6. **No dynamic variable creation (v1).** Pre-defined pool only.
7. **Classification rules drive divergent interpretation.** Iran sees sanctions as coercion; US sees them as enforcement.
8. **Capabilities are assessments, not inventories.** GM evaluates effectiveness relative to current state.
9. **AI opponent behavioral variance.** Probabilistic mode samples character params each game. Realistic mode fixes to best-estimate. Human player faces genuine psychological fog of war.
