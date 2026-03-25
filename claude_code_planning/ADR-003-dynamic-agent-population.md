# ADR-003: Dynamic Agent Population Architecture

**Date:** 2026-03-25
**Status:** Accepted (design-level — implementation deferred to NB6+)
**Context:** The initial model library approach (ADR-001) pre-defined typed models (causal_linear, threshold, escalation_ladder) as the mechanical backbone. This is too rigid — it limits the game to phenomena the scenario designer anticipated and prevents emergent dynamics.

## Decision

The system has two layers: a **mechanical backbone** and a **dynamic agent population**.

### Mechanical backbone (engine — Python computes)

Handles physics — things that must be consistent and verifiable:
- State variables and their values (the shared ground truth)
- Resource budgets and depletion
- Turn structure and timing
- Basic causal tendencies (the causal_edges table — known structural regularities)
- Decay and momentum (autonomous dynamics)
- Range clamping, rate limits
- Fog of war filtering (who can see what)
- State history recording

The mechanical layer does NOT model behavior, psychology, or dynamics that depend on narrative context. It provides structure and constraints.

### Dynamic agent population (LLM agents — instantiated when relevant)

Handles creativity — open-ended phenomena that emerge during play:
- **Permanent agents:** Player-side sub-agents (Intel Chief, Military Advisor), AI opponents
- **Transient agents:** Instantiated by the GM when a phenomenon becomes relevant:
  - American public opinion (or sub-populations: hawks, doves, isolationists)
  - IRGC internal politics
  - UN Security Council dynamics
  - Allied governments' reactions
  - Media narratives
  - Black market / sanctions evasion networks

Each agent:
- Receives a prompt defining its perspective, values, and reasoning framework
- Reads state variables it has access to (fog-of-war permitting)
- Produces structured output (state change proposals, narrative text, assessments)
- Consumes resources from a per-turn compute budget (can't spin up infinite agents)
- Persists as long as the phenomenon is relevant, then goes dormant

### The GM as orchestrator

The GM's expanded role:
1. Adjudicate player actions (as before)
2. **Decide which transient agents are relevant** this turn ("public opinion matters now — instantiate")
3. **Route agent outputs** into the state system (public opinion agent says domestic support drops → GM proposes delta to relevant variables)
4. **Manage agent lifecycle** — activate, maintain, deactivate transient agents

### Interface between layers

| Direction | Mechanism |
|-----------|-----------|
| Agent → Engine | Agent proposes state deltas (structured JSON). Engine validates (var_id exists, within range, budget sufficient) and applies. |
| Engine → Agent | Engine provides current state variables (filtered by fog of war) and mechanical effects summary. |
| GM → Engine | GM requests agent instantiation/deactivation. Engine tracks active agents and compute budget. |
| Engine → GM | Engine provides active agent list, their recent outputs, and remaining compute budget. |

### Why this is better than a fixed model library

- **Open-ended:** Players can try things the scenario designer didn't anticipate. The GM decides what's relevant.
- **Emergent:** New phenomena arise from gameplay, not from pre-coded rules.
- **Creative:** Each agent is a full LLM with a perspective — it can reason, surprise, and fail in ways typed rules can't.
- **Compositional:** Multiple agents interact through the shared state, creating emergent dynamics without explicit interaction rules.

### What the causal graph still does

The causal_edges table stays as a baseline for **known structural tendencies** — sanctions tend to erode cohesion, proxy activity tends to increase tension. These are empirical regularities that shouldn't require an LLM to reinvent every turn. But agents (including the GM) can override them when the narrative warrants it (ADR-002).

### Resource constraint on agents

A per-turn agent compute budget prevents unbounded LLM calls:
- Each agent invocation costs N compute points
- Players and GM must prioritize which transient agents to activate
- This creates a meta-strategic choice: do you invest your compute budget in detailed intelligence analysis, or in modeling the opponent's domestic politics?

## Implementation phases

- **NB1-NB5 (current):** Permanent agents only (GM, parser, sub-agents). Mechanical backbone stable.
- **NB6+:** Sub-agents as first transient agents (Intel Chief activated per turn).
- **NB7+:** AI opponent as a complex agent with character model.
- **Future:** GM-initiated transient agents (public opinion, allied reactions, etc.)

## Consequences

- Engine needs an `active_agents` table and compute budget tracking
- GM prompt needs to include the option to request agent instantiation
- Agent outputs need a standard structured format (proposed deltas + narrative)
- Scenario spec should include agent templates (prompts for common transient agents like "American public opinion")
- Cost tracking becomes critical — each agent invocation is an LLM call
