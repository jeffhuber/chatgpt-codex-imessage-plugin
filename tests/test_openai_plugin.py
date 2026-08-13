from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from plugin_server.bridge import BridgeClient, BridgeError

from tests._helper_loader import REPO_ROOT


class BridgeFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.control = root / "control"
        self.requests = self.control / "requests"
        self.responses = self.control / "responses"
        for directory in (root, self.control, self.requests, self.responses):
            directory.mkdir(mode=0o700, exist_ok=True)
            directory.chmod(0o700)

    def respond_once(self, result: dict[str, object] | None = None) -> threading.Thread:
        def worker() -> None:
            deadline = time.monotonic() + 5
            request_path = None
            while time.monotonic() < deadline:
                matches = list(self.requests.glob("request-*.json"))
                if matches:
                    request_path = matches[0]
                    break
                time.sleep(0.01)
            if request_path is None:
                return
            self.request_mode = request_path.stat().st_mode & 0o777
            request = json.loads(request_path.read_text(encoding="utf-8"))
            response = {
                "id": request["id"],
                "ok": True,
                "action": request["action"],
                **(result or {}),
            }
            final = self.responses / f"response-{request['id']}.json"
            temporary = self.responses / f".{final.name}.tmp"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(response, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, final)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread


class BridgeClientTests(unittest.TestCase):
    def test_atomic_round_trip_deletes_private_response(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openai-imessage-bridge-") as td:
            fixture = BridgeFixture(Path(os.path.realpath(td)))
            worker = fixture.respond_once({"protocol_version": "1.1"})

            result = BridgeClient(fixture.root).request("status", {})
            worker.join(timeout=5)

            self.assertEqual(result["protocol_version"], "1.1")
            self.assertEqual(fixture.request_mode, 0o600)
            self.assertEqual(list(fixture.requests.iterdir()), [])
            self.assertEqual(list(fixture.responses.iterdir()), [])

    def test_rejects_symlinked_bridge_component(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openai-imessage-symlink-") as td:
            root = Path(td)
            real = root / "real"
            BridgeFixture(real)
            linked = root / "linked"
            linked.symlink_to(real, target_is_directory=True)

            with self.assertRaisesRegex(BridgeError, "symlinked bridge path"):
                BridgeClient(linked).request("status", {}, timeout_seconds=0.01)

    def test_rejects_overly_broad_response_permissions_and_deletes_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openai-imessage-mode-") as td:
            fixture = BridgeFixture(Path(os.path.realpath(td)))

            def worker() -> None:
                while not list(fixture.requests.glob("request-*.json")):
                    time.sleep(0.01)
                request = json.loads(
                    list(fixture.requests.glob("request-*.json"))[0].read_text(encoding="utf-8")
                )
                response = fixture.responses / f"response-{request['id']}.json"
                response.write_text(json.dumps({"id": request["id"], "ok": True}))
                response.chmod(0o644)

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            with self.assertRaisesRegex(BridgeError, "permissions are too broad"):
                BridgeClient(fixture.root).request("status", {})
            thread.join(timeout=5)
            self.assertEqual(list(fixture.responses.iterdir()), [])

    def test_send_timeout_warns_that_delivery_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openai-imessage-timeout-") as td:
            fixture = BridgeFixture(Path(os.path.realpath(td)))
            with self.assertRaisesRegex(BridgeError, "Delivery status may be unknown"):
                BridgeClient(fixture.root).request(
                    "send",
                    {},
                    timeout_seconds=0.01,
                    delivery_may_be_unknown=True,
                )


class MCPContractTests(unittest.TestCase):
    def test_tool_annotations_distinguish_reads_preview_and_send(self) -> None:
        from plugin_server import server as server_module

        tools = {tool.name: tool for tool in server_module.server._tool_manager.list_tools()}
        self.assertEqual(len(tools), 8)
        self.assertTrue(tools["search_imessages"].annotations.read_only_hint)
        self.assertFalse(tools["preview_imessage"].annotations.read_only_hint)
        self.assertFalse(tools["preview_imessage"].annotations.open_world_hint)
        self.assertTrue(tools["send_imessage"].annotations.open_world_hint)
        self.assertFalse(tools["send_imessage"].annotations.idempotent_hint)

    def test_stdio_server_initializes_and_lists_tools(self) -> None:
        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        process = subprocess.Popen(
            [sys.executable, "-I", str(REPO_ROOT / "plugin_server" / "server.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(process.kill)
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(json.dumps(messages[0]) + "\n")
        process.stdin.flush()
        initialize_response = json.loads(process.stdout.readline())
        self.assertEqual(initialize_response["id"], 1)
        process.stdin.write(json.dumps(messages[1]) + "\n")
        process.stdin.write(json.dumps(messages[2]) + "\n")
        process.stdin.flush()
        tools_response = json.loads(process.stdout.readline())
        process.stdin.close()
        process.wait(timeout=15)
        stderr = process.stderr.read() if process.stderr else ""
        process.stdout.close()
        process.stderr.close()
        self.assertEqual(process.returncode, 0, stderr)
        names = {tool["name"] for tool in tools_response["result"]["tools"]}
        self.assertEqual(
            names,
            {
                "imessage_status",
                "review_imessages",
                "search_imessages",
                "get_imessage_history",
                "get_imessage_response_stats",
                "lookup_imessage_contacts",
                "preview_imessage",
                "send_imessage",
            },
        )

    def test_manifest_bundles_skill_and_stdio_server(self) -> None:
        manifest = json.loads((REPO_ROOT / ".codex-plugin" / "plugin.json").read_text())
        mcp_config = json.loads((REPO_ROOT / ".mcp.json").read_text())
        self.assertEqual(manifest["name"], "chatgpt-codex-imessage-plugin")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertEqual(manifest["skills"], "./skills/")
        server = mcp_config["mcpServers"]["local-imessage"]
        self.assertEqual(server["command"], "./scripts/run-mcp-server.sh")
        self.assertEqual(server["cwd"], ".")
        self.assertEqual(server["default_tools_approval_mode"], "writes")

    def test_operational_tool_fails_closed_on_protocol_major_mismatch(self) -> None:
        from plugin_server import server as server_module

        with mock.patch.object(server_module, "_compatible_checked", False), mock.patch.object(
            server_module.client,
            "request",
            return_value={"id": "transport-id", "ok": True, "protocol_version": "2.0"},
        ):
            with self.assertRaisesRegex(RuntimeError, "Unsupported iMessage helper protocol"):
                server_module.search_imessages("hello")

    def test_transport_request_id_is_not_returned_to_model(self) -> None:
        from plugin_server import server as server_module

        with mock.patch.object(
            server_module.client,
            "request",
            return_value={"id": "transport-id", "ok": True, "protocol_version": "1.1"},
        ):
            self.assertNotIn("id", server_module.imessage_status())


class MarketplaceTests(unittest.TestCase):
    def test_marketplace_update_is_idempotent_and_preserves_other_plugins(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openai-imessage-marketplace-") as td:
            home = Path(os.path.realpath(td))
            plugin = home / "plugins" / "chatgpt-codex-imessage-plugin"
            (plugin / ".codex-plugin").mkdir(parents=True)
            (plugin / ".codex-plugin" / "plugin.json").write_text("{}")
            marketplace = home / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text(
                json.dumps(
                    {
                        "name": "personal",
                        "interface": {"displayName": "My Plugins"},
                        "plugins": [{"name": "existing"}],
                    }
                )
            )
            env = {**os.environ, "HOME": str(home)}
            command = [
                sys.executable,
                str(REPO_ROOT / "tools" / "install_plugin_manifest.py"),
                "--marketplace",
                str(marketplace),
                "--plugin-destination",
                str(plugin),
            ]
            for _ in range(2):
                result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)

            parsed = json.loads(marketplace.read_text())
            names = [item["name"] for item in parsed["plugins"]]
            self.assertEqual(names, ["existing", "chatgpt-codex-imessage-plugin"])
            self.assertEqual(parsed["interface"]["displayName"], "My Plugins")
            self.assertEqual(marketplace.stat().st_mode & 0o777, 0o600)

            remove = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "install_plugin_manifest.py"),
                    "--marketplace",
                    str(marketplace),
                    "--remove",
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(remove.returncode, 0, remove.stderr)
            self.assertEqual(
                [item["name"] for item in json.loads(marketplace.read_text())["plugins"]],
                ["existing"],
            )


if __name__ == "__main__":
    unittest.main()
