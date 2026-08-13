"""STDIO MCP server for the local ChatGPT/Codex iMessage bridge."""

from __future__ import annotations

import pathlib
import sys
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from plugin_server.bridge import BridgeClient, BridgeError  # noqa: E402

SERVER_VERSION = "0.1.0"
SUPPORTED_PROTOCOL_MAJOR = "1"
client = BridgeClient()
_compatible_checked = False
server = MCPServer(
    name="local-imessage",
    title="Local iMessage",
    description="Use Messages on this Mac through an isolated local helper.",
    version=SERVER_VERSION,
    instructions=(
        "Call imessage_status before the first message operation. Reads are policy-filtered. "
        "For sends: preview, show the complete payload, wait for explicit user approval, then "
        "send with the unchanged payload and nonce. Never retry a send automatically."
    ),
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
LOCAL_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
EXTERNAL_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)


def _request(action: str, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    try:
        result = client.request(action, params, **kwargs)
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
        raise RuntimeError(
            f"Unsupported iMessage helper protocol {protocol!r}; update the helper and plugin together"
        )
    _compatible_checked = True


def _call(action: str, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    if action != "status":
        _ensure_compatible()
    return _request(action, params, **kwargs)


@server.tool(
    title="Check local iMessage helper",
    description="Check helper compatibility, installation health, and active read policy without reading messages.",
    annotations=READ_ONLY,
    structured_output=True,
)
def imessage_status() -> dict[str, Any]:
    return _call("status", {})


@server.tool(
    title="Review recent iMessages",
    description="Review and triage recent allowed iMessage and SMS threads for messages that may need replies.",
    annotations=READ_ONLY,
    structured_output=True,
)
def review_imessages(days: int = 1) -> dict[str, Any]:
    return _call("review", {"days": days})


@server.tool(
    title="Search iMessages",
    description="Search allowed local message history for a case-insensitive text substring.",
    annotations=READ_ONLY,
    structured_output=True,
)
def search_imessages(term: str, days: int = 30, limit: int = 100) -> dict[str, Any]:
    return _call("search", {"term": term, "days": days, "limit": limit})


@server.tool(
    title="Get iMessage conversation history",
    description="Get recent messages from one allowed conversation by contact name, phone, email, or group identifier.",
    annotations=READ_ONLY,
    structured_output=True,
)
def get_imessage_history(chat: str, days: int = 14, limit: int = 100) -> dict[str, Any]:
    return _call("chat_history", {"chat": chat, "days": days, "limit": limit})


@server.tool(
    title="Get iMessage response statistics",
    description="Calculate local response-time statistics for one allowed contact over a bounded time window.",
    annotations=READ_ONLY,
    structured_output=True,
)
def get_imessage_response_stats(chat: str, hours: int = 24) -> dict[str, Any]:
    return _call("response_stats", {"chat": chat, "hours": hours})


@server.tool(
    title="Look up iMessage contacts",
    description="Find allowed Contacts entries by name so the user can disambiguate a recipient before sending.",
    annotations=READ_ONLY,
    structured_output=True,
)
def lookup_imessage_contacts(name: str) -> dict[str, Any]:
    return _call("contacts_lookup", {"name": name})


@server.tool(
    title="Preview an iMessage",
    description="Validate a complete individual-recipient message and mint a short-lived nonce. This does not send the message.",
    annotations=LOCAL_WRITE,
    structured_output=True,
)
def preview_imessage(
    to: str,
    text: str,
    service: Literal["iMessage", "SMS"] = "iMessage",
) -> dict[str, Any]:
    return _call("send_preview", {"to": to, "text": text, "service": service})


@server.tool(
    title="Send an approved iMessage",
    description="Send the exact previously previewed message. Requires its fresh nonce and a separate native macOS confirmation click.",
    annotations=EXTERNAL_WRITE,
    structured_output=True,
)
def send_imessage(
    to: str,
    text: str,
    send_nonce: str,
    service: Literal["iMessage", "SMS"] = "iMessage",
) -> dict[str, Any]:
    return _call(
        "send",
        {"to": to, "text": text, "service": service, "send_nonce": send_nonce},
        timeout_seconds=80.0,
        delivery_may_be_unknown=True,
    )


if __name__ == "__main__":
    server.run(transport="stdio")
