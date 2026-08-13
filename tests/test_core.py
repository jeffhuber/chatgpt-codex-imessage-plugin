from __future__ import annotations

import json
import os
import stat
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests._helper_loader import REPO_ROOT, helper


def make_attributed_blob(body: bytes) -> bytes:
    header = b"streamtyped\x00\x00\x00\x00\x00"
    prefix = header + b"NSString\x01\x2b"
    if len(body) < 0x80:
        return prefix + bytes([len(body)]) + body
    if len(body) < 0x10000:
        return prefix + b"\x81" + struct.pack("<H", len(body)) + body
    return prefix + b"\x82" + struct.pack("<I", len(body)) + body


class ValidationTests(unittest.TestCase):
    def test_send_recipient_accepts_supported_handles(self) -> None:
        for value in (
            "+14155551234",
            "(415) 555-1234",
            "415-555-1234",
            "alex@example.com",
        ):
            with self.subTest(value=value):
                self.assertTrue(helper.validate_send_recipient(value))

    def test_send_recipient_rejects_names_groups_and_control_whitespace(self) -> None:
        for value in (
            "chat123",
            "chatABC",
            "Alice Smith",
            "bad@no-dot",
            'foo"bar@example.com',
            ".alice@example.com",
            "alice..example@example.com",
            "alice@-example.com",
            "41555\n51234",
            "41555\r51234",
            "41555\t51234",
            "41555\v51234",
            "41555\f51234",
            "41555\u00a051234",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                helper.validate_send_recipient(value)

    def test_send_text_bounds_and_controls(self) -> None:
        self.assertEqual(helper.validate_send_text("hello\nworld"), "hello\nworld")
        with self.assertRaises(ValueError):
            helper.validate_send_text("")
        with self.assertRaises(ValueError):
            helper.validate_send_text("x" * (helper.MAX_SEND_LEN + 1))
        with self.assertRaises(ValueError):
            helper.validate_send_text("hello\x00world")


class AttributedBodyTests(unittest.TestCase):
    def test_short_medium_and_unicode_bodies(self) -> None:
        for text in ("hello", "x" * 300, "x" * 0x10000, "cafe \U0001f389"):
            with self.subTest(length=len(text)):
                self.assertEqual(
                    helper.decode_attributed_body(make_attributed_blob(text.encode())),
                    text,
                )

    def test_malformed_or_truncated_bodies_fail_closed(self) -> None:
        values = (
            None,
            b"",
            b"not-streamtyped",
            b"streamtyped\x00\x00\x00\x00\x00NSString\x01\x2b\x81",
            b"streamtyped\x00\x00\x00\x00\x00NSString\x01\x2b\x32short",
        )
        sentinel = "private-malformed-body-sentinel"
        values += (
            make_attributed_blob(sentinel.encode())[:-1],
            make_attributed_blob(b"\xff"),
        )
        with mock.patch.object(helper, "log") as log:
            for value in values:
                with self.subTest(value=value):
                    self.assertEqual(helper.decode_attributed_body(value), "")
        logged = " ".join(str(call.args[0]) for call in log.call_args_list)
        self.assertNotIn(sentinel, logged)


class RedactionTests(unittest.TestCase):
    def test_common_secrets_are_redacted(self) -> None:
        test_code = "".join(("937", "461"))
        test_card = "-".join(("4111", "1111", "1111", "1111"))
        test_ssn = "-".join(("321", "54", "9876"))
        cases = (
            (f"Your verification code is {test_code}", test_code, "[REDACTED-2FA]"),
            (f"Card {test_card}", test_card, "[REDACTED-CARD]"),
            (f"SSN {test_ssn}", test_ssn, "[REDACTED-SSN]"),
        )
        for text, secret, marker in cases:
            with self.subTest(marker=marker):
                redacted = helper.redact(text)
                self.assertIn(marker, redacted)
                self.assertNotIn(secret, redacted)

    def test_plain_text_is_unchanged(self) -> None:
        text = "Meet me at 6:30 by the library"
        self.assertEqual(helper.redact(text), text)


class SendGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="grokbot-nonce-test-")
        self.addCleanup(self._tmp.cleanup)
        self._old_bridge_new = os.environ.get("IMESSAGE_BRIDGE_DIR")
        self._old_bridge_old = os.environ.get("COWORK_IMESSAGE_BRIDGE_DIR")
        os.environ["IMESSAGE_BRIDGE_DIR"] = os.path.realpath(self._tmp.name)
        os.environ["COWORK_IMESSAGE_BRIDGE_DIR"] = os.path.realpath(self._tmp.name)
        self.addCleanup(self._restore_bridge)

    def _restore_bridge(self) -> None:
        if self._old_bridge_new is None:
            os.environ.pop("IMESSAGE_BRIDGE_DIR", None)
        else:
            os.environ["IMESSAGE_BRIDGE_DIR"] = self._old_bridge_new
        if self._old_bridge_old is None:
            os.environ.pop("COWORK_IMESSAGE_BRIDGE_DIR", None)
        else:
            os.environ["COWORK_IMESSAGE_BRIDGE_DIR"] = self._old_bridge_old

    def test_nonce_round_trip_and_replay_rejection(self) -> None:
        nonce = helper.mint_send_nonce("+14155551234", "hello", "iMessage")
        nonce_path = (
            Path(os.environ["COWORK_IMESSAGE_BRIDGE_DIR"]) / "nonces" / f"{nonce}.json"
        )
        self.assertEqual(stat.S_IMODE(nonce_path.stat().st_mode), 0o600)
        helper.consume_send_nonce(nonce, "+14155551234", "hello", "iMessage")
        with self.assertRaises(helper.SendGateError):
            helper.consume_send_nonce(nonce, "+14155551234", "hello", "iMessage")

    def test_payload_mismatch_burns_nonce(self) -> None:
        nonce = helper.mint_send_nonce("+14155551234", "hello", "iMessage")
        with self.assertRaisesRegex(helper.SendGateError, "differs"):
            helper.consume_send_nonce(nonce, "+14155551234", "changed", "iMessage")
        with self.assertRaises(helper.SendGateError):
            helper.consume_send_nonce(nonce, "+14155551234", "hello", "iMessage")

    def test_malformed_expiry_burns_nonce(self) -> None:
        nonce_dir = Path(os.environ["COWORK_IMESSAGE_BRIDGE_DIR"]) / "nonces"
        for expires_at in ("later", float("nan"), True):
            with self.subTest(expires_at=expires_at):
                nonce = helper.mint_send_nonce("+14155551234", "hello", "iMessage")
                path = nonce_dir / f"{nonce}.json"
                record = json.loads(path.read_text())
                record["expires_at"] = expires_at
                path.write_text(json.dumps(record))
                path.chmod(0o600)

                with self.assertRaisesRegex(helper.SendGateError, "malformed nonce record"):
                    helper.consume_send_nonce(nonce, "+14155551234", "hello", "iMessage")

                self.assertFalse(path.exists())
                self.assertFalse((nonce_dir / f"{nonce}.claimed").exists())

    def test_reaper_preserves_fresh_malformed_and_removes_stale_files(self) -> None:
        nonce_dir = Path(self._tmp.name) / "nonces"
        nonce_dir.mkdir(mode=0o700)
        fresh = nonce_dir / "fresh.json"
        stale = nonce_dir / "stale.json"
        claimed = nonce_dir / "stale.claimed"
        for path in (fresh, stale, claimed):
            path.write_text("{")
            path.chmod(0o600)
        old = time.time() - helper.SEND_NONCE_TTL - 10
        os.utime(stale, (old, old))
        os.utime(claimed, (old, old))

        helper.reap_expired_nonces()

        self.assertTrue(fresh.exists())
        self.assertFalse(stale.exists())
        self.assertFalse(claimed.exists())

    def test_nonce_store_rejects_symlinked_directory(self) -> None:
        bridge = Path(os.path.realpath(self._tmp.name))
        victim = bridge / "victim-dir"
        victim.mkdir(mode=0o755)
        (bridge / "nonces").symlink_to(victim, target_is_directory=True)

        with self.assertRaises(RuntimeError):
            helper.mint_send_nonce("+14155551234", "hello", "iMessage")

        self.assertEqual(stat.S_IMODE(victim.stat().st_mode), 0o755)
        self.assertEqual(list(victim.iterdir()), [])

    def test_missing_bridge_dir_env_raises(self) -> None:
        # Save current values
        saved_new = os.environ.get("IMESSAGE_BRIDGE_DIR")
        saved_old = os.environ.get("COWORK_IMESSAGE_BRIDGE_DIR")
        try:
            os.environ.pop("IMESSAGE_BRIDGE_DIR", None)
            os.environ.pop("COWORK_IMESSAGE_BRIDGE_DIR", None)
            with self.assertRaisesRegex(RuntimeError, "IMESSAGE_BRIDGE_DIR.*required"):
                helper.mint_send_nonce("+14155551234", "hello", "iMessage")
        finally:
            # Restore
            if saved_new is not None:
                os.environ["IMESSAGE_BRIDGE_DIR"] = saved_new
            if saved_old is not None:
                os.environ["COWORK_IMESSAGE_BRIDGE_DIR"] = saved_old

    def test_empty_bridge_dir_is_not_replaced_during_helper_import(self) -> None:
        script = """
import importlib.util
import os
import pathlib
import sys

path = pathlib.Path("bin/helper.py").resolve()
spec = importlib.util.spec_from_file_location("isolated_imessage_helper", path)
if spec is None or spec.loader is None:
    raise RuntimeError("could not create helper module spec")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
try:
    spec.loader.exec_module(module)
except RuntimeError as exc:
    assert "IMESSAGE_BRIDGE_DIR" in str(exc) and "required" in str(exc)
else:
    raise AssertionError("helper import must reject an explicitly empty bridge directory")

assert os.environ["IMESSAGE_BRIDGE_DIR"] == ""
assert "COWORK_IMESSAGE_BRIDGE_DIR" not in os.environ
"""
        env = os.environ.copy()
        env["IMESSAGE_BRIDGE_DIR"] = ""
        env.pop("COWORK_IMESSAGE_BRIDGE_DIR", None)
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_empty_new_bridge_dir_does_not_fall_back_to_old_name(self) -> None:
        os.environ["IMESSAGE_BRIDGE_DIR"] = ""
        os.environ["COWORK_IMESSAGE_BRIDGE_DIR"] = self._tmp.name
        with self.assertRaisesRegex(RuntimeError, "IMESSAGE_BRIDGE_DIR.*required"):
            helper._send_gate._bridge_dir()
        with self.assertRaisesRegex(RuntimeError, "IMESSAGE_BRIDGE_DIR.*required"):
            helper.mint_send_nonce("+14155551234", "hello", "iMessage")

    def test_new_env_var_alone_works(self) -> None:
        """IMESSAGE_BRIDGE_DIR alone should work."""
        # Save current values
        saved_new = os.environ.get("IMESSAGE_BRIDGE_DIR")
        saved_old = os.environ.get("COWORK_IMESSAGE_BRIDGE_DIR")
        try:
            os.environ.pop("COWORK_IMESSAGE_BRIDGE_DIR", None)
            os.environ["IMESSAGE_BRIDGE_DIR"] = os.path.realpath(self._tmp.name)
            nonce = helper.mint_send_nonce("+14155551234", "hello", "iMessage")
            self.assertTrue(len(nonce) > 0)
        finally:
            # Restore
            if saved_new is not None:
                os.environ["IMESSAGE_BRIDGE_DIR"] = saved_new
            else:
                os.environ.pop("IMESSAGE_BRIDGE_DIR", None)
            if saved_old is not None:
                os.environ["COWORK_IMESSAGE_BRIDGE_DIR"] = saved_old

    def test_old_env_var_alone_works(self) -> None:
        """COWORK_IMESSAGE_BRIDGE_DIR alone should still work (one-release alias)."""
        # Save current values
        saved_new = os.environ.get("IMESSAGE_BRIDGE_DIR")
        saved_old = os.environ.get("COWORK_IMESSAGE_BRIDGE_DIR")
        try:
            os.environ.pop("IMESSAGE_BRIDGE_DIR", None)
            os.environ["COWORK_IMESSAGE_BRIDGE_DIR"] = os.path.realpath(self._tmp.name)
            nonce = helper.mint_send_nonce("+14155551234", "hello", "iMessage")
            self.assertTrue(len(nonce) > 0)
        finally:
            # Restore
            if saved_new is not None:
                os.environ["IMESSAGE_BRIDGE_DIR"] = saved_new
            if saved_old is not None:
                os.environ["COWORK_IMESSAGE_BRIDGE_DIR"] = saved_old
            else:
                os.environ.pop("COWORK_IMESSAGE_BRIDGE_DIR", None)

    def test_new_env_var_takes_precedence(self) -> None:
        """When both are set, IMESSAGE_BRIDGE_DIR takes precedence."""
        # Save current values
        saved_new = os.environ.get("IMESSAGE_BRIDGE_DIR")
        saved_old = os.environ.get("COWORK_IMESSAGE_BRIDGE_DIR")
        try:
            real_bridge = Path(os.path.realpath(self._tmp.name))
            decoy = real_bridge / "decoy"
            decoy.mkdir(mode=0o700)
            
            os.environ["IMESSAGE_BRIDGE_DIR"] = str(real_bridge)
            os.environ["COWORK_IMESSAGE_BRIDGE_DIR"] = str(decoy)
            
            nonce = helper.mint_send_nonce("+14155551234", "hello", "iMessage")
            nonce_file = real_bridge / "nonces" / f"{nonce}.json"
            self.assertTrue(nonce_file.exists(), "Nonce should be in IMESSAGE_BRIDGE_DIR path")
            self.assertEqual(list(decoy.iterdir()), [], "Decoy dir should be untouched")
        finally:
            # Restore
            if saved_new is not None:
                os.environ["IMESSAGE_BRIDGE_DIR"] = saved_new
            else:
                os.environ.pop("IMESSAGE_BRIDGE_DIR", None)
            if saved_old is not None:
                os.environ["COWORK_IMESSAGE_BRIDGE_DIR"] = saved_old
            else:
                os.environ.pop("COWORK_IMESSAGE_BRIDGE_DIR", None)


if __name__ == "__main__":
    unittest.main()
