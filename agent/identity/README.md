# Identity

## Purpose

Identity record, first-awakening narrative, and name context. The loop constructs IdentityStore, so this package is below runtime in the actual dependency graph.

## Read first

1. `identity.py` — Identity evidence, explanations, and patch proposals.
2. `name_context.py` — Name interpretation without unsupported claims.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `identity.py` | Identity evidence, explanations, and patch proposals (facade) | `IdentityStore` |
| `name_context.py` | Name interpretation without unsupported claims | `resolve_name_context` |
| `store/constants.py` | Constants and line sanitization | `IDENTITY_MAX_BYTES, NAME_MAX_CHARS, now, clean_line` |
| `store/schema.py` | Identity schema, defaults, and dictionary normalization | `get_default_identity, normalize_identity, sanitize_name_context` |
| `store/first_awakening.py` | First-awakening stages A–E, inquiry, and code explanation | `execute_first_awakening, ensure_editable_layer, write_self_inquiry` |
| `store/human_context.py` | About-human documentation and preferred name persistence | `save_human_name, append_human_answer, read_about_human_text` |
| `store/traits_reflections.py` | Evidence-backed traits, session reflections, compaction | `add_trait_to_identity, reflect_on_session, compact_identity_record` |
| `store/core_proposals.py` | Core patch proposal generation and review list | `save_proposed_core_patch, list_proposed_patches` |
| `store/prompting.py` | Prompt context rendering and terminal UI text | `build_identity_prompt_context, format_self_panel_text` |

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
