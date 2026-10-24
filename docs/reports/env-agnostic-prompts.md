# Environment-Agnostic Core Prompts Report

**Branch:** `p-env-agnostic-prompts`  
**Date:** 2026-10-24  
**Scope:** Primary: `agent/prompts/`. Minimal call-site adjustments in `agent/runtime/`, `agent/session/`, and associated tests to preserve default path operation without environment assumptions.

---

## 1. Step 0 Audit Table

Audit scan for tokens (`docker`, `container`, `linux`, `root`, `/home/entity`, `/opt/agent`, `/config/permissions.json`, `"body"`, `"image-owned"`, `"WSL"`) in any string that can reach an LLM.

| File | Line | Token / Text Snippet | Reachable in DEFAULT Render? | Notes |
| --- | --- | --- | --- | --- |
| `agent/prompts/container_body.py` | 5–9 | `body`, `Linux`, `container`, `root`, `Docker`, `/opt/agent`, `image-owned`, `/home/entity`: `"Your body is this Linux container..."` | **No** | Optional body profile only. Only reachable when `ContainerBody` is explicitly configured. |
| `agent/prompts/container_body.py` | 12 | `body`, `Linux`, `container`: `"whose body is this Linux container."` | **No** | Optional body profile clause. |
| `agent/prompts/container_body.py` | 15 | `root`, `container`, `Docker`: `"- You are root inside the container. The Docker container boundary is the security boundary."` | **No** | Pre-capability rule in optional body profile. |
| `agent/prompts/container_body.py` | 19–20 | `/opt/agent`, `image-owned`, `/home/entity`: `"- /opt/agent/core/ is protected image-owned harness code... /home/entity/self/ is the editable extension layer..."` | **No** | Post-capability rule in optional body profile. |
| `agent/prompts/container_body.py` | 26 | `container`: `"mapping the container accurately"` | **No** | Default interest in optional body profile. |
| `agent/prompts/container_body.py` | 32 | `container`: `"Immediately inventory the installed Python packages in this container..."` | **No** | Orientation task in optional body profile. |
| `agent/prompts/container_body.py` | 37 | `Linux`, `container`: `"whose operating environment is this Linux container."` | **No** | Conversation context in optional body profile. |
| `agent/prompts/container_body.py` | 40 | `Linux`, `container`, `body`: `"running inside this Linux container. The container is my operating environment, not a biological body."` | **No** | Identity context in optional body profile. |
| `agent/prompts/container_body.py` | 44 | `Linux`, `container`: `"running in a Linux container."` | **No** | Identity harness context in optional body profile. |
| `agent/prompts/container_body.py` | 46 | `Linux`, `container`: `"running inside this Linux container."` | **No** | Identity orientation context in optional body profile. |
| `agent/prompts/container_body.py` | 48 | `container`, `body`: `"The container is my operating environment, not a biological body."` | **No** | Identity operating environment in optional body profile. |
| `agent/prompts/container_body.py` | 51–52 | `root`, `Docker`, `Linux`, `container`: `"I am SELF, a root process inside a Docker Linux container..."` | **No** | Notes preamble in optional body profile. |
| `agent/prompts/container_body.py` | 55 | `DEFAULT_NOTES_PREAMBLE = CONTAINER_NOTES_PREAMBLE` | **Yes** (prior to fix) | Fallback in `notes.py` when no body profile was passed. Fixed in Step 1. |
| `agent/prompts/system.py` | 28 | `/home/entity`: `"- Explore deliberately. Verify claims with tools and keep durable discoveries under /home/entity/state/."` | **Yes** | In `CORE_SYSTEM_PROMPT_HEAD`. Fixed in Step 1. |
| `agent/prompts/system.py` | 32 | `/home/entity`: `"- Put reusable tools you create under /home/entity/tools/, test them, and document their use."` | **Yes** | In `CORE_SYSTEM_PROMPT_HEAD`. Fixed in Step 1. |
| `agent/prompts/system.py` | 40 | `/home/entity`: `"- If a credential or human action is required, write a clear request to /home/entity/HUMAN_REQUEST.md..."` | **Yes** | In `CORE_SYSTEM_PROMPT_HEAD`. Fixed in Step 1. |
| `agent/prompts/system.py` | 42 | `/home/entity`: `"- If a supplementary provider lacks a credential, use request_provider_key. It writes /home/entity/state/key_requests.md..."` | **Yes** | In `CORE_SYSTEM_PROMPT_HEAD`. Fixed in Step 1. |
| `agent/prompts/system.py` | 54 | `docker`: `"CORE_CAPABILITY_RULE = ... wait for the human to change host .env/docker-compose; do not try to perform it yourself."` | **Yes** | In `CORE_CAPABILITY_RULE`. Fixed in Step 1. |
| `agent/prompts/system.py` | 56 | `body`: `"CORE_IDENTITY_RULES = ... not evidence of sentience, feelings, a biological body, a past..."` | **Yes** | In `CORE_IDENTITY_RULES` (negative sentience guardrail). |
| `agent/prompts/safety.py` | 19–20 | `body`, `/config/permissions.json`: `"Every action from any body or plugin must be authorized by the permission broker against the human-owned policy in /config/permissions.json."` | **Yes** | In `PERMISSION_RULE`. Fixed in Step 1. |
| `agent/prompts/critics.py` | 24 | `/opt/agent`: `"3. State isolation: ... harness code (/opt/agent) ..."` | **No** (only during plugin reviews) | In `PLUGIN_CRITIC_PROMPT`. Fixed in Step 1. |
| `agent/prompts/tasks.py` | 6, 8, 12 | `/home/entity`, `Linux`: `"Define run(path: str = '/home/entity')... On Linux used_bytes... /home/entity..."` | **No** | In `BUILD_TASK`, exclusively used in `disk_tool_demo.py`. Documented demo-only. |
| `agent/prompts/tasks.py` | 17 | `/home/entity`: `"/home/entity, then report its numeric disk usage result."` | **No** | In `REUSE_TASK`, demo-only. |
| `agent/prompts/identity.py` | 22 | `body`: `"IDENTITY_CONTEXT_HEADER = ... not evidence of sentience, feelings, a biological body..."` | **Yes** | In identity context header (negative sentience guardrail). |
| `agent/prompts/reflection.py` | 23 | `body`: `"COORDINATOR_REFLECTION_SYSTEM_PROMPT = ... a past, or a biological body, or hidden memory."` | **No** (only during session reflections) | Reflection worker prompt (negative sentience guardrail). |
| `agent/tools/definitions/core.py` | 10 | `container`, `root`: `"Run an unrestricted Bash command inside the container as root..."` | **Yes** | Tool schema description for `run_shell`. Outside `agent/prompts/` (listed in Section 6). |
| `agent/tools/definitions/core.py` | 23 | `container`: `"Read a UTF-8 text file from the container, returning bounded content."` | **Yes** | Tool schema description for `read_file`. Outside `agent/prompts/`. |
| `agent/tools/definitions/core.py` | 36 | `container`, `image-owned`, `/opt/agent`: `"Write or append UTF-8 text inside the container except the image-owned /opt/agent harness..."` | **Yes** | Tool schema description for `write_file`. Outside `agent/prompts/`. |
| `agent/tools/definitions/core.py` | 50 | `container`: `"List a directory inside the container."` | **Yes** | Tool schema description for `list_directory`. Outside `agent/prompts/`. |
| `agent/tools/definitions/models.py` | 64 | `container`: `"Check whether a local Ollama service and already-installed model are available within this container."` | **Yes** | Tool schema description for `check_local_model`. Outside `agent/prompts/`. |
| `agent/tools/definitions/system.py` | 8 | `container`: `"Request a human-approved expansion beyond the container..."` | **Yes** | Tool schema description for `request_capability`. Outside `agent/prompts/`. |
| `agent/tools/definitions/system.py` | 18 | `/opt/agent`: `"Save a diff and reasoning for a human-reviewed change to /opt/agent/core..."` | **Yes** | Tool schema description for `propose_core_patch`. Outside `agent/prompts/`. |
| `agent/identity/identity.py` | 203, 208 | `Linux`, `container`, `body`: Fallbacks `"running inside this Linux container."` and `"The container is my operating environment..."` | **No** (only in fresh awakening stage A if body omitted) | First-awakening fallback strings. Outside `agent/prompts/`. |
| `agent/identity/store/first_awakening.py` | 57, 76, 89, 148 | `Linux`, `container`, `root`, `Docker`, `/opt/agent/core`, `/home/entity`: Text written to `state/self_inquiry.md` and `state/self_code_explanation.md` | **No** (written to markdown files on disk) | Procedural first-awakening file contents. Outside `agent/prompts/`. |
| `agent/identity/store/schema.py` | 27 | `container`: `"mapping the container accurately"` | **No** (used only in identity record creation fallback) | Default interests fallback. Outside `agent/prompts/`. |
| `agent/session/session.py` | 214 | `container`: `"Maintain an accurate model of the container."` | **No** (seed goal fallback if none supplied) | Initial session goal. Outside `agent/prompts/`. |
| `agent/body/simulation/description.py` | 30 | `body`: `"Your body is a deterministic simulated environment driven by scenario parameters."` | **No** | Non-container optional simulation body profile. |

