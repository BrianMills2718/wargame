"""Tests for the wargame.gm Game Master pipeline.

Tests cover scoring domain models, selecting relevant models, computing state
shifts, applying shifts to base rates, and clamping adjudications to mechanical
base rates.
"""

import pytest
from pydantic import ValidationError
from wargame.gm import (
    MAX_TOTAL_SHIFT,
    apply_state_shift,
    clamp_to_base_rates,
    compute_mechanical_base_rate,
    compute_state_shift,
    explain_base_rate,
    score_domain_model,
    select_relevant_domain_models,
    validate_adjudication,
)
from wargame.models import (
    ActionIntent,
    AdjudicationPacket,
    DomainModel,
    OutcomeBranch,
    PerActorObservation,
    StateCondition,
    StateTransition,
)


class TestDomainModelSelection:
    """Tests for domain model selection and scoring."""

    def test_breakout_selects_the_nuclear_model_not_deterrence(self, spec):
        """A nuclear breakout action should select dm_nuclear_latency, not dm_deterrence_dynamics.

        This is the regression test for the ordering bug: the old selection was
        first-match in YAML order, so kinetic actions always returned dm_deterrence_dynamics
        because it appeared earlier in the YAML.
        """
        action = ActionIntent(
            actor_id="actor_iran",
            action_category="kinetic",
            target_entities=[],
            instruments_used=["inst_iran_nuclear"],
            intended_effect="accelerate toward nuclear breakout",
            resource_cost=2,
        )
        models = select_relevant_domain_models(spec, action)
        assert len(models) > 0, "Should have selected at least one domain model"
        assert models[0].id == "dm_nuclear_latency", (
            f"Top model should be dm_nuclear_latency, got {models[0].id}"
        )

    def test_selection_is_deterministic(self, spec):
        """Calling select_relevant_domain_models twice should return the same list."""
        action = ActionIntent(
            actor_id="actor_iran",
            action_category="kinetic",
            target_entities=[],
            instruments_used=["inst_iran_nuclear"],
            intended_effect="accelerate toward nuclear breakout",
            resource_cost=2,
        )
        models_1 = select_relevant_domain_models(spec, action)
        models_2 = select_relevant_domain_models(spec, action)
        ids_1 = [m.id for m in models_1]
        ids_2 = [m.id for m in models_2]
        assert ids_1 == ids_2, "Selection order should be deterministic"

    def test_variable_overlap_outranks_category_match(self):
        """A model with one overlapping key variable scores higher than zero overlap + category match."""
        # Build an action with action_vars = {sv_test_var}
        action = ActionIntent(
            actor_id="test",
            action_category="kinetic",
            target_entities=[],
            instruments_used=[],
            intended_effect="test",
            resource_cost=1,
        )
        action_vars = {"sv_test_var"}

        # Model A: one key variable overlap, no category match
        dm_a = DomainModel(
            id="dm_a",
            subtype="test",
            description="",
            key_variables=["sv_test_var"],
            categories=[],
        )
        score_a = score_domain_model(dm_a, action, action_vars)

        # Model B: no overlap, but category match
        dm_b = DomainModel(
            id="dm_b",
            subtype="test",
            description="",
            key_variables=["sv_other_var"],
            categories=["kinetic"],
        )
        score_b = score_domain_model(dm_b, action, action_vars)

        assert score_a > score_b, (
            f"Variable overlap should score higher than category match: {score_a} > {score_b}"
        )
        assert score_a == 2.0, f"Expected score 2.0 for one overlap, got {score_a}"
        assert score_b == 1.0, f"Expected score 1.0 for category match, got {score_b}"


