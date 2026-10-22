#!/usr/bin/env python3
"""Opencode binary installer for the Self agent container.

Modes:
    --build   Run at Docker image build time. Downloads + installs the pinned
              version. Exits non-zero on failure only when --strict is also given.
    --ensure  Idempotent startup check. Reinstalls only when needed. Always
              exits 0 so the container boots even if opencode is unavailable.
    --force   Force reinstall regardless of current state.
    --status  Print current install state and exit.
    --list-models  Attempt to list models from the installed opencode binary.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
LOCK_PATH = SCRIPT_DIR / "opencode.lock.json"
# Prefer the repository-level state/ directory if present, else fallback to script dir
_REPO_STATE = SCRIPT_DIR.parent.parent / "state"
STATE_DIR = _REPO_STATE if _REPO_STATE.is_dir() else (Path("state") if Path("state").is_dir() else SCRIPT_DIR / "state")
STATE_PATH = STATE_DIR / "opencode_install.json"

logger = logging.getLogger("install_opencode")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file, returning an empty dict on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically write *data* as pretty-printed JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=path.name
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        # On POSIX os.rename is atomic on the same filesystem.
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def detect_platform() -> dict[str, str]:
    """Return a dict with keys: os, arch, libc, platform_key, avx2."""
    os_name = platform.system().lower()
    if os_name != "linux":
        # Only Linux is supported in the container context.
        return {
            "os": os_name,
            "arch": "unknown",
            "libc": "unknown",
            "platform_key": "unsupported",
            "avx2": "unknown",
        }

    # --- Architecture ---
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "x64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        arch = machine

    # --- Libc ---
    libc = _detect_libc()

    # --- AVX2 ---
    avx2 = _detect_avx2()

    platform_key = f"linux-{arch}-{libc}"
    return {
        "os": os_name,
        "arch": arch,
        "libc": libc,
        "platform_key": platform_key,
        "avx2": avx2,
    }


def _detect_libc() -> str:
    """Detect whether the system uses glibc or musl."""
    # Check for musl first via the dynamic linker path.
    if glob.glob("/lib/ld-musl-*"):
        return "musl"
    # Fall back to ldd --version output.
    try:
        result = subprocess.run(
            ["ldd", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        combined = (result.stdout + result.stderr).lower()
        if "musl" in combined:
            return "musl"
        if "glibc" in combined or "gnu" in combined:
            return "glibc"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    # Default assumption for Debian-based containers.
    return "glibc"


def _detect_avx2() -> str:
    """Return 'yes', 'no', or 'unknown' based on /proc/cpuinfo."""
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        flags_lines = [
            line for line in cpuinfo.splitlines() if line.startswith("flags")
        ]
        if flags_lines:
            all_flags = " ".join(flags_lines)
            return "yes" if "avx2" in all_flags else "no"
    except OSError:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _github_api_get(url: str, *, timeout: int = 30) -> Any:
    """GET a GitHub API URL and return decoded JSON."""
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "self-opencode-installer/1.0")
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download_file(url: str, dest: Path, *, timeout: int = 120) -> None:
    """Download *url* to *dest* using a temp file + rename for atomicity."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(dest.parent), suffix=".download")
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "self-opencode-installer/1.0")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            with os.fdopen(tmp_fd, "wb") as fh:
                shutil.copyfileobj(resp, fh)
        os.replace(tmp_path, str(dest))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 16)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Asset selection
# ---------------------------------------------------------------------------


def fetch_release_assets(
    repo: str, version: str, *, timeout: int = 30
) -> list[dict[str, Any]]:
    """Fetch the asset list for a tagged release from GitHub."""
    url = f"https://api.github.com/repos/{repo}/releases/tags/{version}"
    release = _github_api_get(url, timeout=timeout)
    assets: list[dict[str, Any]] = release.get("assets", [])
    return assets


