#!/bin/bash
# uninstall.sh — remove the ChatGPT/Codex iMessage launchd agent.
#
# Leaves helper source and runtime message data in place so any captured data
# is preserved. Also leaves the FDA grant — you must remove that
# manually in System Settings -> Privacy & Security -> Full Disk Access.

set -euo pipefail

# ---- Early guard: reject root/sudo ------------------------------------------
if [[ "$EUID" -eq 0 ]]; then
    printf "\033[31mError: Do not run this uninstaller as root or with sudo.\033[0m\n" 1>&2
    printf "This is a per-user LaunchAgent. Run as your normal user:\n" 1>&2
    printf "  ./uninstall.sh\n" 1>&2
    exit 1
fi

LABEL="com.jeffhuber.chatgpt-codex-imessage"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PLUGIN_NAME="chatgpt-codex-imessage-plugin"
PLUGIN_DEST="$HOME/plugins/$PLUGIN_NAME"
MARKETPLACE="$HOME/.agents/plugins/marketplace.json"
BRIDGE_ROOT="${CHATGPT_CODEX_IMESSAGE_BRIDGE:-$HOME/Library/Application Support/ChatGPTCodexIMessage}"

if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
    launchctl bootout "gui/$UID/$LABEL"
    echo "  launchd agent unloaded"
fi

CODEX="$(command -v codex 2>/dev/null || true)"
if [[ -z "$CODEX" && -x /Applications/Codex.app/Contents/Resources/codex ]]; then
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

if [[ -f "$PLIST_DEST" ]]; then
    rm -f "$PLIST_DEST"
    echo "  removed $PLIST_DEST"
fi

cat <<EOF

Uninstalled the launchd agent.

To fully remove the helper:
  - Delete this source folder and, after review, $BRIDGE_ROOT.
  - Open System Settings -> Privacy & Security -> Full Disk Access and
    revoke 'chatgpt-codex-imessage-helper'.
  - Open System Settings -> Privacy & Security -> Automation and revoke
    'chatgpt-codex-imessage-helper -> Messages'.
EOF
