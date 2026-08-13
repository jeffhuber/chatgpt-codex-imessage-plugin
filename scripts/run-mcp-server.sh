#!/bin/bash
set -euo pipefail

BRIDGE_ROOT="${CHATGPT_CODEX_IMESSAGE_BRIDGE:-$HOME/Library/Application Support/ChatGPTCodexIMessage}"
PYTHON="$BRIDGE_ROOT/mcp-venv/bin/python"
SERVER="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/plugin_server/server.py"

if [[ ! -x "$PYTHON" ]]; then
    echo "iMessage MCP runtime is missing at $PYTHON; rerun ./install.sh or ./install-hardened.sh" >&2
    exit 1
fi

exec "$PYTHON" -I "$SERVER"
