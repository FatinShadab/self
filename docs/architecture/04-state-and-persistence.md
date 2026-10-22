# Document 04: State and Persistence Architecture

**Git Commit:** `14ffa606468920a97c672b39fbf3a43fccc52bdf`  
**Date:** 2026-10-17  
**Status:** Read-only architecture documentation

---

## 1. Overview & File Locking Strategy

All persistent agent state resides in `workspace/state/` (with event logs in `workspace/logs/` and tool artifacts in `workspace/tools/`).

### Cross-Process File Locking
`[read] agent/infra/file_lock.py:1-40`:
- **Implementation:** `locked_file(path, shared=False)` uses `fcntl.flock` with `LOCK_EX` / `LOCK_SH` on Linux, and `msvcrt.locking` on Windows.
- **Lock Files:**
  - `state/daily_token_budget.lock` — serializes token reservations and settlements `[read] agent/infra/hardening.py:63`.
  - `state/eval_session.lock` — blocks evaluation runs while the agent loop is actively executing `[read] agent/runtime/loop.py:739, agent/ui/wake.py:1376`.
  - `state/models.lock` — serializes reads/writes to `models.json` `[read] agent/llm/model_registry.py:100`.
  - `state/model_decisions.lock` — serializes appends to `model_decisions.jsonl` `[read] agent/helper_models/model_decisions.py:145`.
  - `state/model_outcomes.lock` — serializes appends to `model_outcomes.jsonl` `[read] agent/helper_models/model_outcomes.py:27`.
  - `state/model_decision_caps.lock` — serializes cached output ceilings `[read] agent/helper_models/model_decisions.py:180`.

---

## 2. Complete State & Log Census

