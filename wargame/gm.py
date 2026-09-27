"""Game Master pipeline — LLM-based adjudication with mechanical base rate anchoring.

The GM receives an ActionIntent, current state, relevant domain models, and a
mechanical base rate. It outputs an AdjudicationPacket with probabilities that
must stay within ±0.15 of the base rate per outcome category.
"""

from __future__ import annotations

import json
from typing import Any

from wargame.models import (
    ActionIntent,
    AdjudicationPacket,
    DomainModel,
    OutcomeBranch,
    PerActorObservation,
    ScenarioSpec,
    StateTransition,
)


# Outcome ladder, worst to best. State pressure moves probability mass along it.
OUTCOME_LADDER = ["critical_failure", "failure", "partial", "success", "critical_success"]
WORST_TWO = ("critical_failure", "failure")
BEST_TWO = ("success", "critical_success")
MAX_TOTAL_SHIFT = 0.30


def _format_mechanical_deltas(deltas: dict[str, float] | None) -> str:
    """Format mechanical deltas for inclusion in GM prompt."""
    if not deltas:
        return "None this turn."
    lines = []
    for var_id, delta in sorted(deltas.items()):
        lines.append(f"  {var_id}: {delta:+.4f}")
    return "\n".join(lines) + "\nThese have already been applied. The Current State above reflects them."


def score_domain_model(dm: DomainModel, action: ActionIntent, action_vars: set[str]) -> float:
    """Relevance of one domain model to one action. Higher is more relevant.

    Variable overlap is the strong signal (the model actually describes the
    machinery this action touches); a declared category match is a weaker one.
    """
    score = 2.0 * len(action_vars & set(dm.key_variables))
    if action.action_category in dm.categories:
        score += 1.0
    return score


def select_relevant_domain_models(
    spec: ScenarioSpec,
    action: ActionIntent,
) -> list[DomainModel]:
    """Domain models relevant to this action, most relevant first.

    Selection used to be first-match in YAML order, which meant a nuclear
    breakout attempt, a proxy attack and a missile exercise all drew
    dm_deterrence_dynamics simply because it appeared earlier in the file.
    Ties keep declaration order, so selection stays deterministic.
    """
    action_vars: set[str] = set()
    for actor in spec.actors:
        for inst in actor.instruments:
            if inst.id in action.instruments_used:
                action_vars.update(inst.target_vars)

    scored = [
        (score_domain_model(dm, action, action_vars), index, dm)
        for index, dm in enumerate(spec.domain_models)
    ]
    relevant = [entry for entry in scored if entry[0] > 0]
    relevant.sort(key=lambda entry: (-entry[0], entry[1]))
    return [dm for _, _, dm in relevant]


def compute_state_shift(dm: DomainModel, state: dict[str, float]) -> tuple[float, list[str]]:
    """Total success pressure this domain model's state conditions produce.

    Returns (shift, reasons). The shift is clamped to +/-MAX_TOTAL_SHIFT so no
    combination of conditions can flip an action from hard to certain.
    """
    total = 0.0
    reasons: list[str] = []
    for cond in dm.state_conditions:
        value = state.get(cond.variable)
        if value is None:
            continue
        fired = (
            (cond.above is not None and value > cond.above)
            or (cond.below is not None and value < cond.below)
        )
        if fired:
            total += cond.shift
            reasons.append(f"{cond.variable}={value:.2f} {cond.shift:+.2f} ({cond.note})")
    return max(-MAX_TOTAL_SHIFT, min(MAX_TOTAL_SHIFT, total)), reasons


def apply_state_shift(base_rates: dict[str, float], shift: float) -> dict[str, float]:
    """Move probability mass along the outcome ladder by `shift`.

    A positive shift moves that fraction of the mass sitting on the two worst
    outcomes onto the two best, split in proportion to their existing weight.
    A negative shift mirrors it. `partial` is never touched, and the total is
    preserved exactly, so the result still sums to 1.0.
    """
    rates = dict(base_rates)
    if shift == 0.0:
        return rates

    src = WORST_TWO if shift > 0 else BEST_TWO
    dst = BEST_TWO if shift > 0 else WORST_TWO
    magnitude = abs(shift)

    moved = 0.0
    for key in src:
        take = rates.get(key, 0.0) * magnitude
        rates[key] = rates.get(key, 0.0) - take
        moved += take

    dst_total = sum(rates.get(key, 0.0) for key in dst)
    if dst_total <= 0.0:
        for key in dst:
            rates[key] = rates.get(key, 0.0) + moved / len(dst)
    else:
        weights = {key: rates.get(key, 0.0) / dst_total for key in dst}
        for key in dst:
            rates[key] = rates.get(key, 0.0) + moved * weights[key]
    return rates


