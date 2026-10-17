# Helper-model experiment

The question is whether giving SELF access to configured helper models improves objectively checked tasks. The randomized `off` versus `on` arm comparison is the causal test. Comparisons among `on` runs that happened to use a helper are **observational**. The `forced_critic:<model>` arm is optional and isolates tool-review model choice.

The hidden task definitions and verifiers stay under `eval/` on the host. Each run gets a fresh `ab_runs/<run_id>/workspace` copy of `ab_seed/workspace`; only that run workspace is mounted into `self`. The verifier runs in an eval image with a read-only workspace mount, no network, and no provider credentials. None of these commands has been used here to make a live provider call.

Run these commands from the repository root in PowerShell. Steps 2, 4, 7, and 8 spend provider quota. Read each dry-run count and your provider's remaining quota first; the hidden benchmark plans 840 calls before possible retries, while the full A/B plan caps at 864 attempts with the default 12 per run.

Before the live steps, run both provider-free test suites with the shared
entry point:

```powershell
.\scripts\run-tests.ps1
```

1. Correct model names in the private `.env`, then rebuild and recreate the stopped image. Set the base name in `OLLAMA_MODEL` (or `ANTHROPIC_MODEL`) and comma-separated eligible helpers in `LLM_AVAILABLE_MODELS`. Keep `SELF_HELPER_MODELS=on` for the preparation session.

   ```powershell
   # Edit .env locally; do not paste keys into a chat or a report.
   docker compose build self eval
   docker compose create --force-recreate self
   ```

2. Before seeing benchmark results, let SELF probe configured models, research official model pages, and record its own assessments and five category ratings. Review `workspace/state/models.json` afterward. This is a live agent session.

   ```powershell
   docker compose run --rm --entrypoint python self /opt/agent/loop.py --max-iterations 8 --token-budget 30000 --task "Probe each configured helper model, research its official documentation, and record evidence-backed assessments and ratings for reasoning, code, instruction following, summarization, and JSON output."
   ```

3. Stop the agent before running host-only evaluation.

   ```powershell
   docker compose stop self
   ```

4. Stage the hidden benchmark with a dry run, then run it only when the planned quota is available. The evaluator uses the read-only workspace and writes results under `eval/results/`.

   ```powershell
   docker compose --profile eval run --rm -T eval --dry-run
   docker compose --profile eval run --rm -T eval
   ```

5. Calibrate the pre-benchmark ratings against the latest hidden result. Save the printed host-side calibration for later reporting.

   ```powershell
   New-Item -ItemType Directory -Path eval/ab -Force | Out-Null
   docker compose --profile eval run --rm -T --entrypoint python eval -m eval.calibrate /home/entity | Tee-Object -FilePath eval/ab/calibration-latest.txt
   ```

6. Build one seed from the current identity, environment map, and model assessments. The seed resets measured statistics and omits logs, memory, generated tools, and decision/outcome records. Its content hash is recorded in each run result.

   ```powershell
   docker compose --profile eval run --rm -T --entrypoint python eval -m eval.ab_plan --make-seed
   ```

7. Pilot all 12 tasks with the `off` arm, three repetitions. The first command makes no provider calls. The runner saves progress after every run; increase the cumulative call cap across invocations when quota permits.

   ```powershell
   docker compose --profile eval run --rm -T --entrypoint python eval -m eval.ab_plan --pilot --dry-run --seed 20261017 --max-total-calls 432
   docker compose --profile eval run --rm -T --entrypoint python eval -m eval.ab_plan --pilot --seed 20261017 --max-total-calls 432
   .\scripts\ab-run.ps1 -MaxTotalCalls 72
   .\scripts\ab-run.ps1 -MaxTotalCalls 432
   ```

8. Save the randomized full plan, then run sequential stages with a cumulative provider-attempt cap. The script archives the completed pilot state when the plan changes. `off` and `on` results have distinct run IDs; pilot runs are excluded from the full comparison. An interrupted run is recorded as an infrastructure error for inspection.

   ```powershell
   docker compose --profile eval run --rm -T --entrypoint python eval -m eval.ab_plan --dry-run --seed 20261017 --arms off,on --runs 3 --max-total-calls 864
   docker compose --profile eval run --rm -T --entrypoint python eval -m eval.ab_plan --seed 20261017 --arms off,on --runs 3 --max-total-calls 864
   .\scripts\ab-run.ps1 -MaxTotalCalls 100
   .\scripts\ab-run.ps1 -MaxTotalCalls 200
   .\scripts\ab-run.ps1 -MaxTotalCalls 864
   ```

