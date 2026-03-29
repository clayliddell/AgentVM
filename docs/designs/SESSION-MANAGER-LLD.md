# Session Manager — Low-Level Design

## Component Name: Session Manager

The Session Manager is the primary abstraction layer over VM lifecycle. It coordinates VM creation, auth proxy setup, network configuration, shared folder provisioning, and metadata persistence into a single coherent session. It is the component that the REST API, CLI, and Orchestrator Adapter all interact with.

**Source files:** `src/agentvm/session/manager.py`, `src/agentvm/session/model.py`, `src/agentvm/session/state.py`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| SS-FR-01 | Create a session that provisions: VM, auth proxy, network rules, shared folder, and metadata record | 5.2 |
| SS-FR-02 | Destroy a session — tear down VM, stop proxy, clean network rules, remove shared folder, purge metadata | 5.2 |
| SS-FR-03 | Track session state machine: requested → creating → running → shutdown → destroyed / error | 5.2 |
| SS-FR-04 | Reject state transitions that are invalid (e.g., cannot resume from destroyed) | 5.2 |
| SS-FR-05 | Retrieve session status including VM status, proxy health, resource usage, and connection info | 5.2 |
| SS-FR-06 | List sessions with optional owner filter | 5.2, 11.1 |
| SS-FR-07 | Provide SSH connection info for a session | 6.1 (`/sessions/{sid}/ssh`) |
| SS-FR-08 | Store and return arbitrary metadata tags (agent_id, task_type, orchestrator_session) | 5.2 |
| SS-FR-09 | Support session creation with API keys, shared folder config, network policy, and resource spec in a single call | 6.2 |
| SS-FR-10 | Gracefully handle partial creation failure — if any sub-provisioning step fails, roll back all previously created resources | 5.2 |
| SS-FR-11 | Support session resume (transition from shutdown back to running by re-creating VM with existing shared folder and proxy) | 5.2 state diagram |
| SS-FR-12 | Enforce session ownership — only the owner (API key or orchestrator session) can manage their sessions | 6.1 |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| SS-NFR-01 | Session creation end-to-end must complete within 20 seconds | 6.3 (`startup_latency_ms` = 15000ms + overhead) |
| SS-NFR-02 | Session destroy must complete within 15 seconds regardless of state | 5.2 |
| SS-NFR-03 | Unit test coverage ≥80% for session state machine and manager | 12.1 |
| SS-NFR-04 | All component interactions must be async-safe (concurrent session creation) | Phase 3 |
| SS-NFR-05 | Partial failure rollback must be deterministic and complete — no orphaned resources | 5.2 |

---

## 3. Component API Contracts

### 3.1 Inputs (Methods Exposed)

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class SessionCreateRequest:
    name: str
    base_image: str
    cpu_cores: int
    memory_mb: int
    disk_gb: int
    network_mbps: int = 100
    network_policy: str = "strict"     # "strict" | "restricted" | "permissive"
    ssh_public_key: str = ""
    api_keys: dict[str, str] = field(default_factory=dict)   # {"openai": "sk-...", ...}
    shared_folder: Optional[SharedFolderConfig] = None
    metadata: dict = field(default_factory=dict)
    owner: str = ""                    # API key or orchestrator session ID

@dataclass
class SharedFolderConfig:
    """Shared folder configuration. Used by Session Manager, Orchestrator Adapter, and REST API."""
    project_path: str                  # Host path to project source
    output_path: str                   # Host path for VM output
    permissions: str = "rw"            # "rw" | "ro"

@dataclass
class SessionManager:
    def create_session(self, request: SessionCreateRequest) -> WorkloadSession:
        """Provision a complete session. Blocks until VM is booted or creation fails."""

    def destroy_session(self, session_id: str) -> None:
        """Tear down all session resources. Idempotent."""

    def get_session(self, session_id: str) -> WorkloadSession:
        """Retrieve session details with current status and resource usage."""

    def list_sessions(self, owner: Optional[str] = None) -> list[WorkloadSession]:
        """List sessions, optionally filtered by owner."""

    def get_ssh_info(self, session_id: str) -> SSHInfo:
        """Get SSH connection details for a session's VM."""

    def shutdown_session(self, session_id: str) -> WorkloadSession:
        """Graceful shutdown — VM stops, but proxy/network/shared folder persist."""

    def resume_session(self, session_id: str) -> WorkloadSession:
        """Resume a shutdown session by re-creating the VM."""
