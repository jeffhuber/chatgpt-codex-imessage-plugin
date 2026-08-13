#!/bin/bash
# Install trusted code root-owned and keep request/response state user-owned.

set -euo pipefail
ORIGINAL_PATH="$PATH"
PATH="/usr/bin:/bin:/usr/sbin:/sbin"
export PATH

if [[ "$EUID" -eq 0 ]]; then
    echo "Error: run this script as your normal user; it invokes sudo narrowly." >&2
    exit 1
fi
if [[ "$(uname)" != "Darwin" ]]; then
    echo "Error: the hardened installer only runs on macOS." >&2
    exit 1
fi

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PRODUCT_ROOT="/Library/Application Support/ChatGPTCodexIMessage"
USER_ROOT="$PRODUCT_ROOT/users/$UID"
CODE_ROOT="$USER_ROOT/libexec"
CONFIG_ROOT="$USER_ROOT/config"
BRIDGE_ROOT="${CHATGPT_CODEX_IMESSAGE_BRIDGE:-$HOME/Library/Application Support/ChatGPTCodexIMessage}"
PLIST_TEMPLATE="$SOURCE_ROOT/com.jeffhuber.chatgpt-codex-imessage.plist.template"
PLIST_DEST="$HOME/Library/LaunchAgents/com.jeffhuber.chatgpt-codex-imessage.plist"
LABEL="com.jeffhuber.chatgpt-codex-imessage"
ALLOWLIST="$CONFIG_ROOT/allowed_chats.txt"
CURRENT_USER="$(id -un)"
INSTALL_OPENAI_PLUGIN="${INSTALL_OPENAI_PLUGIN:-1}"
BUILD_DIR="$(mktemp -d -t chatgpt-codex-imessage-build.XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

require_safe_runtime_entry() {
    local path="$1"
    local kind="$2"
    if [[ -L "$path" ]]; then
        echo "Error: refusing symlinked runtime path: $path" >&2
        exit 1
    fi
    if [[ -e "$path" && "$kind" == "directory" && ! -d "$path" ]]; then
        echo "Error: expected a runtime directory: $path" >&2
        exit 1
    fi
    if [[ -e "$path" && "$kind" == "file" && ! -f "$path" ]]; then
        echo "Error: expected a regular runtime file: $path" >&2
        exit 1
    fi
}

