# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Agent Ceremony Automation** — Hooks now automate agent initialization sequence (spawn wrapper, heartbeat setup, status file creation) ([#53](https://github.com/WastelandWares/wasteland-orchestrator/issues/53), [#54](https://github.com/WastelandWares/wasteland-orchestrator/issues/54), [#55](https://github.com/WastelandWares/wasteland-orchestrator/issues/55), [#48](https://github.com/WastelandWares/wasteland-orchestrator/issues/48))
- **Vocabulary Document** — Comprehensive terminology guide for agent protocol and project conventions ([#36](https://github.com/WastelandWares/wasteland-orchestrator/issues/36))
- **Architecture Diagrams** — Visual documentation of agent system flow and transaction lifecycle

### Changed
- **Terminology Update** — Replaced agile terminology across codebase with clearer workflow descriptions ([#52](https://github.com/WastelandWares/wasteland-orchestrator/issues/52))
- **Python Tool Extraction** — Moved inline Python scripts from shell scripts into dedicated `ww-json-tool.py` for better maintainability and testability ([#62](https://github.com/WastelandWares/wasteland-orchestrator/issues/62))

### Removed
- Gitea integration — all Gitea API libraries, hooks, and references removed

## [0.1.0] - 2026-02-28

### Added
- Initial release
- Agent status tracking system with real-time reporting
- Transaction system for auditable action groups
- PreToolUse and PostToolUse hooks for protocol enforcement
- Agent protocol specification
- Dashboard-ready status files and transaction logs

[Unreleased]: https://github.com/WastelandWares/wasteland-orchestrator/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/WastelandWares/wasteland-orchestrator/releases/tag/v0.1.0
