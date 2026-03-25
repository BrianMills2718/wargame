"""Parser pipeline — converts natural language player directives into ActionIntents.

Uses llm_client.call_llm_structured() with the ActionIntent Pydantic model.
Validates that instruments exist in the actor's inventory.
"""

from __future__ import annotations

from wargame.models import ActionIntent, ActorSpec


def build_parser_messages(
    directive: str,
    actor: ActorSpec,
    available_instruments: list[dict],
    resource_budget: dict[str, int],
) -> list[dict[str, str]]:
    """Build messages for the parser LLM.

    Args:
        directive: The player's natural language command.
        actor: The actor spec for the acting player.
        available_instruments: List of instrument dicts with id, midfield tags, target_vars.
        resource_budget: Current resource budget by domain.
    """
    instruments_text = "\n".join(
        f"  - {inst['id']} (domains: {', '.join(inst['midfield'])}, targets: {', '.join(inst['target_vars'])})"
        for inst in available_instruments
    )

    budget_text = "\n".join(f"  - {domain}: {amount}" for domain, amount in resource_budget.items())

    system_prompt = f"""You are the Action Translation Engine for a geopolitical simulation.

Your job is to read a human player's natural language command and map it to a structured ActionIntent.

RULES:
1. Do NOT judge if the action will succeed or fail. Only translate the intent.
2. You MUST map the player's tools to instruments from the list below. Do NOT invent new instrument IDs.
3. If the player is deliberately vague, flag this in ambiguity_flags.
4. resource_cost must be reasonable for the action scope (1-3 for routine, 3-5 for major operations).
5. action_category must be one of: kinetic, diplomatic, covert, economic, information, resource_allocation.
6. The actor_id is always: {actor.id}

AVAILABLE INSTRUMENTS (use only these IDs):
{instruments_text}

CURRENT RESOURCE BUDGET:
{budget_text}"""

    user_prompt = f"""Player directive:
"{directive}"

Parse this into an ActionIntent."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def validate_action_intent(
    intent: ActionIntent,
    actor: ActorSpec,
) -> list[str]:
    """Validate that the ActionIntent references valid instruments.

    Returns list of issues (empty = valid).
    """
    issues = []

    # Check actor_id matches
    if intent.actor_id != actor.id:
        issues.append(f"actor_id mismatch: got {intent.actor_id}, expected {actor.id}")

    # Check instruments exist in actor's inventory
    valid_inst_ids = {inst.id for inst in actor.instruments}
    for inst_id in intent.instruments_used:
        if inst_id not in valid_inst_ids:
            issues.append(f"Actor {actor.id} does not possess instrument: {inst_id}")

    return issues
