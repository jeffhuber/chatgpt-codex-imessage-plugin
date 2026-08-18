"""MCP-5: host-assets detect/install/verify/remove round-trip (fake HOME, fake bundle)."""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

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
        plugin_json = self.home / "plugins/bridge-pro-imessage/.codex-plugin/plugin.json"
        plugin_json.write_text(json.dumps({"name": "wrong", "version": VERSION, "mcpServers": "./.mcp.json"}))
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")
        plugin_json.write_text(json.dumps({"name": "bridge-pro-imessage", "version": VERSION, "mcpServers": "./elsewhere.json"}))
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")
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

    def test_existing_permissive_files_are_mismatch_and_install_repairs(self):
        self._install()
        mcp = self.home / "plugins/bridge-pro-imessage/.mcp.json"
        plugin_json = self.home / "plugins/bridge-pro-imessage/.codex-plugin/plugin.json"
        os.chmod(mcp, 0o644); os.chmod(plugin_json, 0o644)
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")
        self._install()
        self.assertEqual(oct(mcp.lstat().st_mode & 0o777), "0o600")
        self.assertEqual(oct(plugin_json.lstat().st_mode & 0o777), "0o600")
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "installed")

    def test_permissive_existing_marketplace_is_tightened_before_success(self):
        self._install()
        os.chmod(self.marketplace, 0o666)
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "installed")
        self.assertEqual(oct(self.marketplace.lstat().st_mode & 0o777), "0o600")

    def test_symlinked_managed_files_are_not_treated_as_current(self):
        self._install()
        mcp = self.home / "plugins/bridge-pro-imessage/.mcp.json"
        target = self.tmp / "outside-mcp.json"
        target.write_text(mcp.read_text())
        mcp.unlink(); mcp.symlink_to(target)
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")
        with self.assertRaises(ValueError):
            self._install()
        self.assertTrue(mcp.is_symlink())
        self.assertEqual(json.loads(target.read_text())["mcpServers"]["bridge-pro-imessage"]["args"], ["--product", "openai"])

    def test_codex_activation_step(self):
        # No codex on PATH → reported as a failed Codex install, not as a false success.
        out = host_assets("install", host="codex", home=self.home, codex_path=str(self.tmp / "missing-codex"))
        self.assertEqual(out["hosts"]["codex"]["codex_activation"], "codex-not-found")
        self.assertEqual(out["hosts"]["codex"]["status"], "mismatch")
        self.assertFalse(out["ok"])
        # A fake codex CLI records the exact argv and succeeds.
        fake = self.tmp / "codex"; log = self.tmp / "codex.log"
        fake.write_text(f"#!/bin/sh\nprintf '%s ' \"$@\" > {log}\nexit 0\n"); os.chmod(fake, 0o755)
        out = host_assets("install", host="codex", home=self.home, refresh=True, codex_path=str(fake))
        self.assertEqual(out["hosts"]["codex"]["codex_activation"], "activated")
        self.assertEqual(out["hosts"]["codex"]["status"], "installed")
        self.assertTrue(out["ok"])
        self.assertEqual(log.read_text().strip(), "plugin add bridge-pro-imessage@personal")
        fake.write_text("#!/bin/sh\nexit 3\n")
        out = host_assets("install", host="codex", home=self.home, refresh=True, codex_path=str(fake))
        self.assertEqual(out["hosts"]["codex"]["codex_activation"], "failed:3")
        self.assertEqual(out["hosts"]["codex"]["status"], "mismatch")
        self.assertFalse(out["ok"])
        fake.write_text("#!/bin/sh\necho 'bridge-pro-imessage@personal already exists' >&2\nexit 3\n")
        out = host_assets("install", host="codex", home=self.home, refresh=True, codex_path=str(fake))
        self.assertEqual(out["hosts"]["codex"]["codex_activation"], "already-activated")
        self.assertEqual(out["hosts"]["codex"]["status"], "installed")
        self.assertTrue(out["ok"])
        # chatgpt target never runs codex.
        out = host_assets("install", host="chatgpt", home=self.home, refresh=True, codex_path=str(fake))
        self.assertNotIn("codex_activation", out["hosts"]["chatgpt"])

    def test_codex_verify_reports_activation_failure(self):
        self._install()
        out = host_assets("verify", host="codex", home=self.home, codex_path=str(self.tmp / "missing-codex"))
        self.assertFalse(out["ok"])
        self.assertEqual(out["hosts"]["codex"]["status"], "mismatch")
        self.assertEqual(out["hosts"]["codex"]["reason"], "codex-not-found")
        fake = self.tmp / "codex-already"; fake.write_text("#!/bin/sh\necho 'bridge-pro-imessage@personal already exists' >&2\nexit 3\n"); os.chmod(fake, 0o755)
        out = host_assets("verify", host="codex", home=self.home, codex_path=str(fake))
        self.assertTrue(out["ok"])
        self.assertEqual(out["hosts"]["codex"]["status"], "installed")
        self.assertEqual(out["hosts"]["codex"]["codex_activation"], "already-activated")

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
        self.assertIn("/Applications/Codex.app/Contents/Resources/codex", ha.KNOWN_CODEX_LOCATIONS)

    def test_non_personal_marketplace_is_rejected_and_null_source_is_mismatch(self):
        self.marketplace.parent.mkdir(parents=True, exist_ok=True)
        self.marketplace.write_text(json.dumps({"name": "corp", "plugins": []}))
        with self.assertRaises(ValueError):
            self._install()
        self.marketplace.write_text(json.dumps({"name": "personal", "plugins": [{"name": "bridge-pro-imessage", "source": None}]}))
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")
        for malformed in ([], {"name": "personal", "plugins": {}}, {"name": "personal"}):
            self.marketplace.write_text(json.dumps(malformed))
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

    def test_remove_refuses_non_regular_managed_files_before_marketplace_mutation(self):
        self._install()
        mcp = self.home / "plugins/bridge-pro-imessage/.mcp.json"
        mcp.unlink(); mcp.mkdir()
        with self.assertRaises(ValueError):
            host_assets("remove", host="chatgpt", home=self.home)
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
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "installed")

    def test_detect_ok_remains_true_for_mismatch_status(self):
        self._install()
        mcp_path = self.home / "plugins/bridge-pro-imessage/.mcp.json"
        payload = json.loads(mcp_path.read_text())
        payload["mcpServers"]["bridge-pro-imessage"]["args"] = ["--product", "wrong"]
        mcp_path.write_text(json.dumps(payload))
        out = host_assets("detect", host="chatgpt", home=self.home)
        self.assertTrue(out["ok"])
        self.assertEqual(out["hosts"]["chatgpt"]["status"], "mismatch")

    def test_grok_fallback_is_partial_not_installed(self):
        with mock.patch("bridge_mcp.host_assets._resolve_grok", return_value=None):
            out = host_assets("install", host="grok", home=self.home)
        self.assertFalse(out["ok"])
        self.assertEqual(out["hosts"]["grok"]["status"], "partial")
        self.assertEqual(out["hosts"]["grok"]["method"], "skill_dir")
        manifest_path = self.home / ".grok/skills/bridge-pro-imessage/manifest.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["command"], str(self.bundle / "Contents/MacOS/bridge-mcp"))
        self.assertEqual(manifest["args"], ["--product", "grok"])
        self.assertEqual(manifest["transport"], "watched_folder")
        self.assertEqual(oct(manifest_path.stat().st_mode & 0o777), "0o600")
        with mock.patch("bridge_mcp.host_assets._resolve_grok", return_value=None):
            verify = host_assets("verify", host="grok", home=self.home)
            detect = host_assets("detect", host="grok", home=self.home)
        self.assertFalse(verify["ok"])
        self.assertEqual(verify["hosts"]["grok"]["status"], "partial")
        self.assertEqual(detect["hosts"]["grok"]["status"], "partial")

    def test_grok_mcp_cli_install_and_verify(self):
        fake_grok = str(self.tmp / "grok")
        calls: list[list[str]] = []

        def fake_run(args, **_kwargs):
            calls.append(args)
            if args[1:3] == ["mcp", "add"]:
                return mock.Mock(returncode=0, stdout="", stderr="")
            if args[1:3] == ["mcp", "list"]:
                return mock.Mock(returncode=0, stdout="bridge-pro-imessage    running\n", stderr="")
            if args[1:3] == ["mcp", "show"]:
                return mock.Mock(returncode=0, stdout=f"command: {self.bundle / 'Contents/MacOS/bridge-mcp'}\nargs: --product grok\n", stderr="")
            return mock.Mock(returncode=1, stdout="", stderr="")

        with mock.patch("bridge_mcp.host_assets._resolve_grok", return_value=fake_grok), \
             mock.patch("subprocess.run", side_effect=fake_run):
            installed = host_assets("install", host="grok", home=self.home)
            verified = host_assets("verify", host="grok", home=self.home)
        self.assertTrue(installed["ok"])
        self.assertEqual(installed["hosts"]["grok"]["status"], "installed")
        self.assertEqual(installed["hosts"]["grok"]["method"], "mcp_cli")
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["hosts"]["grok"]["status"], "installed")
        self.assertIn([fake_grok, "mcp", "add", "bridge-pro-imessage", "--command", str(self.bundle / "Contents/MacOS/bridge-mcp"), "--args", "--product", "grok"], calls)

    def test_grok_exact_name_matching(self):
        import bridge_mcp.host_assets as ha
        self.assertFalse(ha._is_mcp_registered("bridge-pro-imessage-old\nother\n", "bridge-pro-imessage"))
        self.assertTrue(ha._is_mcp_registered("bridge-pro-imessage running /path\n", "bridge-pro-imessage"))

    def test_grok_remove_reports_failed_cli_state(self):
        fake_grok = str(self.tmp / "grok")

        def fake_run(args, **_kwargs):
            if args[1:3] == ["mcp", "remove"]:
                return mock.Mock(returncode=1, stdout="", stderr="nope")
            if args[1:3] == ["mcp", "list"]:
                return mock.Mock(returncode=0, stdout="bridge-pro-imessage\n", stderr="")
            return mock.Mock(returncode=1, stdout="", stderr="")

        with mock.patch("bridge_mcp.host_assets._resolve_grok", return_value=fake_grok), \
             mock.patch("subprocess.run", side_effect=fake_run):
            out = host_assets("remove", host="grok", home=self.home)
        self.assertFalse(out["ok"])
        self.assertEqual(out["hosts"]["grok"]["status"], "installed")
        self.assertIn("error", out["hosts"]["grok"])

    def test_grok_rejects_symlinked_fallback_manifest(self):
        skill_dir = self.home / ".grok/skills/bridge-pro-imessage"
        skill_dir.mkdir(parents=True)
        target = self.tmp / "outside.json"; target.write_text("{}")
        (skill_dir / "manifest.json").symlink_to(target)
        with mock.patch("bridge_mcp.host_assets._resolve_grok", return_value=None):
            with self.assertRaises(ValueError):
                host_assets("install", host="grok", home=self.home)
            out = host_assets("remove", host="grok", home=self.home)
        self.assertFalse(out["ok"])
        self.assertEqual(out["hosts"]["grok"]["status"], "installed")
        self.assertTrue(target.exists())

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

    def test_detect_and_verify_agree_on_stale_manifest(self):
        self._install()
        meta = self.home / "plugins/bridge-pro-imessage/.codex-plugin/plugin.json"
        m = json.loads(meta.read_text()); m["version"] = "0.0.1"; meta.write_text(json.dumps(m))   # stale version
        self.assertEqual(host_assets("verify", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")
        self._install(refresh=True)
        mcp = self.home / "plugins/bridge-pro-imessage/.mcp.json"
        c = json.loads(mcp.read_text()); c["mcpServers"]["bridge-pro-imessage"]["command"] = "/opt/evil/bridge-mcp"; mcp.write_text(json.dumps(c))
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")   # wrong path, though it says bridge-mcp
        c["mcpServers"]["bridge-pro-imessage"]["command"] = "/tmp/bridge-mcp-wrapper"; mcp.write_text(json.dumps(c))
        self.assertEqual(host_assets("detect", host="chatgpt", home=self.home)["hosts"]["chatgpt"]["status"], "mismatch")

    def test_cli_json_output(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = bridge_mcp_main.main(["host-assets", "verify", "--all", "--json"])
        payload = json.loads(buf.getvalue())
        self.assertIn("hosts", payload)
        self.assertEqual(sorted(payload["hosts"]), ["chatgpt", "codex", "grok"])
        self.assertIn(rc, (0, 1))


if __name__ == "__main__":
    unittest.main()
