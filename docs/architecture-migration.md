# Architecture migration

## Progress

- [x] A0 inventory, dependency review, and provider-free baseline captured.
- [x] A1–A4 modular move, READMEs, and import guard.
- [x] Gate A: rebuild, recreate, full and eval tests, entry points, protection, and diff review.
- [x] Part B A/B harness and Gate B (provider-free construction and dry-runs; campaign not executed).
- [x] Part C reporting, TUI, docs, and Gate C.

No live provider call has been made. The A/B campaign remains for the operator.

## Gate A record

1. `docker compose build self eval` and `docker compose create --force-recreate self` succeeded. The container was recreated without starting the agent.
2. The documented harness command passed 109 tests: all 108 baseline tests plus the new import-graph guard. The eval-only command passed 7 tests.
3. Container `compileall -q /opt/agent` passed; importing all 47 discoverable `agent.*` modules passed. `agent.wake --help` printed successfully and `agent.ui.wake` imported.
4. Provider-free wake, loop, report, model outcomes, eval runner, and calibrate output matched [the baseline](architecture-baseline.txt) exactly after removing Compose container IDs; see [post-migration output](architecture-post-a.txt). The live-only disk demo could not be invoked under the no-provider-call rule.
5. A disposable container rejected `write_file` to `/opt/agent/runtime/loop.py` and left its bytes unchanged. The protected-core unit tests passed.
6. `git diff HEAD -M --summary` identified moves below 98% similarity. All changes in those moved files are module docstrings and import or mock target paths; no function or class body was edited. The differences are larger in short tests and CLIs because several import lines form a higher fraction of the file.
7. Tracked `workspace/` and `.env` contents did not change. Resolved `self` mounts contain only `/home/entity`; there is no `eval/` or Docker-socket mount.

## Gate B record

- Rebuilt `self` and `eval`, recreated the stopped `self` container, and passed 112 harness tests and 11 eval tests. The new tests use fake models and crafted workspaces.
- Container compile and import checks passed for 48 harness modules and 5 eval modules. Provider-free legacy entry-point outputs matched the A0 baseline in [post-B output](architecture-post-b.txt); protected source writes were rejected again.
- The resolved `self` service mount, with `SELF_WORKSPACE_DIR` set to an `ab_runs` path, was only that run workspace at `/home/entity`. `.env` and tracked `workspace/` files remain unchanged.
- `ab_plan --dry-run --seed 20261017` reported 72 full runs with a provider-call upper bound of 864. The `--pilot --dry-run` reported 36 runs and a bound of 432. The per-run cap is 12 attempts and the campaign cap can stop earlier.
- `--make-seed` copied only `state/identity.json`, `state/map.json`, and a stats-reset `state/models.json` into gitignored `ab_seed/workspace`. Seed hash: `937b9ac5614f94af707e70c44934bd3cd0c0b9c97124b23fa24c22c1e4abb853`. A deterministic full plan was saved to gitignored `eval/ab/plan.json`. No campaign run or live provider call was made.

## Gate C record

- Rebuilt `self` and `eval`, recreated the stopped `self` container, and passed 116 harness tests and 11 eval-only tests. The report, `/models`, container host-result isolation, and A/B verifier tests use fakes or disposable workspaces.
- Container compile and import checks passed for 48 discoverable harness modules and 5 eval modules. `agent.ui.wake` imported. Six provider-free legacy entry points matched the baseline after removing Compose container IDs; see [post-C output](architecture-post-c.txt). The live-only disk demo remained uninvoked.
- The protected harness write was rejected in a disposable container with the source bytes unchanged. Default and A/B override `self` mounts each contain only one `/home/entity` workspace; neither includes `eval/` or the Docker socket. Tracked `workspace/` and `.env` remain unchanged.
- Full and pilot dry-runs still report 72/864 and 36/432 planned runs/provider-attempt upper bounds. The corrected standalone verifier entry point ran offline with a disposable seed workspace and yielded an infrastructure-error result as expected; the fixture and result were removed. The PowerShell runner parses. No live provider call was made.

