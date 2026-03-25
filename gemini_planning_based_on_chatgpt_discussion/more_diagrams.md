Here is the ASCII diagram mapping out the full hybrid architecture. 

It explicitly separates the **"LLM Brains"** (handling natural language, psychology, and probability estimation) from the **"Programmatic Spine"** (handling the rigid database, math, and random number generation).

```text
=========================================================================
 1. THE PRINCIPALS (Human/NL Layer)
=========================================================================
    [ Player A (e.g., U.S.) ]                 [ Player B (e.g., Iran) ]
           |      ^                                  |      ^
      (NL  |      | (NL Briefings)              (NL  |      | (NL Briefings)
    Orders)|      |                           Orders)|      |
           v      |                                  v      |
      +---------------+                         +---------------+
      | Side LLM A    |                         | Side LLM B    |
      | (Intel/Parser)|                         | (Intel/Parser)|
      +---------------+                         +---------------+
           |                                         |
           | [ActionIntent JSON]                     | [ActionIntent JSON]
           v                                         v
=========================================================================
 2. THE THIN SPINE (Python Core - Source of Truth)
=========================================================================
           +-------------------------------------------------+
           | ACTION ROUTER & STATE DATABASE                  |
           | - Validates Actor owns the Instruments used     |
           | - Holds CanonicalState (Values, Variables)      | <----+
           +-------------------------------------------------+      |
                           |                                        |
                           | (ActionIntent + Current State)         |
                           v                                        |
=========================================================================
 3. THE ADJUDICATION ENGINE (Game Master LLM)                       |
=========================================================================
           +-------------------------------------------------+      |
           | GAME MASTER LLM                                 |      |
           | - Reads intent & limits via Interaction Model   |      |
           | - NO GOD-MODING (strictly evaluates friction)   |      |
           | - Generates outcome distribution (Sum = 1.0)    |      |
           +-------------------------------------------------+      |
                           |                                        |
                           | [AdjudicationPacket JSON]              |
                           v                                        |
=========================================================================
 4. THE RESOLUTION ENGINE (Python Core)                             |
=========================================================================
           +-------------------------------------------------+      |
           | DICE ROLLER & STATE UPDATER                     |      |
           | 1. RNG execution (Python random.choices)        |      |
           | 2. Applies StateTransitions to Database --------|------+
           | 3. Enforces Observability Rules (Fog of War)    |
           +-------------------------------------------------+
                 |                                  |
                 | [ObservationPacket JSON]         | [ObservationPacket JSON]
                 v                                  v
      (Routes visible data back to Side LLMs for the next turn)

=========================================================================
 5. END OF GAME SCORING (Strategic Expert LLM)
=========================================================================
           +-------------------------------------------------+
           | EVALUATOR LLM                                   |
           | - Reads final CanonicalState vs Initial Values  |
           | - Scores asymmetric value realization           |
           +-------------------------------------------------+
```

### **Why this layout protects your game:**
1. **Total Isolation of Imagination vs. Math:** The Game Master LLM *never* touches the database. It is simply a very smart function that converts a state and an action into a probability table. Python does the actual math and state updates.
2. **True Fog of War:** The GM LLM outputs the truth of what happened alongside rules for who can see it. Python physically strips the hidden data out before sending the `ObservationPacket` back up to the Side LLMs, making it impossible for the Side LLMs to accidentally leak enemy secrets to the players.
3. **The Parser Funnel:** Because the Side LLMs are forced to output the rigid `ActionIntent JSON` to interact with the engine, players can type whatever wildly creative prose they want, but the system won't progress until the LLM successfully maps it to your established causal grammar.



Here is the complete blueprint for your system. I have ordered these from the highest level of abstraction (the entire system) down to the lowest (the exact API call sequence). 

I am providing these using **PlantUML syntax**. You can copy and paste these code blocks directly into any PlantUML viewer (like PlantText.com or the PlantUML VS Code extension) to instantly generate the visual diagrams.

