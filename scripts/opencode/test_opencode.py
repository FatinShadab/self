"""Unit tests for the opencode installer.

All tests run without network access. Platform detection, asset selection,
checksum verification, TOFU lock behaviour, and --ensure decision logic are
covered with mocked values.
"""
from __future__ import annotations

import hashlib
import base64
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

# Ensure the scripts directory is importable.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "opencode"))
import install_opencode as installer


class TestPlatformDetection(unittest.TestCase):
    """Platform detection with mocked values for several combinations."""

    @mock.patch("install_opencode.platform.system", return_value="Linux")
    @mock.patch("install_opencode.platform.machine", return_value="x86_64")
    @mock.patch("install_opencode._detect_libc", return_value="glibc")
    @mock.patch("install_opencode._detect_avx2", return_value="yes")
    def test_linux_x64_glibc(self, *_mocks):
        result = installer.detect_platform()
        self.assertEqual(result["os"], "linux")
        self.assertEqual(result["arch"], "x64")
        self.assertEqual(result["libc"], "glibc")
        self.assertEqual(result["platform_key"], "linux-x64-glibc")
        self.assertEqual(result["avx2"], "yes")

    @mock.patch("install_opencode.platform.system", return_value="Linux")
    @mock.patch("install_opencode.platform.machine", return_value="aarch64")
    @mock.patch("install_opencode._detect_libc", return_value="glibc")
    @mock.patch("install_opencode._detect_avx2", return_value="unknown")
    def test_linux_arm64_glibc(self, *_mocks):
        result = installer.detect_platform()
        self.assertEqual(result["arch"], "arm64")
        self.assertEqual(result["platform_key"], "linux-arm64-glibc")

    @mock.patch("install_opencode.platform.system", return_value="Linux")
    @mock.patch("install_opencode.platform.machine", return_value="x86_64")
    @mock.patch("install_opencode._detect_libc", return_value="musl")
    @mock.patch("install_opencode._detect_avx2", return_value="no")
    def test_linux_x64_musl(self, *_mocks):
        result = installer.detect_platform()
        self.assertEqual(result["libc"], "musl")
        self.assertEqual(result["platform_key"], "linux-x64-musl")
        self.assertEqual(result["avx2"], "no")

    @mock.patch("install_opencode.platform.system", return_value="Linux")
    @mock.patch("install_opencode.platform.machine", return_value="arm64")
    @mock.patch("install_opencode._detect_libc", return_value="musl")
    @mock.patch("install_opencode._detect_avx2", return_value="unknown")
    def test_linux_arm64_musl(self, *_mocks):
        result = installer.detect_platform()
        self.assertEqual(result["arch"], "arm64")
        self.assertEqual(result["platform_key"], "linux-arm64-musl")

    @mock.patch("install_opencode.platform.system", return_value="Darwin")
    def test_non_linux(self, *_mocks):
        result = installer.detect_platform()
        self.assertEqual(result["platform_key"], "unsupported")

    @mock.patch("install_opencode.platform.system", return_value="Linux")
    @mock.patch("install_opencode.platform.machine", return_value="amd64")
    @mock.patch("install_opencode._detect_libc", return_value="glibc")
    @mock.patch("install_opencode._detect_avx2", return_value="yes")
    def test_amd64_alias(self, *_mocks):
        result = installer.detect_platform()
        self.assertEqual(result["arch"], "x64")


class TestLibcDetection(unittest.TestCase):
    """Libc detection edge cases."""

    @mock.patch("install_opencode.glob.glob", return_value=["/lib/ld-musl-x86_64.so.1"])
    def test_musl_via_glob(self, _mock):
        self.assertEqual(installer._detect_libc(), "musl")

    @mock.patch("install_opencode.glob.glob", return_value=[])
    @mock.patch("install_opencode.subprocess.run")
    def test_glibc_via_ldd(self, mock_run, _mock_glob):
        mock_run.return_value = mock.Mock(
            stdout="ldd (GNU libc) 2.31", stderr="", returncode=0
        )
        self.assertEqual(installer._detect_libc(), "glibc")

    @mock.patch("install_opencode.glob.glob", return_value=[])
    @mock.patch("install_opencode.subprocess.run")
    def test_musl_via_ldd(self, mock_run, _mock_glob):
        mock_run.return_value = mock.Mock(
            stdout="musl libc\nVersion 1.2.3", stderr="", returncode=0
        )
        self.assertEqual(installer._detect_libc(), "musl")

    @mock.patch("install_opencode.glob.glob", return_value=[])
    @mock.patch("install_opencode.subprocess.run", side_effect=FileNotFoundError)
    def test_fallback_to_glibc(self, *_mocks):
        self.assertEqual(installer._detect_libc(), "glibc")


