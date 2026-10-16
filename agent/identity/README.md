# Identity

## Purpose

Identity record, first-awakening narrative, and name context. The loop constructs IdentityStore, so this package is below runtime in the actual dependency graph.

## Read first

1. `identity.py` — Identity evidence, explanations, and patch proposals.
2. `name_context.py` — Name interpretation without unsupported claims.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `identity.py` | Identity evidence, explanations, and patch proposals | `IdentityStore` |
| `name_context.py` | Name interpretation without unsupported claims | `resolve_name_context` |

## How it works

IdentityStore reads the record, writes evidence-backed updates, and saves proposed core patches for human review. resolve_name_context supplies bounded name context.

## State it touches

Workspace paths: state/identity.json, state/identity_log.md, state/self_code_explanation.md, state/proposed_patches/.

## Depends on / used by

Depends on infra. Used by runtime, session, and ui.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/identity -v` in the container.

## Gotchas

The /opt/agent/core citations are compatibility links to moved source files. Patch proposals never apply themselves.
