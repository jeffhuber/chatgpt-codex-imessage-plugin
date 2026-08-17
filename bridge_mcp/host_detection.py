"""Host detection for Claude, ChatGPT/Codex, Grok MCP hosts.

Markers: Claude.app/config, ChatGPT.app/marketplace.json, grok binary.
Bridge Pro plugin: 'bridge-pro-imessage'. DIY: 'chatgpt-codex-imessage-plugin'.
"""
from __future__ import annotations
import json
import os
import pathlib
import shutil
from typing import Any

BRIDGE_PRO_PLUGIN_NAME = "bridge-pro-imessage"
DIY_PLUGIN_NAME = "chatgpt-codex-imessage-plugin"

def _detect_claude_desktop(home: pathlib.Path) -> dict[str, Any]:
    markers = {
        "claude_app": pathlib.Path("/Applications/Claude.app").is_dir(),
        "macos_config": (home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json").is_file(),
        "linux_config": (home / ".config" / "claude_desktop_config.json").is_file(),
    }
    cursor_plugins = home / ".cursor" / "plugins"
    if cursor_plugins.is_dir():
        for plugin_dir in cursor_plugins.iterdir():
            if plugin_dir.is_dir() and (plugin_dir / "claude.plugin").exists():
                markers["channel_plugin"] = True
                break
    return {"present": any(markers.values()), "markers": markers, "asset_status": "not_applicable"}

def _detect_chatgpt_codex(home: pathlib.Path) -> dict[str, Any]:
    markers = {
        "chatgpt_app": pathlib.Path("/Applications/ChatGPT.app").is_dir(),
        "plugins_dir": (home / "plugins").is_dir(),
        "codex_plugins": (home / ".codex" / "plugins").is_dir(),
    }
    marketplace_path = home / ".agents" / "plugins" / "marketplace.json"
    markers["marketplace_json"] = marketplace_path.is_file()
    asset_status = "missing"
    bridge_pro_entry = None
    diy_entry = None
    if markers["marketplace_json"]:
        try:
            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
            for plugin in marketplace.get("plugins", []):
                if not isinstance(plugin, dict):
                    continue
                name = plugin.get("name")
                if name == BRIDGE_PRO_PLUGIN_NAME:
                    bridge_pro_entry = plugin
                elif name == DIY_PLUGIN_NAME:
                    diy_entry = plugin
        except (json.JSONDecodeError, OSError):
            pass
    if bridge_pro_entry:
        # The marketplace entry only points at the plugin dir; the command lives in its .mcp.json.
        source = bridge_pro_entry.get("source")
        command = source.get("command") if isinstance(source, dict) else bridge_pro_entry.get("command")
        if not command:
            try:
                servers = json.loads((home / "plugins" / BRIDGE_PRO_PLUGIN_NAME / ".mcp.json").read_text(encoding="utf-8")).get("mcpServers", {})
                command = next(iter(servers.values()), {}).get("command")
            except (OSError, json.JSONDecodeError, AttributeError):
                command = None
        asset_status = "installed" if command and "bridge-mcp" in str(command) else "mismatch"
    elif diy_entry:
        asset_status = "diy_only"
    return {"present": any(markers.values()), "markers": markers, "asset_status": asset_status, "bridge_pro_entry": bridge_pro_entry, "diy_entry": diy_entry}

def _detect_grok_cli(home: pathlib.Path, path_env: str | None = None) -> dict[str, Any]:
    grok = shutil.which("grok", path=path_env)
    grok_binary = pathlib.Path(grok) if grok else None
    return {"present": grok_binary is not None, "markers": {"grok_binary": grok_binary is not None, "grok_path": str(grok_binary) if grok_binary else None}, "asset_status": "not_applicable"}

def detect_hosts(home: pathlib.Path | str | None = None, path_env: str | None = None) -> dict[str, dict[str, Any]]:
    """Detect MCP hosts (Claude, ChatGPT/Codex, Grok) using filesystem markers."""
    home = pathlib.Path(home) if home else pathlib.Path.home()
    path_env = path_env if path_env is not None else os.environ.get("PATH")
    return {"claude": _detect_claude_desktop(home), "openai": _detect_chatgpt_codex(home), "grok": _detect_grok_cli(home, path_env)}

def doctor_check_6_json(home: pathlib.Path | str | None = None, path_env: str | None = None) -> dict[str, Any]:
    """Doctor check 6: host asset present and version-matches (Bridge Pro entry only)."""
    hosts = detect_hosts(home, path_env)
    ok = all(host.get("asset_status") != "mismatch" for host in hosts.values())
    return {"ok": ok, "check": 6, "hosts": hosts}
