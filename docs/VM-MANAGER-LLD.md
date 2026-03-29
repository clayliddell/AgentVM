# VM Manager — Low-Level Design

## Component Name: VM Manager

The VM Manager is the core component responsible for VM lifecycle operations through libvirt. It wraps all libvirt interactions with security-enforcing logic, manages VM domain definitions, disk overlays, and boot orchestration.

**Source files:** `src/agentvm/vm/manager.py`, `src/agentvm/vm/spec.py`, `src/agentvm/vm/xml_builder.py`, `src/agentvm/vm/state.py`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| VM-FR-01 | Validate VM specification against host capabilities and resource limits before creation | 5.1 |
| VM-FR-02 | Check host capacity (CPU, memory, disk) before allocating resources | 5.1 |
| VM-FR-03 | Create qcow2 COW overlay disk from a read-only base image | 5.1, 5.4.1 |
| VM-FR-04 | Generate libvirt XML domain definition from a VM spec (Section 9 template) | 9 |
| VM-FR-05 | Create VM domain via `conn.createXML()` and wait for boot completion | 5.1 |
| VM-FR-06 | Destroy VM domain (hard kill via `domain.destroy()`) and undefine (remove config) | 5.1 |
| VM-FR-07 | Delete disk overlay and release all associated resources on destroy | 5.1 |
| VM-FR-08 | Query VM state, resource usage, and health via `domain.state()` and cgroup reads | 5.1 |
| VM-FR-09 | List all VMs, filter by owner, enrich with metrics | 5.1 |
| VM-FR-10 | Detect host nested virtualization support (`kvm_intel_nested=1` / `kvm_amd_nested=1`) | 8 |
| VM-FR-11 | Configure CPU pinning to dedicated physical cores based on topology | 10, 5.1 |
| VM-FR-12 | Generate libvirt XML with nested virt CPU features (`vmx`/`svm`, `host-passthrough`) | 8, 9 |
| VM-FR-13 | Record VM metadata to SQLite on create and purge on destroy | 5.1, 5.6 |
| VM-FR-14 | Handle QEMU crash/exit gracefully — detect, log, clean up resources | 5.1 |
| VM-FR-15 | Enforce minimal device model: virtio-only, no USB/audio/video/graphics | 5.1, 9 |
| VM-FR-16 | Support VM max lifetime TTL — auto-destroy after configurable hours | 14, 15 (Phase 7) |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| VM-NFR-01 | VM creation must complete within 15 seconds on a properly configured host | 6.3 (`startup_latency_ms`) |
| VM-NFR-02 | Unit test coverage ≥95% for manager.py (critical path) | 12.1 |
| VM-NFR-03 | All libvirt operations must be atomic where possible — partial failure triggers full rollback | 5.1 |
| VM-NFR-04 | VM XML generation must produce deterministic output for a given spec (testability) | 9 |
| VM-NFR-05 | The VM Manager must not hold libvirt connections across idle periods longer than 30s | Reliability |
| VM-NFR-06 | Destroy operations must complete within 10 seconds regardless of VM state | 5.1 |

---

## 3. Component API Contracts

### 3.1 Inputs (Methods Exposed)

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class VMSpec:
    """VM creation specification."""
    name: str                          # Unique VM name (vm-<uuid>)
    session_id: str                    # Owning session UUID
    base_image: str                    # Base image name (e.g., "ubuntu-24.04-amd64")
    cpu_cores: int                     # Number of vCPUs (1-32)
    memory_mb: int                     # Memory in MiB (512-65536)
    disk_gb: int                       # Disk size in GB (10-200)
    ssh_public_key: str                # SSH public key for cloud-init injection
    bridge_name: str                   # Network bridge to attach to (e.g., "agentvm-br0")
    shared_folder_host_path: str       # Host path for shared folder mount
    cloud_init_iso: str                # Path to generated cloud-init ISO
    nested_virt: bool = False          # Enable nested virtualization
    cpu_pinning: Optional[str] = None  # e.g., "0-3" — cores to pin to
    numa_node: Optional[int] = None    # NUMA node for memory locality

