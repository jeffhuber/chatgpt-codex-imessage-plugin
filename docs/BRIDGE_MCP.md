# Bridge MCP Contract

**Source of Truth:** This file in `chatgpt-codex-imessage-plugin` is the canonical specification for bridge-mcp and its MCP contract. Any copy in `jeffhuber/bridge-pro` is a mirror only.

---

## Overview

`bridge-mcp` is the MCP server for Bridge Pro's iMessage integration. It provides stdio JSON-RPC MCP tools to Claude Desktop, Grok, ChatGPT, and OpenAI Codex, exposing the local iMessage helper via the file-based protocol documented in `docs/PROTOCOL.md`.

This document specifies the contract between Bridge Pro (the macOS `.app` bundle) and MCP hosts. It covers:

- CLI interface and transport selection
- Stdlib-only implementation requirements
- Byte compatibility with the current `plugin_server/server.py` implementation
- Launcher security model
- `host-assets` command for ChatGPT/Codex plugin manifest installation and Grok MCP registration
- Environment and argument sanitization (security sign-off target)
- Backward-compatible change classification

---

## CLI Contract

```bash
bridge-mcp --product <claude|grok|openai> [--transport launchd|direct|socket]
bridge-mcp host-assets {detect|install|verify|remove} [--host <id>|--all] [--refresh] --json
# chatgpt and codex share ONE asset (personal marketplace entry + plugin dir): `remove` removes it for both
# and reports both hosts as missing; `install --host codex` additionally runs `codex plugin add`.
# grok uses `grok mcp add` as the only green install path; the skill-dir manifest fallback is reported as partial.
bridge-mcp --bridge-root <path>        # DIY-only, mutually exclusive with --product
```

### Arguments

- **`--product <claude|grok|openai>`**: Select the MCP host product. This determines bridge-root discovery, asset installation paths, and bundle-specific behaviors. Mutually exclusive with `--bridge-root`.

- **`--transport <launchd|direct|socket>`**: Select the transport mechanism for communicating with the helper. Default: `launchd` (the file-based write-and-poll protocol). `direct` and `socket` transports are reserved for the S2 spike; see Transport Constraints below. `manager` is refused in serve mode.

- **`--bridge-root <path>`**: DIY mode only. Explicitly specify the bridge runtime folder. Bypasses product-specific discovery and hardened bundle restrictions. Mutually exclusive with `--product`. This mode is for development and custom installations only; it is not used by Bridge Pro product modes.

- **`host-assets <subcommand>`**: Manage MCP host plugin manifests. Subcommands:
  - `detect`: Check which hosts have bridge-mcp plugin manifests installed.
  - `install`: Write or update the plugin manifest for the specified host(s).
  - `verify`: Check that installed manifests are current and valid.
  - `remove`: Delete the plugin manifest for the specified host(s).
  - Flags: `--host <id>` (target a specific host), `--all` (target all supported hosts), `--refresh` (force reinstall even if current), `--json` (emit JSON output for programmatic use).

---

## Core Requirements

### Stdlib-Only Implementation

**Decision closed: Do not vendor `mcp`.**

The MCP server must use **only Python standard library** for JSON-RPC MCP protocol handling (stdio, `json`, `sys`, `io`, `pathlib`, etc.). The `mcp` package is a 31-package dependency closure (~50 MB) with per-architecture native wheels that would bloat the Bridge Pro bundle and complicate code signing.

Vendoring `mcp` is documented as the **non-default fallback** for users who choose to install dependencies themselves (DIY mode). Product modes (`--product claude|grok|openai`) must not rely on any non-stdlib packages.

**Allowed modules:**
- Python 3.10+ standard library (no third-party packages)
- The bridge client, today `plugin_server/bridge.py`, extracted to `bridge_mcp/client.py` by MCP-2; product mode imports only from `bridge_mcp/`

**Rationale:**
- Minimal binary size for the signed `.app` bundle
- No native wheel architecture dependencies
- Reduced attack surface
- Simplified signing and notarization

---

### Byte Compatibility

`bridge-mcp` must be **byte-compatible** with the current `plugin_server/server.py` MCP server. Clients (AI hosts) must observe identical behavior for all tools.

#### Compatibility Requirements

The following must remain unchanged in bridge-mcp:

1. **Tool names:**
   - `imessage_status`
   - `review_imessages`
   - `search_imessages`
   - `get_imessage_history`
   - `get_imessage_response_stats`
   - `lookup_imessage_contacts`
   - `preview_imessage`
   - `send_imessage`

