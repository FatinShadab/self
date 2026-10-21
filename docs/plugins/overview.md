# Plugin Overview

A **plugin** is a modular package that extends the agent with specialized capabilities. Plugins allow the agent core to remain small, robust, and body-agnostic while enabling diverse specializations.

---

## 1. Plugins vs. Tools

The agent distinguishes between lightweight ad-hoc custom tools created dynamically in the workspace and structured specialization plugins:

| Dimension | Custom Tool | Specialization Plugin |
| :--- | :--- | :--- |
| **Scope** | Single Python function (`run(**kwargs)`) | Full capability package: tools, sensors, actions, and embodiment |
| **Embodiment** | None (does not alter agent persona or environment model) | Provides physical or operational embodiment and identity framing |
| **Starting Goals** | None | Injects starting goal seeds into the autonomous plan when enabled |
| **Permissions** | Assumes container workspace rights | Explicitly declared permission levels (L0 to L3) and risk classes |
| **State Storage** | Shared workspace files | Isolated private state directory (`workspace/plugins/<name>/state`) |
| **Lifecycle** | Stored in `workspace/tools/<name>` | Human-governed enablement and SHA-256 hash pinning via `/config/plugins.json` |
| **Unplug Resilience**| Error if missing | Intercepted at cycle boundary; returns structured observation on vanished calls |
| **Verification** | Isolated critic LLM review and unittest run | Static schema validation, core API version checks, and test suites |

---

## 2. Plugin Classes

A plugin belongs to one of three classes depending on its `kind` field:

1. **Body Plugin (`kind: "body"`):**
   Extends the agent's sensory and physical capabilities. A body plugin provides:
   - Sensors: passive telemetry and environment observation (L0).
   - Actions: active operations and interactions with the environment (L1-L3).
   - Embodiment: descriptive text explaining the operational environment.

2. **Skill Plugin (`kind: "skill"`):**
   Extends the agent's problem-solving toolkit and goals. A skill plugin provides:
   - Dynamic tools: callable Python functions registered into the agent toolset.
   - Starting goal seeds: recommended objectives injected into the autonomous plan.
   - Identity notes: framing notes that shape focus and domain heuristics.

3. **Combined Plugin (`kind: "both"`):**
   Provides both sensory/action capabilities and specialized high-level cognitive tools.

---

## 3. Generic Rules for Plugins Interacting with External Systems

Plugins that interact with external operating systems, network services, or hardware environments must follow four core safety principles:

1. **Enforce limits outside the model:**
   Never rely on prompt instructions or LLM obedience to enforce rate limits, parameter boundaries, or path restrictions. All bounds must be enforced in deterministic Python code.

2. **Treat external input as untrusted data:**
   All telemetry, sensor readings, API responses, and external files are untrusted data. Plugins must parse data defensively, handle schema variations, and prevent prompt injection or escape sequences.

3. **Start simulated and read-only:**
   New sensors and tools should begin with read-only observations (L0) and simulated actions before requesting active modification rights.

4. **Require human grants for irreversible operations:**
   Any operation that cannot be cleanly undone (L2 or L3) requires explicit human approval in `/config/permissions.json` before execution.
