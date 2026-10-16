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

LLMClient selects the configured base provider and records usage in ModelRegistry. BudgetedLLM reserves capacity; BrainRouter uses the separate provider adapter registry.

## State it touches

Workspace paths: state/models.json, state/providers.json, state/daily_tokens.json, logs/actions.jsonl.

## Depends on / used by

Depends on infra. Used by tools, helper_models, runtime, session, and ui.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/llm -v` in the container.

## Gotchas

A model call spends quota. Tests use fake clients; do not run the live entry points as tests.