def select_asset(
    assets: list[dict[str, Any]],
    platform_key: str,
    asset_patterns: dict[str, list[str]],
) -> dict[str, Any] | None:
    """Choose the matching release asset for the given platform key.

    Returns the asset dict or None if no match is found.
    """
    patterns = asset_patterns.get(platform_key)
    if not patterns:
        return None
    for asset in assets:
        name = asset.get("name", "").lower()
        if all(p.lower() in name for p in patterns):
            return asset
    return None


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def _find_checksum_asset(
    assets: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the first asset that looks like a checksum file, if any."""
    for asset in assets:
        name = asset.get("name", "").lower()
        if any(
            kw in name
            for kw in ("checksums", "sha256", "sha256sums", "checksum")
        ):
            return asset
    return None


def _parse_checksums(text: str) -> dict[str, str]:
    """Parse a standard checksums file (``hash  filename`` per line)."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and len(parts[0]) == 64:
            # parts[0] = sha256, parts[-1] = filename (may have *prefix)
            filename = parts[-1].lstrip("*")
            result[filename] = parts[0].lower()
    return result


def verify_integrity(
    downloaded: Path,
    asset_name: str,
    assets: list[dict[str, Any]],
    config: dict[str, Any],
    platform_key: str,
    *,
    timeout: int = 30,
) -> str:
    """Verify the SHA-256 of *downloaded*.

    Strategy:
    1. If the release has a checksum file, fetch it and verify.
    2. Otherwise, use trust-on-first-use (TOFU) via opencode.lock.json.

    Returns the hex sha256 on success, raises on failure.
    """
    actual_hash = _sha256_file(downloaded)

    # --- Try official checksums ---
    checksum_asset = _find_checksum_asset(assets)
    if checksum_asset:
        url = checksum_asset.get("browser_download_url", "")
        if url:
            try:
                req = urllib.request.Request(url)
                req.add_header("User-Agent", "self-opencode-installer/1.0")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    text = resp.read().decode("utf-8")
                checksums = _parse_checksums(text)
                expected = checksums.get(asset_name)
                if expected:
                    if actual_hash != expected:
                        raise RuntimeError(
                            f"Checksum mismatch for {asset_name}: "
                            f"expected {expected}, got {actual_hash}"
                        )
                    logger.info("Checksum verified against official checksums file.")
                    return actual_hash
                else:
                    logger.warning(
                        "Checksums file found but no entry for %s; falling back to TOFU.",
                        asset_name,
                    )
            except (urllib.error.URLError, OSError) as exc:
                logger.warning(
                    "Could not fetch checksums file (%s); falling back to TOFU.", exc
                )

    # --- TOFU ---
    logger.warning(
        "WARNING: Using trust-on-first-use (TOFU) integrity. "
        "No official checksum file found for this release."
    )
    lock = _load_json(LOCK_PATH)
    tofu_key = f"{config.get('opencode_version', 'unknown')}:{platform_key}"
    recorded = lock.get(tofu_key)
    if recorded:
        if actual_hash != recorded:
            raise RuntimeError(
                f"TOFU integrity failure for {tofu_key}: "
                f"expected {recorded}, got {actual_hash}. "
                "If this is a legitimate update, delete the entry from "
                f"{LOCK_PATH} and retry."
            )
        logger.info("TOFU checksum matches recorded value for %s.", tofu_key)
    else:
        logger.warning(
            "TOFU: Recording sha256 %s for %s on first use.", actual_hash, tofu_key
        )
        lock[tofu_key] = actual_hash
        _save_json(LOCK_PATH, lock)

    return actual_hash


# ---------------------------------------------------------------------------
# Install logic
# ---------------------------------------------------------------------------


def install_binary(
    downloaded: Path,
    config: dict[str, Any],
    platform_key: str,
    sha256: str,
    version: str,
) -> Path:
    """Extract or copy the downloaded asset into install_dir, create symlink.

    Returns the path to the installed binary.
    """
    install_dir = Path(config.get("install_dir", "/opt/opencode"))
    bin_link = Path(config.get("bin_link", "/usr/local/bin/opencode"))

    install_dir.mkdir(parents=True, exist_ok=True)

    asset_name = downloaded.name.lower()
    # Determine extraction method.
    if asset_name.endswith(".tar.gz") or asset_name.endswith(".tgz"):
        _extract_tar(downloaded, install_dir)
    elif asset_name.endswith(".zip"):
        _extract_zip(downloaded, install_dir)
    else:
        # Assume raw binary.
        dest = install_dir / "opencode"
        shutil.copy2(str(downloaded), str(dest))

    # Locate the binary inside install_dir.
    binary = _find_binary(install_dir)
    if not binary:
        raise RuntimeError(
            f"Could not find opencode binary in {install_dir} after extraction."
        )

    # Make binary and dir world-readable/executable.
    binary.chmod(0o755)
    _chmod_recursive(install_dir, dir_mode=0o755, file_mode=0o644)
    binary.chmod(0o755)

    # Symlink.
    bin_link.parent.mkdir(parents=True, exist_ok=True)
    if bin_link.exists() or bin_link.is_symlink():
        bin_link.unlink()
    bin_link.symlink_to(binary)

    return binary


def _extract_tar(archive: Path, dest: Path) -> None:
    """Extract a tar.gz archive into *dest*."""
    import tarfile

    with tarfile.open(str(archive), "r:gz") as tf:
        tf.extractall(path=str(dest))


def _extract_zip(archive: Path, dest: Path) -> None:
    """Extract a zip archive into *dest*."""
    import zipfile

    with zipfile.ZipFile(str(archive), "r") as zf:
        zf.extractall(path=str(dest))


def _find_binary(install_dir: Path) -> Path | None:
    """Find the opencode binary inside install_dir (may be nested one level)."""
    # Direct file.
    candidate = install_dir / "opencode"
    if candidate.is_file():
        return candidate
    # Search one level deep.
    for child in install_dir.rglob("opencode"):
        if child.is_file() and not child.suffix:
            return child
    # Also check for any file named opencode* that is executable-looking.
    for child in install_dir.rglob("opencode*"):
        if child.is_file() and not child.name.endswith((".json", ".md", ".txt", ".yml")):
            return child
    return None


def _chmod_recursive(
    root: Path, *, dir_mode: int = 0o755, file_mode: int = 0o644
) -> None:
    """Set permissions recursively."""
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dp = Path(dirpath)
        try:
            dp.chmod(dir_mode)
        except OSError:
            pass
        for fn in filenames:
            try:
                (dp / fn).chmod(file_mode)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------


def generate_opencode_config(config: dict[str, Any], install_dir: Path) -> Path:
    """Generate the opencode.json configuration in the config subdirectory.

    Settings use key names sourced from opencode documentation. Keys that could
    not be verified against the installed binary's help are marked UNVERIFIED.
    """
    config_dir = install_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "opencode.json"

    providers_cfg = config.get("providers", {})

    opencode_config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        # VERIFIED: disable auto-update (from opencode docs)
        "autoupdate": False,
        # VERIFIED: disable session sharing (from opencode docs)
        "share": "disabled",
        # UNVERIFIED: experimental telemetry toggle
        "experimental": {
            "openTelemetry": False,
        },
        # VERIFIED: permission block (from opencode docs)
        "permission": {
            "shell": "allow",
            "bash": "allow",
            "edit": "allow",
        },
        # VERIFIED: provider settings with env var references (from opencode docs)
        "providers": {},
    }

    # Build provider config referencing env vars, not raw keys.
    for provider_name, provider_info in providers_cfg.items():
        if isinstance(provider_info, dict):
            env_var = provider_info.get("env_var_opencode_expects", "")
            if env_var:
                opencode_config["providers"][provider_name] = {
                    "settings": {
                        "apiKey": "{env:" + env_var + "}",
                    }
                }

    _save_json(config_file, opencode_config)
    _chmod_recursive(config_dir, dir_mode=0o755, file_mode=0o644)

    logger.info("Generated opencode config at %s", config_file)
    return config_file


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def _read_state() -> dict[str, Any]:
    return _load_json(STATE_PATH)


