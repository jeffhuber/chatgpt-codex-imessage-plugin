#!/bin/bash
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BRIDGE_RESOLVER="$PLUGIN_ROOT/scripts/bridge_paths.sh"
if [[ ! -f "$BRIDGE_RESOLVER" || -L "$BRIDGE_RESOLVER" ]]; then
    echo "Error: missing regular bridge resolver: $BRIDGE_RESOLVER" >&2
    echo "This launcher runs from the installed plugin. From a source checkout, run ./install-plugin.sh and restart ChatGPT." >&2
    exit 1
fi
# shellcheck source=tools/bridge_paths.sh
source "$BRIDGE_RESOLVER"
if ! BRIDGE_ROOT="$(resolve_runtime_bridge "$PLUGIN_ROOT/bridge-path" "$HOME/Library/Application Support/ChatGPTCodexIMessage")"; then
    exit 1
fi
export CHATGPT_CODEX_IMESSAGE_BRIDGE="$BRIDGE_ROOT"

PYTHON="$BRIDGE_ROOT/mcp-venv/bin/python"
SERVER="$PLUGIN_ROOT/plugin_server/server.py"

if [[ ! -x "$PYTHON" ]]; then
    echo "iMessage MCP runtime is missing at $PYTHON; rerun ./install.sh or ./install-hardened.sh" >&2
    exit 1
fi

exec "$PYTHON" -I "$SERVER"
