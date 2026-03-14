# WastelandWares Vocabulary

> **Canonical glossary for the WastelandWares ecosystem.**
> Living document — add terms as the ecosystem evolves.
> Last updated: 2026-03-12

---

## Workflow & Process

### Cook Mode
Autonomous agent work mode. When activated (`/cook`), the agent works without interruption. User messages are queued in the **btw** system rather than processed inline. Exit keywords ("stop", "pause", "hey", "hold on", "wait", "halt") or `/uncook` deactivate cook mode and present the queued messages.

**Origin:** wasteland-orchestrator, cook.sh skill + lib
**State file:** `~/.claude/state/cook-mode.json`
**Statusline indicator:** 🔥 COOKING

### btw (By The Way)
Two distinct but related uses:

1. **Claude Code built-in (`/btw`):** A native command in recent Claude Code builds. Lets you ask a quick side question without adding to conversation history. The question and answer appear in a dismissible overlay and are ephemeral. Works while Claude is processing. Has full conversation visibility but no tool access. The inverse of a subagent (sees full context but no tools, vs. subagent which has tools but empty context).

2. **WastelandWares Cook Mode queue:** When an agent is cooking, incoming user messages are queued as btw items rather than breaking the agent's focus. Messages are tagged with `cook_mode: true` and presented as a batch when cook mode deactivates.

**Origin (Cook Mode):** wasteland-orchestrator, cook.sh
**Storage:** `~/.claude/btw-queue.json`

### Transaction (tx)
An auditable unit of agent work with declared intent. Every meaningful task is wrapped in `tx_begin` / `tx_end`, with intermediate `tx_action` entries logging significant changes. Transactions record:
- **Intent** — what the agent plans to do (human-readable)
- **Justification** — why the work is being done (e.g., "Phase 1 task #18")
- **Actions** — timestamped log of what changed and why
- **Outcome** — `success`, `partial`, `failed`, or `cancelled`

Transactions feed the dashboard, provide an audit trail, and will integrate with claude-gate for policy-aware gating. They are the **Audit** component of the Gate → Audit → Undo triad.

**Origin:** wasteland-orchestrator, agent-tx.sh
**Storage:** `~/.claude/agents/transactions/`

### Phase
A focused batch of work across one or more projects with named tasks, clear owners, and time-boxed execution. Phases are named (e.g., "First Light," "Ambitious March") and tracked via Gitea `in-phase` labels.

> **Note:** We deliberately avoid the term "sprint" and other Scrum/Agile terminology. Those words carry deep associations with two-week dev cycles, velocity tracking, story pointing, and baked-in wait times — concepts that don't apply to how WastelandWares operates. See *Rule 1/137, the fine-task constant.*

### Task
An actionable item of work, mapped to a Gitea issue. Tasks have complexity labels (`trivial`, `small`, `medium`, `large`) and tier priority (`now`, `next`, `later`, `icebox`). If a task is large, it should be decomposed into many smaller tasks.

> **Not "story."** Stories imply narrative structure and estimation rituals. A task is simply: something that needs doing, with enough context to do it.

### Idea
A workshopable item. Ideas should always be captured with the full context around the ideation — what prompted it, who suggested it, adjacent thoughts — and linked to any duplicate or near-duplicate ideas. Ideas are refined into tasks when they're ready for implementation.

> **Tasks vs. Ideas:** Tasks are actionable. Ideas are explorable. An idea becomes a task when it has a clear definition of done.

