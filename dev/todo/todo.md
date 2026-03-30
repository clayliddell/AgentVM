# AgentVM Kanban Guide

## Overview

All tasks are tracked on the **VibeKanban board**. The phase files (`PHASE1.md` through `PHASE7.md`) define requirements, functional requirements (FRs), and E2E tests — they serve as the source of truth for *what* needs to be built. The Kanban board tracks *when* and *by whom* work is done.

**Do not edit task status in the phase files.** Use VibeKanban exclusively for task tracking.

## How to Use

1. Open the VibeKanban board and filter by the current phase.
2. Find tasks with no blocking dependencies (blocking relationships are shown on the board).
3. Claim a task by assigning it to yourself and moving it to `In Progress`.
4. When complete, move to `Ready for Review`.
5. After review passes, move to `Done`.

**Before starting any task:**
- Read the corresponding LLD document section (linked in each issue description).
- Check blocking relationships on VibeKanban — do not start a task if its blockers are not `Done`.
- Refer to the phase file for detailed requirements, FRs, and E2E test acceptance criteria.

## Phase Files

Phase files remain the authoritative source for:
- Functional requirements (FRs)
- E2E test acceptance criteria
- Phase completion gates

| Phase | Goal | Week |
|-------|------|------|
| [PHASE1](PHASE1.md) | Foundation — core components functional in isolation | 1–2 |
| [PHASE2](PHASE2.md) | Session Model + Auth Proxy — session abstraction and proxy lifecycle | 2–3 |
| [PHASE3](PHASE3.md) | API + CLI — REST API and CLI for all operations | 3–4 |
| [PHASE4](PHASE4.md) | Network Isolation + Policy — three network modes with runtime control | 4–5 |
| [PHASE5](PHASE5.md) | Resource Enforcement + Shared Folder — cgroups and shared folder driver | 5–6 |
| [PHASE6](PHASE6.md) | Observability + Security — audit, metrics, health, hardening | 6–7 |
| [PHASE7](PHASE7.md) | Orchestrator Adapter + Production — resume, TTL, orchestrator protocol | 7–8 |

## Column Definitions

| Column | Description |
|--------|-------------|
| **Title** | Short identifier for the task. Format: `<Component>.<method_or_feature>` |
| **Description** | What must be implemented. References the LLD section. |
| **Priority** | `Low` — can defer without blocking other work. `Medium` — should complete in phase. `High` — blocks other tasks or is on critical path. |
| **Status** | Current state of the task (see below). |

## Valid Status Values

| Status | Meaning |
|--------|---------|
| `To Do` | LLD reviewed, no blockers, available to claim. |
| `In Progress` | Actively being worked on. Only one agent should claim a task at a time. |
| `Ready for Review` | Implementation complete, awaiting code review or test verification. |
| `Done` | Reviewed, tested, and merged. |

## Blocking Relationships

Blocking relationships are represented directly on VibeKanban via issue links. A task with blocking dependencies cannot be started until all blockers are marked `Done`.

To view blockers for a task:
1. Open the issue on VibeKanban.
2. Check for `blocking` relationship links — these are tasks that must complete first.

## Phase Completion

A phase is **COMPLETE** when:
1. All tasks on VibeKanban for that phase are marked `Done`.
2. All functional requirements (FRs) at the bottom of the phase file are verified.
3. All E2E tests listed at the bottom of the phase file are passing.

Mark phases complete below as they pass all gates:

- [ ] **Phase 1: Foundation** — VM lifecycle, bridge networking, metadata, host capacity, storage, config, daemon startup
- [ ] **Phase 2: Session Model + Auth Proxy** — Session state machine, atomic create/destroy, auth proxy forwarding, ownership enforcement
- [ ] **Phase 3: API + CLI** — REST API endpoints, authentication, CLI commands, OpenAPI docs
- [ ] **Phase 4: Network Isolation + Policy** — Three network modes, runtime domain control, dnsmasq filtering, rate limiting
- [ ] **Phase 5: Resource Enforcement + Shared Folder** — cgroup limits, CPU pinning, shared folder driver selection
- [ ] **Phase 6: Observability + Security** — Audit trail, Prometheus metrics, health checks, serial console, hardening, red-team validation
- [ ] **Phase 7: Orchestrator Adapter + Production** — Session shutdown/resume, TTL enforcement, orchestrator protocol, image management, schema migrations

## Status Transitions

```
To Do → In Progress → Ready for Review → Done
```

- Do not start work on a task with unresolved blockers — check VibeKanban issue links.
- Never skip `Ready for Review` — all tasks must be reviewed before `Done`.
