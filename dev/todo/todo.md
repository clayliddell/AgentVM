# AgentVM Kanban Guide

## Overview

Tasks are organized into phase files (`PHASE1.md` through `PHASE7.md`). Each phase corresponds to a development week with a specific goal. Use these files as a Kanban board to track work.

## How to Use

1. Open the phase file for your current sprint.
2. Find tasks with status `Ready for Work` and claim them by updating status to `In Progress`.
3. When complete, update status to `Ready for Review`.
4. After review passes, update status to `Done`.

**Before starting any task:**
- Read the corresponding LLD document section (linked in each table).
- Ensure all predecessor tasks in the same phase are at least `In Progress`.
- Confirm the task is not `Blocked`.

## Column Definitions

| Column | Description |
|--------|-------------|
| **Task Name** | Short identifier for the task. Format: `<Component>.<method_or_feature>` |
| **Task Description** | What must be implemented. References the LLD section. |
| **Priority** | `Low` — can defer without blocking other work. `Medium` — should complete in phase. `High` — blocks other tasks or is on critical path. |
| **Status** | Current state of the task (see below). |

## Valid Status Values

| Status | Meaning |
|--------|---------|
| `Blocked` | Cannot start — dependency not met or external blocker exists. Add a note explaining what is blocking. |
| `Ready for Work` | LLD reviewed, no blockers, available to claim. |
| `In Progress` | Actively being worked on. Only one agent should claim a task at a time. |
| `Ready for Review` | Implementation complete, awaiting code review or test verification. |
| `Done` | Reviewed, tested, and merged. |

## Phase Overview

| Phase | Goal | Week |
|-------|------|------|
| [PHASE1](PHASE1.md) | Foundation — core components functional in isolation | 1–2 |
| [PHASE2](PHASE2.md) | Session Model + Auth Proxy — session abstraction and proxy lifecycle | 2–3 |
| [PHASE3](PHASE3.md) | API + CLI — REST API and CLI for all operations | 3–4 |
| [PHASE4](PHASE4.md) | Network Isolation + Policy — three network modes with runtime control | 4–5 |
| [PHASE5](PHASE5.md) | Resource Enforcement + Shared Folder — cgroups and shared folder driver | 5–6 |
| [PHASE6](PHASE6.md) | Observability + Security — audit, metrics, health, hardening | 6–7 |
| [PHASE7](PHASE7.md) | Orchestrator Adapter + Production — resume, TTL, orchestrator protocol | 7–8 |

## Phase Completion

A phase is **COMPLETE** when:
1. All tasks in the phase are marked `Done`.
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
Ready for Work → In Progress → Ready for Review → Done
                     ↓                ↓
                  Blocked          Blocked
```

- Move to `Blocked` if a dependency is missing. Record the blocker.
- Move back from `Blocked` to `Ready for Work` once the blocker is resolved.
- Never skip `Ready for Review` — all tasks must be reviewed before `Done`.
