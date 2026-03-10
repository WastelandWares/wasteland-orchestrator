# Tool Axiom Analysis — Phase 1 Results
> Date: 2026-03-10
> Source: 8 Claude Code transcripts, 520 tool calls, 142 Bash commands
> For: Issue #22 (meta-analysis) + Thomas's "Opacity as Policy" whitepaper

## Key Finding

**59% of all atomic operations are fully transparent (reads, searches, navigation).** Only 9.7% are opaque (script execution). This means we're already mostly operating in the transparent zone — the tool redesign should formalize that, not fight it.

## The Problem with Bash

39% of Bash calls contain multiple atomic actions chained with `&&`, `;`, or `|`. Each Bash call is a single "tool invocation" but hides 2-7 actual operations. The worst case was a 53-action Bash call.

Pipes are the most common operator (104 occurrences), meaning data transformation chains are the most frequent multi-action pattern. This makes sense — `cat file | grep X | sort | uniq -c` is four operations pretending to be one.

## Tool Usage Distribution

| Tool | Calls | Share |
|------|-------|-------|
| Read | 144 | 27.7% |
| Bash | 142 | 27.3% |
| Write | 112 | 21.5% |
| Edit | 62 | 11.9% |
| Glob | 20 | 3.8% |
| TodoWrite | 19 | 3.7% |
| Grep | 11 | 2.1% |

Read and Bash are neck and neck. But Read is a single transparent operation, while Bash is a grab-bag of 1-53 operations at varying opacity levels.

## Axiom Taxonomy

### OBSERVE (43% of all operations)
- `read_file` — cat, head, tail, wc
- `read_dir` — ls, tree, du
- `search` — grep, find -name, rg
- `git_read` — git status, log, diff

### ENVIRONMENT (21%)
- `navigate` — cd (14.5% alone!)
- `env_state` — export, source
- `package_mgmt` — brew, pip, npm install

### BUILD (14%)
- `compile_build` — cargo build, npm run build
- `run_test` — cargo test, npm test

### TRANSFORM (8%)
- `transform` — sed, awk, perl, jq, cut, sort, uniq

### MUTATE (4%)
- `create_structure` — mkdir, touch
- `delete` — rm
- `git_write` — git add, commit, push

### OPAQUE (10%)
- `opaque_exec` — ./script.sh, binary execution

## Opacity Distribution

| Level | Label | Count | Share |
|-------|-------|-------|-------|
| 0 | Transparent (reads, search, nav) | 122 | 58.9% |
| 1 | Deterministic (writes, transforms) | 37 | 17.9% |
| 2 | Conditional (build, test) | 28 | 13.5% |
| 3 | Network/inline code | 0 | 0.0% |
| 4 | Fully opaque (scripts, binaries) | 20 | 9.7% |

## Insights for Tool Design

1. **`cd` accounts for 14.5% of all atomic operations.** It's the most common single action. But it's not a *tool* — it's context setup. Tools should accept paths directly rather than requiring navigation.

2. **Pipes (`|`) are the #1 operator (104 uses).** Data transformation chains are the primary use of multi-action Bash. A `Transform` tool with composable stages would replace most pipe chains transparently.

3. **The Read tool already exists and is the most-used tool.** But Bash is used for reads 30 times (cat, head, tail, wc). This means Read doesn't cover all read needs — likely because of line-range selection, word count, or format needs.

4. **Only 4% of operations are mutations.** The vast majority of agent work is *understanding* the codebase, not changing it. Tool design should optimize for the 96%, not the 4%.

5. **Opaque execution is 10% — all script execution.** No curl, no wget, no network calls in these sessions. The opacity risk is entirely in running compiled binaries and shell scripts. This is exactly the undecidability problem from the whitepaper.

## Proposed Axiom Set (Draft)

Based on this data, here's a candidate set of primitive operations:

### Transparent (Level 0)
- `ReadFile(path, range?)` — already exists
- `ReadDir(path, depth?, pattern?)` — ls/tree/glob unified
- `Search(pattern, path?, type?)` — grep/find unified (already have Grep/Glob)
- `GitQuery(repo, op)` — read-only git operations

### Deterministic (Level 1)
- `WriteFile(path, content)` — already exists
- `EditFile(path, changes)` — already exists
- `Transform(input, stages[])` — replaces pipe chains, each stage is named+auditable
- `Manage(op, target)` — mkdir, rm, cp, mv with explicit intent
- `GitMutate(repo, op)` — add, commit, push — each a separate auditable action

### Conditional (Level 2)
- `Build(project, target)` — compile with known toolchain
- `Test(project, scope)` — run tests with known framework
- `Install(package, registry)` — package management

### Opaque (Level 3-4) — requires justification + gate
- `Execute(binary, args, justification)` — any script/binary execution
- `Network(url, method, justification)` — any external call
- `InlineCode(language, code, justification)` — python3 -c, node -e

## Sequence Patterns

Most common tool sequences (what follows what):
- Read → Read (87) — codebase exploration
- Write → Write (84) — file creation bursts
- Bash → Bash (77) — command chains
- Edit → Edit (33) — refactoring
- Bash → Read (32) — run then inspect

The Read→Read and Write→Write bursts suggest agents work in phases: understand, then act. Tool design should support this phase pattern explicitly.

## Next Steps

1. Cross-reference with agent transaction logs for intent correlation
2. Analyze larger dataset (history.jsonl has 4,978 entries with project context)
3. Draft the axiom specification as input to tx v2 (issue #20)
4. Feed opacity data into Thomas's whitepaper