class TestAvx2Detection(unittest.TestCase):

    def test_avx2_present(self):
        cpuinfo = "flags\t\t: fpu vme de sse sse2 avx avx2 bmi1\n"
        with mock.patch.object(Path, "read_text", return_value=cpuinfo):
            self.assertEqual(installer._detect_avx2(), "yes")

    def test_avx2_absent(self):
        cpuinfo = "flags\t\t: fpu vme de sse sse2 avx bmi1\n"
        with mock.patch.object(Path, "read_text", return_value=cpuinfo):
            self.assertEqual(installer._detect_avx2(), "no")

    def test_cpuinfo_missing(self):
        with mock.patch.object(Path, "read_text", side_effect=OSError):
            self.assertEqual(installer._detect_avx2(), "unknown")


class TestAssetSelection(unittest.TestCase):
    """Asset selection against a fake releases JSON."""

    FAKE_ASSETS = [
        {"name": "opencode-linux-x64.tar.gz", "browser_download_url": "https://example.com/x64.tar.gz"},
        {"name": "opencode-linux-arm64.tar.gz", "browser_download_url": "https://example.com/arm64.tar.gz"},
        {"name": "opencode-darwin-arm64.zip", "browser_download_url": "https://example.com/darwin.zip"},
        {"name": "opencode-windows-x64.zip", "browser_download_url": "https://example.com/win.zip"},
        {"name": "checksums.txt", "browser_download_url": "https://example.com/checksums.txt"},
    ]

    PATTERNS = {
        "linux-x64-glibc": ["linux", "x64"],
        "linux-x64-musl": ["linux", "x64"],
        "linux-arm64-glibc": ["linux", "arm64"],
        "linux-arm64-musl": ["linux", "arm64"],
    }

    def test_select_linux_x64(self):
        asset = installer.select_asset(self.FAKE_ASSETS, "linux-x64-glibc", self.PATTERNS)
        self.assertIsNotNone(asset)
        self.assertEqual(asset["name"], "opencode-linux-x64.tar.gz")

    def test_select_linux_arm64(self):
        asset = installer.select_asset(self.FAKE_ASSETS, "linux-arm64-glibc", self.PATTERNS)
        self.assertIsNotNone(asset)
        self.assertEqual(asset["name"], "opencode-linux-arm64.tar.gz")

    def test_no_match(self):
        asset = installer.select_asset(self.FAKE_ASSETS, "linux-riscv64-glibc", self.PATTERNS)
        self.assertIsNone(asset)

    def test_no_patterns_for_key(self):
        asset = installer.select_asset(self.FAKE_ASSETS, "freebsd-x64", self.PATTERNS)
        self.assertIsNone(asset)


