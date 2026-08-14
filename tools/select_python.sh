#!/bin/bash
# Select separate interpreters for the FDA helper and user-level MCP runtime.

_imessage_python_path() {
    local candidate="$1"
    local search_path="$2"

    [[ -n "$candidate" ]] || return 1
    if [[ "$candidate" == */* ]]; then
        printf '%s\n' "$candidate"
    else
        PATH="$search_path" command -v "$candidate" 2>/dev/null
    fi
}

_imessage_python_is_supported() {
    local candidate="$1"
    local minimum_minor="$2"
    local require_dir_fd="$3"

    [[ -x "$candidate" ]] &&
        "$candidate" -c 'import os, sys
minor = int(sys.argv[1])
require_dir_fd = sys.argv[2] == "1"
raise SystemExit(
    sys.version_info < (3, minor)
    or (require_dir_fd and os.open not in os.supports_dir_fd)
)' "$minimum_minor" "$require_dir_fd" 2>/dev/null
}

hardened_python_is_trusted() {
    local current="$1"
    local mode
    local owner

    [[ "$current" == /* && -f "$current" && ! -L "$current" ]] || return 1
    while :; do
        [[ ! -L "$current" ]] || return 1
        owner="$(/usr/bin/stat -f '%u' "$current" 2>/dev/null)" || return 1
        mode="$(/usr/bin/stat -f '%Lp' "$current" 2>/dev/null)" || return 1
        [[ "$owner" == "0" && -n "$mode" && "$mode" != *[!0-7]* ]] || return 1
        (( (8#$mode & 0022) == 0 )) || return 1
        [[ "$current" == "/" ]] && break
        current="${current%/*}"
        [[ -n "$current" ]] || current="/"
    done
}

_imessage_select_python() {
    local minimum_minor="$1"
    local require_dir_fd="$2"
    local require_trusted="$3"
    local search_path="$4"
    local override_is_set="$5"
    local override_value="$6"
    local candidate
    local resolved

    if [[ "$override_is_set" == "1" ]]; then
        [[ "$override_value" == /* ]] || return 1
        resolved="$(_imessage_python_path "$override_value" "$search_path")" || return 1
        [[ "$resolved" == /* ]] || return 1
        if [[ "$require_trusted" == "1" ]]; then
            hardened_python_is_trusted "$resolved" || return 1
        fi
        _imessage_python_is_supported \
            "$resolved" "$minimum_minor" "$require_dir_fd" || return 1
        printf '%s\n' "$resolved"
        return 0
    fi

    for candidate in /usr/bin/python3 \
        python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
        resolved="$(_imessage_python_path "$candidate" "$search_path")" || continue
        [[ "$resolved" == /* ]] || continue
        if [[ "$require_trusted" == "1" ]] &&
            ! hardened_python_is_trusted "$resolved"; then
            continue
        fi
        _imessage_python_is_supported \
            "$resolved" "$minimum_minor" "$require_dir_fd" || continue
        printf '%s\n' "$resolved"
        return 0
    done
    return 1
}

find_helper_python() {
    local search_path="${1:-$PATH}"
    local require_trusted="${2:-0}"

    if [[ "${IMESSAGE_HELPER_PYTHON+x}" == "x" ]]; then
        _imessage_select_python \
            9 1 "$require_trusted" "$search_path" 1 "$IMESSAGE_HELPER_PYTHON"
    else
        _imessage_select_python 9 1 "$require_trusted" "$search_path" 0 ""
    fi
}

find_mcp_python() {
    local search_path="${1:-$PATH}"

    if [[ "${IMESSAGE_PYTHON+x}" == "x" ]]; then
        _imessage_select_python 10 0 0 "$search_path" 1 "$IMESSAGE_PYTHON"
    else
        _imessage_select_python 10 0 0 "$search_path" 0 ""
    fi
}
