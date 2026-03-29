# Daemon Entrypoint — Low-Level Design

## Component Name: Daemon Entrypoint

The Daemon Entrypoint (`daemon.py`) is the initialization and wiring layer for the AgentVM platform daemon. It is responsible for constructing all components in dependency order, running startup checks, starting the REST API server, handling signals, and performing graceful shutdown. It is the outermost orchestration layer — the single process that hosts all other components.

**Source files:** `src/agentvm/daemon.py`, `src/agentvm/__main__.py`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| DE-FR-01 | Load configuration from file/env/CLI flags and construct the `Config` object | 14 |
| DE-FR-02 | Initialize the Metadata Store (open SQLite, enable WAL, create schema, run migrations) | 5.6 |
| DE-FR-03 | Ensure storage directory tree exists via Storage Manager | 5.4 |
| DE-FR-04 | Ensure NAT bridge exists via Network Manager | 5.3 |
| DE-FR-05 | Run host hardening verification via Host Manager | 4.4 |
| DE-FR-06 | Reconcile in-memory capacity allocations from metadata store (recover from previous crash) | 5.1 |
| DE-FR-07 | Detect and clean up orphaned sessions from previous daemon instance | Phase 7 |
| DE-FR-08 | Build all component instances in correct dependency order | All |
| DE-FR-09 | Start the FastAPI/Uvicorn HTTP server on configured host:port | 14 |
| DE-FR-10 | Start the Prometheus metrics exporter on configured port | 5.7 |
| DE-FR-11 | Handle SIGTERM/SIGINT for graceful shutdown | 14 |
| DE-FR-12 | Drain all active sessions on shutdown (destroy each with timeout) | 5.2 |
| DE-FR-13 | Close metadata store connection on shutdown | 5.6 |
| DE-FR-14 | Log startup sequence progress via structlog | 14 |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| DE-NFR-01 | Daemon startup must complete within 10 seconds (excluding hardening checks) | 6.3 |
| DE-NFR-02 | Graceful shutdown must complete within 60 seconds (session drain timeout) | 5.2 |
| DE-NFR-03 | All startup failures must log the specific component and reason before exiting | Reliability |
| DE-NFR-04 | Daemon must refuse to start if critical prerequisites fail (cgroups v2, libvirtd) | Safety |

---

## 3. Startup Sequence

```python
# daemon.py — simplified startup flow

def main(config_path: str) -> None:
    # 1. Load config
    config = load_config(config_path)

    # 2. Configure logging
    configure_logging(config.observability.log_level)

    # 3. Initialize metadata store
    store = MetadataStore(config.storage.base_dir + "/metadata.db")
    store.initialize()          # WAL mode, schema creation, migrations

    # 4. Initialize Storage Manager
    storage = StorageManager(config)
    storage.ensure_storage_tree()

    # 5. Initialize Host Manager
    host = HostManager(config, store)
    hardening_report = host.verify()
    if not hardening_report.passed and config.security.refuse_start_on_hardening_fail:
        raise FatalStartupError("Hardening check failed")

    # 6. Reconcile capacity (recover from crash)
    host.reconcile_allocations()  # Rebuild in-memory state from active VMs in DB

    # 7. Clean up orphaned sessions
    orphaned = store.get_sessions_by_status_and_age("creating", older_than="5 minutes")
    for session in orphaned:
        destroy_orphaned_session(session, storage, store)

    # 8. Initialize Network Manager
    network = NetworkPolicyEngine(config, store)
    network.ensure_bridge()     # Bridge creation is idempotent

    # 9. Initialize Auth Proxy Manager
    proxy = AuthProxyManager(config, storage, store)

    # 10. Initialize VM Manager
    vm = VMManager(config, store, host, network, storage)

    # 11. Initialize Session Manager (wires all dependencies)
    session_mgr = SessionManager(config, vm, proxy, network, storage, store, host)

    # 12. Initialize Orchestrator Adapter
    orchestrator = AgentVMBackend(session_mgr, network, proxy, storage, host)

    # 13. Initialize Observability
    metrics = MetricsCollector(config, store, host, vm, proxy)
    metrics.start_exporter(config.observability.metrics_port)

    health = HealthChecker(vm, proxy, storage, host)

    # 14. Build and start FastAPI app
    app = create_app(
        session_manager=session_mgr,
        vm_manager=vm,
        network_engine=network,
        proxy_manager=proxy,
        storage_manager=storage,
        host_manager=host,
        orchestrator_adapter=orchestrator,
        metrics_collector=metrics,
        health_checker=health,
        config=config,
    )

    # 15. Register signal handlers
    signal.signal(signal.SIGTERM, lambda *_: graceful_shutdown(...))
    signal.signal(signal.SIGINT, lambda *_: graceful_shutdown(...))

    # 16. Run server (blocks until shutdown)
    uvicorn.run(app, host=config.api.host, port=config.api.port)
```