class TestNpmAsset(unittest.TestCase):
    @mock.patch("install_opencode.urllib.request.urlopen")
    def test_npm_request_uses_json_accept_header(self, urlopen):
        response = mock.MagicMock()
        response.read.return_value = b'{"name":"@opencode/cli-linux-x64"}'
        response.__enter__.return_value = response
        urlopen.return_value = response

        metadata = installer._npm_api_get("https://registry.npmjs.org/@opencode%2fcli-linux-x64/2.0.30")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(metadata["name"], "@opencode/cli-linux-x64")

    def test_extracts_only_npm_cli_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "cli.tgz"
            payload = b"fake executable"
            with tarfile.open(archive, "w:gz") as package:
                binary = tarfile.TarInfo("package/bin/opencode")
                binary.size = len(payload)
                package.addfile(binary, io.BytesIO(payload))
                ignored = tarfile.TarInfo("package/other.txt")
                ignored.size = 4
                package.addfile(ignored, io.BytesIO(b"skip"))
            installer._extract_npm_binary(archive, root)
            self.assertEqual((root / "opencode").read_bytes(), payload)
            self.assertFalse((root / "other.txt").exists())

    @mock.patch("install_opencode._update_state")
    @mock.patch("install_opencode.generate_opencode_config")
    @mock.patch("install_opencode.install_binary", return_value=Path("/opt/opencode/opencode"))
    @mock.patch("install_opencode.verify_integrity", return_value="abc")
    @mock.patch("install_opencode._download_file")
    @mock.patch("install_opencode.fetch_npm_asset")
    @mock.patch("install_opencode.fetch_release_assets")
    def test_install_uses_npm_for_v2(
        self, github_assets, npm_asset, download, verify, install, generate, update
    ):
        npm_asset.return_value = {
            "name": "cli-linux-x64-2.0.30.tgz",
            "browser_download_url": "https://registry.npmjs.org/package.tgz",
            "integrity": "sha512-YWJj",
        }
        config = {
            "opencode_version": "v2.0.30", "source": "npm", "retry_count": 1,
            "install_dir": "/opt/opencode",
        }
        plat = {"platform_key": "linux-x64-glibc", "arch": "x64", "libc": "glibc", "avx2": "yes"}
        self.assertTrue(installer.do_install(config, plat))
        npm_asset.assert_called_once()
        github_assets.assert_not_called()
        self.assertEqual(verify.call_args.kwargs["npm_integrity"], "sha512-YWJj")

    @mock.patch("install_opencode._npm_api_get")
    def test_pinned_platform_package(self, get_json):
        get_json.return_value = {
            "name": "@opencode/cli-linux-x64",
            "version": "2.0.30",
            "dist": {
                "tarball": "https://registry.npmjs.org/@opencode/cli-linux-x64/-/cli-linux-x64-2.0.30.tgz",
                "integrity": "sha512-" + base64.b64encode(b"digest").decode(),
            },
        }
        plat = {"arch": "x64", "libc": "glibc", "avx2": "yes"}
        asset = installer.fetch_npm_asset("v2.0.30", plat)
        self.assertEqual(asset["name"], "cli-linux-x64-2.0.30.tgz")
        self.assertIn("cli-linux-x64/2.0.30", get_json.call_args.args[0])

    @mock.patch("install_opencode._npm_api_get")
    def test_baseline_and_musl_target(self, get_json):
        get_json.return_value = {
            "name": "@opencode/cli-linux-x64-baseline-musl",
            "version": "2.0.30",
            "dist": {"tarball": "https://example.test/package.tgz", "integrity": "sha512-YWJj"},
        }
        plat = {"arch": "x64", "libc": "musl", "avx2": "no"}
        installer.fetch_npm_asset("v2.0.30", plat)
        self.assertIn("cli-linux-x64-baseline-musl/2.0.30", get_json.call_args.args[0])

    @mock.patch("install_opencode._npm_api_get")
    def test_missing_integrity_is_rejected(self, get_json):
        get_json.return_value = {
            "name": "@opencode/cli-linux-arm64",
            "version": "2.0.30",
            "dist": {"tarball": "https://example.test/package.tgz"},
        }
        with self.assertRaisesRegex(RuntimeError, "integrity"):
            installer.fetch_npm_asset("v2.0.30", {"arch": "arm64", "libc": "glibc", "avx2": "unknown"})


