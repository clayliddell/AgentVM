# Observability — Low-Level Design

## Component Name: Observability

The Observability component provides unified audit logging, structured logging, Prometheus metrics export, and health checks. It ensures all platform events are captured in a format compatible with the orchestrator's audit stream.

**Source files:** `src/agentvm/observe/metrics.py`, `src/agentvm/observe/logging_cfg.py`, `src/agentvm/observe/audit.py`, `src/agentvm/observe/health.py`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| OB-FR-01 | Emit audit events in a unified format compatible with both AgentVM and clampdown backends | 5.7, 11.4 |
| OB-FR-02 | Support shared event types: `session.start`, `session.stop`, `session.error`, `network.allow`, `network.block`, `network.reset`, `proxy.request`, `proxy.error`, `resource.limit_hit`, `shared_folder.mount`, `shared_folder.unmount` | 5.7 |
| OB-FR-03 | Support AgentVM-specific event types: `vm.create`, `vm.boot`, `vm.shutdown`, `vm.crash`, `vm.qemu_exit`, `vm.console_line`, `vm.disk_create`, `vm.disk_delete`, `vm.cgroup_limit_hit`, `proxy.start`, `proxy.stop` | 5.7 |
| OB-FR-04 | Persist all audit events to the `audit_log` metadata store table | 5.6, 5.7 |
| OB-FR-05 | Append audit events to an on-disk log file (`/var/lib/agentvm/logs/audit.log`) in structured JSON format | 5.7, 14 |
| OB-FR-06 | Export Prometheus-format metrics on a configurable port (default 9091) | 5.7, 14 |
| OB-FR-07 | Export per-session metrics: CPU usage %, memory used, disk reads/writes, net RX/TX bytes, VM state, proxy req/s, proxy errors | 5.7 |
| OB-FR-08 | Export host-level metrics: total CPU %, total RAM %, disk usage %, VM count, network flow | 5.7 |
| OB-FR-09 | Provide health checks: VM boot detection (SSH reachability), proxy health (HTTP probe), shared folder accessible, host health dashboard, resource exhaustion alerts | 5.7 |
| OB-FR-10 | Capture VM serial console output to per-VM log files | 5.7 |
| OB-FR-11 | Configure structured JSON logging via `structlog` with configurable log level | 14, 17 |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| OB-NFR-01 | Audit event emission must not block the calling component (async or fire-and-forget) | Performance |
| OB-NFR-02 | Metrics endpoint must respond within 500ms | Performance |
| OB-NFR-03 | Unit test coverage ≥80% for audit event formatting and health checks | 12.1 |
| OB-NFR-04 | Audit log must be append-only — no modification or deletion of past events | Security |
| OB-NFR-05 | Metrics collection must not exceed 1% CPU overhead | Performance |

---

## 3. Component API Contracts

### 3.1 Audit

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class AuditEvent:
    timestamp: str                     # ISO 8601
    session_id: Optional[str]          # None for host-level events
    backend: str                       # "agentvm"
    event_type: str                    # See OB-FR-02, OB-FR-03
    actor: str                         # "orchestrator" | "agent" | "system"
    detail: dict                       # Event-specific payload
    ip_address: Optional[str]          # Client IP for API events

class AuditLogger:
    def emit(self, event: AuditEvent) -> None:
        """Emit an audit event — persists to DB and appends to log file."""

    def query(self, session_id: Optional[str] = None,
              since: Optional[str] = None, limit: int = 100) -> list[AuditEvent]:
        """Query audit events from the metadata store."""
```

### 3.2 Metrics

```python
class MetricsCollector:
    def register_session_metrics(self, session_id: str, vm_id: str) -> None:
        """Register a new session's metrics for collection."""

    def unregister_session_metrics(self, session_id: str) -> None:
        """Remove a session's metrics on destroy."""

    def collect(self) -> None:
        """Refresh all metric values from cgroups, libvirt, proxy logs."""

    def start_exporter(self, port: int = 9091) -> None:
        """Start Prometheus HTTP exporter on the given port."""

    def stop_exporter(self) -> None:
        """Stop the Prometheus exporter."""
```

**Prometheus metrics exported:**
```
# Per-session
agentvm_session_cpu_usage_percent{session_id="...", vm_id="..."}
agentvm_session_memory_used_bytes{session_id="..."}
agentvm_session_disk_read_bytes_total{session_id="..."}
agentvm_session_disk_write_bytes_total{session_id="..."}
agentvm_session_net_rx_bytes_total{session_id="..."}
agentvm_session_net_tx_bytes_total{session_id="..."}
agentvm_session_state{session_id="...", state="running"} 1
agentvm_session_proxy_requests_total{session_id="..."}
agentvm_session_proxy_errors_total{session_id="..."}

# Host-level
agentvm_host_cpu_usage_percent
agentvm_host_memory_usage_percent
agentvm_host_disk_usage_percent
agentvm_host_vm_count
agentvm_host_network_rx_bytes_total
agentvm_host_network_tx_bytes_total
```

### 3.3 Health

```python
@dataclass
class HealthStatus:
    healthy: bool
    checks: dict[str, bool]            # {"vm_boot": True, "proxy": True, ...}
    warnings: list[str]
    errors: list[str]