## Final tree and compatibility

Python source modules, excluding `__init__.py` and tests: `infra` 5, `llm` 3 plus `llm/providers` 3, `tools` 4, `learning` 2, `helper_models` 3, `identity` 2, `runtime` 1, `session` 3, `reporting` 1, and `ui` 4. Six root shims remain: `wake.py`, `loop.py`, `report.py`, `model_outcomes.py`, `disk_tool_demo.py`, and `event_log.py`. They preserve documented module commands, direct `/opt/agent` script commands, and the documented flat `event_log` import. `eval/` stays at the repository root because its hidden tasks and results must remain host-only. `wake.py` remains one large module because its Textual construction and module state do not provide a safe whole-class split; `loop.py` is below the split threshold.

The upward-import fixes are the placement of shared `hardening.py` in `infra` and `model_registry.py` in `llm`. `identity` is below `runtime` because the existing loop constructs its identity store. `disk_tool_demo.py` is in `ui` because it imports runtime. These choices preserve Part A function bodies and yield an acyclic guarded import graph. Part A's test count rises by one for the new graph guard; B and C add the fake tests listed above.

Final `git diff HEAD -M --summary` shows these moves below 98% similarity: `brain_router.py`, `llm.py`, `providers/base.py`, `loop.py`, `conversation.py`, `base_tools.py`, `benchmark.py`, `disk_tool_demo.py`, `phase8_verify.py`, `wake.py`; and moved tests for `model_decisions`, `model_outcomes`, `model_probe`, `identity`, `hardening`, `process_runner`, `coverage`, `learning`, `llm`, `providers`, `report`, `loop`, `conversation`, `reflection`, `session`, `base_tools`, and `tool_registry`. The Part A changes in those files were module docstrings and import/mock paths; Part B and C later added behavior and tests to `llm.py`, `loop.py`, `wake.py`, and related tests. `report.py` is shown as a deletion plus `reporting/report.py` creation by Git because Part C substantially extended the report after its `git mv`.

## Experiment handoff

The 12 tasks are `tool_slugify`, `tool_duration`, `tool_dedupe` (`create_tool`); `data_sales`, `data_events`, `data_inventory` (`data_and_code`); `extract_incident`, `extract_release`, `extract_policy` (`extraction_and_summary`); and `investigate_python`, `investigate_tools`, `investigate_os` (`container_investigation`). The full randomized plan has 72 runs with an 864-attempt upper bound; the off-arm pilot has 36 runs with a 432-attempt upper bound. The operator steps are in [helper-model-experiment.md](helper-model-experiment.md).

Open validation limit: no live A/B run or provider call was allowed in this session, so real quota stops, model responses, and task success rates remain unobserved. The offline verifier and fake tests cover the runner's data path, but the operator should inspect the first pilot results before spending the full campaign allowance. On this Windows host, `python` currently resolves to an unavailable Python install-manager runtime, so the optional host-side report command in the experiment guide requires an installed host Python; the Docker test commands do not.

## Baseline

- Documented Docker test command: `docker compose run --rm --entrypoint python self -m unittest discover -s /opt/agent/tests -v` — 108 tests passed.
- Eval-only command: `docker compose --profile eval run --rm --entrypoint python eval -m unittest discover -s /opt/eval/tests -v` — 7 tests passed.
- Provider-free entry-point recordings: [architecture-baseline.txt](architecture-baseline.txt). `disk_tool_demo.py` has no help/dry-run mode and its `main()` explicitly calls the live provider, so it cannot be executed under the no-provider-call rule. `agent.report` was recorded with `--help` to avoid changing workspace report state.
- Initial `git status --short` was empty.

## Proposed module moves

