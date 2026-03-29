# Host Manager — Low-Level Design

## Component Name: Host Manager

The Host Manager provides host-level resource management: capacity checking, CPU topology mapping and pinning, cgroups v2 enforcement for VM processes, and host security hardening verification. It is the component that ensures the host machine remains stable and secure regardless of VM workload.

**Source files:** `src/agentvm/host/capacity.py`, `src/agentvm/host/cgroups.py`, `src/agentvm/host/hardening.py`, `src/agentvm/host/cpu_map.py`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| HM-FR-01 | Detect total and available host resources: CPU cores, memory, disk space | 5.1, 11.2 |
| HM-FR-02 | Subtract reserved resources (configurable `reserved_cores`, `reserved_memory_mb`) from available capacity | 14 |
| HM-FR-03 | Subtract allocated VM resources from available capacity | 5.1 |
| HM-FR-04 | Check if a requested spec fits within available capacity before session creation | 5.1 |
| HM-FR-05 | Detect host CPU topology: core count, NUMA nodes, hyper-threading pairs | 10 |
| HM-FR-06 | Allocate CPU cores for pinning, excluding reserved cores and already-pinned cores | 10 |
| HM-FR-07 | Create cgroup scopes for each VM under `/sys/fs/cgroup/agentvm.slice/vm-{uuid}.scope/` | 10 |
| HM-FR-08 | Apply CPU limits to cgroup: cpuset.cpus, cpuset.mems, cpu.max | 10 |
| HM-FR-09 | Apply memory limits to cgroup: memory.max, memory.high | 10 |
| HM-FR-10 | Apply I/O throttle to cgroup: io.max | 10 |
| HM-FR-11 | Apply PID limit to cgroup: pids.max | 10 |
| HM-FR-12 | Read cgroup usage stats for metrics: cpu.stat, memory.current, io.stat | 10 |
| HM-FR-13 | Clean up cgroup scope on VM destroy | 10 |
| HM-FR-14 | Detect nested virtualization support (kvm_intel_nested / kvm_amd_nested) | 8 |
| HM-FR-15 | Verify host hardening checklist on daemon startup: sysctl params, SELinux, services, firewall, SSH, filesystem | 4.4 |
| HM-FR-16 | Report host health: KVM available, libvirtd running, disk/memory not exhausted | 5.7 |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| HM-NFR-01 | Capacity check must complete within 100ms | Performance |
| HM-NFR-02 | cgroup setup must complete within 500ms | Performance |
| HM-NFR-03 | Unit test coverage ≥80% for capacity and cgroup modules | 12.1 |
| HM-NFR-04 | Host hardening check must not modify system state — read-only verification | Safety |
| HM-NFR-05 | CPU pinning must avoid hyper-threading siblings of reserved cores | Correctness |

---

## 3. Component API Contracts

### 3.1 Capacity

```python
from dataclasses import dataclass

@dataclass
class HostCapacity:
    total_cpu: int
    available_cpu: int
    total_memory_mb: int
    available_memory_mb: int
    total_disk_gb: int
    available_disk_gb: int
    active_vm_count: int
    max_vm_count: int

class CapacityManager:
    def get_capacity(self) -> HostCapacity:
        """Return current host resource availability."""

    def check_spec(self, cpu_cores: int, memory_mb: int, disk_gb: int) -> CapacityCheckResult:
        """Check if requested spec fits within available capacity."""

    def allocate(self, vm_id: str, cpu_cores: int, memory_mb: int, disk_gb: int) -> None:
        """Record resource allocation (decrement available)."""

    def release(self, vm_id: str) -> None:
        """Release resource allocation (increment available)."""
```

### 3.2 CPU Map

```python
@dataclass
class CPUTopology:
    total_cores: int
    cores_per_socket: int
    numa_nodes: int
    cores_per_numa: list[int]            # cores in each NUMA node
    hyperthread_pairs: dict[int, int]    # {core: sibling_core}

class CPUMapManager:
    def get_topology(self) -> CPUTopology:
        """Read CPU topology from /sys/devices/system/cpu/ and /sys/devices/system/node/."""

    def allocate_cores(self, count: int, reserved: list[int],
                       already_allocated: list[int]) -> tuple[str, int]:
        """Allocate `count` cores, avoiding reserved and already-allocated. Returns (cpuset_str, numa_node)."""

    def release_cores(self, cores: list[int]) -> None:
        """Mark cores as available."""
```

