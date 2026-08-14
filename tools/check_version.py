#!/usr/bin/env python3
"""Verify that a release tag matches all shipped component versions."""

from __future__ import annotations

import argparse
import ast
import json
import re
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def helper_version() -> str:
    module = ast.parse((REPO_ROOT / "bin" / "helper.py").read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "HELPER_VERSION":
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str):
                        return value
    raise RuntimeError("HELPER_VERSION not found in bin/helper.py")


def assigned_version(path: Path, variable: str) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == variable:
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str):
                        return value
    raise RuntimeError(f"{variable} not found in {path}")


def plugin_version() -> str:
    manifest = json.loads(
        (REPO_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    version = manifest.get("version")
    if not isinstance(version, str):
        raise RuntimeError("version not found in plugin manifest")
    return version


def skill_version() -> str:
    """Extract version from SKILL.md frontmatter."""
    skill_path = REPO_ROOT / "skills" / "chatgpt-codex-imessage" / "SKILL.md"
    content = skill_path.read_text(encoding="utf-8")
    match = re.search(r"^version:\s*(.+)$", content, re.MULTILINE)
    if not match:
        raise RuntimeError("version not found in SKILL.md frontmatter")
    return match.group(1).strip()


def shared_core_version() -> str:
    """Extract helper_version from shared-core.json."""
    manifest = json.loads(
        (REPO_ROOT / "shared-core.json").read_text(encoding="utf-8")
    )
    version = manifest.get("identity", {}).get("helper_version")
    if not isinstance(version, str):
        raise RuntimeError("identity.helper_version not found in shared-core.json")
    return version


def check_changelog(expected_version: str) -> tuple[bool, str]:
    """Verify CHANGELOG has exactly one dated heading for the version."""
    changelog_path = REPO_ROOT / "CHANGELOG.md"
    content = changelog_path.read_text(encoding="utf-8")

    pattern = (
        rf"^##[ \t]+{re.escape(expected_version)}[ \t]+-[ \t]+"
        r"([^\r\n]*?)[ \t]*\r?$"
    )
    matches = re.findall(pattern, content, re.MULTILINE)
    if len(matches) != 1:
        return (
            False,
            f"CHANGELOG.md must contain exactly one dated heading for "
            f"version {expected_version}; found {len(matches)}",
        )

    changelog_date = matches[0]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", changelog_date) is None:
        return False, f"CHANGELOG.md has invalid date {changelog_date!r}"
    try:
        date.fromisoformat(changelog_date)
    except ValueError:
        return False, f"CHANGELOG.md has invalid date {changelog_date!r}"

    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="release tag, for example v1.1.0")
    args = parser.parse_args()

    expected = args.tag[1:] if args.tag.startswith("v") else args.tag
    versions = {
        "helper": helper_version(),
        "plugin": plugin_version(),
        "MCP server": assigned_version(
            REPO_ROOT / "plugin_server" / "server.py", "SERVER_VERSION"
        ),
        "skill": skill_version(),
        "shared-core": shared_core_version(),
    }

    mismatches = {name: version for name, version in versions.items() if version != expected}
    if mismatches:
        for name, version in mismatches.items():
            print(f"{name} version {version!r} does not match tag {args.tag!r}")
        return 1

    changelog_ok, changelog_error = check_changelog(expected)
    if not changelog_ok:
        print(changelog_error)
        return 1

    print(f"release versions match {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