```

### 3.2 Outputs (Return Types and Events)

```python
@dataclass
class WorkloadSession:
    id: str                            # UUID — uniform across backends
    backend: str                       # "agentvm"
    workload_type: str                 # "vm"
    status: str                        # requested|creating|running|shutdown|destroyed|error
    owner: str
    created_at: datetime
    stopped_at: Optional[datetime]
    metadata: dict

    # Resource allocation
    cpu_cores: int
    memory_mb: int
    disk_gb: int

    # Connection info (populated after boot)
    ssh_host: Optional[str]
    ssh_port: Optional[int]
    ssh_key_path: Optional[str]

    # Auth proxy (populated after proxy start)
    proxy_port: Optional[int]
    proxy_dummy_key: Optional[str]

    # Shared folder (populated after folder setup)
    shared_folder_host_path: Optional[str]
    shared_folder_guest_mount: Optional[str]

    # Network policy
    network_policy: str                # "strict" | "restricted" | "permissive"

    # Capability flags
    needs_kvm: bool
    needs_gpu: bool
    enforcement_level: str             # "host_kernel"

    # VM backing resource
    vm_id: Optional[str]

    # Live health (populated by get_session/status, not persisted)
    healthy: Optional[bool] = None     # True if VM booted + proxy healthy
    proxy_healthy: Optional[bool] = None  # True if proxy responds to health probe
    cpu_usage_percent: Optional[float] = None
    memory_used_mb: Optional[int] = None
