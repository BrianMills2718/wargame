# Wargame Roadmap

## Current: Notebook Verification Phase

Proving each contract in isolation before extracting to package. No code ships until NB8 passes.

| Notebook | Status | Gate |
|----------|--------|------|
| NB1: Causal Engine | ✅ Done | All mechanics verified, trajectories coherent |
| NB2: GM Pipeline | ✅ Done | 5/5 valid, calibrated, $0.005/call |
| NB3: Full Turn | ✅ Done | 5 turns coherent, feedback loops visible |
| NB4: Parser | ✅ Done | 10/10 valid, zero hallucinated instruments |
| NB5: Fog of War | Planned | Information barrier holds, Bayesian updates work |
| NB6: Sub-Agents | Planned | Anti-sycophancy test passes, no info leaks |
| NB7: AI Opponent | Planned | Character models produce measurably different behavior |
| NB8: Full AI-vs-AI | Planned | 20 turns complete, scoring coherent, cost < $20 |

**Gate to Milestone 1:** All 8 notebooks pass. Extract to `wargame/*.py` package.

## Milestone 1: Playable Game (CLI)

Single scenario (US-Iran), CLI interface, all play modes.

- [ ] Package extracted from verified notebooks
- [ ] CLI interface for human play
- [ ] AI opponent (realistic + probabilistic modes)
- [ ] End-of-game scoring
- [ ] Prompt templates migrated to YAML/Jinja2

**Success:** Two humans (or human vs AI) play a full 20-turn game. Scoring is coherent. Cost < $20.

## Milestone 2: Dynamic Agents (ADR-003)

GM can instantiate transient agents when phenomena become relevant.

- [ ] Active agents table and compute budget tracking
- [ ] GM prompt extended with agent instantiation capability
- [ ] Agent template library (American public opinion, allied reactions, IRGC politics)
- [ ] Standard agent output format (proposed deltas + narrative)
- [ ] Agent lifecycle management (activate, maintain, deactivate)

**Success:** A game where the GM dynamically creates a "public opinion" agent that meaningfully affects outcomes.

## Milestone 3: Web UI

Move from CLI to web-based interface.

- [ ] FastAPI backend wrapping the game engine
- [ ] WebSocket-based turn submission
- [ ] State visualization (variable trajectories, map view)
- [ ] Sub-agent chat interface

**Success:** Two players can play via browser.

## Future (not prioritized)

- Multiple scenarios beyond US-Iran
- Non-unitary actors (factions with independent agency)
- World model revision (actors update causal assumptions based on outcomes)
- Internet-enriched realism (web search for current events via open_web_retrieval)
- Batch AI-vs-AI analysis (100+ games for outcome distribution research)
- prompt_eval integration for systematic GM quality assessment
- Threshold/escalation ladder model types in the mechanical engine
- Stochastic causal propagation (noise on edge effects)

## Open Uncertainties

| ID | Question | Resolved by |
|----|----------|-------------|
| U1 | Can GM produce calibrated probabilities? | ✅ NB2 (yes, with base rate anchoring) |
| U2 | How much context fits in GM prompt? | ✅ NB2 (~764 tokens, no issue) |
| U3 | Does per-actor state estimation add value? | NB5 |
| U4 | How to handle simultaneous action interactions? | NB8 |
| U5 | Is the resource budget fun? | NB8 playtesting |
| U6 | Does sub-agent red-teaming prevent sycophancy? | NB6 |
| U7 | Are causal edge weights well-calibrated? | ✅ NB1+NB3 (plausible trajectories) |
| U8 | Does base rate anchoring improve GM output? | ✅ NB2 (yes, all within ±0.15) |

## Architectural Decisions

| ADR | Decision | Status |
|-----|----------|--------|
| ADR-001 | Mechanical engine vs LLM judgment split | Accepted, implemented |
| ADR-002 | Additive layers (mechanical + GM), no implicit algebra | Accepted, implemented |
| ADR-003 | Dynamic agent population architecture | Accepted, design only (Milestone 2) |

## Off-the-shelf evaluation (not yet done)

Should evaluate before Milestone 2:
- NetworkX or similar for causal graph operations (currently hand-rolled)
- LangGraph/CrewAI for agent orchestration (currently not needed, may need for ADR-003)
- Existing game state management frameworks
