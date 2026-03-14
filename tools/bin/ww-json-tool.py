#!/usr/bin/env python3
"""ww-json-tool — CLI for WastelandWares JSON ops.

Replaces all inline python3 -c "..." blocks in shell scripts.
Each subcommand handles a specific JSON operation pattern.

Usage:
    ww-json-tool.py json safe-string "hello world"
    ww-json-tool.py status write --agent pm --state working --task "doing stuff" --pid 1234 --file /tmp/s.json
    ww-json-tool.py tx begin --id tx_123 --agent pm --intent "test" --justification "test" --file /tmp/tx.json
"""

import argparse
import datetime
import glob as glob_mod
import json
import os
import subprocess
import sys


# ── Helpers ──────────────────────────────────────────────────────────────

def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_local_iso():
    return datetime.datetime.now().isoformat()


def _read_json(path, default=None):
    try:
        with open(os.path.expanduser(path)) as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def _write_json(path, data):
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── json subcommands ────────────────────────────────────────────────────

def cmd_json_safe_string(args):
    """Output a JSON-escaped string."""
    print(json.dumps(args.value))


def cmd_json_get(args):
    """Read a key from a JSON file."""
    data = _read_json(args.file)
    val = data.get(args.key, args.default)
    if val is None:
        print("")
    elif isinstance(val, (dict, list)):
        print(json.dumps(val))
    else:
        print(val)


def cmd_json_set(args):
    """Set a key in a JSON file."""
    data = _read_json(args.file, {})
    try:
        data[args.key] = json.loads(args.value)
    except (json.JSONDecodeError, ValueError):
        data[args.key] = args.value
    _write_json(args.file, data)


def cmd_json_stdin_key(args):
    """Read a key from JSON on stdin."""
    try:
        data = json.load(sys.stdin)
        val = data.get(args.key, args.default or "")
        if isinstance(val, (dict, list)):
            print(json.dumps(val))
        else:
            print(val if val is not None else "")
    except Exception:
        print(args.default or "")


def cmd_json_array_length(args):
    """Read a JSON array from stdin and print its length."""
    try:
        data = json.load(sys.stdin)
        if isinstance(data, list):
            print(len(data))
        else:
            print(args.default)
    except Exception:
        print(args.default)


def cmd_json_build_object(args):
    """Build a JSON object from key=value pairs."""
    obj = {}
    for pair in args.pairs:
        if "=" not in pair:
            continue
        key, val = pair.split("=", 1)
        if val in ("null", "None"):
            obj[key] = None
        elif val == "true":
            obj[key] = True
        elif val == "false":
            obj[key] = False
        else:
            try:
                obj[key] = int(val)
            except ValueError:
                try:
                    obj[key] = float(val)
                except ValueError:
                    obj[key] = val
    if args.file:
        _write_json(args.file, obj)
    else:
        print(json.dumps(obj, indent=2))


# ── status subcommands ──────────────────────────────────────────────────

def cmd_status_write(args):
    """Write a complete agent status JSON file."""
    avatar = {}
    fpath = os.path.expanduser(args.file)
    if os.path.exists(fpath):
        existing = _read_json(fpath)
        avatar = existing.get("avatar", {})

    issue = None
    if args.issue and args.issue not in ("", "null", "None"):
        try:
            issue = int(args.issue)
        except ValueError:
            issue = args.issue

    now = _now_iso()
    status = {
        "agent": args.agent,
        "state": args.state,
        "task": args.task,
        "repo": args.repo if args.repo else None,
        "issue": issue,
        "started_at": now,
        "last_heartbeat": now,
        "pid": args.pid,
        "avatar": avatar,
    }
    _write_json(fpath, status)


def cmd_status_heartbeat(args):
    """Update heartbeat timestamp and pid in existing status file."""
    data = _read_json(args.file)
    if not data:
        return
    data["last_heartbeat"] = args.timestamp or _now_iso()
    data["pid"] = args.pid
    _write_json(args.file, data)


def cmd_status_set_avatar(args):
    """Update avatar field in existing status file."""
    data = _read_json(args.file)
    if not data:
        return
    try:
        data["avatar"] = json.loads(args.avatar_json)
    except json.JSONDecodeError:
        data["avatar"] = {}
    _write_json(args.file, data)