### 3.3 cgroups

```python
class CGroupManager:
    CGROUP_BASE = "/sys/fs/cgroup/agentvm.slice"

    def create_scope(self, vm_id: str, qemu_pid: int) -> str:
        """Create cgroup scope, move QEMU PID into it. Returns cgroup path."""

    def set_cpu_limits(self, vm_id: str, cpu_max_period: int, cpu_max_quota: int,
                       cpuset_cpus: str, cpuset_mems: str) -> None:
        """Set CPU limits on VM cgroup."""

    def set_memory_limits(self, vm_id: str, memory_max: int, memory_high: int) -> None:
        """Set memory hard and soft limits (bytes)."""

    def set_io_limits(self, vm_id: str, device: str, rbps: int, wbps: int) -> None:
        """Set I/O throttle limits."""

    def set_pid_limit(self, vm_id: str, max_pids: int) -> None:
        """Set PID limit."""

    def read_usage(self, vm_id: str) -> dict:
        """Read cgroup usage stats: cpu.stat, memory.current, io.stat."""

    def destroy_scope(self, vm_id: str) -> None:
        """Kill all processes in scope, remove cgroup directory."""
```

### 3.4 Hardening

```python
@dataclass
class HardeningReport:
    passed: bool
    checks: dict[str, bool]            # {"sysctl.kptr_restrict": True, ...}
    warnings: list[str]
    failures: list[str]

class HardeningChecker:
    def verify(self) -> HardeningReport:
        """Run all hardening checks from HLD Section 4.4. Read-only, no modifications."""

    def verify_sysctl(self) -> dict[str, bool]:
        """Check kernel parameters."""

    def verify_selinux(self) -> bool:
        """Check SELinux is enforcing."""

    def verify_services(self) -> dict[str, bool]:
        """Check required services enabled, unnecessary services disabled."""

    def verify_firewall(self) -> bool:
        """Check firewall has default deny inbound."""

    def verify_ssh(self) -> dict[str, bool]:
        """Check SSH hardening."""

    def verify_filesystem(self) -> dict[str, bool]:
        """Check filesystem mount options."""
```

### 3.5 Dependencies

| Component This Depends On | Purpose |
|---|---|
| **Config** | Reserved cores, reserved memory, max VMs, storage paths |
| **Metadata Store** | Query active VMs for capacity calculation |

| Components That Call This | Purpose |
|---|---|
| **VM Manager** | Capacity check before VM create, CPU pinning allocation, cgroup setup after VM start |
| **Session Manager** | Capacity check before session create |
| **Orchestrator Adapter** | Capacity info for capabilities report, nested virt detection |
| **Observability** | Host health checks, host-level metrics |
| **REST API** | `/capacity`, `/health` endpoints |

---

## 4. Implementation Plan (Mapped to HLD Phases)

### Phase 1: Foundation (Week 1-2)

**Phase Goal:** Host can be checked for prerequisites and capacity.

**User Stories & Tasks:**

* **Story:** As a developer, I can detect host CPU topology and nested virt support.
  * **Task:** Implement `cpu_map.py` — read `/sys/devices/system/cpu/cpu*/topology/` for core relationships, `/sys/devices/system/node/node*/cpulist` for NUMA layout, `/sys/module/kvm_intel/parameters/nested` or `/sys/module/kvm_amd/parameters/nested` for nested virt. Return `CPUTopology`.
    * *Identified Blockers/Dependencies:* None.

* **Story:** As a developer, I can check if a requested VM spec fits within host capacity.
  * **Task:** Implement `capacity.py` — `get_capacity()` reads `/proc/cpuinfo` (core count minus reserved), `/proc/meminfo` (total minus reserved minus allocated), `os.statvfs()` (disk). `check_spec()` compares requested against available. Track allocations in-memory.
    * *Identified Blockers/Dependencies:* Config (reserved resources).
  * **Task:** Implement `reconcile_allocations()` — called on daemon startup. Queries metadata store for all active VMs, rebuilds in-memory allocation state from their resource records. Ensures capacity tracking is correct after a daemon restart where in-memory state was lost.
    * *Identified Blockers/Dependencies:* Metadata store must be initialized, `get_vms()` with status filter.

