# Smoke Test — 5-Minute Validation

This checklist verifies that the iMessage helper is installed correctly and working with ChatGPT/Codex.

Run this after initial installation or after rebuilding the helper.

---

## Prerequisites

- [ ] One installer completed successfully
- [ ] Full Disk Access granted to the exact wrapper path printed by that installer
- [ ] The ChatGPT desktop app was restarted after plugin installation
- [ ] The composer is set to **Work locally**, or Codex is open on this Mac

---

## Test 1: Bridge Folder Setup

**Verify the bridge folder structure exists:**

```bash
BRIDGE="$HOME/Library/Application Support/ChatGPTCodexIMessage"
ls -la "$BRIDGE/control/requests"
ls -la "$BRIDGE/control/responses"
ls -la "$BRIDGE/contacts/blocked_chats.txt"
```

**Expected:**
- All directories and files exist
- `control/requests/` and `control/responses/` are mode `700`
- `contacts/blocked_chats.txt` exists (may be empty or template-only)
- Hardened installs report an `allowlist` read policy and return no message or
  contact data until at least one identifier is added

**If this fails:** Re-run the installer you selected.

---

## Test 2: Launchd Agent Is Running

**Check the launchd agent status:**

```bash
launchctl list | grep com.jeffhuber.chatgpt-codex-imessage
```

**Expected:** One line of output like:

```text
12345   0   com.jeffhuber.chatgpt-codex-imessage
```

The first number is the PID (can be `-` if the agent is loaded but not currently running). The second number (`0`) is the last exit status—`0` means success.

**If this fails:**
- Verify the plist exists: `ls -l ~/Library/LaunchAgents/com.jeffhuber.chatgpt-codex-imessage.plist`
- Bootstrap manually: `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.jeffhuber.chatgpt-codex-imessage.plist`

---

## Test 3: Plugin and MCP Discovery

Open **Plugins** in the ChatGPT desktop app and confirm **iMessage for ChatGPT
and Codex** is installed from the Personal source. In Codex, `/mcp` should show
`local-imessage` after the app restarts.

You can also inspect the local package:

```bash
ls -la "$HOME/plugins/chatgpt-codex-imessage-plugin/.codex-plugin/plugin.json"
ls -la "$BRIDGE/mcp-venv/bin/python"
```

**Expected:** Both files exist; the MCP server is available without an OAuth or
remote-service login.

---

## Test 4: Read Action (Manual)

**Manually write a test request:**

```bash
BRIDGE="<your-bridge-folder-path>"
REQ_ID=$(date +%s)

TMP="$BRIDGE/control/requests/.request-$REQ_ID.json.tmp"
FINAL="$BRIDGE/control/requests/request-$REQ_ID.json"

cat > "$TMP" <<EOF
{"id": "$REQ_ID", "action": "contacts_lookup", "params": {"name": "test"}}
EOF
mv "$TMP" "$FINAL"
```

**Poll for the response (max 10 seconds):**

```bash
for i in {1..20}; do
  if [[ -f "$BRIDGE/control/responses/response-$REQ_ID.json" ]]; then
    RESPONSE="$BRIDGE/control/responses/response-$REQ_ID.json"
    cat "$RESPONSE"
    rm -f "$RESPONSE"
    break
  fi
  sleep 0.5
done
```

