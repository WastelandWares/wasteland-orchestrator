#!/bin/bash
# agent-startup.sh — Called when any agent session begins
# Registered as a SessionStart hook
#
# Responsibilities:
# 1. Load environment and libraries
# 2. Detect and persist agent name via CLAUDE_ENV_FILE (#48)
# 3. Register agent in status system with heartbeat (#48)
# 4. Read pinboard and inject as context (#53)
# 5. Read dispatch context and inject for dev-leads (#55)
# 6. Verify required tools are available
#
# Issues resolved: #48, #53, #55

# IMPORTANT: Do NOT use set -euo pipefail here.
# This hook runs before full session env is available.
# Any crash = blocked session. Use set +e and exit codes instead.
set +e

_WW_JSON="${HOME}/.claude/bin/ww-json-tool.py"

# Read hook input from stdin to extract agent_type and session info
HOOK_INPUT=$(cat 2>/dev/null || echo '{}')
HOOK_AGENT_TYPE="$(echo "$HOOK_INPUT" | "$_WW_JSON" json stdin-key --key agent_type --default "" 2>/dev/null || echo "")"
HOOK_SESSION_ID="$(echo "$HOOK_INPUT" | "$_WW_JSON" json stdin-key --key session_id --default "" 2>/dev/null || echo "")"
HOOK_CWD="$(echo "$HOOK_INPUT" | "$_WW_JSON" json stdin-key --key cwd --default "" 2>/dev/null || echo "")"

# Ensure init.sh is sourced to load all libraries
if [[ -f "${HOME}/.claude/lib/init.sh" ]]; then
  source "${HOME}/.claude/lib/init.sh" 2>/dev/null
fi

# ── Issue #48: Auto-detect and persist agent name ─────────────────────
# Priority order:
#   1. CLAUDE_AGENT_NAME already set (e.g. by spawn wrapper)
#   2. agent_type from hook input (--agent flag or subagent type)
#   3. Dispatch context file
#   4. Infer from directory/persona files
#   5. Fallback: "claude"
if [[ -z "${CLAUDE_AGENT_NAME:-}" ]]; then
  if [[ -n "$HOOK_AGENT_TYPE" ]]; then
    CLAUDE_AGENT_NAME="$HOOK_AGENT_TYPE"
  elif [[ -f "${HOME}/.claude/state/dispatch-context.json" ]]; then
    CLAUDE_AGENT_NAME=$("$_WW_JSON" json get \
      --file "${HOME}/.claude/state/dispatch-context.json" \
      --key agent_name --default "" 2>/dev/null || echo "")
  fi

  if [[ -z "$CLAUDE_AGENT_NAME" ]]; then
    # Try to infer from persona file in current session directory
    if [[ -f "CLAUDE.$(basename "$PWD").md" ]]; then
      CLAUDE_AGENT_NAME=$(basename "$PWD" | sed 's/.*\.//')
    else
      CLAUDE_AGENT_NAME="claude"
    fi
  fi
fi
export CLAUDE_AGENT_NAME

# Persist CLAUDE_AGENT_NAME via CLAUDE_ENV_FILE so all Bash calls have it (#48)
if [[ -n "${CLAUDE_ENV_FILE:-}" ]]; then
  echo "export CLAUDE_AGENT_NAME=\"${CLAUDE_AGENT_NAME}\"" >> "$CLAUDE_ENV_FILE"
  # Also persist any dispatch-related env vars
  if [[ -f "${HOME}/.claude/state/dispatch-context.json" ]]; then
    DISPATCH_REPO=$("$_WW_JSON" json get \
      --file "${HOME}/.claude/state/dispatch-context.json" \
      --key repo --default "" 2>/dev/null || echo "")
    DISPATCH_ISSUE=$("$_WW_JSON" json get \
      --file "${HOME}/.claude/state/dispatch-context.json" \
      --key issue_number --default "" 2>/dev/null || echo "")
    if [[ -n "$DISPATCH_REPO" ]]; then
      echo "export DISPATCH_REPO=\"${DISPATCH_REPO}\"" >> "$CLAUDE_ENV_FILE"
    fi
    if [[ -n "$DISPATCH_ISSUE" ]]; then
      echo "export DISPATCH_ISSUE=\"${DISPATCH_ISSUE}\"" >> "$CLAUDE_ENV_FILE"
    fi
  fi
