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

# Ensure state dir exists
mkdir -p "$(dirname "$COOK_STATE_FILE")" 2>/dev/null

cook_is_active() {
  if [[ ! -f "$COOK_STATE_FILE" ]]; then
    return 1
  fi
  local active
  active=$(python3 -c "
import json, os
try:
    with open(os.path.expanduser('$COOK_STATE_FILE')) as f:
        data = json.load(f)
    print('yes' if data.get('active', False) else 'no')
except:
    print('no')
" 2>/dev/null)
  [[ "$active" == "yes" ]]
}

cook_activate() {
  local task="${1:-Autonomous work session}"
  python3 << PYEOF
import json, os, datetime

state = {
    "active": True,
    "started_at": datetime.datetime.now().isoformat(),
    "task": """${task}""",
    "messages_queued": 0,
    "exit_keywords": ["stop", "pause", "hey", "hey claude", "hold on", "wait", "halt"]
}

os.makedirs(os.path.dirname("$COOK_STATE_FILE"), exist_ok=True)
with open("$COOK_STATE_FILE", "w") as f:
    json.dump(state, f, indent=2)

print("🔥 LET HIM COOK — Cook mode activated!")
print(f"   Task: {state['task']}")
print(f"   Started: {state['started_at'][:19]}")
print("   User messages will be queued as btw items.")
print("   Say 'stop', 'pause', or 'hey' to exit cook mode.")
PYEOF
}

cook_deactivate() {
  if [[ ! -f "$COOK_STATE_FILE" ]]; then
    echo "Cook mode is not active."
    return 1
  fi

  python3 << 'PYEOF'
import json, os, datetime

state_file = os.path.expanduser("~/.claude/state/cook-mode.json")
btw_file = os.path.expanduser("~/.claude/btw-queue.json")

try:
    with open(state_file) as f:
        state = json.load(f)
except:
    print("Cook mode is not active.")
    exit(1)

if not state.get("active"):
    print("Cook mode is not active.")
    exit(1)

started = state.get("started_at", "unknown")
queued = state.get("messages_queued", 0)
task = state.get("task", "unknown")

# Read queued btw items tagged with cook-mode
cook_items = []
try:
    with open(btw_file) as f:
        btw = json.load(f)
    cook_items = [i for i in btw["items"]
                  if not i.get("processed") and i.get("cook_mode")]
except:
    pass

# Deactivate
state["active"] = False
state["ended_at"] = datetime.datetime.now().isoformat()
with open(state_file, "w") as f:
    json.dump(state, f, indent=2)

print("🍳 Cook mode deactivated!")
print(f"   Task: {task}")
print(f"   Session started: {started[:19]}")
print(f"   Messages queued: {queued}")

if cook_items:
    print("\n   Queued messages:")
    for i, item in enumerate(cook_items, 1):
        ts = item.get("timestamp", "?")[:16]
        print(f"   {i}. [{ts}] {item['text']}")
    print(f"\n   Process these with: btw  (or btw_read)")
else:
    print("   No messages were queued during this session.")
PYEOF
}

cook_queue_message() {
  local message="$*"
  if [[ -z "$message" ]]; then
    echo "No message to queue."
    return 1
  fi

  python3 << PYEOF
import json, os, datetime

btw_file = os.path.expanduser("~/.claude/btw-queue.json")
state_file = os.path.expanduser("~/.claude/state/cook-mode.json")

# Ensure btw file exists
if not os.path.exists(btw_file):
    with open(btw_file, "w") as f:
        json.dump({"items": [], "processed": []}, f)

with open(btw_file) as f:
    btw = json.load(f)

btw["items"].append({
    "text": """${message}""",
    "timestamp": datetime.datetime.now().isoformat(),
    "processed": False,
    "cook_mode": True,
})

with open(btw_file, "w") as f:
    json.dump(btw, f, indent=2)

# Update cook state counter
try:
    with open(state_file) as f:
        state = json.load(f)
    state["messages_queued"] = state.get("messages_queued", 0) + 1
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
except:
    pass

count = len([i for i in btw["items"] if not i.get("processed")])
print(f"📝 Queued ({count} pending)")
PYEOF
}

cook_check_exit() {
  local message="$*"
  local message_lower
  message_lower=$(echo "$message" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

  # Check against exit keywords
  python3 << PYEOF
import json, os

state_file = os.path.expanduser("~/.claude/state/cook-mode.json")
msg = """${message_lower}""".strip().lower()

try:
    with open(state_file) as f:
        state = json.load(f)
    keywords = state.get("exit_keywords", ["stop", "pause", "hey", "hey claude", "hold on", "wait", "halt"])
except:
    keywords = ["stop", "pause", "hey", "hey claude", "hold on", "wait", "halt"]

# Exact match or starts-with for multi-word keywords
for kw in keywords:
    if msg == kw or msg.startswith(kw + " ") or msg.startswith(kw + ",") or msg.startswith(kw + "."):
        print("exit")
        exit(0)

# Also check /uncook command
if msg.strip().startswith("/uncook"):
    print("exit")
    exit(0)

print("continue")
PYEOF
}
