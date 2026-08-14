# Changelog

Releases use semantic versioning for the helper, MCP server, and plugin package.
The file-bridge protocol has its own major/minor compatibility version.

## Unreleased

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