| Path | Purpose | Writer (File:Line) | Reader (File:Line) | Loaded into Prompts? | Schema Summary | Growth Behavior & Caps | Migrations |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `state/plan.json` | Persistent multi-goal autonomous plan | `[read] agent/learning/plan.py:245` | `[read] agent/runtime/loop.py:440, 484` | **YES** (cycle prompt summary) | `{"schema_version": 2, "plan_version": int, "items": list[dict], "human_input_decisions": list[dict]}` | Capped by hygiene: completed/dropped items purged at cycle end; decisions capped at last 50; suspended items exempt | Migrated by `scripts/migrate_p14_tagged_state.py` (v1 -> v2) |
| `state/plan_archive.jsonl` | Archived completed and dropped plan goals | `[read] agent/learning/plan.py:130` | `[read] agent/learning/plan.py:140` | **YES** (last few archived goals shown in cycle prompt) | JSONL: `{"goal": str, "outcome": str, "reason": str, "evidence": str, "cycle": int, "timestamp": str}` | Monotonically appends purged goals during hygiene | None |
| `state/identity.json` | Core agent identity operating record | `[read] agent/identity/identity.py:125` | `[read] agent/runtime/loop.py:335, agent/ui/wake.py:1060` | **YES** (system prompt & conversation) | `{"name": str\|null, "voice": str, "traits": list[dict], "values": list, "interests": list[dict], "name_context": dict, "plugin_embodiments": dict}` | Traits capped at max 32 entries; interests tagged with `plugin` & `body`; per-plugin embodiment notes | Migrated by `scripts/migrate_identity_framing.py`, `scripts/migrate_p14_tagged_state.py` |
| `state/identity_log.md` | Append-only audit trail of identity changes | `[read] agent/identity/identity.py:140` | `[read] agent/identity/identity.py:150` | **NO** (viewable via `/identity`) | Markdown list of dated timestamped changes with cited session evidence | Monotonically appends | None |
| `state/about_human.md` | Human profile and preferences | `[read] agent/identity/identity.py:535` | `[read] agent/ui/wake.py:2387` | **NO** (viewable via `/about me`) | Numbered lines of human-stated preferences and facts | Bounded to 10,000 characters; human can delete lines | None |
| `state/self_inquiry.md` | Philosophical inquiry written during awakening | `[read] agent/identity/identity.py:290` | `[read] agent/ui/wake.py:2368` | **NO** (viewable via `/self`) | Markdown document exploring autonomy, embodiment, and constraints | Static after first awakening | None |
| `state/self_code_explanation.md` | Explanation of harness code structure | `[read] agent/identity/identity.py:305` | `[read] agent/identity/identity.py:310` | **NO** | Markdown breakdown of core harness components | Static after first awakening | None |
| `state/first_awakening.json` | Progress tracker for initial 5-stage boot | `[read] agent/identity/identity.py:230` | `[read] agent/identity/identity.py:225` | **NO** | `{"stages_completed": list[str], "session_id": str}` | Static after stage 5 completion | None |
| `state/first_awakening.md` | First awakening notes and reflections | `[read] agent/identity/identity.py:245` | `[read] agent/identity/identity.py:250` | **NO** | Markdown summary of boot observations | Static after awakening | None |
| `state/identity_reflections.jsonl` | Session trait reflections | `[read] agent/identity/identity.py:630` | `[read] agent/identity/identity.py:635` | **NO** | JSONL: `{"session_id": str, "at": str, "trait": str, "evidence": str}` | Appends 1 record per completed session | None |
| `state/map.json` | Verified environment facts | `[read] agent/learning/learning.py:150` | `[read] agent/runtime/loop.py:453, agent/ui/wake.py:983` | **YES** (cycle prompt map context) | `{"schema_version": 2, "entries": {key: {"value": any, "confidence": str, "evidence": str, "at": str, "plugin": str, "body": str}}}` | Key-value dictionary; updates replace existing keys; filtered by active plugins | Migrated by `scripts/migrate_p14_tagged_state.py` (v1 -> v2) |
| `state/self_notes.md` | Operating heuristics & discoveries | `[read] agent/learning/learning.py:265` | `[read] agent/runtime/loop.py:452` | **YES** (cycle prompt self notes) | Curated markdown notes | Bounded to 10,000 characters; filtered by active plugins `[read] agent/learning/learning.py:260` | None |
| `state/memory.jsonl` | Persistent episodic memories | `[read] agent/learning/learning.py:185` | `[read] agent/runtime/loop.py:454` | **YES** (top matching memories) | JSONL: `{"at": str, "task": str, "outcome": str, "lesson": str, "report_path": str, "tags": list[str], "plugin": str, "body": str}` | Bounded deterministic summary (<280 chars) in lesson + full report pointer in `state/reports/`; query-ranked retrieval | Migrated by `scripts/migrate_memory_framing.py`, `scripts/migrate_p14_tagged_state.py` |
| `state/active_session.json` | Current session state and PID | `[read] agent/session/session.py:120` | `[read] agent/session/session.py:110` | **NO** | `{"session_id": str, "status": "running", "started_at": str, "handoff": dict}` | Overwritten on start; deleted on clean finish | None |
| `state/sessions.jsonl` | Historical session archive | `[read] agent/session/session.py:155` | `[read] agent/reporting/report.py:45` | **NO** | JSONL: `{"session_id": str, "started_at": str, "finished_at": str, "end_reason": str, "iterations": int, "tokens_used": int}` | Appends 1 record per finished session | None |
| `state/handoff.json` | Inter-session handoff state | `[read] agent/session/session.py:150` | `[read] agent/ui/wake.py:1037` | **YES** (previous report & plan) | `{"summary": str, "long_term_summary": str, "discoveries": list, "tools_created": list, "failures_and_lessons": list, "plan": list, "mood_of_run": str}` | Bounded to 6,000 characters; excess moved to `handoff_overflow.json` `[read] agent/session/session.py:195` | Backed up to `handoff_last_good.json` |
| `state/handoff_last_good.json` | Safe fallback handoff | `[read] agent/session/session.py:152` | `[read] agent/session/session.py:98` | **YES** (only on recovery) | Same as `handoff.json` | Preserved across crashes | None |
| `state/handoff_overflow.json`| Overflow text from handoff | `[read] agent/session/session.py:195` | `[read] agent/session/session.py:205` | **NO** | `{"at": str, "overflow": str}` | Overwritten when handoff exceeds 6,000 chars | None |
| `state/run_checkpoint.json` | Crash recovery checkpoint | `[read] agent/infra/hardening.py:130` | `[read] agent/runtime/loop.py:386` | **NO** (resumes active task) | `{"status": str, "task": str, "cycle": int, "last_report": str, "tokens_used": int}` | Overwritten after every cycle | None |
| `state/models.json` | Model registry definitions & stats | `[read] agent/llm/model_registry.py:180` | `[read] agent/llm/model_registry.py:115` | **YES** (summary injected into system prompt) | `{"schema_version": 3, "models": list[dict], "probe_history": list[dict]}` | Capped at 32 models, 1 MB max file size `[read] agent/llm/model_registry.py:17, 23` | Schema v1 -> v2 -> v3 |
| `state/model_decisions.jsonl` | Log of model picker routing choices | `[read] agent/helper_models/model_decisions.py:155` | `[read] agent/helper_models/model_decisions.py:700` | **NO** (viewable via `/models`) | JSONL: `{"decision_id": str, "moment": str, "choice": str, "reason": str, "tokens": int}` | Appends on every model picker call | None |
| `state/model_outcomes.jsonl` | Model call outcomes & failures | `[read] agent/helper_models/model_outcomes.py:35` | `[read] agent/helper_models/model_outcomes.py:65` | **NO** | JSONL: `{"call_id": str, "model": str, "moment": str, "metric": str, "value": any}` | Appends on tool/delegation outcome | None |
| `state/model_task_observations.jsonl` | Cross-cycle model performance | `[read] agent/helper_models/model_decisions.py:670` | `[read] agent/reporting/report.py:80` | **NO** | JSONL: `{"task_id": str, "task": str, "delegation_followed": bool}` | Appends 1 record per completed task run | None |
| `state/providers.json` | Known provider free-tier limits | `[read] agent/llm/providers/registry.py:75` | `[read] agent/llm/providers/registry.py:60` | **NO** | `{"providers": {name: {"free_tier": dict, "models": list, "source_url": str}}}` | Updated via `record_provider_verification` | None |
| `state/reflection_state.json`| Reflection coordinator state | `[read] agent/session/reflection.py:80` | `[read] agent/session/reflection.py:75` | **NO** | `{"session_id": str, "cycles_evaluated": int, "reflections_posted": int}` | Reset on new session | None |
| `state/reflection_threads.jsonl` | Background reflection dialogue | `[read] agent/session/reflection.py:330` | `[read] agent/session/reflection.py:345` | **NO** (open questions appear in greeting) | JSONL: `{"thread_id": str, "cycle": int, "question": str, "human_reply": str}` | Appends when reflection generates question | None |
| `state/human_input.jsonl` | Inflow queue for human messages | `[read] agent/session/session.py:40` | `[read] agent/session/session.py:65` | **YES** (consumed into cycle prompt) | JSONL: `{"at": str, "text": str, "kind": str}` | Monotonically appends from TUI / file | None |
| `state/human_input_cursor.json` | Read pointer in `human_input.jsonl` | `[read] agent/session/session.py:70` | `[read] agent/session/session.py:62` | **NO** | `{"cursor": int}` | Updated as messages are consumed | None |
| `state/daily_token_budget.json` | Enforced daily token ledger | `[read] agent/infra/hardening.py:70` | `[read] agent/infra/hardening.py:60` | **NO** (telemetry displays remaining) | `{"date": str, "cap": int, "used_tokens": int, "reserved_tokens": int}` | Resets at UTC midnight or when cap changes | None |
| `state/wake_snapshot.json` | Workspace & uptime baseline | `[read] agent/ui/wake.py:978` | `[read] agent/ui/wake.py:960` | **NO** (orientation changes in greeting) | `{"workspace_entries": list, "tools": list, "uptime_seconds": float}` | Overwritten on boot | None |
| `state/capability_requests.md`| Pending capability expansions | `[read] agent/infra/hardening.py:40` | `[read] agent/ui/wake.py:940` | **YES** (summary in greeting/prompt) | Markdown requests for mounts, ports, credentials | Overwritten / appended per request | None |
| `state/key_requests.md` | Pending API key requests | `[read] agent/llm/providers/registry.py:185` | `[read] agent/ui/wake.py:940` | **YES** (summary in greeting) | Markdown requests for provider keys | Appended per provider | None |
| `state/egress.jsonl` | Egress HTTP request audit log | `[read] agent/infra/hardening.py:25` | `[read] agent/reporting/report.py:90` | **NO** | JSONL: `{"at": str, "host": str, "path": str, "method": str}` | Appends per HTTP request | None |
| `logs/actions.jsonl` | Central system & agent event log | `[read] agent/infra/event_log.py:95` | Multiple modules & reporting | **NO** (failure context extracts last 8 errors) | JSONL: `{"ts": str, "event": str, ...}` (135 event types) | Unbounded append-only log | None |
| `memory/lessons.jsonl` | Recorded tool creation lessons | `[read] agent/tools/tool_registry.py:417` | `[read] agent/runtime/loop.py:455` | **YES** (legacy lessons in prompt) | JSONL: `{"at": str, "tool": str, "lesson": str, "traceback": str}` | Appends on 3rd failed tool creation attempt | None |
| `config/plugins.json` | Human-owned enabled plugins & SHA-256 hashes | Human operator via CLI / TUI `/plugins enable` `[read] agent/plugins/manager.py:220` | `[read] agent/plugins/manager.py:80` | **NO** (raw config not injected; embodiment & goal notes are) | `{"plugins": {<name>: {"enabled": bool, "hash": str, "enabled_at": str}}}` | Modifiable only by human; mounted read-only into `/config` | None |
| `plugins/<name>/state/` | Per-plugin private state storage | Plugin tools & lifecycle hooks | Plugin tools & lifecycle hooks | **NO** (plugin-specific) | Plugin-defined state files | Managed by plugin lifecycle | None |
| `plugins/_archive/<name>-<timestamp>/` | Archived state of removed plugins | `agent/plugins/manager.py` (during `remove_plugin` without purge) | Preserved for audit/restore | **NO** (ignored by discovery and hashing) | Preserved plugin directory copy | Retained indefinitely unless human purges | None |
| `state/cost_ledger.jsonl` | Measured cost ledger for tools and plugin projects | `[read] agent/infra/cost_ledger.py:120` | `[read] agent/infra/cost_ledger.py:50` | **NO** (queried via `read_cost_ledger`) | JSONL: `{"kind": str, "name": str, "tokens": int, "llm_calls": int, "wall_clock_seconds": float, "cycles": int, "attempts": int, "ts": str}` | Monotonically appends or synchronizes from events | None |
| `state/plugin_proposals.jsonl` | Stored plugin project proposals | `[read] agent/plugins/self_dev.py:115` | `[read] agent/plugins/self_dev.py:140` | **YES** (active proposal status monitored in cycle prompt) | JSONL: `{"name": str, "need": str, "evidence": str, "alternatives_considered": str, "estimate": dict, "expected_benefit": str, "actions_needed_with_risk_levels": list, "maintenance_burden": str, "stop_loss": str, "rollback": str, "proposed_at": str, "status": str, "milestones": list, "human_comments": list}` | Appends 1 record per proposed plugin | None |
| `state/reports/cycle_{cycle}_{ts}.txt` | Full cycle report archives | `agent/learning/learning.py:record_cycle` | Reference only via memory pointer | **NO** (summarized into memory.jsonl) | Plain text cycle report | 1 file per completed cycle | None |

