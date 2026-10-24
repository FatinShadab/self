# Plugin Lifecycle and Hash Pinning

Plugins operate under strict lifecycle management to guarantee deterministic behavior, prevent untrusted tampering, and survive dynamic loading and unloading without crashing the core engine.

---

## 1. Lifecycle Phases

The plugin lifecycle progresses through distinct stages:

```
[Discovered] ──> [Validated] ──> [Approved & Pinned] ──> [Active] ──> [Disabled / Archived]
```

1. **Discovery:**
   Scans shipped plugins in `/opt/agent/plugins` and workspace plugins in `workspace/plugins/<name>`. Special directories (`_template` and `_archive`) are strictly ignored during discovery.

2. **Validation:**
   Static verification of manifest schema, version ranges, tool namespacing, permissions, and test folder presence via `python -m agent.plugins validate`.

3. **Approval, Hash Pinning, and Permission Ceiling:**
   The operator enables the plugin with a pinned SHA-256 hash in host-owned `config/plugins.json` and optionally sets `permission_level` (L0–L3). `/plugins enable <name>` can write the pin only where config is writable; the default Docker Compose mount is read-only inside the container.

4. **Activation (Cycle Boundary Synchronization):**
   Plugins are enabled or disabled exclusively at autonomous cycle boundaries—never mid-cycle. Changes to a plugin's permission ceiling are also applied at cycle boundaries.

5. **Deactivation (Disable / Unplug):**
   When disabled by the operator, the plugin's tools and sensors are removed from the active loop. Any plan goals tagged with the plugin are marked `"suspended: plugin disabled"`.

6. **Removal & Archival:**
   When a plugin is removed, its folder and runtime state are automatically backed up to `workspace/plugins/_archive/<name>-<timestamp>/` unless an explicit purge is confirmed.

---

## 2. Hash Pinning and Tamper Detection

To protect system integrity, every enabled plugin is pinned to its SHA-256 content digest:

- **Hash Computation:**
  Computed across all files in the plugin folder, sorted deterministically by relative POSIX paths.
  - Automatically **excluded** from hashing: `state/` (private plugin runtime state), `_archive/`, `__pycache__/`, compiled bytecode (`*.pyc`), and hidden dot-files.
- **Mismatch Refusal:**
  If an enabled plugin's files are modified on disk, the next cycle boundary synchronization detects that `actual_hash != pinned_hash`.
  - The core logs a `plugin_hash_mismatch` event.
  - The plugin is immediately refused and deactivated.
  - Its goals remain suspended in the plan.
  - Private state is preserved intact.

### How to Re-Pin After Legitimate Edits

When legitimate changes are made to a plugin (such as editing its manifest, updating tool logic, or upgrading its version):

1. Run the static validator to confirm validity:
   ```bash
   python -m agent.plugins validate plugins/<name>
   ```
2. Re-pin the approved plugin hash in host-owned `config/plugins.json`. Where config is writable, `/plugins enable <name>` or `PluginManager.enable_by_human("<name>")` can recompute and write the pin. The default container cannot write `/config`.

---

## 3. Unplug Resilience and Vanished Tools

If the LLM generates a tool call for a tool belonging to a disabled or vanished plugin:
- The core does **not** crash or raise an unhandled exception.
- The tool runner intercepts the call and returns a structured observation:
  ```json
  {
    "ok": false,
    "error": "tool no longer available: plugin <name> disabled"
  }
  ```
- The model receives this observation and continues its autonomous reasoning without disruption.

---

## 4. Core Version Upgrades and Incompatibility

When the agent core is upgraded, existing plugins may fall outside their declared `core_api` compatibility range:

1. **Discovery Rejection:**
   Plugins whose `core_api` excludes the active core version are rejected during discovery. A `plugin_load_failed` event is logged naming the plugin, the declared range, and the current core version.
2. **State Preservation:**
   An incompatible plugin is not loaded. Any private state files in `workspace/plugins/<name>/state` remain untouched. Nothing is deleted.
3. **Suspended Goal Protection:**
   Any plan goals associated with the plugin retain their `"suspended: plugin disabled"` status. Suspended goals are explicitly exempt from stale-item pruning, item consolidation, and archive purging.
4. **Resumption:**
   When the plugin manifest is updated with a compatible `core_api` range and re-enabled by the operator, suspended goals automatically resume with `status="todo"` and a note `"re-verify: plugin was disabled"`.