2. **Tool titles and descriptions:** Must match `plugin_server/server.py` exactly. These are shown to users and may be embedded in MCP host UI.

3. **Tool parameter names, types, and defaults:**
   - `review_imessages(days: int = 1)`
   - `search_imessages(term: str, days: int = 30, limit: int = 100)`
   - `get_imessage_history(chat: str, days: int = 14, limit: int = 100)`
   - `get_imessage_response_stats(chat: str, hours: int = 24)`
   - `lookup_imessage_contacts(name: str)`
   - `preview_imessage(to: str, text: str, service: Literal["iMessage", "SMS"] = "iMessage")`
   - `send_imessage(to: str, text: str, send_nonce: str, service: Literal["iMessage", "SMS"] = "iMessage")`

4. **ToolAnnotations:** Must match current hint values (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) as defined in `server.py`.

5. **Timeouts and response limits:**
   - Default timeout: 20 seconds (`BridgeClient.request(timeout_seconds=20.0)`)
   - Send timeout: 80 seconds (`send_imessage` only, with `delivery_may_be_unknown=True`)
   - Maximum response size: 16 MiB (`MAX_RESPONSE_BYTES = 16 * 1024 * 1024`)

6. **Protocol major version:** MCP server must reject helper protocol major version mismatches. Currently requires protocol major version `1` (accepts `1.x`).

7. **Server metadata:**
   - `name`: `"local-imessage"`
   - `title`: `"Local iMessage"`
   - `description`: `"Use Messages on this Mac through an isolated local helper."`
   - `instructions`: Current instructions text from `server.py` (preview-then-send workflow, explicit approval, no automatic retries)

8. **Bridge action mapping:** MCP tools must invoke the exact bridge actions documented in `docs/PROTOCOL.md`:
   - `imessage_status` → `status`
   - `review_imessages` → `review`
   - `search_imessages` → `search`
   - `get_imessage_history` → `chat_history`
   - `get_imessage_response_stats` → `response_stats`
   - `lookup_imessage_contacts` → `contacts_lookup`
   - `preview_imessage` → `send_preview`
   - `send_imessage` → `send`

#### Class A Changes (Safe Without User Notification)

The following changes are **backward-compatible** and do not break existing MCP host integrations:

- Internal refactoring (e.g., stdlib-only JSON-RPC implementation)
- Bridge-root discovery logic (product-specific paths, environment variable fallback)
- Launcher hardening (path validation, environment sanitization)
- Error message wording improvements (as long as error conditions remain the same)
- Logging and diagnostics
- Performance optimizations that do not change observable behavior
- Adding **new optional parameters** with defaults to existing tools
- Adding **new tools** (MCP hosts ignore unknown tools)

#### Changes Requiring Restart or Confirmation

The following changes require user notification and/or MCP host restart:

- Changing tool names, titles, or descriptions
- Changing parameter names or types
- Removing or renaming tools
- Changing required parameters to optional or vice versa
- Changing default parameter values
- Breaking protocol version compatibility
- Changing timeout or response size limits
- Changing transport behavior in non-backward-compatible ways

---

## Launcher: `Contents/MacOS/bridge-mcp`

The launcher is a compiled C executable that enforces the security boundary between the MCP host and the Bridge Pro bundle. It is the target of the `~/.agents/plugins/marketplace.json` command path.

This is macOS-only.

### Requirements

1. **Resolve own path:** Use `_NSGetExecutablePath` to get the absolute path of the running executable.

2. **Require `/Contents/MacOS/bridge-mcp`:** The executable path must end with `/Contents/MacOS/bridge-mcp`. Extract `<bundle-root>` from the resolved path.

3. **Refuse symlinked components:** Validate that no component of the launcher's resolved path is a symlink. This prevents PATH substitution attacks.

4. **Exec bundled Python:** Execute the Python interpreter shipped with the bundle:
   - Python binary: `<bundle>/Contents/Frameworks/Python.framework/<PYTHON_RELPATH>`
   - Flags: `-I` (isolated mode, no site packages), `-B` (no bytecode cache), `-X utf8` (UTF-8 mode)
   - Entry point: `<bundle>/Contents/Resources/mcp/bridge_mcp_main.py`
   - Pass through all arguments from the launcher invocation

