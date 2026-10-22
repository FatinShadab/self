# Opencode Delegation Operator Guide

This guide details host-side and container-side procedures for configuring, operating, verifying, and monitoring the `opencode` coding-agent subsystem within the SELF runtime.

---

## 1. Setting API Keys and Configuring Models

### Environment Variables
Opencode uses isolated, namespaced API keys in the environment. These are separated from SELF's core model credentials to prevent token bleed or unauthorized access:

| Variable Name | Required Providers | Description |
| :--- | :--- | :--- |
| `OPENCODE_GROQ_API_KEY` | Groq (`deepseek-r1-distill-llama-70b`, `llama-3.3-70b-versatile`) | API key for Groq Cloud free tier |
| `OPENCODE_GOOGLE_API_KEY` | Google Gemini (`gemini-2.5-flash`, `gemini-2.5-pro`) | API key for Google AI Studio free tier |
| `OPENCODE_HUGGINGFACE_API_KEY` | Hugging Face Router (`Qwen/Qwen2.5-Coder-32B-Instruct`) | User access token for Hugging Face Inference API |

Set these in your host `.env` file or export them in your container runtime environment:
```bash
export OPENCODE_GROQ_API_KEY="gsk_..."
export OPENCODE_GOOGLE_API_KEY="AIzaSy..."
export OPENCODE_HUGGINGFACE_API_KEY="hf_..."
```

### Configuration Generation
Opencode configuration is generated via `scripts/opencode/generate_config.py`. It inspects environment variables, redacts secrets, and writes the provider manifest and model order to `/home/entity/.config/opencode/opencode.json` (or the directory indicated by `$OPENCODE_CONFIG_DIR`):

```bash
python scripts/opencode/generate_config.py --output /home/entity/.config/opencode/opencode.json
```

---

## 2. Install and Re-Install on OS/Platform Change

The installer script `scripts/opencode/install_opencode.py` manages installation, updates, and platform verification. It operates without shell pipes (`curl | sh`), downloading assets atomically and validating SHA256 checksums or trust-on-first-use (TOFU) locks.

### CLI Modes
- `--status`: Inspect current platform detection and binary installation state.
- `--build`: Build-time installation (used in Dockerfile). Exits non-zero only if `--strict` is passed.
- `--ensure`: Container startup mode. Idempotent: checks whether the binary exists, runs, and matches the detected platform. Exits 0 on download failure so the container still boots.
- `--force`: Force download and overwrite of the binary (used for manual upgrades, downgrades, or architecture migrations).

```bash
# Check status
python scripts/opencode/install_opencode.py --status

# Startup ensure (idempotent)
python scripts/opencode/install_opencode.py --ensure

# Force re-installation
python scripts/opencode/install_opencode.py --force
```

### Platform Detection
The installer detects:
- **OS:** Linux (`linux`)
- **Architecture:** x86_64 (`x64`) or ARM64 (`arm64`)
- **Libc:** `glibc` vs `musl` (detected via `ldd --version` or `/lib/ld-musl-*`)
- **AVX2:** Checks `/proc/cpuinfo` for AVX2 flag support to select baseline builds where applicable.

State is recorded in `state/opencode_install.json`.

---

## 3. Interpreting `state/opencode_status.json`

The operational health of opencode providers is stored in `state/opencode_status.json` and protected by a cross-process file lock (`state/opencode_status.json.lock`).

### Structure
```json
{
  "groq": {
    "state": "available",
    "until": null,
    "last_error": null,
    "last_checked": "2026-10-22T18:00:00Z",
    "consecutive_failures": 0,
    "key_hash": "a1b2c3d4..."
  },
  "google": {
    "state": "throttled",
    "until": "2026-10-22T19:00:00Z",
    "last_error": "429 Rate limit exceeded; retry in 3600s",
    "last_checked": "2026-10-22T18:00:00Z",
    "consecutive_failures": 1,
    "key_hash": "e5f6g7h8..."
  },
  "huggingface": {
    "state": "not_configured",
    "until": null,
    "last_error": "No API key configured in environment",
    "last_checked": "2026-10-22T18:00:00Z",
    "consecutive_failures": 0,
    "key_hash": ""
  }
}
```

