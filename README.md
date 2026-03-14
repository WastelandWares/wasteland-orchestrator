# Wasteland Orchestrator

A Claude Code plugin for multi-agent orchestration: status reporting, transactions, team coordination, and real-time dashboard for AI agent workflows.

## What It Does

- **Agent Status Tracking** — Every agent reports what it's doing in real-time via structured status files
- **Ceremony Automation** — Hooks automatically orchestrate agent initialization (spawn setup, heartbeat, status registration)
- **Transaction System** — Groups related actions into auditable units with stated intent and justification
- **Protocol Enforcement** — PreToolUse hooks verify agents follow conventions (worktree isolation, etc.)
- **Sprint Dispatch** — Automated swarm dispatcher reads sprint manifests and spawns parallel `claude -p` agents
- **Dashboard Ready** — Status files and transaction logs feed terminal dashboards and the HQ visual dashboard

## Architecture

### System Overview

The orchestrator sits at the center of a multi-layer agent system. Thomas (human) directs a PM agent, who plans sprints and dispatches work to dev agents via the orchestrator.

```mermaid
graph TB
    subgraph "Human Layer"
        T["Thomas / Contributors"]
    end

    subgraph "Management Layer"
        PM["PM Agent (Elara)<br/>Sprint planning, triage,<br/>manifest generation"]
        DOC["Documentation Agent<br/>Changelog, README,<br/>CLAUDE.md reconciliation"]
    end

    subgraph "Orchestration Layer"
        SWARM["swarm.py<br/>Sprint Dispatcher"]
        DAEMON["dispatch-daemon.sh<br/>Task Queue Daemon"]
        MANIFEST["sprint.yaml<br/>Sprint Manifest"]
        GENMAN["generate_manifest.py<br/>Issue → Manifest"]
    end

    subgraph "Execution Layer"
        DTL["Dev Team Lead<br/>(per project)"]
        DEV1["Dev Agent<br/>(codsworth, drizzt, etc.)"]
        DEV2["Dev Agent<br/>(nick-valentine, minsc, etc.)"]
        TEST["Test Agent"]
        UIUX["UI/UX Agent"]
        REVIEW["claude-review<br/>(GitHub Action)"]
    end

    subgraph "Infrastructure Layer"
        STATUS["Status Files<br/>~/.claude/agents/status/*.json"]
        TX["Transaction Logs<br/>~/.claude/agents/transactions/"]
        GITHUB["GitHub<br/>(Code Hosting)"]
        HQ["HQ Dashboard<br/>(wasteland-hq)"]
        PIN["Pinboard<br/>~/.claude/pinboard.json"]
        BTW["BTW Queue<br/>~/.claude/btw-queue.json"]
    end

    T -->|"ideas, direction"| PM
    PM -->|"generates"| MANIFEST
    GENMAN -->|"writes"| MANIFEST
    MANIFEST -->|"input to"| SWARM
    PM -->|"dispatches tasks"| DAEMON
    SWARM -->|"spawns claude -p"| DEV1 & DEV2
    DAEMON -->|"spawns claude --print"| DTL
    DTL -->|"coordinates"| DEV1 & DEV2 & TEST & UIUX
    DEV1 & DEV2 -->|"push + PR"| GITHUB
    GITHUB -->|"triggers"| REVIEW
    REVIEW -->|"approves/requests changes"| DEV1 & DEV2
    DEV1 & DEV2 & DTL & PM -->|"write"| STATUS
    DEV1 & DEV2 & DTL & PM -->|"write"| TX
    STATUS -->|"read by"| HQ
    PIN -->|"read by"| HQ
    BTW -->|"messages between"| PM
    PM --> DOC
```

### Task Dispatch Flow

There are two dispatch mechanisms: the **swarm dispatcher** for full sprint execution, and the **dispatch daemon** for ad-hoc task delegation.

#### Swarm Dispatcher (Sprint Execution)

