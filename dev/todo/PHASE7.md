# Phase 7: Orchestrator Adapter + Production

> **Note:** Task tracking has moved to VibeKanban. Do not edit task status in this file.
> Refer to the Kanban board for current status and blocking relationships.
> This file is the source of truth for requirements, FRs, and E2E tests only.
> See `dev/todo/todo.md` for details.

**Goal:** Session resume/TTL, orchestrator protocol, image management, schema migrations, production hardening.

**Weeks:** 7–8

---

## Session Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| SessionManager.shutdown_session | Implement `shutdown_session()` — stop VM via `soft_shutdown()`, keep proxy/network/shared folder/metadata intact, transition to `shutdown`. Ref: SESSION-LLD §10.1 | High | Blocked |
| SessionManager.resume_session | Implement `resume_session()` — generate new cloud-init ISO (same config), create new VM from existing shared folder, transition back to `running`. Ref: SESSION-LLD §10.1 | High | Blocked |
| SessionManager.resume_ip_preservation | On resume, Network Manager updates iptables with new IP, Auth Proxy Manager updates `vm_ip` and reloads proxy. Session Manager coordinates. Ref: SESSION-LLD §10.1 | High | Blocked |
| SessionManager.ttl_enforcement | Implement TTL check in background task — query metadata store for sessions with `created_at` older than `security.vm_max_lifetime_hours`, initiate destroy for expired sessions. Ref: SESSION-LLD §10.2 | High | Blocked |
| SessionManager.drain_all_sessions | Implement `drain_all_sessions()` — iterate all `running` sessions, destroy each, with configurable timeout per session. Called on daemon SIGTERM. Ref: SESSION-LLD §10.3 | Medium | Blocked |

## Orchestrator Adapter

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| Orchestrator.create_session | Implement `AgentVMBackend.create_session(spec)`: convert `WorkloadSpec` to `SessionCreateRequest`, call `SessionManager.create_session()`, convert to `SessionStatus`. Ref: ORCHESTRATOR-LLD §5.1 | High | Blocked |
| Orchestrator.network_wrappers | Implement `allow_network()`, `block_network()`, `reset_network()`, `get_network_rules()` — thin wrappers around `NetworkPolicyEngine`. Ref: ORCHESTRATOR-LLD §5.2 | Medium | Blocked |
| Orchestrator.inject_secret | Implement `inject_secret(session_id, key, value)` — call `AuthProxyManager.inject_secret()`. Ref: ORCHESTRATOR-LLD §5.3 | Medium | Blocked |
| Orchestrator.capabilities | Implement `capabilities()`: query `HostManager.detect_nested_virt_support()`, `HostManager.get_capacity()`, `StorageManager.list_images()`, read config, return `BackendCapabilities`. Ref: ORCHESTRATOR-LLD §5.4 | Medium | Blocked |
| Orchestrator.test_adapter | Implement `test_orchestrator_adapter.py` — test `WorkloadSpec` → `SessionCreateRequest` conversion, `WorkloadSession` → `SessionStatus` conversion. Ref: ORCHESTRATOR-LLD §5.5 | Medium | Blocked |
| Orchestrator.test_routing | Implement `test_orchestrator_routing.py` — mock orchestrator uses `AgentVMBackend` to create sessions, verify routing logic. Ref: ORCHESTRATOR-LLD §5.5 | Low | Blocked |

## VM Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| VMManager.soft_shutdown | Implement `VMManager.soft_shutdown(vm_id, timeout)` — ACPI shutdown via `domain.shutdown()`, poll up to timeout, fallback to `domain.destroy()`. Emit `vm.shutdown` or `vm.shutdown_timeout`. Ref: VM-LLD §10.1 | High | Blocked |
| VMManager.start_vm | Implement `VMManager.start_vm(vm_id)` — start previously defined but inactive domain via `domain.create()`. For session resume. Ref: VM-LLD §10.2 | High | Blocked |

## Storage Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| StorageManager.upload_image | Implement `upload_image(name, disk_path, metadata)` — copy disk to `base/<name>/disk.qcow2`, write `metadata.json`, set read-only, verify SHA256. Ref: STORAGE-LLD §10.1 | Medium | Blocked |
| StorageManager.delete_image | Implement `delete_image(name)` — check no active VM references via `MetadataStore.get_vms_by_image()`, remove `base/<name>/` directory. Ref: STORAGE-LLD §10.1 | Medium | Blocked |
| StorageManager.list_images | Implement `list_images()` and `get_image(name)` — read `metadata.json` from each `base/<name>/` directory. Ref: STORAGE-LLD §10.1 | Medium | Blocked |
| StorageManager.get_images_by_capability | Implement `get_images_by_capability(capability)` — filter images where capability is in `metadata.capabilities` list. Ref: STORAGE-LLD §10.1 | Low | Blocked |

## Metadata Store

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| MetadataStore.schema_migrations | Implement `migrations.py` — migration framework with version tracking table (`schema_migrations`). Each migration is a function, `run_migrations(target_version)` applies pending migrations in order. Migrations must be idempotent. Ref: METADATA-LLD §10.1 | Medium | Blocked |
| MetadataStore.get_vms_by_image | Implement `get_vms_by_image(image_name)` — query VMs referencing a specific base image. Used by image deletion guard. Ref: METADATA-LLD §10.1 | Low | Blocked |
| MetadataStore.orphan_detection | Implement `get_sessions_by_status_and_age(status, older_than)` — query sessions in `creating` state with `created_at` older than configurable threshold. Used by daemon startup to detect partially-created sessions. Ref: METADATA-LLD §10.2 | Medium | Blocked |

