# scenario-loading Specification

## Purpose
Characterize how a scenario YAML becomes a validated in-memory scenario specification; this describes existing behavior.

## Requirements

### Requirement: Load a scenario file

The scenario loader SHALL parse a scenario YAML file into a validated scenario specification whose actors, state variables, initial state and causal edges are internally consistent.

Source: inferred by agent, 2026-11-17: documented in AGENTS.md "Scenario Spec" and checked by tests/test_scenario.py (Brian, 2026-11-17: "option B is what i want").

#### Scenario: Bundled scenario loads

- **WHEN** the bundled US-Iran scenario is loaded
- **THEN** it has 2 actors and 16 state variables

#### Scenario: Every variable has an initial value

- **WHEN** the bundled scenario is loaded
- **THEN** every declared state variable has an initial state value

#### Scenario: Causal edges reference declared variables

- **WHEN** the bundled scenario is loaded
- **THEN** every causal edge source and target is a declared state variable
