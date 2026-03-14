---
name: cook
description: Activate "Let Claude Cook" mode — autonomous work with queued user messages
---

# /cook — Let Claude Cook 🔥

Activate autonomous work mode. While cooking:
- Claude works continuously without interruption
- User messages are queued (via btw system) instead of interrupting workflow
- Claude acknowledges queued messages briefly and continues working
- Between major task boundaries, Claude checks and processes the queue

## Activation

When this command is invoked:

$ARGUMENTS

1. Source the cook library and activate:
   ```bash
   source ~/.claude/lib/cook.sh
   cook_activate "$ARGUMENTS"
   ```

2. Respond with a fun cooking-themed confirmation, e.g.:
   - "🔥 Kitchen's hot — let me cook!"
   - "🍳 Chef's in the zone. Messages will be queued."
   - "👨‍🍳 Apron on. I'll check your messages between courses."

3. **CRITICAL BEHAVIORAL CHANGE — From this point forward:**

   When cook mode is active (`~/.claude/state/cook-mode.json` has `"active": true`):

   a. **On receiving any user message:**
      - First, check if it contains an exit keyword: `cook_check_exit "<message>"`
      - If exit keyword detected → run `/uncook` behavior (deactivate, show summary)
      - Otherwise → queue it: `cook_queue_message "<message>"`
      - Respond ONLY with a brief single-line acknowledgment like:
        `📝 Queued: "<brief summary of message>"`
      - Immediately continue your current task. Do NOT engage with message content.

   b. **Between major task completions:**
      - Check the btw queue: `source ~/.claude/lib/btw.sh && btw_check`
      - If items pending, review them and decide:
        - Urgent/relevant to current work → process inline
        - Everything else → leave queued for later
      - Continue to next task

   c. **Exit keywords** that deactivate cook mode:
      - "stop", "pause", "hey", "hey claude", "hold on", "wait", "halt"
      - Or the `/uncook` command

   d. **The mode persists across context compactions** because state is stored in the filesystem at `~/.claude/state/cook-mode.json`

## Example Session

```
User: /cook implementing the auth system
Claude: 🔥 Kitchen's hot! Working on: implementing the auth system
        Messages will be queued — say "stop" or /uncook to exit cook mode.

User: oh also make sure to add rate limiting
Claude: 📝 Queued: "add rate limiting"
[continues working on auth system]

User: hey
Claude: 🍳 Cook mode deactivated!
        1 message was queued:
        1. "oh also make sure to add rate limiting"
        Ready for normal conversation.
```
