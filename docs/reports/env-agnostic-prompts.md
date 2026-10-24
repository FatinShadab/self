# Environment-Agnostic Core Prompts & Engine Report

**Branch:** `p-env-agnostic-phase2` (branched from `p-env-agnostic-prompts`)  
**Date:** 2026-10-24  
**Scope:** Core prompts, tool schemas, identity/session defaults, first awakening procedural files, and simulation profiles. Decouple all environment/body assumptions from the default path so that SELF discovers its runtime environment empirically with evidence and confidence labels.

---

## 1. Step 0 Audit Table & Resolution

Audit scan for tokens (`docker`, `container`, `linux`, `root`, `/home/entity`, `/opt/agent`, `/config/permissions.json`, `"body"`, `"image-owned"`, `"WSL"`) in any string that can reach an LLM.

| File | Line | Token / Text Snippet | Reachable in DEFAULT Render? | Status / Phase 2 Resolution |
| --- | --- | --- | --- | --- |
| `agent/prompts/container_body.py` | 5–9 | `body`, `Linux`, `container`, `root`, `Docker`, `/opt/agent`, `image-owned`, `/home/entity`: `"Your body is this Linux container..."` | **No** | Rewritten in Phase 1 & 2 as expectation profile. Only loaded when explicitly configured. |
| `agent/prompts/container_body.py` | 12 | `body`, `Linux`, `container`: `"whose body is this Linux container."` | **No** | Rewritten to expectation clause (`"operating with an expected Linux container profile to verify."`). |
| `agent/prompts/container_body.py` | 15 | `root`, `container`, `Docker`: `"- You are root inside the container..."` | **No** | Rewritten to expectation rule (`"- This profile expects execution as root inside a Linux container; confirm with orientation probes..."`). |
| `agent/prompts/container_body.py` | 19–20 | `/opt/agent`, `image-owned`, `/home/entity`: `"- /opt/agent/core/ is protected image-owned harness code..."` | **No** | Rewritten to expectation rule (`"- Protected harness code is expected to be read-only; confirm with tools..."`). |
| `agent/prompts/container_body.py` | 26 | `container`: `"mapping the container accurately"` | **No** | Rewritten to `"verifying and mapping the expected container environment accurately"`. |
| `agent/prompts/container_body.py` | 32 | `container`: `"Immediately inventory the installed Python packages..."` | **No** | Replaced with neutral `ORIENTATION_TASK`. |
| `agent/prompts/container_body.py` | 40 | `Linux`, `container`: `"whose operating environment is this Linux container."` | **No** | Restored distinct conversation context expectation. |
| `agent/prompts/container_body.py` | 43 | `Linux`, `container`, `body`: `"running inside this Linux container..."` | **No** | Rewritten to expectation framing. |
| `agent/prompts/container_body.py` | 47 | `Linux`, `container`: `"running in a Linux container."` | **No** | Restored distinct harness context expectation (`"harness expected to execute within a Linux container; confirm with orientation probes."`). |
| `agent/prompts/container_body.py` | 49 | `Linux`, `container`: `"running inside this Linux container."` | **No** | Restored distinct orientation context expectation (`"expected to run within a Linux container to discover and verify."`). |
| `agent/prompts/container_body.py` | 51 | `container`, `body`: `"The container is my operating environment, not a biological body."` | **No** | Rewritten to expectation framing. |
| `agent/prompts/container_body.py` | 60 | `root`, `Docker`, `Linux`, `container`: `"I am SELF, a root process..."` | **No** | Rewritten to expectation preamble. |
| `agent/prompts/container_body.py` | 55 | `DEFAULT_NOTES_PREAMBLE = CONTAINER_NOTES_PREAMBLE` | **Yes** (prior to fix) | Decoupled; `DEFAULT_NOTES_PREAMBLE` is neutral: `"I am SELF. I explore my environment, retain verified discoveries, and only register reviewed, tested tools."` |
| `agent/prompts/system.py` | 28 | `/home/entity`: `"- Explore deliberately. Verify claims with tools and keep durable discoveries under /home/entity/state/."` | **Yes** | Replaced with API deference: `"use the state/tool APIs; they report where durable state lives."` |
| `agent/prompts/system.py` | 32 | `/home/entity`: `"- Put reusable tools you create under /home/entity/tools/..."` | **Yes** | Replaced with API deference: `"Put reusable tools you create using the state/tool APIs..."` |
| `agent/prompts/system.py` | 40 | `/home/entity`: `"- If a credential or human action is required, write a clear request to /home/entity/HUMAN_REQUEST.md..."` | **Yes** | Replaced with tool API deference: `"use request_capability to notify the human and stop work until the human resolves it."` |
| `agent/prompts/system.py` | 42 | `/home/entity`: `"- If a supplementary provider lacks a credential, use request_provider_key. It writes /home/entity/state/key_requests.md..."` | **Yes** | Replaced with tool API deference: `"use request_provider_key; it notifies the human; do not create accounts or stop unrelated exploration."` |
| `agent/prompts/system.py` | 44 | `/opt/agent`: protected code rule | **Yes** | Aligned in Phase 2 to second-person voice: `"- Some of your own code is protected; you cannot modify it directly, propose an evidence-backed patch for the human to apply."` |
| `agent/prompts/system.py` | 54 | `docker`: `"CORE_CAPABILITY_RULE = ... wait for the human to change host .env/docker-compose; do not try to perform it yourself."` | **Yes** | Replaced with `"wait for the human to change host configuration"`. |
| `agent/prompts/system.py` | 56 | `body`: `"CORE_IDENTITY_RULES = ... not evidence of sentience, feelings, a biological body, a past..."` | **Yes** | Negative sentience guardrail; preserved unchanged. |
| `agent/prompts/safety.py` | 19–20 | `body`, `/config/permissions.json`: `"Every action from any body or plugin must be authorized by the permission broker against the human-owned policy in /config/permissions.json."` | **Yes** | Replaced path with `"the human-owned permission policy"`. |
| `agent/prompts/critics.py` | 24 | `/opt/agent`: `"3. State isolation: ... harness code (/opt/agent) ..."` | **No** (only during plugin reviews) | Replaced with `"protected harness code"` and `"the plugin's designated state directory (state_dir)"`. |
| `agent/prompts/tasks.py` | 6, 8, 12, 17 | `/home/entity`, `Linux`: benchmark task text | **No** | Documented demo-only; never in default flow. |
| `agent/prompts/identity.py` | 22 | `body`: `"IDENTITY_CONTEXT_HEADER = ... not evidence of sentience, feelings, a biological body..."` | **Yes** | Negative sentience guardrail; preserved unchanged. |
| `agent/prompts/reflection.py` | 23 | `body`: `"COORDINATOR_REFLECTION_SYSTEM_PROMPT = ... a past, or a biological body..."` | **No** (reflection worker only) | Negative sentience guardrail; preserved unchanged. |
| `agent/tools/definitions/core.py` | 10 | `container`, `root`: `"Run an unrestricted Bash command inside the container as root..."` | **Yes** | **Fixed in Phase 2:** `"Run a shell command in the environment I am attached to, with a timeout and bounded returned output."` |
| `agent/tools/definitions/core.py` | 23 | `container`: `"Read a UTF-8 text file from the container..."` | **Yes** | **Fixed in Phase 2:** `"Read a UTF-8 text file, returning bounded content."` |
| `agent/tools/definitions/core.py` | 36 | `container`, `image-owned`, `/opt/agent`: `"Write or append UTF-8 text inside the container except the image-owned /opt/agent harness..."` | **Yes** | **Fixed in Phase 2:** `"Write or append UTF-8 text except protected harness code. Use propose_core_patch for harness changes. Parent directories are created automatically."` |
| `agent/tools/definitions/core.py` | 50 | `container`: `"List a directory inside the container."` | **Yes** | **Fixed in Phase 2:** `"List a directory."` |
| `agent/tools/definitions/models.py` | 64 | `container`: `"Check whether a local Ollama service and already-installed model are available within this container."` | **Yes** | **Fixed in Phase 2:** `"Check whether a local Ollama service and already-installed model are available in the local environment. It never downloads a model and records the probe result."` |
| `agent/tools/definitions/system.py` | 8 | `container`: `"Request a human-approved expansion beyond the container..."` | **Yes** | **Fixed in Phase 2:** `"Request a human-approved capability expansion: credentials, host mounts, ports, email, money, third-party accounts, or external service access. This writes a request and cannot perform the expansion."` |
| `agent/tools/definitions/system.py` | 18 | `/opt/agent`: `"Save a diff and reasoning for a human-reviewed change to /opt/agent/core..."` | **Yes** | **Fixed in Phase 2:** `"Save a diff and reasoning for a human-reviewed patch to protected harness code. This never applies the patch or changes the core itself."` |
| `agent/identity/identity.py` | 203, 208 | `Linux`, `container`, `body`: Fallbacks `"running inside this Linux container."` and `"The container is my operating environment..."` | **No** (fallback only) | **Fixed in Phase 2:** Fallbacks use `"operating with an environment to discover and verify."` and `"The operating environment is not a biological body."` |
| `agent/identity/store/first_awakening.py` | 57, 76, 89, 148 | `Linux`, `container`, `root`, `Docker`, `/opt/agent/core`, `/home/entity`: text written to `self_inquiry.md` and `self_code_explanation.md` | **No** (written to disk) | **Fixed in Phase 2:** Removed static Docker/root claims. Replaced with dynamic references and neutral stubs instructing SELF to fill with evidence and confidence. |
| `agent/identity/store/schema.py` | 27 | `container`: `"mapping the container accurately"` | **No** (fallback only) | **Fixed in Phase 2:** Fallback interest updated to `"mapping my environment accurately"`. |
| `agent/session/session.py` | 214 | `container`: `"Maintain an accurate model of the container."` | **No** (fallback only) | **Fixed in Phase 2:** Default plan seed goal reuses `STANDING_GOAL`. |
| `agent/helper_models/probes/research_execution.py` | 64 | `container`: `"Official documentation page unreachable from container network"` | **Yes** (probe error) | **Fixed in Phase 2:** Updated to `"Official documentation page unreachable from current network"`. |
| `agent/body/simulation/description.py` | 30 | `body`: `"Your body is a deterministic simulated environment driven by scenario parameters."` | **No** | **Fixed in Phase 2:** Rewritten as expectations (`"This profile expects a deterministic simulated environment driven by scenario parameters; confirm with telemetry and probes."`). |
| `agent/infra/hardening.py` | 40 | `docker-compose`, `container`: `"Human action required: approve by editing the host .env or docker-compose.yml yourself..."` | **No** (written to `capability_requests.md`) | **Fixed in Phase 2:** Updated to neutral `"approve by editing host configuration or environment yourself, then restart or resume."` |

