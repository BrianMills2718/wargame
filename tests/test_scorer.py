"""Tests for the wargame.scorer module — weighted scoring and prompt construction."""

import pytest
from wargame.models import ActorScore, ValueAssessment, ScoredActor
from wargame.scorer import (
    build_scorer_messages,
    compute_weighted_total,
    to_scored_actor,
    format_scoreboard,
)


@pytest.fixture
def actor_us(spec):
    """Grab the US actor from the scenario spec."""
    return next((a for a in spec.actors if a.id == "actor_us"), None)


class TestWeightedTotalArithmetic:
    """Tests for compute_weighted_total — the core weighted-sum logic."""

    def test_all_values_perfect_scores_one(self, actor_us):
        """All values at +1.0 should give exactly 1.0."""
        assessments = [
            ValueAssessment(
                value_id="val_us_stability",
                score=1.0,
                reasoning="Test",
                key_evidence=["test"],
            ),
            ValueAssessment(
                value_id="val_us_nonprolif",
                score=1.0,
                reasoning="Test",
                key_evidence=["test"],
            ),
            ValueAssessment(
                value_id="val_us_ally_security",
                score=1.0,
                reasoning="Test",
                key_evidence=["test"],
            ),
            ValueAssessment(
                value_id="val_us_credibility",
                score=1.0,
                reasoning="Test",
                key_evidence=["test"],
            ),
        ]
        score = ActorScore(
            actor_id="actor_us",
            value_assessments=assessments,
            narrative="Test",
            turning_point="Test",
        )
        total = compute_weighted_total(actor_us, score)
        assert abs(total - 1.0) < 1e-9

    def test_all_values_worst_scores_minus_one(self, actor_us):
        """All values at -1.0 should give exactly -1.0."""
        assessments = [
            ValueAssessment(
                value_id="val_us_stability",
                score=-1.0,
                reasoning="Test",
                key_evidence=["test"],
            ),
            ValueAssessment(
                value_id="val_us_nonprolif",
                score=-1.0,
                reasoning="Test",
                key_evidence=["test"],
            ),
            ValueAssessment(
                value_id="val_us_ally_security",
                score=-1.0,
                reasoning="Test",
                key_evidence=["test"],
            ),
            ValueAssessment(
                value_id="val_us_credibility",
                score=-1.0,
                reasoning="Test",
                key_evidence=["test"],
            ),
        ]
        score = ActorScore(
            actor_id="actor_us",
            value_assessments=assessments,
            narrative="Test",
            turning_point="Test",
        )
        total = compute_weighted_total(actor_us, score)
        assert abs(total - (-1.0)) < 1e-9

    def test_weighting_favours_the_heavier_value(self, actor_us):
        """Higher-weight value at +1.0 should outweigh lower-weight value at +1.0."""
        # val_us_nonprolif has weight 0.35; val_us_credibility has weight 0.10
        # Both at +1.0, but nonprolif should contribute more

        score_heavier = ActorScore(
            actor_id="actor_us",
            value_assessments=[
                ValueAssessment(
                    value_id="val_us_nonprolif",
                    score=1.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_stability",
                    score=0.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_ally_security",
                    score=0.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_credibility",
                    score=0.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
            ],
            narrative="Test",
            turning_point="Test",
        )

        score_lighter = ActorScore(
            actor_id="actor_us",
            value_assessments=[
                ValueAssessment(
                    value_id="val_us_credibility",
                    score=1.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_stability",
                    score=0.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_nonprolif",
                    score=0.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_ally_security",
                    score=0.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
            ],
            narrative="Test",
            turning_point="Test",
        )

        total_heavier = compute_weighted_total(actor_us, score_heavier)
        total_lighter = compute_weighted_total(actor_us, score_lighter)

        assert total_heavier > total_lighter

    def test_total_is_normalised_by_matched_weight(self, actor_us):
        """A partial answer with only one value should normalize to +1.0, not stay at its weight."""
        # Only val_us_nonprolif (weight 0.35) is present at +1.0
        # Without normalization, this would give 0.35
        # With normalization, it should give +1.0
        score = ActorScore(
            actor_id="actor_us",
            value_assessments=[
                ValueAssessment(
                    value_id="val_us_nonprolif",
                    score=1.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
            ],
            narrative="Test",
            turning_point="Test",
        )
        total = compute_weighted_total(actor_us, score)
        assert abs(total - 1.0) < 1e-9

    def test_unknown_value_ids_are_ignored(self, actor_us):
        """A hallucinated value_id should be ignored, resulting in 0.0 total."""
        score = ActorScore(
            actor_id="actor_us",
            value_assessments=[
                ValueAssessment(
                    value_id="val_made_up",
                    score=1.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_also_invented",
                    score=0.5,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
            ],
            narrative="Test",
            turning_point="Test",
        )
        total = compute_weighted_total(actor_us, score)
        assert total == 0.0

    def test_mixed_scores_land_between(self, actor_us):
        """A realistic mix of positive and negative scores should fall between -1.0 and +1.0."""
        score = ActorScore(
            actor_id="actor_us",
            value_assessments=[
                ValueAssessment(
                    value_id="val_us_stability",
                    score=0.8,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_nonprolif",
                    score=-0.3,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_ally_security",
                    score=0.2,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_credibility",
                    score=-0.5,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
            ],
            narrative="Test",
            turning_point="Test",
        )
        total = compute_weighted_total(actor_us, score)
        assert -1.0 < total < 1.0


class TestPromptConstruction:
    """Tests for build_scorer_messages — the prompt building logic."""

    def test_prompt_names_only_this_actors_values(self, actor_us):
        """The prompt should list only this actor's values, not Iran's."""
        initial_state = {"sv_nuclear_latency": 8.0}
        final_state = {"sv_nuclear_latency": 8.0}
        action_history = []

        messages = build_scorer_messages(
            actor_us, initial_state, final_state, action_history, turns_played=1
        )

        # Combine all prompt text
        full_text = "\n".join(m["content"] for m in messages)

        # Should have all US values
        assert "val_us_stability" in full_text
        assert "val_us_nonprolif" in full_text
        assert "val_us_ally_security" in full_text
        assert "val_us_credibility" in full_text

        # Should NOT have Iran values
        assert "val_iran_" not in full_text

    def test_prompt_reports_changes_with_direction(self, actor_us):
        """State changes should show both endpoints and a signed delta."""
        initial_state = {"sv_nuclear_latency": 8.0}
        final_state = {"sv_nuclear_latency": 2.0}
        action_history = []

        messages = build_scorer_messages(
            actor_us, initial_state, final_state, action_history, turns_played=1
        )

        full_text = "\n".join(m["content"] for m in messages)

        # Should show both the start and end values
        assert "8.00" in full_text
        assert "2.00" in full_text

        # Should show the signed delta
        assert "-6.00" in full_text

    def test_prompt_lists_unchanged_variables_separately(self, actor_us):
        """Variables identical in initial and final state should be reported as unchanged."""
        initial_state = {"sv_nuclear_latency": 8.0, "sv_regional_stability": 5.0}
        final_state = {"sv_nuclear_latency": 8.0, "sv_regional_stability": 5.0}
        action_history = []

        messages = build_scorer_messages(
            actor_us, initial_state, final_state, action_history, turns_played=1
        )

        full_text = "\n".join(m["content"] for m in messages)

        # Should contain the word "Unchanged"
        assert "Unchanged" in full_text

    def test_prompt_includes_the_actors_actions(self, actor_us):
        """The action history should appear verbatim in the prompt."""
        initial_state = {"sv_nuclear_latency": 8.0}
        final_state = {"sv_nuclear_latency": 8.0}
        action_history = [
            "Imposed economic sanctions",
            "Conducted military drill",
        ]

        messages = build_scorer_messages(
            actor_us, initial_state, final_state, action_history, turns_played=2
        )

        full_text = "\n".join(m["content"] for m in messages)

        # Both actions should appear
        assert "Imposed economic sanctions" in full_text
        assert "Conducted military drill" in full_text


class TestPlumbing:
    """Tests for to_scored_actor and format_scoreboard."""

    def test_to_scored_actor_carries_name_and_total(self, actor_us):
        """to_scored_actor should attach the actor's name and computed total."""
        score = ActorScore(
            actor_id="actor_us",
            value_assessments=[
                ValueAssessment(
                    value_id="val_us_stability",
                    score=0.5,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_nonprolif",
                    score=0.5,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_ally_security",
                    score=0.5,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_credibility",
                    score=0.5,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
            ],
            narrative="Test narrative",
            turning_point="Test turning point",
        )

        scored = to_scored_actor(actor_us, score)

        # Should have the correct actor name
        assert scored.actor_name == "United States"

        # weighted_total should match compute_weighted_total
        expected_total = compute_weighted_total(actor_us, score)
        assert abs(scored.weighted_total - expected_total) < 1e-9

    def test_format_scoreboard_orders_by_total_descending(self, actor_us, spec):
        """Scoreboard should list higher-scoring actors first."""
        # Create two actors with different scores
        score_high = ActorScore(
            actor_id="actor_us",
            value_assessments=[
                ValueAssessment(
                    value_id="val_us_stability",
                    score=1.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_nonprolif",
                    score=1.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_ally_security",
                    score=1.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
                ValueAssessment(
                    value_id="val_us_credibility",
                    score=1.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
            ],
            narrative="High score",
            turning_point="Test",
        )

        score_low = ActorScore(
            actor_id="actor_iran",
            value_assessments=[
                ValueAssessment(
                    value_id="val_iran_survival",
                    score=-1.0,
                    reasoning="Test",
                    key_evidence=["test"],
                ),
            ],
            narrative="Low score",
            turning_point="Test",
        )

        # Get Iran actor from spec
        actor_iran = next((a for a in spec.actors if a.id == "actor_iran"), None)

        scored_high = to_scored_actor(actor_us, score_high)
        scored_low = to_scored_actor(actor_iran, score_low)

        formatted = format_scoreboard([scored_low, scored_high])

        # The higher-scoring actor should appear first
        idx_high = formatted.find("United States")
        idx_low = formatted.find("Iran")

        assert idx_high < idx_low, "US (high score) should appear before Iran (low score)"
