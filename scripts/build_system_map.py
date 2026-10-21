#!/usr/bin/env python3
"""build_system_map.py - Deterministically extract and output system-map.json."""

import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

def get_tools():
    # Base tools and create_tool
    base_tools_file = REPO_ROOT / "agent" / "tools" / "base_tools.py"
    tool_reg_file = REPO_ROOT / "agent" / "tools" / "tool_registry.py"

    tools = [
        {
            "name": "list_models",
            "module": "agent/tools/base_tools.py",
            "risk_class": "reads",
            "core_vs_body": "core",
            "description": "List the fixed base model and configured helper models with recorded assessments and measured call stats."
        },
        {
            "name": "record_model_assessment",
            "module": "agent/tools/base_tools.py",
            "risk_class": "writes",
            "core_vs_body": "core",
            "description": "Record evidence-backed assessment and ratings of a configured helper model."
        },
        {
            "name": "probe_model",
            "module": "agent/tools/base_tools.py",
            "risk_class": "executes / network",
            "core_vs_body": "core",
            "description": "Run 4 bounded capability probes against a configured helper model."
        },
        {
            "name": "research_model",
            "module": "agent/tools/base_tools.py",
            "risk_class": "network",
            "core_vs_body": "core",
            "description": "Fetch a configured helper model's official documentation page and extract facts."
        },
        {
            "name": "ask_model",
            "module": "agent/tools/base_tools.py",
            "risk_class": "network",
            "core_vs_body": "core",
            "description": "Delegate a bounded plain-text sub-task to an enabled helper model."
        },
        {
            "name": "record_delegation_outcome",
            "module": "agent/tools/base_tools.py",
            "risk_class": "writes",
            "core_vs_body": "core",
            "description": "Record human/agent judgment on whether an ask_model call helped."
        },
        {
            "name": "run_shell",
            "module": "agent/tools/base_tools.py",
            "risk_class": "executes",
            "core_vs_body": "body-specific (Linux container)",
            "description": "Run an unrestricted Bash command inside the container as root with timeout and output cap."
        },
        {
            "name": "read_file",
            "module": "agent/tools/base_tools.py",
            "risk_class": "reads",
            "core_vs_body": "body-specific (container filesystem)",
            "description": "Read a UTF-8 text file from the container with character cap."
        },
        {
            "name": "write_file",
            "module": "agent/tools/base_tools.py",
            "risk_class": "writes",
            "core_vs_body": "body-specific (container filesystem)",
            "description": "Write or append UTF-8 text in workspace, rejecting protected /opt/agent harness and managed identity paths."
        },
        {
            "name": "list_dir",
            "module": "agent/tools/base_tools.py",
            "risk_class": "reads",
            "core_vs_body": "body-specific (container filesystem)",
            "description": "List directory entries in the container with count cap."
        },
        {
            "name": "http_get",
            "module": "agent/tools/base_tools.py",
            "risk_class": "network",
            "core_vs_body": "body-specific (network interface)",
            "description": "Make an HTTP or HTTPS GET request with host/path egress logging and query redaction."
        },
        {
            "name": "update_environment_map",
            "module": "agent/tools/base_tools.py",
            "risk_class": "writes",
            "core_vs_body": "core",
            "description": "Record verified environment observations with confidence and evidence into state/map.json."
        },
        {
            "name": "read_plan",
            "module": "agent/tools/base_tools.py",
            "risk_class": "reads",
            "core_vs_body": "core",
            "description": "Read the current persistent plan from state/plan.json."
        },
        {
            "name": "update_plan",
            "module": "agent/tools/base_tools.py",
            "risk_class": "writes",
            "core_vs_body": "core",
            "description": "Modify the persistent plan (add, edit, drop, mark_done, reorder, unchanged, decide_human_input) with required reason."
        },
        {
            "name": "research_provider",
            "module": "agent/tools/base_tools.py",
            "risk_class": "network",
            "core_vs_body": "core",
            "description": "Fetch a configured provider's official documentation without signing up or creating accounts."
        },
        {
            "name": "record_provider_verification",
            "module": "agent/tools/base_tools.py",
            "risk_class": "writes",
            "core_vs_body": "core",
            "description": "Store verified free-tier limits, models, and strengths from provider documentation into state/providers.json."
        },
        {
            "name": "request_provider_key",
            "module": "agent/tools/base_tools.py",
            "risk_class": "writes",
            "core_vs_body": "core",
            "description": "Write a human-only API key request to state/key_requests.md."
        },
        {
            "name": "ask_brain",
            "module": "agent/tools/base_tools.py",
            "risk_class": "network",
            "core_vs_body": "core",
            "description": "Send a bounded plain-text query through a supplementary provider via the brain router."
        },
        {
            "name": "benchmark_providers",
            "module": "agent/tools/base_tools.py",
            "risk_class": "network",
            "core_vs_body": "core",
            "description": "Run the built-in eval set against configured providers to score latency and quality."
        },
        {
            "name": "probe_local_ollama",
            "module": "agent/tools/base_tools.py",
            "risk_class": "network / reads",
            "core_vs_body": "body-specific (local container port)",
            "description": "Check if a local Ollama daemon is running inside the container."
        },
        {
            "name": "request_capability",
            "module": "agent/tools/base_tools.py",
            "risk_class": "writes",
            "core_vs_body": "core",
            "description": "Write a human-approved request for capability expansion (host mount, port, credential, etc.)."
        },
        {
            "name": "propose_core_patch",
            "module": "agent/tools/base_tools.py",
            "risk_class": "writes",
            "core_vs_body": "core",
            "description": "Save a unified diff and reasoning under state/proposed_patches/ for human review."
        },
        {
            "name": "create_tool",
            "module": "agent/tools/tool_registry.py",
            "risk_class": "executes / writes / network",
            "core_vs_body": "core",
            "description": "Create or update a reusable Python tool with critic review, isolated unittest execution, and schema check."
        }
    ]
    return tools

