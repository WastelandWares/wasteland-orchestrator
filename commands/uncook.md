---
name: uncook
description: Exit "Let Claude Cook" mode and show queued message summary
---

# /uncook — Exit Cook Mode

Deactivate cook mode and return to normal interactive behavior.

## Behavior

When this command is invoked:

1. Source the cook library and deactivate:
   ```bash
   source ~/.claude/lib/cook.sh
   cook_deactivate
   ```

2. Display the summary output from `cook_deactivate`, which shows:
   - How long the cook session lasted
   - How many messages were queued
   - List of all queued messages with timestamps

3. Return to normal interactive behavior — respond to user messages directly instead of queuing them.

4. If there are queued messages, offer to process them:
   - "Would you like me to go through the queued messages now?"
   - Or process them directly if the context makes it clear

5. If cook mode was not active, say so:
   - "Cook mode isn't active. Use `/cook` to start an autonomous work session."
