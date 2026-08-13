# iMessage for ChatGPT and Codex on macOS

Read, search, triage, and send iMessages from **local ChatGPT Work and Codex
sessions in the ChatGPT macOS app** through a permission-aware helper on your
Mac.

This is an independent open-source project by Jeff Huber. It is not made,
endorsed, or supported by Apple or OpenAI.

## Support Boundary

| Surface | Support | Why |
|---|---|---|
| ChatGPT Work with **Work locally** selected | Supported | The plugin's STDIO MCP server runs on the Mac. |
| Codex in the ChatGPT macOS app | Supported | Codex loads the same local plugin and MCP configuration. |
| Codex CLI or IDE extension on the same Mac | Expected | Local Codex clients share MCP configuration, but the desktop app is the primary tested surface. |
| ChatGPT web, hosted Chat, cloud Work, mobile, or remote Codex | Not supported | Cloud sessions cannot reach a private process or Messages database on your Mac. |

There is no cloud relay, hosted MCP endpoint, account service, or telemetry.
The helper and MCP server make no outbound network requests. However, message
content returned to ChatGPT or Codex becomes model input and is processed by
OpenAI under the data controls for your account and workspace.

## Capabilities

- Review recent conversations and surface likely replies
- Search allowed message history by substring
- Retrieve one conversation's recent history
- Calculate response-time statistics
- Resolve Contacts entries before a send
- Send a plain-text iMessage or SMS after two confirmations

The plugin does not support attachments, reactions, edits, deletes, group
sends, or arbitrary database queries.

## Requirements

- macOS 13 or newer
- ChatGPT macOS app with local Work or Codex available
- Xcode Command Line Tools: `xcode-select --install`
- Python 3.10 or newer
- Full Disk Access for the compiled helper wrapper
- Automation access to Messages for sending
- Network access during installation to install the pinned official Python MCP
  SDK (`mcp==2.0.0`) into a dedicated local virtual environment

The helper protocol is independently versioned and currently reports `1.1`.

## Install

Clone the repository:

```bash
git clone https://github.com/jeffhuber/chatgpt-codex-imessage-plugin.git
cd chatgpt-codex-imessage-plugin
```

### Hardened Install (Recommended)

```bash
./install-hardened.sh
```

The hardened installer uses `sudo` narrowly to place trusted helper code under:

```text
/Library/Application Support/ChatGPTCodexIMessage/users/<uid>/libexec
```

Runtime requests, responses, logs, nonces, and the MCP virtual environment stay
user-owned under:

```text
~/Library/Application Support/ChatGPTCodexIMessage
```

Reads default to deny. Add each phone number, email, or group identifier that
the helper may return:

```bash
CODE_ROOT="/Library/Application Support/ChatGPTCodexIMessage/users/$UID/libexec"
python3 "$CODE_ROOT/tools/configure_allowlist.py" add +15551234567
```

The allowlist is root-owned. A same-user process can submit read requests but
cannot broaden the set of conversations the helper may return.

### Standard Install

```bash
./install.sh
```

The standard installer keeps executable helper code in the clone and stores
runtime state in `~/Library/Application Support/ChatGPTCodexIMessage`. It needs
no administrator access, but another unsandboxed process running as your user
could replace that code. Its default blocklist protects against accidental
disclosure, not a compromised same-user process.

Both installers:

1. Build and locally code-sign an FDA wrapper and native confirmation app.
2. Install the independent `com.jeffhuber.chatgpt-codex-imessage` LaunchAgent.
3. Create private mode-700 runtime directories.
4. Install the pinned MCP SDK in the bridge's `mcp-venv`.
5. Copy the plugin to `~/plugins/chatgpt-codex-imessage-plugin`.
6. Add it to the Personal plugin marketplace and attempt to enable it.

Set `INSTALL_OPENAI_PLUGIN=0` to install only the helper. Run
`./install-plugin.sh` later to install the local plugin and MCP runtime.

### Grant macOS Permissions

After installation, grant **Full Disk Access** to the exact wrapper path printed
by the installer:

- Hardened: `/Library/Application Support/ChatGPTCodexIMessage/users/<uid>/libexec/bin/chatgpt-codex-imessage-helper`
- Standard: `<clone>/bin/chatgpt-codex-imessage-helper`

Open **System Settings > Privacy & Security > Full Disk Access**, use the `+`
button, press Cmd-Shift-G, and enter the path.

The first real send prompts for **Automation > Messages** access. The native
confirmation window appears only after that permission is available.

Restart the ChatGPT desktop app after installing or updating the plugin. In the
Plugins directory, confirm **iMessage for ChatGPT and Codex** is installed from
the Personal source if automatic enablement was unavailable.

## Use

Keep the composer set to **Work locally**, or open Codex in the macOS app, and
try:

- "Review my iMessages from the last day and flag replies I owe."
- "Search my iMessages for dinner plans from the last month."
- "Show my conversation with Alex from this week."
- "Text alex@example.com: Running ten minutes late."

The plugin calls `imessage_status` before message access. Hardened installs with
an empty allowlist intentionally return no messages or contacts.

## Send Gate

Every send has two enforced gates:

1. `preview_imessage` validates the individual phone/email recipient and full
   body, checks policy, and creates a single-use 60-second nonce bound to the
   exact `(recipient, text, service)` tuple. The assistant must show that
   complete preview and wait for approval in the conversation.
2. `send_imessage` consumes the nonce and displays a native AppKit window with
   the resolved name, exact address, service, and complete body. **Cancel is the
   keyboard default.** The helper sends only after the user deliberately clicks
   **Send**.

