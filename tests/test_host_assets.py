"""MCP-5: host-assets detect/install/verify/remove round-trip (fake HOME, fake bundle)."""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest

from bridge_mcp.host_assets import VERSION, host_assets
import bridge_mcp_main


class HostAssetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.home = self.tmp / "home"
        (self.home / "plugins").mkdir(parents=True)
        self.bundle = self.tmp / "Bridge Pro.app"           # path with a space (acceptance)
        launcher = self.bundle / "Contents" / "MacOS" / "bridge-mcp"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\n")
        os.environ["BRIDGE_PRO_BUNDLE_ROOT"] = str(self.bundle)
        self.marketplace = self.home / ".agents" / "plugins" / "marketplace.json"

    def tearDown(self):
        os.environ.pop("BRIDGE_PRO_BUNDLE_ROOT", None)

    def _install(self, **kw):
        return host_assets("install", host="chatgpt", home=self.home, **kw)

    def test_round_trip_detect_install_verify_remove(self):
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "missing")
        out = self._install()
        self.assertTrue(out["ok"])
        self.assertEqual(out["hosts"]["chatgpt"], {"status": "installed", "version": VERSION, "path": str(self.bundle / "Contents/MacOS/bridge-mcp")})
        mcp = json.loads((self.home / "plugins/bridge-pro-imessage/.mcp.json").read_text())["mcpServers"]["bridge-pro-imessage"]
        self.assertEqual(mcp["args"], ["--product", "openai"])
        self.assertIn(" ", mcp["command"])                                  # space-containing path preserved verbatim
        self.assertEqual(oct(self.marketplace.stat().st_mode & 0o777), "0o600")
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "installed")
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "installed")
        out = host_assets("remove", host="chatgpt", home=self.home)
        self.assertEqual(out["hosts"]["chatgpt"]["status"], "missing")
        self.assertFalse((self.home / "plugins/bridge-pro-imessage").exists())
        self.assertEqual([p["name"] for p in json.loads(self.marketplace.read_text())["plugins"]], [])

    def test_diy_entry_is_never_touched(self):
        diy = {"name": "chatgpt-codex-imessage-plugin", "source": {"source": "local", "path": "./plugins/chatgpt-codex-imessage-plugin"}}
        self.marketplace.parent.mkdir(parents=True)
        self.marketplace.write_text(json.dumps({"name": "personal", "plugins": [diy]}))
        os.chmod(self.marketplace, 0o600)
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "diy_only")
        self._install()
        names = [p["name"] for p in json.loads(self.marketplace.read_text())["plugins"]]
        self.assertEqual(names, ["chatgpt-codex-imessage-plugin", "bridge-pro-imessage"])
        host_assets("remove", host="chatgpt", home=self.home)
        self.assertEqual([p["name"] for p in json.loads(self.marketplace.read_text())["plugins"]], ["chatgpt-codex-imessage-plugin"])

    def test_verify_flags_stale_command_and_refresh_repairs(self):
        self._install()
        mcp_path = self.home / "plugins/bridge-pro-imessage/.mcp.json"
        payload = json.loads(mcp_path.read_text())
        payload["mcpServers"]["bridge-pro-imessage"]["command"] = "/old/bundle/Contents/MacOS/bridge-mcp"
        mcp_path.write_text(json.dumps(payload))
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")
        self._install(refresh=True)
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "installed")

    def test_guardrails(self):
        with self.assertRaises(ValueError):
            host_assets("install", host="sketchy", home=self.home)
        with self.assertRaises(ValueError):
            host_assets("install", home=self.home)                      # neither --host nor --all
        os.environ.pop("BRIDGE_PRO_BUNDLE_ROOT")
        with self.assertRaises(ValueError):
            self._install()                                             # no bundle root → no caller paths accepted
        os.environ["BRIDGE_PRO_BUNDLE_ROOT"] = "relative/path"
        with self.assertRaises(ValueError):
            self._install()
        out = host_assets("verify", host="codex", home=self.home)       # verify works without a bundle (status only)
        self.assertEqual(out["hosts"]["codex"]["status"], "missing")

    def test_cli_json_output(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = bridge_mcp_main.main(["host-assets", "verify", "--all", "--json"])
        payload = json.loads(buf.getvalue())
        self.assertIn("hosts", payload)
        self.assertEqual(sorted(payload["hosts"]), ["chatgpt", "codex"])
        self.assertIn(rc, (0, 1))


if __name__ == "__main__":
    unittest.main()
