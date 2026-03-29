# Orchestrator Adapter — Low-Level Design

## Component Name: Orchestrator Adapter

The Orchestrator Adapter implements the `IsolationBackend` protocol, providing a uniform interface for an external orchestrator to manage workloads on AgentVM. It actively manages session lifecycle on behalf of the orchestrator and reports backend capabilities for workload routing decisions.

**Source files:** `src/agentvm/orchestrator/backend.py`, `src/agentvm/orchestrator/capabilities.py`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| OA-FR-01 | Implement the `IsolationBackend` protocol with all required methods | 11.1 |
| OA-FR-02 | `create_session(spec)` — accept a `WorkloadSpec`, provision a full session, return once reachable | 11.1 |
| OA-FR-03 | `destroy_session(session_id)` — hard-kill and clean up all resources | 11.1 |
| OA-FR-04 | `get_session_status(session_id)` — return current state, resource usage, health | 11.1 |
| OA-FR-05 | `list_sessions(owner)` — all sessions, optionally filtered by owner | 11.1 |
| OA-FR-06 | `allow_network(session_id, domain, port)` — allow outbound to domain:port | 11.1 |
| OA-FR-07 | `block_network(session_id, domain, port)` — block outbound to domain:port | 11.1 |
| OA-FR-08 | `reset_network(session_id)` — reset network to startup defaults | 11.1 |
| OA-FR-09 | `get_network_rules(session_id)` — return current network policy state | 11.1 |
| OA-FR-10 | `inject_secret(session_id, key, value)` — make a secret available inside the session via proxy | 11.1 |
| OA-FR-11 | `get_ssh_info(session_id)` — return SSH connection details | 11.1 |
| OA-FR-12 | `capabilities()` — return `BackendCapabilities` describing what this backend supports | 11.1, 11.2 |
| OA-FR-13 | Convert between orchestrator `WorkloadSpec` and internal `SessionCreateRequest` | 11.1 |
| OA-FR-14 | Convert between internal `WorkloadSession` and orchestrator `SessionStatus` | 11.1 |
| OA-FR-15 | Report host capacity alongside capabilities for orchestrator routing | 11.3 |
| OA-FR-16 | List available images with capability hints for orchestrator routing | 11.3 |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| OA-NFR-01 | The adapter must be a thin translation layer — no business logic beyond type conversion | Architecture |
| OA-NFR-02 | `create_session` must block until the session is reachable (SSH or proxy health) | 11.1 |
| OA-NFR-03 | `capabilities()` must return accurate real-time host capacity | 11.3 |
| OA-NFR-04 | Unit test coverage ≥80% for type conversion and protocol conformance | 12.1 |

---

## 3. Component API Contracts

### 3.1 IsolationBackend Protocol