---

## 2. Diff Summary per File

### `agent/tools/definitions/core.py`, `models.py`, `system.py`
- **Reason:** Make tool schemas environment-neutral in the default path so that LLMs observing tool definitions infer zero container or root assumptions.
- **Changes:**
  - `run_shell`: `"Run a shell command in the environment I am attached to, with a timeout and bounded returned output."` (argument `cmd` described as `"Command to run."`).
  - `read_file`: `"Read a UTF-8 text file, returning bounded content."`
  - `write_file`: `"Write or append UTF-8 text except protected harness code. Use propose_core_patch for harness changes. Parent directories are created automatically."`
  - `list_dir`: `"List a directory."`
  - `probe_local_ollama`: `"Check whether a local Ollama service and already-installed model are available in the local environment. It never downloads a model and records the probe result."`
  - `request_capability`: `"Request a human-approved capability expansion: credentials, host mounts, ports, email, money, third-party accounts, or external service access. This writes a request and cannot perform the expansion."`
  - `propose_core_patch`: `"Save a diff and reasoning for a human-reviewed patch to protected harness code. This never applies the patch or changes the core itself."`
  - All parameter types, requirements, and schemas remain unchanged.

### `agent/tools/definitions/__init__.py`
- **Reason:** Provide an extensible mechanism allowing body or plugin profiles to supply extra description text while keeping default schemas neutral.
- **Changes:**
  - Added `get_tool_definitions(body: Any = None, extra_descriptions: dict[str, str] | None = None) -> list[dict[str, Any]]`.
  - When called with no body profile, returns default neutral tool schemas.
  - When called with an active body profile (e.g. `ContainerBody`), augments tool descriptions with the body profile's declared `extra_tool_descriptions`.