### Shutdown Sequence

```python
def graceful_shutdown() -> None:
    # 1. Stop accepting new API requests
    server.should_exit = True

    # 2. Drain active sessions
    session_mgr.drain_all_sessions(timeout=60)

    # 3. Stop metrics exporter
    metrics.stop_exporter()

    # 4. Close metadata store
    store.close()

    log.info("Daemon shutdown complete")
```

---

## 4. Component Construction Order

Components must be built in dependency order. The construction graph:

```
Config
  └→ MetadataStore
       └→ StorageManager
       └→ HostManager (needs store for reconciliation)
       └→ NetworkPolicyEngine (needs store)
       └→ AuthProxyManager (needs storage, store)
       └→ VMManager (needs store, host, network, storage)
            └→ SessionManager (needs vm, proxy, network, storage, store, host)
                 └→ AgentVMBackend (needs session_mgr, network, proxy, storage, host)
                 └→ MetricsCollector (needs store, host, vm, proxy)
                 └→ HealthChecker (needs vm, proxy, storage, host)
                      └→ FastAPI App (needs all of the above)
```

---

## 5. Dependencies

| Component This Depends On | Purpose |
|---|---|
| **All components** | Daemon instantiates and wires all components |
| **Config** | Configuration loading |

| Components That Call This | Purpose |
|---|---|
| **`__main__.py`** | CLI entrypoint: `python -m agentvm daemon [--config <path>]` |
| **systemd** | `ExecStart=/usr/bin/agentvm daemon --config /etc/agentvm/config.yaml` |

---

## 6. Implementation Plan

### Phase 1: Foundation (Week 1-2)

**Phase Goal:** Daemon starts, initializes store, runs API server.

**User Stories & Tasks:**

* **Story:** As a developer, the daemon starts and serves API requests.
  * **Task:** Implement `daemon.py` — config loading, metadata store init, storage tree ensure, bridge ensure, component wiring, uvicorn startup. Minimal viable startup sequence (steps 1-5, 8, 14-16 from Section 3).
    * *Identified Blockers/Dependencies:* Config, MetadataStore, StorageManager, NetworkManager, REST API app.

* **Story:** As a developer, the daemon shuts down gracefully on SIGTERM.
  * **Task:** Implement signal handlers, session drain loop, store close.
    * *Identified Blockers/Dependencies:* SessionManager.drain_all_sessions().

---

### Phase 7: Orchestrator Adapter + Production (Week 7-8)

**Phase Goal:** Full startup with hardening, reconciliation, orphan cleanup.

**User Stories & Tasks:**

* **Story:** As a platform operator, the daemon reconciles state and cleans up orphans on startup.
  * **Task:** Implement `reconcile_allocations()` call and orphan cleanup loop (steps 6-7).
    * *Identified Blockers/Dependencies:* HostManager.reconcile_allocations(), metadata store orphan query.

---

## 7. Error Handling

| Error Condition | Handling |
|---|---|
| Config file not found | Log error, exit with code 1 |
| Metadata store init failure (DB corrupt) | Log fatal error, exit with code 1 |
| cgroups v2 not mounted | Log fatal error, refuse to start |
| libvirtd not running | Log fatal error, refuse to start |
| Hardening check failure (critical) | Log fatal error, refuse to start if configured |
| Hardening check failure (warning) | Log warning, continue startup |
| Bridge creation failure | Log fatal error, exit with code 1 |
| Port already in use (API) | Log fatal error with port number, exit with code 1 |
| Session drain timeout | Log warning, force-destroy remaining sessions |
