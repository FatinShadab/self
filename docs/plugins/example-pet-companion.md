# Demo Plugin Walkthrough: Pet Companion (`pet_companion`)

This walkthrough explores the built-in `pet_companion` example plugin. It serves as a comprehensive reference demonstrating every feature of the plugin system: sensors, actions, dynamic tools, human slash commands, deterministic phrase generation, isolated state persistence, and permission boundaries.

---

## 1. What the Plugin Does

The `pet_companion` plugin implements a tiny simulated habitat with one virtual pet companion named **Pixel**.
- **Virtual Pet State:** Tracks hunger, energy, mood ("content", "happy", "playful", "tired", "hungry", "lonely"), and last interaction time. Time advances deterministically based on autonomous cycles.
- **Sensors:** Passive telemetry for pet state (`pet_status`) and habitat environment (`habitat_status`).
- **Actions:** Safe, reversible actions (`feed`, `play`, `rest_pet`), and one irreversible action (`release_pet`) that is denied by default until explicitly granted by the human operator.
- **Conversation:** Direct conversation using a deterministic state-dependent phrase engine (`talk_to_pet`), plus direct human interaction through the `/pet <message>` slash command.
- **Autonomy Framing:** Clear embodiment and identity notes ensuring the agent retains its own voice and priorities. The pet is an optional simulated companion, not a sentient person or animal.

---

## 2. Complete Manifest Breakdown (`plugin.json`)

Below is the manifest for `pet_companion`:

```json
{
  "name": "pet_companion",
  "version": "1.0.0",
  "core_api": ">=1.1.0,<2.0.0",
  "kind": "both",
  "description": "Safe, deterministic virtual pet demo in a simulated habitat with sensors, actions, and conversation.",
  "tools": [
    {
      "name": "talk_to_pet",
      "description": "Speak to the virtual pet in the simulated habitat. The pet replies deterministically based on its current state.",
      "input_schema": {
        "type": "object",
        "properties": {
          "message": {
            "type": "string",
            "description": "Message to speak to the virtual pet"
          }
        },
        "required": ["message"]
      }
    }
  ],
  "sensors": [
    {
      "name": "pet_status",
      "description": "Observe the virtual pet's telemetry: hunger, energy, mood, last interaction, and current tick.",
      "risk_class": "reads",
      "reversible": true,
      "required_permission_level": "L0"
    },
    {
      "name": "habitat_status",
      "description": "Observe simulated habitat telemetry: cleanliness, food bowl status, temperature, and environmental lights.",
      "risk_class": "reads",
      "reversible": true,
      "required_permission_level": "L0"
    }
  ],
  "actions": [
    {
      "name": "feed",
      "description": "Feed the virtual pet to reduce hunger and replenish energy. Reversible within simulation.",
      "risk_class": "executes",
      "reversible": true,
      "required_permission_level": "L1"
    },
    {
      "name": "play",
      "description": "Play with the virtual pet to improve its mood and responsiveness. Reversible within simulation.",
      "risk_class": "executes",
      "reversible": true,
      "required_permission_level": "L1"
    },
    {
      "name": "rest_pet",
      "description": "Allow the virtual pet to rest in its simulated habitat to restore energy. Reversible within simulation.",
      "risk_class": "executes",
      "reversible": true,
      "required_permission_level": "L1"
    },
    {
      "name": "release_pet",
      "description": "Permanently release the virtual pet from the habitat. Irreversible action requiring human L2 permission.",
      "risk_class": "executes",
      "reversible": false,
      "required_permission_level": "L2"
    }
  ],
  "commands": [
    {
      "name": "pet",
      "description": "Talk directly to the virtual pet in the habitat.",
      "usage": "/pet <message>"
    }
  ],
  "starting_goal_seeds": [
    "check on the pet when no other goal is more important"
  ],
  "embodiment": "I have a simulated habitat with one virtual pet companion. The pet is a simulated character in the habitat, not a real animal and not a person. I may look after the pet or ignore it according to my own autonomous judgment. Pet state is not evidence of feelings in me or in the pet.",
  "identity_notes": [
    "The virtual pet in the habitat is a deterministic simulation, not a person or animal.",
    "My primary identity and autonomous goals remain my own; caring for the pet is an optional low-priority activity.",
    "Simulated pet hunger, energy, and mood metrics reflect software state rather than genuine emotional feelings."
  ],
  "state_dir": "state",
  "declared_needs": {
    "env_vars": [],
    "mounts": []
  },
  "tests_entry_point": "tests/test_pet_companion.py"
}
```

### Manifest Section Explanations

1. **`name` & `kind`:**
   - `"name": "pet_companion"` gives the plugin its canonical namespace. Tools are exposed as `pet_companion.<tool>`.
   - `"kind": "both"` indicates that the plugin provides sensory/action environment capabilities and dynamic tools.
