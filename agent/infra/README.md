# Infra

## Purpose

Shared logging, locking, process execution, and durable limits. These primitives are used before any model or tool orchestration starts.

## Read first

1. `event_log.py` — JSONL events and secret redaction.
2. `file_lock.py` — Cross-process file lock.
3. `hardening.py` — Capability requests, daily token ledger, run checkpoints.
4. `process_runner.py` — Bounded subprocess runner.
5. `provider_calls.py` — Optional campaign API-attempt cap.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `event_log.py` | JSONL events and secret redaction | `EventLogger, SecretRedactor` |
| `file_lock.py` | Cross-process file lock | `locked_file` |
| `hardening.py` | Capability requests, daily token ledger, run checkpoints | `CapabilityRequests, DailyTokenLedger, RunCheckpoint` |
| `process_runner.py` | Bounded subprocess runner | `run_process` |
| `provider_calls.py` | Optional campaign API-attempt cap | `reserve_provider_call` |

## How it works

EventLogger redacts and appends events. DailyTokenLedger and RunCheckpoint use locked state; run_process bounds child execution.

## State it touches

Workspace paths: logs/actions.jsonl, logs/egress.jsonl, state/daily_tokens.json, state/checkpoint.json, state/capability_requests.jsonl, state/ab_provider_calls.json.

## Depends on / used by

Depends on the standard library. Used by llm, tools, learning, helper_models, runtime, session, identity, and ui.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/infra -v` in the container.

## Gotchas

Locks protect writes across processes. Root-owned file permissions do not replace the Docker boundary.
