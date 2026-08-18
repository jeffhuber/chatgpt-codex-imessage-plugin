"""`bridge-mcp host-assets` (MCP-5/MCP-10): manage Bridge Pro MCP host assets for
ChatGPT/Codex and Grok (docs/BRIDGE_MCP.md "host-assets Command"; successor to
tools/install_plugin_manifest.py and the product-local Grok configurator).

Stdlib only. Manages ONLY the `bridge-pro-imessage` entry; the DIY
`chatgpt-codex-imessage-plugin` entry is never touched. Paths are fixed:
OpenAI hosts use manifest `~/.agents/plugins/marketplace.json`, plugin dir
`~/plugins/bridge-pro-imessage/`; Grok uses `grok mcp add` when available, with a
truthful manifest-only `partial` fallback under `~/.grok/skills/`. The MCP command is
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

SUPPORTED_HOSTS = ("chatgpt", "codex", "grok")   # chatgpt/codex share the personal marketplace
VERSION = "1.3.0"
MCP_RELPATH = "Contents/MacOS/bridge-mcp"
OPENAI_HOSTS = ("chatgpt", "codex")
GROK_ARGS = ["--product", "grok"]


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
        st = command.lstat()
    except FileNotFoundError:
        raise ValueError(f"bridge-mcp launcher missing at {command}") from None
    if not stat.S_ISREG(st.st_mode):
        raise ValueError(f"bridge-mcp launcher is not a regular file: {command}")
    if not (st.st_mode & 0o111) or not os.access(command, os.X_OK):
        raise ValueError(f"bridge-mcp launcher is not executable: {command}")   # the host could never launch it
    return command


EXPECTED_SOURCE_PATH = f"./plugins/{BRIDGE_PRO_PLUGIN_NAME}"


def _paths(home: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    return home / ".agents" / "plugins" / "marketplace.json", home / "plugins" / BRIDGE_PRO_PLUGIN_NAME


def _load_marketplace(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
    _reject_symlink_components(path)
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError("existing marketplace must be a current-user-owned regular file")
    if metadata.st_mode & 0o077:
        os.chmod(path, 0o600)
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or not isinstance(parsed.get("plugins"), list):
        raise ValueError("existing marketplace must be an object with a plugins array")
    if parsed.get("name") != "personal":
        # Activation targets bridge-pro-imessage@personal; writing into any other marketplace would "succeed" and never activate.
        raise ValueError("existing marketplace must be the Codex 'personal' marketplace")
    # A minimal existing manifest may lack the interface block Codex uses to display the marketplace; fill the default.
    if not isinstance(parsed.get("interface"), dict):
        parsed["interface"] = {"displayName": "Personal"}
    return parsed


def _ensure_private_dir(path: pathlib.Path) -> None:
    """mkdir -p, creating every missing component 0700 (independent of umask), and strip group/world bits from
    pre-existing components we own within the managed subtree (<home>/.agents/plugins/… or <home>/plugins/…)."""
    _reject_symlink_components(path)
    missing: list[pathlib.Path] = []
    current = path
    while not current.exists() and current != current.parent:
        missing.append(current); current = current.parent
    for directory in reversed(missing):            # top-down: each new component is chmod'ed right after creation
        directory.mkdir(mode=0o700)
        os.chmod(directory, 0o700)
    current = path
    for _ in range(4):   # <home>/plugins/<name>[/.codex-plugin] or <home>/.agents/plugins
        st = current.lstat()
        if stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and (st.st_mode & 0o077):
            os.chmod(current, 0o700)
        if current.name in ("plugins", ".agents") or current == current.parent:
            if current.name == "plugins" and current.parent.name == ".agents":
                current = current.parent; continue   # also tighten a freshly created ~/.agents
            break
        current = current.parent


def _write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    _reject_symlink_components(path)
    _ensure_private_dir(path.parent)
    try:
        existing = path.lstat()
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(existing.st_mode) or existing.st_uid != os.getuid():
            raise ValueError(f"refusing to replace unsafe managed file: {path}")
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


def _managed_json_file_is_safe(path: pathlib.Path) -> bool:
    try:
        _reject_symlink_components(path)
        st = path.lstat()
    except (FileNotFoundError, ValueError):
        return False
    return stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and not (st.st_mode & 0o077)


def _validate_managed_file_removal(path: pathlib.Path) -> None:
    _reject_symlink_components(path)
    try:
        st = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        raise ValueError(f"refusing to remove unsafe managed file: {path}")


def _command_has_bridge_app_shape(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    path = pathlib.PurePosixPath(value)
    return (
        path.is_absolute()
        and ".." not in path.parts
        and path.name == "bridge-mcp"
        and path.parent.name == "MacOS"
        and path.parent.parent.name == "Contents"
        and path.parent.parent.parent.suffix == ".app"
    )


def _entry_state(marketplace: dict[str, Any], plugin_dir: pathlib.Path, command: pathlib.Path | None,
                 *, command_required: bool = True) -> tuple[str, dict[str, Any] | None]:
    """Shared by verify (command_required) and detect (structural check; command compared only when resolvable)."""
    ours = next((p for p in marketplace["plugins"] if isinstance(p, dict) and p.get("name") == BRIDGE_PRO_PLUGIN_NAME), None)
    diy = next((p for p in marketplace["plugins"] if isinstance(p, dict) and p.get("name") == DIY_PLUGIN_NAME), None)
    if ours is None:
        return ("diy_only" if diy else "missing"), ours
    # The entry must point at the fixed local plugin dir; otherwise the host loads nothing even if our files exist.
    source = ours.get("source")
    if not isinstance(source, dict) or source.get("source") != "local" or source.get("path") != EXPECTED_SOURCE_PATH:
        return "mismatch", ours
    mcp_path = plugin_dir / ".mcp.json"
    if not _managed_json_file_is_safe(mcp_path):
        return "mismatch", ours
    try:
        servers = json.loads(mcp_path.read_text(encoding="utf-8"))
        configured = servers["mcpServers"]["bridge-pro-imessage"] if isinstance(servers, dict) else None
        if not isinstance(configured, dict):
            return "mismatch", ours
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return "mismatch", ours
    plugin_meta_path = plugin_dir / ".codex-plugin" / "plugin.json"
    if not _managed_json_file_is_safe(plugin_meta_path):
        return "mismatch", ours
    try:
        plugin_meta = json.loads(plugin_meta_path.read_text(encoding="utf-8"))
        plugin_meta_current = (
            isinstance(plugin_meta, dict)
            and plugin_meta.get("name") == BRIDGE_PRO_PLUGIN_NAME
            and plugin_meta.get("mcpServers") == "./.mcp.json"
            and plugin_meta.get("version") == VERSION
        )
    except (OSError, json.JSONDecodeError):
        plugin_meta_current = False
    # No resolvable current bundle ⇒ nothing can be "current"; verify reports it rather than skipping the comparison.
    if command is not None:
        command_ok = configured.get("command") == str(command)
    else:
        command_ok = not command_required and _command_has_bridge_app_shape(configured.get("command"))
    current = command_ok and configured.get("args") == ["--product", "openai"] and plugin_meta_current
    return ("installed" if current else "mismatch"), ours


# Where the Codex CLI normally lives. The bundled launcher sanitizes PATH to /usr/bin:/bin, so PATH lookup alone
# misses npm/Homebrew installs; the app may also pass an explicit --codex-path it trusts.
KNOWN_CODEX_LOCATIONS = (
    "/Applications/Codex.app/Contents/Resources/codex",
    "/opt/homebrew/bin/codex",
    "/usr/local/bin/codex",
    "~/.local/bin/codex",
    "~/.npm-global/bin/codex",
    "~/.codex/bin/codex",
)


KNOWN_GROK_LOCATIONS = (
    "/opt/homebrew/bin/grok",
    "/usr/local/bin/grok",
    "~/.local/bin/grok",
)


def _trusted_executable(cand: str | os.PathLike[str] | None) -> str | None:
    if not cand:
        return None
    path = os.fspath(cand)
    try:
        st = os.stat(path)
    except OSError:
        return None
    if stat.S_ISREG(st.st_mode) and st.st_uid in (0, os.getuid()) and not (st.st_mode & 0o022) and os.access(path, os.X_OK):
        return path
    return None


def _resolve_codex(codex_path: str | None) -> str | None:
    candidates = [codex_path] if codex_path else [shutil.which("codex"), *(os.path.expanduser(c) for c in KNOWN_CODEX_LOCATIONS)]
    for cand in candidates:
        resolved = _trusted_executable(cand)
        if resolved:
            return resolved
    return None


def _resolve_grok(grok_path: str | None, home: pathlib.Path) -> str | None:
    # CLI discovery follows the current process PATH/HOME like `_resolve_codex`;
    # the injected `home` is for managed asset paths, not alternate binary lookup.
    candidates = [grok_path] if grok_path else [
        shutil.which("grok"),
        *(os.path.expanduser(c) for c in KNOWN_GROK_LOCATIONS),
    ]
    for cand in candidates:
        resolved = _trusted_executable(cand)
        if resolved:
            return resolved
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
    if result.returncode == 0:
        return "activated"
    combined_output = f"{result.stdout}\n{result.stderr}".lower()
    if BRIDGE_PRO_PLUGIN_NAME in combined_output and ("already" in combined_output or "exist" in combined_output):
        return "already-activated"
    return f"failed:{result.returncode}"


def _grok_skill_paths(home: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    skill_root = home / ".grok" / "skills"
    skill_dir = skill_root / BRIDGE_PRO_PLUGIN_NAME
    return skill_root, skill_dir, skill_dir / "manifest.json"


def _ensure_grok_skill_dir(home: pathlib.Path) -> pathlib.Path:
    grok_dir = home / ".grok"
    skill_root = grok_dir / "skills"
    skill_dir = skill_root / BRIDGE_PRO_PLUGIN_NAME
    for directory in (grok_dir, skill_root, skill_dir):
        _reject_symlink_components(directory)
        try:
            st = directory.lstat()
        except FileNotFoundError:
            directory.mkdir(mode=0o700)
            os.chmod(directory, 0o700)
            continue
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            raise ValueError(f"refusing unsafe Grok skill directory: {directory}")
        if st.st_mode & 0o077:
            os.chmod(directory, 0o700)
    return skill_dir


def _write_json_existing_private_parent(path: pathlib.Path, payload: dict[str, Any]) -> None:
    _reject_symlink_components(path)
    try:
        parent_st = path.parent.lstat()
    except FileNotFoundError:
        raise ValueError(f"managed parent directory does not exist: {path.parent}") from None
    if not stat.S_ISDIR(parent_st.st_mode) or parent_st.st_uid != os.getuid() or (parent_st.st_mode & 0o077):
        raise ValueError(f"managed parent directory is not private: {path.parent}")
    try:
        existing = path.lstat()
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(existing.st_mode) or existing.st_uid != os.getuid():
            raise ValueError(f"refusing to replace unsafe managed file: {path}")
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


def _is_mcp_registered(mcp_list_output: str, server_name: str) -> bool:
    """Match Grok MCP server names exactly; similar names must not count."""
    for line in mcp_list_output.splitlines():
        tokens = line.strip().split()
        if tokens and tokens[0] == server_name:
            return True
    return False


def _grok_registered(grok_exe: str) -> bool | None:
    try:
        result = subprocess.run([grok_exe, "mcp", "list"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return _is_mcp_registered(result.stdout, BRIDGE_PRO_PLUGIN_NAME)


def _grok_show_matches(grok_exe: str, command: pathlib.Path) -> bool | None:
    try:
        result = subprocess.run([grok_exe, "mcp", "show", BRIDGE_PRO_PLUGIN_NAME], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = f"{result.stdout}\n{result.stderr}"
    return str(command) in output and "--product" in output and "grok" in output


def _grok_fallback_state(home: pathlib.Path, command: pathlib.Path | None,
                         *, command_required: bool = True) -> tuple[str, dict[str, Any] | None]:
    _, skill_dir, manifest_path = _grok_skill_paths(home)
    try:
        _reject_symlink_components(skill_dir)
    except ValueError:
        return "mismatch", None
    if not skill_dir.exists():
        return "missing", None
    if not manifest_path.exists():
        return "missing", None
    if not _managed_json_file_is_safe(manifest_path):
        return "mismatch", None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "mismatch", None
    if not isinstance(manifest, dict):
        return "mismatch", manifest
    if manifest.get("name") != BRIDGE_PRO_PLUGIN_NAME or manifest.get("args") != GROK_ARGS:
        return "mismatch", manifest
    if command is not None:
        command_ok = manifest.get("command") == str(command)
    else:
        command_ok = not command_required and _command_has_bridge_app_shape(manifest.get("command"))
    if manifest.get("transport") != "watched_folder" or not command_ok:
        return "mismatch", manifest
    return "partial", manifest


def _write_grok_fallback(home: pathlib.Path, command: pathlib.Path) -> None:
    _, _, manifest_path = _grok_skill_paths(home)
    _ensure_grok_skill_dir(home)
    _write_json_existing_private_parent(manifest_path, {
        "name": BRIDGE_PRO_PLUGIN_NAME,
        "version": VERSION,
        "command": str(command),
        "args": GROK_ARGS,
        "transport": "watched_folder",
    })


def _remove_grok_fallback(home: pathlib.Path) -> None:
    _, skill_dir, manifest_path = _grok_skill_paths(home)
    try:
        _reject_symlink_components(skill_dir)
    except ValueError:
        raise ValueError(f"refusing to remove unsafe Grok skill path: {skill_dir}") from None
    _validate_managed_file_removal(manifest_path)
    manifest_path.unlink(missing_ok=True)
    try:
        skill_dir.rmdir()
    except OSError:
        pass


def _grok_detect(home: pathlib.Path, *, grok_path: str | None = None) -> dict[str, Any]:
    grok_exe = _resolve_grok(grok_path, home)
    _, skill_dir, _ = _grok_skill_paths(home)
    markers: dict[str, Any] = {
        "grok_cli": grok_exe is not None,
        "grok_cli_path": grok_exe,
        "skill_dir": skill_dir.exists(),
    }
    if grok_exe:
        registered = _grok_registered(grok_exe)
        markers["mcp_registered"] = registered is True
        if registered is True:
            return {"status": "installed", "method": "mcp_cli", "version": VERSION, "present": True, "markers": markers}
    fallback_state, _ = _grok_fallback_state(home, None, command_required=False)
    markers["skill_installed"] = fallback_state == "partial"
    if fallback_state == "partial":
        return {"status": "partial", "method": "skill_dir", "reason": "grok-mcp-add-required", "present": True, "markers": markers}
    if fallback_state == "mismatch":
        return {"status": "mismatch", "method": "skill_dir", "present": True, "markers": markers}
    status = "missing" if grok_exe or skill_dir.exists() else "not_applicable"
    return {"status": status, "present": grok_exe is not None or skill_dir.exists(), "markers": markers}


def _grok_install(home: pathlib.Path, command: pathlib.Path, *, grok_path: str | None = None) -> dict[str, Any]:
    grok_exe = _resolve_grok(grok_path, home)
    if grok_exe:
        try:
            result = subprocess.run([
                grok_exe, "mcp", "add", BRIDGE_PRO_PLUGIN_NAME,
                "--command", str(command), "--args", *GROK_ARGS,
            ], capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = None
            cli_error = f"grok mcp add failed: {type(exc).__name__}"
        else:
            cli_error = f"grok mcp add failed:{result.returncode}" if result.returncode != 0 else None
        if result is not None and result.returncode == 0:
            try:
                _remove_grok_fallback(home)
            except ValueError as exc:
                return {"status": "mismatch", "method": "mcp_cli", "reason": f"fallback-cleanup-failed: {exc}"}
            return {"status": "installed", "method": "mcp_cli", "version": VERSION, "path": str(command)}
    else:
        cli_error = "grok-cli-not-found"
    _write_grok_fallback(home, command)
    return {
        "status": "partial",
        "method": "skill_dir",
        "version": VERSION,
        "path": str(command),
        "reason": cli_error,
        "message": "wrote Grok skill manifest, but Grok is not registered until `grok mcp add` succeeds",
    }


def _grok_verify(home: pathlib.Path, command: pathlib.Path | None, *, grok_path: str | None = None) -> dict[str, Any]:
    grok_exe = _resolve_grok(grok_path, home)
    if grok_exe:
        registered = _grok_registered(grok_exe)
        if registered is True and command is None:
            return {"status": "mismatch", "method": "mcp_cli", "reason": "bundle-unresolved"}
        if registered is True and command is not None:
            show_matches = _grok_show_matches(grok_exe, command)
            if show_matches is True:
                return {"status": "installed", "method": "mcp_cli", "version": VERSION, "path": str(command)}
            return {"status": "mismatch", "method": "mcp_cli", "reason": "grok-mcp-show-mismatch"}
    fallback_state, _ = _grok_fallback_state(home, command, command_required=command is not None)
    if fallback_state == "partial":
        result: dict[str, Any] = {"status": "partial", "method": "skill_dir", "reason": "grok-mcp-add-required"}
        if command is not None:
            result["path"] = str(command)
        return result
    if fallback_state == "mismatch":
        return {"status": "mismatch", "method": "skill_dir"}
    return {"status": "missing" if grok_exe else "not_applicable"}


def _grok_remove(home: pathlib.Path, *, grok_path: str | None = None) -> dict[str, Any]:
    grok_exe = _resolve_grok(grok_path, home)
    if grok_exe:
        try:
            result = subprocess.run([grok_exe, "mcp", "remove", BRIDGE_PRO_PLUGIN_NAME], capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = None
            remove_error = f"grok mcp remove failed: {type(exc).__name__}"
        else:
            remove_error = f"grok mcp remove failed:{result.returncode}" if result.returncode != 0 else None
        if remove_error:
            registered = _grok_registered(grok_exe)
            if registered is True or registered is None:
                return {"status": "installed", "method": "mcp_cli", "error": remove_error}
    try:
        _remove_grok_fallback(home)
    except ValueError as exc:
        return {"status": "installed", "method": "skill_dir", "error": str(exc)}
    return {"status": "missing"}


def host_assets(subcommand: str, *, host: str | None = None, all_hosts: bool = False, refresh: bool = False,
                home: pathlib.Path | None = None, bundle_root: str | None = None, codex_path: str | None = None,
                grok_path: str | None = None) -> dict[str, Any]:
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
    openai_targets = [t for t in targets if t in OPENAI_HOSTS]
    grok_targets = [t for t in targets if t == "grok"]

    if subcommand == "detect":
        hosts: dict[str, Any] = {}
        if openai_targets:
            detected = detect_hosts(home)["openai"]
            hosts.update({t: {"status": detected["asset_status"], "markers": detected["markers"]} for t in openai_targets})
        for t in grok_targets:
            hosts[t] = _grok_detect(home, grok_path=grok_path)
        return {"ok": True, "hosts": hosts}

    command: pathlib.Path | None = None
    if subcommand == "install":
        command = _bundle_command(bundle_root)
        hosts: dict[str, Any] = {}
        if openai_targets:
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
        for t in openai_targets:
            info: dict[str, Any] = {"status": "installed", "version": VERSION, "path": str(command)}
            if t == "codex":
                activation = _codex_plugin_add(codex_path)
                info["codex_activation"] = activation
                if activation not in ("activated", "already-activated"):
                    info["status"] = "mismatch"
                    info["reason"] = activation
            hosts[t] = info
        for t in grok_targets:
            hosts[t] = _grok_install(home, command, grok_path=grok_path)
        return {"ok": all(info["status"] == "installed" for info in hosts.values()), "hosts": hosts}

    if subcommand == "remove":
        hosts: dict[str, Any] = {}
        if openai_targets:
            # Validate every removal target FIRST (same symlink discipline as install); only then mutate anything, so a
            # refused removal leaves both the marketplace entry and the plugin files exactly as they were.
            targets_to_unlink = [plugin_dir / name for name in (".mcp.json", ".codex-plugin/plugin.json")]
            if plugin_dir.exists() or plugin_dir.is_symlink():
                _reject_symlink_components(plugin_dir / ".codex-plugin")
            for target in targets_to_unlink:
                _validate_managed_file_removal(target)
            marketplace = _load_marketplace(marketplace_path) if marketplace_path.exists() else None
            if marketplace is not None:
                marketplace["plugins"] = [p for p in marketplace["plugins"] if not (isinstance(p, dict) and p.get("name") == BRIDGE_PRO_PLUGIN_NAME)]
                _write_json(marketplace_path, marketplace)
            for target in targets_to_unlink:
                target.unlink(missing_ok=True)
            for directory in (plugin_dir / ".codex-plugin", plugin_dir):
                try:
                    directory.rmdir()
                except OSError:
                    pass   # non-empty: user files stay
            # The marketplace entry + plugin dir are ONE shared asset for ChatGPT and Codex: removing it removes it for
            # both, so the report says so explicitly rather than pretending the other host is untouched.
            hosts.update({t: {"status": "missing"} for t in OPENAI_HOSTS})
        for t in grok_targets:
            hosts[t] = _grok_remove(home, grok_path=grok_path)
        payload: dict[str, Any] = {"ok": all(info["status"] == "missing" for info in hosts.values()), "hosts": hosts}
        if openai_targets:
            payload["shared_asset"] = True
        return payload

    # verify
    try:
        command = _bundle_command(bundle_root)
    except ValueError:
        command = None
    hosts: dict[str, Any] = {}
    if openai_targets:
        marketplace = _load_marketplace(marketplace_path) if marketplace_path.exists() else {"plugins": []}
        state, ours = _entry_state(marketplace, plugin_dir, command)
        result: dict[str, Any] = {"status": state}
        if command is None and ours is not None:
            result["reason"] = "bundle-unresolved"   # BRIDGE_PRO_BUNDLE_ROOT missing/invalid: cannot confirm the manifest points at this bundle
        if state == "installed":
            result["version"] = VERSION
            result["path"] = str(command) if command else None
        for t in openai_targets:
            host_result = dict(result)
            if t == "codex" and host_result["status"] == "installed":
                activation = _codex_plugin_add(codex_path)
                host_result["codex_activation"] = activation
                if activation not in ("activated", "already-activated"):
                    host_result["status"] = "mismatch"
                    host_result["reason"] = activation
            hosts[t] = host_result
    for t in grok_targets:
        hosts[t] = _grok_verify(home, command, grok_path=grok_path)
    return {"ok": all(info["status"] in ("installed", "not_applicable") for info in hosts.values()), "hosts": hosts}
