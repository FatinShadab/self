# Opencode Installer

Installs and configures the [opencode](https://github.com/anomalyco/opencode) coding-agent CLI as an optional tool for the Self agent.

> [!IMPORTANT]
> Self must still boot and work normally if opencode is missing or the download fails. The installer never blocks container startup.

---

## Files

| File | Purpose |
|---|---|
| `config.json` | Human-editable configuration: pinned version, GitHub repo, asset patterns, provider mappings, model list. |
| `install_opencode.py` | Installer script with `--build`, `--ensure`, `--force`, `--status`, `--list-models` modes. |
| `opencode.lock.json` | Auto-generated trust-on-first-use (TOFU) checksum lock file. Do not edit. |
| `state/opencode_install.json` | Runtime state: platform key, version, sha256, install timestamp, last error. |
| `smoke_test.py` | Smoke test: version check + optional live prompt test. |
| `test_opencode.py` | Offline unit tests (no network). |
| `README.md` | This file. |

---

## How Install Works

1. **Platform Detection** — Detects OS (Linux only), architecture (x64/arm64), libc (glibc/musl via `ldd --version` or `/lib/ld-musl-*`), and AVX2 support.
2. **Asset Selection** — Queries the GitHub Releases API for the pinned version tag, lists all assets, and selects the one matching the detected platform key using the pattern map in `config.json`.
3. **Download** — Downloads to a temp file with configurable timeout and retries.
4. **Integrity** — If the release publishes a checksums file, fetches and verifies it. Otherwise uses trust-on-first-use (TOFU): records sha256 in `opencode.lock.json` on first install and verifies against it on every later install.
5. **Install** — Extracts the archive (tar.gz or zip) into `/opt/opencode`, creates a symlink at `/usr/local/bin/opencode`, and sets world-readable/executable permissions.
6. **Config Generation** — Creates `/opt/opencode/config/opencode.json` with auto-update disabled, telemetry disabled, shell/edit tools auto-allowed, and provider API keys referenced via environment variables.

---

## How to Bump the Pinned Version

1. Edit `config.json` and change `"opencode_version"` to the new tag (e.g. `"v2.0.31"`).
2. Delete the old entry from `opencode.lock.json` if present (or delete the whole file to re-record TOFU hashes).
3. Rebuild the Docker image: `docker compose build`.

---

## How to Fill the Models List

1. After installation, run `python scripts/opencode/install_opencode.py --list-models` inside the container to see available models.
2. Edit `config.json` and replace the `"models"` placeholder entries with actual `"provider/model"` strings (e.g. `"groq/llama-3.3-70b-versatile"`).

---

## How to Add the Keys

Add the following environment variables to `.env`:

```env
# Opencode provider API keys (namespaced to avoid collisions with Self's own keys)
OPENCODE_GROQ_API_KEY=
OPENCODE_GOOGLE_API_KEY=
OPENCODE_HF_TOKEN=
```

The installer generates an opencode config that references the standard env var names (`GROQ_API_KEY`, `GEMINI_API_KEY`, `HF_TOKEN`). At runtime, the Self wrapper maps the namespaced `OPENCODE_*` names to the standard ones before invoking opencode.

---

## How to Run the Smoke Test

```bash
# Version check only (default)
python scripts/opencode/smoke_test.py

# With live API test (requires at least one key and explicit opt-in)
OPENCODE_SMOKE_LIVE=1 python scripts/opencode/smoke_test.py
```

---

## Running Tests

```bash
# From repo root
python -m unittest scripts/opencode/test_opencode.py -v
```

All tests run offline without network access.
