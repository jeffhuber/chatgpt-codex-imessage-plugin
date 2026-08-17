"""`bridge-mcp host-assets` (MCP-5): manage the Bridge Pro plugin manifest for
ChatGPT/Codex (docs/BRIDGE_MCP.md "host-assets Command"; successor to
tools/install_plugin_manifest.py).

Stdlib only. Manages ONLY the `bridge-pro-imessage` entry; the DIY
`chatgpt-codex-imessage-plugin` entry is never touched. Paths are fixed:
manifest `~/.agents/plugins/marketplace.json`, plugin dir
`~/plugins/bridge-pro-imessage/`; the MCP command is
`<bundle>/Contents/MacOS/bridge-mcp` (absolute, inside the bundle) taken from
BRIDGE_PRO_BUNDLE_ROOT — never a caller-supplied path.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
from typing import Any

from bridge_mcp.host_detection import BRIDGE_PRO_PLUGIN_NAME, DIY_PLUGIN_NAME, detect_hosts

SUPPORTED_HOSTS = ("chatgpt", "codex")   # both register through the same personal marketplace
VERSION = "1.3.0"
MCP_RELPATH = "Contents/MacOS/bridge-mcp"


def _reject_symlink_components(path: pathlib.Path) -> None:
    current = pathlib.Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ValueError(f"refusing symlinked path component: {current}")
        except FileNotFoundError:
            return


def _bundle_command(bundle_root: str | None) -> pathlib.Path:
    root = bundle_root or os.environ.get("BRIDGE_PRO_BUNDLE_ROOT")
    if not root:
        raise ValueError("BRIDGE_PRO_BUNDLE_ROOT is not set (host-assets install runs through the bundled launcher)")
    root_path = pathlib.Path(root)
    if not root_path.is_absolute() or ".." in root_path.parts:
        raise ValueError("bundle root must be an absolute path")
    command = root_path / MCP_RELPATH
    # Never follow symlinks: a symlinked bundle root or descendant could persist a command resolving outside the bundle.
    _reject_symlink_components(command)
    try:
        if not stat.S_ISREG(command.lstat().st_mode):
            raise ValueError(f"bridge-mcp launcher is not a regular file: {command}")
    except FileNotFoundError:
        raise ValueError(f"bridge-mcp launcher missing at {command}") from None
    return command


EXPECTED_SOURCE_PATH = f"./plugins/{BRIDGE_PRO_PLUGIN_NAME}"


def _paths(home: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    return home / ".agents" / "plugins" / "marketplace.json", home / "plugins" / BRIDGE_PRO_PLUGIN_NAME


def _load_marketplace(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError("existing marketplace must be a current-user-owned regular file")
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or not isinstance(parsed.get("plugins"), list):
        raise ValueError("existing marketplace must be an object with a plugins array")
    if parsed.get("name") != "personal":
        # Activation targets bridge-pro-imessage@personal; writing into any other marketplace would "succeed" and never activate.
        raise ValueError("existing marketplace must be the Codex 'personal' marketplace")
    return parsed


def _ensure_private_dir(path: pathlib.Path) -> None:
    """mkdir -p 0700 and, for pre-existing components we own, strip group/world bits."""
    _reject_symlink_components(path)
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    current = path
    for _ in range(3):   # the plugin dir and its parents we created: <home>/plugins/<name>[/.codex-plugin]
        st = current.lstat()
        if stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and (st.st_mode & 0o077):
            os.chmod(current, 0o700)
        if current.name in ("plugins", ".agents") or current == current.parent:
            break
        current = current.parent


def _write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    _reject_symlink_components(path)
    _ensure_private_dir(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = pathlib.Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _plugin_files(plugin_dir: pathlib.Path, command: pathlib.Path) -> None:
    _write_json(plugin_dir / ".mcp.json", {"mcpServers": {"bridge-pro-imessage": {
        "command": str(command), "args": ["--product", "openai"],
        "startup_timeout_sec": 15, "tool_timeout_sec": 90, "default_tools_approval_mode": "writes"}}})
    _write_json(plugin_dir / ".codex-plugin" / "plugin.json", {
        "name": BRIDGE_PRO_PLUGIN_NAME, "version": VERSION,
        "description": "Bridge Pro iMessage bridge (managed by Bridge Pro.app; do not edit).",
        "mcpServers": "./.mcp.json",
        "interface": {"displayName": "Bridge Pro iMessage", "category": "Productivity"}})


def _entry_state(marketplace: dict[str, Any], plugin_dir: pathlib.Path, command: pathlib.Path | None) -> tuple[str, dict[str, Any] | None]:
    ours = next((p for p in marketplace["plugins"] if isinstance(p, dict) and p.get("name") == BRIDGE_PRO_PLUGIN_NAME), None)
    diy = next((p for p in marketplace["plugins"] if isinstance(p, dict) and p.get("name") == DIY_PLUGIN_NAME), None)
    if ours is None:
        return ("diy_only" if diy else "missing"), ours
    # The entry must point at the fixed local plugin dir; otherwise the host loads nothing even if our files exist.
    source = ours.get("source")
    if not isinstance(source, dict) or source.get("source") != "local" or source.get("path") != EXPECTED_SOURCE_PATH:
        return "mismatch", ours
    mcp_path = plugin_dir / ".mcp.json"
    try:
        servers = json.loads(mcp_path.read_text(encoding="utf-8"))
        configured = servers["mcpServers"]["bridge-pro-imessage"] if isinstance(servers, dict) else None
        if not isinstance(configured, dict):
            return "mismatch", ours
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return "mismatch", ours
    try:
        plugin_meta = json.loads((plugin_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        version = plugin_meta.get("version") if isinstance(plugin_meta, dict) else None
    except (OSError, json.JSONDecodeError):
        version = None
    # No resolvable current bundle ⇒ nothing can be "current"; verify reports it rather than skipping the comparison.
    current = command is not None and configured.get("command") == str(command) and \
        configured.get("args") == ["--product", "openai"] and version == VERSION
    return ("installed" if current else "mismatch"), ours


# Where the Codex CLI normally lives. The bundled launcher sanitizes PATH to /usr/bin:/bin, so PATH lookup alone
# misses npm/Homebrew installs; the app may also pass an explicit --codex-path it trusts.
KNOWN_CODEX_LOCATIONS = ("/opt/homebrew/bin/codex", "/usr/local/bin/codex", "~/.local/bin/codex", "~/.npm-global/bin/codex", "~/.codex/bin/codex")


def _resolve_codex(codex_path: str | None) -> str | None:
    candidates = [codex_path] if codex_path else [shutil.which("codex"), *(os.path.expanduser(c) for c in KNOWN_CODEX_LOCATIONS)]
    for cand in candidates:
        if not cand:
            continue
        try:
            st = os.stat(cand)
        except OSError:
            continue
        # Trusted only if a regular executable owned by root or us and not group/world-writable.
        if stat.S_ISREG(st.st_mode) and st.st_uid in (0, os.getuid()) and not (st.st_mode & 0o022) and os.access(cand, os.X_OK):
            return cand
    return None


def _codex_plugin_add(codex_path: str | None) -> str:
    """Documented activation step for Codex: `codex plugin add bridge-pro-imessage@personal`.
    Fixed argv, no shell; only the resolved Codex CLI (explicit path, PATH, or a known install location). Reports
    what happened — 'activated', 'codex-not-found' (fine on ChatGPT-only Macs), or 'failed:<code>'."""
    exe = _resolve_codex(codex_path)
    if not exe:
        return "codex-not-found"
    try:
        result = subprocess.run([exe, "plugin", "add", f"{BRIDGE_PRO_PLUGIN_NAME}@personal"], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "failed:launch"
    return "activated" if result.returncode == 0 else f"failed:{result.returncode}"


def host_assets(subcommand: str, *, host: str | None = None, all_hosts: bool = False, refresh: bool = False,
                home: pathlib.Path | None = None, bundle_root: str | None = None, codex_path: str | None = None) -> dict[str, Any]:
    """Run one host-assets verb; returns the --json payload."""
    if subcommand not in ("detect", "install", "verify", "remove"):
        raise ValueError(f"unknown host-assets subcommand: {subcommand}")
    if host is not None and host not in SUPPORTED_HOSTS:
        raise ValueError(f"unsupported host: {host}; expected one of {list(SUPPORTED_HOSTS)}")
    if (host is None) == (not all_hosts):
        raise ValueError("exactly one of --host or --all is required")
    targets = list(SUPPORTED_HOSTS) if all_hosts else [host]
    home = pathlib.Path(home) if home else pathlib.Path.home()
    marketplace_path, plugin_dir = _paths(home)

    if subcommand == "detect":
        detected = detect_hosts(home)["openai"]
        return {"ok": True, "hosts": {t: {"status": detected["asset_status"], "markers": detected["markers"]} for t in targets}}

    command: pathlib.Path | None = None
    if subcommand == "install":
        command = _bundle_command(bundle_root)
        marketplace = _load_marketplace(marketplace_path)
        state, _ = _entry_state(marketplace, plugin_dir, command)
        if state != "installed" or refresh:
            _plugin_files(plugin_dir, command)
            entry = {"name": BRIDGE_PRO_PLUGIN_NAME,
                     "source": {"source": "local", "path": EXPECTED_SOURCE_PATH},
                     "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                     "category": "Productivity"}
            marketplace["plugins"] = [p for p in marketplace["plugins"] if not (isinstance(p, dict) and p.get("name") == BRIDGE_PRO_PLUGIN_NAME)] + [entry]
            _write_json(marketplace_path, marketplace)
        hosts: dict[str, Any] = {}
        for t in targets:
            info: dict[str, Any] = {"status": "installed", "version": VERSION, "path": str(command)}
            if t == "codex":
                info["codex_activation"] = _codex_plugin_add(codex_path)
            hosts[t] = info
        return {"ok": True, "hosts": hosts}

    if subcommand == "remove":
        if marketplace_path.exists():
            marketplace = _load_marketplace(marketplace_path)
            marketplace["plugins"] = [p for p in marketplace["plugins"] if not (isinstance(p, dict) and p.get("name") == BRIDGE_PRO_PLUGIN_NAME)]
            _write_json(marketplace_path, marketplace)
        # Same symlink discipline as install: never traverse a symlinked plugin dir (or component) when deleting.
        if plugin_dir.exists() or plugin_dir.is_symlink():
            _reject_symlink_components(plugin_dir / ".codex-plugin")
        for name in (".mcp.json", ".codex-plugin/plugin.json"):
            target = plugin_dir / name
            if target.is_symlink():
                raise ValueError(f"refusing to remove symlink {target}")
            target.unlink(missing_ok=True)
        for directory in (plugin_dir / ".codex-plugin", plugin_dir):
            try:
                directory.rmdir()
            except OSError:
                pass   # non-empty: user files stay
        return {"ok": True, "hosts": {t: {"status": "missing"} for t in targets}}

    # verify
    try:
        command = _bundle_command(bundle_root)
    except ValueError:
        command = None
    marketplace = _load_marketplace(marketplace_path) if marketplace_path.exists() else {"plugins": []}
    state, ours = _entry_state(marketplace, plugin_dir, command)
    result: dict[str, Any] = {"status": state}
    if command is None and ours is not None:
        result["reason"] = "bundle-unresolved"   # BRIDGE_PRO_BUNDLE_ROOT missing/invalid: cannot confirm the manifest points at this bundle
    if state == "installed":
        result["version"] = VERSION
        result["path"] = str(command) if command else None
    return {"ok": state in ("installed", "not_applicable"), "hosts": {t: dict(result) for t in targets}}
