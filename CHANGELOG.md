# Changelog

Releases use semantic versioning for the helper, MCP server, and plugin package.
The file-bridge protocol has its own major/minor compatibility version.

## 0.1.1 - Unreleased

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