---

### Phase 5: Resource Enforcement + Shared Folder (Week 5-6)

**Phase Goal:** cgroups v2 enforce VM resource limits.

**User Stories & Tasks:**

* **Story:** As a platform operator, each VM's QEMU process is placed in a constrained cgroup scope.
  * **Task:** Implement `cgroups.py` — `create_scope(vm_id, qemu_pid)`:
    1. Create `/sys/fs/cgroup/agentvm.slice/vm-{uuid}.scope/` (mkdir).
    2. Write QEMU PID to `cgroup.procs`.
    3. Return cgroup path for metadata storage.
    * *Identified Blockers/Dependencies:* VM Manager must provide QEMU PID.
  * **Task:** Implement `set_cpu_limits()` — write to cpuset.cpus, cpuset.mems, cpu.max.
  * **Task:** Implement `set_memory_limits()` — write to memory.max, memory.high.
  * **Task:** Implement `set_io_limits()` — write to io.max.
  * **Task:** Implement `set_pid_limit()` — write to pids.max.
  * **Task:** Implement `read_usage()` — read cpu.stat, memory.current, io.stat.
  * **Task:** Implement `destroy_scope()` — write "1" to cgroup.kill, rmdir scope directory.
    * *Identified Blockers/Dependencies:* cgroups v2 mounted at `/sys/fs/cgroup/`.

* **Story:** As a platform operator, CPU cores are pinned to VMs without overlap.
  * **Task:** Implement `CPUMapManager.allocate_cores(count, reserved, already_allocated)`:
    1. Get topology.
    2. Filter out reserved cores and their hyper-thread siblings.
    3. Filter out already-allocated cores.
    4. Prefer cores from the same NUMA node.
    5. Return cpuset string (e.g., "4-7") and NUMA node.
    * *Identified Blockers/Dependencies:* `get_topology()`.

* **Story:** As a developer, I have integration tests for resource enforcement.
  * **Task:** Implement `test_resource_limits.py` — create VM with limits, run `stress-ng` inside, verify cgroup stats show limits are enforced and VM does not exceed allocation.
    * *Identified Blockers/Dependencies:* VM Manager, SSH access to VM.

---

### Phase 6: Observability + Security (Week 6-7)

**Phase Goal:** Host hardening is verified on startup.

**User Stories & Tasks:**

* **Story:** As a platform operator, host hardening is verified on daemon startup.
  * **Task:** Implement `hardening.py` — `verify()` runs all checks from HLD Section 4.4:
    - Sysctl: read each parameter from `/proc/sys/`, compare against expected values.
    - SELinux: read `/sys/fs/selinux/enforce`, verify returns `1`.
    - Services: check systemctl status of required/disabled services.
    - Firewall: check iptables default policy is DROP for INPUT chain.
    - SSH: read `/etc/ssh/sshd_config`, verify `PermitRootLogin no`, `PasswordAuthentication no`.
    - Filesystem: check `/var/lib/agentvm` mount options via `/proc/mounts`.
    Return `HardeningReport`.
    * *Identified Blockers/Dependencies:* None.
  * **Task:** Integrate hardening check into daemon startup — log warnings for non-critical failures, log errors and optionally refuse to start for critical failures (SELinux disabled).
    * *Identified Blockers/Dependencies:* Config (expected values), daemon startup flow.

---

## 5. Error Handling

| Error Condition | Handling |
|---|---|
| `/dev/kvm` not available | Return `supports_kvm=False`, VMs run without KVM (slower, nested virt impossible) |
| cgroup v2 not mounted | Fatal error — refuse to start |
| Insufficient capacity | Return `CapacityCheckResult.sufficient=False` with shortfall description |
| cgroup write failure (permission denied) | Log error, raise `CGroupError` |
| CPU topology detection failure | Fall back to sequential core allocation |
| Hardening check: SELinux not enforcing | Log critical warning, optionally refuse to start |
| Hardening check: sysctl mismatch | Log warning, apply sysctl if configured to auto-fix |
