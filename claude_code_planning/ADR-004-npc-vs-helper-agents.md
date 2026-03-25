# ADR-004: In-Game NPCs vs Out-of-Game Helper Agent

**Date:** 2026-03-25
**Status:** Accepted
**Context:** The system has multiple LLM agents serving the player. The initial design conflated two distinct roles: in-game characters (Intel Chief) and out-of-game assistance (explaining the game to the player). These need to be separated because they have fundamentally different information access, reliability, and purpose.

## Decision

Two distinct agent categories serve each player:

### In-Game NPCs (unreliable narrators inside the simulation)

Characters within the game world. They are part of the fog of war.

| Property | Behavior |
|----------|----------|
| **Information access** | Limited to their domain. Intel Chief sees intelligence-grade observations. Military Advisor sees force disposition. They do NOT see canonical state. |
| **Reliability** | Can be wrong. Can be fooled by opponent deception. May have biases or agendas. |
| **Prompt framing** | "You are the Director of National Intelligence briefing the President. You only know what your intelligence apparatus has gathered." |
| **Player trust** | The player must decide whether to trust their NPCs. Healthy skepticism is gameplay. |
| **Examples** | Intel Chief, Military Advisor, Diplomatic Envoy, Treasury Secretary |

NPCs create **gameplay** — managing unreliable information sources is a core skill.

### Out-of-Game Helper Agent (reliable analyst outside the simulation)

Knows it's a game. Not a character — a tool for the player.

| Property | Behavior |
|----------|----------|
| **Information access** | Everything the player has access to — all observations, all NPC briefings, action history, game rules. But NOT canonical state, NOT opponent's state, NOT fog-of-war-hidden variables. |
| **Reliability** | Reliable within its information boundary. Will not hallucinate game state. Will say "I don't know" for things behind fog of war. |
| **Prompt framing** | "You are a strategic advisor helping a player in a geopolitical wargame. You can see everything the player has been told and all game mechanics. Help them understand the situation and make informed decisions." |
| **Capabilities** | Explain causal dynamics ("sanctions erode legitimacy over 1-2 turns"), search action history ("last time you did X, the outcome was Y"), identify risks ("nuclear latency is trending toward breakout"), suggest strategies, answer rules questions. |
| **Examples** | "What happens if I sanction their bank?" → helper explains the causal chain. "What's my biggest risk right now?" → helper analyzes visible state. |

The helper creates **accessibility** — players don't need a PhD in IR theory to play well.

### Key distinction

| | NPC | Helper |
|-|-----|--------|
| Inside the game world? | Yes | No |
| Can be fooled by deception? | Yes | No (but limited to player's info) |
| Has opinions/biases? | Yes | No (neutral analyst) |
| Knows it's a game? | No | Yes |
| Can see game mechanics? | No | Yes (causal graph, decay rates, etc.) |
| Can see behind fog of war? | No | No |

### Implementation

- NPCs are instantiated per-actor with domain-specific prompts and filtered observations
- The helper is instantiated per-player with full player-visible state + game rules context
- Both use `call_llm_structured()` or `call_llm_with_tools()` via llm_client
- The helper can be queried freely (no resource cost — it's outside the game)
- NPCs consume the player's resource budget when activated

## Consequences

- NB6 (Sub-Agents) should test BOTH NPC behavior and helper behavior
- NPC prompts must NOT include game mechanics or canonical state
- Helper prompts MUST include game mechanics but NOT canonical/opponent state
- Deception actions should degrade NPC observation quality but NOT affect the helper
- The helper should be the first thing a new player interacts with ("Ask me anything about how this works")