## Config

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| Config.daemon_integration | Integrate config loading into `daemon.py` startup — load config first, pass `AgentVMConfig` instance to all component constructors. Ref: CONFIG-LLD §7.1 | Medium | Blocked |

## Daemon Entrypoint

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| Daemon.reconcile_and_orphans | Implement `reconcile_allocations()` call and orphan cleanup loop — retrieve sessions stuck in `creating` for >5 minutes and destroy them. Ref: DAEMON-LLD §10.1 | Medium | Blocked |

---

## Phase 7 Functional Requirements

| FR | Requirement | Verification |
|----|-------------|-------------|
| P7-FR-01 | Session shutdown preserves metadata, proxy, network rules, and shared folder — only VM stops | After shutdown: VM is gone, proxy running, network rules intact, shared folder exists, metadata status is `shutdown` |
| P7-FR-02 | Session resume creates new VM from existing shared folder, generates new cloud-init, transitions to `running` | After resume: new VM boots, shared folder accessible, status is `running` |
| P7-FR-03 | Resume IP/MAC preservation — Network Manager updates iptables with new IP, Auth Proxy updates `vm_ip` and reloads | After resume: iptables rules reference new VM IP, proxy health check passes |
| P7-FR-04 | Sessions auto-destroy after TTL expires (`security.vm_max_lifetime_hours`) | Background task destroys expired sessions; audit log shows `session.ttl_expired` |
| P7-FR-05 | Daemon graceful shutdown drains all active sessions within configurable timeout | SIGTERM triggers `drain_all_sessions()`; all sessions destroyed before daemon exits |
| P7-FR-06 | Orchestrator adapter implements `IsolationBackend` protocol — `create_session()`, `allow_network()`, `inject_secret()`, `capabilities()` | Mock orchestrator can create and manage sessions through adapter |
| P7-FR-07 | `soft_shutdown()` uses ACPI shutdown with timeout fallback to hard kill | ACPI shutdown triggers graceful VM shutdown; timeout expires → `domain.destroy()`; audit events `vm.shutdown` or `vm.shutdown_timeout` emitted |
| P7-FR-08 | `start_vm()` restarts a previously defined but inactive domain | `domain.create()` succeeds on paused/defined domain; VM boots to `running` state |
| P7-FR-09 | Image management — upload, list, delete, filter by capability | Images stored in `base/<name>/` with `metadata.json`; deletion guarded by `get_vms_by_image()` |
| P7-FR-10 | Schema migrations applied automatically on daemon startup | `schema_migrations` table tracks applied versions; new columns added without data loss |
| P7-FR-11 | Orphan detection on startup — sessions stuck in `creating` >5 minutes are destroyed | Daemon startup detects and destroys orphaned sessions |

## Phase 7 E2E Tests (Must Pass for Phase Completion)

All of the following E2E tests must pass before this phase can be marked COMPLETE:

- [ ] **E2E-7.1: Session shutdown** — Create session, `shutdown_session()`, verify VM is stopped, proxy still running, network rules intact, shared folder exists, status is `shutdown`
- [ ] **E2E-7.2: Session resume** — From shutdown state, `resume_session()`, verify new VM boots, shared folder accessible, status transitions to `running`
- [ ] **E2E-7.3: Resume IP preservation** — After resume, verify iptables rules reference the new VM IP (not old), proxy health check passes, VM can reach allowed domains
- [ ] **E2E-7.4: TTL enforcement** — Create session with short TTL (e.g., 10 seconds), wait, verify session auto-destroyed and `session.ttl_expired` event in audit log
- [ ] **E2E-7.5: Daemon drain** — Create 3 active sessions, send SIGTERM to daemon, verify all 3 sessions destroyed gracefully before daemon exits
- [ ] **E2E-7.6: Orchestrator adapter** — Use mock orchestrator with `AgentVMBackend` to create session, verify `WorkloadSpec` converted to `SessionCreateRequest`, session created, `SessionStatus` returned correctly
- [ ] **E2E-7.7: Soft shutdown** — Create session, call `soft_shutdown()`, verify ACPI shutdown initiated, VM stops within timeout, `vm.shutdown` event emitted
- [ ] **E2E-7.8: Soft shutdown timeout** — Create session with VM that ignores ACPI, call `soft_shutdown(timeout=5)`, verify timeout expires, `domain.destroy()` called, `vm.shutdown_timeout` event emitted
- [ ] **E2E-7.9: Image upload/list/delete** — Upload image, list images (appears), attempt delete while VM uses it (fails), delete VM, delete image (succeeds)
- [ ] **E2E-7.10: Schema migration** — Start daemon with new schema version, verify migration runs, verify `schema_migrations` table updated, verify existing data intact
- [ ] **E2E-7.11: Orphan cleanup** — Simulate daemon crash during session create (session stuck in `creating`), restart daemon, verify orphan session detected and destroyed
