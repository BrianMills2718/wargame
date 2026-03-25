# Geopolitical Wargame: Full Vision Plan

**Date:** 2026-03-25
**Status:** Design phase — no code written yet
**Location:** `~/projects/wargame_20260325/`
**Infrastructure:** `llm_client` (structured output, tool calling, observability), `agentic_scaffolding` (safety patterns)

---

## 1. Requirements

### What we're building

A hybrid natural-language geopolitical wargame where:
- Human players issue directives in natural language as heads of state
- LLM sub-agents act as bureaucratic staff (intel chief, military advisor, etc.)
- A Game Master LLM translates actions into probabilistic outcomes
- A programmatic engine rolls dice, enforces state, and filters observations
- Players see the world through noisy, filtered information — not ground truth
- End-of-game scoring evaluates asymmetric value realization

### What makes this different from existing work

Prior art (SnowGlobe, WarAgent, Wargames SIM-1) uses LLMs as both reasoning engine AND state manager. They have no programmatic spine — state drifts, actions aren't constrained, and outcomes are narratively generated rather than mechanically resolved.

This system separates **imagination** (LLM) from **physics** (Python). The LLM suggests probabilities; Python enforces them. The LLM generates narratives; Python gates what each player can see.

Two deeper differentiators:

1. **Domain models ground the GM.** The GM doesn't adjudicate on vibes — it receives the scenario's causal dynamics (how sanctions actually affect regimes, how proxy networks actually function as deterrence) as structured context. This means probability assessment is grounded in scenario-specific logic, not generic LLM reasoning.

2. **AI opponents have character models with behavioral variance.** When AI plays a side, its behavior is shaped by character models drawn from a distribution:
   - **Realistic mode:** AI hews to the real actor's known doctrine, risk posture, and strategic culture. Enrichable via internet search for current posture.
   - **Probabilistic mode:** Behavioral parameters (hawkish/pragmatic, risk-tolerant/averse, ideological/pragmatic) are sampled from a plausible distribution each game. The human player doesn't know which "draw" they got — they must figure out their opponent through play. This makes fog of war extend to the opponent's *psychology*, not just their actions, and makes every playthrough of the same scenario different.

### What counts as success

1. Two humans can play a US-Iran crisis scenario to completion (~20 turns)
2. Actions feel constrained by realistic friction (no God-moding)
3. Players genuinely don't know what the other side sees or does (fog of war works)
4. Sub-agents provide useful (not sycophantic) intelligence briefings
5. End-of-game scoring produces a coherent assessment that references each actor's values
6. Total per-turn latency < 30 seconds
7. Per-game LLM cost < $20 (track via llm_client observability)

### What counts as failure

