"""Conformance tests for bridge_mcp stdlib JSON-RPC MCP server."""
from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from bridge_mcp import server


class FakeBridgeClient:
    """Fake BridgeClient that records calls for timeout/parameter assertions."""
    
    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.response: dict[str, Any] = {"id": "test-id", "ok": True}
    
    def request(self, action: str, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self.calls.append((action, params, kwargs))
        return self.response.copy()


class TestToolSchemas(unittest.TestCase):
    """Test that all tool schemas match plugin_server/server.py (source of truth)."""
    
    def test_tools_list_has_exactly_eight_tools_in_order(self):
        expected = ["imessage_status", "review_imessages", "search_imessages", "get_imessage_history",
                    "get_imessage_response_stats", "lookup_imessage_contacts", "preview_imessage", "send_imessage"]
        self.assertEqual([t["name"] for t in server.TOOLS], expected)
    
    def test_tool_schemas_match_plugin_server(self):
        t = server.TOOLS[0]
        self.assertEqual(t["name"], "imessage_status")
        self.assertEqual(t["title"], "Check local iMessage helper")
        self.assertEqual(t["inputSchema"]["properties"], {})
        self.assertEqual(t["annotations"], server.READ_ONLY)
        
        self.assertEqual(server.TOOLS[1]["inputSchema"]["properties"]["days"]["default"], 1)
        self.assertEqual(server.TOOLS[2]["inputSchema"]["properties"]["days"]["default"], 30)
        self.assertEqual(server.TOOLS[2]["inputSchema"]["properties"]["limit"]["default"], 100)
        self.assertEqual(server.TOOLS[2]["inputSchema"]["required"], ["term"])
        self.assertEqual(server.TOOLS[3]["inputSchema"]["properties"]["days"]["default"], 14)
        self.assertEqual(server.TOOLS[3]["inputSchema"]["properties"]["limit"]["default"], 100)
        self.assertEqual(server.TOOLS[4]["inputSchema"]["properties"]["hours"]["default"], 24)
        self.assertEqual(server.TOOLS[5]["inputSchema"]["required"], ["name"])
        
        t = server.TOOLS[6]
        self.assertEqual(t["inputSchema"]["properties"]["service"]["enum"], ["iMessage", "SMS"])
        self.assertEqual(t["inputSchema"]["properties"]["service"]["default"], "iMessage")
        self.assertEqual(set(t["inputSchema"]["required"]), {"to", "text"})
        self.assertEqual(t["annotations"], server.LOCAL_WRITE)
        
        t = server.TOOLS[7]
        self.assertEqual(t["inputSchema"]["properties"]["service"]["default"], "iMessage")
        self.assertEqual(set(t["inputSchema"]["required"]), {"to", "text", "send_nonce"})
        self.assertEqual(t["annotations"], server.EXTERNAL_WRITE)


class TestDefaults(unittest.TestCase):
    """Test that omitted arguments produce documented defaults."""
    
    def test_defaults_applied_when_omitted(self):
        fake = FakeBridgeClient()
        with patch.object(server, "_get_client", return_value=fake), patch.object(server, "_ensure_compatible"):
            server._tool_call_review_imessages({})
            self.assertEqual(fake.calls[0][1], {"days": 1})
            
            fake.calls.clear()
            server._tool_call_search_imessages({"term": "hello"})
            self.assertEqual(fake.calls[0][1], {"term": "hello", "days": 30, "limit": 100})
            
            fake.calls.clear()
            server._tool_call_get_imessage_history({"chat": "Alice"})
            self.assertEqual(fake.calls[0][1], {"chat": "Alice", "days": 14, "limit": 100})
            
            fake.calls.clear()
            server._tool_call_get_imessage_response_stats({"chat": "Bob"})
            self.assertEqual(fake.calls[0][1], {"chat": "Bob", "hours": 24})
            
            fake.calls.clear()
            server._tool_call_preview_imessage({"to": "test@example.com", "text": "Hi"})
            self.assertEqual(fake.calls[0][1]["service"], "iMessage")
            
            fake.calls.clear()
            server._tool_call_send_imessage({"to": "test@example.com", "text": "Hi", "send_nonce": "abc"})
            self.assertEqual(fake.calls[0][1]["service"], "iMessage")


class TestTimeouts(unittest.TestCase):
    """Test that timeout_seconds and delivery_may_be_unknown are passed correctly."""
    
    def test_timeouts(self):
        fake = FakeBridgeClient()
        with patch.object(server, "_get_client", return_value=fake), patch.object(server, "_ensure_compatible"):
            server._tool_call_imessage_status({})
            self.assertEqual(fake.calls[0][2], {})
            
            fake.calls.clear()
            server._tool_call_send_imessage({"to": "test@example.com", "text": "Hi", "send_nonce": "nonce123"})
            self.assertEqual(fake.calls[0][2], {"timeout_seconds": 80.0, "delivery_may_be_unknown": True})


class TestErrorHandling(unittest.TestCase):
    """Test that BridgeError becomes a JSON-RPC error with the error message."""
    
    def test_bridge_error_becomes_jsonrpc_error(self):
        from bridge_mcp.client import BridgeError
        mock_client = MagicMock()
        mock_client.request.side_effect = BridgeError("Helper is not running")
        with patch.object(server, "_get_client", return_value=mock_client):
            request = {"jsonrpc": "2.0", "id": "msg-1", "method": "tools/call",
                       "params": {"name": "imessage_status", "arguments": {}}}
            response = server._handle_tools_call(request)
            self.assertEqual(response["error"]["code"], -32000)
            self.assertEqual(response["error"]["message"], "Helper is not running")
            self.assertNotIn("Traceback", response["error"]["message"])


class TestToolsList(unittest.TestCase):
    """Test that tools/list returns exactly eight tools in the correct order."""
    
    def test_tools_list_response(self):
        request = {"jsonrpc": "2.0", "id": "list-1", "method": "tools/list"}
        response = server._handle_tools_list(request)
        tools = response["result"]["tools"]
        self.assertEqual(len(tools), 8)
        expected = ["imessage_status", "review_imessages", "search_imessages", "get_imessage_history",
                    "get_imessage_response_stats", "lookup_imessage_contacts", "preview_imessage", "send_imessage"]
        self.assertEqual([t["name"] for t in tools], expected)


class TestInitialize(unittest.TestCase):
    """Test that initialize returns correct serverInfo."""
    
    def test_initialize_response(self):
        request = {"jsonrpc": "2.0", "id": "init-1", "method": "initialize"}
        response = server._handle_initialize(request)
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "1.0")
        self.assertEqual(result["serverInfo"]["name"], "local-imessage")
        self.assertEqual(result["serverInfo"]["title"], "Local iMessage")
        self.assertEqual(result["serverInfo"]["version"], server.SERVER_VERSION)
        self.assertIn("Call imessage_status before the first message operation", result["instructions"])


if __name__ == "__main__":
    unittest.main()