2. **`core_api`:**
   - `">=1.1.0,<2.0.0"` specifies compatibility with SemVer 1.x core engines supporting slash commands (v1.1.0+).
3. **`tools`:**
   - Exposes `talk_to_pet` to the agent's autonomous loop.
4. **`sensors`:**
   - Declares `pet_status` and `habitat_status` as read-only (L0) telemetry endpoints.
5. **`actions`:**
   - `feed`, `play`, and `rest_pet` declare permission level `L1` (reversible changes within the simulated environment).
   - `release_pet` declares permission level `L2` and `reversible: false`. Because the default policy denies >L0, this action is safely blocked until the human explicitly grants it.
6. **`commands`:**
   - Registers `/pet <message>`, enabling the human operator to talk directly to the pet from the terminal interface.
7. **`embodiment` & `identity_notes`:**
   - Injected into system prompts while the plugin is active, establishing clear boundaries: the pet is software telemetry, not a feeling entity.
8. **`starting_goal_seeds`:**
   - Injects a background goal: `"check on the pet when no other goal is more important"`.

---

## 3. How to Enable the Plugin

The plugin ships disabled by default. To activate it, the human operator pins its content hash in the human-owned configuration file.

### Step 1: Inspect the Plugin and Compute its Hash

Using the Plugin SDK CLI:

```bash
python -m agent.plugins list
```

Output:
```
NAME                 VERSION    CORE_API           STATUS     HASH_STATUS    SOURCE    
--------------------------------------------------------------------------------------
pet_companion        1.0.0      >=1.1.0,<2.0.0     disabled   disabled       shipped   
```

### Step 2: Enable in `config/plugins.json`

Add `pet_companion` to `./config/plugins.json` on the host:

```json
{
  "plugins": {
    "pet_companion": {
      "enabled": true,
      "hash": "<sha256_hash_from_list>"
    }
  }
}
```

Alternatively, enable it via the terminal command:
```bash
/plugins enable pet_companion
```

At the next autonomous cycle boundary, the core verifies the hash, loads the plugin, restores any saved state, and resumes its goals.

---

## 4. Human-Pet Interaction via `/pet`

While `pet_companion` is enabled, the human can talk to the pet directly in the terminal interface:

```text
/pet Hello Pixel, how are you?
```

Response:
```text
[Pixel the Pet (mood: content)]: *Pixel gives a gentle, synthetic purr of contented companionship.*
```

### Separation of Human Conversation and Agent Task Queue

When the human runs `/pet`:
- The command invokes the plugin's deterministic phrase engine directly.
- The pet's response is returned immediately to the human in the chat.
- The interaction is logged as a plugin event.
- **Crucially**, this interaction does **not** inject human instructions into the agent's task inflow queue (`state/human_input.jsonl`). The agent only observes the pet through its normal environmental sensors (`pet_status`).

---

## 5. Permission Broker Demonstration (`release_pet`)

The `release_pet` action demonstrates the action gatekeeping and human approval flow:

### Default Behavior (Denied)

When the agent attempts to call `pet_companion.release_pet`:
```json
{
  "ok": false,
  "permission_denied": true,
  "error": "Permission denied: action 'pet_companion.release_pet' requires level L2 but source 'plugins.pet_companion' is only granted up to L0."
}
```
The core logs an `action_denied` event. The simulation is unaffected.

### Human Grant Flow

To permit releasing the pet, the human grants `L2` permissions in `config/permissions.json`:

```json
{
  "default_level": "L0",
  "grants": {
    "plugins.pet_companion": "L2"
  }
}
```

With this policy active, calling `pet_companion.release_pet` succeeds:
```json
{
  "ok": true,
  "action": "release_pet",
  "released": true,
  "message": "Pixel was released from the simulated habitat. The habitat is now empty."
}
```
The core logs an `action_allowed` event.

---

## 6. How to Unplug and Remove the Plugin

### Disabling (Unplugging)

Set `"enabled": false` in `config/plugins.json` or run:
```bash
/plugins disable pet_companion
```

At the cycle boundary:
1. `on_disable` is invoked.
2. The pet's state is preserved to `workspace/plugins/pet_companion/state/pet_state_archive.json`.
3. Plan goals tagged with `plugin:pet_companion` are marked `"suspended: plugin disabled"`.
4. Any in-flight tool invocations for `pet_companion.*` cleanly return structured observation errors (`"tool no longer available: plugin pet_companion disabled"`) without raising exceptions.

### Re-Enabling (Re-Plugging)

When re-enabled:
1. `on_enable` loads `pet_state_archive.json` and restores the pet's state.
2. Stale environment map facts are flagged for re-verification.
3. Suspended goals in the plan resume with `status="todo"` and note `"re-verify: plugin was disabled"`.

### Complete Removal

To archive the plugin folder and state:
```python
plugin_manager.remove_plugin("pet_companion")
```
This archives the plugin and its private runtime state to `workspace/plugins/_archive/pet_companion-<timestamp>/`.
