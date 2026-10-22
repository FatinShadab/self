# SELF Technical Glossary

Canonical definitions for architectural concepts and terms used across the SELF codebase. All definitions are derived directly from Python source code implementations.

---

### Audit Trail
An append-only cryptographic event log (`workspace/state/audit_trail.jsonl`) managed by `AuditTrail` (`agent/infra/audit_trail.py:25`). Every action authorization, execution, and dry-run attempt is logged with an incrementing counter, timestamp, and SHA-256 hash chained to the preceding entry, providing tamper-evident verification of agent operations.

### Body
An abstraction layer implementing the `Body` interface (`agent/body/body.py:12`) that exposes sensory telemetry, environmental metrics, and operating environment actions to tools and the runtime loop. In default operation, `ContainerBody` (`agent/body/container.py:30`) encapsulates the Linux container environment. In simulation testing, `SimBody` (`agent/body/sim.py:25`) models virtual dynamics.

### Capability Ladder
A five-rung decision heuristic defined in the system prompt preamble (`agent/runtime/loop.py:65-72`) and `docs/plugins/self-development.md:24-38`. When addressing a problem or goal, the agent must evaluate solutions from the lowest rung upward and justify why lower rungs are insufficient:
- **Rung A:** Use existing built-in tools or active plugins.
- **Rung B:** Delegate a bounded sub-task to an eligible helper model via `ask_model`.
- **Rung C:** Create an ad-hoc custom Python tool via `create_tool`.
- **Rung D:** Propose and develop a specialization plugin via `propose_plugin`.
- **Rung E:** Request external capability expansion from the human operator via `request_capability`.

### Cost Ledger
An append-only historical telemetry ledger stored at `workspace/state/cost_ledger.jsonl` and managed by `CostLedger` (`agent/infra/cost_ledger.py:35`). It aggregates tokens spent, LLM calls made, wall-clock duration elapsed, and autonomous cycles consumed per tool creation attempt and plugin project. It supplies median and 90th percentile (p90) baselines for proposal cost derivations.

### Cycle
A single iteration of the outer autonomous loop executed by `AgentLoop.run_cycle()` (`agent/runtime/loop.py:419`). A cycle encompasses context assembly, tool retrieval, one or more inner tool rounds with the LLM, plan updates, memory creation, checkpoint persistence, and reflection scheduling.

### Embodiment
The descriptive prompt text provided by a `Body` implementation (`agent/body/body.py:28`) explaining the operational environment, available hardware or OS facilities, and boundaries to the language model. For example, `ContainerBody` explains that the agent operates inside an isolated Debian Bookworm Docker container.

### Goal
A structured objective maintained within `PlanStore` (`agent/learning/plan.py:35`). Each goal has an identifier, textual description, status (`todo`, `in_progress`, `done`, `dropped`, or `suspended: plugin disabled`), priority, and provenance tags (`plugin`, `body`). Goals marked `done` or `dropped` are purged at cycle boundaries.

### Handoff
A bounded state summary dictionary written to `workspace/state/handoff.json` at cycle boundaries and session termination by `SessionStore` (`agent/session/session.py:60`). It preserves core discoveries, active plans, open questions, and operating context across restarts. Its length is strictly bounded to ≤ 6,000 characters; when exceeded, older items are compacted and the full uncompressed state is archived to `state/handoff_overflow.json`.

### Hash Pinning
A security integrity mechanism managed by `PluginManager` (`agent/plugins/manager.py:350-400`). To prevent untrusted modification of plugin code, the human operator specifies the expected SHA-256 digest of the plugin directory in read-only `config/plugins.json`. On discovery, the core computes the recursive SHA-256 digest (sorting files ordinally and excluding private `state/`); if the hash does not match, the plugin is rejected with a `plugin_hash_mismatch` warning.

### Permission Levels
A hierarchical authorization model enforced by `PermissionBroker` (`agent/infra/permission_broker.py:28`):
- **`L0_OBSERVE`:** Passive observation, telemetry, and read-only inspection (default allowed).
- **`L1_REVERSIBLE`:** Local modifications that can be cleanly undone (e.g. temporary files).
- **`L2_IRREVERSIBLE`:** Permanent modifications to state or environment (e.g. deleting files, releasing entities). Denied unless explicitly granted in `config/permissions.json`.
- **`L3_ACTUATION`:** Physical hardware actuation or high-impact operational commands. Denied unless explicitly granted in `config/permissions.json`.

### Plan
The persistent, evolving roadmap of autonomous exploration maintained in `workspace/state/plan.json` by `PlanStore` (`agent/learning/plan.py:55`). The plan is updated by the model via `update_plan` or reviewed with `record_unchanged`. It tracks active goals, human input decisions, and milestone links.

### Plugin
A modular specialization package stored in `workspace/plugins/<name>/` or `/opt/agent/plugins/` adhering to the Plugin Specification (`agent/plugins/manifest.py:25`). Plugins provide specialized sensors, actions, dynamic tools, and embodiment framing, isolated in private state directories and declared with Core API version ranges.

### Session
A continuous execution period of the agent application managed by `WakeCoordinator` (`agent/ui/wake.py:686`) and `SessionCoordinator` (`agent/session/coordinator.py:48`). A session begins with wake-up initialization (or first awakening A-E sequence), executes multiple autonomous cycles, and ends with clean shutdown, budget exhaustion, or crash recovery. Completed sessions are appended to `state/sessions.jsonl`.

### Soak Suite
A deterministic, multi-cycle integration test suite (`scripts/soak.ps1` and `agent/tests/soak/`) executing 60 to 200 cycles against a mocked `ScriptedProvider` or historical replay fixture. It verifies that core invariants (token budget accounting, handoff size limits, memory boundedness, plan hygiene, and absence of infinite spins) hold over extended runs without incurring real provider costs.

### Stop-Loss
A project governance mechanism implemented in `SelfDevPipeline` (`agent/plugins/self_dev.py:113-144`) and `agent/runtime/loop.py:515-540`. When cumulative token or cycle spend for a plugin project reaches 25%, 50%, or 100% of its estimated ceiling, development tools are blocked until the model explicitly reviews its progress and records an arbitration decision (`continue`, `reduce_scope`, or `abandon`) in its plan.

### Tool
A callable Python function exposed to the agent model with typed parameters, an argument JSON schema, and a structured JSON return format. Tools include 29 built-in tools (`agent/tools/base_tools.py`), dynamic custom tools synthesized at runtime via `create_tool`, and namespaced plugin tools (`<plugin>.<tool>`).