### Provider States
- `available`: Ready for delegation calls.
- `throttled`: Rate-limited or temporarily exhausted. Has an `until` timestamp. Once `until` has elapsed, the state becomes `probe_due`. A probe must succeed before it returns to `available`.
- `invalid`: The API key was rejected (401/403). It will not be tried again until the environment key value changes (`key_hash` mismatch).
- `not_configured`: The corresponding `OPENCODE_*` key is absent from the environment.
- `unknown`: Key is present, but no call or probe has been executed yet.

### Usability Evaluation
`OpencodeStatusTracker.usability()` evaluates overall readiness:
- `usable`: `true` if at least one configured provider is `available`, `unknown`, or `probe_due`.
- `earliest_retry`: When all configured providers are throttled, reports the earliest ISO timestamp when a provider becomes `probe_due`.

---

## 4. Simulating Throttles and Errors with `fake_opencode.py`

Test fixture `agent/opencode/tests/fake_opencode.py` allows offline simulation of CLI execution without network access or live API credentials.

Set the `FAKE_OPENCODE_MODE` environment variable before executing:

```bash
# 1. Simulate successful file generation
export FAKE_OPENCODE_MODE="success"
python agent/opencode/tests/fake_opencode.py run "Build a tool"

# 2. Simulate 429 rate limit with explicit retry hint
export FAKE_OPENCODE_MODE="throttled_with_retry"
python agent/opencode/tests/fake_opencode.py run "Build a tool"
# Output: HTTP 429 Too Many Requests: Rate limit exceeded. Try again in 30s.

# 3. Simulate daily quota exhaustion
export FAKE_OPENCODE_MODE="quota_daily"
python agent/opencode/tests/fake_opencode.py run "Build a tool"
# Output: HTTP 429 ResourceExhausted: Daily quota exceeded for model.

# 4. Simulate invalid API credentials
export FAKE_OPENCODE_MODE="invalid_key"
python agent/opencode/tests/fake_opencode.py run "Build a tool"
# Output: HTTP 401 Unauthorized: Invalid API Key provided.

# 5. Simulate scope violations (writing outside target directory)
export FAKE_OPENCODE_MODE="scope_violation"
python agent/opencode/tests/fake_opencode.py run "Build a tool"

# 6. Simulate hanging process (triggers wall-clock timeout)
export FAKE_OPENCODE_MODE="hang"
python agent/opencode/tests/fake_opencode.py run "Build a tool"
```

---

## 5. Reviewing Decisions and Outcomes

SELF autonomously decides whether to implement code changes directly (`route: "self"`) or delegate to opencode (`route: "opencode"`). All decisions and outcomes are logged for accountability and continuous learning.

### Decision Records: `state/model_decisions.jsonl`
Whenever a build route is selected, a decision record is persisted.

Example record:
```json
{
  "session_id": "session_20261022_180000",
  "task_type": "build_route",
  "task": "Synthesize YAML validator helper plugin",
  "route": "opencode",
  "reasons": "Standalone module with well-defined schema; free-tier quota available",
  "expected_effort": "low",
  "origin": "agent",
  "timestamp": "2026-10-22T18:05:00Z"
}
```
*Note:* If opencode was unavailable or a human operator mandated a specific route, `origin` reflects `"forced:opencode_unavailable"` or `"forced:human_request"`. Forced decisions are excluded from preference learning.

### Outcome Records: `state/build_outcomes.jsonl`
When a build finishes (via acceptance, discard, failure, or direct completion), an outcome record is appended.

Example record:
```json
{
  "task_id": "del_20261022_001",
  "route": "opencode",
  "reasons": "Standalone module with well-defined schema; free-tier quota available",
  "expected_effort": "low",
  "result": "accepted",
  "acceptance_passed": true,
  "duration": 14.2,
  "retries": 0,
  "provider": "groq",
  "model": "deepseek-r1-distill-llama-70b",
  "forced_by": null,
  "notes": "Generated tests and plugin passed validation on first attempt.",
  "session_id": "session_20261022_180000",
  "timestamp": "2026-10-22T18:05:15Z"
}
```