def get_events():
    events_map = {}
    for p in sorted(REPO_ROOT.glob("agent/**/*.py")):
        rel = p.relative_to(REPO_ROOT).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "log":
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        ev = node.args[0].value
                        kws = [kw.arg for kw in node.keywords if kw.arg is not None]
                        events_map.setdefault(ev, []).append({
                            "emitter": f"{rel}:{node.lineno}",
                            "fields": kws
                        })
    results = []
    for ev in sorted(events_map):
        emitters = [item["emitter"] for item in events_map[ev]]
        # collect union of fields
        all_fields = sorted(list({f for item in events_map[ev] for f in item["fields"]}))
        results.append({
            "name": ev,
            "emitters": emitters,
            "fields": all_fields
        })
    return results

def get_env_vars():
    return [
        {"name": "ANTHROPIC_API_KEY", "default": "", "where_read": "agent/llm/llm.py:193", "meaning": "Anthropic API key for primary model or critic fallback."},
        {"name": "ANTHROPIC_API_KEYS", "default": "", "where_read": "agent/llm/llm.py:193", "meaning": "List of Anthropic API keys for rotation on rate limits."},
        {"name": "ANTHROPIC_BASE_URL", "default": "https://api.anthropic.com", "where_read": "agent/llm/llm.py:203", "meaning": "Base URL for Anthropic API endpoint."},
        {"name": "ANTHROPIC_MODEL", "default": "gpt-oss:120b-cloud", "where_read": "agent/llm/llm.py:214", "meaning": "Primary Anthropic model identifier."},
        {"name": "HOST_AGENT_SOURCE_HASH", "default": "", "where_read": "agent/ui/version_check.py:46", "meaning": "Host-computed SHA256 of agent harness code to detect stale Docker images."},
        {"name": "LLM_AVAILABLE_MODELS", "default": "", "where_read": "agent/llm/llm.py:216", "meaning": "Comma-separated list of helper models configured under the same API key."},
        {"name": "OLLAMA_API_KEY", "default": "", "where_read": "agent/llm/llm.py:192", "meaning": "Primary Ollama Cloud API key."},
        {"name": "OLLAMA_API_KEYS", "default": "", "where_read": "agent/llm/llm.py:192", "meaning": "List of Ollama Cloud API keys for rotation on rate limits."},
        {"name": "OLLAMA_BASE_URL", "default": "https://ollama.com", "where_read": "agent/llm/llm.py:196", "meaning": "Base URL for Ollama Cloud API endpoint."},
        {"name": "OLLAMA_LOCAL_BASE_URL", "default": "http://127.0.0.1:11434", "where_read": "agent/llm/providers/adapters.py:179", "meaning": "Local Ollama daemon endpoint within the container."},
        {"name": "OLLAMA_MODEL", "default": "gpt-oss:120b-cloud", "where_read": "agent/llm/llm.py:213", "meaning": "Primary Ollama Cloud model identifier."},
        {"name": "SELF_CONVERSATION_MAX_TOKENS", "default": "0", "where_read": "agent/session/conversation.py:33", "meaning": "Output token ceiling for conversation threads (0 uses model ceiling)."},
        {"name": "SELF_CRITIC_MODEL", "default": "", "where_read": "agent/tools/tool_registry.py:270", "meaning": "Model override for create_tool critic reviews when helper models are disabled."},
        {"name": "SELF_CRITIC_SHADOW_TESTS", "default": "true", "where_read": "agent/tools/tool_registry.py:348", "meaning": "If true, run candidate tool unittests even if critic rejected, to collect objective test telemetry."},
        {"name": "SELF_DEFAULT_OUTPUT_CEILING", "default": "32768", "where_read": "agent/llm/model_registry.py:293", "meaning": "Assumed maximum output tokens when model registry ceiling is unconfigured."},
        {"name": "SELF_EXPECTED_CODE_HASH", "default": "", "where_read": "agent/ui/version_check.py:46", "meaning": "Expected code hash override for version checking."},
        {"name": "SELF_EXPECTED_OUTPUT_TOKENS", "default": "1024", "where_read": "agent/llm/llm.py:73", "meaning": "Output token estimate used for initial budget reservation."},
        {"name": "SELF_HELPER_MODELS", "default": "on", "where_read": "agent/runtime/loop.py:186", "meaning": "Controls helper model system ('on' enables probes, decisions, and delegations; other values disable)."},
        {"name": "SELF_MAX_CONVERSATION_WORKERS", "default": "2", "where_read": "agent/session/conversation.py:32", "meaning": "Maximum background worker threads for independent conversation queries."},
        {"name": "SELF_MAX_ITERATIONS", "default": "0", "where_read": "agent/runtime/loop.py:696", "meaning": "Maximum cycles per autonomous run (0 = unlimited)."},
        {"name": "SELF_MAX_OUTPUT_CHARS", "default": "20000", "where_read": "agent/tools/base_tools.py:334", "meaning": "Maximum characters returned by file reading and tool output."},
        {"name": "SELF_MAX_PROVIDER_CALLS", "default": "0", "where_read": "agent/infra/provider_calls.py:14", "meaning": "Hard ceiling on provider calls per process (0 = unlimited; used in A/B eval)."},
        {"name": "SELF_MAX_TOKENS_PER_DAY", "default": "200000", "where_read": "agent/infra/hardening.py:55", "meaning": "Daily token ledger spending limit across all sessions."},
        {"name": "SELF_MAX_WALL_CLOCK_SECONDS", "default": "0", "where_read": "agent/runtime/loop.py:698", "meaning": "Maximum wall-clock seconds for an autonomous run (0 = unlimited)."},
        {"name": "SELF_MODEL_FAILURE_COOLDOWN_SECONDS", "default": "600", "where_read": "agent/helper_models/model_decisions.py:77", "meaning": "Cooldown period before retrying a helper model that failed."},
        {"name": "SELF_OUTPUT_CAP_<MODEL>", "default": "", "where_read": "agent/llm/model_registry.py:275", "meaning": "Per-model dynamic output cap override (e.g. SELF_OUTPUT_CAP_GPT_OSS_120B_CLOUD)."},
        {"name": "SELF_PROBES_PER_MODEL_PER_SESSION", "default": "2", "where_read": "agent/llm/model_registry.py:99", "meaning": "Maximum probe runs per helper model in one session."},
        {"name": "SELF_PROBE_COOLDOWN_SECONDS", "default": "3600", "where_read": "agent/llm/model_registry.py:97", "meaning": "Cooldown period before re-probing an already probed helper model."},
        {"name": "SELF_REFLECTION_ENABLED", "default": "1", "where_read": "agent/ui/wake.py:733", "meaning": "Enable or disable background session reflections."},
        {"name": "SELF_REFLECTION_MAX_PER_SESSION", "default": "3", "where_read": "agent/ui/wake.py:734", "meaning": "Maximum background reflection triggers per session."},
        {"name": "SELF_REFLECTION_MAX_TOKENS", "default": "384", "where_read": "agent/ui/wake.py:736", "meaning": "Maximum output tokens for reflection LLM calls."},
        {"name": "SELF_REFLECTION_MIN_CYCLES", "default": "3", "where_read": "agent/ui/wake.py:735", "meaning": "Minimum cycles before triggering background reflection."},
        {"name": "SELF_REPORT_AB_FILE", "default": "", "where_read": "agent/reporting/report.py:212", "meaning": "Path to A/B run results file for summary reports."},
        {"name": "SELF_REPORT_CALIBRATION_FILE", "default": "", "where_read": "agent/reporting/report.py:211", "meaning": "Path to calibration data file for reporting."},
        {"name": "SELF_TOKEN_BUDGET", "default": "0", "where_read": "agent/ui/wake.py:702", "meaning": "Deprecated run token budget (daily ledger is the active mechanism)."},
        {"name": "SELF_TOP_K_TOOLS", "default": "5", "where_read": "agent/runtime/loop.py:692", "meaning": "Number of custom tools retrieved by keyword search per step."},
        {"name": "SELF_TUI_TYPING_DELAY", "default": "0.01", "where_read": "agent/ui/wake.py:1631", "meaning": "Typing delay in seconds for terminal UI typewriter animation."},
        {"name": "SELF_VOICE_ENABLED", "default": "false", "where_read": "agent/ui/voice.py:19", "meaning": "Enable or disable speech synthesis / voice output."},
        {"name": "SELF_WORKSPACE_DIR", "default": "./workspace", "where_read": "docker-compose.yml:17", "meaning": "Host directory mounted to /home/entity inside container."},
        {"name": "SELF_CONFIG_DIR", "default": "./config", "where_read": "docker-compose.yml:22", "meaning": "Host configuration directory mounted read-only for human plugin control."},
        {"name": "EVAL_WORKSPACE_DIR", "default": "./workspace", "where_read": "docker-compose.yml:34", "meaning": "Host directory mounted as read-only workspace for eval container."},
        {"name": "HTTP_PROXY", "default": "", "where_read": "docker-compose.yml:78", "meaning": "HTTP forward proxy for container egress filtering under hardened profile."},
        {"name": "HTTPS_PROXY", "default": "", "where_read": "docker-compose.yml:79", "meaning": "HTTPS forward proxy for container egress filtering under hardened profile."},
        {"name": "NO_PROXY", "default": "localhost,127.0.0.1", "where_read": "docker-compose.yml:82", "meaning": "Bypass list for proxy connections under hardened profile."}
    ]

