#!/bin/bash
# Remove the hardened helper while preserving the user-owned runtime bridge.

set -euo pipefail
PATH="/usr/bin:/bin:/usr/sbin:/sbin"
export PATH

if [[ "$EUID" -eq 0 ]]; then
    echo "Error: run as your normal user; this script invokes sudo narrowly." >&2
    exit 1
fi

LABEL="com.jeffhuber.chatgpt-codex-imessage"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PLUGIN_NAME="chatgpt-codex-imessage-plugin"
PLUGIN_DEST="$HOME/plugins/$PLUGIN_NAME"
MARKETPLACE="$HOME/.agents/plugins/marketplace.json"
PRODUCT_ROOT="/Library/Application Support/ChatGPTCodexIMessage"
USER_ROOT="$PRODUCT_ROOT/users/$UID"
BRIDGE_ROOT="${CHATGPT_CODEX_IMESSAGE_BRIDGE:-$HOME/Library/Application Support/ChatGPTCodexIMessage}"

if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
    launchctl bootout "gui/$UID/$LABEL"
    echo "  launchd agent unloaded"
fi
if [[ -f "$PLIST_DEST" ]]; then
    rm -f "$PLIST_DEST"
    echo "  removed $PLIST_DEST"
fi
CODEX=""
if [[ -x /Applications/Codex.app/Contents/Resources/codex ]]; then
    CODEX="/Applications/Codex.app/Contents/Resources/codex"
fi
if [[ -n "$CODEX" ]]; then
    "$CODEX" plugin remove "$PLUGIN_NAME" >/dev/null 2>&1 || true
fi
if [[ -L "$PLUGIN_DEST" ]]; then
    echo "Error: refusing symlinked plugin path: $PLUGIN_DEST" >&2
    exit 1
fi
if [[ -d "$PLUGIN_DEST" ]]; then
    rm -rf "$PLUGIN_DEST"
    echo "  removed local plugin $PLUGIN_DEST"
fi
python3 "$SOURCE_ROOT/tools/install_plugin_manifest.py" \
    --marketplace "$MARKETPLACE" --remove
if [[ -L "$BRIDGE_ROOT/mcp-venv" ]]; then
    echo "Error: refusing symlinked MCP runtime path: $BRIDGE_ROOT/mcp-venv" >&2
    exit 1
fi
if [[ -d "$BRIDGE_ROOT/mcp-venv" ]]; then
    rm -rf "$BRIDGE_ROOT/mcp-venv"
    echo "  removed MCP runtime $BRIDGE_ROOT/mcp-venv"
fi
if [[ -d "$USER_ROOT" ]]; then
    sudo /bin/rm -rf "$USER_ROOT"
    echo "  removed root-owned helper $USER_ROOT"
    if sudo /bin/rmdir "$PRODUCT_ROOT/users" 2>/dev/null; then
        if ! sudo /bin/rmdir "$PRODUCT_ROOT" 2>/dev/null; then
            echo "  retained non-empty $PRODUCT_ROOT"
        fi
    fi
fi

cat <<EOF

Hardened helper uninstalled. Runtime data remains at:
  $BRIDGE_ROOT

Delete that directory only after reviewing any responses/logs you need.
Revoke chatgpt-codex-imessage-helper under Full Disk Access and Automation in
System Settings -> Privacy & Security.
EOF