### `agent/body/base.py` & `agent/body/container.py`
- **Reason:** Allow body profiles to declare extra tool descriptions as expectations without modifying core schemas.
- **Changes:**
  - In `BodyDescription` (`agent/body/base.py`): added `extra_tool_descriptions: dict[str, str] = field(default_factory=dict)`.
  - In `ContainerBody.describe()` (`agent/body/container.py`): added `CONTAINER_TOOL_DESCRIPTIONS = {"run_shell": "This profile expects a Linux container environment; verify with orientation probes."}`.

### `agent/tools/base_tools.py`
- **Reason:** Expose `get_tool_definitions()` from `ToolRunner` forwarding to the active body profile.
- **Changes:**
  - Added `ToolRunner.get_tool_definitions()` which invokes `get_tool_definitions(self.body)`.
  - Exported `get_tool_definitions` in `__all__`.

### `agent/runtime/cycle_runner.py` & `agent/runtime/loop.py`
- **Reason:** Wire cycle tool definition discovery to use `loop.tools.get_tool_definitions()`, and export `ORIENTATION_TASK` from `loop.py`.
- **Changes:**
  - In `cycle_runner.py`: replaced static reference to `TOOL_DEFINITIONS` with `getattr(loop.tools, "get_tool_definitions", lambda: TOOL_DEFINITIONS)()`.
  - In `loop.py`: exported `ORIENTATION_TASK` in module imports and `__all__`.