class VMManager:
    def create_vm(self, spec: VMSpec) -> VMConnectionInfo:
        """Create a VM from spec. Blocks until boot completes or timeout."""

    def destroy_vm(self, vm_id: str) -> None:
        """Hard-kill VM, undefine domain, delete disk, release resources."""

    def get_vm_status(self, vm_id: str) -> VMStatus:
        """Return current VM state, resource usage, and health."""

    def list_vms(self, owner: Optional[str] = None) -> list[VMStatus]:
        """List all VMs, optionally filtered by owner, enriched with metrics."""

    def check_host_capacity(self, spec: VMSpec) -> CapacityCheckResult:
        """Verify host has sufficient resources for the requested spec."""

    def detect_nested_virt_support(self) -> bool:
        """Check if host supports nested virtualization."""

    def get_vm_ssh_info(self, vm_id: str) -> SSHInfo:
        """Return SSH connection details for a running VM."""
```

### 3.2 Outputs (Return Types and Events)

```python
@dataclass
class VMConnectionInfo:
    vm_id: str                         # VM UUID
    vm_name: str                       # libvirt domain name
    ssh_host: str                      # VM IP address (from DHCP lease)
    ssh_port: int                      # Always 22
    ssh_key_path: str                  # Path to private key on host
    status: str                        # "running"

@dataclass
class VMStatus:
    vm_id: str
    session_id: str
    name: str
    status: str                        # "creating"|"running"|"shutdown"|"error"|"destroyed"
    base_image: str
    cpu_cores: int
    memory_mb: int
    disk_gb: int
    cpu_usage_percent: float
    memory_used_mb: int
    disk_read_bytes: int
    disk_write_bytes: int
    created_at: str
    destroyed_at: Optional[str]
    error_message: Optional[str]

@dataclass
class CapacityCheckResult:
    sufficient: bool
    available_cpu: int
    available_memory_mb: int
    available_disk_gb: int
    shortfall: Optional[str]           # Human-readable reason if insufficient

@dataclass
class SSHInfo:
    host: str
    port: int
    username: str
    private_key_path: str
```

**Events emitted (to Audit Logger):**
- `vm.create` — VM domain created
- `vm.boot` — VM boot completed (SSH reachable)
- `vm.shutdown` — VM shutdown initiated
- `vm.crash` — VM crashed or QEMU exited unexpectedly
- `vm.qemu_exit` — QEMU process exited (expected or unexpected)
- `vm.disk_create` — qcow2 overlay created
- `vm.disk_delete` — qcow2 overlay deleted

### 3.3 Dependencies

| Component This Depends On | Purpose |
|---|---|
| **Storage Manager** | Base image lookup (`images.py`), disk overlay creation (`disks.py`), cloud-init ISO path |
| **Metadata Store** | VM record CRUD (`store.py`) |
| **Host Manager** | Capacity checking (`capacity.py`), CPU topology (`cpu_map.py`), cgroup setup (`cgroups.py`) |
| **Network Manager** | Bridge name and vnet name assignment (bridge must exist before VM creation) |
| **Config** | Default resource limits, storage paths |
| **Observability** | Audit event emission (`audit.py`), metrics collection |

| Components That Call This | Purpose |
|---|---|
| **Session Manager** | Creates/destroys VMs as part of session lifecycle |
| **REST API** | Direct VM CRUD endpoints (legacy `/vms` routes) |
| **CLI** | Direct VM commands (`agentvm vm create/destroy/list/status`) |

---

## 4. Implementation Plan (Mapped to HLD Phases)

### Phase 1: Foundation (Week 1-2)

**Phase Goal:** Can create and destroy a single KVM VM via Python code.

**User Stories & Tasks:**

* **Story:** As a developer, I can connect to libvirt and verify host prerequisites.
  * **Task:** Implement `libvirt_connection.py` — manage libvirt URI connection with retry and error handling (`qemu:///system`).
    * *Identified Blockers/Dependencies:* None — foundational.
  * **Task:** Implement `detect_nested_virt_support()` — read `/sys/module/kvm_intel/parameters/nested` or `/sys/module/kvm_amd/parameters/nested` and verify returns `Y`.
    * *Identified Blockers/Dependencies:* libvirt connection must be functional.
  * **Task:** Implement host prerequisite checks — verify `/dev/kvm` exists, libvirtd is running, nested virt module is loaded.
    * *Identified Blockers/Dependencies:* libvirt connection must be functional.

