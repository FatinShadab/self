# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

### Versioning Scheme
- **Core Engine Releases (`core-v<major>.<minor>.<patch>[-rcN]`):** Tracks releases of the complete autonomous agent system, runtime loop, safety mechanisms, container packaging, and operator tooling (e.g. `core-v0.1.0-rc1`, `core-v0.1.0-rc2`).
- **Plugin API Specification (`VERSION` file and `CORE_API_VERSION`):** SemVer specification governing the plugin interface (manifest schema, lifecycle hooks, tool registration, permissions, and slash commands). Plugins declare compatibility ranges against this specification (e.g. `core_api: ">=1.1.0,<2.0.0"`). Git tags `v1.0.0` and `v1.1.0` mark Plugin API milestones.

## [core-v0.1.0-rc3] - 2026-10-22

### Added
- **Deterministic Soak Test Suite (Prompt 20)**:
  - Scripted provider soak runner (`scripts/soak.ps1`) executing multi-cycle deterministic scenarios (B1 through B10) over 60 to 200 cycles without real LLM provider spend.
  - Per-cycle invariant verification checking daily token budget balance, bounded handoffs (≤ 6,000 chars), plan hygiene, header deduplication, and absence of tight spins.
  - Historical replay fixture and `ReplayProvider` running reproducible 30-cycle execution traces (`agent/tests/soak/test_soak_30_cycles_replay.py`).
  - Pre-live soak gate invariant validator (`scripts/live-soak-gate.ps1` and `scripts/live_soak_gate.py`).
  - Strict daily ledger monitoring on canonical `state/token_ledger.json` and active reservations.

### Fixed
- **Tight Spin Prevention**: Fixed tight spinning loop in `AgentLoop._pause_until_daily_reset` when remaining token balance was lower than minimal model call size.
- **Recursive Handoff Header Accumulation**: Prevented recursive accumulation of `"Session complete after X cycles"` in `SessionCoordinator`.
- **Legacy Handoff Bounding on Load**: Ensured oversized legacy handoffs are bounded and archived to `handoff_overflow.json` immediately upon load in `SessionStore`.
- **Indented JSON Handoff Length Measurement**: Fixed handoff character count checks to evaluate `indent=2` JSON formatting matching disk persistence.

## [core-v0.1.0-rc2] - 2026-10-22

### Added
- **Release Candidate Hardening (Prompt 19)**:
  - Empty cost ledger bootstrap baseline support, allowing initial plugin proposals on fresh workspaces with zero prior recorded tool history.
  - Stop-loss draft write blocking: blocked `write_file` and `run_shell` modifications to `workspace/plugin_dev/<name>` when an unacknowledged stop-loss review is pending.
  - Ordinal cross-platform sorting for deterministic plugin SHA-256 hash pinning.
  - Permission broker event mapping in architecture catalog and system map.
  - Reserved slash commands AST verification to prevent plugin command collisions with core human controls.

### Fixed
- **Handoff Cap Alignment**: Aligned `HANDOFF_CAP` in `agent/session/session.py` to 6,000 characters matching architecture specification.
- **Windows File Lock Contention**: Handled lock file contention on uninitialized lock bytes in `agent/infra/file_lock.py`.

## [core-v0.1.0-rc1] - 2026-10-21

### Added
- **Core Release Candidate 1 Suite (Prompt 18)**:
  - Zero-plugin regression suite (`agent/tests/plugins/test_release_regression.py`) and golden prompt snapshots ensuring full backwards-compatibility when the plugin subsystem is present but no plugins are enabled.
  - Enable, disable, and replug round-trip verification for the `pet_companion` demo plugin across cycle boundaries.
  - Live diagnostic check script (`scripts/live-check.ps1` and `scripts/test-live-check.ps1`) reporting discovered plugin status, SHA-256 hash pinning state, plugin proposals, active project reviews, cost ledger summaries, and warnings on `plugin_hash_mismatch`.
  - Run log analysis module (`agent/reporting/run_analysis.py` and `scripts/analyze-run.ps1`) evaluating 30-cycle execution traces: plan updates (agent vs harness_auto), handoff growth, human input decisions, failure categorizations, plugin lifecycle events, and per-cycle token spend.
  - Workspace migration documentation (`docs/workspace-migration.md`) and state partitioning migration script (`scripts/migrate_p14_tagged_state.py`) providing automated snapshot creation and byte-for-byte SHA-256 rollback.
  - Read-only container distribution of developer documentation in `/opt/agent/docs/plugins/` with strict exclusion of internal architecture and evaluation files from the image.

## [1.1.0] - 2026-10-21

### Added
- **Plugin Self-Development & Cost Awareness Pipeline (Prompt 17)**:
  - `CostLedger` primitive (`state/cost_ledger.jsonl`) aggregating measured token spend, LLM calls, wall-clock duration, cycles, and attempts for custom tools and plugin development projects.
  - Six new autonomous tools on `ToolRunner`: `read_cost_ledger`, `propose_plugin`, `scaffold_plugin`, `validate_plugin`, `test_plugin`, `request_plugin_review`.
  - Proposal requirements with 10 mandatory fields; cost estimates must reference measured ledger medians and p90 baselines, rejecting contradictory figures.
  - Isolated draft area in `workspace/plugin_dev/<name>/`; discovery strictly ignores `plugin_dev/`.
  - Advisory static validation (`validate_plugin`) scanning manifest schema, namespacing, permissions, secret credential access, undeclared network/subprocess use, and prompt injection patterns.
  - Sandboxed test runner (`test_plugin`) executing in child process with stripped credentials and loopback proxy routing (`127.0.0.1:0`).
  - Strict critic review prompt (`PLUGIN_CRITIC_PROMPT`) checking declared action risk levels, untrusted data handling, state isolation, unplug behavior, and test quality, subject to daily token ledger budget reservations.
  - Stop-loss review checkpoints at 25%, 50%, and 100% of estimate upper bound; unacknowledged thresholds block further self-dev tools until explicit continue / reduce_scope / abandon plan decisions are recorded.
  - Human governance commands: `/proposals`, `/proposals comment <name> <comment>`, and `/plugins promote <name>`.
  - Added `"proposal"` and `"proposals"` to `RESERVED_SLASH_COMMANDS`.
