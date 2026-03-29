# REST API — Low-Level Design

## Component Name: REST API

The REST API is the HTTP interface exposed by the agentvm daemon. Built with FastAPI and Uvicorn, it provides session management, VM management, network policy control, proxy status, shared folder info, image management, observability, and health/capacity endpoints. It enforces API key authentication.

**Source files:** `src/agentvm/api/app.py`, `src/agentvm/api/routes/sessions.py`, `src/agentvm/api/routes/vms.py`, `src/agentvm/api/routes/network.py`, `src/agentvm/api/routes/proxy.py`, `src/agentvm/api/routes/shared.py`, `src/agentvm/api/routes/images.py`, `src/agentvm/api/routes/health.py`, `src/agentvm/api/schemas.py`, `src/agentvm/api/auth.py`, `src/agentvm/api/errors.py`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| API-FR-01 | Expose session CRUD endpoints: `POST/GET/DELETE /sessions`, `GET /sessions/{sid}`, `GET /sessions/{sid}/ssh` | 6.1 |
| API-FR-02 | Expose VM CRUD endpoints (legacy): `POST/GET/DELETE /vms`, `GET /vms/{vm_id}` | 6.1 |
| API-FR-03 | Expose network policy endpoints: `GET/POST /sessions/{sid}/network`, `POST allow/block/reset` | 6.1 |
| API-FR-04 | Expose proxy endpoints: `GET /sessions/{sid}/proxy`, `GET /sessions/{sid}/proxy/logs` | 6.1 |
| API-FR-05 | Expose shared folder endpoints: `GET /sessions/{sid}/shared`, `POST /sessions/{sid}/shared/sync` | 6.1 |
| API-FR-06 | Expose observability endpoints: `GET /sessions/{sid}/metrics`, `GET /sessions/{sid}/logs`, `GET /sessions/{sid}/audit` | 6.1 |
| API-FR-07 | Expose host endpoints: `GET /health`, `GET /capacity`, `GET /metrics` (Prometheus) | 6.1 |
| API-FR-08 | Expose image management endpoints: `POST/GET/DELETE /images`, `GET /images/{name}` | 6.1 |
| API-FR-09 | Expose orchestrator endpoint: `GET /capabilities` | 6.1 |
| API-FR-10 | Validate all request payloads with Pydantic schemas | 6.2 |
| API-FR-11 | Return standardized error responses (400, 404, 409, 422, 500, 507) with error codes and details | 6.4 |
| API-FR-12 | Enforce API key authentication via Bearer token in Authorization header | 6.1 |
| API-FR-13 | Auto-generate OpenAPI documentation | 17 |
| API-FR-14 | Bind to configurable host/port (default `127.0.0.1:9090`) | 14 |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| API-NFR-01 | Non-blocking: all long-running operations (session create, destroy) must be async | Performance |
| API-NFR-02 | Request validation must return errors within 10ms | Performance |
| API-NFR-03 | API must handle concurrent requests without race conditions on shared state | Reliability |
| API-NFR-04 | All endpoints must require authentication except `/health` | Security |
| API-NFR-05 | API must bind to localhost by default — remote access requires explicit config | Security (14) |

---

## 3. Component API Contracts

### 3.1 Endpoint Map (from HLD Section 6.1)

```
Base URL: http://localhost:9090/api/v1
Auth:     Bearer <api-key>

Sessions:
  POST   /sessions                     → SessionCreateRequest → SessionResponse
  GET    /sessions                     → List[SessionResponse]
  GET    /sessions/{sid}               → SessionResponse
  DELETE /sessions/{sid}               → 204 No Content
  GET    /sessions/{sid}/ssh           → SSHInfoResponse

VMs (legacy):
  POST   /vms                          → VMCreateRequest → VMResponse
  GET    /vms                          → List[VMResponse]
  GET    /vms/{vm_id}                  → VMResponse
  DELETE /vms/{vm_id}                  → 204 No Content

Network:
  GET    /sessions/{sid}/network       → NetworkPolicyResponse
  POST   /sessions/{sid}/network/allow → NetworkActionRequest → NetworkActionResponse
  POST   /sessions/{sid}/network/block → NetworkActionRequest → NetworkActionResponse
  POST   /sessions/{sid}/network/reset → 204 No Content

Proxy:
  GET    /sessions/{sid}/proxy         → ProxyStatusResponse
  GET    /sessions/{sid}/proxy/logs    → List[ProxyLogEntry]

Shared:
  GET    /sessions/{sid}/shared        → SharedFolderResponse
  POST   /sessions/{sid}/shared/sync   → 202 Accepted

Observability:
  GET    /sessions/{sid}/metrics       → SessionMetricsResponse
  GET    /sessions/{sid}/logs          → StreamingResponse or LogResponse
  GET    /sessions/{sid}/audit         → List[AuditEventResponse]

Host:
  GET    /health                       → HealthResponse
  GET    /capacity                     → CapacityResponse
  GET    /metrics                      → Prometheus text format

Images:
  POST   /images                       → ImageUploadRequest → ImageResponse
  GET    /images                       → List[ImageResponse]
  GET    /images/{name}                → ImageResponse
  DELETE /images/{name}                → 204 No Content

Orchestrator:
  GET    /capabilities                 → CapabilitiesResponse
```

