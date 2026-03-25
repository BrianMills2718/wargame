Here is exactly how this hybrid architecture executes a turn. We will trace a single command from the human player, through the two LLMs, and into the Python dice-roller. 

### **1. The Human Input (The Principal)**
The U.S. Player types their command into the interface:
> *"I want Cyber Command to deploy a Stuxnet-style malware into Iran's Natanz facility. The goal is to quietly burn out their centrifuges to delay nuclear breakout, but it needs to look like internal engineering failures. Zero attribution to us."*

---

### **2. The Parser LLM Output (`ActionIntent`)**
The Parser LLM reads the human input, strips the flavor, and maps it strictly to the programmatic capabilities the U.S. currently has in the database. 

```json
{
  "action_id": "act_8f72c1a9",
  "actor_id": "actor_us_president",
  "action_category": "covert",
  "target_entities": [
    "actor_iran_nuclear_program", 
    "facility_natanz"
  ],
  "instruments_used": [
    "inst_us_cyber_command", 
    "inst_us_covert_action"
  ],
  "intended_effect": "Deploy malware to degrade Iranian centrifuge performance and delay nuclear enrichment. Must mimic internal faults to prevent attribution.",
  "ambiguity_flags": [
    "deniable_attribution", 
    "delayed_execution"
  ]
}
```

---

### **3. The Game Master LLM Output (`AdjudicationPacket`)**
The Python backend takes that `ActionIntent`, grabs the current `CanonicalState` variables for the U.S. and Iran, and sends them to the Game Master LLM. 

The GM LLM acts as the physics/psychology engine. Notice how it respects the "No God Moding" rule: the most likely outcomes are a partial success or a quiet failure. The probabilities sum perfectly to 1.0.

```json
{
  "action_id": "act_8f72c1a9",
  "relevant_variables": [
    "ws_pos_iran_nuclear_latency",
    "ws_flow_military_tension_level",
    "ws_pos_us_regional_influence"
  ],
  "proposed_new_variables": [],
  "possible_outcomes": [
    {
      "outcome_id": "critical_success",
      "narrative_description": "The malware bypasses the airgap undetected. It subtly destroys centrifuges over months. Enrichment is severely delayed, and Iran blames poor domestic engineering.",
      "probability": 0.10,
      "state_transitions": [
        { "var_id": "ws_pos_iran_nuclear_latency", "delta": 3.0 }
      ]
    },
    {
      "outcome_id": "partial",
      "narrative_description": "The malware degrades some systems but triggers automated safety shutdowns. The delay is moderate. Iranian counter-cyber teams suspect a state actor but lack hard attribution.",
      "probability": 0.40,
      "state_transitions": [
        { "var_id": "ws_pos_iran_nuclear_latency", "delta": 1.0 },
        { "var_id": "ws_flow_military_tension_level", "delta": 0.1 }
      ]
    },
    {
      "outcome_id": "failure",
      "narrative_description": "The payload fails to breach the facility's updated network defenses. The operation is a dud, but no alarms are tripped.",
      "probability": 0.30,
      "state_transitions": []
    },
    {
      "outcome_id": "critical_failure",
      "narrative_description": "The malware is immediately caught. Forensic signatures heavily implicate U.S. Cyber Command, handing Iran a diplomatic victory and spiking regional threat perceptions.",
      "probability": 0.20,
      "state_transitions": [
        { "var_id": "ws_flow_military_tension_level", "delta": 0.5 },
        { "var_id": "ws_pos_us_regional_influence", "delta": -0.2 }
      ]
    }
  ],
  "observability_rules": {
    "actor_us": [
      "Operation deployed. Awaiting telemetry."
    ],
    "actor_iran": [
      "Routine network logs nominal.",
      "IF critical_failure: Severe intrusion detected. Code architecture matches known U.S. state-sponsored toolkits."
    ],
    "public": [
      "No observable events.",
      "IF critical_failure: Iran publicly accuses the U.S. of cyber terrorism at the UN Security Council."
    ]
  }
}
```

---

### **4. The Programmatic Backend (The Python Dice Roller)**
The LLMs are now completely out of the loop. Your Python script takes over to enforce the reality of the game. It runs something like this:

```python
import random

# Extract data from the GM's AdjudicationPacket
outcomes = packet["possible_outcomes"]
choices = [outcome["outcome_id"] for outcome in outcomes]
weights = [outcome["probability"] for outcome in outcomes]

# The Engine rolls the dice
realized_outcome_id = random.choices(choices, weights=weights, k=1)[0]

# Find the winning outcome object
realized_outcome = next(o for o in outcomes if o["outcome_id"] == realized_outcome_id)

# 1. Update the Canonical Database
for transition in realized_outcome["state_transitions"]:
    update_database_state(transition["var_id"], transition["delta"])

# 2. Route Observations to Player Screens based on the result
distribute_fog_of_war_logs(packet["observability_rules"], realized_outcome_id)
```

### **Why This Architecture Sings**
* **The LLM never touches the database directly.** It only suggests math. Python applies the math.
* **No Hallucinated States:** The Parser LLM forces the player's wild ideas into established `instruments_used`. 
* **True Fog of War:** The Iranian player doesn't see "The US rolled a 0.30 and failed." If the engine rolls a `failure`, the Iranian player's screen literally just says: *"Routine network logs nominal."* They have no idea they were even attacked. 

This is the blueprint for the extraction and execution pipeline. It completely limits the LLM to what it does best (creative interpretation, probability estimation, and parsing text) while offloading state memory to standard, unbreakable code.