class TestStateShift:
    """Tests for state shift computation and application."""

    def test_state_shift_preserves_total(self):
        """Shifting probabilities should preserve the total."""
        base_rates = {
            "critical_success": 0.05,
            "success": 0.25,
            "partial": 0.40,
            "failure": 0.20,
            "critical_failure": 0.10,
        }

        for shift in [-0.30, -0.15, 0.0, 0.15, 0.30]:
            result = apply_state_shift(base_rates, shift)
            total = sum(result.values())
            assert (
                abs(total - 1.0) < 1e-9
            ), f"Shift {shift} produced total {total}, not 1.0"

    def test_state_shift_never_moves_partial(self):
        """The 'partial' outcome should never be moved by state shifts."""
        base_rates = {
            "critical_success": 0.05,
            "success": 0.25,
            "partial": 0.40,
            "failure": 0.20,
            "critical_failure": 0.10,
        }
        original_partial = base_rates["partial"]

        for shift in [-0.30, -0.15, 0.0, 0.15, 0.30]:
            result = apply_state_shift(base_rates, shift)
            assert (
                result["partial"] == original_partial
            ), f"Shift {shift} moved partial from {original_partial} to {result['partial']}"

    def test_positive_shift_moves_mass_toward_success(self):
        """A positive shift should increase success + critical_success."""
        base_rates = {
            "critical_success": 0.05,
            "success": 0.25,
            "partial": 0.40,
            "failure": 0.20,
            "critical_failure": 0.10,
        }
        original_good = base_rates["success"] + base_rates["critical_success"]
        original_bad = base_rates["failure"] + base_rates["critical_failure"]

        result = apply_state_shift(base_rates, 0.30)
        new_good = result["success"] + result["critical_success"]
        new_bad = result["failure"] + result["critical_failure"]

        assert new_good > original_good, (
            f"Positive shift should increase good outcomes: {new_good} > {original_good}"
        )
        assert new_bad < original_bad, (
            f"Positive shift should decrease bad outcomes: {new_bad} < {original_bad}"
        )

    def test_negative_shift_moves_mass_toward_failure(self):
        """A negative shift should decrease success + critical_success."""
        base_rates = {
            "critical_success": 0.05,
            "success": 0.25,
            "partial": 0.40,
            "failure": 0.20,
            "critical_failure": 0.10,
        }
        original_good = base_rates["success"] + base_rates["critical_success"]
        original_bad = base_rates["failure"] + base_rates["critical_failure"]

        result = apply_state_shift(base_rates, -0.30)
        new_good = result["success"] + result["critical_success"]
        new_bad = result["failure"] + result["critical_failure"]

        assert new_good < original_good, (
            f"Negative shift should decrease good outcomes: {new_good} < {original_good}"
        )
        assert new_bad > original_bad, (
            f"Negative shift should increase bad outcomes: {new_bad} > {original_bad}"
        )

    def test_total_shift_is_capped(self):
        """Multiple conditions should not exceed MAX_TOTAL_SHIFT."""
        # Build a model where four conditions all fire and each wants +0.3
        dm = DomainModel(
            id="test_model",
            subtype="test",
            description="",
            key_variables=["var1", "var2", "var3", "var4"],
            categories=[],
            state_conditions=[
                StateCondition(variable="var1", above=0.0, shift=0.3, note="fires"),
                StateCondition(variable="var2", above=0.0, shift=0.3, note="fires"),
                StateCondition(variable="var3", above=0.0, shift=0.3, note="fires"),
                StateCondition(variable="var4", above=0.0, shift=0.3, note="fires"),
            ],
        )
        state = {"var1": 0.5, "var2": 0.5, "var3": 0.5, "var4": 0.5}

        shift, _ = compute_state_shift(dm, state)
        assert (
            shift == MAX_TOTAL_SHIFT
        ), f"Expected capped shift {MAX_TOTAL_SHIFT}, got {shift}"


