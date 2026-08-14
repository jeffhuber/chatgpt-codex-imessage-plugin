#!/bin/bash
set -euo pipefail

# Resolve bridge root in priority order:
# 1. Fail-closed CHATGPT_CODEX_IMESSAGE_BRIDGE if present
# 2. bridge.env next to this plugin (written by install-plugin.sh)
# 3. Application Support fallback
if [[ -n "${CHATGPT_CODEX_IMESSAGE_BRIDGE+x}" ]]; then
    if [[ -z "$CHATGPT_CODEX_IMESSAGE_BRIDGE" ]]; then
        echo "Error: CHATGPT_CODEX_IMESSAGE_BRIDGE is set but empty; refusing to continue." >&2
        exit 1
    fi
    BRIDGE_ROOT="$CHATGPT_CODEX_IMESSAGE_BRIDGE"
else
    PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
    BRIDGE_ENV="$PLUGIN_DIR/bridge.env"
    if [[ -f "$BRIDGE_ENV" ]]; then
        # shellcheck disable=SC1090
        source "$BRIDGE_ENV"
    fi
    BRIDGE_ROOT="${CHATGPT_CODEX_IMESSAGE_BRIDGE:-$HOME/Library/Application Support/ChatGPTCodexIMessage}"
fi

PYTHON="$BRIDGE_ROOT/mcp-venv/bin/python"
SERVER="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/plugin_server/server.py"

if [[ ! -x "$PYTHON" ]]; then
    echo "iMessage MCP runtime is missing at $PYTHON; rerun ./install.sh or ./install-hardened.sh" >&2
    exit 1
fi

exec "$PYTHON" -I "$SERVER"