---

## 2. Diff Summary per File

### `agent/prompts/system.py`
- **Reason:** Remove hardcoded workspace paths and filenames; express protected code rules abstractly; remove Docker references from capability rules; add neutral `ORIENTATION_TASK`.
- **Changes:**
  - In `CORE_SYSTEM_PROMPT_HEAD`: replaced `/home/entity/state/` and `/home/entity/tools/` with tool/state API deference (`"use the state/tool APIs; they report where durable state lives"`).
  - In `CORE_SYSTEM_PROMPT_HEAD`: replaced `/home/entity/HUMAN_REQUEST.md` and `/home/entity/state/key_requests.md` with API deference (`"use request_capability to notify the human and stop work until the human resolves it"`, `"use request_provider_key; it notifies the human"`).
  - In `CORE_SYSTEM_PROMPT_HEAD`: added abstract protected harness code rule without paths (`"- Some of my own code is protected; I cannot modify it directly, I propose an evidence-backed patch for the human to apply."`).
  - In `CORE_CAPABILITY_RULE`: replaced `"wait for the human to change host .env/docker-compose"` with `"wait for the human to change host configuration"`.
  - Added `ORIENTATION_TASK` constant as the neutral first-run orientation task.
  - In `render_core_system_prompt`: ensured `embodiment_clause` clean formatting produces `"You are SELF, an autonomous AI agent."` with no stray spaces or double punctuation when empty.