* **Story:** As a developer, I can build a libvirt XML domain definition from a VMSpec.
  * **Task:** Implement `xml_builder.py` — template engine that takes a `VMSpec` and produces the XML from HLD Section 9 template. Must support: CPU pinning, NUMA, nested virt features, memory backing, minimal device model (virtio-only), serial console, virtiofs shared folder, RNG device.
    * *Identified Blockers/Dependencies:* `VMSpec` dataclass must be defined (`spec.py`).

* **Story:** As a developer, I can create a qcow2 COW overlay from a base image.
  * **Task:** Implement `disks.py` — `create_disk_overlay(base_image_path, vm_id, size_gb)` using `qemu-img create -f qcow2 -F qcow2 -b <base> <overlay> <size>`. Create VM directory under `/var/lib/agentvm/vms/vm-<uuid>/`.
    * *Identified Blockers/Dependencies:* Config must provide `storage.base_images_dir` and `storage.vm_data_dir`.

* **Story:** As a developer, I can create and destroy a VM through Python code.
  * **Task:** Implement `VMManager.create_vm()` — validate spec, check capacity, create disk overlay, generate XML, call `conn.createXML()`, wait for boot (poll domain state or SSH probe), record metadata to SQLite, return `VMConnectionInfo`.
    * *Identified Blockers/Dependencies:* `xml_builder.py`, `disks.py`, Metadata Store (sessions + vms tables), Host Manager (`capacity.py`), Network Manager (bridge must exist).
  * **Task:** Implement `VMManager.destroy_vm()` — `domain.destroy()` (hard kill), `domain.undefine()`, delete disk overlay, purge metadata from SQLite.
    * *Identified Blockers/Dependencies:* `create_vm()` must be functional first.
  * **Task:** Implement `VMManager.get_vm_status()` — read domain state from libvirt, read cgroup usage, return `VMStatus`.
    * *Identified Blockers/Dependencies:* libvirt connection, cgroup path must be tracked in metadata.

* **Story:** As a developer, I have unit tests for VM lifecycle.
  * **Task:** Implement `test_vm_manager.py` and `test_xml_builder.py` with mocked libvirt. Test: spec validation, XML generation correctness, create/destroy happy path, error handling on libvirt failure.
    * *Identified Blockers/Dependencies:* Mock libvirt module (`tests/mocks/mock_libvirt.py`).

---

### Phase 2: Session Model + Auth Proxy (Week 2-3)

**Phase Goal:** VM Manager integrates with Session Manager and Auth Proxy.

**User Stories & Tasks:**

* **Story:** As a Session Manager, I can create a VM with all associated resources (proxy, shared folder) in a single call.
  * **Task:** Extend `create_vm()` to accept pre-generated cloud-init ISO path and shared folder host path from Session Manager, and inject them into the libvirt XML.
    * *Identified Blockers/Dependencies:* Cloud-init generation (Storage Manager), shared folder directory creation (Storage Manager), proxy port allocation (Auth Proxy Manager).

* **Story:** As a Session Manager, I can destroy a VM and all associated resources are cleaned up.
  * **Task:** Ensure `destroy_vm()` is called as part of the Session Manager's destroy flow — VM Manager handles domain + disk cleanup only; Session Manager coordinates proxy/network/shared folder cleanup.
    * *Identified Blockers/Dependencies:* Session Manager must orchestrate the destroy sequence.

---

### Phase 5: Resource Enforcement + Shared Folder (Week 5-6)

**Phase Goal:** VM resource limits are enforced via cgroups; shared folder is secure.

**User Stories & Tasks:**

