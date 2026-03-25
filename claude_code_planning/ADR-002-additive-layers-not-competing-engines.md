# ADR-002: Additive Layers, Not Competing Engines

**Date:** 2026-03-25
**Status:** Accepted
**Context:** External review (Gemini) identified that the causal graph and GM LLM could produce contradictory state changes — e.g., the causal graph drops elite_cohesion from sanctions while the GM's narrative says "rally around the flag" boosts it. This was framed as a "fatal flaw" requiring abolition of either the causal graph or the GM's narrative authority over secondary effects.

## Decision

**Neither system is abolished.** The mechanical engine and GM operate as **additive layers**, not competing engines.

### How it works

1. **Mechanical phase runs first** (decay, momentum, causal propagation, multi-turn actions). State moves from S0 → S1.
2. **GM sees the post-mechanical state S1** as "current state." The GM prompt includes what mechanical effects occurred (for context/understanding, NOT for algebra).
3. **GM outputs deltas relative to S1.** No implicit algebra required — the GM just sees the current state and decides what the action does. If the GM wants elite cohesion to go up despite the mechanical drop, it just outputs a positive delta. The mechanical drop already happened.
4. **Engine applies GM deltas.** S1 → S2. Clamping and rate limits enforced.

**Key design choice (updated after Gemini review of NB3):** The GM does NOT need to calculate relative to mechanical effects. It sees the state as-is and acts on it. Mechanical effects provide context ("legitimacy dropped due to sanctions erosion") but the GM's deltas are absolute from the current state, not relative to what the engine did.

### Why not abolish the causal graph (Gemini's Option A)

- Makes the game entirely LLM-dependent (defeats ADR-001)
- LLM won't maintain consistent structural dynamics over 20 turns
- Feedback loops only exist if the LLM remembers to create them (it won't)
- Loses verifiability — can't trace why a variable changed
- Degrades to "ask the LLM what happens" — the failure mode of every existing LLM wargame

### Why not abolish GM narrative authority (Gemini's Option B)

- The GM needs to generate countervailing effects when the narrative warrants it
- Real geopolitics has exceptions to structural tendencies — the framework must represent them
- Restricting the GM to only direct instrument effects makes the game feel mechanical

### Implementation changes

- `build_gm_messages()` must include the mechanical deltas from the current turn in the GM prompt
- GM prompt must say: "The following mechanical effects have been applied this turn. Your state_transitions are ADDITIONAL to these. If you believe the narrative should countervail a mechanical effect, output an explicit countervailing delta and explain why."
- Engine applies mechanical deltas first, then GM deltas, then records final state

## Also decided: Multi-Turn Action Disruption

Multi-turn actions are no longer guaranteed. Each turn, the engine checks a **disruption condition**: if any of the action's `target_var` dependencies have moved by >0.2 since the action started, the remaining effects are halved. Opponents can also take explicit disrupt actions.

This preserves the mechanical backbone while allowing reactive disruption.

## Also decided: Deception Affects Inputs, Not the Updater

The Bayesian state estimate updater stays mechanical. Deception actions affect the `observation_quality` parameter — reducing it to near-zero or making it negative (misleading signal). The math stays verifiable; the inputs get corrupted. Narrative deception lands in the sub-agent interpretation layer (the Intel Chief LLM reads misleading observations and may brief the player incorrectly).

## Consequences

- GM prompt construction must be updated to include mechanical deltas
- Multi-turn action engine must check disruption conditions
- Deception mechanics specified as observation_quality modifiers in the scenario spec
- Pydantic `@model_validator` added for probability sum enforcement
