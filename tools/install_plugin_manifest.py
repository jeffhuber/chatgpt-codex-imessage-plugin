#!/usr/bin/env python3
"""Atomically add the local iMessage plugin to the personal marketplace."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import stat
import tempfile
from typing import Any

PLUGIN_NAME = "chatgpt-codex-imessage-plugin"


def reject_symlink_components(path: pathlib.Path) -> None:
    absolute = path.expanduser().absolute()
    current = pathlib.Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"refusing symlinked marketplace path component: {current}")


def load_marketplace(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "name": "personal",
            "interface": {"displayName": "Personal"},
            "plugins": [],
        }
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError("existing marketplace must be a current-user-owned regular file")
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or not isinstance(parsed.get("plugins"), list):
        raise ValueError("existing marketplace must be an object with a plugins array")
    if parsed.get("name") != "personal":
        raise ValueError("the default personal marketplace must be named 'personal'")
    return parsed


def write_marketplace(marketplace_path: pathlib.Path, marketplace: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".marketplace.", suffix=".tmp", dir=marketplace_path.parent
    )
    temporary = pathlib.Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(marketplace, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, marketplace_path)
        os.chmod(marketplace_path, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def install_entry(
    marketplace_path: pathlib.Path,
    plugin_destination: pathlib.Path,
) -> None:
    marketplace_path = marketplace_path.expanduser().absolute()
    plugin_destination = plugin_destination.expanduser().absolute()
    expected_destination = pathlib.Path.home() / "plugins" / PLUGIN_NAME
    if plugin_destination != expected_destination:
        raise ValueError(f"plugin destination must be {expected_destination}")
    if not (plugin_destination / ".codex-plugin" / "plugin.json").is_file():
        raise ValueError("plugin destination is missing .codex-plugin/plugin.json")

    reject_symlink_components(marketplace_path)
    marketplace_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(marketplace_path.parent, 0o700)
    marketplace = load_marketplace(marketplace_path)
    marketplace.setdefault("interface", {"displayName": "Personal"})

    entry = {
        "name": PLUGIN_NAME,
        "source": {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }
    plugins = [item for item in marketplace["plugins"] if item.get("name") != PLUGIN_NAME]
    plugins.append(entry)
    marketplace["plugins"] = plugins
    write_marketplace(marketplace_path, marketplace)


def remove_entry(marketplace_path: pathlib.Path) -> None:
    marketplace_path = marketplace_path.expanduser().absolute()
    reject_symlink_components(marketplace_path)
    if not marketplace_path.exists():
        return
    marketplace = load_marketplace(marketplace_path)
    marketplace["plugins"] = [
        item for item in marketplace["plugins"] if item.get("name") != PLUGIN_NAME
    ]
    write_marketplace(marketplace_path, marketplace)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--marketplace", required=True, type=pathlib.Path)
    parser.add_argument("--plugin-destination", type=pathlib.Path)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    if args.remove:
        if args.plugin_destination is not None:
            parser.error("--plugin-destination cannot be used with --remove")
        remove_entry(args.marketplace)
    else:
        if args.plugin_destination is None:
            parser.error("--plugin-destination is required unless --remove is used")
        install_entry(args.marketplace, args.plugin_destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