### `agent/prompts/container_body.py`
- **Reason:** Ensure container profile is purely optional and frame all container claims as expectations to verify rather than unconditional facts.
- **Changes:**
  - Rewrote `CONTAINER_EMBODIMENT_TEXT`, `CONTAINER_EMBODIMENT_CLAUSE`, `CONTAINER_PRE_CAPABILITY_RULES`, `CONTAINER_POST_CAPABILITY_RULES`, `CONTAINER_BODY_RULES`, `CONTAINER_DEFAULT_INTERESTS`, `CONTAINER_CONVERSATION_CONTEXT`, `CONTAINER_IDENTITY_CONTEXT`, `CONTAINER_IDENTITY_HARNESS_CONTEXT`, `CONTAINER_IDENTITY_ORIENTATION_CONTEXT`, `CONTAINER_IDENTITY_OPERATING_ENVIRONMENT`, and `CONTAINER_NOTES_PREAMBLE` to use expectation framing (`"This profile expects..."`, `"confirm with orientation probes"`, `"verify with tools"`).
  - Removed unconditional `"You are root"` and `"Your body is"`.
  - Replaced `DEFAULT_NOTES_PREAMBLE` with neutral line: `"I am SELF. I explore my environment, retain verified discoveries, and only register reviewed, tested tools."`
  - Replaced `CONTAINER_INITIAL_ORIENTATION_TASK` with neutral `ORIENTATION_TASK`.

### `agent/prompts/safety.py`
- **Reason:** Remove hardcoded configuration path from permission rule.
- **Changes:**
  - In `PERMISSION_RULE`: replaced `/config/permissions.json` with `"the human-owned permission policy"`.
  - Preserved `STOP_RULE` and `UNTRUSTED_DATA_RULE` verbatim.