def explain_base_rate(
    domain_models: list[DomainModel],
    state: dict[str, float],
) -> list[str]:
    """Human-readable reasons the base rate moved off its declared value."""
    for dm in domain_models:
        if dm.base_rates:
            _, reasons = compute_state_shift(dm, state)
            return [f"{dm.id}: {r}" for r in reasons]
    return []


def compute_mechanical_base_rate(
    domain_models: list[DomainModel],
    action: ActionIntent,
    state: dict[str, float],
) -> dict[str, float]:
    """Compute a mechanical base rate from domain models and current state.

    Returns a dict of outcome_id -> probability as the baseline the GM must anchor to.
    If no base rates are defined, returns a default distribution.
    """
    # The most relevant domain model that declares base rates supplies them,
    # then its state conditions shift mass along the outcome ladder. The state
    # argument used to be accepted and ignored, so the odds were identical
    # every turn no matter what the world looked like.
    for dm in domain_models:
        if dm.base_rates:
            shift, _ = compute_state_shift(dm, state)
            return apply_state_shift(dm.base_rates, shift)

    # Default base rates by action category
    defaults = {
        "covert": {"critical_success": 0.10, "success": 0.20, "partial": 0.30, "failure": 0.25, "critical_failure": 0.15},
        "kinetic": {"critical_success": 0.05, "success": 0.25, "partial": 0.35, "failure": 0.25, "critical_failure": 0.10},
        "diplomatic": {"critical_success": 0.05, "success": 0.25, "partial": 0.40, "failure": 0.25, "critical_failure": 0.05},
        "economic": {"critical_success": 0.10, "success": 0.25, "partial": 0.35, "failure": 0.25, "critical_failure": 0.05},
        "information": {"critical_success": 0.05, "success": 0.20, "partial": 0.40, "failure": 0.30, "critical_failure": 0.05},
        "resource_allocation": {"critical_success": 0.10, "success": 0.40, "partial": 0.30, "failure": 0.15, "critical_failure": 0.05},
    }
    return defaults.get(action.action_category, defaults["diplomatic"])


def format_turn_history(history: list[dict], max_narrative_chars: int = 220) -> str:
    """Render prior turns for the GM prompt, oldest first."""
    if not history:
        return "This is the first turn. Nothing has happened yet."

    lines: list[str] = []
    current_turn = None
    for entry in history:
        if entry["turn"] != current_turn:
            current_turn = entry["turn"]
            lines.append(f"\nTurn {current_turn}:")
        instruments = ", ".join(entry["instruments"]) or "none"
        lines.append(
            f"  {entry['actor_id']} [{entry['category']}; {instruments}] -> "
            f"{entry['outcome'].upper()}"
        )
        if entry["intent"]:
            lines.append(f"    intent: {entry['intent'][:max_narrative_chars]}")
        if entry["narrative"]:
            lines.append(f"    result: {entry['narrative'][:max_narrative_chars]}")
    return "\n".join(lines).strip()


