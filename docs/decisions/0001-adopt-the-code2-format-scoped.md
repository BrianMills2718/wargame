---
description: Adopt the code2 repository format for scenario loading only, with a fast scoped check
---

# 0001 Adopt the code2 format, scoped

Date: 2026-11-17
Status: accepted
Source: inferred by agent, 2026-11-17: adopt the format now for active vision parts (Brian, 2026-11-17: "option B is what i want")

## Context

Wargame had no README, docs index, architecture page, decision records, OpenSpec specs or Makefile. It has 17 test files and a long suite, some of which call web and LLM-adjacent code.

## Decision

- One capability is under Lockstep: `scenario-loading` (`wargame/scenario.py`), covered by three existing tests in `tests/test_scenario.py`.
- `make check` runs the Lockstep checks, OpenSpec validation and `tests/test_scenario.py`. The whole suite is `make full`; the repository had no earlier check target, so nothing was renamed. `make full` is not green on origin/main: 7 test files fail at collection (the `httpx2` package that starlette's test client needs is undeclared, and the installed `llm_client` has no `call_llm_structured`). Left as found.
- Lockstep scans the `wargame` folder; the `Implements:` line sits in `wargame/scenario.py`. No behaviour or existing test changed.

## Consequences

Other modules stay outside the contract until their next change. Coverage in `docs/status.md` covers only this capability.

## Wrong if

Lockstep reports Implements or marker findings against other `wargame` modules, or `make check` takes more than a few minutes.
