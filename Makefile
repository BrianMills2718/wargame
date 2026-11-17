.PHONY: fast check full docs-specs
unexport GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE GIT_PREFIX GIT_COMMON_DIR GIT_OBJECT_DIRECTORY
docs-specs:
	@mkdir -p docs/specs/scenario-loading
	@ln -sfn ../../../openspec/specs/scenario-loading/spec.md docs/specs/scenario-loading/spec.md
fast:
	uv run lockstep check trace
	uv run lockstep check sources
	uv run lockstep check project --check
	openspec validate --all --strict --no-interactive
check: docs-specs fast
	uv run pytest tests/test_scenario.py
	uv run lockstep check arch check
full: check
	uv run pytest
