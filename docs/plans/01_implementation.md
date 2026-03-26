# Plan 01: Geopolitical Wargame Implementation

**Status**: In Progress
**Date**: 2026-03-25
**Source**: `docs/ONE_PAGER.md` (architectural brief)

---

## Vision

A geopolitical simulation where players issue natural language directives to
AI sub-agents (their "bureaucracy"), a Game Master LLM translates actions into
structured adjudication packets, and a programmatic Python core enforces physics
(state, RNG, fog of war, resource economy).

---

## Phase 1: Programmatic Core (start here)

Build the deterministic engine that everything else plugs into. No LLM calls
in this phase — just Python + tests.

### Acceptance Criteria

- [ ] **State model**: Pydantic models for `WorldState`, `Nation`, `Actor`, and
  the thin-spine dictionary (15-20 variables like `military_readiness`,
  `sanctions_intensity`, `proxy_morale`, `diplomatic_leverage`, `intel_coverage`,
  `public_opinion_domestic`, `public_opinion_international`, `economic_stability`,
  `nuclear_capability`, `alliance_cohesion`, `media_narrative_control`,
  `covert_ops_capacity`, `territorial_control`, `regime_stability`,
  `humanitarian_index`). All variables are integers 0-100.
- [ ] **Turn engine**: `TurnEngine` class that processes a turn: accepts an
  `AdjudicationPacket` (JSON-like dict with affected variables, probability
  distribution, visibility rules), rolls RNG, updates `WorldState`, returns
  `TurnResult` with what changed.
- [x] **Observation filter**: Given a `TurnResult` and a player ID, return only
  the observations that player is allowed to see (fog of war). Players never
  see raw state.
- [x] **Scenario loader**: Load an initial scenario from YAML (nations, starting
  state values, actor definitions, victory conditions).
- [x] **Test suite**: At least 10 tests covering state updates, RNG boundaries,
  observation filtering, and scenario loading.
- [x] **CLI smoke test**: `python -m src.core` loads a scenario, processes
  one hardcoded adjudication packet, prints the filtered observation for each
  player.

### Design Decisions

- SQLite for persistence (game state snapshots per turn for replay/undo)
- Pydantic for all data models (strict validation at boundaries)
- No LLM calls — this phase is pure deterministic Python
- One scenario to start: US-Iran proxy conflict (2 nations, 2-3 actors each)

---

## Phase 2: Game Master LLM

Wire the GM LLM that translates natural language actions into adjudication packets.

### Acceptance Criteria

- [ ] **GM prompt + schema**: System prompt for the GM LLM with Pydantic
  `AdjudicationPacket` schema. GM receives: current world state (thin spine
  values), player action (natural language), and outputs structured JSON.
- [ ] **Probability baselines**: GM prompt includes friction rules — no covert
  action >60% success without overwhelming capability advantage.
- [ ] **Round-trip test**: Player action → GM translation → Core adjudication →
  filtered observation. End-to-end on 3 different action types (military,
  diplomatic, covert).
- [ ] **Hallucination guard**: If GM outputs a variable name not in the thin
  spine dictionary, the core rejects the packet with a clear error (fail loud).
- [ ] **Cost tracking**: Every GM call tracked via llm_client with task/trace_id.

### Design Decisions

- Use llm_client structured output with `json_schema` response format
- GM prompt as YAML/Jinja2 template in `prompts/`
- Start with gemini-2.5-flash for cost (GM is high-volume)

---

## Phase 3: Sub-Agent Bureaucracy

Build the player-facing AI agents that interpret observations and advise.

### Acceptance Criteria

- [ ] **Agent definitions**: At least 3 sub-agent types (Intel Chief, Diplomatic
  Envoy, Military Advisor) with distinct system prompts and specializations.
- [ ] **Observation interpretation**: Sub-agents receive filtered observations
  (not raw state) and produce natural language briefings for the player.
- [ ] **Resource/attention economy**: Each sub-agent action costs attention points.
  Players have a budget per turn. Delegating to sub-agents is cheaper than
  direct action but noisier.
- [ ] **Sycophancy mitigation**: Sub-agent prompts include adversarial framing
  ("your job is to challenge assumptions, not confirm them").
- [ ] **Briefing quality test**: Compare sub-agent briefings against ground truth
  (raw state) on 5 scenarios. Briefings should be directionally correct but
  incomplete (fog of war working).

### Design Decisions

- Sub-agents are stateless per turn (no persistent memory beyond what's in
  the observation)
- Use cheaper models for sub-agents (gemini-flash or haiku)
- Player sees sub-agent briefings, never raw GM output

---

## Phase 4: Player Interface + Game Loop

Wire everything into a playable game loop.

### Acceptance Criteria

- [ ] **CLI game loop**: Player types natural language directives. System
  processes the turn (GM → Core → Sub-agents → Briefing). Next turn.
- [ ] **Turn history**: Condensed summary of prior turns injected into GM context
  (memory condensation pipeline). Keeps active context lean.
- [ ] **Multi-player**: 2 players (US + Iran) taking alternating turns. Each
  sees only their filtered observations.
- [ ] **Game end**: After N turns or when a victory condition triggers, the
  Strategic Expert LLM scores both players on asymmetric criteria.
- [ ] **Replay**: Full game state saved per turn to SQLite. Can replay any
  point.

---

## Phase 5: Scoring + Balance

### Acceptance Criteria

- [ ] **Strategic Expert prompt**: Scoring rubric for asymmetric evaluation
  (Iran: survival + dignity; US: containment + stability; etc.).
- [ ] **Anti-bias calibration**: Run 10 games with identical moves, verify
  scoring doesn't systematically favor one side.
- [ ] **Scenario balance**: Adjust starting state values so neither side has
  >65% win rate over 20 simulated games.

---

## Deferred

### Option B: Plan-from-one-pager (autonomous plan derivation)

It would be valuable for the mission runner to accept a raw one-pager or PRD
and autonomously derive implementation plans with acceptance criteria, without
requiring a human to write `docs/plans/01_*.md` first.

**Uncertainties to resolve before implementing:**
- How does the planner know what "Phase 1" scope should be? The one-pager
  describes the full system but doesn't indicate implementation order.
- How does the planner decide on technology choices (SQLite vs Postgres,
  which LLM model, etc.) without plan-level design decisions?
- How does the planner generate testable acceptance criteria from prose
  architecture descriptions?
- How does it avoid generating tasks that are too large for a single agent
  session?
- Does it need a "plan review" gate before execution, or can it go straight
  from one-pager to tasks?

This is deferred until the mission runner proves reliable on human-written
plans (Phase 1.5 validation). If that works, Option B becomes a natural
extension of the planner.

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| GM LLM hallucinates variable names | Core crashes or silently corrupts state | Thin spine dictionary + strict validation (fail loud) |
| Context window collapse on long games | GM loses track of game state | Memory condensation pipeline (Phase 4) |
| Ontological drift (new variables invented) | Causal tracking breaks | Dictionary is closed — GM cannot add variables |
| Sycophantic sub-agents | Players get false confidence | Adversarial prompting + briefing quality tests |
| Latency per turn (multiple LLM calls) | Unplayable | Cheap models for sub-agents, parallel calls where possible |
| Asymmetric scoring bias | Game feels unfair | Calibration test suite (Phase 5) |