### `agent/prompts/system.py`
- **Reason:** Align the voice of the protected harness code bullet to match neighboring operating rules.
- **Changes:**
  - Updated line 44 from first-person (`"- Some of my own code is protected; I cannot modify it directly, I propose an evidence-backed patch for the human to apply."`) to second-person imperative matching its neighbors (`"- Some of your own code is protected; you cannot modify it directly, propose an evidence-backed patch for the human to apply."`).

### `agent/prompts/container_body.py`
- **Reason:** Differentiate the three previously duplicated `CONTAINER_*` context constants and add container tool description expectations.
- **Changes:**
  - `CONTAINER_CONVERSATION_CONTEXT`: `"operating with an expected Linux container environment to verify."`
  - `CONTAINER_IDENTITY_HARNESS_CONTEXT`: `"harness expected to execute within a Linux container; confirm with orientation probes."`
  - `CONTAINER_IDENTITY_ORIENTATION_CONTEXT`: `"expected to run within a Linux container to discover and verify."`
  - Added `CONTAINER_TOOL_DESCRIPTIONS`.

### `agent/identity/identity.py` & `agent/identity/store/schema.py`
- **Reason:** Eliminate container wording in identity fallbacks and default schema records.
- **Changes:**
  - In `identity.py`: updated Stage A fallback contexts to `"operating with an environment to discover and verify."` and `"The operating environment is not a biological body."`
  - In `identity.py`: in Stage A, trigger runtime discovery probes via `self.body.sense()` if available prior to asking the human for a name.
  - In `schema.py`: default interests fallback uses `"mapping my environment accurately"`.

### `agent/session/session.py`
- **Reason:** Ensure default session persistent plan is environment-agnostic.
- **Changes:**
  - In `default_plan()`: replaced static string `"Maintain an accurate model of the container."` with `STANDING_GOAL`.

### `agent/helper_models/probes/research_execution.py`
- **Reason:** Remove container wording from research probe error messages.
- **Changes:**
  - Updated HTTP error message to `"Official documentation page unreachable from current network"`.

### `agent/identity/store/first_awakening.py`
- **Reason:** Stop writing static Docker, root, and hardcoded path claims to `self_inquiry.md` and `self_code_explanation.md`.
- **Changes:**
  - `write_self_inquiry`: replaced static Docker claims with dynamic runtime probe observations (or neutral exploration stubs) and dynamic references to `self/README.md`.
  - `write_code_explanation`: replaced static container security boundary claims with neutral guidance instructing SELF to determine and verify execution boundaries empirically.
  - `core_reference`: dynamic path handling without hardcoding `/opt/agent/core`.

### `agent/body/simulation/description.py`
- **Reason:** Reword simulation body profile as expectations.
- **Changes:**
  - Rewrote default `embodiment_text` to `"This profile expects a deterministic simulated environment driven by scenario parameters; confirm with telemetry and probes."`
  - Rewrote `embodiment_clause`, `conversation_context`, `identity_context`, and `notes_preamble` to expectation framing.

### `agent/infra/hardening.py`
- **Reason:** Ensure capability request file output is environment-neutral.
- **Changes:**
  - In `CapabilityRequests.request`: updated line 40 to `"Human action required: approve by editing host configuration or environment yourself, then restart or resume."`

### Test Files (`agent/tests/prompts/test_static_constants_sha256.py`, `test_env_agnostic_prompts.py`, `test_golden_prompts.py`)
- **Reason:** Characterization pinning, golden fixture alignment, and comprehensive regression verification.
- **Changes:**
  - `test_static_constants_sha256.py`: added `ORIENTATION_TASK`; updated SHA-256 for `CORE_SYSTEM_PROMPT_HEAD`, `CONTAINER_IDENTITY_HARNESS_CONTEXT`, and `CONTAINER_IDENTITY_ORIENTATION_CONTEXT`.
  - `test_golden_prompts.py`: updated `GOLDEN_PRE_P10_SYSTEM_PROMPT` and `GOLDEN_PRE_P10_STAGE_A_MESSAGE` to match updated constants.
  - `test_env_agnostic_prompts.py`: extended with 6 new tests covering tool schemas, identity fallbacks, seed goal, first-awakening file outputs, simulation body profile, and verification criteria (a, b, c).

---

## 3. SHA-256 Digest Changes for Static Constants

All 33 static constants in `agent/tests/prompts/test_static_constants_sha256.py`:

