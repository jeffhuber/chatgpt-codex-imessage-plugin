from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._helper_loader import REPO_ROOT, helper


class LaunchAgentIdentityTests(unittest.TestCase):
    def test_installers_and_uninstallers_use_only_openai_identity(self) -> None:
        for name in ("install.sh", "install-hardened.sh", "uninstall.sh", "uninstall-hardened.sh"):
            source = (REPO_ROOT / name).read_text()
            self.assertIn("com.jeffhuber.chatgpt-codex-imessage", source, name)
            self.assertNotIn("com.jeffhuber.claudecowork-imessage", source, name)
            self.assertNotIn("com.jeffhuber.grokbot-imessage", source, name)

        template = (REPO_ROOT / "com.jeffhuber.chatgpt-codex-imessage.plist.template").read_text()
        self.assertIn("<string>com.jeffhuber.chatgpt-codex-imessage</string>", template)
        self.assertIn("{{CODE_ROOT}}/bin/chatgpt-codex-imessage-helper", template)


class PythonSelectionTests(unittest.TestCase):
    selector = REPO_ROOT / "tools" / "select_python.sh"

    def select(
        self,
        function: str,
        env: dict[str, str],
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; shift; "$@"',
                "selector-test",
                str(self.selector),
                function,
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    def test_selectors_skip_bad_path_python_and_honor_valid_overrides(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-python-selector-") as td:
            fake_bin = Path(td)
            unsupported = fake_bin / "python3"
            unsupported.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            unsupported.chmod(0o755)
            supported = fake_bin / "python3.12"
            supported.symlink_to(sys.executable)
            env = os.environ.copy()
            env.pop("IMESSAGE_HELPER_PYTHON", None)
            env.pop("IMESSAGE_PYTHON", None)

            mcp = self.select("find_mcp_python", env, str(fake_bin))
            self.assertEqual(mcp.returncode, 0, mcp.stderr)
            selected_mcp = Path(mcp.stdout.strip())
            self.assertNotEqual(selected_mcp, unsupported)
            mcp_probe = subprocess.run(
                [
                    str(selected_mcp),
                    "-c",
                    "import sys; raise SystemExit(sys.version_info < (3, 10))",
                ],
                check=False,
            )
            self.assertEqual(mcp_probe.returncode, 0)

            helper = self.select("find_helper_python", env, str(fake_bin))
            self.assertEqual(helper.returncode, 0, helper.stderr)
            selected_helper = Path(helper.stdout.strip())
            self.assertNotEqual(selected_helper, unsupported)
            helper_probe = subprocess.run(
                [
                    str(selected_helper),
                    "-c",
                    "import os, sys; raise SystemExit("
                    "sys.version_info < (3, 9) or "
                    "os.open not in os.supports_dir_fd)",
                ],
                check=False,
            )
            self.assertEqual(helper_probe.returncode, 0)

            env["IMESSAGE_PYTHON"] = sys.executable
            mcp_override = self.select("find_mcp_python", env, str(fake_bin))
            self.assertEqual(mcp_override.returncode, 0, mcp_override.stderr)
            self.assertEqual(mcp_override.stdout.strip(), sys.executable)

            env.pop("IMESSAGE_PYTHON")
            env["IMESSAGE_HELPER_PYTHON"] = sys.executable
            helper_override = self.select("find_helper_python", env, str(fake_bin))
            self.assertEqual(helper_override.returncode, 0, helper_override.stderr)
            self.assertEqual(helper_override.stdout.strip(), sys.executable)

    def test_explicit_invalid_or_empty_overrides_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-python-selector-") as td:
            fake_bin = Path(td)
            supported = fake_bin / "python3.12"
            supported.symlink_to(sys.executable)
            unsupported = fake_bin / "unsupported-python"
            unsupported.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            unsupported.chmod(0o755)

            for variable, function in (
                ("IMESSAGE_PYTHON", "find_mcp_python"),
                ("IMESSAGE_HELPER_PYTHON", "find_helper_python"),
            ):
                for value in ("", "python3", str(unsupported)):
                    with self.subTest(variable=variable, value=value):
                        env = os.environ.copy()
                        env.pop("IMESSAGE_PYTHON", None)
                        env.pop("IMESSAGE_HELPER_PYTHON", None)
                        env[variable] = value
                        result = self.select(function, env, str(fake_bin))
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(result.stdout, "")

    def test_helper_and_mcp_overrides_are_independent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-python-selector-") as td:
            fake_bin = Path(td)
            supported = fake_bin / "python3.12"
            supported.symlink_to(sys.executable)

            helper_env = os.environ.copy()
            helper_env["IMESSAGE_PYTHON"] = ""
            helper_env.pop("IMESSAGE_HELPER_PYTHON", None)
            helper = self.select("find_helper_python", helper_env, str(fake_bin))
            self.assertEqual(helper.returncode, 0, helper.stderr)

            mcp_env = os.environ.copy()
            mcp_env["IMESSAGE_HELPER_PYTHON"] = ""
            mcp_env.pop("IMESSAGE_PYTHON", None)
            mcp = self.select("find_mcp_python", mcp_env, str(fake_bin))
            self.assertEqual(mcp.returncode, 0, mcp.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "macOS stat semantics")
    def test_hardened_helper_requires_a_root_owned_interpreter_path(self) -> None:
        trusted = Path("/usr/bin/python3")
        if not trusted.is_file():
            self.skipTest("/usr/bin/python3 is unavailable on this runner")

        env = os.environ.copy()
        env["IMESSAGE_HELPER_PYTHON"] = str(trusted)
        accepted = self.select("find_helper_python", env, os.environ["PATH"], "1")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

        with tempfile.TemporaryDirectory(prefix="chatgpt-untrusted-python-") as td:
            untrusted = Path(td) / "python3"
            untrusted.write_bytes(trusted.read_bytes())
            untrusted.chmod(0o755)
            env["IMESSAGE_HELPER_PYTHON"] = str(untrusted)
            rejected = self.select("find_helper_python", env, os.environ["PATH"], "1")
            self.assertNotEqual(rejected.returncode, 0)

            linked = Path(td) / "python-link"
            linked.symlink_to(trusted)
            env["IMESSAGE_HELPER_PYTHON"] = str(linked)
            rejected_link = self.select(
                "find_helper_python", env, os.environ["PATH"], "1"
            )
            self.assertNotEqual(rejected_link.returncode, 0)

    def test_hardened_selection_rejects_before_executing_untrusted_override(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-python-marker-") as td:
            root = Path(td)
            marker = root / "executed"
            candidate = root / "python3"
            candidate.write_text(
                '#!/bin/sh\nprintf "executed\\n" > "$MARKER"\nexit 0\n',
                encoding="utf-8",
            )
            candidate.chmod(0o755)
            env = os.environ.copy()
            env["IMESSAGE_HELPER_PYTHON"] = str(candidate)
            env["MARKER"] = str(marker)
            result = self.select(
                "find_helper_python", env, os.environ["PATH"], "1"
            )
            executed = marker.exists()

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(executed)

    def test_all_installers_source_the_shared_selector(self) -> None:
        for name in ("install.sh", "install-hardened.sh", "install-plugin.sh"):
            source = (REPO_ROOT / name).read_text(encoding="utf-8")
            self.assertIn('source "$PYTHON_SELECTOR"', source, name)
            self.assertNotIn("find_supported_python()", source, name)

        standard = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
        hardened = (REPO_ROOT / "install-hardened.sh").read_text(encoding="utf-8")
        self.assertIn('HELPER_PYTHON_PATH="$(find_helper_python "$PATH")"', standard)
        self.assertIn('MCP_PYTHON_PATH="$(find_mcp_python "$PATH")"', standard)
        self.assertIn(
            'HELPER_PYTHON_PATH="$(find_helper_python "$ORIGINAL_PATH" 1)"',
            hardened,
        )
        self.assertIn(
            'MCP_PYTHON_PATH="$(find_mcp_python "$ORIGINAL_PATH")"', hardened
        )
        self.assertIn("absolute path to a supported interpreter", standard)
        self.assertIn("must be an absolute path", hardened)

    def test_test_runner_rejects_a_relative_interpreter_override(self) -> None:
        env = os.environ.copy()
        env["IMESSAGE_TEST_PYTHON"] = "python3"
        result = subprocess.run(
            ["bash", str(REPO_ROOT / "tools" / "test.sh")],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("absolute path", result.stderr)


class SQLiteBackupTests(unittest.TestCase):
    def test_copy_chatdb_uses_sqlite_backup_and_returns_consistent_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grokbot-db-test-") as td:
            source = Path(td) / "chat.db"
            with sqlite3.connect(str(source)) as conn:
                conn.execute("CREATE TABLE sample(value TEXT)")
                conn.execute("INSERT INTO sample VALUES ('hello')")

            with mock.patch.object(helper, "CHAT_DB_PATH", source):
                snapshot = helper.copy_chatdb()
            self.addCleanup(helper.cleanup_tmpdb, snapshot)

            with sqlite3.connect(str(snapshot)) as conn:
                self.assertEqual(conn.execute("SELECT value FROM sample").fetchone(), ("hello",))
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertFalse(Path(str(snapshot) + "-wal").exists())

    def test_copy_chatdb_includes_uncheckpointed_wal_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grokbot-wal-test-") as td:
            source = Path(td) / "chat.db"
            with sqlite3.connect(str(source)) as writer:
                self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute("CREATE TABLE sample(value TEXT)")
                writer.commit()
                writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                writer.execute("INSERT INTO sample VALUES ('from-live-wal')")
                writer.commit()
                self.assertGreater(Path(f"{source}-wal").stat().st_size, 0)

                with mock.patch.object(helper, "CHAT_DB_PATH", source):
                    snapshot = helper.copy_chatdb()
                self.addCleanup(helper.cleanup_tmpdb, snapshot)

            with sqlite3.connect(str(snapshot)) as conn:
                self.assertEqual(
                    conn.execute("SELECT value FROM sample").fetchall(),
                    [("from-live-wal",)],
                )
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone(), ("ok",))

    def test_production_open_reads_wal_snapshot_without_sidecars(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-codex-wal-open-") as td:
            source = Path(td) / "chat.db"
            with sqlite3.connect(str(source)) as writer:
                self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
                writer.execute("CREATE TABLE sample(value TEXT)")
                writer.execute("INSERT INTO sample VALUES ('wal-header')")
                writer.commit()

                with mock.patch.object(helper, "CHAT_DB_PATH", source):
                    snapshot = helper.copy_chatdb()
                self.addCleanup(helper.cleanup_tmpdb, snapshot)

            wal_path = Path(f"{snapshot}-wal")
            shm_path = Path(f"{snapshot}-shm")
            self.assertEqual(snapshot.read_bytes()[18:20], b"\x02\x02")
            self.assertFalse(wal_path.exists())
            self.assertFalse(shm_path.exists())

            with helper.open_snapshot(snapshot) as reader:
                self.assertEqual(
                    reader.execute("SELECT value FROM sample").fetchall(),
                    [(b"wal-header",)],
                )
                self.assertFalse(wal_path.exists())
                self.assertFalse(shm_path.exists())


class StatusContractTests(unittest.TestCase):
    def test_status_is_whitelisted_and_does_not_need_chat_db(self) -> None:
        self.assertIn("status", helper.ACTIONS)
        self.assertFalse(helper.action_status.needs_db)
        self.assertFalse(helper.action_status.needs_contacts)

    def test_status_request_does_not_load_messages_or_contacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grokbot-status-test-") as td:
            request = Path(td) / "request-status.json"
            request.write_text(json.dumps({"id": "status", "action": "status", "params": {}}))
            with mock.patch.object(helper, "copy_chatdb") as copy_db, mock.patch.object(
                helper, "load_contacts"
            ) as load_contacts, mock.patch.object(helper, "write_response") as write_response:
                helper.process_request(request, [])

        copy_db.assert_not_called()
        load_contacts.assert_not_called()
        self.assertTrue(write_response.call_args.args[1]["ok"])

    def test_status_reports_protocol_version_and_runtime_checks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grokbot-status-test-") as td:
            chat_db = Path(td) / "chat.db"
            chat_db.write_bytes(b"fixture")
            with mock.patch.object(helper, "CHAT_DB_PATH", chat_db), mock.patch.object(
                helper, "CONFIRM_HELPER_PATH", Path(td) / "chatgpt-codex-imessage-confirm"
            ):
                result = helper.action_status({}, None, {}, [])

        self.assertEqual(result["helper_version"], helper.HELPER_VERSION)
        self.assertEqual(result["protocol_version"], helper.PROTOCOL_VERSION)
        self.assertEqual(result["product_id"], "chatgpt-codex-imessage")
        self.assertEqual(result["host_display_name"], "ChatGPT/Codex")
        self.assertEqual(result["launchd_label"], "com.jeffhuber.chatgpt-codex-imessage")
        self.assertTrue(result["checks"]["chat_db_exists"])
        self.assertNotIn("text", json.dumps(result))

    def test_bad_requests_do_not_interrupt_queue(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grokbot-request-test-") as td:
            bridge = Path(os.path.realpath(td))
            bridge.chmod(0o700)
            control = bridge / "control"
            requests = control / "requests"
            responses = control / "responses"
            for directory in (control, requests, responses):
                directory.mkdir(mode=0o700)
            log = control / "log.txt"
            log.write_text("")
            log.chmod(0o600)

            payloads = {
                "01-list": [],
                "02-action": {"id": "bad-action", "action": [], "params": {}},
                "03-params": {"id": "bad-params", "action": "status", "params": []},
                "04-large": {
                    "id": "large",
                    "action": "status",
                    "params": {},
                    "padding": "x" * (64 * 1024),
                },
                "06-status": {"id": "status", "action": "status", "params": {}},
            }
            for name, payload in payloads.items():
                (requests / f"request-{name}.json").write_text(json.dumps(payload))
            os.mkfifo(requests / "request-05-fifo.json", mode=0o600)

            with mock.patch.object(helper, "BRIDGE_ROOT", bridge), mock.patch.object(
                helper, "REQUESTS_DIR", requests
            ), mock.patch.object(helper, "RESPONSES_DIR", responses), mock.patch.object(
                helper, "LOG_PATH", log
            ), mock.patch.object(helper, "load_privacy_policy", return_value=[]), mock.patch.object(
                helper, "reap_expired_nonces"
            ):
                helper.main()

            for name in ("01-list", "02-action", "03-params", "04-large", "05-fifo"):
                response = json.loads((responses / f"response-{name}.json").read_text())
                self.assertFalse(response["ok"], name)
            status = json.loads((responses / "response-06-status.json").read_text())
            self.assertTrue(status["ok"])
            self.assertEqual(list(requests.iterdir()), [])

    def test_request_symlink_is_rejected_without_reading_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grokbot-request-symlink-test-") as td:
            bridge = Path(os.path.realpath(td))
            bridge.chmod(0o700)
            control = bridge / "control"
            requests = control / "requests"
            responses = control / "responses"
            for directory in (control, requests, responses):
                directory.mkdir(mode=0o700)
            log = control / "log.txt"
            log.write_text("")
            log.chmod(0o600)
            victim = bridge / "victim.json"
            victim.write_text(json.dumps({"id": "victim", "action": "status", "params": {}}))
            (requests / "request-linked.json").symlink_to(victim)

            with mock.patch.object(helper, "BRIDGE_ROOT", bridge), mock.patch.object(
                helper, "REQUESTS_DIR", requests
            ), mock.patch.object(helper, "RESPONSES_DIR", responses), mock.patch.object(
                helper, "LOG_PATH", log
            ), mock.patch.object(helper, "load_privacy_policy", return_value=[]), mock.patch.object(
                helper, "reap_expired_nonces"
            ):
                helper.main()

            response = json.loads((responses / "response-linked.json").read_text())
            self.assertFalse(response["ok"])
            self.assertEqual(json.loads(victim.read_text())["id"], "victim")


class DoctorTests(unittest.TestCase):
    def test_doctor_json_reports_actionable_failures(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grokbot-doctor-test-") as td:
            bridge = Path(os.path.realpath(td)) / "bridge"
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "doctor.py"),
                    "--bridge",
                    str(bridge),
                    "--json",
                    "--skip-plugin",
                    "--skip-launchd",
                    "--skip-codesign",
                    "--skip-chat-db",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertFalse(report["ok"])
        self.assertIn("bridge_root", report["checks"])
        self.assertEqual(report["checks"]["bridge_root"]["status"], "fail")

    def test_doctor_json_passes_for_synthetic_install(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grokbot-doctor-test-") as td:
            root = Path(os.path.realpath(td))
            bridge = root / "bridge"
            for directory in (
                bridge / "bin",
                bridge / "control" / "requests",
                bridge / "control" / "responses",
                bridge / "contacts",
            ):
                directory.mkdir(parents=True, mode=0o700)
            bridge.chmod(0o700)
            for path in (
                bridge / "bin" / "helper.py",
                bridge / "bin" / "send_gate.py",
            ):
                path.write_text("# fixture\n")
                path.chmod(0o500)
            for path in (
                bridge / "bin" / "chatgpt-codex-imessage-helper",
                bridge / "bin" / "chatgpt-codex-imessage-confirm",
            ):
                path.write_text("fixture")
                path.chmod(0o700)
            blocklist = bridge / "contacts" / "blocked_chats.txt"
            blocklist.write_text("")
            blocklist.chmod(0o600)
            allowlist = bridge / "contacts" / "allowed_chats.txt"
            allowlist.write_text("")
            allowlist.chmod(0o600)
            read_policy = bridge / "contacts" / "read_policy.txt"
            read_policy.write_text("blocklist\n")
            read_policy.chmod(0o600)
            log = bridge / "control" / "log.txt"
            log.write_text("")
            log.chmod(0o600)
            home = root / "home"
            home.mkdir()
            chat_db = home / "Library" / "Messages" / "chat.db"
            chat_db.parent.mkdir(parents=True)
            chat_db.write_bytes(b"fixture")

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "doctor.py"),
                    "--bridge",
                    str(bridge),
                    "--json",
                    "--skip-plugin",
                    "--skip-launchd",
                    "--skip-codesign",
                ],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "HOME": str(home)},
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["checks"]["chat_db"]["status"], "warn")
        self.assertIn("does not test wrapper FDA", report["checks"]["chat_db"]["detail"])
        self.assertIn("readable to this doctor process", report["checks"]["chat_db"]["detail"])

    def test_doctor_rejects_symlinked_bridge_ancestor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grokbot-doctor-symlink-test-") as td:
            root = Path(os.path.realpath(td))
            real_parent = root / "real-parent"
            real_parent.mkdir(mode=0o700)
            bridge = real_parent / "bridge"
            bridge.mkdir(mode=0o700)
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "doctor.py"),
                    "--bridge",
                    str(linked_parent / "bridge"),
                    "--json",
                    "--skip-plugin",
                    "--skip-launchd",
                    "--skip-codesign",
                    "--skip-chat-db",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["checks"]["bridge_root"]["status"], "fail")

    def test_doctor_preserves_dotdot_while_checking_symlinks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grokbot-doctor-dotdot-test-") as td:
            root = Path(os.path.realpath(td))
            real_parent = root / "real-parent"
            (real_parent / "child").mkdir(parents=True, mode=0o700)
            bridge = real_parent / "bridge"
            bridge.mkdir(mode=0o700)
            link = root / "linked-child"
            link.symlink_to(real_parent / "child", target_is_directory=True)
            supplied = link / ".." / "bridge"

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "doctor.py"),
                    "--bridge",
                    str(supplied),
                    "--json",
                    "--skip-plugin",
                    "--skip-launchd",
                    "--skip-codesign",
                    "--skip-chat-db",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        report = json.loads(result.stdout)
        self.assertEqual(report["bridge"], str(supplied))
        self.assertEqual(report["checks"]["bridge_root"]["status"], "fail")

    def test_doctor_rejects_symlinked_code_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grokbot-doctor-code-symlink-test-") as td:
            root = Path(os.path.realpath(td))
            bridge = root / "bridge"
            for directory in (
                bridge / "control" / "requests",
                bridge / "control" / "responses",
                bridge / "contacts",
            ):
                directory.mkdir(parents=True, mode=0o700)
            bridge.chmod(0o700)
            real_bin = root / "real-bin"
            real_bin.mkdir(mode=0o700)
            for name, file_mode in (
                ("helper.py", 0o500),
                ("send_gate.py", 0o500),
                ("chatgpt-codex-imessage-helper", 0o700),
                ("chatgpt-codex-imessage-confirm", 0o700),
            ):
                path = real_bin / name
                path.write_text("fixture")
                path.chmod(file_mode)
            (bridge / "bin").symlink_to(real_bin, target_is_directory=True)
            for name, contents in (
                ("blocked_chats.txt", ""),
                ("allowed_chats.txt", ""),
                ("read_policy.txt", "blocklist\n"),
            ):
                path = bridge / "contacts" / name
                path.write_text(contents)
                path.chmod(0o600)
            log = bridge / "control" / "log.txt"
            log.write_text("")
            log.chmod(0o600)

            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "doctor.py"),
                    "--bridge",
                    str(bridge),
                    "--json",
                    "--skip-plugin",
                    "--skip-launchd",
                    "--skip-codesign",
                    "--skip-chat-db",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        report = json.loads(result.stdout)
        self.assertEqual(report["checks"]["helper_source"]["status"], "fail")
        self.assertEqual(report["checks"]["fda_wrapper"]["status"], "fail")