* **Story:** As a platform operator, VMs cannot exceed their allocated CPU, memory, or disk I/O.
  * **Task:** After VM creation, call Host Manager's `cgroups.py` to place the QEMU PID into `/sys/fs/cgroup/agentvm.slice/vm-{uuid}.scope/` with CPU, memory, I/O, and PID limits.
    * *Identified Blockers/Dependencies:* Host Manager cgroups implementation, QEMU PID retrieval from libvirt domain.
  * **Task:** Implement CPU pinning — read topology from Host Manager `cpu_map.py`, allocate cores excluding reserved cores, generate `<cputune>` XML, apply cpuset via cgroup.
    * *Identified Blockers/Dependencies:* Host Manager `cpu_map.py` must provide topology.

* **Story:** As a platform operator, the shared folder mount in the VM XML uses the correct driver (virtiofs or 9p fallback).
  * **Task:** Implement driver selection logic: if QEMU version ≥6.0, use `virtiofs` (requires `<driver type='virtiofs'/>` and a virtiofsd process); else fall back to `9p` with `accessmode='mapped'`. Check QEMU version via `qemu-system-x86_64 --version` or libvirt capabilities XML.
    * *Identified Blockers/Dependencies:* Shared folder host path must be created by Storage Manager.

---

### Phase 6: Observability + Security (Week 6-7)

**Phase Goal:** Full audit trail and red-team validation.

**User Stories & Tasks:**

* **Story:** As a platform operator, all VM lifecycle events are captured in the audit log.
  * **Task:** Integrate audit event emission into `create_vm()`, `destroy_vm()`, and crash detection paths. Emit events: `vm.create`, `vm.boot`, `vm.shutdown`, `vm.crash`, `vm.qemu_exit`, `vm.disk_create`, `vm.disk_delete`.
    * *Identified Blockers/Dependencies:* Observability `audit.py` must be implemented.

* **Story:** As a platform operator, VM crash is detected and triggers cleanup.
  * **Task:** Implement QEMU exit detection — register a libvirt domain lifecycle event callback or poll domain state periodically. On unexpected exit: emit `vm.crash`, mark VM as `error` in metadata, trigger cleanup (disk overlay deletion, metadata purge).
    * *Identified Blockers/Dependencies:* Observability audit + metadata store.

---

### Phase 7: Orchestrator Adapter + Production (Week 7-8)

**Phase Goal:** VM Manager supports TTL and is production-ready.

**User Stories & Tasks:**

* **Story:** As a platform operator, VMs are auto-destroyed after their max lifetime expires.
  * **Task:** Implement TTL enforcement — on VM creation, record `created_at` timestamp. Background task periodically checks all running VMs against `security.vm_max_lifetime_hours` config. Expired VMs are destroyed.
    * *Identified Blockers/Dependencies:* Config must provide `vm_max_lifetime_hours`, metadata store must track `created_at`.

* **Story:** As an orchestrator, I can query VM capacity and status through the VM Manager.
  * **Task:** Ensure `list_vms()` and `get_vm_status()` return data compatible with the `IsolationBackend` protocol (sessions as the primary abstraction, VMs as backing resources).
    * *Identified Blockers/Dependencies:* Orchestrator Adapter must define the protocol.

---

## 5. Error Handling

| Error Condition | Handling | HTTP Code (if surfaced) |
|---|---|---|
| libvirt connection refused | Retry 3x with backoff, then raise `VMConnectionError` | 503 |
| Base image not found | Raise `SpecValidationError` with image name | 400 |
| Insufficient host resources | Return `CapacityCheckResult.sufficient=False` | 507 |
| VM name conflict | Raise `NameConflictError` | 409 |
| libvirt XML generation failure | Raise `SpecValidationError` | 400 |
| VM boot timeout (60s) | Destroy partial VM, raise `VMBootTimeoutError` | 500 |
| QEMU crash during operation | Detect via lifecycle callback, emit `vm.crash`, trigger cleanup | N/A (internal) |
| Nested virt not available but requested | Raise `SpecValidationError` | 422 |