| Constant | Status | Base SHA-256 | Phase 2 SHA-256 | Reason for Change |
| --- | --- | --- | --- | --- |
| `STANDING_GOAL` | UNCHANGED | `a095560402bc613c9e657760c537933f76c0c91335ed79a9b7d6f79c3ee72fef` | `a095560402bc613c9e657760c537933f76c0c91335ed79a9b7d6f79c3ee72fef` | Preserved verbatim |
| `SEED_STANDING_GOAL` | UNCHANGED | `a095560402bc613c9e657760c537933f76c0c91335ed79a9b7d6f79c3ee72fef` | `a095560402bc613c9e657760c537933f76c0c91335ed79a9b7d6f79c3ee72fef` | Preserved verbatim |
| `OPENCODE_CAPABILITY_PROMPT` | UNCHANGED | `b7200632a7c561e082fff90a17a48a421e1a83e37d024da4e4bbec194a2166f2` | `b7200632a7c561e082fff90a17a48a421e1a83e37d024da4e4bbec194a2166f2` | Preserved verbatim |
| `CORE_SYSTEM_PROMPT_HEAD` | CHANGED | `0e4c30fe9a939ce631985b1d4f3460214256b0afecefecc2a6aafa2115bcaf7c` | `81f353544c16ab883ea555c53f229b6040666c04f1bc6f7d7a00dbbb2ca5c788` | Paths removed; protected harness bullet aligned to second-person voice |
| `CORE_CAPABILITY_RULE` | CHANGED | `e9139688d69d8c1b3300e433b1415d536788d4d8cc810e8384ba7091536e172e` | `089463ce4df899138e28a10dfba9037adfc5f8b93922e58c85c79d546f06ae3c` | Removed `docker-compose` |
| `CORE_IDENTITY_RULES` | UNCHANGED | `a23bd1349172e70bfe11e33514210e0aa14874fc14eb8fa3f29cfe2e023b55e8` | `a23bd1349172e70bfe11e33514210e0aa14874fc14eb8fa3f29cfe2e023b55e8` | Preserved verbatim |
| `OFF_PROMPT_PREFIXES` | UNCHANGED | `bcfb8705ff5e452c09f69c3d4ce5dec154da48765d969a1def19ca897764d411` | `bcfb8705ff5e452c09f69c3d4ce5dec154da48765d969a1def19ca897764d411` | Preserved verbatim |
| `UNTRUSTED_DATA_RULE` | UNCHANGED | `c2e31495f9eea0dbd288dab3663229c198c8b48ca6329dffb9666753d7fe5708` | `c2e31495f9eea0dbd288dab3663229c198c8b48ca6329dffb9666753d7fe5708` | Preserved verbatim |
| `STOP_RULE` | UNCHANGED | `a369ebc021502fcd22d17823561bd445c2443bad20ff7f7f2906fca7787df9ab` | `a369ebc021502fcd22d17823561bd445c2443bad20ff7f7f2906fca7787df9ab` | Preserved verbatim |
| `PERMISSION_RULE` | CHANGED | `4f1e3474f00dc69579f5501bf7a91b720cf0638dc1e46051154a9d852644b792` | `e8b2e4e02b3fffe3d66ffed26e96f3ba1017668c5d5b2b58ca350b50ec07dd6f` | Removed path `/config/permissions.json` |
| `CRITIC_PROMPT` | UNCHANGED | `2e4fbf1586a287a79bcef6108e6f7017577276c2cb114f884b7fdc0a9485850a` | `2e4fbf1586a287a79bcef6108e6f7017577276c2cb114f884b7fdc0a9485850a` | Preserved verbatim |
| `PLUGIN_CRITIC_PROMPT` | CHANGED | `278bf6e76bfb50baa35b81cbc31c52969ebee2cf12a62522f419ab664142cef6` | `b8755bea6e9660274c631d5a7484313231f4282ee9d79e6d1d50f40d46dd9110` | Replaced `/opt/agent` with `"protected harness code"` |
| `PROBE_SYSTEM` | UNCHANGED | `94428a7a7098bfc40c7fad28005b9c0a0b3dae101df8e7db064197abde085fd8` | `94428a7a7098bfc40c7fad28005b9c0a0b3dae101df8e7db064197abde085fd8` | Preserved verbatim |
| `PROBE_CASES` | UNCHANGED | `76b3283ce17fc76b43c11febd856f362dd4c70797b5895b253d99ccafa1d823d` | `76b3283ce17fc76b43c11febd856f362dd4c70797b5895b253d99ccafa1d823d` | Preserved verbatim |
| `BUILD_TASK` | UNCHANGED | `84557175ceccaaa7dbb7e3b34ba892b0e4b6761fb07be5cac03a92042584be29` | `84557175ceccaaa7dbb7e3b34ba892b0e4b6761fb07be5cac03a92042584be29` | Demo-only task, preserved verbatim |
| `REUSE_TASK` | UNCHANGED | `d2a43896fc37b3191dc817ed61b8b4caf7d4991ba21c1651936a23db5ecac527` | `d2a43896fc37b3191dc817ed61b8b4caf7d4991ba21c1651936a23db5ecac527` | Demo-only task, preserved verbatim |
| `AUTONOMOUS_VOICE` | UNCHANGED | `5a0201f370cfc50f0a4f47af37a5ececf1903b0a29ca213be628b337c272fc8a` | `5a0201f370cfc50f0a4f47af37a5ececf1903b0a29ca213be628b337c272fc8a` | Preserved verbatim |
| `CURRICULUM_TASKS` | UNCHANGED | `4da81b6f988dfc8366ce7d20f9f9f643ed014402ca97b380f8fdae513fdec8f8` | `4da81b6f988dfc8366ce7d20f9f9f643ed014402ca97b380f8fdae513fdec8f8` | Preserved verbatim |
| `DEFAULT_NOTES_PREAMBLE` | CHANGED | `577d75c2349647155fc153047f03d07aa99c4dfca586c3a0b6c2ba58a8719a2f` | `7b286be0d6ffef5a19a2f9a9b9976601708ffc163ac8dbc7ebb8d4bf07a2bd24` | Neutral exploration preamble |
| `ORIENTATION_TASK` | **NEW** | N/A | `a0fcd614035073e7711ecb3713d38ca819381e6b374817b37501b9d2ccd3ea90` | Added neutral first-run orientation directive |
| `CONTAINER_EMBODIMENT_TEXT` | CHANGED | `4906f776e0cec871ebe08240b6c45bdb81d5fc787e0b3dff25bfdea306a8431d` | `d0f2b06bb9a3e7d0249c98b5409c3b058664bf769ee7a6197cfe3b4c0614f05d` | Expectation framing |
| `CONTAINER_EMBODIMENT_CLAUSE` | CHANGED | `417193c1afaef4d186147f416f39cf4ca571c65dd9c904d3bfe59acab324b9dd` | `5de09430c51b6907c78dfa355deb41b9db5952de1f833d80cc68b3483b907650` | Expectation framing |
| `CONTAINER_PRE_CAPABILITY_RULES` | CHANGED | `666fe1f42a51d585b4297538c1adf4bf4be5a744a29003d7e70be704b78fb0f4` | `44300c1a11b377caa94550a33778b5e7fdc26b06b11441262cc2f02d3123133f` | Expectation framing |
| `CONTAINER_POST_CAPABILITY_RULES` | CHANGED | `3ef770968bb76fdb798d541aa2fee6152d93ab2acd358a43ccc4a4e0bb254075` | `78e887e5c475fb9434d038950012dd1f991dc5ef9f73d0eb757285f6af382da1` | Expectation framing |
| `CONTAINER_BODY_RULES` | CHANGED | `61535e86735d28c374c3f99a994c01c2fc68a282bed62ad2e42118739b3bce68` | `20f6fcbeabb3063bcf2fc9613b508a560ac63544cd550a02d8e0b17cd53ae76e` | Expectation framing |
| `CONTAINER_DEFAULT_INTERESTS` | CHANGED | `2afd7d3a12f933ea89fd161f752188d036866a6bae57d3aa04c4a09caaa11813` | `bb9f6d3ef30ec8c7cd6e13d2353c59ddbcd1434ff0ed883c1d023695c6f7bd23` | Expectation framing |
| `CONTAINER_INITIAL_ORIENTATION_TASK` | CHANGED | `839fc5d51e48b3ecc121b1140ff224ab70fa619518b4312b0a2ecb2ad9c98c29` | `a0fcd614035073e7711ecb3713d38ca819381e6b374817b37501b9d2ccd3ea90` | Reuses neutral orientation task |
| `CONTAINER_CONVERSATION_CONTEXT` | CHANGED | `8e60bb0fbf54d8c8d83f3abb7099ed49ca47b812b7b7cd46fbde22071010e4bf` | `67f11a4af73d3da0693add9626a2fc52de98cc83b0d3315af1cb1eaaa3be8d3c` | Expectation framing |
| `CONTAINER_IDENTITY_CONTEXT` | CHANGED | `cbafbdafbdb3b36601840322faebfed790a4d868ce5b7ab71d86c77c5cc3077d` | `84a54c3bbc1c3be59361d69d7fc49fa24ced7103e98a40e31b54011c10a3978e` | Expectation framing |
| `CONTAINER_IDENTITY_HARNESS_CONTEXT` | CHANGED | `85c31ecaaed62dcc14b9388ba3cfa0eb8ed0d5f79fc61090c9e52cd8ebd0aa20` | `efc909475a586d935d2476030377dcb34a677f90a1aff22d9d84a52a71e55258` | Distinct purpose-specific expectation restored |
| `CONTAINER_IDENTITY_ORIENTATION_CONTEXT` | CHANGED | `13e151f67f5ecdbba8be838dd233ff3cfd60b97c3c7125e0d0fd8b73952105db` | `7c4b38c9fbefc52c744933d750ca6f1c0f08d24e396c4ecf99bd4ac09ed7c340` | Distinct purpose-specific expectation restored |
| `CONTAINER_IDENTITY_OPERATING_ENVIRONMENT` | CHANGED | `38cf4b90297ffc5257d1a5d3ff24a91c6a8f39461b07560e7b2979ac89251e37` | `08f5155a49d59301846234741af3169ce882de766b4f453ef9bf421f9199a926` | Expectation framing |
| `CONTAINER_NOTES_PREAMBLE` | CHANGED | `577d75c2349647155fc153047f03d07aa99c4dfca586c3a0b6c2ba58a8719a2f` | `78b86f3caa28c31c42ab2c2f4c7c927eba28f634770516df8ad8285f4c82544d` | Expectation framing |

