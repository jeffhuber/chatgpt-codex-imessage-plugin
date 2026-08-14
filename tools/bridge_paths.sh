#!/bin/bash
# Resolve and persist the user-owned runtime bridge without evaluating config.

_imessage_bridge_path_is_valid() {
    local value="$1"

    [[ -n "$value" && "$value" == /* ]] || return 1
    [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || return 1
    if LC_ALL=C printf '%s' "$value" | /usr/bin/grep -q '[[:cntrl:]]'; then
        return 1
    fi
}

resolve_install_bridge() {
    local source_root="$1"
    local default_root="$2"
    local use_non_git_source="$3"
    local resolved

    if [[ "${CHATGPT_CODEX_IMESSAGE_BRIDGE+x}" == "x" ]]; then
        resolved="$CHATGPT_CODEX_IMESSAGE_BRIDGE"
        if ! _imessage_bridge_path_is_valid "$resolved"; then
            echo "Error: CHATGPT_CODEX_IMESSAGE_BRIDGE must be a non-empty absolute path without control characters." >&2
            return 1
        fi
    elif [[ "$use_non_git_source" == "1" && ! -e "$source_root/.git" ]]; then
        resolved="$source_root"
    else
        resolved="$default_root"
    fi

    _imessage_bridge_path_is_valid "$resolved" || return 1
    printf '%s\n' "$resolved"
}

write_bridge_path_file() {
    local destination="$1"
    local bridge_root="$2"

    _imessage_bridge_path_is_valid "$bridge_root" || return 1
    [[ ! -L "$destination" ]] || return 1
    printf '%s\n' "$bridge_root" > "$destination"
    chmod 600 "$destination"
}

read_bridge_path_file() {
    local source="$1"
    local value=""
    local extra=""

    [[ -f "$source" && ! -L "$source" ]] || return 1
    exec 3< "$source" || return 1
    if ! IFS= read -r value <&3 && [[ -z "$value" ]]; then
        exec 3<&-
        return 1
    fi
    if IFS= read -r extra <&3 || [[ -n "$extra" ]]; then
        exec 3<&-
        return 1
    fi
    exec 3<&-

    _imessage_bridge_path_is_valid "$value" || return 1
    printf '%s\n' "$value"
}

resolve_runtime_bridge() {
    local path_file="$1"
    local default_root="$2"
    local resolved

    if [[ "${CHATGPT_CODEX_IMESSAGE_BRIDGE+x}" == "x" ]]; then
        resolved="$CHATGPT_CODEX_IMESSAGE_BRIDGE"
        if ! _imessage_bridge_path_is_valid "$resolved"; then
            echo "Error: CHATGPT_CODEX_IMESSAGE_BRIDGE must be a non-empty absolute path without control characters." >&2
            return 1
        fi
    elif [[ -e "$path_file" || -L "$path_file" ]]; then
        if ! resolved="$(read_bridge_path_file "$path_file")"; then
            echo "Error: invalid bridge path file: $path_file" >&2
            return 1
        fi
    else
        resolved="$default_root"
    fi

    _imessage_bridge_path_is_valid "$resolved" || return 1
    printf '%s\n' "$resolved"
}