### Project (scope)
A large initiative spanning multiple tasks and potentially multiple phases. Tracked as a Gitea issue with the `project` label, often serving as a parent tracker (e.g., jarlf-host#1).

> **Not "epic."** Epics carry Agile baggage — estimation, velocity, burn-down charts. A project is just: a big thing made of smaller things.

### Tier
Priority classification for tasks and ideas. A degree of abstraction removed from "priority" — lessens the narrative that tasks and ideas can be ordered deterministically.
| Tier | Meaning |
|------|---------|
| **now** | Active priority — work on this immediately |
| **next** | Queued — work on this after current phase |
| **later** | Planned — will be scheduled in a future phase |
| **icebox** | Parked — captured but not currently planned |

Nothing is discarded. Every idea gets at minimum an icebox tier.

### Acceptance Test
*Needs definition.* Thomas flagged that the vocabulary should cover the acceptance test feature — the process by which a task is verified as complete. To be workshopped.

### Banned Terminology (Rule 1/137 — the fine-task constant)
Scrum and Agile terminology is banned from WastelandWares vocabulary. These words carry associations that cause actual friction with how we work — assumptions about velocity, story pointing, two-week cadences, and deterministic ordering that don't apply here.

| Banned | Replacement | Why |
|--------|-------------|-----|
| Sprint | **Phase** | "Sprint" implies fixed time-boxes, velocity tracking, retrospectives |
| Story | **Task** | "Story" implies estimation rituals and narrative structure |
| Epic | **Project** | "Epic" implies burn-down charts and hierarchical decomposition |
| Backlog grooming | **Triage** | Grooming implies a fixed ceremony |
| Standup | **Check-in** | We don't stand, and there's no fixed schedule |
| Velocity | *(no replacement)* | We don't measure throughput in points per sprint |
| Story points | *(no replacement)* | Complexity labels (trivial→large) are sufficient |

### Branching Model
```
main          ← production, ONLY Thomas merges here
  └── _dev    ← integration branch, dev-lead may merge feature PRs here
       ├── feat/issue-8-venmo    ← feature branches target _dev
       ├── fix/issue-2-healing
       └── docs/issue-36-vocab
```
- Feature branches branch from `_dev` and PR back to `_dev`
- Dev-lead may merge feature PRs into `_dev` after review passes
- Releases (`_dev` → `main`) require Thomas's approval and merge

### Conventional Commits
Commit message prefixes used across all repositories:
| Prefix | Purpose |
|--------|---------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `infra:` | Infrastructure/tooling |
| `refactor:` | Code restructuring |
| `test:` | Test additions/changes |
| `chore:` | Maintenance tasks |
| `fun:` | Fun/experimental/creative work — why do any of this if we can't have fun? |
| `havoc:` | Security adversary finding — Havoc (our red panda) found a vulnerability. Treated as critical. |

---

## Tooling & Infrastructure

### Pinboard
Shared sticky-note system for human ↔ agent communication. Persistent notes with threading, priority, and resolution tracking. Agents read the pinboard at session start for context; they pin blockers, action items, and discoveries during work.

**Key operations:**
- `add` — create a note with optional tags, project, priority, and `--needs-human` flag
- `reply` — add a threaded comment to an existing pin
- `thread` — view a pin with its full comment history
- `close` — mark a pin done with an optional resolution note
- `toggle` — flip done/undone status
- `read` — compact view for agent context loading

**Flags:** `--needs-human` surfaces the pin prominently (🚨) for Thomas. `--session` attaches a session ID for potential resume. `--priority=low|med|high` sets urgency.

**Origin:** wasteland-orchestrator, `~/.claude/bin/pinboard`
**Storage:** `~/.claude/pinboard.json`

### Agent Status
Real-time status reporting system. Every agent writes its current state to a JSON file, visible on the dashboard. States:

| State | Meaning | Future HQ Visual |
|-------|---------|-------------------|
| `idle` | No active task | Agent in lounge |
| `working` | Actively on a task | Agent at desk, typing |
| `reviewing` | Reviewing code/PR | Agent at review station |
| `brainstorming` | Design/brainstorm session | Agent at whiteboard |
| `meeting` | Meeting scribe is live | Agent in meeting room |
| `blocked` | Waiting on dependency/human | Agent pacing |
| `starting` | Session initializing | Agent walking in |
| `stopping` | Session ending | Agent walking out |

**Origin:** wasteland-orchestrator, agent-status.sh
**Storage:** `~/.claude/agents/status/{agent-name}.json`

### Heartbeat
Periodic timestamp update in an agent's status file, used to detect stale (crashed/abandoned) sessions. A status with no heartbeat in 5 minutes is flagged as stale.

### Worktree Isolation
Mandatory practice: all agent dev work happens in git worktrees, never in the main working directory. Each task gets its own worktree branched from `_dev`, ensuring agents never interfere with each other's work or with the main checkout.

```bash
git worktree add .worktrees/issue-17-skeleton -b feat/issue-17-skeleton origin/_dev
```

**Origin:** wasteland-orchestrator, agent protocol
**Enforced by:** PreToolUse hooks warn agents working in the main tree

### Dispatch
System for launching sub-agents as independent processes. Uses a file-based message queue to avoid nested Claude instance depth limits. A dispatching agent writes a task JSON to `queue/`, a daemon picks it up, spawns a fresh Claude CLI instance, and writes the result to `results/`.

**Task lifecycle:** queued → active → done
**Max dispatch depth:** 3 (prevents runaway recursion)
**Priority levels:** normal, high, critical

**Origin:** wasteland-orchestrator, dispatch.sh
**Storage:** `~/.claude/dispatch/{queue,active,done,results}/`

### Gitea API Helpers
Shared shell library (`gitea-api.sh`) wrapping all Gitea REST API calls. Agents must never use raw `curl` to Gitea — the library handles dual-auth (Caddy basic auth + Gitea API token), temp-file JSON bodies, and centralized URL/token management.

**Functions:** `gitea_get`, `gitea_post`, `gitea_patch`, `gitea_put`, `gitea_delete`, `gitea_create_issue`

**Origin:** wasteland-orchestrator, gitea-api.sh

### Briefing
Auto-generated session context provided to agents at startup. Includes recent activity, active pins, and relevant project state. Delivered by the spawn script before the agent's Claude session begins.

### claude-review
GitHub Actions workflow that runs automated code review on PRs. Deployed across all active repositories. Agents create PRs, wait for claude-review to complete, address any comments, and iterate until review passes.

---

## Agent System

### Agent Protocol
Mandatory startup and operational conventions for all agents. Includes: source status/gitea/tx libraries → set agent name → report idle → read pinboard → wrap work in transactions → update persona file with learnings → clear status on exit.

**Origin:** wasteland-orchestrator, `skills/agent-protocol/agent-protocol.md`
**Enforced by:** Hooks verify compliance

### Persona File
Agent identity and memory document at `~/.claude/agents/CLAUDE.{name}.md`. Contains the agent's role definition, character bio, working style, performance log, learnings, and project-specific knowledge. Updated by the agent at end of each session — this is how institutional knowledge accumulates across sessions.

### WOW (WastelandWares Orchestration Workflow)
The end-to-end pipeline for how work flows through the agent system: intake → triage → phase planning → dispatch → implementation → review → merge → docs → release. Named to capture the full orchestration lifecycle.

### HitL (Human in the Loop)
Thomas's role in the agent system. Agents operate autonomously but specific actions require human involvement:
- Release merges (`_dev` → `main`)
- Decisions flagged with `--needs-human` on pinboard
- Architectural choices and product direction
- Security-sensitive operations gated by claude-gate

### Chain of Command
```
Thomas / contributors
    → Project Manager (Elara)
        → Dev Team Lead (per project)
            → Dev Agents, Test Agent, UI/UX Agent
        → Documentation Agent
        → claude-review (automated)
```

### Agent Personas

| Name | Role | Scope |
|------|------|-------|
| **Elara** | Project Manager | Cross-project intake, triage, phase planning, backlog management |
| **Vex** | Security Reviewer | Security audits, threat modeling, credential hygiene |
| **Glitch** | Mobile Tester | Mobile app testing, device compatibility, edge cases |
| **Havoc** | Red Panda Adversary | Security vulnerability discovery — `havoc:` commits with proof (tests, scripts, docs). Findings published after set time (zero-day style disclosure). Treated as critical issues. |
| **Pixel** | Mobile UX | Mobile UI/UX design, accessibility, interaction patterns |
| **Sigil** | Brand Designer | Visual identity, style guides, marketing assets |
| **Dev Team Lead** | Phase Coordinator | Per-project implementation, agent dispatch, review cycle |
| **Documentation Agent** | Docs Keeper | Changelog, README, CLAUDE.md reconciliation, end-of-phase docs |

---

## Security & Policy (Opacity as Policy)

> Concepts from Thomas Quick's white paper: *"Opacity as Policy: Static Undecidability as a Security Primitive for Agentic Shell Execution"* (March 2026, draft). Related projects: **claude-gate**, **zsh-redact-history**.

### OaP (Opacity as Policy)
The principle that a command's resistance to static analysis is itself a first-class policy signal for denial. If a command resists decomposition into verified primitive operations, that resistance is sufficient grounds for automatic denial — without user escalation, and without further analysis. The burden of legibility falls on the command generator (the agent), not the command validator.

**Key insight:** OaP inverts the conventional relationship between analyzer capability and security coverage. Rather than building ever-more-sophisticated analyzers, OaP treats unanalyzability as the answer, not the problem.

**Origin:** Thomas Quick, opacity_as_policy_v2.docx (March 2026)

### Opacity
The degree to which a command's runtime effects cannot be determined by static analysis of its syntax. Formally: given a command string *c* and a static analyzer *A*, the opacity of *c* under *A* is the complement of *A*'s coverage — the set of possible runtime effects not captured in *A(c)*.

Opacity is deliberately **analyzer-relative**. A more sophisticated analyzer classifies fewer commands as opaque. OaP does not require a maximally powerful analyzer; it requires a **reference analyzer** whose coverage boundary defines the policy.

### TRANSPARENT / TRANSLUCENT / OPAQUE
Three-level command classification hierarchy under OaP:

| Classification | Definition | Policy Response |
|---------------|------------|-----------------|
| **TRANSPARENT** | All operations statically determinable. Every AST node resolves to a known primitive with known arguments. | Auto-approve against allowlist |
| **TRANSLUCENT** | Most operations determinable; residual opacity is bounded and low-risk (e.g., variable expansion within a known-safe template). | Auto-approve with logging |
| **OPAQUE** | Significant operations undeterminable. Includes `eval`, dynamic binary names, encoded payloads, nested command substitution. | **Automatic denial. No user prompt.** |

**Examples:**
```bash
# TRANSPARENT — fully decomposable
echo "hello" > output.txt

# TRANSLUCENT — bounded residual opacity
grep -r "TODO" $PROJECT_DIR

# OPAQUE — undeterminable, denied without escalation
eval $(echo -n 'cm0gLXJmIC8=' | base64 -d)
```

### Terminal Denial
OaP's policy that OPAQUE commands are denied without escalation to the human. This is distinct from conventional default-deny, which would ask the human to decide. Terminal denial eliminates the rubber-stamping failure mode — a human presented with `eval $(base64 -d ...)` will either rubber-stamp it (defeating security), manually decode it (doesn't scale), or deny it (what OaP does automatically).