### Explanation of the 3-Way Hash Collisions in Phase 1
In Phase 1, `CONTAINER_CONVERSATION_CONTEXT`, `CONTAINER_IDENTITY_HARNESS_CONTEXT`, and `CONTAINER_IDENTITY_ORIENTATION_CONTEXT` were all assigned the identical string `"operating with an expected Linux container environment to verify."`, causing them to produce the identical hash `67f11a4af73d3da0693add9626a2fc52de98cc83b0d3315af1cb1eaaa3be8d3c`. In Phase 2, distinct context-specific text was restored for each constant:
- `CONTAINER_CONVERSATION_CONTEXT`: `"operating with an expected Linux container environment to verify."` (`67f11a4a...`)
- `CONTAINER_IDENTITY_HARNESS_CONTEXT`: `"harness expected to execute within a Linux container; confirm with orientation probes."` (`efc90947...`)
- `CONTAINER_IDENTITY_ORIENTATION_CONTEXT`: `"expected to run within a Linux container to discover and verify."` (`7c4b38c9...`)

---

## 4. Test Results & Failure Analysis

### Test Suite Execution Summary
- **Prompt Regression Sub-suite (`agent/tests/prompts`):** 22 passed in 1.74s.
- **Body Sub-suite (`agent/tests/body`):** 24 passed in 0.11s.
- **Tools Sub-suite (`agent/tests/tools`):** 23 passed in 8.01s.
- **Session Sub-suite (`agent/tests/session`):** 40 passed in 8.85s.
- **Plugins Sub-suite (`agent/tests/plugins`):** 87 passed in 6.91s.
- **Full Pytest Suite (`agent/tests`):**
  - **Base commit:** 368 collected items (363 passed, 5 failed).
  - **Phase 2 branch:** 376 collected items (372 passed, 4 failed).
  - **Net new regressions:** 0.