### 3.2 Pydantic Schemas

```python
# Request schemas
class SessionCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    base_image: str
    cpu_cores: int = Field(..., ge=1, le=32)
    memory_mb: int = Field(..., ge=512, le=65536)
    disk_gb: int = Field(..., ge=10, le=200)
    network_mbps: int = Field(default=100, ge=1, le=10000)
    network_policy: str = Field(default="strict", pattern="^(strict|restricted|permissive)$")
    ssh_public_key: str = ""
    api_keys: dict[str, str] = Field(default_factory=dict)
    shared_folder: Optional[SharedFolderConfigRequest] = None
    metadata: dict = Field(default_factory=dict)

class NetworkActionRequest(BaseModel):
    domain: str = Field(..., min_length=1)
    port: Optional[int] = Field(default=None, ge=1, le=65535)

# Response schemas
class SessionResponse(BaseModel):
    id: str
    vm_id: Optional[str]
    name: str
    status: str
    backend: str = "agentvm"
    workload_type: str = "vm"
    base_image: str
    cpu_cores: int
    memory_mb: int
    disk_gb: int
    network_policy: str
    ssh: Optional[SSHResponse]
    proxy: Optional[ProxyResponse]
    shared_folder: Optional[SharedFolderResponse]
    created_at: str
    metadata: dict

class ErrorResponse(BaseModel):
    error: str
    detail: str
```

### 3.3 Dependencies

| Component This Depends On | Purpose |
|---|---|
| **Session Manager** | All session operations |
| **VM Manager** | Legacy VM operations |
| **Network Manager** | Network policy operations |
| **Auth Proxy Manager** | Proxy status and logs |
| **Storage Manager** | Image management, shared folder info |
| **Observability** | Metrics, logs, audit queries, health checks |
| **Host Manager** | Capacity info |
| **Orchestrator Adapter** | Capabilities endpoint |
| **Config** | API host, port, API keys |

| Components That Call This | None — the API is the outermost layer |

---

## 4. Implementation Plan (Mapped to HLD Phases)

### Phase 3: API + CLI (Week 3-4)

**Phase Goal:** Full REST API for session lifecycle, network control, and observability.

**User Stories & Tasks:**

* **Story:** As a developer, I have a FastAPI application with authentication middleware.
  * **Task:** Implement `app.py` — create FastAPI app, include all route modules, configure CORS (if needed), add startup/shutdown events (initialize metadata store, ensure storage tree, ensure bridge).
  * **Task:** Implement `auth.py` — Bearer token authentication dependency. Extract token from `Authorization` header, validate against configured `api.api_keys` list. Return 401 on invalid/missing token. Skip auth for `/health` endpoint.
  * **Task:** Implement `errors.py` — exception handlers that map internal exceptions to HTTP status codes and `ErrorResponse` schemas: `SpecValidationError`→400, `NotFoundError`→404, `NameConflictError`→409, `CapacityError`→507, `ImageIncompatibleError`→422, `InternalError`→500.
    * *Identified Blockers/Dependencies:* Config (API keys).