- **Plugin Slash Command Framework**:
  - `PluginCommand` manifest specification and core API registration mechanism.
  - Manifest field `commands` allowing plugins to declare human-facing slash commands.
  - Lifecycle dispatch via `PluginManager.register_command` and `handle_slash_command`.
  - Non-intercepting slash command routing in `wake.py` for direct human interaction without polluting autonomous input queues.
  - Hard human control protection: `RESERVED_SLASH_COMMANDS` enforcement forbidding plugins from registering or shadowing `/stop`, `/pause`, `/resume`, `/kill`, `/rename`, `/plugin`, or other core human controls.
- **Example Demo Plugin `pet_companion`**:
  - Shipped under `/opt/agent/plugins/examples/pet_companion` (disabled by default, zero network, zero token spend).
  - Simulated habitat with virtual pet "Pixel" (hunger, energy, mood, last-interaction tick, cleanliness, temperature, food bowl).
  - Sensors (`pet_status`, `habitat_status`), actions (`feed`, `play`, `rest_pet` at L1; irreversible `release_pet` at L2 denied by default), and conversation tool (`talk_to_pet`).
  - Human direct slash command `/pet <message>`.
  - Embodiment text ensuring first-person agent identity is maintained and virtual pet state is not interpreted as sentience.

### Changed
- **System Prompt Head**: Added the explicit 5-rung capability ladder (a. existing tools, b. helper model, c. create a tool, d. develop a plugin, e. request capability expansion from human; lowest rung preferred with justification) and cost floor principles unconditionally to the core system prompt preamble. Note: This consciously modifies the baseline system prompt string from Phase 14 while preserving character-for-character prompt formatting across embodiments.

## [1.0.0] - 2026-10-21

### Added
- **Plugin System**: Modular specialization framework enabling decoupled bodies (senses and actions) and skills (tools and goal seeds).
  - Dynamic discovery and loading of plugins from shipped `/opt/agent/plugins` and workspace `workspace/plugins/<name>`.
  - Dynamic registration of namespaced tools (`<plugin>.<tool>`) preventing collisions with core tools.
  - Cycle-boundary hot plug, unplug, and state synchronization.
  - Graceful interception for vanished tools returning structured observations without core crashes.
  - Human-owned enablement and SHA-256 hash pinning via `/config/plugins.json`.
  - Plugin removal with automated archiving to `workspace/plugins/_archive/<name>-<timestamp>/`.
- **Plugin-Tagged State**: Cross-subsystem entity ownership tagging (`plugin`, `body`) across persistent plan goals, verified map facts, episodic memories, and custom tool metadata.
  - Automatic goal suspension (`status: "suspended: plugin disabled"`) when plugins are disabled.
  - Explicit exemptions for suspended goals from stale pruning, item consolidation, boot pruning, and archive purging.
  - Resumption on re-enable with required re-verification notes.
  - Bounded memory retrieval and ranked lesson summaries preventing unbounded prompt growth.
- **Core API Versioning**:
  - `CORE_API_VERSION` constant (`1.0.0`) and repository root `VERSION` file.
  - Manifest `core_api` compatibility ranges with simple range syntax (`>=1.0,<2.0`, `^1.0.0`, `~1.0.0`).
  - Clear breaking (major), additive (minor), and fix (patch) contract definitions.
  - Rejection of incompatible plugins with clear diagnostics and `plugin_load_failed` logging.
  - Preserved state and suspended goals when an enabled plugin becomes incompatible after a core upgrade.
- **Plugin SDK & CLI**:
  - CLI commands via `python -m agent.plugins`: `new`, `validate`, `list`, and `check`.
  - Static validation without executing untrusted plugin code.
  - Scaffold template in `plugins/_template` with manifest, tool, sensor, action, and unit tests.
  - Exclusion of `_template` and `_archive` directories from discovery and hash computation.
- **Plugin Documentation**:
  - Dedicated developer documentation in `docs/plugins/`: overview, manifest reference, authoring guide, permissions and risk, lifecycle, and testing.
  - Shipped read-only documentation in container image at `/opt/agent/docs/plugins`.

## [0.1.0] - 2026-10-17

### Added
- Modularized harness package tree (`agent.infra`, `agent.llm`, `agent.body`, `agent.tools`, `agent.learning`, `agent.helper_models`, `agent.identity`, `agent.runtime`, `agent.session`, `agent.reporting`, `agent.ui`).
- Host-only randomized helper-model A/B planner, seed workspaces, and sequential runner.
- Learning report and `/models` snapshot telemetry with measured usage and decision origins.
- Open-source governance, security policy, contribution guidelines, and CI foundation.