```python
from typing import Protocol, Optional
from dataclasses import dataclass

@dataclass
class WorkloadSpec:
    """Orchestrator-provided workload specification."""
    name: str
    base_image: str
    cpu_cores: int
    memory_mb: int
    disk_gb: int
    network_mbps: int = 100
    network_policy: str = "strict"
    ssh_public_key: str = ""
    api_keys: dict[str, str] = None
    shared_folder: dict = None        # {"project_path": ..., "output_path": ...}
    metadata: dict = None
    owner: str = ""

    # Orchestrator routing hints
    needs_kvm: bool = False
    needs_nested_virt: bool = False
    needs_gpu: bool = False
    enforcement_level: str = "host_kernel"
    max_startup_ms: Optional[int] = None

@dataclass
class SessionStatus:
    """Orchestrator-facing session status."""
    id: str
    backend: str                      # "agentvm"
    workload_type: str                # "vm"
    status: str
    owner: str
    created_at: str
    stopped_at: Optional[str]
    cpu_cores: int
    memory_mb: int
    disk_gb: int
    ssh_host: Optional[str]
    ssh_port: Optional[int]
    proxy_port: Optional[int]
    proxy_dummy_key: Optional[str]
    shared_folder_host_path: Optional[str]
    shared_folder_guest_mount: Optional[str]
    network_policy: str
    metadata: dict
    healthy: bool

@dataclass
class NetworkRule:
    domain: str
    ip_address: Optional[str]
    port: Optional[int]
    action: str
    source: str
    created_at: str

@dataclass
class SSHInfo:
    host: str
    port: int
    username: str
    private_key_path: str

@dataclass
class BackendCapabilities:
    name: str                         # "agentvm"
    backend_version: str
    max_sessions: int
    supports_kvm: bool
    supports_gpu: bool
    supports_nested_virt: bool
    supports_runtime_network: bool
    supports_filesystem_policy: bool
    supports_secret_injection: bool
    supports_shared_folder: bool
    supports_auth_proxy: bool
    enforcement_level: str            # "host_kernel"
    startup_latency_ms: int
    per_session_overhead_mb: int
    available_images: list[ImageSummary]
    host_capacity: CapacityInfo

@dataclass
class ImageSummary:
    name: str
    capabilities: list[str]
    needs_kvm: bool

@dataclass
class CapacityInfo:
    total_cpu: int
    available_cpu: int
    total_memory_mb: int
    available_memory_mb: int
    total_disk_gb: int
    available_disk_gb: int

class IsolationBackend(Protocol):
    def create_session(self, spec: WorkloadSpec) -> SessionStatus: ...
    def destroy_session(self, session_id: str) -> None: ...
    def get_session_status(self, session_id: str) -> SessionStatus: ...
    def list_sessions(self, owner: Optional[str] = None) -> list[SessionStatus]: ...
    def allow_network(self, session_id: str, domain: str, port: Optional[int] = None) -> None: ...
    def block_network(self, session_id: str, domain: str, port: Optional[int] = None) -> None: ...
    def reset_network(self, session_id: str) -> None: ...
    def get_network_rules(self, session_id: str) -> list[NetworkRule]: ...
    def inject_secret(self, session_id: str, key: str, value: str) -> None: ...
    def get_ssh_info(self, session_id: str) -> SSHInfo: ...
    def capabilities(self) -> BackendCapabilities: ...
```

### 3.2 Adapter Implementation

```python
class AgentVMBackend:
    """Implements IsolationBackend for AgentVM."""

    def __init__(self, session_manager: SessionManager,
                 network_engine: NetworkPolicyEngine,
                 proxy_manager: AuthProxyManager,
                 storage_manager: StorageManager,
                 host_manager: HostManager,
                 image_manager: ImageManager):
        self.session_manager = session_manager
        self.network_engine = network_engine
        self.proxy_manager = proxy_manager
        self.storage_manager = storage_manager
        self.host_manager = host_manager
        self.image_manager = image_manager

    def create_session(self, spec: WorkloadSpec) -> SessionStatus:
        """Convert WorkloadSpec → SessionCreateRequest, delegate to SessionManager, convert result."""

    def capabilities(self) -> BackendCapabilities:
        """Gather capabilities from all sub-components, include host capacity."""
```

### 3.3 Dependencies

| Component This Depends On | Purpose |
|---|---|
| **Session Manager** | All session CRUD operations |
| **Network Manager** | Network policy operations |
| **Auth Proxy Manager** | Secret injection (write to proxy config), proxy status |
| **Storage Manager** | Image listing with capabilities |
| **Host Manager** | Capacity info, KVM/nested virt detection |
| **Config** | Max sessions, startup latency estimate, per-session overhead estimate |

| Components That Call This | Purpose |
|---|---|
| **REST API** | `/capabilities` endpoint |
| **External orchestrator** | Primary consumer of the `IsolationBackend` interface |

---

## 4. Implementation Plan (Mapped to HLD Phases)

### Phase 7: Orchestrator Adapter + Production (Week 7-8)

**Phase Goal:** `IsolationBackend` protocol implementation, orchestrator can route workloads.

**User Stories & Tasks:**