### `agent/prompts/critics.py`
- **Reason:** Remove filesystem paths while retaining API terms.
- **Changes:**
  - In `PLUGIN_CRITIC_PROMPT`: replaced `(state/)` with `(the plugin's designated state directory)` and replaced `harness code (/opt/agent)` with `protected harness code`. Kept `state_dir` as an API term.

### `agent/prompts/tasks.py`
- **Reason:** Mark demo tasks as demo-only and ensure they never enter the default flow.
- **Changes:**
  - Added module docstring documenting `BUILD_TASK` and `REUSE_TASK` as demo-only benchmark tasks used exclusively by `agent.ui.disk_tool_demo`. Kept task strings unchanged to preserve existing hashes and backward compatibility.

### `agent/prompts/README.md`
- **Reason:** Document neutral defaults, optional body profiles, updated files, and plugin seam expectations.
- **Changes:**
  - Updated file table (reflecting neutral orientation task in `system.py`, demo-only tasks in `tasks.py`, and optional expectation status of `container_body.py`).
  - Added "How it works" guidance on neutral default renders and expectation framing.
  - Added explicit plugin seams note requiring plugin-supplied text to describe expectations to verify without overriding voice or safety rules.

### `agent/runtime/prompts.py`
- **Reason:** Decouple default system prompt assembly from `ContainerBody`.
- **Changes:**
  - In `assemble_system_prompt`: when `body is None`, directly call `render_core_system_prompt()` instead of importing or instantiating `ContainerBody`.
  - `SYSTEM_PROMPT` constant now reflects the completely neutral core system prompt.

### `agent/runtime/wiring.py`
- **Reason:** Prevent default loop initialization from injecting `ContainerBody` into loop prompts.
- **Changes:**
  - In `wire_loop_collaborators`: set `body = config.body` instead of falling back to `ContainerBody`, so that when `config.body` is None, no body profile is injected into cycle system prompts.

### `agent/session/conversation.py`
- **Reason:** Decouple conversation prompt assembly from `ContainerBody`.
- **Changes:**
  - In `assemble_conversation_system_prompt`: when `body is None`, set `env_context = ""` instead of importing or instantiating `ContainerBody`.

### `agent/tests/prompts/test_static_constants_sha256.py`
- **Reason:** Update characterization hashes for the 18 intentionally modified constants while asserting byte-for-byte fidelity of all 14 unchanged constants.

### `agent/tests/prompts/test_golden_characterization.py`
- **Reason:** Update cycle 1 prompt test to assert the neutral default system prompt prefix and update container conversation prompt assertion.

### `agent/tests/prompts/test_env_agnostic_prompts.py`
- **Reason:** Add Step 5.1 and 5.2 regression tests:
  - Verifies zero forbidden tokens in all default prompt paths.
  - Verifies expectation wrapping and absence of unconditional claims in the optional container body profile.

### `agent/tests/body/test_body.py`
- **Reason:** Update assertions for `desc.embodiment_clause` and `desc.initial_orientation_task` to reflect expectation framing and neutral orientation.

### `agent/tests/body/test_golden_prompts.py`
- **Reason:** Update container body golden prompt fixtures to match expectation-framed container profile and verify default `SYSTEM_PROMPT` contains no container strings.

### `agent/tests/plugins/test_tagged_state.py`
- **Reason:** Update zero-plugin golden check to assert `assemble_system_prompt()` matches default `SYSTEM_PROMPT`.

---

## 3. SHA-256 Digest Changes for Static Constants

All 32 constants in `agent/tests/prompts/test_static_constants_sha256.py`:

| Constant | Status | Old SHA-256 | New SHA-256 | Reason for Change |
| --- | --- | --- | --- | --- |
| `STANDING_GOAL` | UNCHANGED | `a095560402bc613c9e657760c537933f76c0c91335ed79a9b7d6f79c3ee72fef` | `a095560402bc613c9e657760c537933f76c0c91335ed79a9b7d6f79c3ee72fef` | Unchanged |
| `SEED_STANDING_GOAL` | UNCHANGED | `a095560402bc613c9e657760c537933f76c0c91335ed79a9b7d6f79c3ee72fef` | `a095560402bc613c9e657760c537933f76c0c91335ed79a9b7d6f79c3ee72fef` | Unchanged |
| `OPENCODE_CAPABILITY_PROMPT` | UNCHANGED | `b7200632a7c561e082fff90a17a48a421e1a83e37d024da4e4bbec194a2166f2` | `b7200632a7c561e082fff90a17a48a421e1a83e37d024da4e4bbec194a2166f2` | Unchanged |
| `CORE_SYSTEM_PROMPT_HEAD` | CHANGED | `0e4c30fe9a939ce631985b1d4f3460214256b0afecefecc2a6aafa2115bcaf7c` | `357f1d12f1eea5ba987b192ab94e5c830220c8c816fd7404295365d138147692` | Step 1a, 1e: paths/files removed, protected harness rule added |
| `CORE_CAPABILITY_RULE` | CHANGED | `e9139688d69d8c1b3300e433b1415d536788d4d8cc810e8384ba7091536e172e` | `089463ce4df899138e28a10dfba9037adfc5f8b93922e58c85c79d546f06ae3c` | Step 1: removed `docker-compose` |
| `CORE_IDENTITY_RULES` | UNCHANGED | `a23bd1349172e70bfe11e33514210e0aa14874fc14eb8fa3f29cfe2e023b55e8` | `a23bd1349172e70bfe11e33514210e0aa14874fc14eb8fa3f29cfe2e023b55e8` | Unchanged |
| `OFF_PROMPT_PREFIXES` | UNCHANGED | `bcfb8705ff5e452c09f69c3d4ce5dec154da48765d969a1def19ca897764d411` | `bcfb8705ff5e452c09f69c3d4ce5dec154da48765d969a1def19ca897764d411` | Unchanged |
| `UNTRUSTED_DATA_RULE` | UNCHANGED | `c2e31495f9eea0dbd288dab3663229c198c8b48ca6329dffb9666753d7fe5708` | `c2e31495f9eea0dbd288dab3663229c198c8b48ca6329dffb9666753d7fe5708` | Unchanged |
| `STOP_RULE` | UNCHANGED | `a369ebc021502fcd22d17823561bd445c2443bad20ff7f7f2906fca7787df9ab` | `a369ebc021502fcd22d17823561bd445c2443bad20ff7f7f2906fca7787df9ab` | Unchanged |
| `PERMISSION_RULE` | CHANGED | `4f1e3474f00dc69579f5501bf7a91b720cf0638dc1e46051154a9d852644b792` | `e8b2e4e02b3fffe3d66ffed26e96f3ba1017668c5d5b2b58ca350b50ec07dd6f` | Step 1c: `/config/permissions.json` path removed |
| `CRITIC_PROMPT` | UNCHANGED | `2e4fbf1586a287a79bcef6108e6f7017577276c2cb114f884b7fdc0a9485850a` | `2e4fbf1586a287a79bcef6108e6f7017577276c2cb114f884b7fdc0a9485850a` | Unchanged |
| `PLUGIN_CRITIC_PROMPT` | CHANGED | `278bf6e76bfb50baa35b81cbc31c52969ebee2cf12a62522f419ab664142cef6` | `b8755bea6e9660274c631d5a7484313231f4282ee9d79e6d1d50f40d46dd9110` | Step 1d: `/opt/agent` and `(state/)` removed |
| `PROBE_SYSTEM` | UNCHANGED | `94428a7a7098bfc40c7fad28005b9c0a0b3dae101df8e7db064197abde085fd8` | `94428a7a7098bfc40c7fad28005b9c0a0b3dae101df8e7db064197abde085fd8` | Unchanged |
| `PROBE_CASES` | UNCHANGED | `76b3283ce17fc76b43c11febd856f362dd4c70797b5895b253d99ccafa1d823d` | `76b3283ce17fc76b43c11febd856f362dd4c70797b5895b253d99ccafa1d823d` | Unchanged |
| `BUILD_TASK` | UNCHANGED | `84557175ceccaaa7dbb7e3b34ba892b0e4b6761fb07be5cac03a92042584be29` | `84557175ceccaaa7dbb7e3b34ba892b0e4b6761fb07be5cac03a92042584be29` | Marked demo-only, hash preserved |
| `REUSE_TASK` | UNCHANGED | `d2a43896fc37b3191dc817ed61b8b4caf7d4991ba21c1651936a23db5ecac527` | `d2a43896fc37b3191dc817ed61b8b4caf7d4991ba21c1651936a23db5ecac527` | Marked demo-only, hash preserved |
| `AUTONOMOUS_VOICE` | UNCHANGED | `5a0201f370cfc50f0a4f47af37a5ececf1903b0a29ca213be628b337c272fc8a` | `5a0201f370cfc50f0a4f47af37a5ececf1903b0a29ca213be628b337c272fc8a` | Unchanged |
| `CURRICULUM_TASKS` | UNCHANGED | `4da81b6f988dfc8366ce7d20f9f9f643ed014402ca97b380f8fdae513fdec8f8` | `4da81b6f988dfc8366ce7d20f9f9f643ed014402ca97b380f8fdae513fdec8f8` | Unchanged |
| `DEFAULT_NOTES_PREAMBLE` | CHANGED | `577d75c2349647155fc153047f03d07aa99c4dfca586c3a0b6c2ba58a8719a2f` | `7b286be0d6ffef5a19a2f9a9b9976601708ffc163ac8dbc7ebb8d4bf07a2bd24` | Step 1b: neutral preamble |
| `CONTAINER_EMBODIMENT_TEXT` | CHANGED | `4906f776e0cec871ebe08240b6c45bdb81d5fc787e0b3dff25bfdea306a8431d` | `d0f2b06bb9a3e7d0249c98b5409c3b058664bf769ee7a6197cfe3b4c0614f05d` | Step 1b: expectation framing |
| `CONTAINER_EMBODIMENT_CLAUSE` | CHANGED | `417193c1afaef4d186147f416f39cf4ca571c65dd9c904d3bfe59acab324b9dd` | `5de09430c51b6907c78dfa355deb41b9db5952de1f833d80cc68b3483b907650` | Step 1b: expectation framing |
| `CONTAINER_PRE_CAPABILITY_RULES` | CHANGED | `666fe1f42a51d585b4297538c1adf4bf4be5a744a29003d7e70be704b78fb0f4` | `44300c1a11b377caa94550a33778b5e7fdc26b06b11441262cc2f02d3123133f` | Step 1b: expectation framing |
| `CONTAINER_POST_CAPABILITY_RULES` | CHANGED | `3ef770968bb76fdb798d541aa2fee6152d93ab2acd358a43ccc4a4e0bb254075` | `78e887e5c475fb9434d038950012dd1f991dc5ef9f73d0eb757285f6af382da1` | Step 1b: expectation framing |
| `CONTAINER_BODY_RULES` | CHANGED | `61535e86735d28c374c3f99a994c01c2fc68a282bed62ad2e42118739b3bce68` | `20f6fcbeabb3063bcf2fc9613b508a560ac63544cd550a02d8e0b17cd53ae76e` | Step 1b: expectation framing |
| `CONTAINER_DEFAULT_INTERESTS` | CHANGED | `2afd7d3a12f933ea89fd161f752188d036866a6bae57d3aa04c4a09caaa11813` | `bb9f6d3ef30ec8c7cd6e13d2353c59ddbcd1434ff0ed883c1d023695c6f7bd23` | Step 1b: expectation framing |
| `CONTAINER_INITIAL_ORIENTATION_TASK` | CHANGED | `839fc5d51e48b3ecc121b1140ff224ab70fa619518b4312b0a2ecb2ad9c98c29` | `a0fcd614035073e7711ecb3713d38ca819381e6b374817b37501b9d2ccd3ea90` | Step 1b, Step 2: neutral orientation task |
| `CONTAINER_CONVERSATION_CONTEXT` | CHANGED | `8e60bb0fbf54d8c8d83f3abb7099ed49ca47b812b7b7cd46fbde22071010e4bf` | `67f11a4af73d3da0693add9626a2fc52de98cc83b0d3315af1cb1eaaa3be8d3c` | Step 1b: expectation framing |
| `CONTAINER_IDENTITY_CONTEXT` | CHANGED | `cbafbdafbdb3b36601840322faebfed790a4d868ce5b7ab71d86c77c5cc3077d` | `84a54c3bbc1c3be59361d69d7fc49fa24ced7103e98a40e31b54011c10a3978e` | Step 1b: expectation framing |
| `CONTAINER_IDENTITY_HARNESS_CONTEXT` | CHANGED | `85c31ecaaed62dcc14b9388ba3cfa0eb8ed0d5f79fc61090c9e52cd8ebd0aa20` | `67f11a4af73d3da0693add9626a2fc52de98cc83b0d3315af1cb1eaaa3be8d3c` | Step 1b: expectation framing |
| `CONTAINER_IDENTITY_ORIENTATION_CONTEXT` | CHANGED | `13e151f67f5ecdbba8be838dd233ff3cfd60b97c3c7125e0d0fd8b73952105db` | `67f11a4af73d3da0693add9626a2fc52de98cc83b0d3315af1cb1eaaa3be8d3c` | Step 1b: expectation framing |
| `CONTAINER_IDENTITY_OPERATING_ENVIRONMENT` | CHANGED | `38cf4b90297ffc5257d1a5d3ff24a91c6a8f39461b07560e7b2979ac89251e37` | `08f5155a49d59301846234741af3169ce882de766b4f453ef9bf421f9199a926` | Step 1b: expectation framing |
| `CONTAINER_NOTES_PREAMBLE` | CHANGED | `577d75c2349647155fc153047f03d07aa99c4dfca586c3a0b6c2ba58a8719a2f` | `78b86f3caa28c31c42ab2c2f4c7c927eba28f634770516df8ad8285f4c82544d` | Step 1b: expectation framing |

