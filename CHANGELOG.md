# Changelog

Releases use semantic versioning for the helper, MCP server, and plugin package.
The file-bridge protocol has its own major/minor compatibility version.

## Unreleased

## 1.3.0 - 2026-08-16

- Bridge protocol 1.2: add the `list_chats` action, which enumerates threads
  with recent activity for policy discovery and never selects message bodies
  (a sentinel-body fixture asserts this); add worker-enforced bridge roles
  (`IMESSAGE_BRIDGE_ROLE`, default `host`) — `list_chats` is served only on a
  `manager` bridge, body-returning and send actions only on a `host` bridge,
  and unknown roles serve nothing; `status` reports `bridge_role` and
  `allowed_actions`. DIY installs are unaffected: nothing sets the role, so
  every existing action behaves as before.
- Harden `list_chats` policy checks: apply the same ownership and mode checks
  as message-body reads; reject requests when `read_policy.txt` is missing.
- Root-owned files satisfy `require_uid_owner` policy entries regardless of the
  running process's uid.
- Defense-in-depth check in `_load_send_gate()` validates the loaded module path.
- Add an `env-plumbing` re-import test with `os.path.realpath()` validation.
- Stdlib JSON-RPC MCP server in `bridge_mcp/server.py` with eight typed tools
  and accurate read/local-write/external-write annotations.
- Product-specific MCP layout under `bridges/{claude,grok,openai}` folders to
  distinguish DIY `chatgpt-codex-imessage-plugin` from Bridge Pro
  `bridge-pro-imessage`.
- MCP conformance tests for all eight tools with schema validation, default
  parameters, and timeout handling.
- Python-level egress tests for helper, send_gate, and bridge_mcp modules with
  no network access required.
- Host detection heuristics and fixtures for distinguishing DIY installations
  from managed Bridge Pro deployments; add `doctor.py` check 6 JSON output.
- Product isolation tests verifying independent control queues and nonce stores
  across ChatGPT/Codex, Claude, and Grok helpers.
- Align ChatGPT helper feature parity with sibling Claude and Grok helpers
  (CORE-8).
- Per-bridge flock protection in `helper.py` main loop (CORE-6).
- Preserve case-insensitive bridge role environment variable handling.

## 1.2.2 - 2026-08-14

- Harden hardened-install Python selection by validating interpreter ownership
  and path permissions before executing a compatibility probe.
- Report shell-only `chat.db` access accurately in `doctor.py`; the wrapper's Full
  Disk Access remains verified by the smoke test.
- Pin setup-python by commit, prevent release checkout credential persistence,
  and add weekly Python dependency monitoring.
- Install from a non-git live folder (e.g. `~/imessage-bridge-chatgpt`)
  defaults the bridge to that same folder, matching the Grok/Claude pattern.
  Wrapper, control queue, contacts, and MCP venv stay together.
- `install-plugin.sh` writes a validated, non-executable `bridge-path` data
  file so the MCP launcher can find the correct bridge without hardcoded paths.
- `scripts/run-mcp-server.sh` reads from fail-closed
  `CHATGPT_CODEX_IMESSAGE_BRIDGE`, then `bridge-path`, then Application Support.
- Empty `CHATGPT_CODEX_IMESSAGE_BRIDGE` now fails closed in all installers and
  the MCP launcher.
- Installing from a git checkout warns when `~/imessage-bridge-chatgpt` exists
  with a live helper.
- Add a supported-interpreter test entrypoint and announcement-ready install,
  upgrade, privacy, release-integrity, and host-support documentation.
- Require a GitHub-verified signed tag and draft-first publication for immutable
  release assets.
- Keep installer-warning coverage independent of `.git` metadata so the test
  suite also passes from source release archives.

## 1.2.1 - 2026-08-13

- Select the FDA helper and user-level MCP Python runtimes independently,
  fail closed on invalid overrides, and require a protected root-owned helper
  interpreter in hardened mode.

## 1.2.0 - 2026-08-13

- Preserve an explicitly empty bridge environment variable so send-gate setup
  fails closed instead of silently selecting the default bridge.
- Clarify standard and hardened installation as an explicit threat-model choice.
- Add a deterministic shared-core manifest and CI check for security parity
  with the Claude Cowork and Grok Bot sibling repositories.

## 1.1.0 - 2026-08-12

- Version alignment with sibling ChatGPT/Codex, Claude Cowork, and Grok Bot helpers.
- Rename wrapper source `bin/cowork_imessage_helper.c` → `bin/imessage_helper.c`.
- Export `IMESSAGE_BRIDGE_DIR` from wrapper; keep `COWORK_IMESSAGE_BRIDGE_DIR` as a
  one-release alias (Python prefers new name, falls back to old).
- Refuse the retired `~/cowork-imessage` send-gate default; document three-host
  coexistence.
- Standard install now leads in README install order; hardened is optional defense-in-depth.
- Fail-closed send-gate with native confirmation dialog; Cancel is the keyboard default.
- Document and screenshot the native send-confirmation dialog (shared dialog family with Grok/Claude helpers).
- Independence by design: three separate helpers coexist on the same Mac, do not share helpers.

## 0.1.1 - 2026-08-12

- Open completed Messages snapshots as immutable, read-only databases so
  WAL-marked snapshots do not require writable `-wal` or `-shm` sidecars.

## 0.1.0 - 2026-08-12

- Add a local-only ChatGPT/Codex plugin with a bundled STDIO MCP server and
  task-focused iMessage skill.
- Add eight typed MCP tools with accurate read, local-write, and external-write
  annotations.
- Add atomic, no-follow MCP bridge requests, bounded private response reads,
  immediate response deletion, and ambiguous-send timeout guidance.
- Add independent ChatGPT/Codex LaunchAgent, executable, bridge, hardened code
  root, policies, logs, responses, and nonces for three-way coexistence with the
  Claude Cowork and Grok Bot sibling projects.
- Carry forward the native fail-closed send confirmation, nonce gate, SQLite
  online backups, privacy lifecycle, diagnostics, and root-owned hardened mode.
- Add personal marketplace installation, pinned MCP runtime setup, plugin
  validation, CI, release checksums, and coexistence documentation.