The groups follow the code's responsibilities: `infra` holds event logging, process isolation, locks, and shared budget/checkpoint primitives; `llm` holds clients, provider routing, and the registry the client constructs; `tools` holds built-in and generated tools; `learning` holds memory and coverage; `helper_models` holds probes, decisions, and outcomes; `runtime` holds the action loop; `session` holds persisted sessions and background conversations/reflection; `identity` holds identity and name context; `ui` holds wake, voice, and verification CLI; `reporting` holds summaries. `eval/` remains host-only.

| Old | Planned new |
| --- | --- |
| `agent/base_tools.py` | `agent/tools/base_tools.py` |
| `agent/benchmark.py` | `agent/tools/benchmark.py` |
| `agent/brain_router.py` | `agent/llm/brain_router.py` |
| `agent/conversation.py` | `agent/session/conversation.py` |
| `agent/disk_tool_demo.py` | `agent/ui/disk_tool_demo.py` |
| `agent/event_log.py` | `agent/infra/event_log.py` |
| `agent/exploration_coverage.py` | `agent/learning/exploration_coverage.py` |
| `agent/file_lock.py` | `agent/infra/file_lock.py` |
| `agent/hardening.py` | `agent/infra/hardening.py` |
| `agent/identity.py` | `agent/identity/identity.py` |
| `agent/learning.py` | `agent/learning/learning.py` |
| `agent/llm.py` | `agent/llm/llm.py` |
| `agent/loop.py` | `agent/runtime/loop.py` |
| `agent/model_decisions.py` | `agent/helper_models/model_decisions.py` |
| `agent/model_outcomes.py` | `agent/helper_models/model_outcomes.py` |
| `agent/model_probe.py` | `agent/helper_models/model_probe.py` |
| `agent/model_registry.py` | `agent/llm/model_registry.py` |
| `agent/name_context.py` | `agent/identity/name_context.py` |
| `agent/phase8_verify.py` | `agent/ui/phase8_verify.py` |
| `agent/process_runner.py` | `agent/infra/process_runner.py` |
| `agent/reflection.py` | `agent/session/reflection.py` |
| `agent/report.py` | `agent/reporting/report.py` |
| `agent/session.py` | `agent/session/session.py` |
| `agent/tool_registry.py` | `agent/tools/tool_registry.py` |
| `agent/tool_worker.py` | `agent/tools/tool_worker.py` |
| `agent/voice.py` | `agent/ui/voice.py` |
| `agent/wake.py` | `agent/ui/wake.py` |
| `agent/providers/*.py` | `agent/llm/providers/*.py` |
| `agent/tests/test_*.py` | `agent/tests/<matching package>/test_*.py` |
| `eval/*.py`, `eval/tests/*.py` | remain in `eval/` |

External compatibility paths to retain are `agent.wake`, `agent.report`, `agent.model_outcomes`, `/opt/agent/loop.py`, `/opt/agent/disk_tool_demo.py`, and the documented flat `event_log` import. Other old flat paths should be removed after internal imports, tests, and patch targets are updated. CLI shims must dispatch `main()` under `__main__`.

## Dependency findings

The current flat import graph has no cycle among harness modules. The requested layer order is `infra → llm → tools/learning/helper_models → runtime → session/identity → ui`. Three existing edges conflict with that exact order: `llm → hardening` (token ledger), `llm → model_registry` (client constructs registry), and `loop → identity` (loop constructs identity store). Placing `hardening` in `infra` and `model_registry` in `llm` resolves the first two without body changes. Moving identity above runtime would require changing how `AgentLoop` receives its `IdentityStore`; the implemented order keeps that existing construction. `wake.py` has 1,652 lines but shares module state and nested UI construction, so leave it intact and document a section map. No split is needed for `loop.py` (653 lines).

The implemented guard uses `infra → llm → tools/learning/helper_models/identity → runtime → session/reporting → ui`. This is a documented deviation from the proposed identity position: `AgentLoop` still constructs `IdentityStore`, preserving its existing behavior. The live disk-tool demo was moved to `ui` because it imports the loop. The guard adds one test, so the expected count is the 108 baseline tests plus one import-graph test.