class HealthChecker:
    def check_host_health(self) -> HealthStatus:
        """Check host-level health: KVM available, disk space, memory, libvirtd."""

    def check_session_health(self, session_id: str) -> HealthStatus:
        """Check session-level health: VM booted, proxy responsive, shared folder accessible."""

    def check_resource_alerts(self) -> list[str]:
        """Return warnings if resources exceed 80% utilization."""
```

### 3.4 Logging

```python
def configure_logging(log_level: str = "INFO",
                      audit_log_path: str = "/var/lib/agentvm/logs/audit.log") -> None:
    """Configure structlog with JSON output and log level."""
```

### 3.5 Dependencies

| Component This Depends On | Purpose |
|---|---|
| **Metadata Store** | Audit event persistence (`audit_log` table) |
| **Config** | Metrics port, log level, audit log path, console log dir |
| **Host Manager** | CPU/memory/disk utilization for metrics |
| **Auth Proxy Manager** | Proxy health probe, proxy request log parsing |
| **VM Manager** | VM state for metrics, cgroup path for resource reads |

| Components That Call This | Purpose |
|---|---|
| **All components** | `AuditLogger.emit()` for event logging |
| **REST API** | `/health`, `/metrics`, `/sessions/{sid}/metrics`, `/sessions/{sid}/logs`, `/sessions/{sid}/audit` |
| **CLI** | `agentvm logs`, `agentvm audit`, `agentvm host` |

---

## 4. Implementation Plan (Mapped to HLD Phases)

### Phase 6: Observability + Security (Week 6-7)

**Phase Goal:** Full audit trail, metrics, health checks, and red-team validation.

**User Stories & Tasks:**

* **Story:** As a platform operator, all platform events are captured in a unified audit format.
  * **Task:** Implement `audit.py` — `AuditLogger` class. `emit()` writes to both the `audit_log` metadata table and appends a JSON line to the audit log file. Events are defined as `AuditEvent` dataclass with all fields from HLD Section 5.7.
    * *Identified Blockers/Dependencies:* Metadata Store `insert_audit_event()`.

* **Story:** As a platform operator, I have a Prometheus metrics endpoint.
  * **Task:** Implement `metrics.py` — `MetricsCollector` using the `prometheus_client` library. Register all gauges and counters listed in Section 3.2. `collect()` reads cgroup values for each active VM (CPU from `cpu.stat`, memory from `memory.current`, I/O from `io.stat`), libvirt domain state, and proxy request counts. `start_exporter()` starts an HTTP server on the configured port.
    * *Identified Blockers/Dependencies:* VM Manager (cgroup paths), Auth Proxy Manager (proxy logs), Host Manager (host metrics).

* **Story:** As a platform operator, I can check host and session health.
  * **Task:** Implement `health.py` — `HealthChecker` class:
    - `check_host_health()`: verify `/dev/kvm` exists, libvirtd is running, disk usage <90%, memory usage <90%.
    - `check_session_health(session_id)`: compose three sub-checks (below), aggregate into `HealthStatus`.
    * *Identified Blockers/Dependencies:* VM Manager (SSH info), Auth Proxy Manager (health_check()), Storage Manager (shared folder path).
  * **Task:** Implement sub-check: `check_vm_booted(session_id)` — verify VM is running (via VM Manager `get_vm_status()` or SSH probe). Returns bool.
  * **Task:** Implement sub-check: `check_proxy_responsive(session_id)` — call `AuthProxyManager.health_check()`. Returns bool.
  * **Task:** Implement sub-check: `check_shared_folder_accessible(session_id)` — verify shared folder directory exists and is readable. Returns bool.
  * **Task:** Implement `check_resource_alerts()` — return warnings if any resource exceeds 80% of configured limits (CPU, memory, disk). Separate from health checks.
    * *Identified Blockers/Dependencies:* Config thresholds.

* **Story:** As a platform operator, structured logging is configured with the correct format and level.
  * **Task:** Implement `logging_cfg.py` — configure `structlog` with JSON renderer, add standard fields (timestamp, level, logger name). Support configurable log level from `observability.log_level` config.
    * *Identified Blockers/Dependencies:* Config.

* **Story:** As a platform operator, VM serial console output is captured to per-VM log files (OB-FR-10).
  * **Task:** Implement serial console capture — configure libvirt XML with `<serial type='file'>` pointing to `/var/lib/agentvm/logs/vm-<uuid>/serial.log`. The `<log>` element in the libvirt domain XML captures all serial output. VM Manager's `xml_builder.py` generates this config. Observability reads the log file for the `/sessions/{sid}/logs` endpoint.
    * *Identified Blockers/Dependencies:* VM Manager XML builder, storage directory structure.

* **Story:** As a developer, I have unit tests for audit formatting and health checks.
  * **Task:** Implement `test_audit.py` — test AuditEvent construction and field validation, test emit writes to mock DB and log file.
  * **Task:** Implement health check tests — mock filesystem/cgroup/process state, verify health status computation.
    * *Identified Blockers/Dependencies:* None.

---

## 5. Error Handling

| Error Condition | Handling |
|---|---|
| Audit log file not writable | Log to stderr, continue with DB-only persistence |
| Metadata store unavailable for audit insert | Write to log file only, retry on next event |
| Prometheus port in use | Log error, metrics endpoint unavailable (non-fatal) |
| cgroup read failure (VM process gone) | Mark metric as NaN, emit `vm.crash` audit event |
| Health check timeout | Return unhealthy for that check with timeout message |