* **Story:** As an orchestrator, I can create sessions through a uniform protocol.
  * **Task:** Implement `AgentVMBackend.create_session(spec)`:
    1. Convert `WorkloadSpec` to `SessionCreateRequest` (map fields directly).
    2. Call `SessionManager.create_session(request)`.
    3. Convert returned `WorkloadSession` to `SessionStatus`.
    4. Return `SessionStatus`.
    * *Identified Blockers/Dependencies:* Session Manager must be fully implemented.

* **Story:** As an orchestrator, I can manage network policy through a uniform protocol.
  * **Task:** Implement `allow_network()`, `block_network()`, `reset_network()`, `get_network_rules()` — thin wrappers around `NetworkPolicyEngine` methods, converting between orchestrator `NetworkRule` and internal `NetworkRule` types.
    * *Identified Blockers/Dependencies:* Network Manager.

* **Story:** As an orchestrator, I can inject secrets into a session.
  * **Task:** Implement `inject_secret(session_id, key, value)` — write the secret to the session's proxy config and restart the proxy process so the new secret is available.
    * *Identified Blockers/Dependencies:* Auth Proxy Manager.

* **Story:** As an orchestrator, I can query backend capabilities and host capacity.
  * **Task:** Implement `capabilities()`:
    1. Query `HostManager.detect_nested_virt_support()` → `supports_nested_virt`.
    2. Query `HostManager.get_capacity()` → `host_capacity`.
    3. Query `StorageManager.list_images()` → `available_images` (with capability hints).
    4. Read config values → `max_sessions`, `startup_latency_ms`, `per_session_overhead_mb`.
    5. Return `BackendCapabilities`.
    * *Identified Blockers/Dependencies:* Host Manager, Storage Manager, Config.

* **Story:** As a developer, I have unit tests for type conversion and protocol conformance.
  * **Task:** Implement `test_orchestrator_adapter.py` — test `WorkloadSpec` → `SessionCreateRequest` conversion, `WorkloadSession` → `SessionStatus` conversion, verify all `IsolationBackend` methods are implemented and callable.
    * *Identified Blockers/Dependencies:* None.

* **Story:** As a developer, I have E2E tests with a mock orchestrator.
  * **Task:** Implement `test_orchestrator_routing.py` — mock orchestrator that uses `AgentVMBackend` to create sessions, verify routing logic selects AgentVM for KVM/nested virt workloads.
    * *Identified Blockers/Dependencies:* Full system integration.

---

## 5. Type Conversion Map

| Orchestrator Field | Internal Field | Notes |
|---|---|---|
| `WorkloadSpec.name` | `SessionCreateRequest.name` | Direct |
| `WorkloadSpec.base_image` | `SessionCreateRequest.base_image` | Direct |
| `WorkloadSpec.cpu_cores` | `SessionCreateRequest.cpu_cores` | Direct |
| `WorkloadSpec.memory_mb` | `SessionCreateRequest.memory_mb` | Direct |
| `WorkloadSpec.disk_gb` | `SessionCreateRequest.disk_gb` | Direct |
| `WorkloadSpec.network_policy` | `SessionCreateRequest.network_policy` | Direct |
| `WorkloadSpec.api_keys` | `SessionCreateRequest.api_keys` | Direct |
| `WorkloadSpec.shared_folder` | `SessionCreateRequest.shared_folder` | Convert dict → `SharedFolderConfig` |
| `WorkloadSpec.owner` | `SessionCreateRequest.owner` | Direct |
| `WorkloadSession.status` | `SessionStatus.status` | Direct |
| `WorkloadSession.healthy` | Derived from health check | Call `HealthChecker.check_session_health()` |

---

## 6. Error Handling

| Error Condition | Handling |
|---|---|
| `WorkloadSpec` validation failure | Propagate `SpecValidationError` from Session Manager |
| Capacity exceeded | Propagate `CapacityError` from Host Manager |
| Image not found | Propagate `ImageNotFoundError` from Storage Manager |
| Session not found | Propagate `NotFoundError` from Session Manager |
| `inject_secret` on destroyed session | Raise `SessionStateError` |
