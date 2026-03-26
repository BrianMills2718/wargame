"""Simple AI opponent — picks actions based on character model and visible state.

Uses llm_client for decision-making. Character model params shape the prompt.
"""

from __future__ import annotations

from wargame.models import ActionIntent, ActorSpec, CharacterModel


def build_ai_opponent_messages(
    actor: ActorSpec,
    state_estimates: dict[str, float],
    observations: list[str],
    action_history: list[str],
    turn_number: int,
    resource_budget: dict[str, int],
) -> list[dict[str, str]]:
    """Build messages for the AI opponent to decide its action."""
    character = actor.character

    # Format instruments
    inst_text = "\n".join(
        f"  - {inst.id} (domains: {', '.join(inst.midfield)})"
        for inst in actor.instruments
    )

    # Format state estimates
    state_text = "\n".join(f"  {k}: {v:.3f}" for k, v in sorted(state_estimates.items()))

    # Format values
    values_text = "\n".join(f"  - {v.name} (weight: {v.weight})" for v in actor.values)

    # Format observations
    obs_text = "\n".join(f"  - {o}" for o in observations[-5:]) if observations else "  No recent observations."

    # Format history
    hist_text = "\n".join(f"  - {h}" for h in action_history[-5:]) if action_history else "  No prior actions."

    # Format budget
    budget_text = "\n".join(f"  {d}: {a}" for d, a in resource_budget.items())

    system_prompt = f"""You are the leader of {actor.name} in a geopolitical crisis simulation.

YOUR VALUES (what you care about, in priority order):
{values_text}

YOUR CHARACTER:
- Risk posture: {"aggressive/willing to take risks" if character.risk_posture > 0.6 else "cautious/risk-averse" if character.risk_posture < 0.4 else "moderate"}
- Ideological commitment: {"strongly ideological" if character.ideological_weight > 0.6 else "pragmatic" if character.ideological_weight < 0.4 else "balanced"}
- Escalation threshold: {"quick to escalate" if character.escalation_threshold < 0.4 else "restrained/patient" if character.escalation_threshold > 0.6 else "moderate"}
- Openness to cooperation: {"closed/unilateral" if character.cooperation_openness < 0.4 else "open to deals" if character.cooperation_openness > 0.6 else "selective"}

YOUR INSTRUMENTS (available tools):
{inst_text}

RULES:
1. You must pick ONE action per turn using your available instruments.
2. actor_id must be: {actor.id}
3. instruments_used must come from the list above. Do not invent new instruments.
4. resource_cost should be 1-3 for routine actions, 3-5 for major operations.
5. action_category must be: kinetic, diplomatic, covert, economic, information, or resource_allocation.
6. Think strategically about your values and the current situation."""

    user_prompt = f"""Turn {turn_number}

YOUR INTELLIGENCE ESTIMATE OF THE WORLD:
{state_text}

RECENT OBSERVATIONS:
{obs_text}

YOUR RECENT ACTIONS:
{hist_text}

RESOURCE BUDGET THIS TURN:
{budget_text}

What is your directive for this turn?"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