**Expected:**
- A JSON response appears within 2–5 seconds.
- The response has `"ok": true` or `"ok": false` (with an error message if your Contacts app has no matching entries—that's fine for this test).

**If this fails:**
- Check `$BRIDGE/control/log.txt` for errors.
- Verify FDA is granted (System Settings → Privacy & Security → Full Disk Access).
- If `log.txt` shows `sqlite3.OperationalError: unable to open database file`, FDA is missing or stale.

---

## Test 5: ChatGPT/Codex Integration (Read)

Keep the task local. Ask ChatGPT/Codex to check the helper status first and
confirm `protocol_version` begins with `1` and the installation checks are true.

**Ask ChatGPT/Codex to triage recent messages:**

"Triage my iMessages from the last day."

**Expected:**
- ChatGPT/Codex uses the `local-imessage` MCP server and presents the triage
  (needs-reply / low-priority / skipped buckets).
- ChatGPT/Codex does **not** say "I can't access your iMessages" or "helper not found."

**If this fails:**
- Verify you've provided the correct bridge folder path to ChatGPT/Codex.
- Check `$BRIDGE/control/log.txt` for errors.

---

## Test 6: Sending (Preview Only)

**Ask ChatGPT/Codex to preview a send:**

"Preview sending a message to +15551234567 that says 'Test message.'"

(Use a real phone number if you have one handy, or a fake one for this test—preview doesn't actually send.)

**Expected:**
- ChatGPT/Codex calls `preview_imessage` and shows you:
  - Resolved recipient name (if in your Contacts) or the raw number/email
  - Service (iMessage or SMS)
  - Text and text length
  - Whether the recipient is blocked (`blocked: false` for this test number)
  - A `send_nonce` (opaque string)
- ChatGPT/Codex does **not** actually send anything yet.

**If this fails:**
- Check `$BRIDGE/control/log.txt` for errors.
- Verify the skill is correctly handling `send_preview` requests.

---

## Test 7: Sending (Full Flow - Optional)

**Only run this if you want to test an actual send.** Use a real recipient you're comfortable texting.

**Ask ChatGPT/Codex to send a message:**

"Text +15551234567: 'This is a test message from the iMessage helper.'"

**Expected:**
1. ChatGPT/Codex runs `send_preview` and shows you the preview.
2. ChatGPT/Codex waits for your explicit approval.
3. You confirm.
4. ChatGPT/Codex runs `send` with the `send_nonce` from the preview.
5. **The helper displays a native macOS confirmation dialog** showing the exact recipient and full message text in a scrollable view. Cancel is the keyboard default; deliberately select **Send** to proceed.
6. You see a confirmation: `sent_at` timestamp and resolved recipient name.
7. The message appears in Messages.app on your Mac as sent.

**On first send only:** macOS will prompt: *"chatgpt-codex-imessage-helper wants to control Messages."* Click **OK**. This grants the Automation permission.

**If this fails:**
- **Automation prompt denied:** Re-enable in System Settings → Privacy & Security → Automation → chatgpt-codex-imessage-helper → Messages.
- **`send gate: missing nonce`:** ChatGPT/Codex didn't call `send_preview` first. This is a skill bug—report it.
- **`send payload differs from preview`:** ChatGPT/Codex changed the body or recipient between preview and send. Re-run the preview.

---

## Test 8: Check Logs

**Read the helper logs:**

```bash
tail -n 50 "$BRIDGE/control/log.txt"
```

**Expected:**
- The log may be empty on a healthy run, or may contain timestamped
  diagnostics such as `contacts: loaded ...`.
- No repeated errors or stack traces.

**If you see errors:**
- `sqlite3.OperationalError: unable to open database file` → FDA not granted or stale.
- `AttributeError: ... AddressBook` → Contacts.app database schema changed (rare; report this).
- `OSError: [Errno 2] No such file or directory: '/usr/bin/osascript'` → osascript missing (should never happen on macOS; reinstall Command Line Tools).

---

## All Tests Pass?

If you've reached this point and all tests passed:

**Your iMessage helper is installed correctly and working.**

You can now use ChatGPT/Codex to:
- Triage recent messages
- Search message history
- Pull conversation threads
- Compute response-time stats
- Send plain-text iMessages with preview-and-confirm safety

---

## Common Fixes

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| No response files appear | FDA not granted | Grant FDA to the exact wrapper path printed by the installer |
| `sqlite3.OperationalError` in logs | FDA not granted or stale | Re-add the wrapper in System Settings → Full Disk Access |
| Send fails on first attempt | Automation permission needed | Click **OK** on the macOS prompt; future sends will work |
| `send gate: missing nonce` | Skill didn't call `send_preview` first | Report a bug—the skill should always preview before send |
| Messages decode as empty | `attributedBody` parser failed | Check logs for a byte-count-only parser diagnostic |

---

## Next Steps

- Hardened install: add only the contacts the user intends to expose with `configure_allowlist.py`
- Standard install: add sensitive threads to `contacts/blocked_chats.txt`
- Explore chained workflows: "Triage the last 3 days, then draft replies to anything actionable."
- Read the full protocol: `docs/PROTOCOL.md`
- Review security details: `SECURITY.md`

---

## Reporting Issues

If a test fails and the fix isn't obvious:

1. Collect `$BRIDGE/control/log.txt`.
2. Note which test failed and what the actual output was.
3. Open an issue at [github.com/jeffhuber/chatgpt-codex-imessage-plugin/issues](https://github.com/jeffhuber/chatgpt-codex-imessage-plugin/issues) with:
   - macOS version
   - ChatGPT/Codex version (if applicable)
   - Test number that failed
   - Relevant log excerpts (redact personal info)

---

## License

This smoke test is part of the `chatgpt-codex-imessage-plugin` project, licensed under MIT.