find_supported_python() {
    local candidate
    local resolved
    local restricted_path="$PATH"
    PATH="$ORIGINAL_PATH"
    for candidate in "${IMESSAGE_PYTHON:-}" python3.13 python3.12 python3.11 python3.10 python3; do
        [[ -n "$candidate" ]] || continue
        if [[ "$candidate" == */* ]]; then
            resolved="$candidate"
        else
            resolved="$(command -v "$candidate" 2>/dev/null || true)"
        fi
        if [[ -x "$resolved" ]] &&
            "$resolved" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' 2>/dev/null; then
            PATH="$restricted_path"
            printf '%s\n' "$resolved"
            return 0
        fi
    done
    PATH="$restricted_path"
    return 1
}

if [[ "$INSTALL_OPENAI_PLUGIN" != "0" && "$INSTALL_OPENAI_PLUGIN" != "1" ]]; then
    echo "Error: INSTALL_OPENAI_PLUGIN must be 0 or 1." >&2
    exit 1
fi

for cmd in clang codesign launchctl sudo; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: required command not found: $cmd" >&2
        exit 1
    fi
done
if ! xcode-select -p >/dev/null 2>&1; then
    echo "Error: install Xcode Command Line Tools with xcode-select --install" >&2
    exit 1
fi
if ! PYTHON3_PATH="$(find_supported_python)"; then
    echo "Error: Python 3.10 or newer is required for the MCP runtime." >&2
    exit 1
fi

for path in \
    "$SOURCE_ROOT/bin/helper.py" \
    "$SOURCE_ROOT/bin/send_gate.py" \
    "$SOURCE_ROOT/bin/imessage_helper.c" \
    "$SOURCE_ROOT/bin/confirm_imessage_send.m" \
    "$SOURCE_ROOT/tools/doctor.py" \
    "$SOURCE_ROOT/tools/configure_allowlist.py" \
    "$SOURCE_ROOT/contacts/blocked_chats.txt.template" \
    "$SOURCE_ROOT/contacts/allowed_chats.txt.template" \
    "$SOURCE_ROOT/install-plugin.sh" \
    "$SOURCE_ROOT/requirements-mcp.txt" \
    "$PLIST_TEMPLATE"; do
    if [[ ! -f "$path" ]]; then
        echo "Error: missing source file: $path" >&2
        exit 1
    fi
done

for path in "$BRIDGE_ROOT/control" "$BRIDGE_ROOT/control/requests" \
    "$BRIDGE_ROOT/control/responses" "$BRIDGE_ROOT/contacts"; do
    require_safe_runtime_entry "$path" directory
done
for path in "$BRIDGE_ROOT/control/log.txt" \
    "$BRIDGE_ROOT/contacts/blocked_chats.txt" \
    "$BRIDGE_ROOT/contacts/read_policy.txt"; do
    require_safe_runtime_entry "$path" file
done
mkdir -p "$BRIDGE_ROOT/control/requests" "$BRIDGE_ROOT/control/responses" \
    "$BRIDGE_ROOT/contacts"
BRIDGE_ROOT="$(cd "$BRIDGE_ROOT" && pwd -P)"
touch "$BRIDGE_ROOT/control/log.txt"
chmod 700 "$BRIDGE_ROOT" "$BRIDGE_ROOT/control" \
    "$BRIDGE_ROOT/control/requests" "$BRIDGE_ROOT/control/responses" \
    "$BRIDGE_ROOT/contacts"
chmod 600 "$BRIDGE_ROOT/control/log.txt"

if [[ ! -f "$BRIDGE_ROOT/contacts/blocked_chats.txt" ]]; then
    cp "$SOURCE_ROOT/contacts/blocked_chats.txt.template" \
        "$BRIDGE_ROOT/contacts/blocked_chats.txt"
fi
printf 'allowlist\n' > "$BRIDGE_ROOT/contacts/read_policy.txt"
chmod 600 "$BRIDGE_ROOT/contacts/blocked_chats.txt" \
    "$BRIDGE_ROOT/contacts/read_policy.txt"

echo "Requesting administrator access for the root-owned code and policy..."
sudo -v
sudo /usr/bin/install -d -o root -g wheel -m 755 \
    "$PRODUCT_ROOT" "$PRODUCT_ROOT/users" "$USER_ROOT" "$CODE_ROOT" \
    "$CODE_ROOT/bin" "$CODE_ROOT/tools" "$CONFIG_ROOT"
if [[ -L "$ALLOWLIST" ]]; then
    echo "Error: hardened allowlist must not be a symlink: $ALLOWLIST" >&2
    exit 1
fi
if [[ ! -e "$ALLOWLIST" ]]; then
    sudo /usr/bin/install -o root -g wheel -m 600 \
        "$SOURCE_ROOT/contacts/allowed_chats.txt.template" "$ALLOWLIST"
fi
if ! "$PYTHON3_PATH" - "$ALLOWLIST" <<'PYCHECK'; then
import os
import stat
import sys

metadata = os.lstat(sys.argv[1])
valid = stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0
valid = valid and not metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
raise SystemExit(0 if valid else 1)
PYCHECK
    echo "Error: existing hardened allowlist is not a protected root-owned file." >&2
    exit 1
fi
if ! sudo /bin/chmod -N "$ALLOWLIST" 2>/dev/null; then
    echo "  no existing ACL to clear"
fi
sudo /bin/chmod +a "user:$CURRENT_USER allow read" "$ALLOWLIST"

clang -Wall -Wextra -Werror -fobjc-arc \
    -framework AppKit -framework Foundation \
    -o "$BUILD_DIR/chatgpt-codex-imessage-confirm" "$SOURCE_ROOT/bin/confirm_imessage_send.m"

clang -Wall -Wextra -Werror -O2 \
    -DHELPER_SCRIPT="\"$CODE_ROOT/bin/helper.py\"" \
    -DSEND_GATE_SCRIPT="\"$CODE_ROOT/bin/send_gate.py\"" \
    -DCONFIRM_HELPER="\"$CODE_ROOT/bin/chatgpt-codex-imessage-confirm\"" \
    -DBRIDGE_ROOT="\"$BRIDGE_ROOT\"" \
    -DPYTHON_INTERPRETER="\"$PYTHON3_PATH\"" \
    -DEXPECTED_CODE_UID=0 \
    -DREAD_POLICY_MODE='"allowlist"' \
    -DREAD_ALLOWLIST_PATH="\"$ALLOWLIST\"" \
    -DREQUIRE_ROOT_POLICY=1 \
    -DHELPER_DISPLAY_NAME='"chatgpt-codex-imessage-helper"' \
    -DHOST_DISPLAY_NAME='"ChatGPT/Codex"' \
    -o "$BUILD_DIR/chatgpt-codex-imessage-helper" \
    "$SOURCE_ROOT/bin/imessage_helper.c"

CODESIGN_IDENTITY="${CODESIGN_IDENTITY:--}"
SIGN_ARGS=(--force --sign "$CODESIGN_IDENTITY" --options runtime)
if [[ "$CODESIGN_IDENTITY" != "-" ]]; then
    SIGN_ARGS+=(--timestamp)
fi
codesign "${SIGN_ARGS[@]}" "$BUILD_DIR/chatgpt-codex-imessage-helper"
codesign "${SIGN_ARGS[@]}" "$BUILD_DIR/chatgpt-codex-imessage-confirm"

sudo /usr/bin/install -o root -g wheel -m 444 \
    "$SOURCE_ROOT/bin/helper.py" "$CODE_ROOT/bin/helper.py"
sudo /usr/bin/install -o root -g wheel -m 444 \
    "$SOURCE_ROOT/bin/send_gate.py" "$CODE_ROOT/bin/send_gate.py"
sudo /usr/bin/install -o root -g wheel -m 444 \
    "$SOURCE_ROOT/bin/imessage_helper.c" "$CODE_ROOT/bin/imessage_helper.c"
sudo /usr/bin/install -o root -g wheel -m 444 \
    "$SOURCE_ROOT/bin/confirm_imessage_send.m" "$CODE_ROOT/bin/confirm_imessage_send.m"
sudo /usr/bin/install -o root -g wheel -m 555 \
    "$BUILD_DIR/chatgpt-codex-imessage-helper" "$CODE_ROOT/bin/chatgpt-codex-imessage-helper"
sudo /usr/bin/install -o root -g wheel -m 555 \
    "$BUILD_DIR/chatgpt-codex-imessage-confirm" "$CODE_ROOT/bin/chatgpt-codex-imessage-confirm"
sudo /usr/bin/install -o root -g wheel -m 555 \
    "$SOURCE_ROOT/tools/doctor.py" "$CODE_ROOT/tools/doctor.py"
sudo /usr/bin/install -o root -g wheel -m 555 \
    "$SOURCE_ROOT/tools/configure_allowlist.py" "$CODE_ROOT/tools/configure_allowlist.py"

mkdir -p "$(dirname "$PLIST_DEST")"
"$PYTHON3_PATH" - "$CODE_ROOT" "$BRIDGE_ROOT" "$PLIST_DEST" "$PLIST_TEMPLATE" <<'PYGEN'
import sys
import xml.etree.ElementTree as ET

code_root, bridge_root, destination, template = sys.argv[1:]
tree = ET.parse(template)
for element in tree.getroot().iter("string"):
    if element.text:
        element.text = element.text.replace("{{CODE_ROOT}}", code_root)
        element.text = element.text.replace("{{BRIDGE_ROOT}}", bridge_root)
tree.write(destination, encoding="UTF-8", xml_declaration=True)
PYGEN
chmod 644 "$PLIST_DEST"

if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
    launchctl bootout "gui/$UID/$LABEL"
fi
launchctl bootstrap "gui/$UID" "$PLIST_DEST"
launchctl enable "gui/$UID/$LABEL"
if [[ "$INSTALL_OPENAI_PLUGIN" == "1" ]]; then
    PATH="$ORIGINAL_PATH" \
        IMESSAGE_PYTHON="$PYTHON3_PATH" \
        CHATGPT_CODEX_IMESSAGE_BRIDGE="$BRIDGE_ROOT" \
        "$SOURCE_ROOT/install-plugin.sh"
else
    echo "  skipped OpenAI plugin installation (INSTALL_OPENAI_PLUGIN=0)"
fi

cat <<EOF

Hardened install complete.

Trusted code (root-owned): $CODE_ROOT
Runtime bridge (user-owned): $BRIDGE_ROOT
Read policy: root-owned allowlist (default-deny)

Add an allowed contact before reading:
  python3 "$CODE_ROOT/tools/configure_allowlist.py" add +15551234567

Grant Full Disk Access to:
  $CODE_ROOT/bin/chatgpt-codex-imessage-helper

Then verify:
  "$PYTHON3_PATH" "$CODE_ROOT/tools/doctor.py" --bridge "$BRIDGE_ROOT" --code-root "$CODE_ROOT" --architecture hardened
EOF