### **1. Component / Architecture Diagram (The 10,000-Foot View)**
**Why first:** Before we map the data, we need to establish the hard boundaries. This diagram ensures that the Side LLMs (the players' intelligence chiefs) are physically isolated from the Canonical Database to prevent cheating or "God Moding."

```plantuml
@startuml
skinparam componentStyle rectangle

package "Client Tier" {
  [Player A UI (U.S.)] as P1
  [Player B UI (Iran)] as P2
}

package "LLM Tier (Semantic Translation)" {
  [Side Analyst LLM (U.S.)] as SideA
  [Side Analyst LLM (Iran)] as SideB
  [Game Master LLM] as GM
  [Strategic Scorer LLM] as Scorer
}

package "Programmatic Core (Python/FastAPI)" {
  [WebSocket/API Router] as Router
  [State Manager & Validator] as StateMgr
  [Dice Roller / RNG Engine] as RNG
  [Fog of War Filter] as FoW
}

database "The 'Thin Spine' DB (PostgreSQL/NoSQL)" {
  [Canonical State] as DB_State
  [Action & Event Ledger] as DB_Log
}

P1 <--> Router : Natural Language / JSON
P2 <--> Router : Natural Language / JSON

Router <--> SideA : Context + Prompts
Router <--> SideB : Context + Prompts

Router --> StateMgr : ActionIntent JSON
StateMgr --> DB_State : Read/Write Locks
StateMgr --> GM : CanonicalState + ActionIntent
GM --> RNG : AdjudicationPacket JSON (Probabilities)
RNG --> DB_State : Apply StateTransitions
RNG --> FoW : Raw Results
FoW --> Router : ObservationPackets (Filtered)
DB_Log <-- StateMgr : Audit Trail

@enduml
```

---

### **2. Entity-Relationship Diagram (The "Thin Spine" Data Schema)**
**Why second:** Now that we know where the data lives, we define what it looks like. This represents the absolute minimum relational structure needed to persist the game. Notice there are no "Objectives" or "Constraints" tables—those are derived dynamically by the LLM from the `StateVariable` table.

```plantuml
@startuml
hide circle
skinparam linetype ortho

entity "Actor" as act {
  * actor_id : UUID
  --
  name : String
  type : String
}

entity "Value" as val {
  * value_id : UUID
  --
  actor_id : UUID <<FK>>
  name : String (e.g., "Regime Survival")
  weight : Float
}

entity "StateVariable" as sv {
  * var_id : UUID
  --
  name : String (e.g., "sanctions_intensity")
  type : String (structural, positional, flow)
  current_value : Float
}

entity "Instrument" as inst {
  * inst_id : UUID
  --
  actor_id : UUID <<FK>>
  name : String
  midfield_tag : String
}

entity "ActionLog" as log {
  * action_id : UUID
  --
  turn_number : Int
  actor_id : UUID <<FK>>
  action_intent_json : JSONB
  adjudication_packet_json : JSONB
  rng_roll : Float
  realized_outcome_id : String
}

entity "Observation" as obs {
  * obs_id : UUID
  --
  turn_number : Int
  actor_id : UUID <<FK>>
  visibility_level : String (public, private)
  narrative_text : String
}

act ||--o{ val : holds
act ||--o{ inst : possesses
act ||--o{ log : initiates
log ||--|{ sv : modifies
log ||--o{ obs : generates
@enduml
```

---

### **3. UML State Machine Diagram (The Action Lifecycle)**
**Why third:** This maps the lifecycle of a single move. It is critical for engineering because it highlights the failure states (e.g., what happens if the GM LLM hallucinates bad JSON).

```plantuml
@startuml
[*] --> Drafted : Player talks to Side Analyst
Drafted --> Submitted : Player commits command

state Submitted {
  [*] --> Parsing
  Parsing --> ActionIntent_Created : Parser LLM outputs valid JSON
  Parsing --> Failed_Parsing : LLM outputs bad JSON
}

Submitted --> Validating : Python receives ActionIntent
Validating --> Rejected_Invalid_Instrument : Player lacks the Instrument
Validating --> Adjudicating : Validated against DB

state Adjudicating {
  [*] --> GM_Prompting
  GM_Prompting --> AdjudicationPacket_Created : GM returns valid probabilities (Sum=1.0)
  GM_Prompting --> Failed_Adjudication : GM returns bad math/JSON
}

Adjudicating --> Resolving : Python receives AdjudicationPacket
Resolving --> RNG_Rolled : Python picks outcome via weights
RNG_Rolled --> Applied : StateVariables updated in DB

Applied --> FogOfWar_Filtering : Python generates Observations
FogOfWar_Filtering --> [*] : Turn complete, UI updated

Failed_Parsing --> Drafted : Retry loop / Prompt user
Failed_Adjudication --> Adjudicating : Automated Retry (Max 3)
Rejected_Invalid_Instrument --> Drafted : Error to Player UI
@enduml
```

---

### **4. UML Sequence Diagram (The Turn Resolution Flow)**
**Why last:** This is the exact step-by-step API call chain. If you hand this to a backend engineer, they can build the FastAPIs and WebSockets directly from this flow. 

```plantuml
@startuml
actor "U.S. Player" as P1
participant "Side Analyst LLM" as Side
participant "Python Core" as Core
database "Database" as DB
participant "Game Master LLM" as GM

P1 -> Side : "Deploy Stuxnet to Natanz."
activate Side
Side -> Core : Submit **ActionIntent** (JSON)
deactivate Side

activate Core
Core -> DB : Validate Actor owns 'cyber_command'
activate DB
DB --> Core : Valid
deactivate DB

Core -> DB : Fetch current **CanonicalState**
activate DB
DB --> Core : Return state variables
deactivate DB

Core -> GM : Send **ActionIntent** + **CanonicalState**
activate GM
Note right of GM: Evaluates friction,\ncalculates probabilities
GM --> Core : Return **AdjudicationPacket** (JSON)
deactivate GM

Core -> Core : Parse JSON, check Probabilities sum to 1.0
Core -> Core : Roll RNG (e.g., 0.35)
Core -> Core : Select realized_outcome

Core -> DB : Execute **StateTransitions** (Update DB)
activate DB
DB --> Core : DB Locked & Saved
deactivate DB

Core -> Core : Filter via **ObservabilityRules**
Core -> P1 : Send **ObservationPacket** (U.S. View)
Core -> DB : Store full **ActionLog** for End-Game Scoring

deactivate Core
@enduml
```

### **What's Next?**
These diagrams lock in the engineering architecture. We have successfully bridged the abstract geopolitical theory with a rigid software design. 

Would you like me to start translating these diagrams into the actual **Python Pydantic models (Data Classes)** or the **FastAPI routing logic** that will run the programmatic core?