```mermaid
sequenceDiagram
    participant PM as PM Agent
    participant GEN as generate_manifest.py
    participant SW as swarm.py
    participant DAG as Dependency DAG
    participant CF as Conflict Detector
    participant AG1 as Agent 1 (claude -p)
    participant AG2 as Agent 2 (claude -p)
    participant MON as Health Monitor
    participant SF as Status Files

    GEN->>GEN: Extract files, deps, agents from issue data
    GEN-->>PM: sprint.yaml manifest

    PM->>SW: python3 swarm.py sprint.yaml

    SW->>DAG: Build dependency layers (topological sort)
    SW->>CF: Detect file ownership conflicts
    CF-->>SW: Add serialization edges for overlapping files

    rect rgb(230, 245, 255)
        Note over SW,AG2: Layer 0 — No dependencies
        SW->>AG1: Spawn: claude -p (story #A)
        SW->>AG2: Spawn: claude -p (story #B)
    end

    loop Every 10 seconds
        SW->>AG1: poll() — check exit code
        SW->>AG2: poll() — check exit code
        AG1->>SF: Write heartbeat
        AG2->>SF: Write heartbeat
        MON->>SF: Check heartbeats (stale > 5min?)
        MON-->>SW: Health issues (if any)
    end

    AG1-->>SW: Exit code 0 (success)

    rect rgb(230, 255, 230)
        Note over SW,AG2: Layer 1 — Dependencies met
        SW->>AG2: (Already running from Layer 0)
    end

    AG2-->>SW: Exit code 0 (success)
    SW-->>PM: Sprint complete (N/N succeeded)
```

#### Dispatch Daemon (Ad-hoc Task Queue)

```mermaid
sequenceDiagram
    participant CALLER as Calling Agent (e.g. PM)
    participant LIB as dispatch.sh
    participant Q as queue/ directory
    participant DMN as dispatch-daemon.sh
    participant ACT as active/ directory
    participant CL as claude --print (depth 0)
    participant DONE as done/ + results/

    CALLER->>LIB: dispatch_task("dev-team-lead", "/path", "Implement #22")
    LIB->>Q: Write task-{timestamp}-{pid}-{hex}.json
    LIB-->>CALLER: Return task_id

    loop Every 2 seconds
        DMN->>Q: Scan for pending tasks (priority order: critical > high > normal)
    end

    DMN->>Q: Pick up task JSON
    DMN->>ACT: Move task to active/
    DMN->>CL: Spawn: claude --print --agent {name} --permission-mode auto -p "prompt"

    Note over CL: Agent works at depth 0<br/>Has full Agent tool access<br/>Can spawn own subagents (depth 1, 2)

    CL->>CL: Execute task autonomously
    CL-->>DMN: Process exits

    DMN->>DONE: Move task JSON to done/
    DMN->>DONE: Write result text to results/{task_id}.txt

    CALLER->>LIB: dispatch_poll(task_id) or dispatch_wait(task_id, 600)
    LIB->>DONE: Check for done/{task_id}.json
    LIB-->>CALLER: Task complete
    CALLER->>LIB: dispatch_result(task_id)
    LIB-->>CALLER: Result text
```

### Project Structure

```
wasteland-orchestrator/
  .claude-plugin/
    plugin.json          # Plugin manifest
  hooks/
    hooks.json           # Hook registration
    pretooluse.py        # PreToolUse: heartbeat, worktree checks
    posttooluse.py       # PostToolUse: heartbeat, tool tracking
    stop.py              # Stop: cleanup status, archive interrupted transactions
  lib/
    agent_status.sh      # Agent status reporting (shell wrapper)
    agent_status.py      # Agent status reporting (Python)
    agent_tx.sh          # Transaction system (shell wrapper)
    agent_tx.py          # Transaction system (Python)
  tools/
    ww-json-tool.py      # JSON processing utility for agent workflows
  skills/
    agent-protocol/
      SKILL.md           # Mandatory protocol documentation
  commands/
    status.md            # /status slash command
    tx.md                # /tx slash command
  docs/
    VOCABULARY.md        # Agent protocol terminology guide
    ARCHITECTURE.md      # System design and data flow diagrams
```

### Agent Communication & Status

