# Phase 6: Observability + Security

> **Note:** Task tracking has moved to VibeKanban. Do not edit task status in this file.
> Refer to the Kanban board for current status and blocking relationships.
> This file is the source of truth for requirements, FRs, and E2E tests only.
> See `dev/todo/todo.md` for details.

**Goal:** Full audit trail, Prometheus metrics, health checks, serial console capture, host hardening, red-team validation.

**Weeks:** 6–7

---

## VM Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| VMManager.audit_events | Integrate audit event emission into `create_vm()`, `destroy_vm()`, and crash detection paths. Emit: `vm.create`, `vm.boot`, `vm.shutdown`, `vm.crash`, `vm.qemu_exit`, `vm.disk_create`, `vm.disk_delete`. Ref: VM-LLD §9.1 | High | Blocked |
| VMManager.crash_detection | Implement QEMU exit detection — register libvirt domain lifecycle event callback or poll domain state periodically. On unexpected exit: emit `vm.crash`, mark VM as `error` in metadata, trigger cleanup. Ref: VM-LLD §9.2 | High | Blocked |

## Auth Proxy Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| AuthProxy.red_team_tests | Implement red-team tests: `test_escape_proxy.py` (attempt `/proc/<pid>/mem` read — denied), `test_proxy_security.py` (direct upstream access fails, replay with modified headers fails). Ref: AUTH-PROXY-LLD §9.1 | High | Blocked |

## Observability

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| Observability.audit_logger | Implement `audit.py` — `AuditLogger` class. `emit()` writes to `audit_log` metadata table and appends JSON line to audit log file. Ref: OBSERVABILITY-LLD §5.1 | High | Blocked |
| Observability.metrics_collector | Implement `metrics.py` — `MetricsCollector` using `prometheus_client`. Register all gauges/counters. `collect()` reads cgroup values, libvirt domain state, proxy request counts. `start_exporter()` starts HTTP server. Ref: OBSERVABILITY-LLD §5.2 | High | Blocked |
| Observability.health_checker | Implement `health.py` — `HealthChecker` class: `check_host_health()`, `check_session_health(session_id)`. Ref: OBSERVABILITY-LLD §5.3 | High | Blocked |
| Observability.health_vm_booted | Implement sub-check: `check_vm_booted(session_id)` — verify VM is running. Ref: OBSERVABILITY-LLD §5.3 | Medium | Blocked |
| Observability.health_proxy_responsive | Implement sub-check: `check_proxy_responsive(session_id)` — call `AuthProxyManager.health_check()`. Ref: OBSERVABILITY-LLD §5.3 | Medium | Blocked |
| Observability.health_shared_folder | Implement sub-check: `check_shared_folder_accessible(session_id)` — verify shared folder directory exists. Ref: OBSERVABILITY-LLD §5.3 | Medium | Blocked |
| Observability.health_resource_alerts | Implement `check_resource_alerts()` — return warnings if any resource exceeds 80% of configured limits. Ref: OBSERVABILITY-LLD §5.3 | Medium | Blocked |
| Observability.logging_config | Implement `logging_cfg.py` — configure `structlog` with JSON renderer, support configurable log level. Ref: OBSERVABILITY-LLD §5.4 | Medium | Blocked |
| Observability.serial_console_capture | Implement serial console capture (OB-FR-10) — configure libvirt XML `<serial type='file'>` pointing to `/var/lib/agentvm/logs/vm-<uuid>/serial.log`. VM Manager generates XML, Observability reads log file. Ref: OBSERVABILITY-LLD §5.5 | Medium | Blocked |
| Observability.test_audit | Implement `test_audit.py` — test AuditEvent construction, field validation, emit writes to mock DB and log file. Ref: OBSERVABILITY-LLD §5.6 | Medium | Blocked |
| Observability.test_health | Implement health check tests — mock filesystem/cgroup/process state, verify health status computation. Ref: OBSERVABILITY-LLD §5.6 | Medium | Blocked |

