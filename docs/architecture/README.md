# SELF Architecture Documentation Index

**Git Commit:** `14ffa606468920a97c672b39fbf3a43fccc52bdf`  
**Date:** 2026-10-17  
**Status:** Read-only baseline architecture documentation

---

## Overview

This directory contains the complete, evidence-based architecture and implementation specification for the `self` repository. The documentation is compiled to support transforming the codebase into a reusable agent core with plug-and-unplug specializations (e.g., an antivirus engine, a robotic/IoT body), while strictly preserving existing behavior, prompts, defaults, and runtime state.

All claims in these documents are tagged with concrete evidence:
- `[read] <path>:<line>`: Verified by reading source code.
- `[ran]`: Verified by executing tests or diagnostic commands.
- `[log]`: Verified by inspecting recorded workspace state or action logs.
- `[inferred]`: Logically deduced from code relationships (with explicit reasoning).

---

## Documents Directory

| Document | Title | Description |
| :--- | :--- | :--- |
| **[BRIEFING.md](BRIEFING.md)** | **Architecture Briefing** | **Executive summary (< 2,500 words) containing core principles, cycle diagram, 15 essential facts, state/prompt table, tool index, coupling hotspots, and top known issues.** |
| **[01-repo-map.md](01-repo-map.md)** | Repository Map & Execution Topology | Directory tree, package responsibilities, container lifecycle, layer builds, mounts, host vs. container split, and full environment variable catalog. |
| **[02-runtime-loop.md](02-runtime-loop.md)** | Runtime Execution Loop | Step-by-step cycle execution, prompt assembly, tool retrieval, inner tool rounds, reflection scheduling, iteration vs. cycle semantics, pause/stop controls, and stop reasons. |
| **[03-tools.md](03-tools.md)** | Tool Subsystem & Creation Pipeline | Full tool inventory (core vs. body-specific, risk classes), the complete `create_tool` pipeline (critic review, unittests, schema check, versioning), and `run_shell` sandboxing. |
| **[04-state-and-persistence.md](04-state-and-persistence.md)** | State & Persistence Architecture | Complete census of files under `workspace/state/` and `workspace/logs/`, schemas, readers/writers, prompt injection status, growth limits, and lock files. |
| **[05-llm-and-models.md](05-llm-and-models.md)** | LLM Client & Multi-Model System | `LLMClient`, `BudgetedLLM`, daily token ledger, retries, output ceilings, provider and model registries, and the helper-model probing and delegation system. |
| **[06-plan-identity-conversation.md](06-plan-identity-conversation.md)** | Plan, Identity & Conversation | Plan store lifecycle, human input arbitration, persistent identity, name context resolution, background reflection, conversation manager, and TUI slash commands. |
| **[07-safety-and-limits.md](07-safety-and-limits.md)** | Safety, Boundaries & Limits | Protection of host and credentials, egress filtering, container privileges, path protections (`/opt/agent` and managed identity), enforced vs. unenforced limits, and prompt-injection attack surfaces. |
| **[08-events-catalog.md](08-events-catalog.md)** | Events Catalog | Exhaustive dictionary of all 101 structured event types logged to `workspace/logs/actions.jsonl`, including emitting source lines and payload schemas. |
| **[09-tests.md](09-tests.md)** | Test Suites & Verification | Test suites (157 harness tests + 11 eval tests), Docker test execution, coverage scope, known gaps, and complete eval isolation verification. |
| **[10-coupling-and-seams.md](10-coupling-and-seams.md)** | Coupling, Assumptions & Plugin Seams | All Linux container assumptions (paths, `/proc`, `/sys`, strings), package dependency matrix, candidate seams for Body and Plugins, difficulty ratings, and unplug impact analysis. |
| **[11-known-issues-and-unknowns.md](11-known-issues-and-unknowns.md)** | Known Issues, Bugs & Open Unknowns | Deprecated mechanisms, dead code, duplicate shims, root privilege mismatch, workspace clutter, and unanswered empirical questions. |
| **[prompts-verbatim.md](prompts-verbatim.md)** | Verbatim Prompts Catalog | Exact verbatim source text and file line numbers for `SYSTEM_PROMPT`, `STANDING_GOAL`, cycle prompts, identity prompts, conversation prompt, model picker, and tool critic. |
| **[system-map.json](system-map.json)** | Machine-Readable System Map | Machine-readable schema mapping modules, entry points, tools, events, state files, and environment variables. |

---

## Agent Visibility & Isolation Verification

As required by repository security rules:
- `[read] Dockerfile:29-32`: The container image copies only `agent/requirements.txt` and `agent/` into `/opt/agent/`. Neither `docs/` nor `eval/` are copied into the image.
- `[read] docker-compose.yml:15-19`: The agent service `self` mounts only `${SELF_WORKSPACE_DIR:-./workspace}` to `/home/entity`. The `docs/` directory is never mounted into the container.
- `[read] .dockerignore:1-7`: Excludes `.env`, `.git`, `workspace`, and `eval`.
- **Conclusion:** These architecture documents are entirely invisible and inaccessible to the agent during runtime.