class TestChecksumVerification(unittest.TestCase):
    """Checksum verification pass/fail and TOFU lock behaviour."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.test_file = Path(self.tmpdir) / "test_binary"
        self.test_file.write_bytes(b"test content for hashing")
        self.expected_hash = hashlib.sha256(b"test content for hashing").hexdigest()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_npm_sha512_verification(self):
        integrity = "sha512-" + base64.b64encode(hashlib.sha512(self.test_file.read_bytes()).digest()).decode()
        result = installer.verify_integrity(
            self.test_file, "test_binary", [], {}, "linux-x64-glibc", npm_integrity=integrity
        )
        self.assertEqual(result, self.expected_hash)
        with self.assertRaisesRegex(RuntimeError, "integrity mismatch"):
            installer.verify_integrity(
                self.test_file, "test_binary", [], {}, "linux-x64-glibc",
                npm_integrity="sha512-" + base64.b64encode(b"wrong").decode(),
            )

    def test_checksum_pass_with_official_file(self):
        """Verify passes when the official checksums file contains the correct hash."""
        checksum_text = f"{self.expected_hash}  test_binary\n"
        assets = [
            {"name": "test_binary", "browser_download_url": "https://example.com/bin"},
            {"name": "checksums.txt", "browser_download_url": "https://example.com/checksums.txt"},
        ]

        with mock.patch("install_opencode.urllib.request.urlopen") as mock_urlopen:
            mock_resp = mock.MagicMock()
            mock_resp.read.return_value = checksum_text.encode("utf-8")
            mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
            mock_resp.__exit__ = mock.Mock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = installer.verify_integrity(
                self.test_file, "test_binary", assets, {}, "linux-x64-glibc"
            )
            self.assertEqual(result, self.expected_hash)

    def test_checksum_fail_with_official_file(self):
        """Verify raises when the official checksums file has a wrong hash."""
        bad_hash = "a" * 64
        checksum_text = f"{bad_hash}  test_binary\n"
        assets = [
            {"name": "test_binary", "browser_download_url": "https://example.com/bin"},
            {"name": "checksums.txt", "browser_download_url": "https://example.com/checksums.txt"},
        ]

        with mock.patch("install_opencode.urllib.request.urlopen") as mock_urlopen:
            mock_resp = mock.MagicMock()
            mock_resp.read.return_value = checksum_text.encode("utf-8")
            mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
            mock_resp.__exit__ = mock.Mock(return_value=False)
            mock_urlopen.return_value = mock_resp

            with self.assertRaises(RuntimeError) as ctx:
                installer.verify_integrity(
                    self.test_file, "test_binary", assets, {}, "linux-x64-glibc"
                )
            self.assertIn("Checksum mismatch", str(ctx.exception))

    def test_tofu_first_use(self):
        """TOFU records the hash on first use."""
        lock_path = Path(self.tmpdir) / "opencode.lock.json"
        assets = [{"name": "test_binary", "browser_download_url": "https://example.com/bin"}]
        config = {"opencode_version": "v2.0.30"}

        with mock.patch.object(installer, "LOCK_PATH", lock_path):
            result = installer.verify_integrity(
                self.test_file, "test_binary", assets, config, "linux-x64-glibc"
            )
            self.assertEqual(result, self.expected_hash)
            lock_data = json.loads(lock_path.read_text())
            self.assertEqual(lock_data["v2.0.30:linux-x64-glibc"], self.expected_hash)

    def test_tofu_repeat_matches(self):
        """TOFU passes when recorded hash matches."""
        lock_path = Path(self.tmpdir) / "opencode.lock.json"
        lock_path.write_text(json.dumps({"v2.0.30:linux-x64-glibc": self.expected_hash}))
        assets = [{"name": "test_binary", "browser_download_url": "https://example.com/bin"}]
        config = {"opencode_version": "v2.0.30"}

        with mock.patch.object(installer, "LOCK_PATH", lock_path):
            result = installer.verify_integrity(
                self.test_file, "test_binary", assets, config, "linux-x64-glibc"
            )
            self.assertEqual(result, self.expected_hash)

    def test_tofu_mismatch_raises(self):
        """TOFU raises when recorded hash does not match."""
        lock_path = Path(self.tmpdir) / "opencode.lock.json"
        lock_path.write_text(json.dumps({"v2.0.30:linux-x64-glibc": "b" * 64}))
        assets = [{"name": "test_binary", "browser_download_url": "https://example.com/bin"}]
        config = {"opencode_version": "v2.0.30"}

        with mock.patch.object(installer, "LOCK_PATH", lock_path):
            with self.assertRaises(RuntimeError) as ctx:
                installer.verify_integrity(
                    self.test_file, "test_binary", assets, config, "linux-x64-glibc"
                )
            self.assertIn("TOFU integrity failure", str(ctx.exception))


class TestEnsureDecisions(unittest.TestCase):
    """--ensure decision logic for various states."""

    def _make_config(self) -> dict:
        return {
            "opencode_version": "v2.0.30",
            "github_repo": "anomalyco/opencode",
            "install_dir": "/opt/opencode",
            "bin_link": "/usr/local/bin/opencode",
            "download_timeout_seconds": 30,
            "retry_count": 1,
            "asset_patterns": {"linux-x64-glibc": ["linux", "x64"]},
        }

    @mock.patch("install_opencode._read_state")
    @mock.patch("install_opencode._binary_works", return_value=True)
    @mock.patch("install_opencode.detect_platform")
    def test_already_installed_does_nothing(self, mock_plat, mock_works, mock_state):
        """If binary works and state matches, no reinstall."""
        mock_plat.return_value = {
            "os": "linux", "arch": "x64", "libc": "glibc",
            "platform_key": "linux-x64-glibc", "avx2": "yes",
        }
        mock_state.return_value = {
            "platform_key": "linux-x64-glibc",
            "version": "v2.0.30",
        }
        config = self._make_config()

        with mock.patch("install_opencode.do_install") as mock_install:
            rc = installer.cmd_ensure(config)
            self.assertEqual(rc, 0)
            mock_install.assert_not_called()

    @mock.patch("install_opencode._read_state")
    @mock.patch("install_opencode._binary_works", return_value=False)
    @mock.patch("install_opencode.detect_platform")
    @mock.patch("install_opencode.do_install", return_value=True)
    def test_binary_missing_triggers_install(self, mock_install, mock_plat, mock_works, mock_state):
        """If binary doesn't work, reinstall is attempted."""
        mock_plat.return_value = {
            "os": "linux", "arch": "x64", "libc": "glibc",
            "platform_key": "linux-x64-glibc", "avx2": "yes",
        }
        mock_state.return_value = {
            "platform_key": "linux-x64-glibc",
            "version": "v2.0.30",
        }
        config = self._make_config()

        rc = installer.cmd_ensure(config)
        self.assertEqual(rc, 0)
        mock_install.assert_called_once()

    @mock.patch("install_opencode._read_state")
    @mock.patch("install_opencode._binary_works", return_value=True)
    @mock.patch("install_opencode.detect_platform")
    @mock.patch("install_opencode.do_install", return_value=True)
    def test_platform_changed_triggers_install(self, mock_install, mock_plat, mock_works, mock_state):
        """If platform key changed, reinstall is attempted."""
        mock_plat.return_value = {
            "os": "linux", "arch": "arm64", "libc": "glibc",
            "platform_key": "linux-arm64-glibc", "avx2": "unknown",
        }
        mock_state.return_value = {
            "platform_key": "linux-x64-glibc",
            "version": "v2.0.30",
        }
        config = self._make_config()

        rc = installer.cmd_ensure(config)
        self.assertEqual(rc, 0)
        mock_install.assert_called_once()

    @mock.patch("install_opencode._read_state")
    @mock.patch("install_opencode._binary_works", return_value=False)
    @mock.patch("install_opencode.detect_platform")
    @mock.patch("install_opencode.do_install", side_effect=RuntimeError("network down"))
    @mock.patch("install_opencode._update_state")
    def test_download_failure_exits_zero(self, mock_update, mock_install, mock_plat, mock_works, mock_state):
        """Download failure during --ensure always exits 0."""
        mock_plat.return_value = {
            "os": "linux", "arch": "x64", "libc": "glibc",
            "platform_key": "linux-x64-glibc", "avx2": "yes",
        }
        mock_state.return_value = {}
        config = self._make_config()

        rc = installer.cmd_ensure(config)
        self.assertEqual(rc, 0)
        # State should be updated with last_error.
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args
        self.assertIn("network down", call_kwargs.kwargs.get("last_error", ""))

    @mock.patch("install_opencode._read_state")
    @mock.patch("install_opencode._binary_works", return_value=True)
    @mock.patch("install_opencode.detect_platform")
    @mock.patch("install_opencode.do_install", return_value=True)
    def test_version_changed_triggers_install(self, mock_install, mock_plat, mock_works, mock_state):
        """If config version differs from state version, reinstall."""
        mock_plat.return_value = {
            "os": "linux", "arch": "x64", "libc": "glibc",
            "platform_key": "linux-x64-glibc", "avx2": "yes",
        }
        mock_state.return_value = {
            "platform_key": "linux-x64-glibc",
            "version": "v2.0.29",  # older than config
        }
        config = self._make_config()

        rc = installer.cmd_ensure(config)
        self.assertEqual(rc, 0)
        mock_install.assert_called_once()