def build_gm_messages(
    action: ActionIntent,
    state: dict[str, float],
    domain_models: list[DomainModel],
    base_rates: dict[str, float],
    actor_ids: list[str],
    variable_ids: list[str],
    mechanical_deltas: dict[str, float] | None = None,
    turn_history: list[dict] | None = None,
) -> list[dict[str, str]]:
    """Build the GM system + user messages for adjudication.

    Args:
        mechanical_deltas: Deltas already applied by the causal engine this turn.
            The GM's deltas are ADDITIONAL to these (ADR-002).

    Returns a list of message dicts suitable for llm_client.call_llm_structured().
    Will be migrated to YAML/Jinja2 templates once the prompt stabilizes.
    """
    # Format domain models
    dm_text = ""
    for dm in domain_models:
        dm_text += f"\n### {dm.id} ({dm.subtype})\n{dm.description}\n"
        if dm.key_variables:
            dm_text += f"Key variables: {', '.join(dm.key_variables)}\n"

    # Format state
    state_text = "\n".join(f"  {k}: {v:.3f}" for k, v in sorted(state.items()))

    # Format base rates
    br_text = "\n".join(f"  {k}: {v:.2f}" for k, v in base_rates.items())

    system_prompt = """You are the Adjudication Engine for a strict geopolitical simulation.

You will receive an ActionIntent and the current game state. Your job is to output an AdjudicationPacket JSON defining the probability distribution of outcomes.

RULES:
1. NO GOD-MODING. Geopolitics is full of friction. Use the mechanical base rates as your anchor.
2. You may adjust each outcome probability by at most ±0.15 from the base rate, with explicit justification.
3. Your probabilities MUST sum to exactly 1.0.
4. All var_ids in state_transitions MUST come from the provided variable list.
5. State transition deltas should be small (typically ±0.05 to ±0.20). Large moves are rare.
6. Explain your reasoning BEFORE deciding probabilities.
7. For each outcome, describe what happens in 2-3 sentences.
8. For observability, specify what EACH actor sees for EACH possible outcome.
9. You are given what has already happened in this game. Use it. An overture that has already been refused twice is not the same action the third time; an actor that has just been humiliated responds differently; credibility spent earlier is not available now. Judge this action as the next move in a sequence, not in isolation.
10. The acting actor should generally know they attempted the action. The target actor should see effects proportional to the outcome's observability.

You must output EXACTLY 5 outcomes: critical_success, success, partial, failure, critical_failure.

NOTE: The "Current State" below ALREADY reflects any mechanical effects (decay, momentum, causal propagation) that occurred this turn. Your state_transitions are applied ON TOP of the current state values shown. You do NOT need to account for or reverse mechanical effects — just decide what the action does to the world as it currently stands."""

    user_prompt = f"""## Action to Adjudicate

Actor: {action.actor_id}
Category: {action.action_category}
Instruments: {', '.join(action.instruments_used)}
Targets: {', '.join(action.target_entities)}
Intended effect: {action.intended_effect}
Ambiguity flags: {', '.join(action.ambiguity_flags) if action.ambiguity_flags else 'none'}

## What Has Already Happened In This Game
{format_turn_history(turn_history or [])}

## Current State
{state_text}

## Relevant Domain Models
{dm_text}

## Mechanical Base Rates (your anchor — justify any deviation)
{br_text}

## Mechanical Effects Already Applied This Turn (context only — do not reverse or account for these)
{_format_mechanical_deltas(mechanical_deltas)}

## Valid Variable IDs (only use these in state_transitions)
{', '.join(variable_ids)}

## Actor IDs (use these in observability)
{', '.join(actor_ids)}

Generate the AdjudicationPacket."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def adjudication_structure_issues(
    packet: AdjudicationPacket,
    valid_var_ids: set[str],
    valid_actor_ids: set[str],
) -> list[str]:
    """Defects no repair can fix: the packet names things the scenario lacks.

    Such a packet must be re-requested or rejected, never applied. Contrast
    `adjudication_band_issues`, which clamping repairs.
    """
    issues = []
    for outcome in packet.possible_outcomes:
        for t in outcome.state_transitions:
            if t.var_id not in valid_var_ids:
                issues.append(f"Unknown var_id: {t.var_id}")

    for obs in packet.observability:
        if obs.actor_id not in valid_actor_ids:
            issues.append(f"Unknown actor_id in observability: {obs.actor_id}")

    outcome_ids = {o.outcome_id for o in packet.possible_outcomes}
    required = {"critical_success", "success", "partial", "failure", "critical_failure"}
    missing = required - outcome_ids
    if missing:
        issues.append(f"Missing outcome_ids: {missing}")
    return issues


def adjudication_band_issues(
    packet: AdjudicationPacket,
    base_rates: dict[str, float],
    tolerance: float = 0.15,
) -> list[str]:
    """Outcomes whose probability strays more than ±tolerance from the base rate
    (ADR-001 anti-god-moding). Repairable by `clamp_to_base_rates`."""
    issues = []
    for outcome in packet.possible_outcomes:
        base = base_rates.get(outcome.outcome_id)
        if base is not None:
            deviation = abs(outcome.probability - base)
            if deviation > tolerance:
                issues.append(
                    f"God-moding: {outcome.outcome_id} probability {outcome.probability:.2f} "
                    f"deviates {deviation:.2f} from base rate {base:.2f} (max ±{tolerance})"
                )
    return issues


def validate_adjudication(
    packet: AdjudicationPacket,
    valid_var_ids: set[str],
    valid_actor_ids: set[str],
    base_rates: dict[str, float],
    tolerance: float = 0.15,
) -> list[str]:
    """Validate an AdjudicationPacket. Returns list of issues (empty = valid).

    Mixes repairable and unrepairable issues; callers deciding what to do with a
    packet should use `adjudication_structure_issues` and
    `adjudication_band_issues` separately.
    """
    issues = []
    prob_sum = sum(o.probability for o in packet.possible_outcomes)
    if abs(prob_sum - 1.0) > 0.02:
        issues.append(f"Probabilities sum to {prob_sum:.4f}, not 1.0")
    issues.extend(adjudication_structure_issues(packet, valid_var_ids, valid_actor_ids))
    if base_rates:
        issues.extend(adjudication_band_issues(packet, base_rates, tolerance))
    return issues


def normalize_probabilities(packet: AdjudicationPacket) -> AdjudicationPacket:
    """Normalize probabilities to sum to exactly 1.0."""
    total = sum(o.probability for o in packet.possible_outcomes)
    if total == 0:
        # Uniform fallback
        n = len(packet.possible_outcomes)
        for o in packet.possible_outcomes:
            o.probability = 1.0 / n
    else:
        for o in packet.possible_outcomes:
            o.probability = o.probability / total
    return packet


def clamp_to_base_rates(
    packet: AdjudicationPacket,
    base_rates: dict[str, float],
    tolerance: float = 0.15,
    max_passes: int = 64,
) -> AdjudicationPacket:
    """Project the GM's distribution into its allowed band, keeping the sum at 1.0.

    ADR-001 says the GM may adjust each outcome by at most +/-`tolerance` from
    the mechanical base rate. `validate_adjudication` has always been able to
    detect a violation but was never called, so nothing enforced it. This is the
    enforcement.

    Clamping alone does not achieve it: clamp-then-renormalise pushes values
    straight back out of the band (a 0.70 success against a 0.20 base lands at
    0.41 when the ceiling is 0.35). So this alternates clamping with pushing the
    leftover probability into whatever headroom each outcome still has, which
    converges to a point inside every band summing to 1.0 whenever one exists.

    If the bands cannot sum to 1.0 -- possible when a scenario's base rates are
    themselves malformed -- it stops at the clamped values rather than looping,
    and the distribution will not sum to 1.0. The caller has already logged the
    original violation, and `resolve_action` handles a short distribution.
    """
    bounds: dict[str, tuple[float, float]] = {}
    for outcome in packet.possible_outcomes:
        base = base_rates.get(outcome.outcome_id)
        if base is None:
            bounds[outcome.outcome_id] = (0.0, 1.0)
        else:
            bounds[outcome.outcome_id] = (
                max(0.0, base - tolerance),
                min(1.0, base + tolerance),
            )

    probs = {o.outcome_id: o.probability for o in packet.possible_outcomes}

    for _ in range(max_passes):
        for key, (low, high) in bounds.items():
            probs[key] = max(low, min(high, probs[key]))

        residual = 1.0 - sum(probs.values())
        if abs(residual) < 1e-12:
            break

        if residual > 0:
            headroom = {k: bounds[k][1] - probs[k] for k in probs}
        else:
            headroom = {k: probs[k] - bounds[k][0] for k in probs}
        total_headroom = sum(headroom.values())
        if total_headroom <= 1e-12:
            break

        for key in probs:
            probs[key] += residual * (headroom[key] / total_headroom)

    for outcome in packet.possible_outcomes:
        outcome.probability = probs[outcome.outcome_id]
    return packet


# ---------------------------------------------------------------------------
# Conversation mode: one running GM conversation per game
# ---------------------------------------------------------------------------

def build_gm_system_prompt(spec: ScenarioSpec) -> str:
    """The invariant half of the GM prompt: rules and the whole world.

    Everything here is identical for every adjudication in a game, which is
    what makes it cacheable. Anything that changes turn to turn belongs in
    build_gm_turn_message() instead, appended after this prefix.
    """
    dm_text = ""
    for dm in spec.domain_models:
        dm_text += f"\n### {dm.id} ({dm.subtype})\n{dm.description}\n"
        if dm.key_variables:
            dm_text += f"Key variables: {', '.join(dm.key_variables)}\n"
        if dm.categories:
            dm_text += f"Governs action categories: {', '.join(dm.categories)}\n"

    actors_text = "\n".join(
        f"  {a.id} ({a.name}) — instruments: {', '.join(i.id for i in a.instruments)}"
        for a in spec.actors
    )
    vars_text = ", ".join(sv.id for sv in spec.state_variables)

    return f"""You are the Adjudication Engine for a strict geopolitical simulation.