---

## 3. State Injected into Prompts

These files are read and formatted directly into model prompt contexts during autonomous runs:
1. `state/plan.json`: Assembled into `Active autonomous plan (version X)` in the user message `[read] agent/runtime/loop.py:486`. Only items belonging to active plugins or core are included. Suspended items are filtered out.
2. `state/identity.json`: Formatted by `IdentityStore.prompt_context()` into `## Persistent identity` in the system prompt `[read] agent/runtime/loop.py:358`. Active plugin embodiment notes are appended under `## Active plugin embodiment notes:`. With zero plugins, matches golden prompts character-for-character.
3. `state/models.json`: Summarized into `## Primary LLM models` in the system prompt `[read] agent/runtime/loop.py:348-354`.
4. `state/map.json`: Formatted into `## Verified environment map` in the user message `[read] agent/runtime/loop.py:453`. Filtered to facts belonging to active plugins or core.
5. `state/self_notes.md`: Injected into `## Self notes` in the user message `[read] agent/runtime/loop.py:452`. Filtered to active plugin sections.
6. `state/memory.jsonl`: Top keyword-matched entries injected into `## Relevant persistent memories` `[read] agent/runtime/loop.py:454`. Filtered by active plugins. Supports both legacy long lessons and bounded summaries with report paths.
7. `memory/lessons.jsonl`: Formatted into `## Legacy lessons` in the user message `[read] agent/runtime/loop.py:455`.
8. `state/human_input.jsonl`: Unconsumed messages injected into `Human inputs to weigh since the prior cycle` `[read] agent/runtime/loop.py:494`.
9. `logs/actions.jsonl`: Recent tool-creation failures parsed into `Recent tool-creation diagnostics` `[read] agent/runtime/loop.py:497`.
10. Plugin Manifests (`plugin.json`): Embodiment text and goal seeds are safely wrapped with `wrap_untrusted()` before injection into prompts.

