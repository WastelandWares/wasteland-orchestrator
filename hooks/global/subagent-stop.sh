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
eval "$(echo "$HOOK_INPUT" | "$_WW_JSON" hook parse-input --keys agent_type agent_id 2>/dev/null || echo "")"
AGENT_TYPE="${agent_type:-unknown}"
AGENT_ID="${agent_id:-}"

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
  tx_end "success" "Subagent ${AGENT_TYPE} completed" 2>/dev/null || true
fi

# Clear status
if type agent_status_clear &>/dev/null; then
  agent_status_clear 2>/dev/null || true
fi

echo '{}'
exit 0
