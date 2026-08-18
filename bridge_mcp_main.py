#!/usr/bin/env python3
"""Entry point for bridge-mcp: stdio JSON-RPC MCP server, plus `host-assets`
manifest management (docs/BRIDGE_MCP.md). Stdlib only."""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "host-assets":
        parser = argparse.ArgumentParser(prog="bridge-mcp host-assets")
        parser.add_argument("subcommand", choices=["detect", "install", "verify", "remove"])
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--host")
        group.add_argument("--all", action="store_true")
        parser.add_argument("--refresh", action="store_true")
        parser.add_argument("--codex-path")
        parser.add_argument("--grok-path")
        parser.add_argument("--json", action="store_true", dest="as_json")
        args = parser.parse_args(argv[1:])
        from bridge_mcp.host_assets import host_assets
        try:
            payload = host_assets(args.subcommand, host=args.host, all_hosts=args.all, refresh=args.refresh,
                                  codex_path=args.codex_path, grok_path=args.grok_path)
        except (ValueError, OSError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}) if args.as_json else f"host-assets: {exc}", file=sys.stderr if not args.as_json else sys.stdout)
            return 1
        print(json.dumps(payload) if args.as_json else json.dumps(payload, indent=2))
        return 0 if payload.get("ok") else 1

    parser = argparse.ArgumentParser(prog="bridge-mcp")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--product", choices=["claude", "grok", "openai"])
    group.add_argument("--bridge-root")
    # Documented contract: launchd | direct | socket. Only launchd is implemented today; the others are accepted
    # (so launchers built against the contract keep working) and rejected only when actually selected.
    parser.add_argument("--transport", choices=["launchd", "direct", "socket"], default="launchd")   # socket client is MCP-13
    args = parser.parse_args(argv)
    if args.transport != "launchd":
        print(f"bridge-mcp: transport '{args.transport}' is not implemented yet (MCP-13); use --transport launchd", file=sys.stderr)
        return 2
    from bridge_mcp.server import run_server
    run_server(product=args.product, bridge_root=args.bridge_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