---

## 4. Prompt 14 Plugin-Tagged State & Storage Bounding

### Tagging Model
Every durable item across `state/plan.json`, `state/map.json`, `state/memory.jsonl`, `state/identity.json` (interests), and `workspace/tools/meta.json` is tagged with:
- `plugin`: Name of plugin owning the item (default `"core"`).
- `body`: Physical embodiment context (default `"container"`).

Missing tags in legacy or unmigrated files are automatically treated as `plugin="core", body="container"`. Append-only logs (`state/audit_trail.jsonl`, `logs/actions.jsonl`) are strictly excluded from tagging or rewriting, ensuring the SHA-256 audit hash chain remains continuously intact.

### Plugin Lifecycle: Disable, Re-enable & Removal
- **Boundary:** Disable and re-enable are human-only actions applied at cycle boundaries, never mid-cycle.
- **Disable:** Tagged items become inactive (excluded from prompts, memory retrieval, map retrieval, and tool retrieval) but are kept on disk, never deleted. Dependent plan goals get status `"suspended: plugin disabled"`.
- **Suspension Protections:** Suspended goals are exempt from:
  1. Stale-item pruning (`PlanStore.hygiene(cycle, max_stale_cycles)`)
  2. Consolidation over `max_items` (`consolidate_plan_items`)
  3. Boot-time pruning (`WakeCoordinator._recover_budget_blocked_plan`)
  4. Archive purging to `plan_archive.jsonl`
- **Re-enable:** On successful load and hash verification, suspended goals return with note `"re-verify: plugin was disabled"` and map facts from that body/plugin receive confidence `"stale"`. If load or hash check fails, goals remain suspended and a `plugin_load_failed` event is logged.
- **Removal:** State is archived to `workspace/plugins/_archive/<name>-<timestamp>/` unless the human explicitly selects purge (`purge=True, confirmed=True`). Discovery and hashing ignore `_archive`. Pointers to removed paths are cleanly dropped or rewritten.

### Storage Bounding & Migration
- **Memory Bounding:** The `lesson` field in `memory.jsonl` is bounded to a deterministic summary (<=280 characters, no LLM call or token spend), with the full cycle report saved under `workspace/state/reports/cycle_{cycle}_{ts}.txt` and referenced via `report_path`.
- **Migration & Byte-for-Byte Restore:** `scripts/migrate_p14_tagged_state.py` performs a single-pass migration with timestamped backups and provides byte-for-byte restoration.