Agents communicate through file-based systems. No sockets, no message queues — just JSON files on disk.

```mermaid
graph LR
    subgraph "Agent Sessions"
        A1["Agent 1<br/>(interactive)"]
        A2["Agent 2<br/>(claude -p)"]
        A3["Agent 3<br/>(claude --print)"]
    end

    subgraph "Status System"
        SS["agent_status_update()<br/>agent-status.sh / agent_status.py"]
        SF["~/.claude/agents/status/<br/>{agent-name}.json"]
        HB["Heartbeat<br/>(auto via PreToolUse hook)"]
    end

    subgraph "Transaction System"
        TXB["tx_begin() / tx_end()<br/>agent-tx.sh / agent_tx.py"]
        TXF["~/.claude/agents/transactions/<br/>{agent}.current.json"]
        TXL["~/.claude/agents/transactions/log/<br/>{tx_id}.json"]
    end

    subgraph "Messaging"
        BTW["BTW Queue<br/>~/.claude/btw-queue.json"]
        COOK["Cook Mode State<br/>~/.claude/state/cook-mode.json"]
        PINB["Pinboard<br/>~/.claude/pinboard.json"]
    end

    subgraph "Dashboard"
        HQW["hq-status-writer.py<br/>(polls every 5s agents)"]
        HQJ["~/.claude/hq-status.json"]
        HQUI["Wasteland HQ<br/>React Dashboard"]
    end

    A1 & A2 & A3 --> SS
    SS --> SF
    HB --> SF
    A1 & A2 & A3 --> TXB
    TXB --> TXF
    TXB -->|"on tx_end()"| TXL

    A1 -->|"cook_queue_message()"| BTW
    A1 -->|"cook_activate()"| COOK
    A1 -->|"pin_add()"| PINB

    SF --> HQW
    PINB --> HQW
    COOK --> HQW
    HQW -->|"atomic write"| HQJ
    HQJ --> HQUI
```

### Git Workflow

All code changes flow through feature branches, pull requests, and automated review.

```mermaid
gitGraph
    commit id: "v0.1.0"
    branch _dev
    checkout _dev
    commit id: "merged features"
    branch feat/issue-8-layout
    checkout feat/issue-8-layout
    commit id: "feat(#8): side-by-side layout"
    commit id: "fix: address review feedback"
    checkout _dev
    merge feat/issue-8-layout id: "PR #1 merged"
    branch feat/issue-16-api-key
    checkout feat/issue-16-api-key
    commit id: "feat(#16): wire API key"
    checkout _dev
    merge feat/issue-16-api-key id: "PR #2 merged"
    checkout main
    merge _dev id: "Release: Thomas merges" tag: "v1.0.0"
```

**Branch rules:**
- `main` — production, only Thomas merges here
- `_dev` — integration branch, dev-lead may merge feature PRs here
- `feat/issue-N-*` — feature branches, one per story, target `_dev`
- Agents **never** commit directly to `main` or `_dev`

**PR lifecycle:**
1. Agent creates `feat/issue-N-*` branch from `_dev`
2. Agent pushes to GitHub and creates PR targeting `_dev`
3. `claude-review` GitHub Action runs automated code review
4. Agent addresses review feedback, pushes fixes
5. Once review passes, dev-lead merges PR into `_dev`
6. For releases: PM creates `_dev` → `main` PR, Thomas reviews and merges

### Hook Enforcement

The plugin uses Claude Code hooks to enforce protocol compliance at the tool-call level.

```mermaid
flowchart TD
    TC["Agent makes a tool call"]
    PRE["PreToolUse Hook<br/>(pretooluse.py)"]
    HB["Update heartbeat<br/>(every tool call)"]
    BASH{"Tool is Bash?"}
    WT{"Dev agent in worktree?"}
    WARN["ALLOW + WARNING<br/>Inject system message"]
    ALLOW["ALLOW<br/>Proceed normally"]
    POST["PostToolUse Hook<br/>(posttooluse.py)"]
    TRACK["Update heartbeat +<br/>track last_tool used"]
    STOP["Stop Hook<br/>(stop.py)"]
    CLEAN["Remove status file +<br/>archive interrupted txs"]

    TC --> PRE
    PRE --> HB
    HB --> BASH
    BASH -->|"No"| ALLOW
    BASH -->|"Yes"| WT
    WT -->|"In worktree"| ALLOW
    WT -->|"In main tree"| WARN

    ALLOW --> POST
    POST --> TRACK

    TC -.->|"Session ends"| STOP
    STOP --> CLEAN
```

