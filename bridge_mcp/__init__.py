"""Bridge MCP package for local iMessage integration."""

from bridge_mcp.client import (
    BridgeClient,
    BridgeError,
    DEFAULT_BRIDGE,
    MAX_RESPONSE_BYTES,
    resolve_runtime_bridge,
)

__all__ = [
    "BridgeClient",
    "BridgeError",
    "DEFAULT_BRIDGE",
    "MAX_RESPONSE_BYTES",
    "resolve_runtime_bridge",
]
