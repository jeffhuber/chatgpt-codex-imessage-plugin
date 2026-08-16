#!/bin/bash
# Run the repository's Python checks with one explicitly validated interpreter.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SELECTOR="$REPO_ROOT/tools/select_python.sh"

if [[ ! -f "$SELECTOR" || -L "$SELECTOR" ]]; then
    echo "Error: missing regular Python selector: $SELECTOR" >&2
    exit 1
fi
# shellcheck source=tools/select_python.sh
source "$SELECTOR"

if [[ "$#" -gt 1 ]]; then
    echo "Usage: $0 [vX.Y.Z]" >&2
    exit 2
fi

test_python_is_usable() {
    local candidate="$1"
    [[ "$candidate" == /* ]] || return 1
    _imessage_python_is_supported "$candidate" 10 0 || return 1
    "$candidate" -c 'import mcp' >/dev/null 2>&1
}

if [[ "${IMESSAGE_TEST_PYTHON+x}" == "x" ]]; then
    if ! test_python_is_usable "$IMESSAGE_TEST_PYTHON"; then
        echo "Error: IMESSAGE_TEST_PYTHON must be an absolute path to Python 3.10+ with requirements-mcp.txt installed." >&2
        exit 1
    fi
    TEST_PYTHON="$IMESSAGE_TEST_PYTHON"
else
    TEST_PYTHON=""
    for candidate in \
        "$REPO_ROOT/.venv/bin/python" \
        "$HOME/imessage-bridge-chatgpt/mcp-venv/bin/python" \
        "$HOME/Library/Application Support/ChatGPTCodexIMessage/mcp-venv/bin/python"; do
        if test_python_is_usable "$candidate"; then
            TEST_PYTHON="$candidate"
            break
        fi
    done
    if [[ -z "$TEST_PYTHON" ]]; then
        candidate="$(find_mcp_python "$PATH" || true)"
        if test_python_is_usable "$candidate"; then
            TEST_PYTHON="$candidate"
        fi
    fi
    if [[ -z "$TEST_PYTHON" ]]; then
        echo "Error: no Python 3.10+ interpreter with requirements-mcp.txt installed was found." >&2
        echo "Create .venv, install requirements-mcp.txt, or set absolute IMESSAGE_TEST_PYTHON." >&2
        exit 1
    fi
fi

cd "$REPO_ROOT"
printf 'Test interpreter: %s (%s)\n' \
    "$TEST_PYTHON" "$("$TEST_PYTHON" -c 'import platform; print(platform.python_version())')"
"$TEST_PYTHON" -m py_compile \
    bin/helper.py bin/send_gate.py plugin_server/bridge.py plugin_server/server.py \
    bridge_mcp/server.py bridge_mcp/client.py bridge_mcp/host_detection.py bridge_mcp_main.py \
    tools/doctor.py tools/check_version.py tools/configure_allowlist.py \
    tools/check_shared_core.py tools/install_plugin_manifest.py
"$TEST_PYTHON" -m unittest discover -s tests -v
"$TEST_PYTHON" tools/check_shared_core.py
"$TEST_PYTHON" -m json.tool .codex-plugin/plugin.json >/dev/null

if [[ "$#" -eq 1 ]]; then
    "$TEST_PYTHON" tools/check_version.py "$1"
fi