class TestMechanicalBaseRate:
    """Tests for computing mechanical base rates with state dependency."""

    def test_base_rate_responds_to_world_state(self, spec):
        """Base rates should change when relevant state variables change."""
        # US force posture action with initial state
        action_initial = ActionIntent(
            actor_id="actor_us",
            action_category="kinetic",
            target_entities=["actor_iran"],
            instruments_used=["inst_us_force_posture"],
            intended_effect="demonstrate credible deterrence",
            resource_cost=2,
        )
        models_initial = select_relevant_domain_models(spec, action_initial)
        rate_initial = compute_mechanical_base_rate(models_initial, action_initial, spec.initial_state)

        # Now raise military tension to 0.85
        hot_state = dict(spec.initial_state)
        hot_state["sv_military_tension"] = 0.85

        rate_hot = compute_mechanical_base_rate(models_initial, action_initial, hot_state)

        # Distributions should differ
        assert rate_initial != rate_hot, (
            "Base rates should respond to world state"
        )

        # P(success or better) should be lower in hot state
        initial_good = rate_initial.get("success", 0.0) + rate_initial.get("critical_success", 0.0)
        hot_good = rate_hot.get("success", 0.0) + rate_hot.get("critical_success", 0.0)
        assert hot_good < initial_good, (
            f"In hot crisis, success should be less likely: {hot_good} < {initial_good}"
        )

    def test_explain_base_rate_names_the_condition(self, spec):
        """Explanations should name the state variable that moved the odds."""
        # Hot state with high military tension
        hot_state = dict(spec.initial_state)
        hot_state["sv_military_tension"] = 0.85

        # Force posture action
        action = ActionIntent(
            actor_id="actor_us",
            action_category="kinetic",
            target_entities=["actor_iran"],
            instruments_used=["inst_us_force_posture"],
            intended_effect="demonstrate credible deterrence",
            resource_cost=2,
        )
        models = select_relevant_domain_models(spec, action)

        explanations = explain_base_rate(models, hot_state)
        explanation_text = " ".join(explanations)

        assert "sv_military_tension" in explanation_text, (
            f"Explanation should mention sv_military_tension. Got: {explanation_text}"
        )

    def test_breakout_is_harder_than_a_show_of_force(self, spec):
        """A nuclear breakout should have lower P(success or better) than a force posture action."""
        # Breakout action
        breakout = ActionIntent(
            actor_id="actor_iran",
            action_category="kinetic",
            target_entities=[],
            instruments_used=["inst_iran_nuclear"],
            intended_effect="accelerate toward nuclear breakout",
            resource_cost=2,
        )
        breakout_models = select_relevant_domain_models(spec, breakout)
        breakout_rate = compute_mechanical_base_rate(breakout_models, breakout, spec.initial_state)

        # Force posture action
        force_posture = ActionIntent(
            actor_id="actor_us",
            action_category="kinetic",
            target_entities=["actor_iran"],
            instruments_used=["inst_us_force_posture"],
            intended_effect="demonstrate credible deterrence",
            resource_cost=2,
        )
        posture_models = select_relevant_domain_models(spec, force_posture)
        posture_rate = compute_mechanical_base_rate(posture_models, force_posture, spec.initial_state)

        breakout_good = breakout_rate.get("success", 0.0) + breakout_rate.get("critical_success", 0.0)
        posture_good = posture_rate.get("success", 0.0) + posture_rate.get("critical_success", 0.0)

        assert breakout_good < posture_good, (
            f"Breakout should be harder than force posture: "
            f"P(success) {breakout_good} < {posture_good}"
        )


