# Host Detection Test Fixtures

These fixtures simulate different MCP host configurations for testing
host detection without requiring actual installations.

## Fixtures

- `none/` - No hosts detected
- `claude-only/` - Only Claude desktop markers
- `chatgpt-app-only/` - Only ChatGPT/Codex markers with Bridge Pro asset
- `grok-cli-only/` - Only grok CLI marker
- `mixed/` - Multiple hosts present
- `diy-only/` - Only DIY chatgpt-codex-imessage-plugin (should NOT count as Bridge Pro)
- `bridge-pro-valid/` - Valid Bridge Pro installation
- `bridge-pro-mismatch/` - Bridge Pro entry with invalid command

Each fixture has a simulated home directory structure.