### Chain of Command

```mermaid
graph TD
    T["Thomas<br/>(Human, Final Authority)"]
    PM["PM Agent — Elara<br/>Sprint planning, triage, intake"]
    DTL_CG["Dev Lead<br/>claude-gate"]
    DTL_DND["Dev Lead<br/>dnd-tools"]
    DTL_MS["Dev Lead<br/>meeting-scribe"]
    DOC["Documentation Agent<br/>Changelog, README, CLAUDE.md"]
    COD["codsworth<br/>(UI/Swift dev)"]
    NICK["nick-valentine<br/>(integration/API dev)"]
    DRIZZT["drizzt<br/>(content systems)"]
    MINSC["minsc<br/>(gameplay dev)"]
    TASHA["tasha<br/>(evaluation/infrastructure)"]
    ELM["elminster<br/>(AI pipeline design)"]
    DOG["dogmeat<br/>(infrastructure/CI)"]
    PIXEL["pixel<br/>(UI/UX)"]
    SCRIBE["scribe<br/>(meeting transcription)"]
    CR["claude-review<br/>(GitHub Action)"]
    TEST["Test Agent"]
    UIUX["UI/UX Agent"]

    T -->|"ideas, priorities"| PM
    PM -->|"sprint plans"| DTL_CG & DTL_DND & DTL_MS
    PM -->|"doc tasks"| DOC
    DTL_CG -->|"assigns stories"| COD & NICK
    DTL_DND -->|"assigns stories"| DRIZZT & MINSC & TASHA & ELM
    DTL_CG & DTL_DND & DTL_MS -->|"code review"| CR
    DTL_CG & DTL_DND -->|"test tasks"| TEST
    DTL_CG -->|"design review"| UIUX
    DOG -->|"infra across projects"| DTL_CG & DTL_DND
```

**Idea flow:** Thomas's raw ideas → PM triages → issue created → manifest generated → dispatcher spawns agents → agents implement → PR reviewed → merged to `_dev` → PM creates release PR → Thomas merges to `main`.

## Component Reference

### Core Orchestrator

| File | Description |
|------|-------------|
| `swarm.py` | Sprint dispatcher — reads manifest, builds DAG, spawns `claude -p` agents, monitors health |
| `generate_manifest.py` | Provides helper functions for parsing issues into `sprint.yaml` manifests |
| `sprint.yaml` | Sprint manifest — stories, agents, dependencies, max parallelism |

### Plugin Infrastructure

| File | Description |
|------|-------------|
| `.claude-plugin/plugin.json` | Claude Code plugin manifest (name, version, metadata) |
| `hooks/hooks.json` | Hook registration — maps PreToolUse, PostToolUse, Stop to Python scripts |
| `hooks/pretooluse.py` | PreToolUse hook — heartbeat, worktree checks |
| `hooks/posttooluse.py` | PostToolUse hook — heartbeat update, last-tool tracking |
| `hooks/stop.py` | Stop hook — cleanup status file, archive interrupted transactions |

### Python Libraries (`lib/`)

| File | Description |
|------|-------------|
| `lib/manifest.py` | `SprintManifest` and `Story` dataclasses, YAML parser, topological sort |
| `lib/agent_status.py` | `AgentStatus` class for reading/writing status JSON files |
| `lib/agent_tx.py` | `Transaction` class for begin/action/end with JSON persistence |
| `lib/conflict.py` | File ownership graph — detects overlapping stories, adds serialization edges |
| `lib/monitor.py` | `HealthMonitor` — heartbeat checks, stall detection, auto-restart of failed agents |

