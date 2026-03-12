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

# Read hook input
HOOK_INPUT=$(cat 2>/dev/null || echo '{}')
AGENT_TYPE=$(echo "$HOOK_INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('agent_type',''))" 2>/dev/null || echo "unknown")
AGENT_ID=$(echo "$HOOK_INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('agent_id',''))" 2>/dev/null || echo "")

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
export CLAUDE_AGENT_NAME="sub-${AGENT_TYPE}-$$"

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