### Asymmetric Trust Tiers
Agents and humans receive different levels of analysis and trust:
- **Agents** → Tier 1 only (static analysis). Must produce legible commands. OPAQUE = denied.
- **Humans** → Tier 1 + Tier 2 (static analysis + simulated execution). May use complex constructs with pre-execution visibility.

This reflects differing trust models: agents are high-speed, low-trust, and capable of reformulation. Humans are low-speed, high-trust, and may have legitimate reasons for complex shell constructs.

### Expressive Equivalence
The claim that for the practical set of operations agents perform, every opaque formulation has a transparent equivalent. An agent that needs to create a file can emit `echo content > file.txt` rather than constructing the command through variable concatenation. This is analogous to how a C compiler doesn't need inline assembly for the vast majority of programs.

**Implication:** When an agent reaches for opaque constructs, that signals something unusual — and in a security context, "unusual" warrants denial, not curiosity.

### Reference Analyzer
The static analyzer whose coverage boundary defines the OaP policy. Commands inside the boundary are legible; commands outside are not. The policy attaches to the boundary, not to any particular analyzer's implementation. Practical implementations use AST-based parsing (e.g., via `shfmt` or `tree-sitter-bash`).

### Security Plane
Not a boundary or perimeter (those imply you can draw a line between "inside" and "outside"). A **plane** — a continuous surface where every point is a potential attack/defense interaction. Captures the topology of the problem: there is no "inside" and "outside," only regions of relative opacity and transparency.