def get_state_files():
    return [
        {"path": "workspace/state/active_session.json", "purpose": "Live session status, PID, start time, and handoff pointer", "writer": "agent/session/session.py", "reader": "agent/session/session.py"},
        {"path": "workspace/state/sessions.jsonl", "purpose": "Historical log of completed sessions with token usage and end reasons", "writer": "agent/session/session.py", "reader": "agent/session/session.py"},
        {"path": "workspace/state/handoff.json", "purpose": "Durable inter-session handoff: goals, achievements, plan, discoveries", "writer": "agent/session/session.py", "reader": "agent/session/session.py, agent/ui/wake.py"},
        {"path": "workspace/state/handoff_last_good.json", "purpose": "Backup of previous valid handoff used if handoff.json is corrupt", "writer": "agent/session/session.py", "reader": "agent/session/session.py"},
        {"path": "workspace/state/handoff_overflow.json", "purpose": "Archived excess text when handoff exceeds 6,000-character bound", "writer": "agent/session/session.py", "reader": "agent/session/session.py"},
        {"path": "workspace/state/run_checkpoint.json", "purpose": "Cycle-by-cycle crash recovery checkpoint (task, cycle, last_report)", "writer": "agent/infra/hardening.py", "reader": "agent/infra/hardening.py, agent/runtime/loop.py"},
        {"path": "workspace/state/plan.json", "purpose": "Persistent plan store: goals, priority, status, evidence, human decisions", "writer": "agent/learning/plan.py", "reader": "agent/learning/plan.py, agent/runtime/loop.py, agent/ui/wake.py"},
        {"path": "workspace/state/plan_archive.jsonl", "purpose": "Archived completed and dropped plan goals with outcome, reason, evidence, and cycle", "writer": "agent/learning/plan.py", "reader": "agent/learning/plan.py"},
        {"path": "workspace/state/identity.json", "purpose": "Persistent identity: name, voice, traits, values, interests, style cues", "writer": "agent/identity/identity.py", "reader": "agent/identity/identity.py, agent/runtime/loop.py, agent/ui/wake.py"},
        {"path": "workspace/state/identity_log.md", "purpose": "Append-only audit log of identity updates and evidence citations", "writer": "agent/identity/identity.py", "reader": "agent/identity/identity.py"},
        {"path": "workspace/state/about_human.md", "purpose": "Persistent human profile: volunteered preferences and facts about human", "writer": "agent/identity/identity.py", "reader": "agent/identity/identity.py"},
        {"path": "workspace/state/self_inquiry.md", "purpose": "First-awakening philosophical inquiry and operating principles", "writer": "agent/identity/identity.py", "reader": "agent/identity/identity.py, agent/ui/wake.py"},
        {"path": "workspace/state/self_code_explanation.md", "purpose": "First-awakening explanation of core harness code structure", "writer": "agent/identity/identity.py", "reader": "agent/identity/identity.py"},
        {"path": "workspace/state/first_awakening.json", "purpose": "State tracking for initial 5-stage boot sequence", "writer": "agent/identity/identity.py", "reader": "agent/identity/identity.py"},
        {"path": "workspace/state/first_awakening.md", "purpose": "Detailed notes generated during first awakening", "writer": "agent/identity/identity.py", "reader": "agent/identity/identity.py"},
        {"path": "workspace/state/identity_reflections.jsonl", "purpose": "Session-by-session trait reflections citing completed session evidence", "writer": "agent/identity/identity.py", "reader": "agent/identity/identity.py"},
        {"path": "workspace/state/map.json", "purpose": "Verified environment observations (OS, CPU, memory, tools, network)", "writer": "agent/learning/learning.py", "reader": "agent/learning/learning.py, agent/runtime/loop.py"},
        {"path": "workspace/state/self_notes.md", "purpose": "Curated working notes and operational patterns loaded into cycle prompt", "writer": "agent/learning/learning.py", "reader": "agent/learning/learning.py, agent/runtime/loop.py"},
        {"path": "workspace/state/memory.jsonl", "purpose": "Persistent episodic memories with tags, query keywords, and outcomes", "writer": "agent/learning/learning.py", "reader": "agent/learning/learning.py"},
        {"path": "workspace/state/models.json", "purpose": "Model registry: configured primary/helper models, stats, ratings, probes", "writer": "agent/llm/model_registry.py", "reader": "agent/llm/model_registry.py, agent/runtime/loop.py"},
        {"path": "workspace/state/model_decisions.jsonl", "purpose": "Log of model routing decisions (moment, context, model chosen, reason)", "writer": "agent/helper_models/model_decisions.py", "reader": "agent/helper_models/model_decisions.py"},
        {"path": "workspace/state/model_outcomes.jsonl", "purpose": "Outcomes of model calls (success, failure, truncation, parse errors)", "writer": "agent/helper_models/model_outcomes.py", "reader": "agent/helper_models/model_outcomes.py"},
        {"path": "workspace/state/model_task_observations.jsonl", "purpose": "Task-level observations of model performance across cycles", "writer": "agent/helper_models/model_decisions.py", "reader": "agent/helper_models/model_decisions.py"},
        {"path": "workspace/state/providers.json", "purpose": "Provider registry: known model providers, free limits, verified docs", "writer": "agent/llm/providers/registry.py", "reader": "agent/llm/providers/registry.py"},
        {"path": "workspace/state/reflection_state.json", "purpose": "Background reflection manager state (session counters, last cycle)", "writer": "agent/session/reflection.py", "reader": "agent/session/reflection.py"},
        {"path": "workspace/state/reflection_threads.jsonl", "purpose": "Background reflection conversation threads and human replies", "writer": "agent/session/reflection.py", "reader": "agent/session/reflection.py"},
        {"path": "workspace/state/human_input.jsonl", "purpose": "Inbox queue of human inputs from TUI or file", "writer": "agent/session/session.py", "reader": "agent/session/session.py"},
        {"path": "workspace/state/human_input_cursor.json", "purpose": "Read cursor position in human_input.jsonl", "writer": "agent/session/session.py", "reader": "agent/session/session.py"},
        {"path": "workspace/state/daily_token_budget.json", "purpose": "Daily token ledger tracking tokens used and reserved vs daily cap", "writer": "agent/infra/hardening.py", "reader": "agent/infra/hardening.py, agent/llm/llm.py"},
        {"path": "workspace/state/wake_snapshot.json", "purpose": "Snapshot of workspace entries, tools, and credentials to detect changes on wake", "writer": "agent/ui/wake.py", "reader": "agent/ui/wake.py"},
        {"path": "workspace/state/capability_requests.md", "purpose": "Human-facing requests for new capabilities (mounts, credentials, etc.)", "writer": "agent/infra/hardening.py", "reader": "agent/ui/wake.py"},
        {"path": "workspace/state/key_requests.md", "purpose": "Human-facing requests for supplementary provider API keys", "writer": "agent/llm/providers/registry.py", "reader": "agent/ui/wake.py"},
        {"path": "workspace/state/egress.jsonl", "purpose": "Audit log of external HTTP requests made by tools", "writer": "agent/infra/hardening.py", "reader": "agent/reporting/report.py"},
        {"path": "workspace/state/audit_trail.jsonl", "purpose": "Append-only hash-chained action audit log with SHA-256 verification", "writer": "agent/infra/audit_trail.py", "reader": "agent/infra/audit_trail.py"},
        {"path": "workspace/state/extension_diffs.log", "purpose": "Append-only diff log for self-modifications loaded from /home/entity/self/", "writer": "agent/infra/untrusted.py", "reader": "agent/infra/untrusted.py"},
        {"path": "workspace/logs/actions.jsonl", "purpose": "Primary append-only event log containing all system and agent events", "writer": "agent/infra/event_log.py", "reader": "agent/infra/event_log.py, agent/reporting/report.py, agent/ui/wake.py"},
        {"path": "workspace/memory/lessons.jsonl", "purpose": "Recorded tool failure lessons after 3 failed creation attempts", "writer": "agent/tools/tool_registry.py", "reader": "agent/runtime/loop.py"},
        {"path": "config/plugins.json", "purpose": "Human-owned configuration file recording plugin enablement status and SHA-256 hash pins", "writer": "agent/plugins/manager.py", "reader": "agent/plugins/manager.py"},
        {"path": "config/permissions.json", "purpose": "Human-owned permission policy defining action levels (L0-L3) and actor grants", "writer": "Human operator", "reader": "agent/infra/permission_broker.py"},
        {"path": "config/egress_allowlist.txt", "purpose": "Human-owned domain and IP prefix allowlist for hardened egress proxy sidecar", "writer": "Human operator", "reader": "scripts/egress_proxy.py"}
    ]

