#!/bin/bash
# Install the local plugin, MCP runtime, and personal marketplace entry.

set -euo pipefail

if [[ "$EUID" -eq 0 ]]; then
    echo "Error: run install-plugin.sh as your normal user, not with sudo." >&2
    exit 1
fi

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PLUGIN_NAME="chatgpt-codex-imessage-plugin"
PLUGIN_PARENT="$HOME/plugins"
PLUGIN_DEST="$PLUGIN_PARENT/$PLUGIN_NAME"
MARKETPLACE="$HOME/.agents/plugins/marketplace.json"
BRIDGE_ROOT="${CHATGPT_CODEX_IMESSAGE_BRIDGE:-$HOME/Library/Application Support/ChatGPTCodexIMessage}"
MCP_VENV="$BRIDGE_ROOT/mcp-venv"
PYTHON_SELECTOR="$SOURCE_ROOT/tools/select_python.sh"

if [[ ! -f "$PYTHON_SELECTOR" || -L "$PYTHON_SELECTOR" ]]; then
    echo "Error: missing regular Python selector: $PYTHON_SELECTOR" >&2
    exit 1
fi
# shellcheck source=tools/select_python.sh
source "$PYTHON_SELECTOR"

require_directory_or_missing() {
    local path="$1"
    if [[ -L "$path" ]]; then
        echo "Error: refusing symlinked installation path: $path" >&2
        exit 1
    fi
    if [[ -e "$path" && ! -d "$path" ]]; then
        echo "Error: expected a directory: $path" >&2
        exit 1
    fi
}

if ! PYTHON="$(find_mcp_python "$PATH")"; then
    echo "Error: Python 3.10 or newer is required for the MCP runtime." >&2
    echo "If IMESSAGE_PYTHON is set, it must name a supported interpreter." >&2
    exit 1
fi

for path in "$BRIDGE_ROOT" "$MCP_VENV" "$PLUGIN_PARENT" "$PLUGIN_DEST"; do
    require_directory_or_missing "$path"
done

mkdir -p "$BRIDGE_ROOT" "$PLUGIN_PARENT"
chmod 700 "$BRIDGE_ROOT" "$PLUGIN_PARENT"

if [[ ! -x "$MCP_VENV/bin/python" ]]; then
    "$PYTHON" -m venv "$MCP_VENV"
fi
"$MCP_VENV/bin/python" -m pip install \
    --disable-pip-version-check \
    --requirement "$SOURCE_ROOT/requirements-mcp.txt"

STAGING="$(mktemp -d "$PLUGIN_PARENT/.${PLUGIN_NAME}.install.XXXXXX")"
BACKUP=""
cleanup() {
    rm -rf "$STAGING"
    if [[ -n "$BACKUP" && -d "$BACKUP" && ! -e "$PLUGIN_DEST" ]]; then
        mv "$BACKUP" "$PLUGIN_DEST"
    fi
}
trap cleanup EXIT

mkdir -p "$STAGING/scripts"
for directory in .codex-plugin plugin_server skills; do
    cp -R "$SOURCE_ROOT/$directory" "$STAGING/$directory"
done
cp "$SOURCE_ROOT/.mcp.json" "$STAGING/.mcp.json"
cp "$SOURCE_ROOT/scripts/run-mcp-server.sh" "$STAGING/scripts/run-mcp-server.sh"
cp "$SOURCE_ROOT/LICENSE" "$STAGING/LICENSE"
find "$STAGING" -type d -exec chmod 700 {} +
find "$STAGING" -type f -exec chmod 600 {} +
chmod 700 "$STAGING/scripts/run-mcp-server.sh"

if [[ -d "$PLUGIN_DEST" ]]; then
    BACKUP="$PLUGIN_PARENT/.${PLUGIN_NAME}.backup.$$"
    if [[ -e "$BACKUP" ]]; then
        echo "Error: stale plugin backup already exists: $BACKUP" >&2
        exit 1
    fi
    mv "$PLUGIN_DEST" "$BACKUP"
fi
mv "$STAGING" "$PLUGIN_DEST"
STAGING=""
if [[ -n "$BACKUP" ]]; then
    rm -rf "$BACKUP"
    BACKUP=""
fi

"$PYTHON" "$SOURCE_ROOT/tools/install_plugin_manifest.py" \
    --marketplace "$MARKETPLACE" \
    --plugin-destination "$PLUGIN_DEST"

CODEX="$(command -v codex 2>/dev/null || true)"
if [[ -z "$CODEX" && -x /Applications/Codex.app/Contents/Resources/codex ]]; then
    CODEX="/Applications/Codex.app/Contents/Resources/codex"
fi
if [[ -n "$CODEX" ]]; then
    if ! "$CODEX" plugin add "$PLUGIN_NAME@personal" >/dev/null 2>&1; then
        echo "Warning: plugin files are installed, but automatic enablement did not succeed." >&2
        echo "Open Plugins in the ChatGPT desktop app and install $PLUGIN_NAME from Personal." >&2
    fi
else
    echo "Warning: Codex CLI not found; install the plugin from Personal in the desktop app." >&2
fi

echo "Installed local plugin: $PLUGIN_DEST"
echo "Installed MCP runtime: $MCP_VENV"
echo "MCP bootstrap Python: $PYTHON"
echo "Updated personal marketplace: $MARKETPLACE"
echo "Restart the ChatGPT desktop app before first use."