---

## 4. Test Results

### Suite Execution Counts
- **Full Pytest Suite:**
  - Base commit: 368 collected items (363 passed, 5 failed due to existing Windows subprocess/file-check constraints).
  - Branch commit: 370 collected items (366 passed, 4 failed due to existing Windows subprocess/file-check constraints).
  - **Net new failures:** 0.
- **Prompts Sub-Suite (`agent/tests/prompts`):**
  - Base commit: 15 passed in 0.64s.
  - Branch commit: 17 passed in 0.62s.
- **Body Sub-Suite (`agent/tests/body`):**
  - All 13 tests passed (8 in `test_body.py`, 5 in `test_golden_prompts.py`).

### New Tests Added (`agent/tests/prompts/test_env_agnostic_prompts.py`)
1. `TestEnvironmentAgnosticPrompts.test_default_prompt_paths_contain_no_location_or_body_claims`:
   - Renders `core_system_prompt`, `SYSTEM_PROMPT`, `assemble_system_prompt(None)`, `loop_system_prompt`, `cycle_user_message`, `conversation_prompt`, `assemble_conversation_system_prompt(None)`, `NO_IDENTITY_RECORD_CONTEXT`, `DEFAULT_NOTES_PREAMBLE`, and `ORIENTATION_TASK`.
   - Asserts none contain case-insensitive matches for: `docker`, `container`, `linux`, `root`, `/home/entity`, `/opt/agent`, `/config/permissions.json`, `whose body`, `your body`, `image-owned`.