* **Story:** As an API consumer, I can manage sessions via REST.
  * **Task:** Implement `routes/sessions.py`:
    - `POST /sessions` — parse `SessionCreateRequest`, call `SessionManager.create_session()`, return `SessionResponse` (201).
    - `GET /sessions` — optional `owner` query param, call `SessionManager.list_sessions()`, return `List[SessionResponse]`.
    - `GET /sessions/{sid}` — call `SessionManager.get_session()`, return `SessionResponse` (404 if not found).
    - `DELETE /sessions/{sid}` — call `SessionManager.destroy_session()`, return 204.
    - `GET /sessions/{sid}/ssh` — call `SessionManager.get_ssh_info()`, return `SSHInfoResponse`.
    All session endpoints use `async def` and wrap blocking calls in `asyncio.to_thread()`.
    * *Identified Blockers/Dependencies:* Session Manager.

* **Story:** As an API consumer, I can manage VMs directly (legacy).
  * **Task:** Implement `routes/vms.py` — `POST/GET/DELETE /vms`, `GET /vms/{vm_id}`. POST wraps `SessionManager.create_session()` internally (VM-only path).
    * *Identified Blockers/Dependencies:* Session Manager, VM Manager.

* **Story:** As an API consumer, I can control network policy at runtime.
  * **Task:** Implement `routes/network.py`:
    - `GET /sessions/{sid}/network` — call `NetworkPolicyEngine.get_rules()`, return `NetworkPolicyResponse`.
    - `POST /sessions/{sid}/network/allow` — parse `NetworkActionRequest`, call `NetworkPolicyEngine.allow_domain()`, return IPs resolved.
    - `POST /sessions/{sid}/network/block` — similar to allow.
    - `POST /sessions/{sid}/network/reset` — call `NetworkPolicyEngine.reset_network()`, return 204.
    * *Identified Blockers/Dependencies:* Network Manager.

* **Story:** As an API consumer, I can view proxy status and logs.
  * **Task:** Implement `routes/proxy.py`:
    - `GET /sessions/{sid}/proxy` — call `AuthProxyManager.get_proxy_config()`, return status.
    - `GET /sessions/{sid}/proxy/logs` — call `AuthProxyManager.get_request_logs()`, return entries.
    * *Identified Blockers/Dependencies:* Auth Proxy Manager.

* **Story:** As an API consumer, I can view shared folder info and trigger sync.
  * **Task:** Implement `routes/shared.py`:
    - `GET /sessions/{sid}/shared` — return shared folder paths from metadata.
    - `POST /sessions/{sid}/shared/sync` — trigger resync (placeholder for rsync fallback), return 202.
    * *Identified Blockers/Dependencies:* Storage Manager.

* **Story:** As an API consumer, I can manage base images.
  * **Task:** Implement `routes/images.py`:
    - `POST /images` — multipart upload, call `StorageManager.upload_image()`, return 201.
    - `GET /images` — call `StorageManager.list_images()`, return list.
    - `GET /images/{name}` — call `StorageManager.get_image()`, return metadata.
    - `DELETE /images/{name}` — call `StorageManager.delete_image()`, return 204.
    * *Identified Blockers/Dependencies:* Storage Manager.

* **Story:** As an API consumer, I can query host health, capacity, and capabilities.
  * **Task:** Implement `routes/health.py`:
    - `GET /health` — call `HealthChecker.check_host_health()`, return status (no auth required).
    - `GET /capacity` — call `HostManager.get_capacity()`, return available resources.
    - `GET /capabilities` — call `OrchestratorAdapter.capabilities()`, return `CapabilitiesResponse`.
    - `GET /metrics` — return Prometheus text from `MetricsCollector`.
    * *Identified Blockers/Dependencies:* Observability, Host Manager, Orchestrator Adapter.

* **Story:** As a developer, I have auto-generated OpenAPI documentation.
  * **Task:** Verify FastAPI auto-generates OpenAPI at `/docs` and `/redoc` with all endpoints, request/response schemas, and authentication requirements documented.
    * *Identified Blockers/Dependencies:* All routes implemented.

---

## 5. Error Handling

| Error Condition | HTTP Code | Error Code |
|---|---|---|
| Missing/invalid API key | 401 | `unauthorized` |
| Insufficient permissions | 403 | `forbidden` |
| Session not found | 404 | `not_found` |
| Invalid request payload | 400 | `invalid_spec` or `validation_error` |
| Name conflict (VM/session name taken) | 409 | `name_conflict` |
| Insufficient host resources | 507 | `capacity_exceeded` |
| Image incompatible (e.g., needs KVM) | 422 | `image_incompatible` |
| Internal server error | 500 | `internal_error` |
