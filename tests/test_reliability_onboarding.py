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
                    "python3",
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
            bridge = Path(os.path.realpath(td)) / "bridge"
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

            result = subprocess.run(
                [
                    "python3",
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

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

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
                "python3",
                str(REPO_ROOT / "tools" / "check_version.py"),
                f"v{helper.HELPER_VERSION}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
