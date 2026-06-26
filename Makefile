# Wargame Makefile
#
# Usage: make help

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ─── Development ─────────────────────────────────────────────────────────

.PHONY: test check install

test:  ## Run tests
	@pytest tests/ -q --tb=short

check:  ## Run tests + lint
	@pytest tests/ -q --tb=short && ruff check . 2>/dev/null || true

install:  ## Install in editable mode
	@pip install -e .

# ─── Help ────────────────────────────────────────────────────────────────

.PHONY: help

help:  ## Show available targets
	@echo "Wargame"
	@echo ""
	@grep -E '^[a-z][-a-zA-Z0-9_]*:.*## ' $(MAKEFILE_LIST) | \
		awk -F ':.*## ' '{printf "  make %-20s %s\n", $$1, $$2}'