9. Analyze the valid full-campaign results and supply the saved comparison and calibration to a **host-side** report. The agent container never reads `eval/`.

   ```powershell
   docker compose --profile eval run --rm -T --entrypoint python eval -m eval.ab_analyze | Tee-Object -FilePath eval/ab/analysis-latest.txt
   $env:SELF_REPORT_CALIBRATION_FILE = (Resolve-Path eval/ab/calibration-latest.txt).Path
   $env:SELF_REPORT_AB_FILE = (Resolve-Path eval/ab/analysis-latest.txt).Path
   python -m agent.report --workspace (Resolve-Path workspace).Path --no-advance
   Remove-Item Env:SELF_REPORT_CALIBRATION_FILE, Env:SELF_REPORT_AB_FILE
   ```

The task set has three tasks per category:

| Category | Task IDs |
| --- | --- |
| `create_tool` | `tool_slugify`, `tool_duration`, `tool_dedupe` |
| `data_and_code` | `data_sales`, `data_events`, `data_inventory` |
| `extraction_and_summary` | `extract_incident`, `extract_release`, `extract_policy` |
| `container_investigation` | `investigate_python`, `investigate_tools`, `investigate_os` |

The analysis excludes contaminated and infrastructure-error runs but lists and counts them. It separates tasks that are at 0% or 100% in every arm, reports sample sizes and a within-task bootstrap interval, and states whether that interval excludes zero. An interval that includes zero is inconclusive at the observed sample size; it does not establish that helper access has no effect. A small pilot is mainly a test of the harness and task difficulty.

## Operator Guide: Model Evaluation & Routing

### 1. Onboarding & Re-evaluation
- On wake-up, the agent checks `helpers_needing_evaluation`: any configured helper lacking a probe at the current probe format version, with an invalidated probe, with `not_checked` research status, or lacking an agent assessment is surfaced to the agent.
- The agent performs the evaluation itself using `probe_model`, then `research_model`, then `record_model_assessment` (citing the probe ID as evidence).
- Assessments are recorded as compact, single-line comparisons putting total/active params and context window first (or unknown), followed by `status ok`, reporting measured_stats call latency (total / calls) next to probe-only latency labeled separately (e.g. `550B/55B, ctx 262k+, status ok, call latency ~2.1s, probe latency ~1.8s, strong reasoning; probe 4/4 passed`), explicitly distinguishing web facts (verified) from unverified `model_knowledge`.
- `research_model` fetches the official model page and Ollama `/tags` sections up to 500 KB, stripping boilerplate and navigation elements. It marks status `facts_found` only when verified properties are extracted with excerpts, otherwise `fetched_no_model_fact`, or `not_found` when a model has no matching page.

### 2. Validation & Model Names
- Model names must exactly match configured registry entries. Calling tools with a missing or extra `-cloud` suffix returns an actionable alias hint explaining that results will not attach to the configured entry.
- `ask_model` rejects the fixed base model (`gpt-oss:120b`) and lists enabled helpers. Unknown arguments return friendly errors listing valid arguments rather than raising Python `TypeError`.

### 3. Checkpoints & Decision Caching
- Checkpoint caps have been removed (`MAX_CHECKPOINTS_PER_SESSION`); every checkpoint decision is a real deliberate choice with a reason.
- Decisions are cached per moment (e.g. `create_tool_critic`, `session_end_handoff`) within the active task and current tool attempt. The cache is invalidated on a new tool name, new task start (`start_task`), or any tool/provider failure.
- Honest error fallbacks (`origin: "default_after_error"`) remain only for real network or unrecoverable provider failures.

### 4. Output Ceilings, Bounded Retries & Daily Token Allowance
- The daily token allowance (`DailyTokenLedger` / `SELF_MAX_TOKENS_PER_DAY`) is the single token limit. Per-run and per-session budgets have been eliminated.
- Calls reserve an input estimate plus expected output tokens rather than the full ceiling, so a large model ceiling never blocks a call when the daily allowance covers likely usage. Mid-call daily exhaustion allows the call to finish, while the subsequent call pauses until reset.
- Structured callers (reflection, critic, checkpoint) use the model's registry ceiling (`get_output_cap`, defaulting to 32,768). On truncation (`stop_reason: max_tokens`) or parse failure, exactly one bounded retry is executed requesting concise output conforming to valid JSON.
- Truncated calls increment `truncated_calls` in `measured_stats` and record `call_truncated` and `output_parse_failed` signals in `model_outcomes.jsonl`.
- Transient network and connection errors (`APIConnectionError`, `ConnectionError`, timeouts) are retried with exponential backoff and recorded as `network_errors`. They do not touch `failures` or `consecutive_failures`, and token reservations in `BudgetedLLM` are released.

### 5. Interpreting `critic_flagged_but_tests_passed`
- The `critic_flagged_but_tests_passed` signal is **ambiguous**: it often indicates that the critic astutely caught a subtle bug, security flaw, or edge case that an incomplete or weak unit test suite missed.
- Do **not** treat this signal as negative evidence against the critic model; flag it for manual review of both the generated code and unit tests.
