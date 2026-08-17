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
        launcher.write_text("#!/bin/sh\n"); os.chmod(launcher, 0o755)
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
        # Shared asset: removal is reported for BOTH hosts, never silently for one.
        self.assertTrue(out["shared_asset"]); self.assertEqual(set(out["hosts"]), {"chatgpt", "codex"})
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

    def test_malformed_manifest_is_mismatch_and_refresh_repairs(self):
        self._install()
        mcp_path = self.home / "plugins/bridge-pro-imessage/.mcp.json"
        for bad in ("[]", '{"mcpServers": []}', '{"mcpServers": {"bridge-pro-imessage": "nope"}}', "{}"):
            mcp_path.write_text(bad)
            self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch", bad)
        (self.home / "plugins/bridge-pro-imessage/.codex-plugin/plugin.json").write_text("[]")
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")
        self._install(refresh=True)
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "installed")

    def test_existing_permissive_dirs_are_tightened(self):
        plugin_dir = self.home / "plugins/bridge-pro-imessage"
        (plugin_dir / ".codex-plugin").mkdir(parents=True)
        os.chmod(plugin_dir, 0o755); os.chmod(plugin_dir / ".codex-plugin", 0o755)
        self._install()
        self.assertEqual(oct(plugin_dir.stat().st_mode & 0o777), "0o700")
        self.assertEqual(oct((plugin_dir / ".codex-plugin").stat().st_mode & 0o777), "0o700")
        self.assertEqual(oct(self.marketplace.parent.stat().st_mode & 0o777), "0o700")

    def test_codex_activation_step(self):
        # No codex on PATH → reported, not fatal.
        out = host_assets("install", host="codex", home=self.home, codex_path=str(self.tmp / "missing-codex"))
        self.assertEqual(out["hosts"]["codex"]["codex_activation"], "codex-not-found")
        # A fake codex CLI records the exact argv and succeeds.
        fake = self.tmp / "codex"; log = self.tmp / "codex.log"
        fake.write_text(f"#!/bin/sh\nprintf '%s ' \"$@\" > {log}\nexit 0\n"); os.chmod(fake, 0o755)
        out = host_assets("install", host="codex", home=self.home, refresh=True, codex_path=str(fake))
        self.assertEqual(out["hosts"]["codex"]["codex_activation"], "activated")
        self.assertEqual(log.read_text().strip(), "plugin add bridge-pro-imessage@personal")
        fake.write_text("#!/bin/sh\nexit 3\n")
        out = host_assets("install", host="codex", home=self.home, refresh=True, codex_path=str(fake))
        self.assertEqual(out["hosts"]["codex"]["codex_activation"], "failed:3")
        # chatgpt target never runs codex.
        out = host_assets("install", host="chatgpt", home=self.home, refresh=True, codex_path=str(fake))
        self.assertNotIn("codex_activation", out["hosts"]["chatgpt"])

    def test_codex_found_via_known_location_when_path_sanitized(self):
        # The launcher sanitizes PATH; the CLI is still found under a known install location (here ~/.local/bin).
        import bridge_mcp.host_assets as ha
        cli = self.tmp / "codexhome" / ".local" / "bin" / "codex"; cli.parent.mkdir(parents=True)
        cli.write_text("#!/bin/sh\nexit 0\n"); os.chmod(cli, 0o755)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.tmp / "codexhome")}
        saved = {k: os.environ.get(k) for k in env}
        try:
            os.environ.update(env)
            self.assertEqual(ha._resolve_codex(None), str(cli))
            os.chmod(cli, 0o777)     # world-writable → not trusted
            self.assertIsNone(ha._resolve_codex(None))
        finally:
            for k, v in saved.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v

    def test_non_personal_marketplace_is_rejected_and_null_source_is_mismatch(self):
        self.marketplace.parent.mkdir(parents=True, exist_ok=True)
        self.marketplace.write_text(json.dumps({"name": "corp", "plugins": []}))
        with self.assertRaises(ValueError):
            self._install()
        self.marketplace.write_text(json.dumps({"name": "personal", "plugins": [{"name": "bridge-pro-imessage", "source": None}]}))
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")

    def test_remove_refuses_symlinked_plugin_dir(self):
        self._install()
        real = self.home / "plugins" / "bridge-pro-imessage"
        victim = self.tmp / "victim"; victim.mkdir(); (victim / ".mcp.json").write_text("{}")
        import shutil
        shutil.rmtree(real); real.symlink_to(victim)
        with self.assertRaises(ValueError):
            host_assets("remove", host="chatgpt", home=self.home)
        self.assertTrue((victim / ".mcp.json").exists())
        # Refused removal mutates nothing: the marketplace entry is still there.
        names = [p["name"] for p in json.loads(self.marketplace.read_text())["plugins"]]
        self.assertIn("bridge-pro-imessage", names)

    def test_wrong_source_path_is_mismatch_and_install_repairs(self):
        self._install()
        m = json.loads(self.marketplace.read_text())
        m["plugins"][0]["source"] = {"source": "local", "path": "./plugins/elsewhere"}
        self.marketplace.write_text(json.dumps(m))
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")
        self._install()   # non-refresh install must repair the broken entry
        self.assertEqual(json.loads(self.marketplace.read_text())["plugins"][0]["source"]["path"], "./plugins/bridge-pro-imessage")
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "installed")

    def test_symlinked_bundle_command_is_rejected(self):
        real = self.bundle
        link = self.tmp / "Linked.app"; link.symlink_to(real)
        os.environ["BRIDGE_PRO_BUNDLE_ROOT"] = str(link)
        with self.assertRaises(ValueError):
            self._install()
        os.environ["BRIDGE_PRO_BUNDLE_ROOT"] = str(real)
        launcher = real / "Contents" / "MacOS" / "bridge-mcp"; launcher.unlink()
        launcher.symlink_to(self.tmp / "elsewhere"); (self.tmp / "elsewhere").write_text("#!/bin/sh\n")
        with self.assertRaises(ValueError):
            self._install()

    def test_verify_without_resolvable_bundle_is_mismatch_not_installed(self):
        self._install()
        os.environ.pop("BRIDGE_PRO_BUNDLE_ROOT")
        out = host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]
        self.assertEqual(out["status"], "mismatch"); self.assertEqual(out["reason"], "bundle-unresolved")

    def test_detection_selects_managed_server_by_name(self):
        self._install()
        mcp_path = self.home / "plugins/bridge-pro-imessage/.mcp.json"
        m = json.loads(mcp_path.read_text())
        # An unrelated server inserted FIRST must not change the verdict either way.
        m["mcpServers"] = {"other": {"command": "/usr/bin/true"}, **m["mcpServers"]}
        mcp_path.write_text(json.dumps(m))
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "installed")
        m["mcpServers"] = {"other": {"command": "/opt/bridge-mcp"}, "bridge-pro-imessage": {"command": "/usr/bin/true"}}
        mcp_path.write_text(json.dumps(m))
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")

    def test_configure_resets_protocol_compatibility(self):
        from bridge_mcp import server
        server._compatible_checked = True
        server.configure(bridge_root=str(self.tmp / "bridge"))
        self.assertFalse(server._compatible_checked); self.assertIsNone(server._client)
        server.configure()   # back to defaults

    def test_non_executable_launcher_is_rejected(self):
        launcher = self.bundle / "Contents" / "MacOS" / "bridge-mcp"; os.chmod(launcher, 0o644)
        with self.assertRaises(ValueError):
            self._install()
        os.chmod(launcher, 0o755); self._install()
        os.chmod(launcher, 0o644)
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")

    def test_every_created_ancestor_is_private(self):
        import shutil
        shutil.rmtree(self.home / "plugins", ignore_errors=True)
        old = os.umask(0o022)
        try:
            self._install()
        finally:
            os.umask(old)
        for rel in (".agents", ".agents/plugins", "plugins", "plugins/bridge-pro-imessage", "plugins/bridge-pro-imessage/.codex-plugin"):
            mode = (self.home / rel).lstat().st_mode & 0o777
            self.assertEqual(mode, 0o700, rel)

    def test_minimal_existing_marketplace_gets_interface_and_transport_contract(self):
        self.marketplace.parent.mkdir(parents=True, exist_ok=True)
        self.marketplace.write_text(json.dumps({"name": "personal", "plugins": []}))
        self._install()
        self.assertEqual(json.loads(self.marketplace.read_text())["interface"], {"displayName": "Personal"})
        # Documented transports parse; unimplemented ones are refused only when selected (exit 2, not argparse's 2-with-usage).
        import io, contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = bridge_mcp_main.main(["--product", "openai", "--transport", "socket"])
        self.assertEqual(rc, 2); self.assertIn("MCP-13", err.getvalue())

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
