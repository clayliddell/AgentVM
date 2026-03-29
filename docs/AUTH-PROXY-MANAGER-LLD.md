# Auth Proxy Manager — Low-Level Design

## Component Name: Auth Proxy Manager

The Auth Proxy Manager orchestrates per-session HTTP proxy processes that run on the host. Each proxy intercepts API requests from a VM, validates the dummy key and source IP, replaces the dummy key with the real API key, and forwards the request to the upstream API. The proxy binary itself is a static Go binary with minimal attack surface.

**Source files (Python):** `src/agentvm/proxy/manager.py`, `src/agentvm/proxy/config.py`, `src/agentvm/proxy/client.py`
**Source files (Go):** `proxy/cmd/proxy/main.go`, `proxy/internal/handler.go`, `proxy/internal/config.go`, `proxy/internal/validate.go`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| PX-FR-01 | Allocate a unique port per session from a configurable range (default starting at 23760) | 5.5.1 |
| PX-FR-02 | Generate a unique dummy key per session: `sk-proxy-<session-id>` | 5.5.1, 4.3 |
| PX-FR-03 | Write proxy config YAML to `/var/lib/agentvm/proxy/<session-id>/config.yaml` containing upstream endpoints and key references | 5.5.1 |
| PX-FR-04 | Start the proxy Go binary as a managed subprocess with hardened security context | 5.5.2 |
| PX-FR-05 | Stop the proxy process on session destroy and clean up config directory | 5.5.1 |
| PX-FR-06 | Health-check the proxy via HTTP probe | 5.5.1 |
| PX-FR-07 | The Go proxy binary validates incoming requests: source IP must match the session's VM IP, Authorization header must match the dummy key | 5.5.2 |
| PX-FR-08 | The Go proxy binary replaces the dummy key with the real API key and forwards to the upstream endpoint | 5.5.2 |
| PX-FR-09 | The Go proxy binary logs every request (method, path, status, model, token counts, duration) to a structured log file | 5.5.2, 5.7 |
| PX-FR-10 | The Go proxy binary must be a static binary (CGO_ENABLED=0), run with no shell, no writable filesystem, no capabilities | 5.5.2 |
| PX-FR-11 | The Go proxy binary must bind only to `localhost:<port>` (or bridge IP for VM access) | 5.5.2 |
| PX-FR-12 | Support multiple upstream providers (OpenAI, Anthropic, etc.) via config | 5.5.3 |
| PX-FR-13 | Return proxy request logs via the Python manager for the REST API | 6.1 (`/sessions/{sid}/proxy/logs`) |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| PX-NFR-01 | Proxy startup must complete within 2 seconds | Reliability |
| PX-NFR-02 | Request forwarding latency overhead must be <50ms | Performance |
| PX-NFR-03 | The Go binary must have zero runtime dependencies (no libc, no shell) | Security (5.5.2) |
| PX-NFR-04 | The Go binary must not have access to any filesystem path outside its config directory | Security (5.5.2) |
| PX-NFR-05 | Unit test coverage ≥90% for proxy config generation and key management (security-critical) | 12.1 |
| PX-NFR-06 | Proxy process must be immune to shell injection — no `sh -c` invocation | Security |
| PX-NFR-07 | Port allocation must be deterministic and avoid collisions under concurrent session creation | Reliability |

---

## 3. Component API Contracts

### 3.1 Python Manager — Inputs (Methods Exposed)

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class ProxyConfig:
    session_id: str
    port: int
    dummy_key: str
    base_url: str                      # e.g., "http://10.0.0.1:23760"
    upstream_endpoints: dict[str, str] # {"openai": "https://api.openai.com", ...}

@dataclass
class ProxyRequestLog:
    timestamp: str
    method: str
    path: str
    status_code: int
    upstream: str
    model: Optional[str]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    duration_ms: int

class AuthProxyManager:
    def create_proxy(self, session_id: str, api_keys: dict[str, str],
                     vm_ip: str) -> ProxyConfig:
        """Allocate port, generate dummy key, write config, start proxy process."""

    def destroy_proxy(self, session_id: str) -> None:
        """Stop proxy process, remove config directory. Idempotent."""

    def health_check(self, session_id: str) -> bool:
        """HTTP probe to proxy health endpoint. Returns True if responsive."""

    def get_proxy_config(self, session_id: str) -> Optional[ProxyConfig]:
        """Retrieve current proxy config for a session."""

    def get_request_logs(self, session_id: str, limit: int = 100) -> list[ProxyRequestLog]:
        """Read proxy request logs for a session."""

    def get_running_port(self, session_id: str) -> Optional[int]:
        """Check if proxy is running and return its port."""

    def is_port_available(self, port: int) -> bool:
        """Check if a port is not in use by any proxy."""