def cmd_status_list(args):
    """List all agent statuses with staleness and process-alive checks."""
    status_dir = os.path.expanduser(args.dir)
    now = datetime.datetime.now(datetime.timezone.utc)
    agents = []

    for f in glob_mod.glob(os.path.join(status_dir, "*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
            hb = data.get("last_heartbeat", "")
            if hb:
                hb_dt = datetime.datetime.fromisoformat(hb.replace("Z", "+00:00"))
                stale_sec = (now - hb_dt).total_seconds()
                data["stale"] = stale_sec > 300
                data["heartbeat_age_sec"] = int(stale_sec)
            pid = data.get("pid")
            if pid:
                try:
                    os.kill(pid, 0)
                    data["process_alive"] = True
                except (OSError, ProcessLookupError):
                    data["process_alive"] = False
            agents.append(data)
        except Exception:
            pass

    print(json.dumps(agents, indent=2))


def cmd_status_list_human(args):
    """List agent statuses in human-readable format (for ww_agents)."""
    status_dir = os.path.expanduser(args.dir)
    files = sorted(glob_mod.glob(os.path.join(status_dir, "*.json")))
    if not files:
        print("No active agents")
        return
    for f in files:
        try:
            with open(f) as fh:
                d = json.load(fh)
            name = os.path.basename(f).replace(".json", "")
            state = d.get("state", "?")
            msg = d.get("message", "") or d.get("task", "")
            icons = {"working": "\u2692", "idle": "\u23f8", "done": "\u2714", "error": "\u2718"}
            icon = icons.get(state, "\u2753")
            print(f"  {icon} {name:20s} {state:10s} {msg}")
        except Exception:
            pass


# ── tx subcommands ──────────────────────────────────────────────────────

def cmd_tx_begin(args):
    """Create a new transaction JSON file."""
    issue = None
    if args.issue and args.issue not in ("", "null", "None"):
        try:
            issue = int(args.issue)
        except ValueError:
            issue = args.issue

    tx = {
        "id": args.id,
        "agent": args.agent,
        "intent": args.intent,
        "justification": args.justification,
        "repo": args.repo if args.repo else None,
        "issue": issue,
        "state": "active",
        "started_at": args.timestamp or _now_iso(),
        "actions": [],
    }
    _write_json(args.file, tx)
    print(args.id)


def cmd_tx_action(args):
    """Append an action to an existing transaction."""
    data = _read_json(args.file)
    if not data:
        print("WARNING: No active transaction file.", file=sys.stderr)
        sys.exit(1)
    data.setdefault("actions", []).append({
        "timestamp": args.timestamp,
        "what": args.what,
        "why": args.why,
    })
    _write_json(args.file, data)


def cmd_tx_end(args):
    """Complete a transaction, archive to log dir."""
    data = _read_json(args.file)
    if not data:
        print("WARNING: No active transaction to end.", file=sys.stderr)
        sys.exit(1)

    data["state"] = "completed"
    data["outcome"] = args.outcome
    data["summary"] = args.summary if args.summary else None
    data["ended_at"] = args.timestamp
    data["action_count"] = len(data.get("actions", []))

    log_dir = os.path.expanduser(args.log_dir)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, data["id"] + ".json")
    _write_json(log_path, data)

    print(f'Transaction {data["id"]} completed: {data["outcome"]} ({data["action_count"]} actions)')


def cmd_tx_recent(args):
    """List recent transactions from log dir."""
    log_dir = os.path.expanduser(args.log_dir)
    tx_dir = os.path.expanduser(args.tx_dir)
    files = sorted(glob_mod.glob(os.path.join(log_dir, "*.json")), reverse=True)[:args.count]

    txs = []
    for f in files:
        try:
            with open(f) as fh:
                txs.append(json.load(fh))
        except Exception:
            pass

    for f in glob_mod.glob(os.path.join(tx_dir, "*.current.json")):
        try:
            with open(f) as fh:
                txs.insert(0, json.load(fh))
        except Exception:
            pass

    print(json.dumps(txs, indent=2))


# ── cook subcommands ────────────────────────────────────────────────────

def cmd_cook_read(args):
    """Read cook mode state, output yes/no."""
    data = _read_json(args.file, {"active": False})
    print("yes" if data.get("active", False) else "no")


def cmd_cook_activate(args):
    """Write cook state as active."""
    state = {
        "active": True,
        "started_at": _now_local_iso(),
        "task": args.task,
        "messages_queued": 0,
        "exit_keywords": ["stop", "pause", "hey", "hey claude", "hold on", "wait", "halt"],
    }
    _write_json(args.file, state)
    print("\U0001f525 LET HIM COOK \u2014 Cook mode activated!")
    print(f"   Task: {state['task']}")
    print(f"   Started: {state['started_at'][:19]}")
    print("   User messages will be queued as btw items.")
    print("   Say 'stop', 'pause', or 'hey' to exit cook mode.")


def cmd_cook_deactivate(args):
    """Deactivate cook mode, print summary."""
    state = _read_json(args.state_file)
    if not state or not state.get("active"):
        print("Cook mode is not active.")
        sys.exit(1)

    started = state.get("started_at", "unknown")
    queued = state.get("messages_queued", 0)
    task = state.get("task", "unknown")

    cook_items = []
    btw = _read_json(args.btw_file, {"items": [], "processed": []})
    cook_items = [i for i in btw.get("items", [])
                  if not i.get("processed") and i.get("cook_mode")]

    state["active"] = False
    state["ended_at"] = _now_local_iso()
    _write_json(args.state_file, state)

    print("\U0001f373 Cook mode deactivated!")
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


def cmd_cook_queue(args):
    """Append message to btw queue with cook-mode tag."""
    btw_file = os.path.expanduser(args.btw_file)
    state_file = os.path.expanduser(args.state_file)

    if not os.path.exists(btw_file):
        _write_json(btw_file, {"items": [], "processed": []})

    btw = _read_json(btw_file, {"items": [], "processed": []})
    btw.setdefault("items", []).append({
        "text": args.message,
        "timestamp": _now_local_iso(),
        "processed": False,
        "cook_mode": True,
    })
    _write_json(btw_file, btw)

    state = _read_json(state_file)
    if state:
        state["messages_queued"] = state.get("messages_queued", 0) + 1
        _write_json(state_file, state)

    count = len([i for i in btw["items"] if not i.get("processed")])
    print(f"\U0001f4dd Queued ({count} pending)")


def cmd_cook_check_exit(args):
    """Check if message matches exit keywords. exit 0=yes, 1=no (print exit/continue)."""
    state = _read_json(args.state_file, {})
    keywords = state.get("exit_keywords",
                         ["stop", "pause", "hey", "hey claude", "hold on", "wait", "halt"])

    msg = args.message.strip().lower()

    for kw in keywords:
        if msg == kw or msg.startswith(kw + " ") or msg.startswith(kw + ",") or msg.startswith(kw + "."):
            print("exit")
            sys.exit(0)

    if msg.startswith("/uncook"):
        print("exit")
        sys.exit(0)

    print("continue")


# ── pin subcommands ─────────────────────────────────────────────────────

def cmd_pin_add(args):
    """Add a pin to the pinboard."""
    board = _read_json(args.file, {"version": 1, "notes": [], "last_updated": None, "last_updated_by": None})

    note = {
        "id": str(uuid.uuid4())[:8],
        "text": args.text,
        "priority": args.priority,
        "project": args.project,
        "color": args.color,
        "created_at": _now_local_iso(),
        "created_by": args.agent,
        "done": False,
    }
    board.setdefault("notes", []).append(note)
    board["last_updated"] = _now_local_iso()
    board["last_updated_by"] = args.agent
    _write_json(args.file, board)
    print(f"Pinned: [{note['id']}] {note['text']}")


def cmd_pin_list(args):
    """List all pins."""
    board = _read_json(args.file, {"notes": []})
    notes = board.get("notes", [])
    if not notes:
        print("  (pinboard empty)")
    else:
        for n in notes:
            status = "x" if n.get("done") else " "
            pri_map = {"high": "!", "medium": "-", "low": "."}
            p = pri_map.get(n.get("priority", "medium"), "-")
            proj = f' [{n["project"]}]' if n.get("project") else ""
            print(f'  [{status}] {p} {n["id"]}: {n["text"]}{proj}')


def cmd_pin_done(args):
    """Mark a pin as done."""
    board = _read_json(args.file, {"notes": []})
    found = False
    for n in board.get("notes", []):
        if n["id"].startswith(args.id_prefix):
            n["done"] = True
            n["completed_at"] = _now_local_iso()
            n["completed_by"] = args.agent
            print(f"Done: {n['id']}: {n['text']}")
            found = True
            break
    if not found:
        print(f"Note not found: {args.id_prefix}")
    else:
        board["last_updated"] = _now_local_iso()
        _write_json(args.file, board)


def cmd_pin_remove(args):
    """Remove a pin."""
    board = _read_json(args.file, {"notes": []})
    original_len = len(board.get("notes", []))
    board["notes"] = [n for n in board.get("notes", []) if not n["id"].startswith(args.id_prefix)]
    if len(board["notes"]) < original_len:
        board["last_updated"] = _now_local_iso()
        _write_json(args.file, board)
        print(f"Removed note: {args.id_prefix}")
    else:
        print(f"Note not found: {args.id_prefix}")


def cmd_pin_update(args):
    """Update a pin with rich details."""
    board = _read_json(args.file, {"notes": []})
    found = False
    for n in board.get("notes", []):
        if n["id"].startswith(args.id_prefix):
            if args.details:
                n["details"] = args.details
            if args.code:
                n["code"] = args.code
            if args.issue:
                n["issue"] = args.issue
            if args.verify:
                n["verify"] = args.verify
            if args.links_json:
                new_links = json.loads(args.links_json)
                existing = n.get("links", [])
                existing.extend(new_links)
                n["links"] = existing
            n["updated_at"] = _now_local_iso()
            n["updated_by"] = args.agent
            print(f"Updated: {n['id']}: {n['text']}")
            found = True
            break
    if not found:
        print(f"Note not found: {args.id_prefix}")
    else:
        board["last_updated"] = _now_local_iso()
        _write_json(args.file, board)


def cmd_pin_last_id(args):
    """Get the ID of the last pin."""
    board = _read_json(args.file, {"notes": []})
    notes = board.get("notes", [])
    if notes:
        print(notes[-1]["id"])
    else:
        print("")


def cmd_pin_clear_done(args):
    """Clear all done pins."""
    board = _read_json(args.file, {"notes": []})
    before = len(board.get("notes", []))
    board["notes"] = [n for n in board.get("notes", []) if not n.get("done")]
    after = len(board["notes"])
    board["last_updated"] = _now_local_iso()
    _write_json(args.file, board)
    print(f"Cleared {before - after} done notes ({after} remaining)")


def cmd_pin_read_context(args):
    """Read pinboard and output formatted context for hook injection."""
    board = _read_json(args.file, {"notes": []})
    notes = [p for p in board.get("notes", []) if not p.get("done")]
    if not notes:
        print("No active pins.")
        return

    human_pins = [p for p in notes if p.get("needs_human")]
    regular_pins = [p for p in notes if not p.get("needs_human")]
    lines = []
    if human_pins:
        lines.append(f"ATTENTION: {len(human_pins)} pin(s) need human response:")
        for p in human_pins:
            tag = f' [{p["tag"]}]' if p.get("tag") else ""
            proj = f' ({p["project"]})' if p.get("project") else ""
            lines.append(f'  * {p["id"]}: {p["text"][:120]}{tag}{proj}')
    if regular_pins:
        lines.append(f"{len(regular_pins)} active pin(s):")
        for p in regular_pins:
            tag = f' [{p["tag"]}]' if p.get("tag") else ""
            proj = f' ({p["project"]})' if p.get("project") else ""
            lines.append(f'  * {p["text"][:120]}{tag}{proj}')
    print("\n".join(lines))


def cmd_pin_build_links(args):
    """Build links JSON array from label|url pair, merging with existing."""
    links = json.loads(args.existing) if args.existing else []
    if "|" in args.link:
        label, url = args.link.split("|", 1)
    else:
        label = args.link
        url = args.link
    links.append({"label": label, "url": url})
    print(json.dumps(links))


# ── dispatch subcommands ────────────────────────────────────────────────

def cmd_dispatch_write_task(args):
    """Write a dispatch task JSON file."""
    task = {
        "id": args.id,
        "agent": args.agent,
        "project_dir": args.project_dir,
        "prompt": args.prompt,
        "max_turns": args.max_turns,
        "caller": args.caller,
        "parent_task": args.parent_task,
        "priority": args.priority,
        "depth": args.depth,
        "status": "queued",
        "created_at": args.created_at or _now_iso(),
        "issue_number": args.issue_number,
        "use_tmux": args.use_tmux.lower() == "true",
        "use_worktree": args.use_worktree.lower() == "true",
    }
    _write_json(args.file, task)


def cmd_dispatch_parse_task(args):
    """Parse task JSON and output shell-safe variable assignments."""
    data = _read_json(args.file)
    if not data:
        print("ERROR=failed to parse task", file=sys.stderr)
        sys.exit(1)

    prompt_file = args.file.replace(".json", ".prompt")
    with open(prompt_file, "w") as pf:
        pf.write(data.get("prompt", ""))

    print(f"agent={data.get('agent', '')}")
    print(f"project_dir={data.get('project_dir', '')}")
    print(f"max_turns={data.get('max_turns', 30)}")
    print(f"depth={data.get('depth', 0)}")
    print(f"caller={data.get('caller', 'unknown')}")
    print(f"issue_number={data.get('issue_number', '')}")
    print(f"use_tmux={str(data.get('use_tmux', False)).lower()}")
    print(f"use_worktree={str(data.get('use_worktree', False)).lower()}")


def cmd_dispatch_update_status(args):
    """Update status field in a task file."""
    data = _read_json(args.file)
    if not data:
        return
    data["status"] = args.status
    if args.started_at:
        data["started_at"] = args.started_at
    _write_json(args.file, data)


def cmd_dispatch_mark_done(args):
    """Mark a task as done, write to done dir."""
    data = _read_json(args.active_file)
    if not data:
        return
    data["status"] = "done"
    data["exit_code"] = args.exit_code
    data["completed_at"] = args.completed_at or _now_iso()
    _write_json(args.done_file, data)


def cmd_dispatch_get_priority(args):
    """Get priority from a task file."""
    data = _read_json(args.file)
    print(data.get("priority", "normal"))


def cmd_dispatch_print_task(args):
    """Print task info in specified format."""
    data = _read_json(args.file)
    if not data:
        return
    if args.format == "active":
        print(f"  ACTIVE  {data['id']}  agent={data['agent']}  ")
        print(f"          {data.get('prompt', '')[:80]}...")
    elif args.format == "queued":
        print(f"  QUEUED  {data['id']}  agent={data['agent']}  pri={data.get('priority', 'normal')}")
    else:
        status = data.get("status", "?")
        print(f"{status:>8}  {data['id']}  {data['agent']}  {data.get('prompt', '')[:60]}...")


def cmd_dispatch_cancel(args):
    """Cancel a queued task."""
    data = _read_json(args.queue_file)
    if not data:
        sys.exit(1)
    data["status"] = "cancelled"
    _write_json(args.done_file, data)


def cmd_dispatch_write_context(args):
    """Write dispatch context JSON for pre-loading agent context."""
    ctx = {
        "agent_name": args.agent,
        "repo": args.repo,
        "issue_number": args.issue if args.issue else None,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "created_by": os.environ.get("CLAUDE_AGENT_NAME", "unknown"),
        "consumed": False,
    }

    if args.briefing:
        ctx["briefing_summary"] = args.briefing
    if args.instructions:
        ctx["custom_instructions"] = args.instructions

    if args.issue and args.repo:
        import urllib.request
        api_url = args.gitea_api_url or os.environ.get("GITEA_API_URL", "https://git.wastelandwares.com/api/v1")
        token = args.gitea_token or os.environ.get("GITEA_API_TOKEN", "")
        try:
            url = f"{api_url}/repos/{args.repo}/issues/{args.issue}?token={token}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                issue = json.loads(resp.read())
            ctx["issue_bodies"] = [{
                "number": issue["number"],
                "title": issue["title"],
                "body": issue.get("body", ""),
                "labels": [l["name"] for l in issue.get("labels", [])],
            }]
        except Exception:
            pass

    project_name = args.repo.split("/")[-1] if args.repo else ""
    if project_name:
        project_dir = os.path.expanduser(f"~/projects/{project_name}")
        if os.path.isdir(project_dir):
            try:
                result = subprocess.run(
                    ["git", "log", "--oneline", "-15"],
                    capture_output=True, text=True, timeout=5,
                    cwd=project_dir
                )
                if result.returncode == 0:
                    ctx["recent_commits"] = result.stdout.strip()
            except Exception:
                pass

    _write_json(args.file, ctx)
    print(f'Dispatch context written for {ctx["agent_name"]} ({ctx["repo"]})')


def cmd_dispatch_consume_context(args):
    """Mark dispatch context as consumed."""
    data = _read_json(args.file)
    if not data:
        return
    data["consumed"] = True
    data["consumed_by"] = args.agent
    _write_json(args.file, data)


# ── btw subcommands ─────────────────────────────────────────────────────

def cmd_btw_count(args):
    """Count pending btw items."""
    data = _read_json(args.file, {"items": []})
    count = len([i for i in data.get("items", []) if not i.get("processed")])
    print(count)


def cmd_btw_read(args):
    """Read pending btw items."""
    data = _read_json(args.file, {"items": []})
    pending = [i for i in data.get("items", []) if not i.get("processed")]
    if not pending:
        print("(no pending btw items)")
    else:
        for item in pending:
            ts = item.get("timestamp", "?")[:16]
            print(f"[{ts}] {item['text']}")


def cmd_btw_process_all(args):
    """Mark all pending btw items as processed."""
    data = _read_json(args.file, {"items": [], "processed": []})
    pending = [i for i in data.get("items", []) if not i.get("processed")]
    for item in data.get("items", []):
        if not item.get("processed"):
            item["processed"] = True
            item["processed_at"] = _now_local_iso()
    _write_json(args.file, data)
    for item in pending:
        ts = item.get("timestamp", "?")[:16]
        print(f"[{ts}] {item['text']}")


# ── hook subcommands ────────────────────────────────────────────────────

def cmd_hook_parse_input(args):
    """Read JSON from stdin, output requested keys as key=value pairs."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    for key in args.keys:
        val = data.get(key, "")
        print(f"{key}={val}")


def cmd_hook_build_output(args):
    """Build hook output JSON with additionalContext from stdin."""
    context = sys.stdin.read() if not args.context else args.context
    output = {
        "hookSpecificOutput": {
            "hookEventName": args.event_name,
            "additionalContext": context,
        }
    }
    print(json.dumps(output))


def cmd_hook_read_dispatch_context(args):
    """Read dispatch context and output formatted text for hook injection."""
    data = _read_json(args.file)
    if not data:
        return

    created = data.get("created_at", "")
    if created:
        try:
            created_dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
            now = datetime.datetime.now(datetime.timezone.utc)
            if (now - created_dt).total_seconds() > 300:
                return
        except Exception:
            pass

    lines = []
    if data.get("briefing_summary"):
        lines.append("## PM Briefing Summary")
        lines.append(data["briefing_summary"])
        lines.append("")
    if data.get("issue_bodies"):
        lines.append("## Issue Details")
        for issue in data["issue_bodies"]:
            lines.append(f'### #{issue.get("number", "?")} \u2014 {issue.get("title", "")}')
            lines.append(issue.get("body", ""))
            labels = issue.get("labels", [])
            if labels:
                lines.append(f'Labels: {", ".join(labels)}')
            lines.append("")
    if data.get("recent_commits"):
        lines.append("## Recent Commits")
        lines.append(data["recent_commits"])
        lines.append("")
    if data.get("cross_dependencies"):
        lines.append("## Cross-Project Dependencies")
        lines.append(data["cross_dependencies"])
        lines.append("")
    if data.get("phase_plan"):
        lines.append("## Phase Plan")
        lines.append(data["phase_plan"])
        lines.append("")
    if data.get("custom_instructions"):
        lines.append("## Instructions from PM")
        lines.append(data["custom_instructions"])
        lines.append("")

    print("\n".join(lines))


# ── stream subcommands ──────────────────────────────────────────────────

def cmd_stream_extract_result(args):
    """Extract text result from stream-json output file."""
    try:
        with open(args.file) as f:
            lines = f.readlines()
    except Exception:
        return

    text_parts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            t = event.get("type", "")
            if t == "result":
                if "result" in event:
                    text_parts.append(event["result"])
            elif t == "assistant":
                msg = event.get("message", {})
                if isinstance(msg, dict):
                    for block in msg.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block["text"])
        except (json.JSONDecodeError, KeyError):
            continue

    if text_parts:
        print("\n".join(text_parts))
    else:
        for line in lines[-20:]:
            print(line.rstrip())


def cmd_stream_pretty_print(args):
    """Pretty-print stream-json events from stdin (for tail -f piping)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            t = e.get("type", "")
            if t == "assistant":
                msg = e.get("message", {})
                if isinstance(msg, dict):
                    for b in msg.get("content", []):
                        if isinstance(b, dict) and b.get("type") == "text":
                            print(b["text"], end="", flush=True)
                elif isinstance(msg, str):
                    print(msg, end="", flush=True)
            elif t == "tool_use":
                name = e.get("tool", e.get("name", "?"))
                print(f"\n--- [{name}] ---", flush=True)
            elif t == "tool_result":
                print("--- [result] ---\n", flush=True)
            elif t == "result":
                print("\n=== DONE ===", flush=True)
        except Exception:
            pass


# ── refine subcommands ──────────────────────────────────────────────────

def cmd_refine_ollama(args):
    """Call Ollama API with prompt from file, print response text."""
    with open(args.prompt_file) as f:
        prompt_text = f.read()

    payload = json.dumps({
        "model": args.model,
        "prompt": prompt_text,
        "stream": False,
        "options": {"num_predict": args.max_tokens, "temperature": 0.4},
    })

    try:
        r = subprocess.run(
            ["curl", "-sf", args.url, "-d", payload],
            capture_output=True, text=True, timeout=120
        )
        if r.returncode == 0 and r.stdout:
            resp = json.loads(r.stdout)
            print(resp.get("response", ""))
    except Exception:
        pass


def cmd_refine_project_context(args):
    """Read project context from context graph JSON."""
    graph_path = os.path.expanduser(args.graph_file)
    try:
        with open(graph_path) as f:
            g = json.load(f)
        p = g.get("projects", {}).get(args.project, {})
        print(f"Project: {args.project}")
        print(f"Description: {p.get('blurb', 'unknown')}")
        print(f"Tech stack: {', '.join(p.get('tech_stack', []))}")
        print(f"Current sprint: {p.get('current_sprint', 'none')}")
        print(f"Open issues: {p.get('open_issues', '?')}")
        related = p.get("related_projects", [])
        if related:
            print(f"Related projects: {', '.join(related)}")
    except Exception:
        print("Project context unavailable")


# ── Main argument parser ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="ww-json-tool",
        description="WastelandWares JSON CLI \u2014 replaces inline Python in shell scripts",
    )
    sub = parser.add_subparsers(dest="group", help="Command group")

    # ── json ──
    json_p = sub.add_parser("json", help="Generic JSON operations")
    json_sub = json_p.add_subparsers(dest="cmd")

    p = json_sub.add_parser("safe-string", help="JSON-escape a string value")
    p.add_argument("value")
    p.set_defaults(func=cmd_json_safe_string)

    p = json_sub.add_parser("get", help="Read a key from a JSON file")
    p.add_argument("--file", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--default", default="")
    p.set_defaults(func=cmd_json_get)

    p = json_sub.add_parser("set", help="Set a key in a JSON file")
    p.add_argument("--file", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--value", required=True)
    p.set_defaults(func=cmd_json_set)

    p = json_sub.add_parser("stdin-key", help="Read a key from JSON on stdin")
    p.add_argument("--key", required=True)
    p.add_argument("--default", default="")
    p.set_defaults(func=cmd_json_stdin_key)

    p = json_sub.add_parser("array-length", help="Read JSON array from stdin, print length")
    p.add_argument("--default", default="?")
    p.set_defaults(func=cmd_json_array_length)

    p = json_sub.add_parser("build-object", help="Build JSON from key=value pairs")
    p.add_argument("pairs", nargs="*")
    p.add_argument("--file", default=None)
    p.set_defaults(func=cmd_json_build_object)

    # ── status ──
    status_p = sub.add_parser("status", help="Agent status operations")
    status_sub = status_p.add_subparsers(dest="cmd")

    p = status_sub.add_parser("write", help="Write agent status file")
    p.add_argument("--agent", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--repo", default="")
    p.add_argument("--issue", default="")
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_status_write)

    p = status_sub.add_parser("heartbeat", help="Update heartbeat")
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--timestamp", default="")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_status_heartbeat)

    p = status_sub.add_parser("set-avatar", help="Set avatar properties")
    p.add_argument("--avatar-json", required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_status_set_avatar)

    p = status_sub.add_parser("list", help="List all agent statuses (JSON)")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=cmd_status_list)

    p = status_sub.add_parser("list-human", help="List agent statuses (human-readable)")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=cmd_status_list_human)

    # ── tx ──
    tx_p = sub.add_parser("tx", help="Transaction operations")
    tx_sub = tx_p.add_subparsers(dest="cmd")

    p = tx_sub.add_parser("begin", help="Begin a transaction")
    p.add_argument("--id", required=True)
    p.add_argument("--agent", required=True)
    p.add_argument("--intent", required=True)
    p.add_argument("--justification", required=True)
    p.add_argument("--repo", default="")
    p.add_argument("--issue", default="")
    p.add_argument("--timestamp", default="")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_tx_begin)

    p = tx_sub.add_parser("action", help="Log a transaction action")
    p.add_argument("--what", required=True)
    p.add_argument("--why", required=True)
    p.add_argument("--timestamp", required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_tx_action)

    p = tx_sub.add_parser("end", help="End a transaction")
    p.add_argument("--outcome", required=True)
    p.add_argument("--summary", default="")
    p.add_argument("--timestamp", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--log-dir", required=True)
    p.set_defaults(func=cmd_tx_end)

    p = tx_sub.add_parser("recent", help="List recent transactions")
    p.add_argument("--log-dir", required=True)
    p.add_argument("--tx-dir", required=True)
    p.add_argument("--count", type=int, default=10)
    p.set_defaults(func=cmd_tx_recent)

    # ── cook ──
    cook_p = sub.add_parser("cook", help="Cook mode operations")
    cook_sub = cook_p.add_subparsers(dest="cmd")

    p = cook_sub.add_parser("read", help="Check if cook mode is active")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_cook_read)

    p = cook_sub.add_parser("activate", help="Activate cook mode")
    p.add_argument("--file", required=True)
    p.add_argument("--task", default="Autonomous work session")
    p.set_defaults(func=cmd_cook_activate)

    p = cook_sub.add_parser("deactivate", help="Deactivate cook mode")
    p.add_argument("--state-file", required=True)
    p.add_argument("--btw-file", required=True)
    p.set_defaults(func=cmd_cook_deactivate)

    p = cook_sub.add_parser("queue", help="Queue a message in cook mode")
    p.add_argument("--btw-file", required=True)
    p.add_argument("--state-file", required=True)
    p.add_argument("--message", required=True)
    p.set_defaults(func=cmd_cook_queue)

    p = cook_sub.add_parser("check-exit", help="Check for exit keywords")
    p.add_argument("--state-file", required=True)
    p.add_argument("--message", required=True)
    p.set_defaults(func=cmd_cook_check_exit)

    # ── pin ──
    pin_p = sub.add_parser("pin", help="Pinboard operations")
    pin_sub = pin_p.add_subparsers(dest="cmd")

    p = pin_sub.add_parser("add", help="Add a pin")
    p.add_argument("--file", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--priority", default="medium")
    p.add_argument("--project", default="")
    p.add_argument("--color", default="yellow")
    p.add_argument("--agent", default="unknown")
    p.set_defaults(func=cmd_pin_add)

    p = pin_sub.add_parser("list", help="List pins")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_pin_list)

    p = pin_sub.add_parser("done", help="Mark a pin done")
    p.add_argument("--file", required=True)
    p.add_argument("--id-prefix", required=True)
    p.add_argument("--agent", default="unknown")
    p.set_defaults(func=cmd_pin_done)

    p = pin_sub.add_parser("remove", help="Remove a pin")
    p.add_argument("--file", required=True)
    p.add_argument("--id-prefix", required=True)
    p.set_defaults(func=cmd_pin_remove)

    p = pin_sub.add_parser("update", help="Update a pin with rich details")
    p.add_argument("--file", required=True)
    p.add_argument("--id-prefix", required=True)
    p.add_argument("--details", default="")
    p.add_argument("--code", default="")
    p.add_argument("--issue", default="")
    p.add_argument("--verify", default="")
    p.add_argument("--links-json", default="")
    p.add_argument("--agent", default="unknown")
    p.set_defaults(func=cmd_pin_update)

    p = pin_sub.add_parser("last-id", help="Get last pin ID")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_pin_last_id)

    p = pin_sub.add_parser("clear-done", help="Clear all done pins")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_pin_clear_done)

    p = pin_sub.add_parser("read-context", help="Read pinboard for hook injection")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_pin_read_context)

    p = pin_sub.add_parser("build-links", help="Build links JSON from label|url")
    p.add_argument("--link", required=True)
    p.add_argument("--existing", default="[]")
    p.set_defaults(func=cmd_pin_build_links)

    # ── dispatch ──
    disp_p = sub.add_parser("dispatch", help="Dispatch operations")
    disp_sub = disp_p.add_subparsers(dest="cmd")

    p = disp_sub.add_parser("write-task", help="Write a dispatch task")
    p.add_argument("--file", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--agent", required=True)
    p.add_argument("--project-dir", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--max-turns", type=int, default=30)
    p.add_argument("--caller", default="unknown")
    p.add_argument("--parent-task", default="")
    p.add_argument("--priority", default="normal")
    p.add_argument("--depth", type=int, default=0)
    p.add_argument("--issue-number", default="")
    p.add_argument("--use-tmux", default="false")
    p.add_argument("--use-worktree", default="false")
    p.add_argument("--created-at", default="")
    p.set_defaults(func=cmd_dispatch_write_task)

    p = disp_sub.add_parser("parse-task", help="Parse task to shell vars")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_dispatch_parse_task)

    p = disp_sub.add_parser("update-status", help="Update task status")
    p.add_argument("--file", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--started-at", default="")
    p.set_defaults(func=cmd_dispatch_update_status)

    p = disp_sub.add_parser("mark-done", help="Mark task as done")
    p.add_argument("--active-file", required=True)
    p.add_argument("--done-file", required=True)
    p.add_argument("--exit-code", type=int, required=True)
    p.add_argument("--completed-at", default="")
    p.set_defaults(func=cmd_dispatch_mark_done)

    p = disp_sub.add_parser("get-priority", help="Get task priority")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_dispatch_get_priority)

    p = disp_sub.add_parser("print-task", help="Print task info")
    p.add_argument("--file", required=True)
    p.add_argument("--format", choices=["active", "queued", "list"], default="list")
    p.set_defaults(func=cmd_dispatch_print_task)

    p = disp_sub.add_parser("cancel", help="Cancel a queued task")
    p.add_argument("--queue-file", required=True)
    p.add_argument("--done-file", required=True)
    p.set_defaults(func=cmd_dispatch_cancel)

    p = disp_sub.add_parser("write-context", help="Write dispatch context")
    p.add_argument("--file", required=True)
    p.add_argument("--agent", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--issue", default="")
    p.add_argument("--briefing", default="")
    p.add_argument("--instructions", default="")
    p.add_argument("--gitea-api-url", default="")
    p.add_argument("--gitea-token", default="")
    p.set_defaults(func=cmd_dispatch_write_context)

    p = disp_sub.add_parser("consume-context", help="Mark context consumed")
    p.add_argument("--file", required=True)
    p.add_argument("--agent", required=True)
    p.set_defaults(func=cmd_dispatch_consume_context)

    # ── btw ──
    btw_p = sub.add_parser("btw", help="BTW queue operations")
    btw_sub = btw_p.add_subparsers(dest="cmd")

    p = btw_sub.add_parser("count", help="Count pending items")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_btw_count)

    p = btw_sub.add_parser("read", help="Read pending items")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_btw_read)

    p = btw_sub.add_parser("process-all", help="Mark all as processed")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_btw_process_all)

    # ── hook ──
    hook_p = sub.add_parser("hook", help="Hook helper operations")
    hook_sub = hook_p.add_subparsers(dest="cmd")

    p = hook_sub.add_parser("parse-input", help="Parse hook JSON from stdin")
    p.add_argument("--keys", nargs="+", required=True)
    p.set_defaults(func=cmd_hook_parse_input)

    p = hook_sub.add_parser("build-output", help="Build hook output JSON")
    p.add_argument("--event-name", required=True)
    p.add_argument("--context", default="")
    p.set_defaults(func=cmd_hook_build_output)

    p = hook_sub.add_parser("read-dispatch-context", help="Read dispatch context for injection")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_hook_read_dispatch_context)

    # ── stream ──
    stream_p = sub.add_parser("stream", help="Stream JSON operations")
    stream_sub = stream_p.add_subparsers(dest="cmd")

    p = stream_sub.add_parser("extract-result", help="Extract text from stream-json")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_stream_extract_result)

    p = stream_sub.add_parser("pretty-print", help="Pretty-print stream-json from stdin")
    p.set_defaults(func=cmd_stream_pretty_print)

    # ── refine ──
    refine_p = sub.add_parser("refine", help="Refinement operations")
    refine_sub = refine_p.add_subparsers(dest="cmd")

    p = refine_sub.add_parser("ollama", help="Call Ollama with prompt file")
    p.add_argument("--prompt-file", required=True)
    p.add_argument("--model", default="phi4-mini")
    p.add_argument("--url", default="http://localhost:11434/api/generate")
    p.add_argument("--max-tokens", type=int, default=800)
    p.set_defaults(func=cmd_refine_ollama)

    p = refine_sub.add_parser("project-context", help="Read project context from graph")
    p.add_argument("--project", required=True)
    p.add_argument("--graph-file", default="~/.claude/context-graph/graph.json")
    p.set_defaults(func=cmd_refine_project_context)

    # ── Parse and execute ──
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