You will adjudicate every action in this game, one after another, in this same
conversation. You will therefore remember what has already happened, and you are
expected to use it: an overture already refused twice is not the same action the
third time, an actor just humiliated responds differently, and credibility spent
earlier is not available now. Judge each action as the next move in a sequence.

SCENARIO: {spec.meta.name}
{spec.meta.description}
Each turn is {spec.meta.time_per_turn}. The game runs {spec.meta.turns} turns.

ACTORS
{actors_text}

VALID STATE VARIABLES (state_transitions may use only these ids)
{vars_text}

HOW THIS WORLD WORKS
{dm_text}

RULES
1. NO GOD-MODING. Geopolitics is full of friction. The mechanical base rates you
   are given each turn are your anchor.
2. You may adjust each outcome probability by at most ±0.15 from the base rate,
   with explicit justification.
3. Your probabilities MUST sum to exactly 1.0.
4. All var_ids in state_transitions MUST come from the variable list above.
5. State transition deltas should be small (typically ±0.05 to ±0.20). Large
   moves are rare.
6. Explain your reasoning BEFORE deciding probabilities.
7. For each outcome, describe what happens in 2-3 sentences.
8. For observability, specify what EACH actor sees for EACH possible outcome.
9. The acting actor generally knows they attempted the action. The target sees
   effects proportional to the outcome's observability.

