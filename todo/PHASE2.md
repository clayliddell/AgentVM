# Phase 2: Session Model + Auth Proxy

**Goal:** Session abstraction wrapping VM lifecycle with auth proxy and shared folder.

**Weeks:** 2–3

---

## Session Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| SessionManager.workload_session_model | Implement `model.py` — `WorkloadSession` dataclass matching HLD §5.2 definition. Ref: SESSION-LLD §5.1 | High | Blocked |
| SessionManager.state_machine | Implement `state.py` — session state machine with transitions: requested → creating → running → shutdown → destroyed, and any state → error. Define `InvalidTransitionError`. Ref: SESSION-LLD §5.2 | High | Blocked |
| SessionManager.create_session | Implement `SessionManager.create_session()` — orchestrate full sequence: validate, check capacity, allocate vnet, create shared folder, generate cloud-init, start proxy, create VM, resolve IP, apply network rules, transition to `running`. Ref: SESSION-LLD §5.3 | High | Blocked |
| SessionManager.destroy_session | Implement `SessionManager.destroy_session()` — destroy VM, stop proxy, clean network rules, remove shared folder, purge metadata, transition to `destroyed`, emit `session.stop`. Ref: SESSION-LLD §5.4 | High | Blocked |
| SessionManager.get_and_list_sessions | Implement `get_session()` — query metadata, enrich with live VM status and proxy health. Implement `list_sessions()` with optional owner filter. Ref: SESSION-LLD §5.5 | Medium | Blocked |
| SessionManager.test_session | Implement `test_session.py` — test state machine, mock sub-components, test create/destroy orchestration, test rollback on partial failure. Ref: SESSION-LLD §5.6 | Medium | Blocked |
| SessionManager.ownership_enforcement | Implement ownership enforcement in all mutating methods — verify `session.owner == caller` before proceeding. Raise `ForbiddenError` on mismatch. Ref: SESSION-LLD §5.7 (SS-FR-12) | High | Blocked |

## VM Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| VMManager.extend_create_vm | Extend `create_vm()` to accept pre-generated cloud-init ISO path and shared folder host path from Session Manager, inject into libvirt XML. Ref: VM-LLD §6.1 | Medium | Blocked |
| VMManager.session_destroy_integration | Ensure `destroy_vm()` integrates with Session Manager destroy flow — VM Manager handles domain + disk cleanup only. Ref: VM-LLD §6.2 | Medium | Blocked |

## Metadata Store

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| MetadataStore.proxy_crud | Implement proxy CRUD: `create_proxy()`, `get_proxy_by_session()`, `update_proxy()`, `delete_proxy()`. Ref: METADATA-LLD §6.1 | High | Blocked |
| MetadataStore.shared_folder_crud | Implement shared folder CRUD: `create_shared_folder()`, `get_shared_folder_by_session()`, `delete_shared_folder()`. Ref: METADATA-LLD §6.1 | High | Blocked |
| MetadataStore.resource_allocation_crud | Implement resource allocation CRUD: `create_resource_allocation()`, `get_allocation_by_vm()`, `delete_allocation()`. Ref: METADATA-LLD §6.1 | Medium | Blocked |

## Storage Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| StorageManager.shared_folder_create | Implement `create_shared_folder(session_id, project_path, output_path)` — create `/var/lib/agentvm/shared/<session-id>/` with subdirs `project/` and `output/`, set permissions 0700. Ref: STORAGE-LLD §6.1 | Medium | Blocked |
| StorageManager.shared_folder_delete | Implement `delete_shared_folder(session_id)`. Ref: STORAGE-LLD §6.1 | Medium | Blocked |
| StorageManager.proxy_config_dir_create | Implement `create_proxy_config_dir(session_id)`. Ref: STORAGE-LLD §6.2 | Medium | Blocked |
| StorageManager.proxy_config_dir_delete | Implement `delete_proxy_config_dir(session_id)`. Ref: STORAGE-LLD §6.2 | Medium | Blocked |

