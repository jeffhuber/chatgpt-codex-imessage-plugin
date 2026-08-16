"""Bridge MCP package for local iMessage integration."""

from bridge_mcp.client import (
    BridgeClient,
    BridgeError,
    DEFAULT_BRIDGE,
    MAX_RESPONSE_BYTES,
    resolve_runtime_bridge,
)
from bridge_mcp.host_detection import (
    BRIDGE_PRO_PLUGIN_NAME,
    DIY_PLUGIN_NAME,
    detect_hosts,
    doctor_check_6_json,
)
from bridge_mcp.server import run_server

__all__ = [
    "BRIDGE_PRO_PLUGIN_NAME",
    "BridgeClient",
    "BridgeError",
    "DEFAULT_BRIDGE",
    "DIY_PLUGIN_NAME",
    "MAX_RESPONSE_BYTES",
    "detect_hosts",
    "doctor_check_6_json",
    "resolve_runtime_bridge",
    "run_server",
]