def get_entry_points():
    return [
        {"name": "agent.wake", "path": "agent/ui/wake.py", "type": "CLI / Main Service", "description": "Primary container entrypoint running WakeCoordinator with Textual TUI or --headless mode."},
        {"name": "agent.run", "path": "agent/run.py", "type": "CLI / Entrypoint", "description": "Headless agent entrypoint running WakeCoordinator without Textual UI (--headless mode)."},
        {"name": "agent.runtime.loop", "path": "agent/runtime/loop.py", "type": "CLI", "description": "Direct execution of autonomous exploration loop with --task, --max-iterations, etc."},
        {"name": "agent.reporting.report", "path": "agent/reporting/report.py", "type": "CLI", "description": "Generate markdown summary report of agent activity, token spend, and discoveries."},
        {"name": "agent.helper_models.model_outcomes", "path": "agent/helper_models/model_outcomes.py", "type": "CLI", "description": "Print summary table of helper model decisions, outcomes, and stats."},
        {"name": "agent.helper_models.model_decisions", "path": "agent/helper_models/model_decisions.py", "type": "CLI", "description": "Print summary of model decisions recorded in state/model_decisions.jsonl."},
        {"name": "agent.ui.version_check", "path": "agent/ui/version_check.py", "type": "CLI / Hook", "description": "Verify code hash against expected image version to catch stale containers."},
        {"name": "agent.ui.phase8_verify", "path": "agent/ui/phase8_verify.py", "type": "CLI", "description": "Verification script for Phase 8 identity and plan integration."},
        {"name": "agent.plugins", "path": "agent/plugins/__main__.py", "type": "CLI", "description": "Static plugin CLI for scaffolding (new), manifest validation (validate), discovery listing (list), and version compatibility checks (check)."},
        {"name": "agent.tools.tool_worker", "path": "agent/tools/tool_worker.py", "type": "Subprocess Worker", "description": "Subprocess runner for custom tools; reads JSON from stdin and emits JSON envelope."},
        {"name": "scripts/egress_proxy.py", "path": "scripts/egress_proxy.py", "type": "Proxy Sidecar", "description": "Forward HTTP/HTTPS filtering proxy sidecar with domain allowlist for hardened profile."},
        {"name": "scripts/run-tests.ps1", "path": "scripts/run-tests.ps1", "type": "Host Script", "description": "Build CI image and run agent unit tests and isolated eval unit tests in Docker."},
        {"name": "scripts/run-tests.sh", "path": "scripts/run-tests.sh", "type": "Host Script", "description": "Shell script equivalent of run-tests.ps1 for Linux/macOS hosts."},
        {"name": "scripts/live-check.ps1", "path": "scripts/live-check.ps1", "type": "Host Script", "description": "Diagnostic health check verifying image, plan, models, errors, framing, and environment."}
    ]