```

**Events emitted (to Audit Logger):**
- `session.start` — Session creation initiated
- `session.stop` — Session destroyed
- `session.error` — Session entered error state

### 3.3 Dependencies

| Component This Depends On | Purpose |
|---|---|
| **VM Manager** | Create/destroy VMs (`vm/manager.py`) |
| **Auth Proxy Manager** | Start/stop proxy processes (`proxy/manager.py`) |
| **Network Manager** | Apply network rules on session create, clean up on destroy (`net/firewall.py`, `net/policy.py`) |
| **Storage Manager** | Create shared folder directory, generate cloud-init ISO (`storage/shared.py`, `storage/cloud_init.py`) |
| **Metadata Store** | CRUD for sessions, vms, proxies, shared_folders, resource_allocations tables (`db/store.py`) |
| **Host Manager** | Capacity checking before create (`host/capacity.py`) |
| **Observability** | Audit event emission (`observe/audit.py`) |
| **Config** | Default resource values, paths |

| Components That Call This | Purpose |
|---|---|
| **REST API** | Session CRUD endpoints (`/sessions/*`) |
| **CLI** | Session commands (`agentvm session create/destroy/list/status`) |
| **Orchestrator Adapter** | `IsolationBackend.create_session()`, `destroy_session()`, etc. |

---

## 4. Implementation Plan (Mapped to HLD Phases)

### Phase 2: Session Model + Auth Proxy (Week 2-3)

**Phase Goal:** Session abstraction wrapping VM lifecycle with auth proxy and shared folder.

**User Stories & Tasks:**

* **Story:** As a developer, I have a `WorkloadSession` dataclass and a state machine that governs valid transitions.
  * **Task:** Implement `model.py` — `WorkloadSession` dataclass matching HLD Section 5.2 definition exactly. Include all fields: id, backend, workload_type, status, owner, resource allocation, connection info, proxy info, shared folder info, network policy, capability flags.
    * *Identified Blockers/Dependencies:* None — defines the contract all other components use.
  * **Task:** Implement `state.py` — session state machine with transitions: requested → creating → running → shutdown → destroyed, and any state → error. Define `InvalidTransitionError` for invalid transitions.
    * *Identified Blockers/Dependencies:* `WorkloadSession` dataclass.

* **Story:** As a developer, I can create a session that provisions all resources atomically.
  * **Task:** Implement `SessionManager.create_session()` — orchestrate the following sequence:
    1. Validate request (check image exists, resource bounds).
    2. Check host capacity via Host Manager.
    3. Transition session state to `creating`, persist to metadata store.
    4. Allocate vnet interface (vnet_name, mac_address) via Network Manager `BridgeManager.allocate_vm_interface()`.
    5. Create shared folder directory via Storage Manager.
    6. Generate cloud-init ISO via Storage Manager (injecting SSH key, shared folder config, proxy port/key placeholder).
    7. Start auth proxy via Auth Proxy Manager (needs VM IP for validation; proxy port/key injected into cloud-init in prior step).
    8. Create VM via VM Manager (receives vnet_name, mac_address in VMSpec; VM boots and gets DHCP IP).
    9. Resolve VM IP via Network Manager `BridgeManager.get_vm_ip()` using the allocated MAC.
    10. Apply network rules via Network Manager `setup_session_network()` (now that VM IP is known).
    11. Update proxy VM IP if needed (proxy validates source IP).
    12. Transition to `running`, update metadata.
    13. Return `WorkloadSession` with all connection info populated.

    On any step failure: roll back all previously completed steps (e.g., if VM creation fails, stop proxy, clean network rules, remove shared folder, delete cloud-init ISO, purge metadata).
    * *Identified Blockers/Dependencies:* VM Manager, Auth Proxy Manager, Network Manager, Storage Manager, Metadata Store, Host Manager must all have basic implementations (Phase 1 for VM Manager, partial Phase 2 for others).

* **Story:** As a developer, I can destroy a session and all resources are cleaned up.
  * **Task:** Implement `SessionManager.destroy_session()` — orchestrate destroy sequence:
    1. If already `destroyed`, return immediately (idempotent).
    2. Destroy VM via VM Manager (this handles domain + disk cleanup).
    3. Stop auth proxy via Auth Proxy Manager.
    4. Clean network rules via Network Manager.
    5. Remove shared folder directory via Storage Manager.
    6. Purge all metadata records (sessions, vms, proxies, shared_folders, resource_allocations).
    7. Transition to `destroyed` in metadata (only after all cleanup succeeds).
    8. Emit `session.stop` audit event.
    If any cleanup step fails, transition to `error` state instead of `destroyed`, log the failure, and leave remaining metadata for manual inspection.
    * *Identified Blockers/Dependencies:* All sub-component destroy methods must be implemented.

* **Story:** As a developer, I can get session details and list sessions.
  * **Task:** Implement `get_session()` — query metadata store for session record, enrich with live VM status from VM Manager (`cpu_usage_percent`, `memory_used_mb`), proxy health from Auth Proxy Manager (`health_check()`), and derive `healthy` (VM running AND proxy responsive) and `proxy_healthy` fields. Return `WorkloadSession` with all live fields populated.
    * *Identified Blockers/Dependencies:* Metadata store read, VM Manager `get_vm_status()`, Auth Proxy Manager `health_check()`.
  * **Task:** Implement `list_sessions()` — query metadata store with optional owner filter, enrich each with live status.
    * *Identified Blockers/Dependencies:* Same as `get_session()`.

* **Story:** As a developer, I have unit tests for session lifecycle and state machine.
  * **Task:** Implement `test_session.py` — test state machine transitions (valid and invalid), mock all sub-components and verify the create/destroy orchestration sequence, test rollback on partial failure.
    * *Identified Blockers/Dependencies:* Mock implementations of all sub-components.

* **Story:** As a platform operator, session ownership is enforced so only the owning API key or orchestrator session can manage its sessions.
  * **Task:** Implement ownership enforcement in all Session Manager methods (`get_session`, `destroy_session`, `shutdown_session`, `resume_session`, `get_ssh_info`) — accept `owner` parameter, verify `session.owner == owner` before proceeding. Raise `ForbiddenError` on mismatch. `list_sessions(owner)` already filters by owner.
    * *Identified Blockers/Dependencies:* REST API auth must extract owner identity from Bearer token and pass it through.

---

### Phase 3: API + CLI (Week 3-4)

**Phase Goal:** Session Manager is the backend for REST API session endpoints.

**User Stories & Tasks:**

* **Story:** As an API consumer, I can create/get/list/destroy sessions via REST.
  * **Task:** Ensure Session Manager methods are async-compatible (wrap blocking libvirt calls in `asyncio.to_thread()` if needed) so FastAPI endpoints can call them without blocking the event loop.
    * *Identified Blockers/Dependencies:* Phase 2 Session Manager implementation complete.

**Sync/Async Model:** Session Manager public methods are synchronous. The REST API wraps all calls in `asyncio.to_thread()` at the route handler level. Metadata Store operations are async (using `aiosqlite`). Within synchronous Session Manager methods, metadata store calls use `asyncio.run()` or are delegated to a shared event loop. The boundary is: Session Manager is sync, Metadata Store is async, and FastAPI bridges the two.

---

### Phase 7: Orchestrator Adapter + Production (Week 7-8)

**Phase Goal:** Session Manager supports resume, TTL, and graceful shutdown.

**User Stories & Tasks:**

* **Story:** As a platform operator, I can shutdown a session (VM stops) and later resume it.
  * **Task:** Implement `shutdown_session()` — stop the VM via VM Manager `soft_shutdown()`, keep proxy/network/shared folder/metadata intact, transition to `shutdown`.
    * *Identified Blockers/Dependencies:* VM Manager supports soft shutdown.
  * **Task:** Implement `resume_session()` — generate new cloud-init ISO (same config), create new VM from existing shared folder, transition back to `running`.
    * *Identified Blockers/Dependencies:* `shutdown_session()` implemented.
  * **Resume IP/MAC preservation:** On resume, the VM is recreated with a new DHCP lease. The Network Manager must update iptables rules with the new IP. The Auth Proxy Manager must update `vm_ip` in the proxy config and reload (or restart) the proxy so source IP validation passes. Session Manager coordinates this: after VM boots and acquires a new IP, call `NetworkManager.update_session_ip(session_id, old_ip, new_ip)` and `AuthProxyManager.update_vm_ip(session_id, new_ip)`.

* **Story:** As a platform operator, sessions auto-destroy after their TTL expires.
  * **Task:** Implement TTL check in the Session Manager's background task — query metadata store for sessions with `created_at` older than `security.vm_max_lifetime_hours`, initiate destroy for expired sessions.
    * *Identified Blockers/Dependencies:* Config `vm_max_lifetime_hours`, metadata store query.

* **Story:** As a daemon shutting down, I can gracefully drain all active sessions.
  * **Task:** Implement `drain_all_sessions()` — iterate all `running` sessions, destroy each, with configurable timeout per session. Called on daemon SIGTERM.
    * *Identified Blockers/Dependencies:* `destroy_session()`.

---

## 5. Error Handling and Rollback Strategy

```
create_session() rollback sequence (if step N fails):

  Step 4 failed (vnet allocation):
    → Purge metadata record

  Step 5 failed (shared folder):
    → Release vnet interface
    → Purge metadata record
  
  Step 6 failed (cloud-init):
    → Remove shared folder directory
    → Release vnet interface
    → Purge metadata record

  Step 7 failed (proxy):
    → Delete cloud-init ISO
    → Remove shared folder directory
    → Release vnet interface
    → Purge metadata record

  Step 8 failed (VM):
    → Stop proxy
    → Delete cloud-init ISO
    → Remove shared folder directory
    → Release vnet interface
    → Purge metadata record

  Step 9-10 failed (IP resolution / network rules):
    → Destroy VM
    → Stop proxy
    → Delete cloud-init ISO
    → Remove shared folder directory
    → Release vnet interface
    → Purge metadata record

  Each rollback step must be idempotent (safe to re-run if rollback itself fails).
```

| Error Condition | Handling |
|---|---|
| Base image not found | Reject before provisioning starts, no rollback needed |
| Insufficient capacity | Reject before provisioning starts, no rollback needed |
| Vnet allocation failure | Rollback to step 3, raise error |
| Cloud-init generation failure | Rollback to step 5, raise error |
| Proxy port exhausted | Rollback to step 6, raise error |
| VM boot timeout | Full rollback, raise error |
| IP resolution failure (no DHCP lease) | Destroy VM, stop proxy, full rollback, raise error |
| Partial rollback failure | Log error, emit `session.error`, leave orphan marker in metadata for manual cleanup |