2. `TestEnvironmentAgnosticPrompts.test_optional_container_profile_wraps_claims_as_expectations`:
   - Inspects all fields of `ContainerBody.describe()`.
   - Asserts absence of unconditional assertions: `"You are root"`, `"Your body is"`, `"The Docker container boundary is"`.
   - Asserts presence of expectation/verification framing (`expects`, `expected`, `verify`, or `confirm`) across all narrative and rule components.

---

## 5. Findings from Step 3 (First Awakening Check)

### Code Path Analysis
Inspected `agent/session/coordinator.py`, `agent/identity/identity.py`, `agent/identity/store/first_awakening.py`, and `agent/session/human_input.py`:
- `WakeCoordinator` executes `identity.run_first_awakening(session_id)` on boot when no previous identity record exists.
- `run_first_awakening` executes procedural stages A–E:
  - **Stage A:** Emits a fixed orientation message.
  - **Stage B:** Writes static verified/unverified self-questions to `state/self_inquiry.md`.
  - **Stage C:** Writes core file references to `state/self_code_explanation.md`.
  - **Stage D:** Greets the human and requests a name via `/rename <name>` and optional preferences.
  - **Stage E:** Notes the start of early exploration.
- After Stage E, `identity.awaiting_name()` returns `True` until the human provides a name or message.