class PluginInstallTests(unittest.TestCase):
    def test_plugin_installer_uses_personal_marketplace_and_mcp_runtime(self) -> None:
        script = (REPO_ROOT / "install-plugin.sh").read_text()
        self.assertIn('PLUGIN_DEST="$PLUGIN_PARENT/$PLUGIN_NAME"', script)
        self.assertIn('MARKETPLACE="$HOME/.agents/plugins/marketplace.json"', script)
        self.assertIn('MCP_VENV="$BRIDGE_ROOT/mcp-venv"', script)
        self.assertIn('PYTHON="$(find_mcp_python "$PATH")"', script)
        self.assertIn('plugin add "$PLUGIN_NAME@personal"', script)

    def test_main_installer_supports_skipping_plugin_install(self) -> None:
        script = (REPO_ROOT / "install.sh").read_text()
        self.assertIn('INSTALL_OPENAI_PLUGIN="${INSTALL_OPENAI_PLUGIN:-1}"', script)
        self.assertIn('if [[ "$INSTALL_OPENAI_PLUGIN" == "1" ]]', script)
        self.assertIn("--skip-plugin", script)

    def test_protocol_version_is_documented(self) -> None:
        protocol = (REPO_ROOT / "docs" / "PROTOCOL.md").read_text()
        self.assertIn(f"Protocol version: `{helper.PROTOCOL_VERSION}`", protocol)

    def test_release_version_matches_helper(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "check_version.py"),
                f"v{helper.HELPER_VERSION}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class BridgePathResolutionTests(unittest.TestCase):
    resolver = REPO_ROOT / "tools" / "bridge_paths.sh"

    def run_resolver(
        self,
        function: str,
        *arguments: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        run_env = (env or os.environ).copy()
        return subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; shift; "$@"',
                "bridge-test",
                str(self.resolver),
                function,
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=run_env,
        )

    def test_production_resolver_distinguishes_live_and_git_trees(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-bridge-resolver-") as td:
            source_root = Path(td).resolve()
            default = source_root / "Application Support" / "Default"
            env = os.environ.copy()
            env.pop("CHATGPT_CODEX_IMESSAGE_BRIDGE", None)

            live = self.run_resolver(
                "resolve_install_bridge",
                str(source_root),
                str(default),
                "1",
                env=env,
            )
            self.assertEqual(live.returncode, 0, live.stderr)
            self.assertEqual(Path(live.stdout.strip()).resolve(), source_root)

            (source_root / ".git").write_text("gitdir: elsewhere\n")
            checkout = self.run_resolver(
                "resolve_install_bridge",
                str(source_root),
                str(default),
                "1",
                env=env,
            )
            self.assertEqual(checkout.returncode, 0, checkout.stderr)
            self.assertEqual(checkout.stdout.strip(), str(default))

    def test_explicit_bridge_override_is_absolute_and_control_free(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-bridge-resolver-") as td:
            source_root = str(Path(td).resolve())
            default = f"{source_root}/default"
            valid = f"{source_root}/Bridge With Spaces"
            env = os.environ.copy()
            env["CHATGPT_CODEX_IMESSAGE_BRIDGE"] = valid
            accepted = self.run_resolver(
                "resolve_install_bridge", source_root, default, "1", env=env
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(accepted.stdout.strip(), valid)

            for invalid in ("", "relative/path", f"{source_root}/bad\npath", f"{source_root}/bad\tpath"):
                with self.subTest(value=invalid):
                    env["CHATGPT_CODEX_IMESSAGE_BRIDGE"] = invalid
                    rejected = self.run_resolver(
                        "resolve_install_bridge", source_root, default, "1", env=env
                    )
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertEqual(rejected.stdout, "")

    def test_bridge_path_file_is_data_only_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-bridge-file-") as td:
            root = Path(td).resolve()
            path_file = root / "bridge-path"
            bridge = root / "Bridge With Spaces"
            written = self.run_resolver(
                "write_bridge_path_file", str(path_file), str(bridge)
            )
            self.assertEqual(written.returncode, 0, written.stderr)
            self.assertEqual(path_file.read_text(), f"{bridge}\n")
            self.assertEqual(stat.S_IMODE(path_file.stat().st_mode), 0o600)

            directory_destination = root / "destination-directory"
            directory_destination.mkdir()
            failed_write = self.run_resolver(
                "write_bridge_path_file", str(directory_destination), str(bridge)
            )
            self.assertNotEqual(failed_write.returncode, 0)

            env = os.environ.copy()
            env.pop("CHATGPT_CODEX_IMESSAGE_BRIDGE", None)
            read = self.run_resolver(
                "resolve_runtime_bridge",
                str(path_file),
                str(root / "default"),
                env=env,
            )
            self.assertEqual(read.returncode, 0, read.stderr)
            self.assertEqual(read.stdout.strip(), str(bridge))

            path_file.write_text(f"{bridge}\n/second-line\n")
            malformed = self.run_resolver(
                "resolve_runtime_bridge",
                str(path_file),
                str(root / "default"),
                env=env,
            )
            self.assertNotEqual(malformed.returncode, 0)

            path_file.unlink()
            target = root / "target"
            target.write_text(f"{bridge}\n")
            path_file.symlink_to(target)
            linked = self.run_resolver(
                "resolve_runtime_bridge",
                str(path_file),
                str(root / "default"),
                env=env,
            )
            self.assertNotEqual(linked.returncode, 0)

    def test_mcp_launcher_reads_space_containing_path_without_sourcing_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-launcher-") as td:
            plugin = Path(td).resolve() / "plugin"
            scripts = plugin / "scripts"
            server_dir = plugin / "plugin_server"
            scripts.mkdir(parents=True)
            server_dir.mkdir()
            launcher = scripts / "run-mcp-server.sh"
            launcher.write_text(
                (REPO_ROOT / "scripts" / "run-mcp-server.sh").read_text()
            )
            launcher.chmod(0o700)
            (scripts / "bridge_paths.sh").write_text(self.resolver.read_text())
            (server_dir / "server.py").write_text("# fixture\n")

            bridge = Path(td).resolve() / "Bridge With Spaces"
            python = bridge / "mcp-venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text('#!/bin/sh\nprintf "ran\\n" > "$MARKER"\n')
            python.chmod(0o700)
            (plugin / "bridge-path").write_text(f"{bridge}\n")
            marker = Path(td) / "marker"
            env = os.environ.copy()
            env.pop("CHATGPT_CODEX_IMESSAGE_BRIDGE", None)
            env["MARKER"] = str(marker)

            result = subprocess.run(
                ["bash", str(launcher)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(marker.read_text(), "ran\n")

    def test_source_checkout_launcher_has_an_install_hint(self) -> None:
        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "run-mcp-server.sh")],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("run ./install-plugin.sh", result.stderr)

    def test_installer_errors_and_warnings_use_defined_logging_functions(self) -> None:
        empty_env = os.environ.copy()
        empty_env["CHATGPT_CODEX_IMESSAGE_BRIDGE"] = ""
        empty = subprocess.run(
            ["bash", str(REPO_ROOT / "install.sh")],
            capture_output=True,
            text=True,
            check=False,
            env=empty_env,
        )
        self.assertNotEqual(empty.returncode, 0)
        self.assertNotIn("command not found", empty.stderr)
        self.assertIn("must be a non-empty absolute path", empty.stderr)

        with tempfile.TemporaryDirectory(prefix="chatgpt-live-warning-") as td:
            home = Path(td).resolve()
            helper_path = (
                home
                / "imessage-bridge-chatgpt"
                / "bin"
                / "chatgpt-codex-imessage-helper"
            )
            helper_path.parent.mkdir(parents=True)
            helper_path.write_text("#!/bin/sh\n")
            helper_path.chmod(0o700)
            warning_env = os.environ.copy()
            warning_env.pop("CHATGPT_CODEX_IMESSAGE_BRIDGE", None)
            warning_env["HOME"] = str(home)
            warning_env["INSTALL_OPENAI_PLUGIN"] = "invalid"
            warning = subprocess.run(
                ["bash", str(REPO_ROOT / "install.sh")],
                capture_output=True,
                text=True,
                check=False,
                env=warning_env,
            )
            self.assertNotEqual(warning.returncode, 0)
            self.assertNotIn("command not found", warning.stderr)
            self.assertIn("detected live install", warning.stdout)

    def test_installers_and_launcher_use_the_production_resolver(self) -> None:
        for relative in (
            "install.sh",
            "install-hardened.sh",
            "install-plugin.sh",
            "scripts/run-mcp-server.sh",
        ):
            with self.subTest(script=relative):
                source = (REPO_ROOT / relative).read_text()
                self.assertIn('source "$BRIDGE_RESOLVER"', source)
                self.assertNotIn("source \"$BRIDGE_ENV\"", source)


if __name__ == "__main__":
    unittest.main()
