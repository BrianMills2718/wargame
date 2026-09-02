"""Tests for the wargame.engine module."""

import pytest
from wargame.engine import (
    apply_delta,
    apply_decay_and_momentum,
    propagate_causal_edges,
    apply_pending_effects,
    run_mechanical_phases,
    resolve_action,
    get_variable,
    get_current_turn,
)


class TestDeltaApplication:
    """Tests for apply_delta behavior."""

    def test_clamping_respects_range(self, conn):
        """Huge positive delta on a bounded variable should clamp at max."""
        # sv_military_tension has range [0, 1] and starts at 0.4
        initial = get_variable(conn, "sv_military_tension")
        assert initial == 0.4

        # Apply a huge positive delta
        actual_delta = apply_delta(conn, "sv_military_tension", 999.0)

        # Should clamp at 1.0
        final = get_variable(conn, "sv_military_tension")
        assert final == 1.0

        # actual_delta should reflect the clamped amount, not the requested amount
        assert actual_delta == pytest.approx(0.6, abs=1e-9)  # 1.0 - 0.4

    def test_structural_variables_are_rate_limited(self, conn):
        """Structural variables should be limited to ±0.05 per application."""
        # sv_force_posture is type "structural" and starts at 0.6
        initial = get_variable(conn, "sv_force_posture")
        assert initial == 0.6

        # Apply a large delta
        actual_delta = apply_delta(conn, "sv_force_posture", 0.5)

        # Should be rate-limited to ±0.05
        assert actual_delta <= 0.05 + 1e-9

        final = get_variable(conn, "sv_force_posture")
        assert final == pytest.approx(0.65, abs=1e-9)


class TestBaselineReversion:
    """Tests for decay/momentum behavior."""

    def test_baseline_reversion_moves_toward_baseline_not_zero(self, conn):
        """Variables with decay_rate should revert to baseline, not zero."""
        # sv_military_tension: baseline=0.25, initial=0.4, decay_rate=0.15
        # After 30 turns of only decay/momentum, it should approach 0.25

        for _ in range(30):
            run_mechanical_phases(conn)

        final = get_variable(conn, "sv_military_tension")
        baseline = 0.25

        # Should be within 0.02 of baseline
        assert abs(final - baseline) < 0.02, f"Expected ~{baseline}, got {final}"

        # Should NOT be less than 0.05 (it's reverting toward 0.25, not 0)
        assert final >= 0.05, f"Should not march to zero; got {final}"

    def test_reversion_is_proportional_so_it_asymptotes(self, conn):
        """Proportional decay should slow down (asymptotic), not constant."""
        # sv_sanctions_intensity: baseline=0.55, initial=0.7, decay_rate=0.05
        # Capture value after 10 turns and after 30 turns
        # Change over turns 0-10 should be larger than change over 10-30

        for _ in range(10):
            run_mechanical_phases(conn)
        value_at_10 = get_variable(conn, "sv_sanctions_intensity")

        for _ in range(20):
            run_mechanical_phases(conn)
        value_at_30 = get_variable(conn, "sv_sanctions_intensity")

        change_0_to_10 = abs(value_at_10 - 0.7)  # 0.7 was initial
        change_10_to_30 = abs(value_at_30 - value_at_10)

        # Proportional decay should have larger change early
        assert change_10_to_30 < change_0_to_10, (
            f"Proportional decay should asymptote. Change 0-10: {change_0_to_10}, "
            f"Change 10-30: {change_10_to_30}"
        )

    def test_momentum_is_linear_and_ignores_baseline(self, conn):
        """Variables with momentum should advance linearly, ignoring baseline."""
        # sv_nuclear_latency: momentum=-0.3, initial=8.0
        # After 10 turns: 8.0 - 10*0.3 = 5.0

        for _ in range(10):
            run_mechanical_phases(conn)

        final = get_variable(conn, "sv_nuclear_latency")
        expected = 8.0 - 10 * 0.3  # 5.0

        assert final == pytest.approx(expected, abs=1e-6)


