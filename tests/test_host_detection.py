"""Tests for MCP host detection (MCP-8)."""
from __future__ import annotations
import pathlib
import shutil
import tempfile
import unittest
from bridge_mcp.host_detection import BRIDGE_PRO_PLUGIN_NAME, DIY_PLUGIN_NAME, detect_hosts, doctor_check_6_json

class TestHostDetection(unittest.TestCase):
    def setUp(self):
        temp_root = pathlib.Path(tempfile.gettempdir()).resolve()
        self._fixtures_tmp = tempfile.TemporaryDirectory(dir=temp_root)
        source = pathlib.Path(__file__).parent / "fixtures" / "host_detection"
        self.fixtures = pathlib.Path(self._fixtures_tmp.name) / "host_detection"
        shutil.copytree(source, self.fixtures)
        for managed_file in self.fixtures.glob("*/plugins/bridge-pro-imessage/.mcp.json"):
            managed_file.chmod(0o600)
        for managed_file in self.fixtures.glob("*/plugins/bridge-pro-imessage/.codex-plugin/plugin.json"):
            managed_file.chmod(0o600)

    def tearDown(self):
        self._fixtures_tmp.cleanup()

    def test_none_fixture(self):
        hosts = detect_hosts(home=self.fixtures / "none", path_env="/usr/bin")
        self.assertFalse(hosts["claude"]["present"])
        self.assertFalse(hosts["openai"]["present"])
        self.assertFalse(hosts["grok"]["present"])

    def test_claude_only_fixture(self):
        hosts = detect_hosts(home=self.fixtures / "claude-only", path_env="/usr/bin")
        self.assertTrue(hosts["claude"]["present"])
        self.assertTrue(hosts["claude"]["markers"]["macos_config"])
        self.assertFalse(hosts["openai"]["present"])

    def test_chatgpt_app_only_fixture(self):
        hosts = detect_hosts(home=self.fixtures / "chatgpt-app-only", path_env="/usr/bin")
        self.assertTrue(hosts["openai"]["present"])
        self.assertEqual(hosts["openai"]["asset_status"], "installed")
        self.assertIsNotNone(hosts["openai"]["bridge_pro_entry"])

    def test_diy_only_fixture(self):
        hosts = detect_hosts(home=self.fixtures / "diy-only", path_env="/usr/bin")
        self.assertTrue(hosts["openai"]["present"])
        self.assertEqual(hosts["openai"]["asset_status"], "diy_only")
        self.assertIsNone(hosts["openai"]["bridge_pro_entry"])
        self.assertEqual(hosts["openai"]["diy_entry"]["name"], DIY_PLUGIN_NAME)

    def test_grok_cli_only_fixture(self):
        hosts = detect_hosts(home=self.fixtures / "grok-cli-only", path_env=str(self.fixtures / "grok-cli-only" / "bin"))
        self.assertTrue(hosts["grok"]["present"])
        self.assertIn("grok", str(hosts["grok"]["markers"]["grok_path"]))

    def test_mixed_fixture(self):
        hosts = detect_hosts(home=self.fixtures / "mixed", path_env="/usr/bin")
        self.assertTrue(hosts["claude"]["present"])
        self.assertTrue(hosts["openai"]["present"])
        self.assertEqual(hosts["openai"]["asset_status"], "installed")

    def test_bridge_pro_valid_fixture(self):
        hosts = detect_hosts(home=self.fixtures / "bridge-pro-valid", path_env="/usr/bin")
        self.assertEqual(hosts["openai"]["asset_status"], "installed")
        self.assertEqual(hosts["openai"]["bridge_pro_entry"]["name"], BRIDGE_PRO_PLUGIN_NAME)

    def test_bridge_pro_mismatch_fixture(self):
        hosts = detect_hosts(home=self.fixtures / "bridge-pro-mismatch", path_env="/usr/bin")
        self.assertEqual(hosts["openai"]["asset_status"], "mismatch")
        self.assertNotIn("bridge-mcp", hosts["openai"]["bridge_pro_entry"]["source"]["command"])

    def test_doctor_check_6_none(self):
        result = doctor_check_6_json(home=self.fixtures / "none", path_env="/usr/bin")
        self.assertEqual(result["check"], 6)
        self.assertTrue(result["ok"])

    def test_doctor_check_6_valid(self):
        result = doctor_check_6_json(home=self.fixtures / "bridge-pro-valid", path_env="/usr/bin")
        self.assertTrue(result["ok"])
        self.assertEqual(result["hosts"]["openai"]["asset_status"], "installed")

    def test_doctor_check_6_diy_only(self):
        result = doctor_check_6_json(home=self.fixtures / "diy-only", path_env="/usr/bin")
        self.assertTrue(result["ok"])
        self.assertEqual(result["hosts"]["openai"]["asset_status"], "diy_only")

    def test_doctor_check_6_mismatch(self):
        result = doctor_check_6_json(home=self.fixtures / "bridge-pro-mismatch", path_env="/usr/bin")
        self.assertFalse(result["ok"])
        self.assertEqual(result["hosts"]["openai"]["asset_status"], "mismatch")

    def test_detect_hosts_default_home(self):
        hosts = detect_hosts()
        for host in hosts.values():
            self.assertIn("present", host)
            self.assertIn("markers", host)

if __name__ == "__main__":
    unittest.main()
