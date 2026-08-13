---
name: chatgpt-codex-imessage
version: 1.1.0
description: Read, search, triage, and send iMessages through the local macOS iMessage MCP helper. Use for message reviews, history searches, contact lookup, response-time analysis, and user-approved plain-text sends. Use only in local ChatGPT Work or Codex sessions on a Mac where the helper is installed.
---

# Local iMessage

Use the `local-imessage` MCP tools. Do not access `chat.db` directly and do not
write bridge request files with shell commands.

## Preconditions

1. Call `imessage_status` before the first message operation in a conversation.
2. Require protocol major version `1`. Stop with upgrade guidance on a mismatch.
3. If the tool is unavailable, explain that this plugin supports local ChatGPT
   Work and local Codex sessions only. Direct the user to the repository's
   installation and Full Disk Access instructions.
4. If allowlist mode has no entries, explain that message reads are intentionally
   disabled. Never change read policy automatically.

## Reading

- Use the narrowest tool and time window that satisfies the request.
- Do not broaden a query after an allowlist or blocklist rejection.
- Return only the message details needed to answer the user.
- Remind the user when relevant that selected message content becomes model
  input and is handled under their OpenAI account and workspace data controls.

## Sending

Sending always follows this sequence:

1. Resolve a named recipient with `lookup_imessage_contacts`. Ask the user to
   choose if results are ambiguous. Send tools accept only a phone number or
   email address, never a contact name or group-chat identifier.
2. Call `preview_imessage` with the complete recipient, service, and body.
3. Show the resolved recipient, exact address, service, and complete body.
4. Wait for explicit user approval in the conversation. Approval given before
   the preview does not count.
5. Call `send_imessage` with the unchanged payload and preview nonce.
6. Tell the user a native macOS confirmation window is waiting. The message is
   sent only if they deliberately select Send there; Cancel is the default.

Never retry `send_imessage` automatically. If it times out or reports that
delivery is unknown, ask the user to inspect Messages before considering a new
send. If the nonce expires while waiting for approval, create a new preview and
show it again.

## Boundaries

- Plain-text individual sends only.
- No attachments, reactions, edits, deletes, or group sends.
- Never claim that message content remains entirely on-device. The helper makes
  no network requests, but content returned to the conversation is processed by
  OpenAI through the active product surface.