class TestLaggedEffects:
    """Tests for causal edge propagation and lagged effects."""

    def test_lagged_effects_apply_on_the_right_turn(self, conn):
        """Lagged effects should queue and apply on the correct turn."""
        # sv_sanctions_intensity -> sv_internal_legitimacy has lag=1, effect=-0.15

        turn_0 = get_current_turn(conn)
        assert turn_0 == 0

        # Apply a delta to sv_sanctions_intensity
        source_deltas = {"sv_sanctions_intensity": 0.1}
        current_turn = get_current_turn(conn)

        # Propagate should queue the lagged effect
        propagate_causal_edges(conn, source_deltas, current_turn)

        # Check pending_effects: should have a row with applies_on_turn = 0 + lag
        pending = conn.execute(
            "SELECT target_var, delta, applies_on_turn FROM pending_effects WHERE applies_on_turn=?",
            (current_turn + 1,),
        ).fetchall()

        # The edge has lag=1, so it should apply on turn 0+1=1
        assert len(pending) > 0, "Expected lagged effect to be queued"
        target_var, delta, applies_on_turn = pending[0]
        assert target_var == "sv_internal_legitimacy"
        assert delta == pytest.approx(-0.15 * 0.1, abs=1e-9)  # effect * source_delta
        assert applies_on_turn == 1

        # Now run a mechanical phase (advances turn to 1) and check that
        # apply_pending_effects applies the queued effect
        pre_apply = get_variable(conn, "sv_internal_legitimacy")
        run_mechanical_phases(conn)
        post_apply = get_variable(conn, "sv_internal_legitimacy")

        # The effect should have been applied
        assert post_apply < pre_apply, "Internal legitimacy should have decreased"

        # Verify the pending effect was deleted
        leftover = conn.execute(
            "SELECT COUNT(*) FROM pending_effects WHERE applies_on_turn=1"
        ).fetchone()[0]
        assert leftover == 0, "Applied pending effect should be deleted"


class TestActionResolution:
    """Tests for RNG and action resolution."""

    def test_resolve_action_is_replayable_with_same_seed(self, conn):
        """Same seed should produce same outcome and roll."""
        outcomes = [
            {
                "outcome_id": "critical_success",
                "probability": 0.1,
                "state_transitions": [],
            },
            {"outcome_id": "success", "probability": 0.3, "state_transitions": []},
            {"outcome_id": "partial", "probability": 0.4, "state_transitions": []},
            {"outcome_id": "failure", "probability": 0.15, "state_transitions": []},
            {"outcome_id": "critical_failure", "probability": 0.05, "state_transitions": []},
        ]

        # First call with explicit seed
        outcome1, roll1, seed1 = resolve_action(conn, outcomes, turn_number=0, seed=42)

        # Second call with same seed
        outcome2, roll2, seed2 = resolve_action(conn, outcomes, turn_number=0, seed=42)

        # Should be identical
        assert outcome1["outcome_id"] == outcome2["outcome_id"]
        assert roll1 == roll2
        assert seed1 == seed2

    def test_resolve_action_respects_probability_weights(self, conn):
        """Outcome with prob 1.0 should always be selected."""
        outcomes = [
            {"outcome_id": "guaranteed", "probability": 1.0, "state_transitions": []},
            {"outcome_id": "impossible1", "probability": 0.0, "state_transitions": []},
            {"outcome_id": "impossible2", "probability": 0.0, "state_transitions": []},
        ]

        # Test with 50 different seeds
        for seed_val in range(50):
            outcome, roll, used_seed = resolve_action(conn, outcomes, turn_number=0, seed=seed_val)
            assert outcome["outcome_id"] == "guaranteed", (
                f"Outcome with prob 1.0 should always be selected; got {outcome['outcome_id']} "
                f"with seed {seed_val}"
            )