def _write_state(state: dict[str, Any]) -> None:
    _save_json(STATE_PATH, state)


def _update_state(
    *,
    platform_key: str = "",
    version: str = "",
    sha256: str = "",
    binary_path: str = "",
    last_error: str = "",
) -> None:
    state = _read_state()
    if platform_key:
        state["platform_key"] = platform_key
    if version:
        state["version"] = version
    if sha256:
        state["sha256"] = sha256
    if binary_path:
        state["binary_path"] = binary_path
    state["installed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if last_error:
        state["last_error"] = last_error
    elif "last_error" in state:
        state["last_error"] = ""
    _write_state(state)


# ---------------------------------------------------------------------------
# Binary health check
# ---------------------------------------------------------------------------


def _binary_works(bin_link: str) -> bool:
    """Return True if the binary at *bin_link* runs successfully."""
    try:
        result = subprocess.run(
            [bin_link, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Core workflow
# ---------------------------------------------------------------------------


def do_install(
    config: dict[str, Any],
    plat: dict[str, str],
    *,
    strict: bool = False,
) -> bool:
    """Download, verify, and install. Returns True on success."""
    version = config.get("opencode_version", "")
    if not version or version.startswith("_PLACEHOLDER"):
        msg = (
            "opencode_version in config.json is not set. "
            "Please pin an exact version (e.g. v2.0.30) before running the installer."
        )
        logger.error(msg)
        _update_state(
            platform_key=plat["platform_key"],
            version=version,
            last_error=msg,
        )
        if strict:
            raise RuntimeError(msg)
        return False

    repo = config.get("github_repo", "anomalyco/opencode")
    timeout = int(config.get("download_timeout_seconds", 120))
    retries = int(config.get("retry_count", 3))
    asset_patterns = config.get("asset_patterns", {})

    # Fetch release assets.
    last_exc: Exception | None = None
    assets: list[dict[str, Any]] = []
    for attempt in range(1, retries + 1):
        try:
            logger.info(
                "Fetching release %s from %s (attempt %d/%d)",
                version, repo, attempt, retries,
            )
            assets = fetch_release_assets(repo, version, timeout=timeout)
            break
        except Exception as exc:
            last_exc = exc
            logger.warning("Attempt %d failed: %s", attempt, exc)
            if attempt < retries:
                time.sleep(2 ** attempt)

    if not assets:
        msg = f"Could not fetch release assets after {retries} attempts: {last_exc}"
        logger.error(msg)
        _update_state(
            platform_key=plat["platform_key"],
            version=version,
            last_error=msg,
        )
        if strict:
            raise RuntimeError(msg)
        return False

    # Select asset.
    asset = select_asset(assets, plat["platform_key"], asset_patterns)
    if not asset:
        available = [a.get("name", "?") for a in assets]
        msg = (
            f"No release asset matches platform key '{plat['platform_key']}'. "
            f"Available assets: {available}"
        )
        logger.error(msg)
        _update_state(
            platform_key=plat["platform_key"],
            version=version,
            last_error=msg,
        )
        if strict:
            raise RuntimeError(msg)
        return False

    # Download.
    download_url = asset.get("browser_download_url", "")
    asset_name = asset.get("name", "opencode-download")
    if not download_url:
        msg = f"Asset {asset_name} has no download URL."
        logger.error(msg)
        _update_state(
            platform_key=plat["platform_key"],
            version=version,
            last_error=msg,
        )
        return False

    tmp_dir = Path(tempfile.mkdtemp(prefix="opencode-"))
    downloaded = tmp_dir / asset_name
    try:
        for attempt in range(1, retries + 1):
            try:
                logger.info(
                    "Downloading %s (attempt %d/%d)", asset_name, attempt, retries
                )
                _download_file(download_url, downloaded, timeout=timeout)
                break
            except Exception as exc:
                last_exc = exc
                logger.warning("Download attempt %d failed: %s", attempt, exc)
                if attempt < retries:
                    time.sleep(2 ** attempt)
        else:
            msg = f"Download failed after {retries} attempts: {last_exc}"
            logger.error(msg)
            _update_state(
                platform_key=plat["platform_key"],
                version=version,
                last_error=msg,
            )
            if strict:
                raise RuntimeError(msg)
            return False

        # Verify.
        sha256 = verify_integrity(
            downloaded, asset_name, assets, config, plat["platform_key"],
            timeout=timeout,
        )

        # Install.
        binary = install_binary(downloaded, config, plat["platform_key"], sha256, version)

        # Generate config.
        install_dir = Path(config.get("install_dir", "/opt/opencode"))
        generate_opencode_config(config, install_dir)

        # Update state.
        _update_state(
            platform_key=plat["platform_key"],
            version=version,
            sha256=sha256,
            binary_path=str(binary),
        )
        logger.info("opencode %s installed successfully at %s", version, binary)
        return True

    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def cmd_build(config: dict[str, Any], *, strict: bool = False) -> int:
    """--build: install at image build time."""
    plat = detect_platform()
    logger.info("Platform: %s", plat)
    success = do_install(config, plat, strict=strict)
    if not success:
        if strict:
            return 1
        logger.warning(
            "opencode install failed during build (non-strict); container will "
            "attempt --ensure at startup."
        )
    return 0


def cmd_ensure(config: dict[str, Any]) -> int:
    """--ensure: idempotent startup check. Always returns 0."""
    plat = detect_platform()
    state = _read_state()
    bin_link = config.get("bin_link", "/usr/local/bin/opencode")

    # Check if already installed and working.
    if (
        state.get("platform_key") == plat["platform_key"]
        and state.get("version") == config.get("opencode_version")
        and _binary_works(bin_link)
    ):
        logger.info("opencode is already installed and working. Nothing to do.")
        return 0

    logger.info("opencode needs (re)install. Platform: %s", plat)
    try:
        do_install(config, plat, strict=False)
    except Exception as exc:
        msg = f"Ensure install failed: {exc}"
        logger.warning(msg)
        _update_state(
            platform_key=plat["platform_key"],
            version=config.get("opencode_version", ""),
            last_error=msg,
        )
    # Always exit 0 - opencode is optional.
    return 0


def cmd_force(config: dict[str, Any]) -> int:
    """--force: reinstall regardless of state."""
    plat = detect_platform()
    logger.info("Force reinstall. Platform: %s", plat)
    success = do_install(config, plat, strict=False)
    return 0 if success else 1


def cmd_status(config: dict[str, Any]) -> int:
    """--status: print install state."""
    state = _read_state()
    plat = detect_platform()
    bin_link = config.get("bin_link", "/usr/local/bin/opencode")
    works = _binary_works(bin_link)

    print(json.dumps({
        "installed_state": state,
        "detected_platform": plat,
        "binary_works": works,
        "config_version": config.get("opencode_version", ""),
    }, indent=2))
    return 0


def cmd_list_models(config: dict[str, Any]) -> int:
    """--list-models: attempt to list models from the installed binary."""
    bin_link = config.get("bin_link", "/usr/local/bin/opencode")
    if not _binary_works(bin_link):
        logger.info("opencode is not installed or not working. Cannot list models.")
        return 0

    # Try common model-listing commands.
    for cmd in [
        [bin_link, "models"],
        [bin_link, "model", "list"],
        [bin_link, "--list-models"],
    ]:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                print(result.stdout)
                return 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue

    logger.info("Could not find a model-listing command in the installed opencode.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Opencode binary installer for the Self agent container."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true", help="Install at image build time.")
    group.add_argument("--ensure", action="store_true", help="Idempotent startup check.")
    group.add_argument("--force", action="store_true", help="Force reinstall.")
    group.add_argument("--status", action="store_true", help="Print current state.")
    group.add_argument("--list-models", action="store_true", help="List available models.")
    parser.add_argument(
        "--strict", action="store_true",
        help="With --build, exit non-zero on any failure.",
    )
    parser.add_argument(
        "--config", type=str, default=str(CONFIG_PATH),
        help="Path to config.json.",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="[opencode-installer] %(levelname)s: %(message)s",
    )

    config_path = Path(args.config)
    config = _load_json(config_path)
    if not config:
        logger.error("Could not load config from %s", config_path)
        return 1

    if args.build:
        return cmd_build(config, strict=args.strict)
    elif args.ensure:
        return cmd_ensure(config)
    elif args.force:
        return cmd_force(config)
    elif args.status:
        return cmd_status(config)
    elif args.list_models:
        return cmd_list_models(config)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