class TestClampingAndValidation:
    """Tests for clamping adjudications to base rates."""

    def test_clamp_pulls_god_moding_back_into_band(self):
        """An out-of-band adjudication should be pulled back inside and renormalised."""
        # Base rate: success = 0.20
        base_rates = {
            "critical_success": 0.05,
            "success": 0.20,
            "partial": 0.40,
            "failure": 0.25,
            "critical_failure": 0.10,
        }

        # God-moded packet: success = 0.70
        packet = AdjudicationPacket(
            reasoning="The GM gave success way too high.",
            possible_outcomes=[
                OutcomeBranch(
                    outcome_id="critical_success",
                    narrative="Incredible success.",
                    probability=0.00,
                    state_transitions=[],
                ),
                OutcomeBranch(
                    outcome_id="success",
                    narrative="Good success.",
                    probability=0.70,
                    state_transitions=[],
                ),
                OutcomeBranch(
                    outcome_id="partial",
                    narrative="Mixed result.",
                    probability=0.20,
                    state_transitions=[],
                ),
                OutcomeBranch(
                    outcome_id="failure",
                    narrative="Failed.",
                    probability=0.05,
                    state_transitions=[],
                ),
                OutcomeBranch(
                    outcome_id="critical_failure",
                    narrative="Disaster.",
                    probability=0.05,
                    state_transitions=[],
                ),
            ],
            observability=[],
        )

        # Validate should find an issue
        valid_vars = {"sv_test"}
        valid_actors = {"actor_test"}
        issues = validate_adjudication(packet, valid_vars, valid_actors, base_rates)
        assert len(issues) > 0, "Should have found god-moding violation"
        assert any("success" in issue for issue in issues), (
            f"Should complain about success probability. Got: {issues}"
        )

        # Clamp should fix it
        clamped = clamp_to_base_rates(packet, base_rates, tolerance=0.15)

        # Check sum is 1.0
        prob_sum = sum(o.probability for o in clamped.possible_outcomes)
        assert abs(prob_sum - 1.0) < 1e-6, f"Clamped probabilities sum to {prob_sum}, not 1.0"

        # Check success is in band
        success_prob = next(o.probability for o in clamped.possible_outcomes if o.outcome_id == "success")
        low = base_rates["success"] - 0.15
        high = base_rates["success"] + 0.15
        assert low <= success_prob <= high, (
            f"Success {success_prob} should be in band [{low}, {high}]"
        )

    def test_clamp_leaves_a_compliant_packet_alone(self):
        """A compliant packet must be a fixed point of the clamp.

        The clamp is only meaningful as enforcement if it does nothing to an
        adjudication that was already inside its band. Note the base rates here
        sum to exactly 1.0: a fixture summing to less would make the clamp
        redistribute the shortfall, and the resulting movement would be correct
        behaviour rather than a bug.
        """
        base_rates = {
            "critical_success": 0.05,
            "success": 0.25,
            "partial": 0.40,
            "failure": 0.25,
            "critical_failure": 0.05,
        }
        assert abs(sum(base_rates.values()) - 1.0) < 1e-9, "fixture must be a real distribution"

        packet = AdjudicationPacket(
            reasoning="The GM was careful.",
            possible_outcomes=[
                OutcomeBranch(
                    outcome_id=outcome_id,
                    narrative="n",
                    probability=probability,
                    state_transitions=[],
                )
                for outcome_id, probability in [
                    ("critical_success", 0.08),
                    ("success", 0.30),
                    ("partial", 0.34),
                    ("failure", 0.22),
                    ("critical_failure", 0.06),
                ]
            ],
            observability=[],
        )
        assert abs(sum(o.probability for o in packet.possible_outcomes) - 1.0) < 1e-9
        assert not validate_adjudication(packet, set(), set(), base_rates), (
            "fixture must start compliant, or this tests the wrong thing"
        )

        before = {o.outcome_id: o.probability for o in packet.possible_outcomes}
        clamped = clamp_to_base_rates(packet, base_rates, tolerance=0.15)
        after = {o.outcome_id: o.probability for o in clamped.possible_outcomes}

        for outcome_id, probability in before.items():
            assert abs(after[outcome_id] - probability) < 1e-9, (
                f"{outcome_id}: clamp moved a compliant outcome from "
                f"{probability} to {after[outcome_id]}"
            )


class TestOutcomeLadderShape:
    """An AdjudicationPacket must carry each of the five outcome rungs exactly once.

    A duplicate rung used to pass validation (only the ID *set* was checked);
    clamp_to_base_rates then collapsed duplicates into one probability entry and
    wrote it back to both, so the distribution handed to resolve_action could sum
    past 1.0 and the second copy's transitions could never be chosen.
    """

    LADDER = {"critical_success": 0.10, "success": 0.20, "partial": 0.30,
              "failure": 0.25, "critical_failure": 0.15}

    def _branches(self, items):
        return [OutcomeBranch(outcome_id=k, narrative="n", probability=p, state_transitions=[])
                for k, p in items]

    def test_duplicate_outcome_rejected(self):
        # Sums to 1.0, contains all five IDs, plus a second "success".
        items = [("critical_success", 0.05), ("success", 0.15), ("success", 0.15),
                 ("partial", 0.30), ("failure", 0.25), ("critical_failure", 0.10)]
        with pytest.raises(ValidationError, match="exactly once"):
            AdjudicationPacket(reasoning="r", possible_outcomes=self._branches(items),
                               observability=[])

    def test_missing_outcome_rejected(self):
        items = [("success", 0.40), ("partial", 0.30), ("failure", 0.20),
                 ("critical_failure", 0.10)]
        with pytest.raises(ValidationError, match="exactly once"):
            AdjudicationPacket(reasoning="r", possible_outcomes=self._branches(items),
                               observability=[])

    def test_five_unique_in_any_order_accepted(self):
        items = list(reversed(self.LADDER.items()))
        packet = AdjudicationPacket(reasoning="r", possible_outcomes=self._branches(items),
                                    observability=[])
        assert sorted(o.outcome_id for o in packet.possible_outcomes) == sorted(self.LADDER)