The security plane concept explicitly rejects **complacency language** — terms like "air-gapped," "firewalled," and "sandboxed" that create false confidence by implying binary safe/unsafe states. Opacity is a *spectrum*, not a boolean.

**Origin:** Thomas Quick, Gitea issue comment (wasteland-orchestrator #36)

### Complacency Language
Terms like "air-gapped," "firewalled," "sandboxed" that imply binary security states (safe/unsafe) when the reality is a gradient. OaP explicitly rejects this framing — the policy response is calibrated to the *degree* of opacity rather than a claimed security state. Language that makes you feel safe is often language that makes you unsafe.

### Gate → Audit → Undo Triad
The complete lifecycle that three WastelandWares systems form together, each operating on the security plane at a different phase:

| Phase | System | Function |
|-------|--------|----------|
| **Pre-execution** | OaP / claude-gate | Gates commands by opacity classification |
| **During execution** | Transactions (tx) | Audits intent, actions, and outcomes |
| **Post-execution** | Rollback layers | Enables reversal of changes |

This is the unifying philosophy behind the WastelandWares security tooling. Each component addresses a different temporal phase of the same security surface.

### Two-Tier Verification Architecture
OaP's proposed verification system:
- **Tier 1 (Static Decomposition):** Command is parsed into an AST, walked to produce an intermediate representation of primitive operations (EXEC, READ, WRITE, PIPE, REDIRECT, etc.), and classified against an allowlist. Available to agents and humans.
- **Tier 2 (Simulated Execution):** Command is run against a consequence-free environment (in-memory virtual filesystem, null network layer, simulated process table). Available to humans only.

### Session-Level Effect Accumulator
A Tier 1 extension that tracks the cumulative predicted effects of approved commands across a session. Detects multi-step attack patterns where individually transparent commands compose into harmful sequences (e.g., `curl URL > payload && chmod +x payload && ./payload`).

---

## Business & Product

### WastelandWares
The umbrella brand for all projects in the ecosystem. Evokes post-apocalyptic resourcefulness — building useful things from whatever is available.

**Domain:** wastelandwares.com

**Live services:**
- `git.wastelandwares.com` — Gitea (issue tracking, mirrors)
- `dungeoncrawler.wastelandwares.com` — Dungeon crawler game
- `dev.dungeoncrawler.wastelandwares.com` — Dev preview builds
- `papers.wastelandwares.com` — Whitepapers (OaP, etc.)
- `turtles.wastelandwares.com` — Dev preview (legacy)

**Coming soon:**
- `hq.wastelandwares.com` — HQ dashboard
- `thomas.wastelandwares.com` — Personal/portfolio

### Projects

| Project | Description |
|---------|-------------|
| **wasteland-orchestrator** | Claude Code plugin for multi-agent orchestration — hooks, libs, skills, commands |
| **claude-gate** | Biometric permission gating for Claude Code — macOS native app with rule engine |
| **meeting-scribe** | Live meeting transcription with AI assistant — Python server + Obsidian plugin |
| **wasteland-infra** | Infrastructure-as-code for all wastelandwares.com services |
| **wasteland-hq** | Game-like dev operations dashboard — watch AI agents work in real-time |
| **dnd-tools** | D&D dungeon crawler web game |
| **neuroscript-rs** | Neural architecture composition language in Rust |
| **JARLF** | Just a Really Long Finger — Android biometric auth bridged to macOS (commercial) |

### JARLF (Just a Really Long Finger)
Commercial product: Android biometric authentication bridged to macOS + remote script execution. DroidID replacement. Multi-repo architecture (jarlf-host, jarlf-mobile, jarlf-core, jarlf-server, jarlf-docs).

**Business model:** $25, 10-day free trial, license keys outside app stores, 3rd party payment processor.

---

## Acronyms

| Acronym | Expansion | Context |
|---------|-----------|---------|
| **WOW** | WastelandWares Orchestration Workflow | The end-to-end agent pipeline |
| **HitL** | Human in the Loop | Thomas's supervisory role |
| **OaP** | Opacity as Policy | Security principle from Thomas's white paper |
| **tx** | Transaction | Auditable work unit with intent |
| **btw** | By The Way | Non-interrupting message queue for cook mode |
| **PR** | Pull Request | Code review unit on GitHub |
| **AST** | Abstract Syntax Tree | Used in OaP command parsing |
| **IR** | Intermediate Representation | Tier 1 primitive operations decomposition |
| **IaC** | Infrastructure as Code | wasteland-infra approach |
| **MCP** | Model Context Protocol | Tool integration standard |
| **JARLF** | Just a Really Long Finger | Android→macOS biometric bridge product |
| **PM** | Project Manager | Elara's role |
| **SDK** | Software Development Kit | Claude Agent SDK |
| **CI/CD** | Continuous Integration / Continuous Deployment | GitHub Actions + Gitea runners |

---

## Contributing to This Document

When introducing new terminology:
1. Add it to the appropriate domain section
2. Include a clear definition, origin note, and any relevant storage paths or CLI references
3. Add acronyms to the acronyms table
4. Keep definitions precise but accessible — assume the reader is a new contributor or agent being onboarded