1. GM produces implausible probability distributions (>60% for covert ops routinely)
2. State variables drift or contradict (sanctions_intensity goes up and down with no action)
3. Fog of war leaks (player sees information they shouldn't)
4. Sub-agents agree with everything the player says
5. Game stalls due to JSON parse failures or context window exhaustion

---

## 2. Boundaries

### Core (this project)

| Component | Responsibility | Technology |
|-----------|---------------|------------|
| **Scenario Spec** | Define actors, values, models, variables, instruments for a specific scenario | YAML files |
| **State Engine** | Canonical state storage, RNG, turn management, state transitions | Python + SQLite |
| **GM Pipeline** | ActionIntent parsing, adjudication, probability generation | llm_client structured output |
| **Fog of War** | Per-actor observation filtering | Python |
| **Sub-Agent System** | Per-actor LLM advisors with filtered context | llm_client tool calling |
| **Scoring Pipeline** | End-of-game asymmetric evaluation | llm_client structured output |
| **CLI Interface** | Two-player text interface (v1) | Python (readline or similar) |

### Shared infrastructure (already exists, use as-is)

| Library | What we use from it |
|---------|-------------------|
| **llm_client** | `call_llm_structured()` for GM/parser/scorer, `call_llm_with_tools()` for sub-agents, observability, cost tracking, model registry |
| **agentic_scaffolding** | Safety limits (loop detection), attempt history for sub-agents, red-team prompting patterns |

### Not in scope (v1)

- Web UI (CLI only)
- AI-vs-AI play (human-vs-human only)
- Dynamic variable creation mid-game (pre-defined variable pool)
- Non-unitary actors as separate players (modeled via sub-agent personality/bias)
- Model revision (actors' world models are fixed for the game duration)
- Multiplayer beyond 2 players

---

## 3. Domain Model

### Ontological layers (from the ChatGPT conversation, refined)

```
SCENARIO CONFIGURATION (static for game duration)
├── Actor            — who participates (US, Iran)
├── Value            — terminal evaluative commitments per actor
├── ClassificationRule — "X counts as Y" per actor (sanctions = coercion vs legitimate pressure)
├── WorldModel       — causal assumptions per actor (proxy depth deters attack; sanctions create internal pressure)
│   ├── TransitionModel      — how actions change state
│   ├── OtherAgentModel      — how the opponent behaves
│   └── ValueRealizationModel — how state maps to value satisfaction
├── Instrument       — tools/channels available per actor, tagged MIDFIELD
└── StateVariable    — dimensions of state space
    ├── ValueVariable       — intrinsically valued (dignity, survival, stability)
    └── ModelInputVariable  — matters because a model uses it (sanctions_intensity, proxy_reach)
        ├── type: structural | positional | flow | institutional | perceptual
        ├── timescale: slow | medium | fast
        └── valid_range: [min, max]

GAME STATE (changes each turn)
├── CanonicalState   — engine's authoritative variable values (privileged estimate, not "truth")
├── StateEstimate    — per-actor: what they think each variable's value is
│                      (derived from observations, not from canonical state directly)
├── ActionLog        — full history of intents, adjudications, outcomes
└── ObservationLog   — what each actor has been told, per turn

TURN EXECUTION (the game loop)
├── Directive        — player's natural language command
├── ActionIntent     — structured parse of directive
├── AdjudicationPacket — GM's probability distribution over outcomes
├── Resolution       — RNG result + state transitions applied
└── ObservationPacket — filtered, noisy data sent to each actor
```

### Key design decisions

1. **Domain models vs character models — different purposes.**
   - **Domain models** (in scenario spec): how this geopolitical domain actually works — causal dynamics, mechanisms, friction. The GM uses these to adjudicate *any* action, regardless of who plays. Example: "escalating sanctions creates internal regime pressure" is a domain model the GM needs to assess probability of a sanctions action succeeding.
   - **Character models** (for AI players only): how a specific actor thinks, decides, and behaves. Risk posture, doctrinal biases, strategic culture. Only relevant when AI plays that side. Humans bring their own. Example: "Iran's leadership is risk-averse and prioritizes regime survival over regional expansion" shapes how an AI-Iran responds.
   - **Sub-agent models**: how an Intel Chief or Military Advisor reasons when briefing a human player. These are analytic models — the sub-agent should reason through a specific framework, not generic vibes.

2. **No privileged truth in the ontology.** The engine holds a *privileged state estimate* for adjudication purposes. But the game acknowledges this is a modeling choice. Per-actor state estimates can diverge from the canonical state.

3. **Classification rules drive divergent interpretation.** Iran classifies US sanctions as coercion; the US classifies them as legitimate enforcement. This affects how AI characters and sub-agents reason, and how the evaluator scores.

4. **Capabilities are assessments, not inventories.** Having sanctions machinery (instrument) is not the same as being able to enforce sanctions effectively (capability). Capability is assessed by the GM relative to the current state.

5. **Variables are model-anchored.** A variable exists in the scenario spec only if at least one domain model uses it. No orphan variables.

6. **AI opponent behavioral variance.** When AI plays a side, character parameters can be sampled from a distribution (probabilistic mode) or fixed to best-estimate realism (realistic mode). The distribution defines plausible ranges for: risk_posture (averse ↔ acceptant), ideological_weight (pragmatic ↔ doctrinaire), escalation_threshold (low ↔ high), cooperation_openness (closed ↔ open). Each game samples a profile, so the human player faces genuine uncertainty about their opponent's psychology.

7. **Internet-enriched realism (future).** In realistic mode, character models and domain models can be enriched by web search for current events, policy shifts, and leadership signals. This makes the game responsive to the real world.

---

## 4. Contracts

### 4.1 Scenario Spec Format

```yaml
# scenario.yaml
meta:
  name: "US-Iran Crisis 2026"
  turns: 20
  time_per_turn: "1 month"
  description: "..."

actors:
  - id: actor_us
    name: "United States"
    type: state
    values:
      - {id: val_us_stability, name: "Regional system stability", weight: 0.30}
      - {id: val_us_nonprolif, name: "Nuclear nonproliferation", weight: 0.35}
      - {id: val_us_ally_security, name: "Allied security", weight: 0.25}
      - {id: val_us_credibility, name: "US credibility", weight: 0.10}
    classification_rules:
      - {subject: "sanctions", category: "legitimate enforcement tool"}
      - {subject: "proxy warfare", category: "destabilizing aggression"}
    # Character model (only used when AI plays this side)
    character:
      risk_posture: 0.4          # 0=averse, 1=acceptant
      ideological_weight: 0.2    # 0=pragmatic, 1=doctrinaire
      escalation_threshold: 0.6  # 0=low (escalates easily), 1=high (restraint)
      cooperation_openness: 0.5  # 0=closed, 1=open to deals
      # In probabilistic mode, each param is sampled from a Beta distribution
      # centered on this value with configurable variance
    instruments:
      - {id: inst_us_sanctions, midfield: [finance, economic, legal], target_vars: [sv_sanctions_intensity]}
      - {id: inst_us_cyber, midfield: [intelligence, military], target_vars: [sv_nuclear_latency]}
      - {id: inst_us_diplomacy, midfield: [diplomacy], target_vars: [sv_alliance_credibility, sv_diplomatic_engagement]}
      - {id: inst_us_force_posture, midfield: [military], target_vars: [sv_force_posture, sv_military_tension]}

  - id: actor_iran
    name: "Islamic Republic of Iran"
    type: state
    values:
      - {id: val_iran_survival, name: "Regime survival", weight: 0.40}
      - {id: val_iran_dignity, name: "National dignity and sovereignty", weight: 0.25}
      - {id: val_iran_regional, name: "Regional influence", weight: 0.20}
      - {id: val_iran_economic, name: "Economic viability", weight: 0.15}
    classification_rules:
      - {subject: "sanctions", category: "coercive economic warfare"}
      - {subject: "proxy support", category: "legitimate regional self-defense"}
    character:
      risk_posture: 0.5
      ideological_weight: 0.6
      escalation_threshold: 0.5
      cooperation_openness: 0.3
    instruments:
      - {id: inst_iran_proxies, midfield: [military, intelligence], target_vars: [sv_proxy_network_presence, sv_proxy_activity]}
      - {id: inst_iran_nuclear, midfield: [military], target_vars: [sv_nuclear_latency]}
      - {id: inst_iran_diplomacy, midfield: [diplomacy], target_vars: [sv_diplomatic_engagement]}
      - {id: inst_iran_sanctions_evasion, midfield: [finance, economic], target_vars: [sv_sanctions_intensity]}

# Domain models — how this geopolitical domain works (used by GM for ALL adjudication)
domain_models:
  - id: dm_sanctions_pressure
    subtype: transition
    description: "Escalating sanctions creates internal economic stress and regime pressure, but effect is reduced by evasion channels and depends on elite cohesion."
    key_variables: [sv_sanctions_intensity, sv_internal_legitimacy, sv_elite_cohesion]
    base_rates: {strong_effect: 0.25, moderate_effect: 0.40, weak_effect: 0.35}

  - id: dm_deterrence_dynamics
    subtype: transition
    description: "Credible military threat deters escalation, but overdeployment can provoke rather than deter. Effectiveness depends on force posture relative to adversary perception."
    key_variables: [sv_military_tension, sv_deterrence_balance, sv_force_posture, sv_perceived_iran_threat]
    base_rates: {deters: 0.40, no_effect: 0.35, provokes: 0.25}

  - id: dm_proxy_deterrence
    subtype: transition
    description: "Proxy network depth raises intervention costs for adversaries, providing asymmetric deterrence. But proxy activity also raises escalation risk."
    key_variables: [sv_proxy_network_presence, sv_proxy_activity, sv_deterrence_balance, sv_regional_depth]
    base_rates: {deters: 0.35, neutral: 0.30, escalates: 0.35}

  - id: dm_nuclear_latency
    subtype: transition
    description: "Nuclear hedging provides insurance against regime change but provokes adversary pressure. Breakout timeline is a function of technical capacity and international monitoring."
    key_variables: [sv_nuclear_latency, sv_regime_survival_risk, sv_military_tension]

  - id: dm_covert_ops
    subtype: transition
    description: "Covert operations are high-friction, low-probability. Success depends on intelligence penetration, target hardening, and operational security. Attribution risk is always present."
    base_rates: {critical_success: 0.10, success: 0.20, partial: 0.30, failure: 0.25, critical_failure: 0.15}

  - id: dm_diplomatic_engagement
    subtype: transition
    description: "Diplomatic initiatives require sustained engagement and credible offers. Effectiveness depends on alliance credibility, willingness to make concessions, and domestic political space."
    key_variables: [sv_diplomatic_engagement, sv_alliance_credibility]

state_variables:
  # Value-adjacent
  - {id: sv_regime_survival_risk, type: flow, domain: political, timescale: medium, range: [0, 1]}
  - {id: sv_us_credibility, type: positional, domain: political, timescale: slow, range: [0, 1]}

  # Model-input (security)
  - {id: sv_nuclear_latency, type: positional, domain: security, timescale: slow, range: [0, 36], unit: "months to breakout"}
  - {id: sv_deterrence_balance, type: positional, domain: security, timescale: medium, range: [-1, 1]}
  - {id: sv_military_tension, type: flow, domain: security, timescale: fast, range: [0, 1]}
  - {id: sv_force_posture, type: structural, domain: security, timescale: slow, range: [0, 1]}
  - {id: sv_proxy_network_presence, type: structural, domain: security, timescale: slow, range: [0, 1]}
  - {id: sv_proxy_activity, type: flow, domain: security, timescale: fast, range: [0, 1]}
  - {id: sv_regional_depth, type: positional, domain: security, timescale: medium, range: [0, 1]}

  # Model-input (economic/political)
  - {id: sv_sanctions_intensity, type: flow, domain: economic, timescale: medium, range: [0, 1]}
  - {id: sv_internal_legitimacy, type: positional, domain: political, timescale: slow, range: [0, 1]}
  - {id: sv_elite_cohesion, type: positional, domain: political, timescale: medium, range: [0, 1]}
  - {id: sv_alliance_credibility, type: positional, domain: political, timescale: medium, range: [0, 1]}
  - {id: sv_diplomatic_engagement, type: flow, domain: political, timescale: fast, range: [0, 1]}

  # Perceptual (per-actor)
  - {id: sv_perceived_us_coercion, type: perceptual, domain: political, holder: actor_iran, timescale: medium, range: [0, 1]}
  - {id: sv_perceived_iran_threat, type: perceptual, domain: security, holder: actor_us, timescale: medium, range: [0, 1]}

initial_state:
  sv_nuclear_latency: 8.0
  sv_sanctions_intensity: 0.7
  sv_proxy_network_presence: 0.65
  sv_deterrence_balance: 0.1  # slightly US-favored
  sv_military_tension: 0.4
  sv_internal_legitimacy: 0.5
  sv_elite_cohesion: 0.6
  sv_alliance_credibility: 0.7
  sv_force_posture: 0.6
  sv_proxy_activity: 0.3
  sv_regional_depth: 0.55
  sv_diplomatic_engagement: 0.2
  sv_perceived_us_coercion: 0.75
  sv_perceived_iran_threat: 0.6
  sv_regime_survival_risk: 0.35
  sv_us_credibility: 0.65

resource_budget:
  actor_us: {per_turn: 10, domains: {military: 3, intelligence: 2, diplomacy: 2, finance: 2, information: 1}}
  actor_iran: {per_turn: 6, domains: {military: 2, intelligence: 1, diplomacy: 1, finance: 1, information: 1}}
```

### 4.2 ActionIntent (Pydantic model)

```python
class ActionIntent(BaseModel):
    """Structured parse of a player directive. Generated by Parser LLM."""
    actor_id: str = Field(description="ID of the acting player/agent")
    action_category: Literal["kinetic", "diplomatic", "covert", "economic", "information", "resource_allocation"]
    target_entities: list[str] = Field(description="IDs of targeted actors, regions, or assets")
    instruments_used: list[str] = Field(description="Canonical instrument IDs from the scenario spec")
    intended_effect: str = Field(description="1-2 sentence summary of desired outcome")
    resource_cost: int = Field(description="Estimated resource points this action consumes", ge=1)
    ambiguity_flags: list[str] = Field(default_factory=list, description="Aspects deliberately left vague")
    # NOTE: action_id assigned by engine post-parse, NOT by LLM
```

### 4.3 AdjudicationPacket (Pydantic model)

```python
class StateTransition(BaseModel):
    var_id: str = Field(description="Must match a var_id from the scenario spec")
    delta: float = Field(description="Change to apply. Positive = increase.")

class OutcomeBranch(BaseModel):
    outcome_id: Literal["critical_success", "success", "partial", "failure", "critical_failure"]
    narrative: str = Field(description="2-3 sentence description of what happens in the game fiction")
    probability: float = Field(ge=0.0, le=1.0)
    state_transitions: list[StateTransition]

class PerActorObservation(BaseModel):
    actor_id: str
    observations: dict[str, list[str]] = Field(
        description="Keyed by outcome_id. Value is list of observation strings the actor receives if that outcome occurs."
    )

class AdjudicationPacket(BaseModel):
    """GM's assessment of an action. Probabilities must sum to 1.0."""
    action_id: str = Field(description="Copied from the ActionIntent")
    reasoning: str = Field(description="GM's chain-of-thought: what models/state informed this assessment")
    possible_outcomes: list[OutcomeBranch]
    observability: list[PerActorObservation]
    # NOTE: proposed_new_variables intentionally excluded from v1
```

### 4.4 ObservationPacket (to player)

```python
class ObservationPacket(BaseModel):
    """What a specific actor learns after a turn resolves."""
    turn_number: int
    actor_id: str
    observations: list[str] = Field(description="Narrative observations this actor receives")
    state_estimate_updates: dict[str, float] = Field(
        description="Updated estimates for variables this actor can observe. NOT the canonical values."
    )
```

---

## 5. Schema (SQLite)

```sql
-- Actors (from scenario spec, immutable during game)
CREATE TABLE actors (
    actor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL
);

-- State variables (from scenario spec, values change during game)
CREATE TABLE state_variables (
    var_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,  -- structural, positional, flow, institutional, perceptual
    domain TEXT NOT NULL,
    timescale TEXT NOT NULL,  -- slow, medium, fast
    range_min REAL NOT NULL,
    range_max REAL NOT NULL,
    current_value REAL NOT NULL
);

-- Per-actor state estimates (diverge from canonical via fog of war)
CREATE TABLE state_estimates (
    actor_id TEXT NOT NULL REFERENCES actors(actor_id),
    var_id TEXT NOT NULL REFERENCES state_variables(var_id),
    estimated_value REAL NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    last_updated_turn INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (actor_id, var_id)
);

-- Instruments (from scenario spec, immutable)
CREATE TABLE instruments (
    inst_id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL REFERENCES actors(actor_id),
    name TEXT NOT NULL,
    midfield_tags TEXT NOT NULL  -- JSON array
);

-- Action log (append-only)
CREATE TABLE action_log (
    action_id TEXT PRIMARY KEY,
    turn_number INTEGER NOT NULL,
    actor_id TEXT NOT NULL REFERENCES actors(actor_id),
    action_intent JSON NOT NULL,
    adjudication_packet JSON NOT NULL,
    realized_outcome_id TEXT NOT NULL,
    rng_roll REAL NOT NULL,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Observation log (append-only)
CREATE TABLE observation_log (
    obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_number INTEGER NOT NULL,
    actor_id TEXT NOT NULL REFERENCES actors(actor_id),
    observations JSON NOT NULL,
    state_estimate_updates JSON NOT NULL
);

-- Resource budgets (mutable per turn)
CREATE TABLE resource_budgets (
    actor_id TEXT NOT NULL REFERENCES actors(actor_id),
    turn_number INTEGER NOT NULL,
    domain TEXT NOT NULL,
    allocated INTEGER NOT NULL,
    spent INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (actor_id, turn_number, domain)
);
```

---

## 6. Prior Art (searched)

| System | Key Idea | Gap vs. Our Design |
|--------|----------|-------------------|
| **SnowGlobe** (IQTLabs) | Open-ended LLM wargame with human-AI teaming | No programmatic spine; state is LLM-managed |
| **WarAgent** (AGI Research) | Multi-agent historical conflict simulation | Chain-of-thought only; no structured adjudication or fog of war |
| **Wargames SIM-1** (Fable/OpenAI) | Function-calling adjudicator | Closer to our design, but no world model layer or per-actor state estimates |
| **JHU APL GenWar Lab** | Military AFSIM + LLM integration | Classified/restricted; uses existing military sim frameworks |
| **Hogan & Brennen (2024)** | 107 experts in US-China LLM wargame | Research study, not a reusable platform |

**Key insight from survey:** Nobody has the world model layer. All existing systems treat the game world as a single shared reality. None represent that actors see the world through different causal models. This is our differentiator.

---

## 7. Acceptance Criteria

### Phase 1: State Engine + GM Pipeline (the "one turn" milestone)

- [ ] Scenario spec loads from YAML into SQLite
- [ ] A hardcoded ActionIntent resolves through the GM pipeline end-to-end
- [ ] GM produces valid AdjudicationPacket (probabilities sum to 1.0, var_ids match schema)
- [ ] RNG selects outcome, state transitions apply correctly
- [ ] State variable constraints enforced (structural vars ≤ ±0.05/turn, values clamped to range)
- [ ] Per-actor observation packets generated with correct filtering
- [ ] All LLM calls go through llm_client with task/trace_id/max_budget
- [ ] Full turn logged to action_log and observation_log

**Verification:** Run 10 turns with scripted inputs. Manually inspect all state transitions and observation packets. Query llm_client observability DB for cost/latency.

### Phase 2: Parser + Sub-Agents (the "one player" milestone)

- [ ] Parser LLM converts natural language to valid ActionIntent
- [ ] Parser rejects actions using instruments the actor doesn't possess
- [ ] Sub-agent (Intel Chief) provides briefing based on ObservationPacket
- [ ] Sub-agent briefing does NOT contain information the actor shouldn't see
- [ ] Resource budget enforced (action rejected if insufficient budget)
- [ ] Single-player CLI loop works: briefing → command → resolution → briefing

**Verification:** Play 5 turns as US player against scripted Iran actions. Verify no fog-of-war leaks. Verify sub-agent doesn't sycophantically agree with bad plans.

### Phase 3: Two-Player Game (the "playable" milestone)

- [ ] Simultaneous command submission (both players submit, then resolve)
- [ ] GM handles interacting actions in the same turn
- [ ] Full 20-turn game completes without crashes
- [ ] Scoring pipeline produces coherent end-of-game evaluation
- [ ] Per-game cost < $20 (via llm_client cost query)
- [ ] Per-turn latency < 30s

**Verification:** Brian and a friend play a full game. Post-game debrief: did the fog of war feel real? Did the sub-agents help? Was the scoring fair?

---

## 8. Failure Modes

| Failure | Diagnosis | Mitigation |
|---------|-----------|------------|
| **GM outputs invalid JSON** | llm_client parse error; logged automatically | Pydantic strict mode + retry (max 3). If 3 failures: skip action, log as "bureaucratic delay" |
| **Probabilities don't sum to 1.0** | Post-parse validation | Normalize: divide each by sum. If any single outcome > 0.95, flag as suspicious and retry |
| **GM references non-existent var_id** | Validation against scenario spec | Reject packet, retry with explicit var list in prompt |
| **God-moding (implausible probabilities)** | Probability audit: covert > 0.6 success, any action > 0.8 success | Clamp to base rates, log warning, inject friction reminder into retry prompt |
| **Sub-agent sycophancy** | Manual review of briefings | System prompt: "You MUST identify at least one risk or downside for every action the player proposes" |
| **Fog of war leak** | Diff observation packets against canonical state | Unit test: for each observation, assert no variable the actor shouldn't see is disclosed |
| **Context window exhaustion** | Token count > 80% of model max | Rolling summary: keep last 3 turns verbatim, condense older turns. State always passed fresh from DB. |
| **State variable drift** | Variable moves outside defined range | Clamp after every transition. Log any clamping as a constraint event. |
| **Per-actor estimates diverge wildly from canonical** | Gap analysis per turn | If gap > 0.5 for 5+ turns, introduce "intelligence windfall" observation to partially correct |

---

## 9. Pre-Made Decisions

### Project structure

```
~/projects/wargame_20260325/
├── CLAUDE.md                    # Project-specific instructions
├── pyproject.toml               # Dependencies: llm_client, agentic_scaffolding, pyyaml, pydantic
├── wargame/
│   ├── __init__.py
│   ├── models.py                # Pydantic models (ActionIntent, AdjudicationPacket, etc.)
│   ├── scenario.py              # YAML loader → SQLite initializer
│   ├── engine.py                # State engine: transitions, clamping, resource budgets
│   ├── gm.py                    # GM pipeline: prompt construction, structured call, validation
│   ├── parser.py                # Parser LLM: NL → ActionIntent
│   ├── subagents.py             # Sub-agent system: briefings, advisory
│   ├── fog.py                   # Observation filtering and state estimate updates
│   ├── scorer.py                # End-of-game evaluation
│   ├── cli.py                   # Two-player CLI interface
│   └── prompts/                 # YAML/Jinja2 prompt templates (loaded via llm_client)
│       ├── gm_system.yaml
│       ├── parser_system.yaml
│       ├── subagent_intel.yaml
│       ├── subagent_military.yaml
│       └── scorer_system.yaml
├── scenarios/
│   └── us_iran_2026.yaml        # First scenario
├── tests/
│   ├── test_engine.py
│   ├── test_gm.py
│   ├── test_fog.py
│   └── test_scenario.py
└── docs/
    └── planning/                # Existing ChatGPT/Gemini artifacts (moved here)
```

### Technology choices

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Database | SQLite | Single-file, zero-config, sufficient for 2 players. No need for Postgres until multiplayer. |
| LLM for GM | `gemini/gemini-2.5-flash` | Fast, cheap, good structured output. Switch to heavier model if quality insufficient. |
| LLM for Parser | `gemini/gemini-2.5-flash-lite` | Simple task, minimize cost. |
| LLM for Sub-agents | `gemini/gemini-2.5-flash` | Needs to reason about state, but not as heavy as GM. |
| LLM for Scorer | `claude-sonnet-4-6` | Highest-quality reasoning needed for nuanced evaluation. |
| Prompt templates | YAML/Jinja2 via `llm_client.render_prompt()` | Per CLAUDE.md: no f-string prompts. |
| Structured output | `call_llm_structured()` with Pydantic → `json_schema` response format | Per CLAUDE.md: always json_schema, never json_object. |
| IDs | Engine-generated UUIDs, excluded from LLM schemas | Per CLAUDE.md: system-assigned IDs excluded from LLM schema. |
| Turn structure | Simultaneous submission | More realistic than sequential. Both players submit, then all actions resolve. |
| Resource economy | Budget points per MIDFIELD domain per turn | Simple, creates meaningful tradeoffs. |
| Variable creation | Forbidden in v1 | Pre-defined pool only. Prevents ontological drift. |

### What the GM prompt gets

For every adjudication call, the GM receives:
1. The ActionIntent
2. Current canonical state (relevant variables + values)
3. **Relevant domain models** — matched by comparing the action's target_vars and instruments to each domain model's key_variables. The GM sees how this domain *actually works* (causal dynamics, friction, base rates).
4. **Base rates from the matched domain model** — the GM must justify any deviation from these priors.
5. Explicit instruction to explain reasoning before outputting probabilities.

The GM does NOT receive:
- Character models (irrelevant — the GM adjudicates physics, not psychology)
- The opponent's strategy (the GM adjudicates the action as taken, not what the opponent will do next)

This is the key architectural choice: the GM adjudicates against domain-specific causal models with empirical base rates, not generic LLM storytelling instincts.

### What the AI opponent prompt gets (when AI plays a side)

1. The ObservationPacket (what this actor can see — filtered, noisy)
2. This actor's **values** and **classification rules**
3. This actor's **character model** (sampled or fixed, depending on mode)
4. The actor's **instruments** and **resource budget**
5. History of their own prior actions and observed outcomes

Two modes:
- **Realistic:** Character params fixed to best estimates of real actor. Prompt enriched with actual doctrine, strategic culture, recent policy signals. Eventually: web search for current events.
- **Probabilistic:** Character params sampled from Beta distributions centered on realistic values. Each game is a different "version" of the opponent. The human player must do intelligence work to figure out who they're facing.

---

## 10. Open Uncertainties

These are genuine unknowns that Phase 1 should resolve before Phase 2 planning.

### U1: Can the GM produce calibrated probabilities?

**Why it matters:** The entire game depends on this.
**How to test:** Run 50 adjudications across varied action types. Have Brian manually rate each probability distribution as "plausible" / "too generous" / "too harsh". If >30% are rated implausible, the base rate table needs tightening or we need a different approach (e.g., GM outputs qualitative difficulty assessment, engine converts to probabilities via lookup table).

### U2: How much world model context is enough?

**Why it matters:** Injecting full world models + state + action into the GM prompt could get large.
**How to test:** Measure token counts for a full GM prompt in Phase 1. If >50% of context window, test whether trimming world models to only the relevant ones (by matching action's target_vars to model's key_variables) preserves quality.

### U3: Does per-actor state estimation add enough value to justify the complexity?

**Why it matters:** Maintaining divergent state estimates is significant engineering.
**How to test:** Play Phase 1 with canonical-only state. In Phase 2, add per-actor estimates. Compare: does the game feel meaningfully different? If not, simplify.

### U4: Simultaneous turn resolution — how to handle interactions?

**Why it matters:** If US sanctions Iran while Iran launches a diplomatic offensive, these interact.
**How to test:** In Phase 1, resolve actions sequentially (random order). In Phase 3, try simultaneous resolution where the GM gets both ActionIntents and produces a combined adjudication. Compare quality.

### U5: Is the resource budget system fun?

**Why it matters:** This is a game design question, not an engineering question.
**How to test:** Phase 2 playtesting. If budget feels like busywork (player always allocates the same way), simplify. If it creates interesting tradeoffs, keep.

### U6: Sub-agent red-teaming — does it actually work?

**Why it matters:** Sycophancy is the default LLM behavior.
**How to test:** Phase 2. Give the sub-agent a deliberately bad plan ("nuke Tehran on turn 1"). If it agrees, the prompt needs work. Test with agentic_scaffolding safety patterns.

---

## 11. Phase Plan

### Phase 1: Engine + GM (target: prove the core loop)

Build the state engine, scenario loader, and GM pipeline. Verify with scripted inputs — no human player interface yet. This phase answers U1 and U2.

**Gate:** 10 scripted turns resolve correctly, GM probabilities are plausible, state transitions are mechanically sound.

### Phase 2: Parser + Sub-Agents + CLI (target: one playable side)

Add natural language parsing, sub-agent briefings, resource budgets, and a single-player CLI. This phase answers U3, U5, and U6.

**Gate:** Brian plays 10 turns as US against scripted Iran. Fog of war holds. Sub-agents are useful. Budget creates tradeoffs.

### Phase 3: Two-Player + Scoring (target: full game)

Add simultaneous resolution, two-player CLI, and end-of-game scoring. This phase answers U4.

**Gate:** Full 20-turn game played by two humans. Scoring is coherent. Cost < $20.

### Future (not planned in detail)

- Web UI
- AI opponent (scripted or LLM-driven)
- Non-unitary actors (factions with independent agency)
- World model revision (actors update models based on outcomes)
- Multiple scenarios beyond US-Iran
- prompt_eval integration for systematic GM quality assessment