## Auth Proxy Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| AuthProxy.proxy_config_go | Implement `proxy/internal/config.go` — config struct and YAML parser. Read real API keys from environment variables. Ref: AUTH-PROXY-LLD §5.1 | High | Blocked |
| AuthProxy.proxy_validate_go | Implement `proxy/internal/validate.go` — request validation: check source IP matches `config.vm_ip`, check Authorization header matches `config.dummy_key`. Ref: AUTH-PROXY-LLD §5.1 | High | Blocked |
| AuthProxy.proxy_handler_go | Implement `proxy/internal/handler.go` — HTTP handler: validate, determine upstream from path, replace auth header with real key, forward, stream response, log. Ref: AUTH-PROXY-LLD §5.1 | High | Blocked |
| AuthProxy.proxy_main_go | Implement `proxy/cmd/proxy/main.go` — entrypoint: parse config path, load config, start HTTP server, graceful shutdown on SIGTERM. Health endpoint at `GET /health`. Ref: AUTH-PROXY-LLD §5.1 | High | Blocked |
| AuthProxy.proxy_makefile | Implement `proxy/Makefile` — `CGO_ENABLED=0 go build -o agentvm-auth-proxy ./cmd/proxy/`. Ref: AUTH-PROXY-LLD §5.1 | Medium | Blocked |
| AuthProxy.create_proxy | Implement `AuthProxyManager.create_proxy()`: allocate port, generate dummy key, create config dir, write config.yaml, start subprocess, record in metadata, wait for health check, return `ProxyConfig`. Ref: AUTH-PROXY-LLD §5.2 | High | Blocked |
| AuthProxy.destroy_proxy | Implement `AuthProxyManager.destroy_proxy()`: SIGTERM, wait for exit, SIGKILL if needed, remove config dir, delete metadata record. Ref: AUTH-PROXY-LLD §5.2 | High | Blocked |
| AuthProxy.health_check | Implement `AuthProxyManager.health_check()` — HTTP GET to `http://<listen_address>:<port>/health`. Ref: AUTH-PROXY-LLD §5.3 | Medium | Blocked |
| AuthProxy.get_request_logs | Implement `AuthProxyManager.get_request_logs()` — read and parse proxy structured log file. Ref: AUTH-PROXY-LLD §5.4 | Low | Blocked |
| AuthProxy.test_unit | Implement `test_auth_proxy.py` (unit) — test config YAML generation, dummy key format, port allocation logic. Ref: AUTH-PROXY-LLD §5.5 | Medium | Blocked |
| AuthProxy.test_integration | Implement `test_auth_proxy.py` (integration) — start real proxy, send HTTP request with dummy key from VM IP, verify request reaches mock upstream. Ref: AUTH-PROXY-LLD §5.5 | Medium | Blocked |
| AuthProxy.test_security | Implement `test_proxy_security.py` (integration) — wrong source IP rejected, wrong dummy key rejected, direct upstream access fails. Ref: AUTH-PROXY-LLD §5.5 | High | Blocked |

---

## Phase 2 Functional Requirements

| FR | Requirement | Verification |
|----|-------------|-------------|
| P2-FR-01 | Session state machine enforces valid transitions: requested → creating → running → shutdown → destroyed; any state → error | Invalid transitions raise `InvalidTransitionError` |
| P2-FR-02 | `create_session()` provisions all resources atomically — vnet, shared folder, cloud-init, proxy, VM | All resources exist after successful create; rollback on failure cleans up all provisioned resources |
| P2-FR-03 | `destroy_session()` cleans up all resources — VM, proxy, network rules, shared folder, metadata | No orphaned iptables rules, ipsets, cgroup scopes, disk files, or metadata records after destroy |
| P2-FR-04 | Auth proxy intercepts API calls: rejects wrong source IP, rejects wrong dummy key, injects real key into upstream request | Integration test passes with mock upstream |
| P2-FR-05 | Auth proxy config uses environment variables for real API keys — no plaintext keys in config files | Config YAML contains only `api_key_env` fields, not raw keys |
| P2-FR-06 | `get_session()` enriches metadata with live VM status and proxy health | Returned `WorkloadSession` has accurate `status` and proxy health fields |
| P2-FR-07 | Session ownership enforced — only the owning API key can get, destroy, or modify a session | `ForbiddenError` raised on ownership mismatch |
| P2-FR-08 | Shared folder created with correct directory structure and permissions (0700) | `ls -la /var/lib/agentvm/shared/<session-id>/` shows `project/` and `output/` with 0700 |
| P2-FR-09 | Proxy process lifecycle managed correctly — starts on create, stops on destroy, health-checkable | `AuthProxyManager.health_check()` returns true after create; proxy process gone after destroy |
| P2-FR-10 | Rollback on partial failure during `create_session()` is idempotent — re-running cleanup on already-cleaned resources does not error | Rollback function called twice produces no errors |

## Phase 2 E2E Tests (Must Pass for Phase Completion)

All of the following E2E tests must pass before this phase can be marked COMPLETE:

- [ ] **E2E-2.1: Session create** — Create a session via `SessionManager.create_session()`, verify VM boots, proxy is running, shared folder exists, metadata records exist for session + VM + proxy + shared_folder + resource_allocation
- [ ] **E2E-2.2: Session destroy** — Destroy the session, verify VM is gone (libvirt domain undefined), proxy process killed, iptables rules removed, shared folder deleted, metadata records purged
- [ ] **E2E-2.3: Auth proxy forwarding** — Create session, send HTTP request to proxy port with dummy key from VM IP, verify upstream receives request with real API key injected
- [ ] **E2E-2.4: Auth proxy rejection** — Attempt to reach upstream API through proxy with wrong source IP (rejected), wrong dummy key (rejected), and without proxy (auth fails at upstream)
- [ ] **E2E-2.5: Session ownership** — Create session with owner A, attempt to destroy with owner B, verify `ForbiddenError` is raised; destroy with owner A succeeds
- [ ] **E2E-2.6: Rollback on failure** — Simulate failure during session create (e.g., proxy fails to start), verify all previously provisioned resources are cleaned up (no orphans)
- [ ] **E2E-2.7: Session state transitions** — Verify `WorkloadSession` status transitions correctly through requested → creating → running during create; and running → shutdown → destroyed during destroy