### Shell Libraries (`~/.claude/lib/`)

| File | Description |
|------|-------------|
| `agent-status.sh` | `agent_status_update`, `agent_status_heartbeat`, `agent_status_clear`, `agent_status_list` |
| `agent-tx.sh` | `tx_begin`, `tx_action`, `tx_end`, `tx_current`, `tx_recent` |
| `dispatch.sh` | `dispatch_task`, `dispatch_poll`, `dispatch_wait`, `dispatch_result`, `dispatch_status` |
| `cook.sh` | `cook_activate`, `cook_deactivate`, `cook_queue_message`, `cook_check_exit`, `cook_is_active` |
| `btw.sh` | `btw_check`, `btw_count`, `btw_read`, `btw_process_all` — background message queue |
| `pinboard.sh` | `pin_add`, `pin_list`, `pin_done`, `pin_remove`, `pin_update` — persistent cross-session notes |

### Daemon & Dashboard

| File | Description |
|------|-------------|
| `~/.claude/bin/dispatch-daemon.sh` | Standalone daemon — watches queue/, spawns `claude --print`, manages lifecycle |
| `~/.claude/bin/hq-status-writer.py` | Polls status files, writes `hq-status.json` for the React dashboard |

### Slash Commands

| Command | Description |
|---------|-------------|
| `/status` | Show all agent states, active transactions, stale/dead detection |
| `/tx` | Transaction management — `begin`, `action`, `end`, `current`, `recent` |
| `/cook` | Activate autonomous work mode — user messages queued, not interrupting |
| `/uncook` | Exit cook mode — show queued message summary |

### Skills

| Skill | Description |
|-------|-------------|
| `agent-protocol` | Mandatory protocol spec — status reporting, worktrees, transactions, commits |

## Protocol Overview

All agents must:
1. Report status via `agent_status_update` (hooks handle heartbeat automatically)
2. Wrap work in transactions with intent/justification
3. Work in git worktrees (dev agents only, enforced by hooks)
4. Update persona files with learnings after each session

See `skills/agent-protocol/SKILL.md` for the full protocol specification.

## Documentation

- **VOCABULARY.md** — Terminology guide for agent roles, states, and workflow concepts
- **ARCHITECTURE.md** — Visual system design including agent initialization flow and transaction lifecycle
- **Ceremony Automation** — Hooks automatically initialize agents with proper status tracking and spawn handling

## Agent States

| State | Meaning |
|-------|---------|
| idle | No active task |
| working | Actively on a task |
| reviewing | Reviewing code/PR |
| brainstorming | Design session |
| meeting | Meeting scribe live |
| blocked | Waiting on dependency |

## Installation

### As a Claude Code Plugin
```bash
# From the Claude Code CLI
claude plugin add wasteland-orchestrator
```

### Manual
```bash
git clone https://github.com/severeon/wasteland-orchestrator.git
# Add to your Claude Code project's plugin configuration
```

## Usage

### Running a Sprint

```bash
# 1. Create or edit a sprint manifest
vim sprint.yaml

# 2. Launch the swarm
python3 swarm.py sprint.yaml

# 3. Watch progress (separate terminal)
python3 swarm.py --status
```

### Transaction Example

```python
from lib.agent_tx import Transaction

tx = Transaction("dev-lead-ms")
tx.begin("Implementing assistant skeleton", "Phase 1 task #17", repo="tquick/meeting-scribe", issue=17)
tx.action("Created src/assistant.py", "Core assistant class with Ollama client")
tx.action("Updated pipeline.py", "Integrated assistant as post-transcription stage")
tx.end("success", "Assistant skeleton in place, ready for model integration")
```

### Dispatch Daemon

```bash
# Start the daemon (background)
~/.claude/bin/dispatch-daemon.sh start

# Check status
~/.claude/bin/dispatch-daemon.sh status

# Tail a running task's output
~/.claude/bin/dispatch-daemon.sh tail task-1741234567-12345-a1b2c3d4

# Stop the daemon
~/.claude/bin/dispatch-daemon.sh stop
```

## License

MIT