### Inspecting Route Statistics
The agent (and operator) can query route statistics via `build_route_stats`:
```python
stats = model_decisions.build_route_stats(limit=10)
# Returns:
# - counts: {"self": 4, "opencode": 6, "total": 10}
# - pass_rate: {"self": 1.0, "opencode": 0.833}
# - median_duration: {"self": 12.0, "opencode": 14.5}
# - note: Imbalance suggestion if >80% non-forced records favor one route
# - recent_records: Formatted single-line history bounded to hard character limit (3,000 chars)
```

---

## 6. Manual Live Checklist (Steps Only)

Follow these steps to manually verify opencode integration in a live container:

### (a) Live Smoke Test
1. Confirm the binary is installed and executable:
   ```bash
   opencode --version
   python scripts/opencode/install_opencode.py --status
   ```
2. Verify provider environment keys are present:
   ```bash
   env | grep OPENCODE_
   ```
3. Run an initial status probe:
   ```bash
   python -c "from agent.opencode.status import OpencodeStatusTracker; tracker = OpencodeStatusTracker(); print(tracker.probe('groq'))"
   ```
4. Verify `state/opencode_status.json` records `"state": "available"` for the probed provider.

### (b) Trivial Delegation
1. In an interactive Python session or agent prompt, invoke `delegate_coding`:
   ```python
   from agent.opencode.wrapper import OpencodeDelegator
   delegator = OpencodeDelegator()
   result = delegator.delegate_coding(
       spec="Create a python module workspace/tools/hello.py that prints 'Hello from Opencode'",
       route_reasons="Live verification smoke test",
       target_dirs=["workspace/tools"],
       acceptance_check="python workspace/tools/hello.py"
   )
   print(result)
   ```
2. Inspect the sandbox diff output in `result["diff"]`.
3. Check `state/model_decisions.jsonl` for the corresponding `"task_type": "build_route"` entry.
4. Apply the delegation:
   ```python
   apply_res = delegator.apply_delegation(result["delegation_id"])
   print(apply_res)
   ```
5. Confirm `workspace/tools/hello.py` exists on disk and `state/build_outcomes.jsonl` contains `"result": "accepted"`.

### (c) Forced Invalid Key Failure
1. Temporarily set an invalid key for a provider:
   ```bash
   export OPENCODE_GROQ_API_KEY="gsk_invalid_test_key_12345"
   ```
2. Run a probe against that provider:
   ```python
   tracker.probe("groq")
   ```
3. Check `state/opencode_status.json` and confirm:
   - Provider state is `"invalid"`.
   - `last_error` contains the authentication error description.
   - Provider is skipped in subsequent delegation requests without retrying until the key hash changes.

### (d) Restore Key and Probe Recovery
1. Restore the valid API key in the environment:
   ```bash
   export OPENCODE_GROQ_API_KEY="<valid_groq_key>"
   ```
2. Trigger a probe:
   ```python
   tracker.probe("groq")
   ```
3. Confirm provider transitions from `"invalid"` back to `"available"`.
4. Confirm `OpencodeStatusTracker.usability()["usable"]` returns `true`.

---

## 7. Known Limitations

- **Staging Sandbox Isolation:** The sandbox operates via a separate workspace directory with symlinked or copied dependencies. It enforces path boundaries at pre-run and post-run check time, blocking modifications to core paths (`agent/`, `.git/`, `.env`, `config/`), but does not use OS-level root isolation (e.g. Docker-in-Docker). Acceptance tests and diff inspection are the primary safety boundary prior to promotion.
- **Free-Tier Provider Quotas:** Free-tier endpoints (Groq, Gemini, Hugging Face) have per-minute and per-day rate limits. When throttled, fallback to other configured providers occurs automatically. If all providers are throttled, SELF falls back cleanly to implementing tasks itself (`route: "self"`).
- **Subprocess Wall-Clock Timeouts:** Subprocess execution is bounded by default to 30 minutes for code generation and 10 minutes for acceptance testing. Tasks requiring longer compilation or processing must be subdivided.
