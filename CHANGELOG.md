# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
