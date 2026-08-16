"""Tests for bridge_mcp stdlib JSON-RPC MCP server."""
import json
from unittest.mock import MagicMock, patch
from bridge_mcp import server

def test_tools_list_matches_plugin_server():
    expected_tools = [
        ("imessage_status", "Check local iMessage helper", "Check helper compatibility, installation health, and active read policy without reading messages.", {}),
        ("review_imessages", "Review recent iMessages", "Review and triage recent allowed iMessage and SMS threads for messages that may need replies.", {"days": 1}),
        ("search_imessages", "Search iMessages", "Search allowed local message history for a case-insensitive text substring.", {"days": 30, "limit": 100}),
        ("get_imessage_history", "Get iMessage conversation history", "Get recent messages from one allowed conversation by contact name, phone, email, or group identifier.", {"days": 14, "limit": 100}),
        ("get_imessage_response_stats", "Get iMessage response statistics", "Calculate local response-time statistics for one allowed contact over a bounded time window.", {"hours": 24}),
        ("lookup_imessage_contacts", "Look up iMessage contacts", "Find allowed Contacts entries by name so the user can disambiguate a recipient before sending.", {}),
        ("preview_imessage", "Preview an iMessage", "Validate a complete individual-recipient message and mint a short-lived nonce. This does not send the message.", {"service": "iMessage"}),
        ("send_imessage", "Send an approved iMessage", "Send the exact previously previewed message. Requires its fresh nonce and a separate native macOS confirmation click.", {"service": "iMessage"}),
    ]
    for i, (name, title, desc, defaults) in enumerate(expected_tools):
        tool = server.TOOLS[i]
        assert tool["name"] == name and tool["title"] == title and tool["description"] == desc
        for param, default_value in defaults.items():
            assert tool["inputSchema"]["properties"][param].get("default") == default_value

def test_tool_call_imessage_status():
    mock_client = MagicMock()
    mock_client.request.return_value = {"id": "test-123", "ok": True, "action": "status", "protocol_version": "1.1"}
    with patch.object(server, "_get_client", return_value=mock_client):
        request = {"jsonrpc": "2.0", "id": "msg-1", "method": "tools/call", "params": {"name": "imessage_status", "arguments": {}}}
        response = server._handle_tools_call(request)
        assert response["jsonrpc"] == "2.0" and response["id"] == "msg-1" and "result" in response
        result_json = json.loads(response["result"]["content"][0]["text"])
        assert result_json["ok"] is True and result_json["action"] == "status"
        mock_client.request.assert_called_once_with("status", {})

def test_tool_call_search_imessages_with_defaults():
    mock_client = MagicMock()
    mock_client.request.return_value = {"id": "test-456", "ok": True, "action": "search", "match_count": 0, "matches": []}
    with patch.object(server, "_get_client", return_value=mock_client):
        with patch.object(server, "_ensure_compatible"):
            request = {"jsonrpc": "2.0", "id": "msg-2", "method": "tools/call", "params": {"name": "search_imessages", "arguments": {"term": "hello"}}}
            response = server._handle_tools_call(request)
            assert "result" in response
            mock_client.request.assert_called_once_with("search", {"term": "hello", "days": 30, "limit": 100})

if __name__ == "__main__":
    test_tools_list_matches_plugin_server()
    test_tool_call_imessage_status()
    test_tool_call_search_imessages_with_defaults()
    print("All tests passed!")