class TestConfigGeneration(unittest.TestCase):
    """Opencode config generation."""

    def test_generates_valid_config(self):
        tmpdir = tempfile.mkdtemp()
        try:
            install_dir = Path(tmpdir) / "opencode"
            install_dir.mkdir()
            config = {
                "providers": {
                    "groq": {
                        "env_var_opencode_expects": "GROQ_API_KEY",
                        "env_var_self_namespace": "OPENCODE_GROQ_API_KEY",
                    },
                    "google": {
                        "env_var_opencode_expects": "GEMINI_API_KEY",
                        "env_var_self_namespace": "OPENCODE_GOOGLE_API_KEY",
                    },
                },
            }
            config_file = installer.generate_opencode_config(config, install_dir)
            self.assertTrue(config_file.exists())
            data = json.loads(config_file.read_text())
            self.assertFalse(data["autoupdate"])
            self.assertEqual(data["share"], "disabled")
            self.assertEqual(data["permission"]["shell"], "allow")
            self.assertEqual(data["permission"]["bash"], "allow")
            self.assertEqual(data["permission"]["edit"], "allow")
            self.assertFalse(data["experimental"]["openTelemetry"])
            self.assertEqual(
                data["providers"]["groq"]["settings"]["apiKey"],
                "{env:GROQ_API_KEY}",
            )
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestPlaceholderVersion(unittest.TestCase):
    """Installer refuses to run with placeholder version."""

    @mock.patch("install_opencode._update_state")
    def test_placeholder_version_fails(self, mock_update):
        config = {
            "opencode_version": "_PLACEHOLDER",
            "github_repo": "anomalyco/opencode",
        }
        plat = {"platform_key": "linux-x64-glibc"}
        result = installer.do_install(config, plat, strict=False)
        self.assertFalse(result)

    @mock.patch("install_opencode._update_state")
    def test_empty_version_fails(self, mock_update):
        config = {
            "opencode_version": "",
            "github_repo": "anomalyco/opencode",
        }
        plat = {"platform_key": "linux-x64-glibc"}
        result = installer.do_install(config, plat, strict=False)
        self.assertFalse(result)


