"""Tests for the wargame.scenario module and scenario spec validation."""

import pytest
from wargame.scenario import load_scenario


class TestScenarioLoading:
    """Tests for scenario loading and basic structure."""

    def test_scenario_loads(self):
        """Scenario should load successfully with 2 actors and 16 state variables."""
        spec = load_scenario("scenarios/us_iran_2026.yaml")

        assert spec is not None
        assert len(spec.actors) == 2
        assert len(spec.state_variables) == 16

    def test_every_variable_has_an_initial_value(self):
        """Every state variable should have an initial value."""
        spec = load_scenario("scenarios/us_iran_2026.yaml")

        declared_vars = {sv.id for sv in spec.state_variables}
        initial_keys = set(spec.initial_state.keys())

        missing = declared_vars - initial_keys
        assert (
            len(missing) == 0
        ), f"These state variables have no initial_state value: {missing}"

    def test_causal_edges_reference_real_variables(self):
        """Every causal edge should reference declared state variables."""
        spec = load_scenario("scenarios/us_iran_2026.yaml")

        declared_vars = {sv.id for sv in spec.state_variables}

        for edge in spec.causal_edges:
            assert edge.source in declared_vars, (
                f"Causal edge source '{edge.source}' not in state_variables"
            )
            assert edge.target in declared_vars, (
                f"Causal edge target '{edge.target}' not in state_variables"
            )

    def test_instrument_target_vars_are_real_variables(self):
        """Every instrument's target_vars should be declared state variables."""
        spec = load_scenario("scenarios/us_iran_2026.yaml")

        declared_vars = {sv.id for sv in spec.state_variables}

        for actor in spec.actors:
            for instrument in actor.instruments:
                for target_var in instrument.target_vars:
                    assert target_var in declared_vars, (
                        f"Instrument {instrument.id} targets '{target_var}' "
                        f"which is not in state_variables"
                    )


class TestDomainModels:
    """Tests for domain model validity."""

    def test_domain_model_base_rates_sum_to_one(self):
        """Domain models with base_rates should sum to ~1.0."""
        spec = load_scenario("scenarios/us_iran_2026.yaml")

        for dm in spec.domain_models:
            if not dm.base_rates:
                # Skip domain models with empty base_rates
                continue

            total = sum(dm.base_rates.values())
            assert (
                abs(total - 1.0) <= 0.001
            ), f"Domain model {dm.id} base_rates sum to {total}, not 1.0"

    def test_every_domain_model_declares_base_rates(self):
        """Every domain model must declare base_rates.

        A model without base rates silently falls through to whichever model
        sorts first, causing ambiguous and unintuitive adjudication. Each
        model must declare its base rate distribution so compute_mechanical_base_rate
        finds the right rates for the right domain.
        """
        spec = load_scenario("scenarios/us_iran_2026.yaml")

        for dm in spec.domain_models:
            assert (
                dm.base_rates
            ), f"Domain model {dm.id} has no base_rates; this will cause ambiguity in GM adjudication"
