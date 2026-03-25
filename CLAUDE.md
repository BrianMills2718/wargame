# Wargame

Generative AI geopolitical wargame. Hybrid architecture: programmatic state engine + LLM adjudication.

## Key Documents

- `claude_code_planning/PLAN.md` — full vision, acceptance criteria, pre-made decisions
- `chatgpt_initial_discussion/` — 107k-token ontology conversation (chunked into 5 parts)
- `gemini_planning_based_on_chatgpt_discussion/` — PRD, schemas, architecture diagrams (ChatGPT/Gemini artifacts)

## Architecture

- **State Engine** (Python/SQLite): canonical state, RNG, transitions, fog of war
- **GM LLM**: translates ActionIntent + state + world models → AdjudicationPacket (probabilities)
- **Parser LLM**: natural language → ActionIntent (structured)
- **Sub-agent LLMs**: per-actor advisors with filtered context
- **Scorer LLM**: end-of-game asymmetric evaluation

LLMs never touch the database. They suggest; Python decides.

## Infrastructure

- All LLM calls via `llm_client` (`task=`, `trace_id=`, `max_budget=` required)
- Prompts as YAML/Jinja2 in `wargame/prompts/`, loaded via `render_prompt()`
- Structured output via `call_llm_structured()` with Pydantic → `json_schema` response format
- Safety patterns from `agentic_scaffolding` for sub-agent delegation
- System-assigned IDs excluded from LLM schemas; generated in Python, corrected post-parse

## Scenario Spec

Scenarios are YAML files in `scenarios/`. A scenario defines: actors, values, classification rules, world models, instruments, state variables, initial state, resource budgets. The engine is general; the scenario is specific.

## Key Design Principles

1. **Domain models vs character models.** Domain models (how sanctions/deterrence/proxy dynamics actually work) ground the GM's adjudication for ALL actions. Character models (risk posture, doctrine, biases) drive AI opponent behavior only — humans bring their own.
2. **AI opponent behavioral variance.** Probabilistic mode samples character params from a distribution each game, so the human player faces genuine psychological fog of war. Realistic mode fixes params to best-estimate real actor behavior, enrichable via web search.
3. **No privileged truth.** Engine holds a privileged state estimate for adjudication, not metaphysical truth. Per-actor estimates can diverge.
4. **Variables are model-anchored.** A variable exists only if at least one domain model uses it.
5. **No dynamic variable creation (v1).** Pre-defined pool only.
6. **Classification rules drive divergent interpretation.** Iran sees sanctions as coercion; US sees them as enforcement. Affects sub-agent reasoning and scoring.
7. **Capabilities are assessments, not inventories.** GM evaluates effectiveness relative to current state and domain model base rates.