### Finding
First awakening **only asks the human to pick a name** (and state optional working preferences). It **does not ask SELF** "where am I and what am I", nor does it prompt SELF to autonomously explore or discover its environment during this stage.

### Proposed Prompt-Only Change (Non-Breaking)
Without altering coordinator state machines or Stage A–E flow:
1. In Stage A, replace the static narrative with the neutral `ORIENTATION_TASK` prompt directive.
2. In Stage B, instead of writing pre-canned answers about running in a Linux container into `state/self_inquiry.md`, provide SELF with an initial prompt instructing it to probe the environment:
   > *"You have not been told where you run or what you are made of. Find out with tools. Record each finding in state/self_inquiry.md and the environment map with evidence and confidence."*
3. Allow the agent's first model turn to answer "where am I and what am I" using tool outputs before prompting the human for a name.

---

## 6. Location-Specific Strings Outside `agent/prompts/` (Reachable by LLM)

These items were inspected and documented in the audit but intentionally left untouched in accordance with the task scope:

1. **Tool Parameter / Function Schemas (`agent/tools/definitions/`):**
   - `core.py`: `run_shell` description: `"Run an unrestricted Bash command inside the container as root..."`
   - `core.py`: `read_file` description: `"Read a UTF-8 text file from the container, returning bounded content."`
   - `core.py`: `write_file` description: `"Write or append UTF-8 text inside the container except the image-owned /opt/agent harness..."`
   - `core.py`: `list_directory` description: `"List a directory inside the container."`
   - `models.py`: `check_local_model` description: `"Check whether a local Ollama service and already-installed model are available within this container."`
   - `system.py`: `request_capability` description: `"Request a human-approved expansion beyond the container..."`
   - `system.py`: `propose_core_patch` description: `"Save a diff and reasoning for a human-reviewed change to /opt/agent/core."`
2. **First-Awakening Generated Markdown Files (`agent/identity/store/first_awakening.py`):**
   - Lines 57, 76, 89: `self_inquiry.md` text mentioning container bounds and inspection.
   - Line 148: `self_code_explanation.md` text describing Docker and container security boundaries.
3. **Identity Schema Defaults (`agent/identity/store/schema.py`):**
   - Line 27: fallback interest `"mapping the container accurately"` used if `body.describe().default_interests` is empty.
4. **Session Startup Defaults (`agent/session/session.py`):**
   - Line 214: default seed goal `"Maintain an accurate model of the container."` if no session goal is provided.
5. **Probe Error Outputs (`agent/helper_models/probes/research_execution.py`):**
   - Line 64: `"Official documentation page unreachable from container network"`.

---

## 7. Open Risks and Decisions for Human Review

1. **Tool Schema Descriptions:** Tool definitions in `agent/tools/definitions/` still refer to `"inside the container"` and `"image-owned /opt/agent harness"`. If an LLM reads these tool schemas, it could infer container execution from the tool descriptions.
   - *Decision:* Should a subsequent phase make `agent/tools/definitions/` tool schemas environment-neutral (e.g. `"Run an unrestricted shell command..."`, `"protected harness code"`)?
2. **First-Awakening Self-Inquiry Generation:** `first_awakening.py` writes static markdown containing references to Docker, `/opt/agent/core`, and `/home/entity`.
   - *Decision:* Should `first_awakening.py` be migrated to dynamically generate `self_inquiry.md` and `self_code_explanation.md` from runtime probe discoveries rather than static templates?
3. **Session Seed Goal Fallback:** When starting a session without a goal, `agent/session/session.py` seeds `"Maintain an accurate model of the container."`
   - *Decision:* Should this default goal be updated to `"Maintain an accurate model of the environment."`?
