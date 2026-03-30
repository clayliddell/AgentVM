# Phase 3: API + CLI

> **Note:** Task tracking has moved to VibeKanban. Do not edit task status in this file.
> Refer to the Kanban board for current status and blocking relationships.
> This file is the source of truth for requirements, FRs, and E2E tests only.
> See `dev/todo/todo.md` for details.

**Goal:** Full REST API and CLI for session lifecycle, network control, and observability.

**Weeks:** 3–4

---

## Session Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| SessionManager.async_compat | Ensure Session Manager methods are async-compatible — wrap blocking libvirt calls in `asyncio.to_thread()` so FastAPI endpoints don't block the event loop. Ref: SESSION-LLD §7.1 | High | Blocked |

## REST API

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| API.app_setup | Implement `app.py` — FastAPI app, include all route modules, configure CORS, add startup/shutdown events. Ref: REST-API-LLD §5.1 | High | Blocked |
| API.auth_middleware | Implement `auth.py` — Bearer token auth dependency. Extract token from `Authorization` header, validate against `api.api_keys`. Return 401 on invalid/missing. Skip auth for `/health`. Ref: REST-API-LLD §5.1 | High | Blocked |
| API.error_handlers | Implement `errors.py` — exception handlers mapping internal exceptions to HTTP status codes and `ErrorResponse` schemas with `ErrorCode` enum. Ref: REST-API-LLD §5.1 | Medium | Blocked |
| API.session_routes | Implement `routes/sessions.py`: `POST /sessions`, `GET /sessions`, `GET /sessions/{sid}`, `DELETE /sessions/{sid}`, `GET /sessions/{sid}/ssh`. All use `async def` with `asyncio.to_thread()`. Ref: REST-API-LLD §5.2 | High | Blocked |
| API.vm_routes | Implement `routes/vms.py` — `POST/GET/DELETE /vms`, `GET /vms/{vm_id}`. Ref: REST-API-LLD §5.3 | Medium | Blocked |
| API.network_routes | Implement `routes/network.py`: `GET /sessions/{sid}/network`, `POST /sessions/{sid}/network/allow`, `POST /sessions/{sid}/network/block`, `POST /sessions/{sid}/network/reset`. Ref: REST-API-LLD §5.4 | High | Blocked |
| API.proxy_routes | Implement `routes/proxy.py`: `GET /sessions/{sid}/proxy`, `GET /sessions/{sid}/proxy/logs`. Ref: REST-API-LLD §5.5 | Medium | Blocked |
| API.shared_routes | Implement `routes/shared.py`: `GET /sessions/{sid}/shared`, `POST /sessions/{sid}/shared/sync`. Ref: REST-API-LLD §5.6 | Low | Blocked |
| API.audit_routes | Implement `routes/audit.py`: `GET /sessions/{sid}/audit`, `GET /audit` (global). Ref: REST-API-LLD §5.7 | Medium | Blocked |
| API.image_routes | Implement `routes/images.py`: `POST /images`, `GET /images`, `GET /images/{name}`, `DELETE /images/{name}`. Ref: REST-API-LLD §5.8 | Medium | Blocked |
| API.health_routes | Implement `routes/health.py`: `GET /health`, `GET /capacity`, `GET /capabilities`, `GET /metrics`. Ref: REST-API-LLD §5.9 | High | Blocked |
| API.openapi_docs | Verify FastAPI auto-generates OpenAPI at `/docs` and `/redoc`. Ref: REST-API-LLD §5.10 | Low | Blocked |

## CLI

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| CLI.main_setup | Implement `main.py` — Click group with global options (`--api-url`, `--api-key`, `--format`, `--verbose`). Create HTTP client helper. Ref: CLI-LLD §5.1 | High | Blocked |
| CLI.session_commands | Implement `session` group with `create`, `destroy`, `list`, `status` commands. Ref: CLI-LLD §5.2 | High | Blocked |
| CLI.network_commands | Implement `network` group with `allow`, `block`, `reset`, `list` commands. Ref: CLI-LLD §5.3 | High | Blocked |
| CLI.proxy_commands | Implement `proxy` group with `status` and `logs` commands. Ref: CLI-LLD §5.4 | Medium | Blocked |
| CLI.ssh_command | Implement `ssh` command — GET SSH info from API, print `ssh` command string, or exec directly. Ref: CLI-LLD §5.5 | Medium | Blocked |
| CLI.host_commands | Implement `host` group with `health` and `capacity` commands. Ref: CLI-LLD §5.6 | Medium | Blocked |
| CLI.image_commands | Implement `images` group and `capabilities` command. Ref: CLI-LLD §5.7 | Medium | Blocked |
| CLI.test_cli | Implement `test_cli.py` — test each command with Click's `CliRunner`, mock HTTP responses. Ref: CLI-LLD §5.8 | Medium | Blocked |