## Host Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| HostManager.hardening_verify | Implement `hardening.py` — `verify()` runs all checks from HLD §4.4: sysctl, SELinux, services, firewall, SSH hardening, filesystem mount options. Return `HardeningReport`. Ref: HOST-LLD §9.1 | High | Blocked |
| HostManager.hardening_startup | Integrate hardening check into daemon startup — log warnings for non-critical failures, log errors for critical failures (SELinux disabled). Ref: HOST-LLD §9.2 | Medium | Blocked |

---

## Phase 6 Functional Requirements

| FR | Requirement | Verification |
|----|-------------|-------------|
| P6-FR-01 | All platform events captured in unified audit format — written to both metadata `audit_log` table and JSON log file | `GET /audit` returns events; `cat /var/lib/agentvm/logs/audit.jsonl` shows matching entries |
| P6-FR-02 | VM lifecycle events emitted: `vm.create`, `vm.boot`, `vm.shutdown`, `vm.crash`, `vm.qemu_exit`, `vm.disk_create`, `vm.disk_delete` | Each event appears in audit log after corresponding action |
| P6-FR-03 | Prometheus metrics endpoint exposes all registered gauges and counters | `curl http://localhost:<port>/metrics` returns Prometheus text format with all expected metrics |
| P6-FR-04 | Health checks available for host and per-session: VM booted, proxy responsive, shared folder accessible, resource alerts | `GET /health` returns host health; `GET /sessions/{sid}` includes health fields |
| P6-FR-05 | Resource alerts trigger when any resource exceeds 80% of configured limits | Health check returns warning when CPU > 80%, memory > 80%, etc. |
| P6-FR-06 | Structured logging configured with JSON renderer and configurable log level | Log output is valid JSON; log level matches config |
| P6-FR-07 | VM serial console captured to `/var/lib/agentvm/logs/vm-<uuid>/serial.log` | Serial log file contains VM boot output after VM creation |
| P6-FR-08 | Host hardening verified on daemon startup — sysctl, SELinux, services, firewall, SSH, filesystem mount options | `HardeningReport` generated; critical failures (SELinux disabled) cause startup error |
| P6-FR-09 | Auth proxy immune to key extraction — memory, direct upstream access, and replay attacks all fail | Red-team tests pass: `/proc/<pid>/mem` read denied, direct upstream fails, replay fails |
| P6-FR-10 | QEMU crash detection — unexpected VM exit triggers `vm.crash` audit event, VM marked as `error` in metadata | Kill QEMU process, verify crash event in audit log and VM status is `error` |

## Phase 6 E2E Tests (Must Pass for Phase Completion)

All of the following E2E tests must pass before this phase can be marked COMPLETE:

- [ ] **E2E-6.1: Audit trail** — Create session, allow domain, destroy session — verify `session.create`, `vm.create`, `vm.boot`, `network.allow`, `session.stop`, `vm.shutdown` events all appear in audit log
- [ ] **E2E-6.2: Prometheus metrics** — Create a session, query `/metrics`, verify `agentvm_sessions_total` gauge incremented, `agentvm_vm_cpu_usage_percent` shows value for running VM
- [ ] **E2E-6.3: Health check** — Query `/health`, verify response includes host health status, capacity info, and active session count
- [ ] **E2E-6.4: Session health** — Query `GET /sessions/{sid}`, verify `healthy`, `proxy_healthy`, `cpu_usage_percent`, `memory_used_mb` fields are populated
- [ ] **E2E-6.5: Resource alerts** — Create VM with 1 CPU, run stress test inside to exceed 80% CPU, verify health check returns warning
- [ ] **E2E-6.6: Serial console** — Create VM, wait for boot, read `/var/lib/agentvm/logs/vm-<uuid>/serial.log`, verify boot messages present
- [ ] **E2E-6.7: Host hardening** — Start daemon on hardened host, verify no critical warnings. Start on host with SELinux disabled, verify startup fails with error message
- [ ] **E2E-6.8: Proxy security (red-team)** — Attempt to read proxy memory via `/proc/<pid>/mem` (denied). Attempt direct upstream access without proxy (fails). Attempt request replay with modified headers (fails)
- [ ] **E2E-6.9: Crash detection** — Create session, kill QEMU process, verify `vm.crash` audit event and VM status `error`