The nonce prevents blind, replayed, and payload-swapped sends. It does not
authorize a same-user process that can read and write the bridge. The native
dialog is the final send authorization boundary. Cancel any unexpected dialog.

The MCP send tool is marked as a non-idempotent external write. A timeout warns
that delivery may be unknown and must never be retried automatically. The
bundled MCP configuration prompts for write tools by default; the native dialog
still remains mandatory even if the host-side tool call is approved.

## Architecture

```text
ChatGPT Work locally / Codex on this Mac
                 |
       local STDIO MCP server
          (narrow typed tools)
                 |
       mode-700 JSON file bridge
                 |
      independent LaunchAgent wrapper
        (Full Disk Access holder)
                 |
       chat.db and Messages.app
```

The MCP process does not receive Full Disk Access or Automation permission. It
can only submit protocol requests to the bridge. The locally signed wrapper is
the TCC identity, validates its loaded components, applies read policy, and
owns the final send confirmation.

Responses are mode `600`, read with `O_NOFOLLOW`, bounded to 16 MiB by the MCP
client, and deleted immediately after parsing. The helper independently reaps
abandoned responses after one hour.

## MCP Tools

| Tool | Effect |
|---|---|
| `imessage_status` | Compatibility and installation checks; reads no messages |
| `review_imessages` | Triage recent allowed threads |
| `search_imessages` | Search allowed messages |
| `get_imessage_history` | Retrieve one allowed conversation |
| `get_imessage_response_stats` | Calculate response timing |
| `lookup_imessage_contacts` | Find allowed contact handles |
| `preview_imessage` | Validate payload and create an expiring nonce |
| `send_imessage` | External write requiring nonce and native confirmation |

There is deliberately no arbitrary SQL, filesystem, AppleScript, or generic
"run action" tool.

## Coexistence

These are independent helpers. Do not share a bridge folder, request queue, or Full Disk Access grant.

- **Grok Bot** — LaunchAgent `com.jeffhuber.grokbot-imessage`, wrapper `grokbot-imessage-helper` — https://github.com/jeffhuber/grokbot-imessage-skill
- **Claude Cowork** — LaunchAgent `com.jeffhuber.claudecowork-imessage`, wrapper `claude-cowork-imessage-helper` — https://github.com/jeffhuber/claudecowork-imessage-skill
- **ChatGPT/Codex** — LaunchAgent `com.jeffhuber.chatgpt-codex-imessage`, wrapper `chatgpt-codex-imessage-helper` — https://github.com/jeffhuber/chatgpt-codex-imessage-plugin

This helper is independent from the sibling Claude Cowork and Grok Bot
projects. All three can be installed and loaded at once:

| Host | LaunchAgent | Default hardened product root |
|---|---|---|
| ChatGPT/Codex | `com.jeffhuber.chatgpt-codex-imessage` | `/Library/Application Support/ChatGPTCodexIMessage` |
| Claude Cowork | `com.jeffhuber.claudecowork-imessage` | `/Library/Application Support/ClaudeCoworkIMessage` |
| Grok Bot | `com.jeffhuber.grokbot-imessage` | `/Library/Application Support/GrokBotIMessage` |

They do not share wrappers, LaunchAgents, bridge queues, policies, logs,
responses, nonces, or TCC identities. They do share the system Messages
database and Messages.app Automation surface. Do not configure two hosts to use
the same bridge directory.

## Privacy and Trust

Full Disk Access is much broader than Messages access. A compromised FDA helper
could read other protected user files. The hardened install reduces code
replacement risk but does not protect against root compromise, malicious
administrator action, compromise of OpenAI or Apple software, or disclosure of
content intentionally returned to the active model conversation.

Messages are two-sided. Other participants have not necessarily consented to
LLM processing. Allowlist only the conversations appropriate for your use.

Read [SECURITY.md](./SECURITY.md) before installing. Protocol details are in
[docs/PROTOCOL.md](./docs/PROTOCOL.md), and the post-install checklist is in
[docs/SMOKE_TEST.md](./docs/SMOKE_TEST.md).

## Diagnose and Test

For a standard install:

```bash
python3 tools/doctor.py \
  --bridge "$HOME/Library/Application Support/ChatGPTCodexIMessage" \
  --code-root "$PWD" \
  --architecture standard
```

For a hardened install, use the exact doctor command printed by the installer.

Developer checks:

```bash
python3 -m pip install -r requirements-mcp.txt
python3 -m unittest discover -s tests -v
python3 -m py_compile bin/*.py plugin_server/*.py tools/*.py
bash -n install.sh install-hardened.sh install-plugin.sh \
  uninstall.sh uninstall-hardened.sh scripts/run-mcp-server.sh
shellcheck install.sh install-hardened.sh install-plugin.sh \
  uninstall.sh uninstall-hardened.sh scripts/run-mcp-server.sh
python3 /path/to/plugin-creator/scripts/validate_plugin.py .
```

CI also compiles the C wrapper and native AppKit confirmation helper on macOS.

## Uninstall

Use the matching uninstaller:

```bash
./uninstall.sh
# or
./uninstall-hardened.sh
```

The uninstaller removes the LaunchAgent, local plugin, marketplace entry, and
MCP virtual environment. Message-related runtime files remain for review.
Delete `~/Library/Application Support/ChatGPTCodexIMessage` only when ready,
then revoke the wrapper under Full Disk Access and Automation in System
Settings.

## License

MIT. See [LICENSE](./LICENSE).