You must output EXACTLY 5 outcomes: critical_success, success, partial, failure,
critical_failure.

The Current State given to you each turn ALREADY reflects that turn's mechanical
effects (decay, momentum, causal propagation). Your state_transitions apply on
top of the values shown. Do not reverse or re-apply them."""


def build_gm_turn_message(
    action: ActionIntent,
    state: dict[str, float],
    relevant_domain_models: list[DomainModel],
    base_rates: dict[str, float],
    turn_number: int,
    mechanical_deltas: dict[str, float] | None = None,
) -> str:
    """The volatile half: only what differs from one adjudication to the next."""
    state_text = "\n".join(f"  {k}: {v:.3f}" for k, v in sorted(state.items()))
    br_text = "\n".join(f"  {k}: {v:.2f}" for k, v in base_rates.items())
    relevant = ", ".join(dm.id for dm in relevant_domain_models) or "none matched"

    return f"""## Turn {turn_number} — adjudicate this action

Actor: {action.actor_id}
Category: {action.action_category}
Instruments: {', '.join(action.instruments_used)}
Targets: {', '.join(action.target_entities)}
Intended effect: {action.intended_effect}
Ambiguity flags: {', '.join(action.ambiguity_flags) if action.ambiguity_flags else 'none'}

Most relevant domain models for this action: {relevant}

## Current State
{state_text}

## Mechanical Base Rates (your anchor — justify any deviation)
{br_text}

## Mechanical Effects Already Applied This Turn (context only)
{_format_mechanical_deltas(mechanical_deltas)}

Generate the AdjudicationPacket."""