5. **Fixed environment:** Replace the environment with only these variables:
   - `PATH`: `/usr/bin:/bin` (system-only, no user paths; nothing in bridge-mcp needs sbin)
   - `HOME`: Current user's home directory (required for bridge-root discovery)
   - `LANG`: `en_US.UTF-8` (predictable locale)
   - `BRIDGE_PRO_BUNDLE_ROOT`: Absolute path to `<bundle-root>`
   - **Drop everything else:** No `PYTHONPATH`, `DYLD_*`, `LD_*`, `TMPDIR`, `XDG_*`, or caller-controlled variables.

6. **No fallback:** If validation fails, exit with a non-zero code and a diagnostic message to stderr. Do not attempt to locate Python or the entry point elsewhere.

### Rationale

- **Symlink check:** Prevents an attacker from substituting a malicious bundle via PATH or symlink manipulation.
- **Fixed environment:** Prevents Python import hijacking (PYTHONPATH), library injection (DYLD_*/LD_*), and other environment-based attacks.
- **System-only PATH:** Prevents execution of user-installed binaries masquerading as system tools.
- **Bundle-relative discovery:** Ensures the launcher always uses the signed Python interpreter and entry point shipped with Bridge Pro.

---

## `host-assets` Command

The `host-assets` subcommand manages MCP plugin manifests for ChatGPT, Codex, and Grok. It is the successor to `tools/install_plugin_manifest.py` and the Bridge Pro-local Grok configurator.

### Behavior

**Subcommands:**

- `detect`: Scan host-specific MCP registrations for existing bridge-mcp manifests. Report which hosts have manifests installed and whether they are current.

- `install`: Write or update the plugin manifest for the specified host(s):
  - For `chatgpt` and `codex`:
    - Plugin name: `bridge-pro-imessage`
    - Destination: `~/plugins/bridge-pro-imessage/`
    - Manifest: Atomic 0600 write of `~/.agents/plugins/marketplace.json`, preserving other plugins
    - `.mcp.json` schema:
      ```json
      {
        "command": "<absolute-path-to-bundle>/Contents/MacOS/bridge-mcp",
        "args": ["--product", "openai"],
        "startup_timeout_sec": 15,
        "tool_timeout_sec": 90,
        "default_tools_approval_mode": "writes"
      }
      ```
    - After writing `.mcp.json`, run `codex plugin add <name>@personal` when the Codex CLI is available.
    - **Preservation:** Never modify or remove the DIY `chatgpt-codex-imessage-plugin` entry (the legacy plugin name from the open-source era). Only manage the `bridge-pro-imessage` entry.
  - For `grok`:
    - Primary path: run `grok mcp add bridge-pro-imessage --command <bundle>/Contents/MacOS/bridge-mcp --args --product grok`.
    - Green status is reported only when the Grok CLI registration succeeds and `verify` can match the registered command.
    - Fallback path: write `~/.grok/skills/bridge-pro-imessage/manifest.json` with the same command and `["--product", "grok"]` args.
    - Fallback status is **`partial`**, not `installed`. It records intent and lets the UI explain the missing step, but doctor/verify must not treat it as green until a real watched-folder bridge exists.

- `verify`: Check that installed manifests reference the current bundle and have correct command/args. Report mismatches (e.g., manifests pointing to old bundle versions or incorrect args).

- `remove`: Delete the `bridge-pro-imessage` manifest entry from `~/.agents/plugins/marketplace.json` and the `~/plugins/bridge-pro-imessage/` directory for ChatGPT/Codex, or run `grok mcp remove bridge-pro-imessage` and remove the skill-dir fallback for Grok. Preserve other plugins.

**Flags:**

- `--host <id>`: Target a specific host (e.g., `chatgpt`, `codex`, `grok`). Fails if the host is not supported.
- `--all`: Target all supported hosts. Equivalent to running the command for each host sequentially.
- `--refresh`: Force reinstall even if the manifest is already current. Useful after bundle upgrades.
- `--json`: Emit JSON output for programmatic use (e.g., Bridge Pro GUI). Format:
  ```json
  {
    "ok": true,
    "hosts": {
      "chatgpt": {"status": "installed", "version": "1.2.2", "path": "/path/to/bundle"},
      "codex": {"status": "missing"},
      "grok": {"status": "partial", "method": "skill_dir", "reason": "grok-mcp-add-required"}
    }
  }
  ```

### Path Restrictions

