# SELF Documentation Index

This directory contains the operational, architectural, and developer documentation for the SELF autonomous agent system.

---

## Documentation Distribution & Boundary Model

The repository maintains an explicit boundary between documentation shipped into the container image and internal documentation retained strictly on the host:

| Documentation Area | Shipped in Docker Image? | Destination Path | Purpose & Access Rules |
| :--- | :--- | :--- | :--- |
| **Plugin Documentation** (`docs/plugins/`) | **YES** (Read-Only) | `/opt/agent/docs/plugins/` | Shipped in the image for developers and tools. Scanned by `agent/tests/plugins/test_docs_and_image.py` to ensure no internal paths, credentials, or forbidden keywords appear. |
| **Architecture Specifications** (`docs/architecture/`) | **NO** (Host-Only) | *Excluded from image* | Detailed 11-part internal architectural specifications, system maps, and verbatim prompts. Excluded via `Dockerfile`. |
| **Operator Runbooks** (`docs/operations.md`) | **NO** (Host-Only) | *Excluded from image* | Host-side commands for building, testing, running soak suites, backups, and pre-live deployment gates. |
| **Reference Guides** (`docs/glossary.md`, `docs/faq.md`) | **NO** (Host-Only) | *Excluded from image* | Conceptual terminology definitions from code, and honest technical answers to common operational questions. |
| **Workspace Migration** (`docs/workspace-migration.md`) | **NO** (Host-Only) | *Excluded from image* | Operator procedures for migrating persistent workspace state, backing up state, and byte-for-byte SHA-256 rollback. |
| **Historical Reports** (`docs/reports/`, etc.) | **NO** (Host-Only) | *Excluded from image* | Historical milestone verification logs and experiment records. |

---

## Directory Map

### 1. Developer & Plugin Documentation (`docs/plugins/`)
- **[plugins/README.md](../plugins/README.md)**: Hands-on developer guide: what is a plugin, how to build one, and how to attach it to SELF.
Shipped inside `/opt/agent/docs/plugins/`:
- **[overview.md](plugins/overview.md)**: Conceptual overview of plugins vs. tools, plugin classes (`body`, `skill`, `both`), and external system rules.
- **[manifest-reference.md](plugins/manifest-reference.md)**: Complete specification of all 15 fields of `plugin.json` and Core API compatibility ranges.
- **[authoring-guide.md](plugins/authoring-guide.md)**: Tutorial on scaffolding, implementing, validating, and testing plugins with the SDK CLI.
- **[permissions-and-risk.md](plugins/permissions-and-risk.md)**: Permission levels (L0 to L3), risk classes, and declarative human policies in `config/permissions.json`.
- **[lifecycle.md](plugins/lifecycle.md)**: Dynamic plug/unplug semantics, cycle-boundary synchronization, SHA-256 hash pinning, and state isolation.
- **[testing.md](plugins/testing.md)**: Guide to writing unit tests, simulation tests with `SimBody`, and scenario fixtures.
- **[self-development.md](plugins/self-development.md)**: Agent-driven autonomous plugin development, the 5-rung capability ladder, cost ledger, and stop-loss boundaries.
- **[example-pet-companion.md](plugins/example-pet-companion.md)**: Complete walkthrough of the shipped reference plugin `pet_companion`.

### 2. Operational Guides & Runbooks
Host-side operational documentation:
- **[operations.md](operations.md)**: Host-side operator runbook: building containers, running offline test suites, executing the deterministic soak suite, live diagnostic checks, and pre-live run safety checklists.
- **[workspace-migration.md](workspace-migration.md)**: Step-by-step procedures to migrate older workspaces to the tagged-state schema, with snapshot backups and byte-for-byte rollback.
- **[glossary.md](glossary.md)**: Canonical glossary defining terms directly from code implementations (cycle, session, handoff, plan, capability ladder, stop-loss, soak).
- **[faq.md](faq.md)**: Honest, concrete answers to technical questions about safety, costs, capabilities, stopping, and versioning.

### 3. Architecture Specifications (`docs/architecture/`)
Comprehensive internal design and implementation documents:
- **[README.md](architecture/README.md)**: Architecture index and verification rules.
- **[BRIEFING.md](architecture/BRIEFING.md)**: High-level architectural briefing, cycle diagram, essential implementation facts, state tables, and hotspot analysis.
- **[01-repo-map.md](architecture/01-repo-map.md)**: Repository layout, execution topology, and environment variables.
- **[02-runtime-loop.md](architecture/02-runtime-loop.md)**: Execution loop, prompt assembly, and tool round handling.
- **[03-tools.md](architecture/03-tools.md)**: Tool subsystem, base tools inventory, and dynamic tool creation pipeline.
- **[04-state-and-persistence.md](architecture/04-state-and-persistence.md)**: Census of persistent state files, schemas, and caps.
- **[05-llm-and-models.md](architecture/05-llm-and-models.md)**: Multi-model architecture, LLM clients, and provider routing.
- **[06-plan-identity-conversation.md](architecture/06-plan-identity-conversation.md)**: Plan store, persistent identity, reflection threads, and conversation channels.
- **[07-safety-and-limits.md](architecture/07-safety-and-limits.md)**: Security boundaries, permission broker, rate limits, and audit trails.
- **[08-events-catalog.md](architecture/08-events-catalog.md)**: Exhaustive catalog of all 135 structured events emitted to `actions.jsonl`.
- **[09-tests.md](architecture/09-tests.md)**: Test suites breakdown (337 harness tests + 20 eval tests).
- **[10-coupling-and-seams.md](architecture/10-coupling-and-seams.md)**: Coupling analysis, dependency ranking, and architectural seams.
- **[11-known-issues-and-unknowns.md](architecture/11-known-issues-and-unknowns.md)**: Tracked technical debt, known gaps, and open empirical questions.
- **[prompts-verbatim.md](architecture/prompts-verbatim.md)**: Exact verbatim text of all core system and critic prompts.
- **[system-map.json](architecture/system-map.json)**: Machine-readable architecture map generated by `scripts/build_system_map.py`.
