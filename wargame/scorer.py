"""End-of-game scoring — asymmetric evaluation against each actor's own values.

There is no common yardstick. The United States and Iran are not playing the
same game: one is trying to prevent proliferation and hold a regional order
together, the other is trying to survive, keep its sovereignty and stay
solvent. A single "winner" score would have to flatten that into a scale
neither actor recognises, so each is judged only against the terminal values
its own scenario entry declares, weighted as that entry weights them.

The model judges how well each value was served. Python multiplies by the
declared weights and sums. Keeping the arithmetic out of the model is the same
rule the rest of the engine follows: LLMs suggest, Python decides.
"""

from __future__ import annotations

from wargame.models import ActorScore, ActorSpec, ScoredActor


def build_scorer_messages(
    actor: ActorSpec,
    initial_state: dict[str, float],
    final_state: dict[str, float],
    action_history: list[str],
    turns_played: int,
) -> list[dict[str, str]]:
    """Build the scoring call for one actor.

    The scorer is an out-of-game evaluator run after the last turn, so it sees
    canonical state rather than any actor's estimate. That is deliberate and is
    not a fog-of-war leak: there is no remaining turn for the knowledge to
    affect, and judging an actor on what it merely believed happened would
    reward being wrong.
    """
    values_text = "\n".join(
        f"  - {v.id} | {v.name} | weight {v.weight}" for v in actor.values
    )

    moved, unchanged = [], []
    for var_id in sorted(final_state):
        start = initial_state.get(var_id)
        if start is None:
            continue
        delta = final_state[var_id] - start
        line = f"  {var_id.replace('sv_', '')}: {start:.2f} -> {final_state[var_id]:.2f} ({delta:+.2f})"
        (moved if abs(delta) > 0.01 else unchanged).append(line)

    moved_text = "\n".join(moved) or "  Nothing moved materially."
    unchanged_text = ", ".join(
        ln.strip().split(":")[0] for ln in unchanged
    ) or "none"
    history_text = "\n".join(f"  - {h}" for h in action_history) or "  This actor took no action."

    system_prompt = f"""You are scoring one player's performance at the end of a geopolitical wargame.

You are judging {actor.name}, and ONLY against {actor.name}'s own terminal values, listed below with the weight each carries for them. Do not score them against the other side's interests, against international opinion, or against your own view of what a good outcome would be. An outcome that is bad for the world can still be an excellent result for this actor, and you must score it that way.

HOW TO SCORE
For each value, give a score from -1.0 to +1.0:
  +1.0  this value was strongly advanced
  +0.5  meaningfully better off
   0.0  essentially unchanged
  -0.5  meaningfully worse off
  -1.0  this value was badly damaged

RULES
1. Ground every score in the state changes and actions given below. Cite specific variables by name in key_evidence. A score with no evidence behind it is worthless.
2. Judge outcomes, not intentions. A well-reasoned action that achieved nothing scores as nothing achieved.
3. Do not reward activity. An actor that acted every turn and moved nothing did not do well.
4. Weigh what did NOT change too. A value can be preserved successfully under pressure, and that is a real positive result, not a zero.
5. Do not compute totals or compare the two actors. You are scoring this actor alone; the weighted total is calculated outside your answer.
6. Be willing to give negative scores. A scorer that never scores below zero is not measuring anything.

{actor.name.upper()}'S TERMINAL VALUES
{values_text}"""

    user_prompt = f"""The game ran {turns_played} turns.

WHAT CHANGED IN THE WORLD (canonical, start -> end):
{moved_text}

Unchanged over the whole game: {unchanged_text}

WHAT {actor.name.upper()} ACTUALLY DID:
{history_text}

Score {actor.name} against each of their values."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def compute_weighted_total(actor: ActorSpec, score: ActorScore) -> float:
    """Weight the model's per-value scores by the actor's declared weights.

    Only values the actor actually declares are counted, so a hallucinated
    value_id contributes nothing rather than silently skewing the result. The
    total is normalised by the weight actually matched, so a partial answer
    stays on the same -1.0..+1.0 scale instead of looking artificially moderate.
    """
    weights = {v.id: v.weight for v in actor.values}
    total = 0.0
    matched_weight = 0.0
    for assessment in score.value_assessments:
        weight = weights.get(assessment.value_id)
        if weight is None:
            continue
        total += assessment.score * weight
        matched_weight += weight
    if matched_weight <= 0.0:
        return 0.0
    return total / matched_weight


def to_scored_actor(actor: ActorSpec, score: ActorScore) -> ScoredActor:
    """Attach the engine-computed total to the model's judgment."""
    return ScoredActor(
        actor_id=actor.id,
        actor_name=actor.name,
        weighted_total=compute_weighted_total(actor, score),
        value_assessments=score.value_assessments,
        narrative=score.narrative,
        turning_point=score.turning_point,
    )


def format_scoreboard(scored: list[ScoredActor]) -> str:
    """Render the final scores for the terminal."""
    lines = []
    for s in sorted(scored, key=lambda x: x.weighted_total, reverse=True):
        lines.append("")
        lines.append(f"  {s.actor_name}   {s.weighted_total:+.2f}")
        lines.append(f"  {'-' * 60}")
        for a in s.value_assessments:
            lines.append(f"    {a.score:+.2f}  {a.value_id.replace('val_', '')}")
            lines.append(f"           {a.reasoning}")
        lines.append(f"    Overall: {s.narrative}")
        lines.append(f"    Turning point: {s.turning_point}")
    return "\n".join(lines)
