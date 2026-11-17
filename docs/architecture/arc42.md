# Wargame architecture

The architecture authorities are [AGENTS.md](../../AGENTS.md) (components and design principles) and `claude_code_planning/ADR-001` to `ADR-004` (mechanical engine versus GM judgment, additive layers, dynamic agents, NPC versus helper). This page does not restate them.

Scoped here: only scenario loading (`wargame.scenario`, which reads a scenario YAML into the `wargame.models` types and initializes SQLite). [The import model](model.c4) covers that module. The engine, GM, parser, advisor, scorer, AI opponent and web layers are described in AGENTS.md and are not under Lockstep.
