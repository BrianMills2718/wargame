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


def _format_mechanical_deltas(deltas: dict[str, float] | None) -> str:
    """Format mechanical deltas for inclusion in GM prompt."""
    if not deltas:
        return "None this turn."
    lines = []
    for var_id, delta in sorted(deltas.items()):
        lines.append(f"  {var_id}: {delta:+.4f}")
    return "\n".join(lines) + "\nThese have already been applied. The Current State above reflects them."


def select_relevant_domain_models(
    spec: ScenarioSpec,
    action: ActionIntent,
) -> list[DomainModel]:
    """Select domain models relevant to this action based on instrument target_vars overlap."""
    # Collect all target_vars for the instruments used in this action
    action_vars: set[str] = set()
    for actor in spec.actors:
        for inst in actor.instruments:
            if inst.id in action.instruments_used:
                action_vars.update(inst.target_vars)

    # Also match by action category
    category_model_map = {
        "covert": "dm_covert_ops",
        "diplomatic": "dm_diplomatic_engagement",
        "economic": "dm_sanctions_pressure",
        "kinetic": "dm_deterrence_dynamics",
    }

    relevant = []
    for dm in spec.domain_models:
        # Match by variable overlap
        if action_vars & set(dm.key_variables):
            relevant.append(dm)
        # Match by category
        elif dm.id == category_model_map.get(action.action_category):
            relevant.append(dm)

    # Always include covert ops model for covert actions
    if action.action_category == "covert":
        covert = next((dm for dm in spec.domain_models if dm.id == "dm_covert_ops"), None)
        if covert and covert not in relevant:
            relevant.append(covert)

    return relevant


def compute_mechanical_base_rate(
    domain_models: list[DomainModel],
    action: ActionIntent,
    state: dict[str, float],
) -> dict[str, float]:
    """Compute a mechanical base rate from domain models and current state.

    Returns a dict of outcome_id -> probability as the baseline the GM must anchor to.
    If no base rates are defined, returns a default distribution.
    """
    # Use the first domain model with base_rates defined
    for dm in domain_models:
        if dm.base_rates:
            return dm.base_rates

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


def build_gm_messages(
    action: ActionIntent,
    state: dict[str, float],
    domain_models: list[DomainModel],
    base_rates: dict[str, float],
    actor_ids: list[str],
    variable_ids: list[str],
    mechanical_deltas: dict[str, float] | None = None,
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
9. The acting actor should generally know they attempted the action. The target actor should see effects proportional to the outcome's observability.

You must output EXACTLY 5 outcomes: critical_success, success, partial, failure, critical_failure.

NOTE: The "Current State" below ALREADY reflects any mechanical effects (decay, momentum, causal propagation) that occurred this turn. Your state_transitions are applied ON TOP of the current state values shown. You do NOT need to account for or reverse mechanical effects — just decide what the action does to the world as it currently stands."""

    user_prompt = f"""## Action to Adjudicate

Actor: {action.actor_id}
Category: {action.action_category}
Instruments: {', '.join(action.instruments_used)}
Targets: {', '.join(action.target_entities)}
Intended effect: {action.intended_effect}
Ambiguity flags: {', '.join(action.ambiguity_flags) if action.ambiguity_flags else 'none'}

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


def validate_adjudication(
    packet: AdjudicationPacket,
    valid_var_ids: set[str],
    valid_actor_ids: set[str],
    base_rates: dict[str, float],
    tolerance: float = 0.15,
) -> list[str]:
    """Validate an AdjudicationPacket. Returns list of issues (empty = valid)."""
    issues = []

    # Check probabilities sum to 1.0
    prob_sum = sum(o.probability for o in packet.possible_outcomes)
    if abs(prob_sum - 1.0) > 0.02:
        issues.append(f"Probabilities sum to {prob_sum:.4f}, not 1.0")

    # Check all var_ids are valid
    for outcome in packet.possible_outcomes:
        for t in outcome.state_transitions:
            if t.var_id not in valid_var_ids:
                issues.append(f"Unknown var_id: {t.var_id}")

    # Check all actor_ids in observability are valid
    for obs in packet.observability:
        if obs.actor_id not in valid_actor_ids:
            issues.append(f"Unknown actor_id in observability: {obs.actor_id}")

    # Check for required outcome_ids
    outcome_ids = {o.outcome_id for o in packet.possible_outcomes}
    required = {"critical_success", "success", "partial", "failure", "critical_failure"}
    missing = required - outcome_ids
    if missing:
        issues.append(f"Missing outcome_ids: {missing}")

    # Check ±tolerance deviation from base rates (anti-god-moding)
    if base_rates:
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