- **Manifest destination:** Must be `~/.agents/plugins/marketplace.json` (no other paths accepted).
- **Plugin directory:** Must be `~/plugins/<plugin-name>/` (no other paths accepted). MCP-5 will re-verify against `~/.codex/plugins` if that path becomes canonical.
- **Command path:** Must be an absolute path within the Bridge Pro bundle (`/Applications/Bridge Pro.app/Contents/MacOS/bridge-mcp` or similar).
- **No user paths in product mode:** The `--product openai` mode must not accept caller-controlled paths. Only `--bridge-root <path>` (DIY mode) allows custom paths.

### Permissions

- Manifest file: 0600 (user read-write only)
- Plugin directory: 0700 (user read-write-execute only)
- No group or world permissions on any created files or directories

---

## Environment and Argument Sanitization

**Security sign-off target:** This section documents the rules for accepting arguments and emitting environment variables in product modes (`--product claude|grok|openai`).

### Accepted Arguments (Product Mode)

In `--product` mode, the following arguments are **accepted**:

- `--product <claude|grok|openai>`: Required. Determines bridge-root and host-specific behavior.
- `--transport <launchd|direct|socket>`: Optional. Default: `launchd`. `direct` and `socket` are reserved for the S2 spike.

All other arguments are **rejected** with a clear error message (e.g., `"--bridge-root is mutually exclusive with --product"`).

### Accepted Arguments (DIY Mode)

In `--bridge-root <path>` mode, the following arguments are **accepted**:

- `--bridge-root <path>`: Required. Explicit bridge runtime folder.
- `--transport <launchd|direct|socket>`: Optional. Default: `launchd`.

All other arguments are **rejected** with a clear error message (e.g., `"--product is mutually exclusive with --bridge-root"`).

### Environment Variables Emitted

The launcher provides a **fixed environment** to the Python entry point:

- `PATH=/usr/bin:/bin`: System-only PATH (no user directories; nothing in bridge-mcp needs sbin).
- `HOME=<user-home>`: Current user's home directory (required for `~` expansion and bridge-root discovery).
- `LANG=en_US.UTF-8`: Predictable locale for text processing.
- `BRIDGE_PRO_BUNDLE_ROOT=<bundle-root>`: Absolute path to the Bridge Pro `.app` bundle.

**All other environment variables are dropped**, including:
- `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`: Prevent import hijacking.
- `DYLD_*`, `LD_*`: Prevent library injection.
- `TMPDIR`, `XDG_*`: Prevent directory substitution.
- Caller-supplied variables (e.g., from the MCP host environment).

### Environment Variables Read (Python)

The Python entry point may read:

- `BRIDGE_PRO_BUNDLE_ROOT`: Absolute path to the bundle (set by launcher).
- `HOME`: User home directory (set by launcher).
- `CHATGPT_CODEX_IMESSAGE_BRIDGE`: **DIY mode only.** When `--bridge-root` is specified, this environment variable provides a fallback bridge-root path if the argument value is relative or needs expansion. **Environment-only invocation (without `--bridge-root` argument) is INVALID.** The env var is not a mode selector; DIY mode requires the `--bridge-root` argument. **Not used in product mode.**

### Security Invariants

1. **No caller paths in product mode:** In `--product` mode, the bridge-root is discovered via bundle-relative heuristics or user-specific defaults. Caller-supplied paths (e.g., from MCP host environment variables) are never used.

2. **DIY mode isolation:** `--bridge-root <path>` mode bypasses bundle restrictions and is intended for development/testing only. It is **mutually exclusive** with `--product` and must not be usable from product MCP host configurations.

3. **Launcher environment reset:** The launcher drops all caller-supplied environment variables before executing Python. This prevents MCP hosts from injecting paths, libraries, or configuration.

---

## Transport Constraints

### Supported Transports

- **`launchd`** (default): The file-based write-and-poll protocol documented in `docs/PROTOCOL.md`. This is the **only supported transport** until the S2 spike.

The `--transport launchd` flag is accepted but is the default and does not need to be specified.

### Reserved Transports (S2 Spike)

- **`direct`**: Direct Python subprocess invocation. Reserved for S2 spike. S2 arms 1/2 (docs/spikes/s2-arms-1-3.md in bridge-pro) found that a host-exec'd wrapper is TCC-attributed to the host, so `direct` is on track to be refused.
- **`socket`**: Unix domain socket IPC. Reserved for S2 spike (arm 4 still open).

The `--transport direct` and `--transport socket` flags are **accepted for forward compatibility** but will fail at runtime with a clear error message: `"direct/socket transports are reserved for the S2 spike; use launchd (default) for now"`.

---

## License

This specification is part of the `chatgpt-codex-imessage-plugin` project, licensed under MIT.