```

### 3.2 Go Binary — Interface

The Go binary is configured via a YAML config file and command-line flags:

```yaml
# /var/lib/agentvm/proxy/<session-id>/config.yaml
session_id: "sess-a1b2c3d4"
listen_port: 23760
listen_address: "10.0.0.1"           # Bridge IP (host side)
vm_ip: "10.0.0.2"                    # Expected source IP
dummy_key: "sk-proxy-sess-a1b2c3d4"
log_path: "/var/lib/agentvm/logs/proxy-sess-a1b2c3d4.log"

upstreams:
  openai:
    base_url: "https://api.openai.com"
    api_key_env: ""                   # Real key injected via env var at launch
    api_key: "sk-real-openai-key-..." # Real key (read from env, not stored in file)
  anthropic:
    base_url: "https://api.anthropic.com"
    api_key: "sk-ant-real-key-..."
```

**Proxy request flow:**
```
1. Receive HTTP request on listen_port
2. Extract source IP from connection
3. Validate: source_ip == config.vm_ip → reject if not
4. Extract Authorization header
5. Validate: header == config.dummy_key → reject if not
6. Determine upstream from request path (e.g., /v1/* → openai)
7. Replace Authorization header with real API key from config
8. Forward request to upstream.base_url + request path
9. Stream response back to VM
10. Log: timestamp, method, path, status, model (from request body), token counts (from response), duration
```

### 3.3 Dependencies

| Component This Depends On | Purpose |
|---|---|
| **Storage Manager** | Proxy config directory creation (`storage.create_proxy_config_dir()`) |
| **Config** | Port range start, binary path, default user |
| **Metadata Store** | Proxy records in `proxies` table |
| **Observability** | Audit event emission, proxy request log format |

| Components That Call This | Purpose |
|---|---|
| **Session Manager** | `create_proxy()` on session create, `destroy_proxy()` on session destroy, `health_check()` on status |
| **REST API** | Proxy status and logs endpoints (`/sessions/{sid}/proxy`, `/sessions/{sid}/proxy/logs`) |
| **CLI** | `agentvm proxy status/logs` commands |

---

## 4. Implementation Plan (Mapped to HLD Phases)

### Phase 2: Session Model + Auth Proxy (Week 2-3)

**Phase Goal:** Auth proxy Go binary is built, manager can start/stop proxies, proxy intercepts and forwards API calls.

**User Stories & Tasks:**

* **Story:** As a developer, I have a statically compiled Go auth proxy binary.
  * **Task:** Implement `proxy/internal/config.go` — config struct and YAML parser. Support fields: session_id, listen_port, listen_address, vm_ip, dummy_key, log_path, upstreams map. Read real API keys from environment variables at startup (not from config file).
    * *Identified Blockers/Dependencies:* None.
  * **Task:** Implement `proxy/internal/validate.go` — request validation logic: check source IP matches `config.vm_ip`, check Authorization header matches `config.dummy_key`. Return descriptive error on validation failure.
    * *Identified Blockers/Dependencies:* config.go.
  * **Task:** Implement `proxy/internal/handler.go` — HTTP handler implementing the proxy flow:
    1. Validate request (source IP + dummy key).
    2. Determine upstream from request path prefix.
    3. Replace Authorization header with real key from config.
    4. Forward request using `net/http/httputil.ReverseProxy` or manual forwarding.
    5. Stream response back.
    6. Log request details (method, path, status, model parsed from body, token counts from response body, duration).
    * *Identified Blockers/Dependencies:* validate.go, config.go.
  * **Task:** Implement `proxy/cmd/proxy/main.go` — entrypoint: parse config path from CLI flag, load config, start HTTP server on `listen_address:listen_port`, handle graceful shutdown on SIGTERM. Health endpoint at `GET /health`.
    * *Identified Blockers/Dependencies:* handler.go, config.go.
  * **Task:** Implement `proxy/Makefile` — `CGO_ENABLED=0 go build -o agentvm-auth-proxy ./cmd/proxy/` to produce static binary.
    * *Identified Blockers/Dependencies:* All Go source files.

* **Story:** As a Python daemon, I can start and stop per-session proxy processes.
  * **Task:** Implement `AuthProxyManager.create_proxy()`:
    1. Allocate port from `auth_proxy.port_range_start` + offset (scan for first available).
    2. Generate dummy key: `sk-proxy-<session-id>`.
    3. Create proxy config directory via Storage Manager.
    4. Write `config.yaml` with session info, port, vm_ip, dummy_key, and upstream real API keys (keys passed via env vars to the subprocess, not written to file).
    5. Start proxy binary as subprocess: `subprocess.Popen([binary_path, "-config", config_path], env={**os.environ, "OPENAI_API_KEY": key, ...})`. Run as dedicated `agentvm-proxy` user if possible.
    6. Record proxy in `proxies` metadata table.
    7. Wait for health check to pass (poll `GET /health` with timeout).
    8. Return `ProxyConfig`.
    * *Identified Blockers/Dependencies:* Storage Manager (proxy config dir), Go binary built, Metadata Store.
  * **Task:** Implement `AuthProxyManager.destroy_proxy()`:
    1. Send SIGTERM to proxy subprocess.
    2. Wait up to 5 seconds for graceful exit.
    3. Send SIGKILL if still running.
    4. Remove config directory via Storage Manager.
    5. Delete proxy record from metadata.
    * *Identified Blockers/Dependencies:* `create_proxy()`.

* **Story:** As a Session Manager, I can health-check the proxy.
  * **Task:** Implement `AuthProxyManager.health_check()` — HTTP GET to `http://<listen_address>:<port>/health`, return True if 200 OK within 2 seconds.
    * *Identified Blockers/Dependencies:* Go binary health endpoint.

* **Story:** As a platform operator, I can read proxy request logs.
  * **Task:** Implement `AuthProxyManager.get_request_logs()` — read and parse the proxy's structured log file, return `list[ProxyRequestLog]`.
    * *Identified Blockers/Dependencies:* Go binary must write structured logs.

* **Story:** As a developer, I have unit tests for proxy config generation and integration tests for proxy forwarding.
  * **Task:** Implement `test_auth_proxy.py` (unit) — test config YAML generation, dummy key format, port allocation logic.
  * **Task:** Implement `test_auth_proxy.py` (integration) — start real proxy, send HTTP request with dummy key from VM IP, verify request reaches mock upstream with real key injected.
  * **Task:** Implement `test_proxy_security.py` (integration) — send request with wrong source IP (rejected), wrong dummy key (rejected), attempt direct upstream access without proxy (fails).
    * *Identified Blockers/Dependencies:* Go binary, VM with SSH access for integration tests.

---

### Phase 3: API + CLI (Week 3-4)

**Phase Goal:** Proxy status and logs accessible via REST API and CLI.

**User Stories & Tasks:**

* **Story:** As an API consumer, I can get proxy status and request logs.
  * **Task:** Ensure `get_proxy_config()` and `get_request_logs()` return data compatible with REST API schemas.
    * *Identified Blockers/Dependencies:* Phase 2 proxy implementation.

---

### Phase 6: Observability + Security (Week 6-7)

**Phase Goal:** Proxy security is validated via red-team tests.

**User Stories & Tasks:**

* **Story:** As a security engineer, the proxy is verified to be immune to key extraction attacks.
  * **Task:** Implement red-team tests:
    - `test_escape_proxy.py` — attempt to read proxy process memory via `/proc/<pid>/mem` (should be denied).
    - `test_proxy_security.py` — attempt to connect directly to upstream API without proxy (should fail with auth error).
    - Attempt proxy request replay with modified headers (should fail source IP + dummy key validation).
    * *Identified Blockers/Dependencies:* Red-team test infrastructure.

---

## 5. Go Binary Security Hardening

The Go binary is hardened at build time and runtime:

**Build time:**
- `CGO_ENABLED=0` — static binary, no libc dependency
- `-ldflags="-s -w"` — strip debug symbols
- No `os/exec`, no `syscall.Exec` — the binary cannot spawn subprocesses

**Runtime (configured via systemd or subprocess launch):**
- `User=agentvm-proxy` — dedicated non-root UID
- `CapabilityBoundingSet=` — drop all capabilities
- `NoNewPrivileges=yes`
- `ProtectSystem=strict` — read-only filesystem; proxy config dir mounted read-only (config read at startup, no writes needed at runtime)
- `PrivateTmp=yes`
- `RestrictAddressFamilies=AF_INET AF_INET6` — only allow IPv4/IPv6 socket calls
- `SystemCallFilter=@system-service` — minimal seccomp allowlist

## 6. Error Handling

| Error Condition | Handling |
|---|---|
| Port range exhausted | Raise `ProxyError("no available ports in range")` |
| Proxy binary not found | Raise `DependencyError` with binary path and build instructions |
| Proxy fails to start (crash on launch) | Retry once, then raise `ProxyError` with stderr output |
| Proxy health check timeout (10s) | Kill process, raise `ProxyError` |
| Proxy process dies unexpectedly | Session Manager detects via health check, marks session as `error` |
| Config YAML write failure | Rollback: do not start process, raise `StorageError` |
| API key not provided in env | Proxy starts but rejects all requests to that upstream |
