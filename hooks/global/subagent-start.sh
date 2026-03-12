#!/bin/bash
# subagent-start.sh — Called when a subagent is spawned
# Registered as a SubagentStart hook
#
# Issue #54: Auto-fire tx_begin when subagent spawns
#
# This hook:
# 1. Reads the subagent's agent_type and agent_id from stdin
# 2. Starts a transaction (tx_begin) automatically
# 3. Sets the subagent's CLAUDE_AGENT_NAME
# 4. Injects context including pinboard and dispatch info

set +e

# Read hook input
HOOK_INPUT=$(cat 2>/dev/null || echo '{}')
AGENT_TYPE=$(echo "$HOOK_INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('agent_type',''))" 2>/dev/null || echo "unknown")
AGENT_ID=$(echo "$HOOK_INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('agent_id',''))" 2>/dev/null || echo "")
SESSION_ID=$(echo "$HOOK_INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null || echo "")
CWD=$(echo "$HOOK_INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || echo "")

# Source libraries
if [[ -f "${HOME}/.claude/lib/init.sh" ]]; then
  source "${HOME}/.claude/lib/init.sh" 2>/dev/null
fi

# Set agent name for this subagent
PARENT_AGENT="${CLAUDE_AGENT_NAME:-unknown}"
export CLAUDE_AGENT_NAME="sub-${AGENT_TYPE}-$$"

# ── Auto tx_begin (#54) ──────────────────────────────────────────────
# Start a transaction automatically for the subagent
# Skip for built-in lightweight agents (Explore, Plan, Bash) that are
# quick lookups, not real work sessions
case "$AGENT_TYPE" in
  Bash|Explore|Plan|Glob|Grep|Read|Edit|Write)
    # Skip tx for built-in tool-like agents — they're lightweight
    ;;
  *)
    # Real subagent (dev-lead, test-agent, etc.) — start a transaction
    if type tx_begin &>/dev/null; then
      # Detect repo from cwd
      REPO=""
      if [[ -n "$CWD" ]]; then
        REPO=$(cd "$CWD" 2>/dev/null && git remote get-url origin 2>/dev/null | sed 's|.*/||;s|\.git$||' || echo "")
        if [[ -n "$REPO" ]]; then
          REPO="tquick/$REPO"
        fi
      fi

      tx_begin "Subagent task: ${AGENT_TYPE}" \
               "Auto-dispatched by ${PARENT_AGENT}" \
               "$REPO" \
               "" 2>/dev/null || true
    fi
    ;;
esac

# ── Build additionalContext for the subagent ──────────────────────────
CONTEXT_LINES=""

# Include dispatch context if available
DISPATCH_CTX_FILE="${HOME}/.claude/state/dispatch-context.json"
if [[ -f "$DISPATCH_CTX_FILE" ]]; then
  DISPATCH_SUMMARY=$(python3 -c "
import json, os
ctx_file = os.path.expanduser('~/.claude/state/dispatch-context.json')
with open(ctx_file) as f:
    ctx = json.load(f)
# Only include if not consumed or if custom_instructions exist
if ctx.get('custom_instructions'):
    print(ctx['custom_instructions'])
elif ctx.get('briefing_summary'):
    # Abbreviated version for subagents
    print(ctx['briefing_summary'][:500])
" 2>/dev/null || echo "")
  if [[ -n "$DISPATCH_SUMMARY" ]]; then
    CONTEXT_LINES+="<parent-context>
Dispatched by: ${PARENT_AGENT}
${DISPATCH_SUMMARY}
</parent-context>
"
  fi
fi

# Agent metadata
CONTEXT_LINES+="<agent-metadata>
Agent: ${CLAUDE_AGENT_NAME} (subagent of ${PARENT_AGENT})
Transaction started automatically — no need to call tx_begin.
Use tx_action to log significant changes. tx_end will fire on SubagentStop.
Libraries available: agent-status.sh, agent-tx.sh, gitea-api.sh
</agent-metadata>"

if [[ -n "$CONTEXT_LINES" ]]; then
  python3 -c "
import json, sys
context = sys.stdin.read()
output = {
    'hookSpecificOutput': {
        'hookEventName': 'SubagentStart',
        'additionalContext': context
    }
}
print(json.dumps(output))
" <<< "$CONTEXT_LINES"
else
  echo '{}'
fi

exit 0
