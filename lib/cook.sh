#!/bin/bash
# cook.sh — Shell helpers for "Let Claude Cook" mode
#
# Source in agent sessions:
#   source ~/.claude/lib/cook.sh
#
# Functions:
#   cook_is_active       — returns 0 if cook mode active, 1 if not
#   cook_activate        — writes state file, prints confirmation
#   cook_deactivate      — clears state, prints summary
#   cook_queue_message   — wraps btw queue with cook-mode tagging
#   cook_check_exit      — checks if a message contains exit keywords

COOK_STATE_FILE="${HOME}/.claude/state/cook-mode.json"
_WW_JSON="${HOME}/.claude/bin/ww-json-tool.py"

# Ensure state dir exists
mkdir -p "$(dirname "$COOK_STATE_FILE")" 2>/dev/null

cook_is_active() {
  if [[ ! -f "$COOK_STATE_FILE" ]]; then
    return 1
  fi
  local active
  active=$("$_WW_JSON" cook read --file "$COOK_STATE_FILE" 2>/dev/null)
  [[ "$active" == "yes" ]]
}

cook_activate() {
  local task="${1:-Autonomous work session}"
  "$_WW_JSON" cook activate \
    --file "$COOK_STATE_FILE" \
    --task "$task"
}

cook_deactivate() {
  if [[ ! -f "$COOK_STATE_FILE" ]]; then
    echo "Cook mode is not active."
    return 1
  fi

  "$_WW_JSON" cook deactivate \
    --state-file "$COOK_STATE_FILE" \
    --btw-file "${HOME}/.claude/btw-queue.json"
}

cook_queue_message() {
  local message="$*"
  if [[ -z "$message" ]]; then
    echo "No message to queue."
    return 1
  fi

  "$_WW_JSON" cook queue \
    --btw-file "${HOME}/.claude/btw-queue.json" \
    --state-file "$COOK_STATE_FILE" \
    --message "$message"
}

cook_check_exit() {
  local message="$*"
  local message_lower
  message_lower=$(echo "$message" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

  "$_WW_JSON" cook check-exit \
    --state-file "$COOK_STATE_FILE" \
    --message "$message_lower"
}
