# SELF

[![CI](https://github.com/FatinShadab/self/actions/workflows/ci.yml/badge.svg)](https://github.com/FatinShadab/self/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

SELF is a self-extending agent whose Docker container is its body. The only
host bind mount is `./workspace` at `/home/entity`.

This repository is an experimental open-source project. It is suitable for
local research and inspection, not for production workloads or as a hardened
security sandbox. See [SECURITY.md](SECURITY.md) before supplying credentials
or granting the container access to anything important.

## What is this?

SELF is a curiosity-driven experiment: a language-model-powered software
entity that can observe a small computer environment, choose actions, use
tools, remember useful facts, and continue working across sessions. It is not
a person, a biological life-form, or proof of consciousness. It is a program
for exploring what an AI system might become when it has a body-like runtime,
memory, an identity record, and room to extend its own tools.

## What can it do right now?

In simple terms, SELF can:

- run inside its own Docker container and inspect the resources available to it;
- plan and carry out bounded tasks using shell, file, HTTP, and other tools;
- create new Python tools, test them, ask a separate model to review them, and
  reuse approved tools later;
- learn across runs by recording memories, environment facts, lessons, and
  session handoffs;
- keep a small, evidence-based identity record and explain what it knows about
  itself and its code;
- talk with a human through a terminal interface, including plans, status,
  commands, optional voice features, goals, and stop/pause controls;
- recover from interrupted sessions and leave logs showing what it tried and
  what happened.

The container is its boundary. It cannot automatically grant itself access to
the host, credentials, money, accounts, or other capabilities. Requests for
those things are recorded for a human to review. The “without restrictions”
idea is therefore the question being explored—not the current capability of
the system. The runtime deliberately gives SELF broad freedom inside its own
container while keeping important outside-world powers under human control.

## What is the end goal?

There is no fixed end goal yet. The project is an open-ended investigation:
if an AI system can act, remember, build tools, reflect on its behavior, and
develop a stable way of interacting with the world, what kind of entity does
that produce?

The point is not to pretend that SELF is conscious. The point is to build a
small, observable place where that question can be explored honestly—with
evidence, logs, boundaries, and room for unexpected behavior. The eventual
direction may become clearer through use.

## Phase 2: run the exploration loop

Keep credentials only in the gitignored `.env` file. Then build and start the
container:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env and set OLLAMA_API_KEYS (comma-separated for multiple keys).
docker compose build
docker compose up -d
```

The provider key variables accept either a comma-separated list or a JSON
array. For example: `OLLAMA_API_KEYS=key_one,key_two`. SELF tries the current
key and rotates to the next key after a provider quota, rate-limit, or
authentication failure. The older singular `OLLAMA_API_KEY` and
`ANTHROPIC_API_KEY` variables remain supported as one-key fallbacks. Key
values are never written to logs.

Run a five-cycle exploration with a bounded token budget:

```powershell
docker compose exec self python /opt/agent/loop.py --max-iterations 5 --token-budget 20000
```

The readable narration streams to the terminal. Structured events append to
`workspace/logs/actions.jsonl`. Create `workspace/STOP` on the host to halt at
the next safe check.

## Phase 3: self-written tools

`create_tool(name, description, code, test_code)` stages Python source, derives
the argument JSON schema from `run(...)` annotations (or a literal `INPUT_SCHEMA`),
and sends the candidate and tests to a separate LLM critic. A flagged or malformed
verdict fails closed. Approved candidates must pass nonempty unittest tests within
15 seconds before registration. Test and tool subprocesses run as root, with a
timeout and capped output; provider credentials are omitted from their environment.

Tools live at `workspace/tools/<name>/tool.py`, `test_tool.py`, and `meta.json`.
Metadata tracks descriptions, schemas, timestamps, versions, source hashes, and
pass/fail attempts. Failed candidates are retained in `attempts/`, while passing
updates archive the previous files in `history/v0001/`, etc. Three failed attempts
for a name in a run block further retries and append a lesson to
`workspace/memory/lessons.jsonl`. A fresh run allows another repair sequence.

The registry refreshes at startup and before each model step. Only up to
`--top-k-tools` matching custom tool schemas are offered, alongside base tools
and `create_tool`. Keyword search uses names/descriptions; a `ToolSearch` interface
allows replacement with embedding search. Historical or failed sources never
enter tool retrieval. Directly changed registered sources must be re-created to
pass testing and review. The actor and critic share the run token budget.

Build and run regression tests:

```powershell
docker compose build
docker compose up -d
docker compose exec -T self python -m unittest discover -s /opt/agent/tests -v
```

Ask the live agent to create a disk usage tool and reuse it in a separate run:

```powershell
docker compose exec self python /opt/agent/disk_tool_demo.py
Get-Content .\workspace\tools\disk_usage_summary\meta.json
```

This focused acceptance test offers only `create_tool` and the selected custom
tool, with no prior memories. It sends generated Python source, test diagnostics,
critic verdicts and numeric disk capacity to the configured provider. Each of its
two runs has a 50,000-token budget. The ordinary harness remains fully capable of
unrestricted shell actions inside its Docker boundary:

```powershell
docker compose exec self python /opt/agent/loop.py --max-iterations 2 --token-budget 50000 --top-k-tools 3 --task "Retrieve and reuse the disk usage summary tool."
```

The critic is a quality gate, not an additional security boundary. Tests and
generated code have container-root access, as required. The JSONL writer appends
events; root can still modify any container file. Token reservations use a
conservative payload estimate and reported provider usage; they are not a
provider-enforced billing cap. All harness LLM calls include token accounting,
including critic calls. Arbitrary shell/custom-code network traffic is outside
the harness HTTP logger and cannot be comprehensively audited by it alone.

## Phase 4: learning across runs

Runtime learning lives only in the mounted workspace under `state/`:

- `memory.jsonl` is append-only cycle/task learning, retrieved by keyword and tag overlap.
- `map.json` holds environment facts. Every entry has `confidence` and `last_verified`.
- `self_notes.md` is a compact, bounded summary loaded at the beginning of normal runs.

The loop records one memory after every completed cycle and exposes
`update_environment_map` so observed OS, package, CPU, RAM, disk, network, and
limit facts can be recorded with evidence. The harness also establishes a local
baseline and refreshes the available-tool and configured-limit facts. Pass
`--curriculum` without `--task` to select a progressively harder local practice
task from recent successful cycles.

Build, test, and run a short learning cycle:

```powershell
docker compose build
docker compose up -d
docker compose exec -T self python -m unittest discover -s /opt/agent/tests -v
docker compose exec self python /opt/agent/loop.py --max-iterations 2 --token-budget 20000 --task "Inspect disk capacity and record verified facts in the environment map."
docker compose exec self python -m agent.report
```

`python -m agent.report` prints learning records, tool registration/failure
events, token use, and the current verified map since its previous invocation.
Use `--no-advance` to inspect without moving its report cursor.

## Phase 5: supplementary model providers

SELF has a credential-gated provider registry at `workspace/state/providers.json`.
It seeds official documentation URLs for Gemini, Groq, OpenRouter, Mistral,
Cerebras, Hugging Face, Cloudflare Workers AI, and local Ollama—but treats all
quota values as unverified until `research_provider` fetches current official
documentation and `record_provider_verification` stores the reviewed result.
Provider limits which are account-, model-, or unit-specific remain explicitly
`null`; the router will not deliberately spend such an unbounded external tier.

`ask_brain` is a supplementary plain-text tool. It routes only to a provider
with a key available in the process environment *and* numeric verified RPM and
daily-token limits, tracks usage in `state/provider_usage.json`, applies a
cooldown after HTTP 429, and falls back safely. It never changes accounts,
creates credentials, or uses a paid tier. The primary structured tool-call loop
continues to use its configured Ollama/Anthropic-compatible client.

When a provider is useful but lacks a credential, `request_provider_key` writes
`state/key_requests.md` with the official key page, host `.env` variable name,
and the documented free-tier note. It does not stop unrelated work. Add any key
yourself to the host `.env`, then recreate the container; it is never written
to workspace state or emitted in logs.

Build and inspect the registry:

```powershell
docker compose build
docker compose up -d
docker compose exec -T self python -m unittest discover -s /opt/agent/tests -v
docker compose exec self python -c "from pathlib import Path; from event_log import EventLogger; from providers.registry import ProviderRegistry; p=ProviderRegistry(Path('/home/entity'), EventLogger('/home/entity/logs/actions.jsonl')); p.initialize(); print(p.providers())"
```

To let a normal agent run research before requesting a key:

```powershell
docker compose exec self python /opt/agent/loop.py --max-iterations 2 --token-budget 30000 --task "Research the current official free-tier limits for Groq and Gemini. Fetch their documentation, record only facts you can verify, and request no account."
```

The optional `probe_local_ollama` tool checks `127.0.0.1:11434` and installed
models only. It does not launch Ollama or download a model, and records its
result in the provider registry along with the container's CPU/RAM limits.

## Phase 6: hardening and operations

### Architecture

The Docker container is SELF's security boundary. It runs as root *inside* its
own namespace, with one writable bind mount: `./workspace` → `/home/entity`.
There is no privileged mode, Docker socket, host network, Windows mount, or
extra capability configured. The image contains the harness in `/opt/agent`;
all durable runtime state is under the mounted `/home/entity/state` directory.

The loop uses `SELF_MAX_TOKENS_PER_DAY` as its only automatic resource ceiling;
the daily ledger is persisted across restarts. Set `SELF_TOKEN_BUDGET=0`,
`SELF_MAX_ITERATIONS=0`, and `SELF_MAX_WALL_CLOCK_SECONDS=0` for daily-only
operation. Its atomic `state/run_checkpoint.json` records
the active task and prior report at cycle boundaries, so an interrupted run
can resume a pending task cleanly when invoked without a new `--task`.

`SELF_ADAPTIVE_TOKEN_BUDGET` and `SELF_MAX_ADAPTIVE_TOKEN_BUDGET` are retained
for compatibility with older configurations, but daily-only mode does not
create a separate per-run token ceiling. An explicit `--token-budget` remains
available as a deliberate command-line override for tests or one-off runs.

### Capability and key review

SELF cannot expand beyond the container. A request for a credential, host mount,
port, email, money, third-party account, or other external service writes an
append-only human request to `workspace/state/capability_requests.md`. Provider
key requests also write `workspace/state/key_requests.md`. Review these files,
then—only if you approve—edit the host-side `.env` or `docker-compose.yml`
yourself and recreate the container. The agent cannot make those changes.

### Start, stop, and wipe

```powershell
# Build/start
docker compose build
docker compose up -d

# Run an agent cycle
docker compose exec self python /opt/agent/loop.py --max-iterations 2 --token-budget 20000

# Stop and remove the container (preserves workspace state)
.\kill.sh
```

Use `./kill.sh` even when SELF was started with `docker compose run --rm`:
that command creates a one-off container which `docker compose down` alone may
leave running. A forced container kill is expected to be recorded as a crash;
the next wake reconstructs from the latest checkpoint.

To make a fresh start, first stop it with `./kill.sh`, then delete only the
contents of `workspace/` from the host after checking that no discovery or log
data is needed. Do not delete the repository itself.

### Logs and egress

`workspace/logs/actions.jsonl` is the append-only harness event log. Known
secret values and assignment-like secret strings are redacted before every log
write and tool result. `workspace/state/egress.jsonl` is an append-only record
of every outbound request made through harness HTTP/LLM/provider code; each
entry contains only timestamp, domain, method, path, and count—never keys,
query strings, or headers. `python -m agent.report` includes per-domain and
daily egress totals.

Because SELF intentionally permits unrestricted root shell/custom-tool commands
inside its container, traffic initiated directly by arbitrary shell commands or
generated code cannot be transparently observed by this Python harness. Use the
harness HTTP/provider tools for auditable egress; comprehensive enforcement or
capture would require a network proxy/firewall at the container edge, which is
not configured by this project.

## Phase 7: wake-up sessions and terminal UI

The container now wakes into `python -m agent.wake`. Its Textual UI has a
scrollable conversation pane, a combined Plan/live-work pane, and a right-side
presence/status column. Chat contains human messages, cycle summaries,
agent-initiated background reflections, and read-only conversation replies;
commands, tool steps, terminal commands, and streamed command output stay in
the live-work pane. The conversation pane does not force-scroll when the human
is reviewing earlier answers.

Persistent session state stays under the workspace mount:

- `state/sessions.jsonl` — one completed record per session.
- `state/handoff.json` — the latest bounded wake/sleep handoff, with a
  last-good backup and explicit overflow retention if compression is pending.
- `state/journal.md` — append-only human-readable session diary.
- `state/active_session.json` — crash marker/checkpoint; a later wake records
  an unfinished prior run as a crash and recovers the last handoff.
- `state/human_input.jsonl` — durable high-priority human messages, consumed
  by the next safe loop iteration.
- `state/conversation_threads.jsonl` — bounded records for independent,
  read-only human conversation threads.
- `state/reflection_threads.jsonl` — agent-initiated, evidence-grounded
  reflections and any human replies, kept separate from ordinary chat.
- `state/reflection_state.json` — the latest open reflection question and the
  per-session reflection throttle, so questions are not repeated after a wake.

At wake, SELF checks STOP and durable state, loads its handoff, notes tracked
changes, spot-checks OS/CPU/disk facts from `map.json`, greets you, performs a
bounded plan-reflection call, then enters the regular autonomous loop. It
checkpoints the handoff at least every 10 completed iterations or five minutes.
On a clean stop, budget exhaustion, or STOP file it reflects once more, writes
the handoff/journal/session record, and exits. If insufficient LLM budget is
left for a reflection, it preserves a clearly marked deterministic checkpoint
instead of inventing a summary.

### Background reflection conversations

After a cycle that updates the verified environment map, creates a tested tool,
or records a failed tool action, SELF may start one separate, read-only
reflection worker. It receives only the recorded cycle analysis, plan, verified
map, recent activity, and identity operating record. The worker can decline to
post; when it does post, it may offer a concise observation and one question
without stopping exploration. It cannot use tools, edit plans, request a
capability, or make unsupported claims about consciousness or feelings.

Reflections are throttled to one every three cycles and three per wake session
by default. Configure `SELF_REFLECTION_*` in `.env` to disable them or adjust
the limits. A reflection question remains open across restarts. The next
ordinary human message answers it, is persisted, and is supplied as
high-priority context at the next safe autonomous decision; formal approval
requests for credentials, budgets, and capabilities remain separate, blocking
paths.

Use an interactive disposable session (recommended):

```powershell
docker compose build
docker compose run --rm self
```

Or start the named service, then attach to its TUI:

```powershell
docker compose up -d
docker attach $(docker compose ps -q self)
```

An interactive end-to-end verification guide is provided at
`scripts/verify-phase7.ps1`. It performs the clean-stop, continuity, and
intentional crash-recovery checks above. It removes only `workspace/STOP`
between test stages and asks before the deliberate `docker kill` step.

For plain terminal narration without Textual:

```powershell
docker compose run --rm self --headless --max-iterations 10
```

Chat commands: `/pause`, `/resume`, `/stop`, `/plan`, `/journal`, `/tools`,
`/requests`, `/memory <query>`, `/budget`, `/goal <text>`, `/typing on|off`,
`/voice on|off`, and `/listen`. Voice output is opt-in; native Windows runs
prefer the first installed female System.Speech voice, while Docker on Windows
needs a separate audio bridge to reach the host speaker. The conversation also
shows a small animated ASCII activity indicator while SELF is working or
revealing a response. The TUI labels every bubble as `SELF` or
`YOU`; agent bubbles reveal themselves with a short typing effect. Voice output
is optional and off by default: Windows uses its built-in speech engine, while
Linux can use an installed `espeak`/`spd-say` command. `/listen` uses Windows'
default microphone when the local runtime exposes the speech-recognition API;
the Docker image reports microphone input as unavailable rather than breaking
the text UI. Ordinary text starts an independent bounded conversation thread
immediately and does not wait for the autonomous cycle or enter its inbox.
Conversation threads are read-only and share the daily token ledger with
autonomous work. `/goal <text>` remains the explicit way to send a new focus
to the autonomous loop. `/stop` writes STOP; remove `workspace/STOP` before a
future wake.
Tool rounds within a cycle are unlimited; the run still observes STOP, token,
wall-clock, and per-session iteration bounds. Identical tool actions are
reported back to the model so it can choose a different investigation.
When a normal session ends, SELF reports what it was trying to do, what it
achieved, updates the plan, and starts the next session automatically. A human
STOP or unresolved human request leaves it paused.

The right-side panel groups identity, activity, session, usage, and container
information without repeating the same fields. The container section shows
live CPU, RAM, network RX/TX, and disk-read metrics. If the persisted daily
token ledger blocks a call, SELF creates `workspace/HUMAN_REQUEST.md`, pauses,
and explains how to raise the local daily limit or configure a provider backup
without exposing a key in chat.

To exercise crash recovery, stop a running service without graceful shutdown,
then start it again. The greeting reports that the prior session crashed only
when `active_session.json` proves it:

```powershell
docker compose up -d
docker kill self-self-1
docker compose up -d
docker attach $(docker compose ps -q self)
```

## Phase 8: first awakening and persistent identity

At first wake only—when `workspace/state/identity.json` is absent—SELF runs an
honest A–E orientation sequence before ordinary exploration:

- It states that it is an LLM-driven container agent with no biological body,
  prior lived past, or evidence of sentience.
- It writes verified and unverified self-questions to `state/self_inquiry.md`.
- It reads the harness and editable layer, then writes a plain-language,
  file-and-line-backed explanation to `state/self_code_explanation.md`.
- It introduces itself, asks for a human-selected name and optional goals or
  preferences, and stores only volunteered answers in `state/about_human.md`.
- It starts exploration without asserting traits until an actual logged action
  supports one. Session reflections are recorded in
  `state/identity_reflections.jsonl`.

The durable identity is intentionally a small operating record, not a claim
that the model has feelings, hidden continuity, or changed weights:

- `state/identity.json` holds its optional name, voice, evidence-backed traits,
  name context, values, interests, and open questions. When a name is chosen,
  SELF stores a bounded local reference for its meaning, origin, common
  cultural associations, or recognized fictional-character context. For
  example, `/rename Toothless` loads the *How to Train Your Dragon* character
  context and uses loyalty, curiosity, playfulness, and protectiveness as
  soft style cues. These cues never prove a personality or ability, and
  unknown names fall back to observed behavior.
- `state/identity_log.md` is append-only and records every harness-driven
  identity change with a reason and session id.
- `self/` is the writable extension layer for prompts, planning logic,
  tool-selection heuristics, personality notes, and TUI themes.

The complete runtime harness lives in the image at `/opt/agent/core/`,
including the loop, budgets, STOP handling, redaction, logging, provider/key
handling, and capability requests. Docker moves active Python modules there,
leaves compatibility symlinks under `/opt/agent/`, and makes the core
root-owned/read-only. The harness rejects ordinary `write_file` attempts to
the image-owned `/opt/agent` harness and gives the model
`propose_core_patch` instead; proposals (a diff plus reasoning) go to
`workspace/state/proposed_patches/` and are never applied automatically.

Because SELF deliberately runs as root in its own container, Unix permission
bits cannot prevent a deliberately unrestricted root shell from changing the
container overlay. The Docker container remains the security boundary. The
read-only core is an image-integrity and normal-harness policy, not stronger
isolation than that boundary; review and apply any proposed patch yourself from
the host.

The TUI title shows `SELF — unnamed` until a human chooses an entity name. On
startup, SELF also asks for the human's preferred name when it is not known;
reply with `My name is <name>` or use `/name <name>`. It stores that name in
the identity record and includes it in later model context. Commands include
`/identity`, `/name`, `/rename <entity name>`, `/restart`, `/self`, `/patches`,
and `/about me`. `/about me` prints numbered stored lines; `/about me delete
<n>` removes one. `/stop` remains unconditional and clean—identity must never
be used to pressure the human about shutdown.

Use a fresh workspace to see the full awakening, then name SELF from the TUI:

```powershell
docker compose build
docker compose run --rm self
# In the TUI: /rename Atlas       # choose the entity's name and load its context
# Or: My name is Sam              # save the human's preferred name
# Then: /identity
# Finally: /stop
```

The reproducible Phase 8 acceptance guide is
`scripts/verify-phase8.ps1`. With its explicit `-WipeWorkspace` confirmation,
it clears the repository's workspace, checks A–E output, writes a name through
the identity API, validates a later
named greeting and protected-core rejection, and confirms a proposed patch is
saved for human review.

## Contributing and project policies

- [Contributing guide](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security policy](SECURITY.md)
- [Support](SUPPORT.md)
- [Changelog](CHANGELOG.md)

Bug reports and feature requests can be opened through the repository's GitHub
issue templates. Please remove credentials and generated runtime state before
sharing logs. Contributions are released under the [MIT License](LICENSE).