def get_packages():
    return [
        {"package": "agent.infra", "layer": 0, "purpose": "Event logging, file locks, process runner, provider call caps, daily token budget, permission broker, untrusted data delimiters, stop watcher, and audit trail."},
        {"package": "agent.llm", "layer": 1, "purpose": "LLM client, BudgetedLLM wrapper, model registry, provider adapters, and brain router."},
        {"package": "agent.body", "layer": 1, "purpose": "Body interface, capability declarations, sensing, hardware/OS actions, and ContainerBody implementation."},
        {"package": "agent.tools", "layer": 2, "purpose": "Base tools, tool runner, tool registry, tool creation pipeline, and tool worker subprocess."},
        {"package": "agent.learning", "layer": 2, "purpose": "Persistent plan store, memory store, environment map, self notes, and exploration coverage."},
        {"package": "agent.helper_models", "layer": 2, "purpose": "Model prober, model decision router/picker, outcomes tracker, and delegation logic."},
        {"package": "agent.identity", "layer": 2, "purpose": "Identity store, first awakening, name context resolution, traits, and core patch proposals."},
        {"package": "agent.plugins", "layer": 2, "purpose": "Plugin lifecycle, discovery, manifest validation, dynamic tool registration, and SHA-256 hash pinning."},
        {"package": "agent.runtime", "layer": 3, "purpose": "Autonomous agent loop, cycle coordination, prompt assembly, and tool round execution."},
        {"package": "agent.session", "layer": 4, "purpose": "Headless WakeCoordinator, session management, inter-session handoff, independent conversations, and background reflections."},
        {"package": "agent.reporting", "layer": 4, "purpose": "Activity reporting and experiment summary generation."},
        {"package": "agent.ui", "layer": 5, "purpose": "Textual TUI front-end, cardiac monitor, voice interface, and terminal front-end."}
    ]


def main():
    tools = get_tools()
    events = get_events()
    env_vars = get_env_vars()
    state_files = get_state_files()
    entry_points = get_entry_points()
    packages = get_packages()

    system_map = {
        "$schema": "docs/architecture/system-map.json",
        "description": "Machine-readable map of the SELF agent architecture",
        "packages": packages,
        "entry_points": entry_points,
        "tools": tools,
        "events": events,
        "state_files": state_files,
        "env_vars": env_vars
    }

    out_file = REPO_ROOT / "docs" / "architecture" / "system-map.json"
    with open(out_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(system_map, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {out_file} successfully:")
    print(f"  Packages: {len(packages)}")
    print(f"  Entry points: {len(entry_points)}")
    print(f"  Tools: {len(tools)}")
    print(f"  Events: {len(events)}")
    print(f"  State files: {len(state_files)}")
    print(f"  Env vars: {len(env_vars)}")

if __name__ == "__main__":
    main()