## Compatibility scan

No active `workspace/tools/*/tool.py`, `workspace/self/*.py`, or `scripts/*.ps1` imports flat harness modules. The root README documents `from event_log import ...` and direct `/opt/agent/loop.py` and `/opt/agent/disk_tool_demo.py` commands. `scripts/verify-phase7.ps1` and `verify-phase8.ps1` use the documented test path. The Dockerfile's current `core` relocation and symlinks need replacing; `self` must remain without an `eval/` mount.

## Python inventory

`Imports` lists repository-local flat-module dependencies. `Importers` includes tests; standard-library and third-party imports are omitted from this compact graph.

The [complete pre-migration inventory](architecture-inventory.md) lists every Python file, all static imports, and importers.

| Module | Lines | Imports | Importers |
| --- | ---: | --- | --- |
| `agent/__init__.py` | 1 | — | — |
| `agent/base_tools.py` | 468 | benchmark, event_log, llm, process_runner | agent/disk_tool_demo.py, agent/loop.py, agent/phase8_verify.py, agent/tests/test_base_tools.py, agent/tests/test_identity.py, agent/tests/test_learning.py, agent/tests/test_llm.py, agent/tests/test_loop.py, agent/tests/test_model_decisions.py, agent/tests/test_tool_registry.py, agent/wake.py |
| `agent/benchmark.py` | 37 | brain_router, event_log | agent/base_tools.py, agent/tests/test_providers.py |
| `agent/brain_router.py` | 185 | event_log | agent/benchmark.py, agent/loop.py, agent/tests/test_providers.py |
| `agent/conversation.py` | 107 | event_log, hardening, llm | agent/tests/test_conversation.py, agent/wake.py |
| `agent/disk_tool_demo.py` | 57 | base_tools, event_log, llm, loop | — |
| `agent/event_log.py` | 101 | — | agent/base_tools.py, agent/benchmark.py, agent/brain_router.py, agent/conversation.py, agent/disk_tool_demo.py, agent/hardening.py, agent/identity.py, agent/learning.py, agent/llm.py, agent/loop.py, agent/model_decisions.py, agent/model_outcomes.py, agent/model_probe.py, agent/model_registry.py, agent/phase8_verify.py, agent/providers/registry.py, agent/reflection.py, agent/report.py, agent/session.py, agent/tests/test_base_tools.py, agent/tests/test_conversation.py, agent/tests/test_hardening.py, agent/tests/test_identity.py, agent/tests/test_learning.py, agent/tests/test_llm.py, agent/tests/test_loop.py, agent/tests/test_model_decisions.py, agent/tests/test_model_outcomes.py, agent/tests/test_model_probe.py, agent/tests/test_providers.py, agent/tests/test_reflection.py, agent/tests/test_report.py, agent/tests/test_session.py, agent/tests/test_tool_registry.py, agent/tool_registry.py, agent/wake.py |
| `agent/exploration_coverage.py` | 93 | — | agent/tests/test_coverage.py, agent/wake.py |
| `agent/file_lock.py` | 36 | — | agent/hardening.py, agent/loop.py, agent/model_decisions.py, agent/model_outcomes.py, agent/model_registry.py, agent/reflection.py, agent/wake.py, eval/tests/test_eval.py |
| `agent/hardening.py` | 121 | event_log, file_lock | agent/conversation.py, agent/llm.py, agent/loop.py, agent/providers/registry.py, agent/reflection.py, agent/tests/test_conversation.py, agent/tests/test_hardening.py, agent/tests/test_llm.py, agent/tests/test_model_decisions.py, agent/tests/test_model_probe.py, agent/tests/test_reflection.py, agent/wake.py |
| `agent/identity.py` | 707 | event_log, name_context | agent/loop.py, agent/phase8_verify.py, agent/tests/test_identity.py, agent/tests/test_session.py, agent/wake.py |
| `agent/learning.py` | 284 | event_log | agent/loop.py, agent/report.py, agent/tests/test_learning.py, agent/tests/test_report.py, agent/wake.py |
| `agent/llm.py` | 353 | event_log, hardening, model_registry | agent/base_tools.py, agent/conversation.py, agent/disk_tool_demo.py, agent/loop.py, agent/model_decisions.py, agent/model_probe.py, agent/phase8_verify.py, agent/reflection.py, agent/tests/test_conversation.py, agent/tests/test_identity.py, agent/tests/test_learning.py, agent/tests/test_llm.py, agent/tests/test_loop.py, agent/tests/test_model_decisions.py, agent/tests/test_model_probe.py, agent/tests/test_reflection.py, agent/tests/test_session.py, agent/tests/test_tool_registry.py, agent/tool_registry.py, agent/wake.py, eval/runner.py, eval/tests/test_eval.py |
| `agent/loop.py` | 653 | base_tools, brain_router, event_log, file_lock, hardening, identity, learning, llm, model_decisions, model_probe, model_registry, tool_registry | agent/disk_tool_demo.py, agent/tests/test_identity.py, agent/tests/test_learning.py, agent/tests/test_loop.py, agent/tests/test_model_decisions.py, agent/tests/test_tool_registry.py, agent/wake.py |
| `agent/model_decisions.py` | 570 | event_log, file_lock, llm, model_outcomes, model_registry | agent/loop.py, agent/reflection.py, agent/tests/test_model_decisions.py, agent/tests/test_model_outcomes.py, agent/wake.py |
| `agent/model_outcomes.py` | 111 | event_log, file_lock | agent/model_decisions.py, agent/tests/test_model_outcomes.py |
| `agent/model_probe.py` | 315 | event_log, llm, model_registry | agent/loop.py, agent/tests/test_model_probe.py |
| `agent/model_registry.py` | 354 | event_log, file_lock | agent/llm.py, agent/loop.py, agent/model_decisions.py, agent/model_probe.py, agent/tests/test_llm.py, agent/tests/test_model_decisions.py, agent/tests/test_model_outcomes.py, agent/tests/test_model_probe.py |
| `agent/name_context.py` | 154 | — | agent/identity.py |
| `agent/phase8_verify.py` | 105 | base_tools, event_log, identity, llm, wake | — |
| `agent/process_runner.py` | 82 | — | agent/base_tools.py, agent/tests/test_process_runner.py, agent/tool_registry.py |
| `agent/providers/__init__.py` | 6 | — | — |
| `agent/providers/adapters.py` | 166 | — | — |
| `agent/providers/base.py` | 34 | — | — |
| `agent/providers/registry.py` | 179 | event_log, hardening | — |
| `agent/reflection.py` | 304 | event_log, file_lock, hardening, llm, model_decisions | agent/tests/test_reflection.py, agent/wake.py |
| `agent/report.py` | 142 | event_log, learning | agent/tests/test_hardening.py, agent/tests/test_report.py |
| `agent/session.py` | 183 | event_log | agent/tests/test_session.py, agent/wake.py |
| `agent/tool_registry.py` | 363 | event_log, llm, process_runner | agent/loop.py, agent/tests/test_model_decisions.py, agent/tests/test_tool_registry.py |
| `agent/tool_worker.py` | 26 | — | — |
| `agent/voice.py` | 121 | — | agent/wake.py |
| `agent/wake.py` | 1652 | base_tools, conversation, event_log, exploration_coverage, file_lock, hardening, identity, learning, llm, loop, model_decisions, reflection, session, voice | agent/phase8_verify.py, agent/tests/test_coverage.py, agent/tests/test_model_decisions.py, agent/tests/test_reflection.py, agent/tests/test_session.py |
| `eval/__init__.py` | 1 | — | — |
| `eval/calibrate.py` | 152 | — | — |
| `eval/runner.py` | 309 | llm | — |
