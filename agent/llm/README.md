# Llm

## Purpose

Model calls, provider adapters, routing, and the model registry. The client constructs ModelRegistry, so the registry lives beside it.

## Read first

1. `llm.py` — Budgeted and provider-backed model calls.
2. `model_registry.py` — Available model metadata, ratings, and stats.
3. `brain_router.py` — Optional provider selection.
4. `providers/base.py` — Provider protocol and errors.
5. `providers/adapters.py` — Provider HTTP adapters.
6. `providers/registry.py` — Provider research metadata.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `llm.py` | Budgeted and provider-backed model calls | `LLMClient, BudgetedLLM, LLMResult` |
| `model_registry.py` | Available model metadata, ratings, and stats | `ModelRegistry` |
| `brain_router.py` | Optional provider selection | `BrainRouter` |
| `providers/base.py` | Provider protocol and errors | `ProviderAdapter, ProviderResponse` |
| `providers/adapters.py` | Provider HTTP adapters | `OpenAICompatibleAdapter, GeminiAdapter` |
| `providers/registry.py` | Provider research metadata | `ProviderRegistry` |

## How it works

LLMClient selects the configured base provider and records usage in ModelRegistry. BudgetedLLM manages token allowance against the daily ledger; BrainRouter uses the separate provider adapter registry.

- **Single Daily Token Limit**: The daily ledger (`DailyTokenLedger` / `SELF_MAX_TOKENS_PER_DAY`) is the only active token limit. Per-run and per-session budgets (`SELF_TOKEN_BUDGET`) have been removed, and the `--token-budget` CLI flag is deprecated.
- **Model Output Ceilings**: Per-call hardcoded output caps have been replaced with the model's maximum output length from registry (`get_output_cap`, defaulting to 32,768 if unconfigured).
- **Daily Budget Reservation**: Calls reserve an estimated input allowance plus expected output tokens rather than the full ceiling, settling against actual spend. Mid-call daily allowance exhaustion allows the call to complete cleanly; the subsequent call is refused with `BudgetExceeded(kind="daily")` and pauses until daily reset.
- **Model Registry (Schema Version 2)**: Tracks configured and unconfigured historical models, records `truncated_calls` and `network_errors` separately from model failures, computes `helpers_needing_evaluation` on wake-up, provides registry name validation with alias hints (`+/- "-cloud"`), and supports per-model output cap overrides via `get_output_cap`.
- **Transient Network Errors**: `APIConnectionError` and transport/connection failures are retried with bounded exponential backoff. If exhausted, they are counted as `network_errors` without resetting or incrementing `consecutive_failures`. In `BudgetedLLM`, network error reservations are settled to 0 and released back to the daily ledger without incrementing `tokens_used`.

## State it touches

Workspace paths: state/models.json (schema_version 2), state/providers.json, state/daily_tokens.json, logs/actions.jsonl.

## Depends on / used by

Depends on infra. Used by tools, helper_models, runtime, session, and ui.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/llm -v` in the container.

## Gotchas

1. A model call spends quota. Tests use fake clients; do not run the live entry points as tests.
2. Models renamed in configuration retain their historical probe/assessment records under `configured: false` (`status: "unconfigured"`) and do not attach to the new name.