fi

# Register in status system — create status file automatically (#48)
if type agent_status_update &>/dev/null; then
  agent_status_update "starting" "Session initializing" "" "" 2>/dev/null || true
fi

# ── Issue #53: Read pinboard for context injection ────────────────────
PINBOARD_CONTEXT=""
PINBOARD_FILE="${HOME}/.claude/pinboard.json"
if [[ -f "$PINBOARD_FILE" ]]; then
  PINBOARD_CONTEXT=$("$_WW_JSON" pin read-context --file "$PINBOARD_FILE" 2>/dev/null || echo "")
fi

# ── Issue #55: Read dispatch context for dev-leads ────────────────────
DISPATCH_CONTEXT=""
DISPATCH_CTX_FILE="${HOME}/.claude/state/dispatch-context.json"
if [[ -f "$DISPATCH_CTX_FILE" ]]; then
  DISPATCH_CONTEXT=$("$_WW_JSON" hook read-dispatch-context --file "$DISPATCH_CTX_FILE" 2>/dev/null || echo "")

  # Mark the dispatch context as consumed so it doesn't re-inject on resume
  "$_WW_JSON" dispatch consume-context \
    --file "$DISPATCH_CTX_FILE" \
    --agent "${CLAUDE_AGENT_NAME}" 2>/dev/null || true
fi

# Verify Gitea access (non-fatal, quiet) — use env vars instead of hardcoded credentials
GITEA_USER="${GITEA_USER:-}"
GITEA_PASS="${GITEA_PASS:-}"
GITEA_TOKEN="${GITEA_TOKEN:-}"
if [[ -n "$GITEA_USER" && -n "$GITEA_PASS" ]]; then
  GITEA_CHECK=$(curl -sf -o /dev/null -w "%{http_code}" \
    -u "${GITEA_USER}:${GITEA_PASS}" \
    "https://git.wastelandwares.com/api/v1/version?token=${GITEA_TOKEN}" 2>/dev/null || echo "000")
else
  GITEA_CHECK="000"
fi

# Update status to idle (ready for work)
if type agent_status_update &>/dev/null; then
  agent_status_update "idle" "Ready" "" "" 2>/dev/null || true
fi

# ── Build output JSON with additionalContext ──────────────────────────
# SessionStart hooks can return hookSpecificOutput.additionalContext
# to inject text into the agent's context automatically
ADDITIONAL_CONTEXT=""

if [[ -n "$PINBOARD_CONTEXT" ]]; then
  ADDITIONAL_CONTEXT+="<pinboard>
${PINBOARD_CONTEXT}
</pinboard>
"
fi

if [[ -n "$DISPATCH_CONTEXT" ]]; then
  ADDITIONAL_CONTEXT+="<dispatch-context>
${DISPATCH_CONTEXT}
</dispatch-context>
"
fi

# Add agent identity reminder
ADDITIONAL_CONTEXT+="<agent-metadata>
Agent: ${CLAUDE_AGENT_NAME}
Session: ${HOOK_SESSION_ID}
Libraries pre-loaded: agent-status.sh, agent-tx.sh, gitea-api.sh (via CLAUDE_ENV_FILE)
CLAUDE_AGENT_NAME is set in your environment — no need to export it manually.
</agent-metadata>"

if [[ -n "$ADDITIONAL_CONTEXT" ]]; then
  echo "$ADDITIONAL_CONTEXT" | "$_WW_JSON" hook build-output --event-name "SessionStart"
else
  echo '{}'
fi

exit 0
