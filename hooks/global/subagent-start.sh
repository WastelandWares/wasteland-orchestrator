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

_WW_JSON="${HOME}/.claude/bin/ww-json-tool.py"

# Read hook input
HOOK_INPUT=$(cat 2>/dev/null || echo '{}')
AGENT_TYPE="$(echo "$HOOK_INPUT" | "$_WW_JSON" json stdin-key --key agent_type --default "unknown" 2>/dev/null || echo "unknown")"
AGENT_ID="$(echo "$HOOK_INPUT" | "$_WW_JSON" json stdin-key --key agent_id --default "" 2>/dev/null || echo "")"
SESSION_ID="$(echo "$HOOK_INPUT" | "$_WW_JSON" json stdin-key --key session_id --default "" 2>/dev/null || echo "")"
CWD="$(echo "$HOOK_INPUT" | "$_WW_JSON" json stdin-key --key cwd --default "" 2>/dev/null || echo "")"

# Source libraries
if [[ -f "${HOME}/.claude/lib/init.sh" ]]; then
  source "${HOME}/.claude/lib/init.sh" 2>/dev/null
fi

# Set agent name for this subagent
PARENT_AGENT="${CLAUDE_AGENT_NAME:-unknown}"
export CLAUDE_AGENT_NAME="sub-${AGENT_TYPE}-${AGENT_ID}"

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
      # Detect repo from cwd using full remote URL to extract owner/name
      REPO=""
      if [[ -n "$CWD" ]]; then
        REMOTE_URL=$(cd "$CWD" 2>/dev/null && git remote get-url origin 2>/dev/null || echo "")
        if [[ -n "$REMOTE_URL" ]]; then
          # Extract owner/name from remote URL (handles both HTTPS and SSH formats)
          # e.g. https://github.com/owner/repo.git -> owner/repo
          # e.g. git@github.com:owner/repo.git -> owner/repo
          REPO=$(echo "$REMOTE_URL" | sed -E 's|.*[:/]([^/]+/[^/]+?)(\.git)?$|\1|')
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
  # Read custom_instructions or briefing_summary for subagent context
  DISPATCH_INSTRUCTIONS=$("$_WW_JSON" json get \
    --file "$DISPATCH_CTX_FILE" --key custom_instructions --default "" 2>/dev/null || echo "")
  if [[ -z "$DISPATCH_INSTRUCTIONS" ]]; then
    DISPATCH_BRIEFING=$("$_WW_JSON" json get \
      --file "$DISPATCH_CTX_FILE" --key briefing_summary --default "" 2>/dev/null || echo "")
    DISPATCH_INSTRUCTIONS="${DISPATCH_BRIEFING:0:500}"
  fi
  if [[ -n "$DISPATCH_INSTRUCTIONS" ]]; then
    CONTEXT_LINES+="<parent-context>
Dispatched by: ${PARENT_AGENT}
${DISPATCH_INSTRUCTIONS}
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
  echo "$CONTEXT_LINES" | "$_WW_JSON" hook build-output --event-name "SubagentStart"
else
  echo '{}'
fi

exit 0