## Auth Proxy Manager

| Task Name | Task Description | Priority | Status |
|-----------|-----------------|----------|--------|
| AuthProxy.api_compat | Ensure `get_proxy_config()` and `get_request_logs()` return data compatible with REST API schemas. Ref: AUTH-PROXY-LLD §7.1 | Low | Blocked |

---

## Phase 3 Functional Requirements

| FR | Requirement | Verification |
|----|-------------|-------------|
| P3-FR-01 | All REST API endpoints return correct HTTP status codes and response schemas | OpenAPI validation against LLD schemas |
| P3-FR-02 | Bearer token authentication is enforced on all endpoints except `/health` | Requests without token return 401; requests with invalid token return 401; `/health` returns 200 without token |
| P3-FR-03 | CLI commands map correctly to REST API endpoints and display results in configured format (table/json) | Click test with `CliRunner` and mocked HTTP responses |
| P3-FR-04 | `--provider-key` flag on `session create` passes upstream API keys without collision with daemon auth `--api-key` | CLI sends correct `api_keys` in request body |
| P3-FR-05 | `async def` API endpoints do not block the event loop — blocking libvirt calls wrapped in `asyncio.to_thread()` | Concurrent API requests do not deadlock |
| P3-FR-06 | Global `GET /audit` and session-scoped `GET /sessions/{sid}/audit` both return correct audit entries | Audit events appear in both endpoints after session operations |
| P3-FR-07 | `ErrorResponse` schema includes `ErrorCode` enum for machine-readable error classification | All error responses contain `code` field matching defined enum |
| P3-FR-08 | FastAPI auto-generates OpenAPI documentation at `/docs` and `/redoc` | Swagger UI loads and shows all endpoints |
| P3-FR-09 | Network policy endpoints return `NetworkPolicyResponse` with mode, vm_ip, vnet_name, rules, default_action | `GET /sessions/{sid}/network` returns complete policy summary |
| P3-FR-10 | SSH info endpoint returns correct connection string for session VM | `GET /sessions/{sid}/ssh` returns `ssh` command with correct host, port, key path |

## Phase 3 E2E Tests (Must Pass for Phase Completion)

All of the following E2E tests must pass before this phase can be marked COMPLETE:

- [ ] **E2E-3.1: REST API session lifecycle** — `POST /sessions` → `GET /sessions/{sid}` → `DELETE /sessions/{sid}` — verify session is created, status is running, then destroyed
- [ ] **E2E-3.2: API authentication** — Send request without token (401), with wrong token (401), with valid token (200), to `/health` without token (200)
- [ ] **E2E-3.3: CLI session create** — `agentvm session create --name test --image ubuntu-22.04 --cpu 2 --memory 4096` — verify API receives correct request body
- [ ] **E2E-3.4: CLI session list** — `agentvm session list` — verify CLI displays all sessions in table format
- [ ] **E2E-3.5: CLI network control** — `agentvm network allow <sid> api.openai.com` → verify API receives correct allow request
- [ ] **E2E-3.6: CLI SSH** — `agentvm ssh <sid>` — verify CLI prints correct SSH connection command
- [ ] **E2E-3.7: API network policy** — `GET /sessions/{sid}/network` returns `NetworkPolicyResponse` with all fields populated
- [ ] **E2E-3.8: API audit** — Create session, destroy session, `GET /audit` — verify both `session.create` and `session.stop` events present
- [ ] **E2E-3.9: OpenAPI docs** — Navigate to `http://localhost:<port>/docs`, verify Swagger UI loads with all endpoints visible
