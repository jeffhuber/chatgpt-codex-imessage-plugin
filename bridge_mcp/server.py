"""Stdlib stdio JSON-RPC MCP server for local iMessage bridge."""
from __future__ import annotations
import json
import sys
from typing import Any
import pathlib
from bridge_mcp.client import BridgeClient, BridgeError, resolve_runtime_bridge

SERVER_VERSION = "1.3.0"
SUPPORTED_PROTOCOL_MAJOR = "1"
_compatible_checked = False
_client: BridgeClient | None = None
_configured_root: "pathlib.Path | None" = None

def configure(product: str | None = None, bridge_root: str | None = None) -> None:
    """Select the bridge root before serving (bridge-mcp --product / --bridge-root)."""
    global _configured_root, _client, _compatible_checked
    _configured_root = resolve_runtime_bridge(explicit_path=bridge_root, product=product) if (product or bridge_root) else None
    _client = None
    _compatible_checked = False   # a different bridge must pass its own protocol check before any operation

def _get_client() -> BridgeClient:
    global _client
    if _client is None:
        _client = BridgeClient(bridge_root=_configured_root)
    return _client

def _request(action: str, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    try:
        result = _get_client().request(action, params, **kwargs)
    except BridgeError as exc:
        raise RuntimeError(str(exc)) from exc
    result.pop("id", None)
    return result

def _ensure_compatible() -> None:
    global _compatible_checked
    if _compatible_checked:
        return
    status = _request("status", {})
    protocol = status.get("protocol_version")
    if not isinstance(protocol, str) or protocol.split(".", 1)[0] != SUPPORTED_PROTOCOL_MAJOR:
        raise RuntimeError(f"Unsupported iMessage helper protocol {protocol!r}; update the helper and plugin together")
    _compatible_checked = True

def _call(action: str, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    if action != "status":
        _ensure_compatible()
    return _request(action, params, **kwargs)


READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
LOCAL_WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
EXTERNAL_WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}

TOOLS = [
    {"name": "imessage_status", "title": "Check local iMessage helper", "description": "Check helper compatibility, installation health, and active read policy without reading messages.", "inputSchema": {"type": "object", "properties": {}, "required": []}, "annotations": READ_ONLY},
    {"name": "review_imessages", "title": "Review recent iMessages", "description": "Review and triage recent allowed iMessage and SMS threads for messages that may need replies.", "inputSchema": {"type": "object", "properties": {"days": {"type": "integer", "default": 1}}, "required": []}, "annotations": READ_ONLY},
    {"name": "search_imessages", "title": "Search iMessages", "description": "Search allowed local message history for a case-insensitive text substring.", "inputSchema": {"type": "object", "properties": {"term": {"type": "string"}, "days": {"type": "integer", "default": 30}, "limit": {"type": "integer", "default": 100}}, "required": ["term"]}, "annotations": READ_ONLY},
    {"name": "get_imessage_history", "title": "Get iMessage conversation history", "description": "Get recent messages from one allowed conversation by contact name, phone, email, or group identifier.", "inputSchema": {"type": "object", "properties": {"chat": {"type": "string"}, "days": {"type": "integer", "default": 14}, "limit": {"type": "integer", "default": 100}}, "required": ["chat"]}, "annotations": READ_ONLY},
    {"name": "get_imessage_response_stats", "title": "Get iMessage response statistics", "description": "Calculate local response-time statistics for one allowed contact over a bounded time window.", "inputSchema": {"type": "object", "properties": {"chat": {"type": "string"}, "hours": {"type": "integer", "default": 24}}, "required": ["chat"]}, "annotations": READ_ONLY},
    {"name": "lookup_imessage_contacts", "title": "Look up iMessage contacts", "description": "Find allowed Contacts entries by name so the user can disambiguate a recipient before sending.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}, "annotations": READ_ONLY},
    {"name": "preview_imessage", "title": "Preview an iMessage", "description": "Validate a complete individual-recipient message and mint a short-lived nonce. This does not send the message.", "inputSchema": {"type": "object", "properties": {"to": {"type": "string"}, "text": {"type": "string"}, "service": {"type": "string", "enum": ["iMessage", "SMS"], "default": "iMessage"}}, "required": ["to", "text"]}, "annotations": LOCAL_WRITE},
    {"name": "send_imessage", "title": "Send an approved iMessage", "description": "Send the exact previously previewed message. Requires its fresh nonce and a separate native macOS confirmation click.", "inputSchema": {"type": "object", "properties": {"to": {"type": "string"}, "text": {"type": "string"}, "send_nonce": {"type": "string"}, "service": {"type": "string", "enum": ["iMessage", "SMS"], "default": "iMessage"}}, "required": ["to", "text", "send_nonce"]}, "annotations": EXTERNAL_WRITE},
]

def _tool_call_imessage_status(a: dict[str, Any]) -> dict[str, Any]:
    return _call("status", {})

def _tool_call_review_imessages(a: dict[str, Any]) -> dict[str, Any]:
    return _call("review", {"days": a.get("days", 1)})

def _tool_call_search_imessages(a: dict[str, Any]) -> dict[str, Any]:
    return _call("search", {"term": a["term"], "days": a.get("days", 30), "limit": a.get("limit", 100)})

def _tool_call_get_imessage_history(a: dict[str, Any]) -> dict[str, Any]:
    return _call("chat_history", {"chat": a["chat"], "days": a.get("days", 14), "limit": a.get("limit", 100)})

def _tool_call_get_imessage_response_stats(a: dict[str, Any]) -> dict[str, Any]:
    return _call("response_stats", {"chat": a["chat"], "hours": a.get("hours", 24)})

def _tool_call_lookup_imessage_contacts(a: dict[str, Any]) -> dict[str, Any]:
    return _call("contacts_lookup", {"name": a["name"]})

def _tool_call_preview_imessage(a: dict[str, Any]) -> dict[str, Any]:
    return _call("send_preview", {"to": a["to"], "text": a["text"], "service": a.get("service", "iMessage")})

def _tool_call_send_imessage(a: dict[str, Any]) -> dict[str, Any]:
    return _call("send", {"to": a["to"], "text": a["text"], "service": a.get("service", "iMessage"), "send_nonce": a["send_nonce"]}, timeout_seconds=80.0, delivery_may_be_unknown=True)

TOOL_HANDLERS = {"imessage_status": _tool_call_imessage_status, "review_imessages": _tool_call_review_imessages, "search_imessages": _tool_call_search_imessages, "get_imessage_history": _tool_call_get_imessage_history, "get_imessage_response_stats": _tool_call_get_imessage_response_stats, "lookup_imessage_contacts": _tool_call_lookup_imessage_contacts, "preview_imessage": _tool_call_preview_imessage, "send_imessage": _tool_call_send_imessage}


def _read_message() -> dict[str, Any] | None:
    content_length = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        if line.lower().startswith(b"content-length:"):
            content_length = int(line.split(b":", 1)[1].strip())
    if content_length is None:
        return None
    return json.loads(sys.stdin.buffer.read(content_length).decode("utf-8"))

def _write_message(message: dict[str, Any]) -> None:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8"))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()

def _handle_initialize(request: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request.get("id"), "result": {"protocolVersion": "1.0", "serverInfo": {"name": "local-imessage", "title": "Local iMessage", "description": "Use Messages on this Mac through an isolated local helper.", "version": SERVER_VERSION}, "instructions": "Call imessage_status before the first message operation. Reads are policy-filtered. For sends: preview, show the complete payload, wait for explicit user approval, then send with the unchanged payload and nonce. Never retry a send automatically."}}

def _handle_tools_list(request: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request.get("id"), "result": {"tools": TOOLS}}

def _handle_tools_call(request: dict[str, Any]) -> dict[str, Any]:
    params = request.get("params", {})
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    if tool_name not in TOOL_HANDLERS:
        return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}
    try:
        result = TOOL_HANDLERS[tool_name](arguments)
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32000, "message": str(exc)}}

def _handle_ping(request: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request.get("id"), "result": {}}

def run_server(product: str | None = None, bridge_root: str | None = None) -> None:
    if product or bridge_root:
        configure(product=product, bridge_root=bridge_root)
    while True:
        try:
            message = _read_message()
            if message is None:
                break
            method = message.get("method")
            if method == "initialize":
                _write_message(_handle_initialize(message))
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                _write_message(_handle_tools_list(message))
            elif method == "tools/call":
                _write_message(_handle_tools_call(message))
            elif method == "ping":
                _write_message(_handle_ping(message))
            else:
                _write_message({"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32601, "message": f"Unknown method: {method}"}})
        except Exception as exc:
            if "id" in locals() and message and "id" in message:
                _write_message({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32603, "message": str(exc)}})