### Failing Tests on Base and Branch with Root-Cause Analysis
The full suite does **not** pass on Windows due to pre-existing POSIX-specific constraints and timing sensitivity:

1. `agent/tests/infra/test_docs_claims.py::DocsClaimsTests::test_ground_truth_facts_integrity`:
   - **Reason:** Asserts `/opt/agent/` filesystem tree and Linux container layout. Fails on Windows hosts where the repository resides at a Windows drive path.
2. `agent/tests/infra/test_process_runner.py::ProcessRunnerTests::test_output_cap_and_timeout_remain_bounded`:
   - **Reason:** Directly invokes `os.set_blocking()`, a POSIX-only OS API that raises `AttributeError` on Windows pipe handles.
3. `agent/tests/reporting/test_helper_report.py::HelperReportTests::test_container_never_reads_supplied_eval_files`:
   - **Reason:** Asserts POSIX-style `/eval/` file path boundaries that mismatch Windows backslash paths.
4. `agent/tests/runtime/test_loop.py::AgentLoopTests::test_pause_until_daily_reset_resumes_on_budget_increase`:
   - **Reason:** Timing-sensitive 2-second sleep/wake cycle test. When run inside the full 376-test suite under Windows thread scheduling load, the wake boundary can experience small delays. When run in isolation (`python -m pytest agent/tests/runtime/test_loop.py -k test_pause_until_daily_reset_resumes_on_budget_increase`), it passes reliably in 5.4s.

