#!/bin/bash
# subagent-stop.sh — Called when a subagent finishes
# Registered as a SubagentStop hook
#
# Issue #54: Auto-fire tx_end when subagent completes
#
# This hook:
# 1. Ends any active transaction for the subagent
# 2. Clears the subagent's status

set +e

_WW_JSON="${HOME}/.claude/bin/ww-json-tool.py"

# Read hook input
HOOK_INPUT=$(cat 2>/dev/null || echo '{}')
AGENT_TYPE="$(echo "$HOOK_INPUT" | "$_WW_JSON" json stdin-key --key agent_type --default "unknown" 2>/dev/null || echo "unknown")"
AGENT_ID="$(echo "$HOOK_INPUT" | "$_WW_JSON" json stdin-key --key agent_id --default "" 2>/dev/null || echo "")"
EXIT_CODE="$(echo "$HOOK_INPUT" | "$_WW_JSON" json stdin-key --key exit_code --default "1" 2>/dev/null || echo "1")"
OUTCOME="$(echo "$HOOK_INPUT" | "$_WW_JSON" json stdin-key --key outcome --default "" 2>/dev/null || echo "")"

# Source libraries
if [[ -f "${HOME}/.claude/lib/init.sh" ]]; then
  source "${HOME}/.claude/lib/init.sh" 2>/dev/null
fi

# Skip for built-in lightweight agents
case "$AGENT_TYPE" in
  Bash|Explore|Plan|Glob|Grep|Read|Edit|Write)
    echo '{}'
    exit 0
    ;;
esac

# Set agent name to match what SubagentStart set
export CLAUDE_AGENT_NAME="sub-${AGENT_TYPE}-${AGENT_ID}"

# Auto tx_end (#54)
if type tx_end &>/dev/null; then
  # Determine outcome based on exit code or outcome field
  TX_OUTCOME="failed"
  if [[ "$EXIT_CODE" == "0" ]] || [[ "$OUTCOME" == "success" ]]; then
    TX_OUTCOME="success"
  fi
  tx_end "$TX_OUTCOME" "Subagent ${AGENT_TYPE} completed with exit code ${EXIT_CODE}" 2>/dev/null || true
fi

# Clear status
if type agent_status_clear &>/dev/null; then
  agent_status_clear 2>/dev/null || true
fi

echo '{}'
exit 0
