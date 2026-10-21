# SELF

[![CI](https://github.com/FatinShadab/self/actions/workflows/ci.yml/badge.svg)](https://github.com/FatinShadab/self/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

SELF is a self-extending agent whose Docker container is its body. By default,
the `self` service's only host bind mount is `./workspace` at `/home/entity`.

> [!WARNING]
> Experimental local research software. SELF is not a hardened security
> sandbox or a production service. Read [SECURITY.md](SECURITY.md) before
> supplying credentials or granting access to important data.

| Start here | Then explore |
| --- | --- |
| [Quick start](#how-to-run) · [Safe operation](#phase-6-hardening-and-operations) | [Features](#what-can-it-do-right-now) · [Harness map](agent/README.md) |
| [Tests](#how-to-run) · [Contributing](#contributing-and-project-policies) | [Helper-model experiment](docs/helper-model-experiment.md) · [Terminal UI](#phase-7-wake-up-sessions-and-terminal-ui) |

## What is this?

SELF is a curiosity-driven, language-model-powered program. It can observe a
small computer environment, choose actions, use tools, remember verified facts,
and continue across sessions. Its body-like runtime, memory, identity record,
and ability to extend its own tools make it a research experiment. SELF is not
a person, biological life-form, or proof of consciousness.

## What can it do right now?

| Area | Current capability |
| --- | --- |
| **Runtime** | Bounded tasks with shell, file, HTTP, and other tools inside Docker; layered `agent` package and durable recovery checkpoints. |
| **Tools** | Generate Python tools, test and review candidates, then retrieve approved versions. |
| **Learning** | Record memories, verified environment facts, lessons, and session handoffs. |
| **Models** | Configure a base model and eligible helpers for bounded subtasks, critic calls, and reflections; probe availability and report outcomes. |
| **Interface** | Terminal UI with plans, status, model choices, coverage, goals, stop/pause controls, optional voice, and a separate read-only conversation channel. |
| **Identity** | Keep a small, evidence-backed operating record and a file-and-line explanation of its code. |
| **Plugins** | Modular specialization framework for decoupled bodies and skills with static SDK CLI and SHA-256 hash pinning. |
| **Evaluation** | Run host-only calibration and randomized helper-model A/B experiments without exposing hidden tasks to the agent service. |

See the [harness architecture](agent/README.md) for the package map and code
reading order. SELF has broad freedom *inside* its container. Access to host
paths, credentials, money, accounts, and other outside capabilities requires a
human to change the configuration; requests are recorded for review. The
“without restrictions” idea is a research question, not a current capability.

## What is the end goal?

There is no fixed end goal. The project asks what may emerge when an AI system
can act, remember, build tools, reflect, and develop a stable way of interacting
with the world. It provides an observable environment with evidence, logs, and
boundaries; it does not claim SELF is conscious. The direction may become
clearer through use.

## How to run

**Requirements:** Docker with Compose. Tests need no provider key; live runs
need an Ollama Cloud or Anthropic API key. Run these commands from the
repository root in PowerShell.

### 1. Test the checkout

```powershell
.\scripts\run-tests.ps1
```

| Test entry point | What it does |
| --- | --- |
| PowerShell: `.\scripts\run-tests.ps1` | Builds the CI image and runs 116 harness and 11 eval-only tests. |
| Unix: `bash scripts/run-tests.sh` | Runs the same two suites. |

CI invokes the PowerShell script and keeps the image's
`PYTHONPATH=/opt:/opt/agent` so `agent.*` imports resolve.

### 2. Configure a key and start small

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env: set OLLAMA_API_KEY, or ANTHROPIC_API_KEY and ANTHROPIC_MODEL.
docker compose build
docker compose run --rm self --max-iterations 2 --token-budget 20000
```

The command opens the interactive terminal UI. At first wake, SELF asks you to
name it and can record your preferred name.

| In the UI | Result |
| --- | --- |
| `/goal <text>` | Give autonomous work a focus. Ordinary chat instead starts a separate read-only conversation. |
| `/models` · `/coverage` | Inspect configured models, explored directories, and saved tools. |
| `/stop` | End cleanly. If `workspace/STOP` remains, remove it before the next wake or use `/restart`. |

Memory and logs persist under `workspace/`. Review the first session before
raising `--max-iterations`. `--token-budget` limits the application run; it is
not a provider-enforced spending cap.

### 3. Increase the run length when ready

```powershell
docker compose down
docker compose build
docker compose run --rm self --max-iterations 50
```

`down` removes the named Compose service. It preserves `workspace/` and may
leave an earlier one-off `run` container active. Fifty iterations can make many
provider calls; add `--token-budget` if you want a per-run limit.

For plain terminal output instead of the UI:

```powershell
docker compose run --rm self --headless --max-iterations 2 --token-budget 20000
```

> [!CAUTION]
> Only `workspace/` is mounted writable into `self`, but the container has
> network access and executes generated code as root inside Docker. Use a
> limited provider key and keep important host paths unmounted. Read
> [SECURITY.md](SECURITY.md) before supplying sensitive data. Stop with
> `/stop`; for an unresponsive session, see [Start, stop, and wipe](#start-stop-and-wipe).
> Do not run `scripts/verify-phase8.ps1 -WipeWorkspace` on a workspace you
> want to keep.

See [provider and model configuration](#phase-2-run-the-exploration-loop)
for key rotation and model selection. [Wake-up sessions and terminal UI](#phase-7-wake-up-sessions-and-terminal-ui)
has the full command list and service-based startup.

## Phase 2: run the exploration loop

Keep credentials only in the gitignored `.env` file. To run the original
exploration loop directly rather than the wake-up UI:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env and set OLLAMA_API_KEY.
docker compose build
docker compose run --rm --entrypoint python self /opt/agent/loop.py --max-iterations 5 --token-budget 20000
```

| Setting | Purpose |
| --- | --- |
| `OLLAMA_API_KEY` or `ANTHROPIC_API_KEY` | Primary credential. Ollama takes priority if both are present. Key values are never written to logs. |
| `OLLAMA_API_KEYS` or `ANTHROPIC_API_KEYS` | Multiple keys as a comma-separated list or JSON array, such as `OLLAMA_API_KEYS=key_one,key_two`. SELF rotates after quota, rate-limit, or authentication failures. |
| `OLLAMA_MODEL` or `ANTHROPIC_MODEL` | Base model used by the primary loop. |
| `LLM_AVAILABLE_MODELS` | Eligible helpers as a comma-separated list or JSON array, such as `small-model,large-model`. The base model is included automatically. |

`ask_model` can delegate a bounded subtask to an eligible helper. Decision
checkpoints can choose a helper for critic or reflection calls. Ollama helpers
share the same endpoint and key pool; no separate key is needed. The Anthropic
base model uses the same `LLM_AVAILABLE_MODELS` setting. `ask_brain` is a
separate supplementary-provider tool and does not use that list.

### Host-only model calibration (Step 5a)

Use `record_model_assessment` to save optional structured `ratings` for
reasoning, code, instruction following, summarization, and JSON output.
Record judgments **before** running the hidden benchmark. Its definitions and
results stay under host-side `eval/`; only the opt-in `eval` service mounts
them. Stop the agent session first. A shared lock rejects overlapping sessions.

```sh
docker compose stop self
docker compose --profile eval run --rm eval --dry-run
# After checking quota and recording ratings, run the full benchmark explicitly:
docker compose --profile eval run --rm eval
python -m eval.calibrate
```

- `--dry-run` prints the planned provider-call count without calling a model.
- The full run writes results only to `eval/results/`.
- Calibration flags ratings recorded after the benchmark as tainted.

### Randomized helper-model A/B experiment (Steps 5b and 6)

The host-only [experiment guide](docs/helper-model-experiment.md) covers:

1. Probe and rate helpers, then run the hidden benchmark.
2. Build an isolated seed and pilot 12 deterministic tasks.
3. Compare randomized `off` and `on` arms.

`SELF_HELPER_MODELS=off` removes helper tools and decision checkpoints;
`SELF_CRITIC_MODEL` can force one critic in that arm. `scripts/ab-run.ps1`
creates a separate gitignored workspace per run and enforces a cumulative
provider-call cap. A dry-run command never starts an A/B run.

The [learning report](agent/reporting/README.md) and `/models` view now include
helper-model usage and decision evidence. Host-only calibration and A/B summaries
can be supplied to a host-side report; they are never mounted into `self`.

The readable narration streams to the terminal. Structured events append to
`workspace/logs/actions.jsonl`. Create `workspace/STOP` on the host to halt at
the next safe check.

## Phase 3: self-written tools

`create_tool(name, description, code, test_code)` stages Python source, derives
the argument JSON schema from `run(...)` annotations (or a literal `INPUT_SCHEMA`),
and sends the candidate and tests to a separate LLM critic. A flagged or malformed
verdict fails closed. By default, flagged candidates also run shadow tests for
evaluation but are never registered. Approved candidates must pass nonempty
unittest tests within 15 seconds before registration. Test and tool subprocesses run as root, with a
timeout and capped output; provider credentials are omitted from their environment.

| Tool lifecycle | Where or how it is recorded |
| --- | --- |
| Source and tests | `workspace/tools/<name>/tool.py` and `test_tool.py` |
| Metadata | `meta.json` tracks descriptions, schemas, timestamps, versions, source hashes, and pass/fail attempts. |
| Failed candidates | Kept in `attempts/`. Three failures for one name block further retries in that run and add a lesson to `workspace/memory/lessons.jsonl`; a fresh run permits repair. |
| Passing updates | Previous versions move to `history/v0001/`, etc. |

The registry refreshes at startup and before each model step. It offers up to
`--top-k-tools` matching custom schemas alongside base tools and `create_tool`.
Keyword retrieval searches names and descriptions; the `ToolSearch` interface
can be replaced with embedding search. Failed or historical sources are never
retrieved. A direct source edit must pass creation, testing, and review again.
Actor and critic calls share the run token budget.

Run regression tests, then start the service for the tool demo:

```powershell
.\scripts\run-tests.ps1
docker compose build
docker compose up -d
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

> [!NOTE]
> The critic is a quality gate, not a security boundary. Tests and generated
> code run as container root, which can modify container files despite the
> append-only JSONL writer. Token reservations estimate payload and reported
> provider usage; they are not a provider-enforced billing cap. All harness
> LLM calls, including critic calls, count tokens. Shell and custom-code
> traffic can bypass the harness HTTP logger.

## Phase 4: learning across runs

Runtime learning lives under the mounted workspace's `state/` directory:

| File | Purpose |
| --- | --- |
| `memory.jsonl` | Append-only cycle and task learning, retrieved by keyword and tag overlap. |
| `map.json` | Environment facts with `confidence` and `last_verified` on every entry. |
| `self_notes.md` | Compact, bounded summary loaded at the start of normal runs. |

The loop records one memory after every completed cycle and exposes
`update_environment_map` so observed OS, package, CPU, RAM, disk, network, and
limit facts can be recorded with evidence. The harness also establishes a local
baseline and refreshes the available-tool and configured-limit facts. Pass
`--curriculum` without `--task` to select a progressively harder local practice
task from recent successful cycles.

Test and run a short learning cycle:

```powershell
.\scripts\run-tests.ps1
docker compose build
docker compose up -d
docker compose exec self python /opt/agent/loop.py --max-iterations 2 --token-budget 20000 --task "Inspect disk capacity and record verified facts in the environment map."
docker compose exec self python -m agent.report
```

`python -m agent.report` prints learning records, tool registration/failure
events, token use, and the current verified map since its previous invocation.
Use `--no-advance` to inspect without moving its report cursor.

## Phase 5: supplementary model providers

SELF keeps a credential-gated registry in `workspace/state/providers.json`.

| Tool or rule | Behavior |
| --- | --- |
| Provider catalog | Seeds official documentation links for Gemini, Groq, OpenRouter, Mistral, Cerebras, Hugging Face, Cloudflare Workers AI, and local Ollama. Quotas remain unverified until `research_provider` fetches official docs and `record_provider_verification` stores the reviewed result. Account-, model-, or unit-specific unknown limits stay `null`; the router will not deliberately spend an unbounded external tier. |
| `ask_brain` | Supplementary plain-text routing only when a process key and verified numeric RPM and daily-token limits exist. Tracks `state/provider_usage.json`, cools down after HTTP 429, and falls back safely. It does not create accounts or credentials, change accounts, or use a paid tier. The primary structured loop keeps its configured Ollama/Anthropic-compatible client. |
| `request_provider_key` | Writes `state/key_requests.md` with the official key page, host `.env` variable, and documented free-tier note without stopping unrelated work. Add a key yourself to host `.env` and recreate the container; it is not saved in workspace state or logs. |

Test and inspect the registry:

```powershell
.\scripts\run-tests.ps1
docker compose build
docker compose up -d
docker compose exec self python -c "from pathlib import Path; from agent.infra.event_log import EventLogger; from agent.llm.providers.registry import ProviderRegistry; p=ProviderRegistry(Path('/home/entity'), EventLogger('/home/entity/logs/actions.jsonl')); p.initialize(); print(p.providers())"
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

| Boundary or limit | Behavior |
| --- | --- |
| Container | Runs as root inside its own namespace. The sole writable host bind mount is `./workspace` → `/home/entity`; no privileged mode, Docker socket, host network, Windows mount, or extra capability is configured. Harness code lives at `/opt/agent`, durable state at `/home/entity/state`. |
| Automatic ceiling | `SELF_MAX_TOKENS_PER_DAY` is the automatic resource ceiling; its ledger persists across restarts. For daily-only operation, set `SELF_TOKEN_BUDGET=0`, `SELF_MAX_ITERATIONS=0`, and `SELF_MAX_WALL_CLOCK_SECONDS=0`. |
| Recovery | Atomic `state/run_checkpoint.json` records the active task and prior report at cycle boundaries. A run without a new `--task` can resume pending work after interruption. |
| Explicit run limit | `--token-budget` remains available for tests and one-off runs. `SELF_ADAPTIVE_TOKEN_BUDGET` and `SELF_MAX_ADAPTIVE_TOKEN_BUDGET` remain for compatibility; daily-only mode adds no separate per-run token ceiling. |

### Capability and key review

SELF cannot grant itself outside capabilities. Requests for credentials, host
mounts, ports, email, money, accounts, or external services are appended to
`workspace/state/capability_requests.md`; provider-key requests also go to
`workspace/state/key_requests.md`. Review these files and, if approved, edit
host-side `.env` or `docker-compose.yml` yourself and recreate the container.

### Start, stop, and wipe

```powershell
# Build/start
docker compose build
docker compose up -d

# Run an agent cycle
docker compose exec self python /opt/agent/loop.py --max-iterations 2 --token-budget 20000

# Stop the named service and remove its container (preserves workspace state)
docker compose down
```

For a one-off `docker compose run --rm self` session, use `/stop` in the UI.
If it is unresponsive, `docker compose rm --stop --force self` stops Compose
service containers, including one-off containers, then `docker compose down
--remove-orphans` removes the stack. On a Unix shell, `bash kill.sh` performs
these two commands. A forced stop is recorded as a crash; the next wake
reconstructs from the latest checkpoint.

`docker compose down` does not erase `workspace/`. To make a fresh start,
stop all SELF containers first, back up anything you want to keep, then remove
only the contents of `workspace/` from the host. Do not delete the repository.

### Logs and egress

| Log | Contents |
| --- | --- |
| `workspace/logs/actions.jsonl` | Append-only harness events. Known secret values and assignment-like secret strings are redacted before log writes and tool results. |
| `workspace/state/egress.jsonl` | Harness HTTP/LLM/provider egress: timestamp, domain, method, path, and count. No keys, query strings, or headers. `python -m agent.report` shows per-domain and daily totals. |

Because SELF intentionally permits unrestricted root shell/custom-tool commands
inside its container, traffic initiated directly by arbitrary shell commands or
generated code cannot be transparently observed by this Python harness. Use the
harness HTTP/provider tools for auditable egress; comprehensive enforcement or
capture would require a network proxy/firewall at the container edge, which is
not configured by this project.

## Phase 7: wake-up sessions and terminal UI

The container wakes into `python -m agent.wake`. The Textual interface has:

| Pane | Shows |
| --- | --- |
| Conversation | Human messages, cycle summaries, background reflections, and read-only conversation replies. It does not force-scroll while you review older answers. |
| Plan and live work | Plans, commands, tool steps, terminal commands, and streamed output. |
| Presence and status | Identity, activity, session, usage, and container state. |

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

| Command group | Commands |
| --- | --- |
| Session | `/pause`, `/resume`, `/stop`, `/plan`, `/journal`, `/budget` |
| Explore | `/tools`, `/coverage`, `/back`, `/requests`, `/memory <query>`, `/models` |
| Direct work | `/goal <text>` |
| Interface | `/typing on\|off`, `/voice on\|off`, `/listen` |

- **Chat:** Ordinary text opens an independent, bounded, read-only conversation
  immediately. It shares the daily token ledger but does not wait for the
  autonomous cycle or enter its inbox. Use `/goal <text>` to change autonomous
  work. `/stop` writes `workspace/STOP`; remove it before a later wake.
- **Feedback:** Bubbles are labeled `SELF` or `YOU`. Agent text has a short
  typing reveal and an animated ASCII activity indicator; `/typing` controls
  the effect.
- **Voice:** Off by default. Native Windows uses System.Speech, preferring the
  first installed female voice. Linux can use `espeak` or `spd-say`. Docker on
  Windows needs a separate host audio bridge. `/listen` uses the default
  microphone only when the local Windows speech-recognition API is available;
  in Docker it reports that microphone input is unavailable.

`/coverage` opens a scrollable view of distinct directories, visit counts, and
registered tools with descriptions across sessions. A successful `list_dir`
or `read_file` in a file's parent counts as a visit; repeats count again.
Shell paths are excluded because they cannot be identified reliably. Type
`/coverage` again to refresh or `/back` to return.

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

The durable identity is a small operating record. It does not imply feelings,
hidden continuity, or changed model weights.

| Location | Contents |
| --- | --- |
| `state/identity.json` | Optional name, voice, evidence-backed traits, name context, values, interests, and open questions. |
| `state/identity_log.md` | Append-only identity changes, each with a reason and session ID. |
| `self/` | Writable extension layer for prompts, planning logic, tool-selection heuristics, personality notes, and TUI themes. |

When a name is chosen, SELF stores a bounded local reference to its meaning,
origin, common cultural associations, or recognized fictional-character
context. For example, `/rename Toothless` loads *How to Train Your Dragon*
context and uses loyalty, curiosity, playfulness, and protectiveness as soft
style cues. These do not prove personality or ability; unknown names fall back
to observed behavior.

The image-owned harness at `/opt/agent/` contains the loop, budgets, STOP
handling, redaction, logging, provider/key handling, and capability requests.
Docker keeps compatibility entry points there and source citations under
`/opt/agent/core/`, then makes the tree root-owned and read-only. Ordinary
`write_file` attempts to change it are rejected. The agent can instead submit
`propose_core_patch`: a diff and reasoning saved at
`workspace/state/proposed_patches/` for human review, never automatic application.

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

## Plugins

SELF features a modular specialization plugin system that decouples the reusable core agent from specialized bodies (senses and actions) and skills (tools and goal seeds).

- **[Plugin Overview](docs/plugins/overview.md)** — What plugins are, how they differ from ad-hoc tools, and plugin classes (`body`, `skill`, `both`).
- **[Manifest Reference](docs/plugins/manifest-reference.md)** — Complete schema specification for `plugin.json` and core API compatibility ranges.
- **[Authoring Guide](docs/plugins/authoring-guide.md)** — Step-by-step tutorial for scaffolding, implementing, and validating plugins using the Plugin SDK CLI.
- **[Permissions and Risk](docs/plugins/permissions-and-risk.md)** — Risk levels (L0–L3), reversibility rules, and human governance via `/config/permissions.json`.
- **[Lifecycle and Hash Pinning](docs/plugins/lifecycle.md)** — Dynamic plug/unplug, cycle boundary synchronization, SHA-256 hash pinning, and version upgrades.
- **[Testing and Verification](docs/plugins/testing.md)** — Unit testing, simulation testing, and scenario verification.

### Plugin SDK CLI

The SDK includes a static CLI for developer workflows:

```bash
# Scaffold a new plugin skeleton from the built-in template
python -m agent.plugins new <name>

# Statically validate a plugin manifest and structure without executing code
python -m agent.plugins validate plugins/<name>

# List discovered plugins, enablement status, and SHA-256 hash pinning
python -m agent.plugins list

# Check compatibility of all plugins against the current core API version
python -m agent.plugins check
```

## Contributing and project policies

The [contributing guide](CONTRIBUTING.md) documents Python docstrings based
on PEP 257. Run `python scripts/check_docstrings.py` to audit public module,
class, and function documentation. The shared test script above runs both
offline suites; live provider experiments are opt-in and documented in the
[helper-model experiment guide](docs/helper-model-experiment.md).

- [Contributing guide](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security policy](SECURITY.md)
- [Support](SUPPORT.md)
- [Changelog](CHANGELOG.md)

Bug reports and feature requests can be opened through the repository's GitHub
issue templates. Please remove credentials and generated runtime state before
sharing logs. Contributions are released under the [MIT License](LICENSE).