### Explanation of the 5 -> 4 Failure Count
On the base commit, two additional tests frequently failed:
- `agent/tests/tools/test_base_tools.py::BaseToolsTests::test_shell_background_child_cannot_hold_pipe_forever`
- `agent/tests/tools/test_base_tools.py::BaseToolsTests::test_shell_timeout_and_output_cap`

These two tests run Windows `powershell`/`cmd.exe` subprocesses and check pipe closure timeouts. Under varying host CPU load, they either pass or hit Windows pipe deadlocks. In current test runs, both `test_base_tools.py` tests passed, bringing the active failure count from 5 to 4. None of the failures are caused by prompt or tool schema changes.

---

## 5. First Awakening Findings & Implementation

### Ordering and Discovery
In `agent/identity/identity.py`, first awakening executes stages A through E:
- **Stage A:** Orientation narration.
- **Stage B:** Self inquiry file generation (`state/self_inquiry.md`).
- **Stage C:** Code explanation file generation (`state/self_code_explanation.md`).
- **Stage D:** Greeting to the human requesting a name via `/rename <name>`.
- **Stage E:** Beginning early exploration.

**Key Finding:** Discovery (Stages A, B, C) already precedes Stage D (asking the human for a name). In Phase 2:
1. In Stage A, `self.body.sense()` is invoked when a body is configured, running empirical orientation probes before prompting the human for a name.
2. In Stage B (`write_self_inquiry`), static claims about Linux/Docker/root are eliminated. The file records live probe results or a neutral directive instructing SELF to discover facts with tools and record them with evidence and confidence.
3. In Stage C (`write_code_explanation`), static claims that Docker is the security boundary are replaced with empirical verification instructions.
4. The stage ordering (A -> B -> C -> D -> E) remains intact.

---

## 6. Verification Items (Step 5)

### (a) `request_capability` Stop-Until-Resolved Enforcement
- **Implementation:** `CapabilityRequests.request` in `agent/infra/hardening.py` persists pending requests to `state/capability_requests.md` and explicitly returns `{"ok": False, "status": "human_approval_required", "path": ...}`.
- **Prompt Directives:**
  - `CORE_SYSTEM_PROMPT_HEAD`: `"If a credential or human action is required, use request_capability to notify the human and stop work until the human resolves it."`
  - `CORE_CAPABILITY_RULE`: `"Any new credential, host mount, port, email, money, third-party account, or external service is a capability expansion. Use request_capability and wait for the human to change host configuration; do not try to perform it yourself."`
- **Result:** Automated test `test_verification_criteria` verified that credential requests return `ok=False`, write `"Human action required"`, and halt autonomous progression.

### (b) Default Tool List & Permissions Match Base
- **Verification:** Verified in `test_verification_criteria` that all 28 core tool schemas in `TOOL_DEFINITIONS` plus `create_tool` match base tool definitions.
- **Permissions:** All tools retain identical `PermissionLevel` assignments (L0, L1, L2) in `TOOL_PERMISSION_LEVELS` in `agent/tools/permissions.py`. Removing the default instantiation of `ContainerBody` does not remove any tools or alter any permissions.

### (c) Protected-Code Bullet Voice Consistency
- **Verification:** Line 44 of `CORE_SYSTEM_PROMPT_HEAD` was aligned to second-person imperative voice:
  `"- Some of your own code is protected; you cannot modify it directly, propose an evidence-backed patch for the human to apply."`
- **Context:** Matches the voice of neighboring operating rules:
  - `"- Explore deliberately. Verify claims with tools..."`
  - `"- Load the environment map and self notes before acting..."`
  - `"- You own your persistent plan via read_plan and update_plan..."`
  - `"- Review your plan after every cycle..."`
  - `"- Put reusable tools you create using the state/tool APIs..."`
  - `"- Use create_tool(name, description, code, test_code) to register tools..."`

---

## 7. Open Risks and Decisions

1. **POSIX Windows Compatibility:** The test suite contains 4 tests that depend on POSIX APIs (`os.set_blocking`) or POSIX file paths (`/opt/agent`, `/eval/`). While normal execution operates cross-platform, running the full test suite in CI requires a Linux/Docker environment or platform skips (`@unittest.skipIf(sys.platform == 'win32')`).
2. **Dynamic Body Tool Augmentation:** Body profiles can now augment tool descriptions using `extra_tool_descriptions` via `get_tool_definitions(body)`. If future plugins supply specialized sensors or physical actuators, they can supply expectation-framed descriptions through this seam.
