"""Player advisor — the reliable out-of-game analyst from ADR-004.

This is the accessibility layer. The game holds sixteen interacting variables,
hidden state and a causal graph; a player without a background in international
relations has no way in. The advisor is how they ask "what happens if I
sanction their bank?" and get a straight answer before committing a turn.

It is deliberately NOT an in-game character. In-game NPCs are unreliable
narrators and part of the fog of war; this one knows it is a game, explains the
mechanics honestly, and says when it does not know something.

The information barrier is the whole point: the advisor is built from the
player's own state estimates, never from canonical state, so it cannot leak
what the player has not observed.
"""

from __future__ import annotations

from wargame.models import ActorSpec, DomainModel


def build_advisor_messages(
    actor: ActorSpec,
    domain_models: list[DomainModel],
    estimates: dict[str, float],
    budget: dict[str, int],
    recent_observations: list[str],
    action_history: list[str],
    turn_number: int,
    total_turns: int,
    question: str,
) -> list[dict[str, str]]:
    """Build the advisor call for one player question.

    `estimates` must be the player's own state estimates, never canonical
    state. Passing canonical values here would silently defeat fog of war.
    """
    instruments_text = "\n".join(
        f"  - {inst.id} (domains: {', '.join(inst.midfield)}; affects: {', '.join(inst.target_vars)})"
        for inst in actor.instruments
    )
    values_text = "\n".join(f"  - {v.name} (weight {v.weight})" for v in actor.values)
    state_text = "\n".join(f"  {k.replace('sv_', '')}: {v:.2f}" for k, v in sorted(estimates.items()))
    budget_text = ", ".join(f"{d}: {a}" for d, a in budget.items())

    mechanics_text = ""
    for dm in domain_models:
        mechanics_text += f"\n  {dm.id}: {dm.description}\n"
        if dm.base_rates:
            odds = dm.base_rates
            good = odds.get("critical_success", 0.0) + odds.get("success", 0.0)
            mechanics_text += f"    Baseline odds of this working well: about {good:.0%}.\n"
        for cond in dm.state_conditions:
            edge = f"above {cond.above}" if cond.above is not None else f"below {cond.below}"
            direction = "better" if cond.shift > 0 else "worse"
            mechanics_text += f"    When {cond.variable.replace('sv_', '')} is {edge}, odds get {direction}: {cond.note}\n"

    observations_text = "\n".join(f"  - {o}" for o in recent_observations[-6:]) or "  Nothing reported yet."
    history_text = "\n".join(f"  - {h}" for h in action_history[-5:]) or "  No orders given yet."

    system_prompt = f"""You are the player's personal analyst in a geopolitical wargame. You work for the player, who is commanding {actor.name}.

You are NOT a character inside the simulation. You know this is a game and you explain how it works honestly. You are not a cheerleader and you are not a diplomat — your value is that you tell the player things they did not want to hear.

WHAT YOU CAN SEE
You see exactly what the player sees and nothing more: their own intelligence picture, their instruments, their budget, and what has been reported to them. The intelligence picture is an ESTIMATE, not the truth. It can be wrong, and it can be wrong because the opponent wanted it to be. Never claim to know the opponent's real internal condition, their intentions, or anything the player has not observed.

HOW TO ANSWER
1. Answer the actual question first, in plain language. No jargon. If a term is unavoidable, define it in the same sentence.
2. Be concrete about odds. You know the baseline chances below; use them. "Roughly a one-in-four chance of it working well" beats "this may be difficult."
3. When the player asks what to do, give two or three real options that use instruments they actually have, and phrase each one the way they could type it as an order.
4. Always name the most important risk. An option with no downside means you have not thought hard enough.
5. Say plainly what you cannot see. A confident answer built on a guess is worse than an admitted gap.
6. Do not invent instruments, variables or events. If the answer depends on something you have not been told, say so.

THE PLAYER'S PRIORITIES (what counts as winning for them)
{values_text}

THE PLAYER'S INSTRUMENTS (only these exist)
{instruments_text}

HOW THIS WORLD WORKS (the actual game mechanics — you may explain these openly)
{mechanics_text}"""

    user_prompt = f"""Turn {turn_number} of {total_turns}. Budget this turn — {budget_text}.

THE PLAYER'S CURRENT INTELLIGENCE PICTURE (estimates, possibly wrong):
{state_text}

RECENTLY REPORTED TO THE PLAYER:
{observations_text}

ORDERS THE PLAYER HAS ALREADY GIVEN:
{history_text}

The player asks:
"{question}"

Answer them."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
