# ADR-001: Mechanical Engine vs LLM Judgment Split

**Date:** 2026-03-25
**Status:** Accepted
**Context:** The initial design relied almost entirely on LLM judgment for game dynamics (the GM generates probabilities from scratch, decides deltas, determines observations). This makes the game's quality entirely dependent on LLM quality and makes outcomes unverifiable.

## Decision

Split game mechanics into two layers: a **deterministic/stochastic mechanical engine** (Python) and an **LLM judgment layer** (creative interpretation on top of mechanical baselines).

### Mechanical (engine computes, no LLM)

| Mechanic | What it does |
|----------|-------------|
| **Causal graph propagation** | When a variable changes, downstream effects propagate along defined edges with specified effect sizes and lags |
| **Variable decay/momentum** | Variables naturally evolve each turn without action (tension eases, sanctions erode, nuclear program advances) |
| **Base rate computation** | Engine computes mechanical probability baselines from state (covert_base = 0.30 + modifiers from capability/target state) |
| **Bayesian state estimate updates** | Actor estimates update toward canonical values proportional to observation quality (intelligence investment) |
| **Multi-turn action progression** | Long actions advance each turn, consuming resources, with defined per-turn effects |
| **Range clamping** | Variables clamped to defined [min, max] after every transition |
| **Rate-of-change limits** | Structural variables limited to ±0.05/turn; flow variables unconstrained |
| **Resource budget enforcement** | Actions rejected if insufficient budget in the relevant domain |

### LLM judgment (creative interpretation)

| Function | What the LLM does |
|----------|-------------------|
| **Translating NL to ActionIntent** | Parser maps player prose to structured intent |
| **Primary variable targeting** | Parser determines which variables an action primarily affects |
| **Probability adjustment** | GM adjusts mechanical base rate by ±0.15 with explicit justification |
| **Narrative generation** | GM writes per-outcome narrative descriptions |
| **Observation content** | GM determines what the noisy signal says in natural language |
| **Sub-agent briefings** | Intel Chief interprets observations into actionable intelligence |
| **AI opponent decisions** | Character model drives strategic choices (when AI plays a side) |
| **End-of-game scoring** | Evaluator assesses value realization with full context |

### Why this split

1. **Verifiability:** Mechanical outputs can be unit tested. We know exactly why sanctions_intensity changed.
2. **Emergent dynamics:** Feedback loops emerge from the causal graph, not from LLM storytelling. The escalation spiral happens because edges create it.
3. **LLM constraint:** The GM can't God-mode because the base rate anchors it. Its role is marginal adjustment, not creation.
4. **Replayability:** Same initial state + same actions = same mechanical outcomes. Variance comes from RNG + LLM margin, not from LLM reinventing physics each turn.

### Risks

- Causal edge weights are hard to calibrate. Wrong weights → implausible dynamics. Mitigation: notebook testing with manual inspection.
- Decay rates determine game tempo. Too fast → everything resets; too slow → actions feel permanent. Mitigation: tune in Notebook 1.
- Base rate tables may feel too constraining if the GM has no room for creative assessment. Mitigation: ±0.15 margin is adjustable.

## Consequences

- Scenario YAML must include `causal_edges` and `variable_dynamics` sections
- SQLite schema needs `causal_edges` and `variable_dynamics` tables
- Engine must implement graph propagation, decay, and base rate computation
- GM prompt must include the mechanical base rate and constrain the LLM to justify deviations
