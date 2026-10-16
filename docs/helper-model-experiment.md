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