class TestParseChecksums(unittest.TestCase):
    """Parsing of checksum files in various formats."""

    def test_standard_format(self):
        text = textwrap.dedent("""\
            abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234  opencode-linux-x64.tar.gz
            1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd  opencode-linux-arm64.tar.gz
        """)
        result = installer._parse_checksums(text)
        self.assertEqual(
            result["opencode-linux-x64.tar.gz"],
            "abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234",
        )

    def test_bsd_star_prefix(self):
        text = "abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234 *opencode-linux-x64.tar.gz\n"
        result = installer._parse_checksums(text)
        self.assertIn("opencode-linux-x64.tar.gz", result)

    def test_empty_file(self):
        result = installer._parse_checksums("")
        self.assertEqual(result, {})


class TestStateManagement(unittest.TestCase):
    """State file read/write."""

    def test_roundtrip(self):
        tmpdir = tempfile.mkdtemp()
        try:
            state_path = Path(tmpdir) / "state" / "opencode_install.json"
            with mock.patch.object(installer, "STATE_PATH", state_path):
                installer._update_state(
                    platform_key="linux-x64-glibc",
                    version="v2.0.30",
                    sha256="abc123",
                    binary_path="/opt/opencode/opencode",
                )
                state = installer._read_state()
                self.assertEqual(state["platform_key"], "linux-x64-glibc")
                self.assertEqual(state["version"], "v2.0.30")
                self.assertEqual(state["sha256"], "abc123")
                self.assertIn("installed_at", state)
                self.assertEqual(state.get("last_error", ""), "")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
