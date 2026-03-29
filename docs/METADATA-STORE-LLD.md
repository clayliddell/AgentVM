# Metadata Store — Low-Level Design

## Component Name: Metadata Store

The Metadata Store provides persistent state management via SQLite. It manages all application records: sessions, VMs, proxies, shared folders, resource allocations, network rules, and audit log entries. It includes schema definition, CRUD operations, and migration support.

**Source files:** `src/agentvm/db/store.py`, `src/agentvm/db/migrations.py`

---

## 1. Functional Requirements

| ID | Requirement | Source (HLD Section) |
|---|---|---|
| DB-FR-01 | Provide CRUD operations for the `sessions` table | 5.6 |
| DB-FR-02 | Provide CRUD operations for the `vms` table | 5.6 |
| DB-FR-03 | Provide CRUD operations for the `proxies` table | 5.6 |
| DB-FR-04 | Provide CRUD operations for the `shared_folders` table | 5.6 |
| DB-FR-05 | Provide CRUD operations for the `resource_allocations` table | 5.6 |
| DB-FR-06 | Provide insert and query operations for the `audit_log` table | 5.6, 5.7 |
| DB-FR-07 | Provide CRUD operations for the `network_rules` table | 5.6 |
| DB-FR-08 | Support session queries filtered by owner and status | 5.6, 11.1 |
| DB-FR-09 | Support audit log queries filtered by session_id and timestamp range | 6.1 |
| DB-FR-10 | Support network rules queries filtered by session_id with active rules only (`removed_at IS NULL`) | 5.6 |
| DB-FR-11 | Initialize database schema on first run (create all tables and indexes) | 5.6 |
| DB-FR-12 | Support schema migrations for future versions | Phase 7 |
| DB-FR-13 | Support concurrent read access (SQLite WAL mode) | Reliability |
| DB-FR-14 | Orphan detection — query for sessions in `creating` state older than a threshold | Phase 7 |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| DB-NFR-01 | All queries must complete within 100ms for typical dataset sizes (≤1000 sessions) | Performance |
| DB-NFR-02 | Unit test coverage ≥80% for store operations | 12.1 |
| DB-NFR-03 | Database must use WAL journal mode for concurrent read/write safety | Reliability |
| DB-NFR-04 | Schema must be versioned — migrations must be idempotent and reversible | Maintainability |
| DB-NFR-05 | Database file must be located at `/var/lib/agentvm/metadata.db` with restricted permissions (0600) | Security |

---

## 3. Component API Contracts

### 3.1 Schema Definition

The schema is defined in HLD Section 5.6. Tables: `sessions`, `vms`, `proxies`, `shared_folders`, `resource_allocations`, `audit_log`, `network_rules`. Indexes on: `sessions.owner`, `sessions.status`, `vms.session_id`, `audit_log.session_id`, `audit_log.timestamp`, `network_rules.session_id`.

### 3.2 Store API

```python
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

class MetadataStore:
    async def initialize(self) -> None:
        """Open database connection, enable WAL mode, create schema if not exists, run migrations."""

    async def close(self) -> None:
        """Close database connection."""

    # Sessions
    async def create_session(self, session: dict) -> str:
        """Insert session record. Returns session ID."""

    async def get_session(self, session_id: str) -> Optional[dict]:
        """Retrieve session by ID."""

    async def update_session(self, session_id: str, updates: dict) -> None:
        """Update session fields (status, stopped_at, etc.)."""

    async def list_sessions(self, owner: Optional[str] = None,
                            status: Optional[str] = None) -> list[dict]:
        """List sessions with optional filters."""

    async def delete_session(self, session_id: str) -> None:
        """Delete session and all related records. Cascade is application-enforced:
        1. DELETE FROM vms WHERE session_id = ?
        2. DELETE FROM proxies WHERE session_id = ?
        3. DELETE FROM shared_folders WHERE session_id = ?
        4. DELETE FROM resource_allocations WHERE vm_id IN (SELECT id FROM vms WHERE session_id = ?)
        5. DELETE FROM network_rules WHERE session_id = ?
        6. DELETE FROM sessions WHERE id = ?
        Audit log entries are NOT deleted (append-only for compliance).
        Note: SQLite foreign keys are NOT used for cascade — this is application-level deletion
        to ensure deterministic ordering and avoid FK constraint issues during partial state."""

    async def get_sessions_by_status_and_age(self, status: str,
                                              older_than: str) -> list[dict]:
        """Find sessions in a given state older than a threshold (for orphan detection)."""

    # VMs
    async def create_vm(self, vm: dict) -> str:
        """Insert VM record. Returns VM ID."""

    async def get_vm(self, vm_id: str) -> Optional[dict]:
        """Retrieve VM by ID."""

    async def get_vm_by_session(self, session_id: str) -> Optional[dict]:
        """Retrieve VM for a session."""

    async def get_vms_by_image(self, base_image: str) -> list[dict]:
        """Retrieve all VMs referencing a given base image (for image deletion guard)."""

    async def update_vm(self, vm_id: str, updates: dict) -> None:
        """Update VM fields."""

    async def delete_vm(self, vm_id: str) -> None:
        """Delete VM record."""

    # Proxies
    async def create_proxy(self, proxy: dict) -> int:
        """Insert proxy record. Returns row ID."""

    async def get_proxy_by_session(self, session_id: str) -> Optional[dict]:
        """Retrieve proxy for a session."""

    async def update_proxy(self, session_id: str, updates: dict) -> None:
        """Update proxy fields."""

    async def delete_proxy(self, session_id: str) -> None:
        """Delete proxy record."""

    # Shared Folders
    async def create_shared_folder(self, folder: dict) -> int:
        """Insert shared folder record."""

    async def get_shared_folder_by_session(self, session_id: str) -> Optional[dict]:
        """Retrieve shared folder for a session."""

    async def delete_shared_folder(self, session_id: str) -> None:
        """Delete shared folder record."""

    # Resource Allocations
    async def create_resource_allocation(self, allocation: dict) -> int:
        """Insert resource allocation record."""

    async def get_allocation_by_vm(self, vm_id: str) -> Optional[dict]:
        """Retrieve resource allocation for a VM."""

    async def delete_allocation(self, vm_id: str) -> None:
        """Delete resource allocation record."""

    # Audit Log
    async def insert_audit_event(self, event: dict) -> int:
        """Insert audit log entry."""

    async def query_audit_log(self, session_id: Optional[str] = None,
                               since: Optional[str] = None,
                               limit: int = 100) -> list[dict]:
        """Query audit log with optional filters."""

    # Network Rules
    async def create_network_rule(self, rule: dict) -> int:
        """Insert network rule record."""

    async def get_network_rules(self, session_id: str,
                                 active_only: bool = True) -> list[dict]:
        """Retrieve network rules for a session."""

    async def deactivate_network_rule(self, rule_id: int) -> None:
        """Mark rule as removed (set removed_at)."""

    async def deactivate_all_network_rules(self, session_id: str) -> None:
        """Mark all rules for a session as removed."""

    async def delete_network_rules(self, session_id: str) -> None:
        """Delete all network rules for a session."""

    # Migrations
    async def get_schema_version(self) -> int:
        """Return current schema version."""

    async def run_migrations(self, target_version: int) -> None:
        """Apply migrations from current version to target."""
```

### 3.3 Dependencies

| Component This Depends On | Purpose |
|---|---|
| **Config** | Database file path (`storage.base_dir` + `/metadata.db`) |

| Components That Call This | Purpose |
|---|---|
| **Session Manager** | All session, VM, proxy, shared folder, resource allocation CRUD |
| **VM Manager** | VM record creation/deletion |
| **Auth Proxy Manager** | Proxy record CRUD |
| **Network Manager** | Network rule CRUD |
| **Observability** | Audit log insert and query |
| **REST API** | All data queries for API responses |
| **Orchestrator Adapter** | Session queries for capability and status reporting |

---

## 4. Implementation Plan (Mapped to HLD Phases)

### Phase 1: Foundation (Week 1-2)

**Phase Goal:** SQLite database with sessions and vms tables is functional.

**User Stories & Tasks:**

* **Story:** As a developer, I have a SQLite database with the correct schema.
  * **Task:** Implement `store.py` — `MetadataStore` class with `initialize()` that opens SQLite at configured path, enables WAL mode (`PRAGMA journal_mode=WAL`), and creates all tables from HLD Section 5.6 DDL. Create all indexes.
    * *Identified Blockers/Dependencies:* Config must provide database path.

* **Story:** As a developer, I can create and query session and VM records.
  * **Task:** Implement session CRUD: `create_session()`, `get_session()`, `update_session()`, `list_sessions()`, `delete_session()`.
  * **Task:** Implement VM CRUD: `create_vm()`, `get_vm()`, `get_vm_by_session()`, `update_vm()`, `delete_vm()`.
    * *Identified Blockers/Dependencies:* Schema must be initialized.

* **Story:** As a developer, I have unit tests for metadata operations.
  * **Task:** Implement `test_metadata_store.py` — test all CRUD operations against an in-memory SQLite database. Test: insert, read, update, delete, list with filters, foreign key constraints.
    * *Identified Blockers/Dependencies:* None.

---

### Phase 2: Session Model + Auth Proxy (Week 2-3)

**Phase Goal:** Proxies and shared folders tables are functional.

**User Stories & Tasks:**

* **Story:** As a Session Manager, I can persist proxy and shared folder records.
  * **Task:** Implement proxy CRUD: `create_proxy()`, `get_proxy_by_session()`, `update_proxy()`, `delete_proxy()`.
  * **Task:** Implement shared folder CRUD: `create_shared_folder()`, `get_shared_folder_by_session()`, `delete_shared_folder()`.
  * **Task:** Implement resource allocation CRUD: `create_resource_allocation()`, `get_allocation_by_vm()`, `delete_allocation()`.
    * *Identified Blockers/Dependencies:* Schema (tables exist from Phase 1).

---

### Phase 4: Network Isolation + Policy (Week 4-5)

**Phase Goal:** Network rules persistence.

**User Stories & Tasks:**

* **Story:** As a Network Manager, I can persist and query network rules.
  * **Task:** Implement network rule CRUD: `create_network_rule()`, `get_network_rules()` (with `active_only` filter), `deactivate_network_rule()`, `deactivate_all_network_rules()`, `delete_network_rules()`.
    * *Identified Blockers/Dependencies:* Schema (table exists from Phase 1).

---

### Phase 6: Observability + Security (Week 6-7)

**Phase Goal:** Audit log persistence.

**User Stories & Tasks:**

* **Story:** As an Observability module, I can insert and query audit events.
  * **Task:** Implement `insert_audit_event()` and `query_audit_log()` with session_id and timestamp range filters, ordered by timestamp descending, with limit.
    * *Identified Blockers/Dependencies:* Schema (table exists from Phase 1).

---

### Phase 7: Orchestrator Adapter + Production (Week 7-8)

**Phase Goal:** Schema migrations and orphan detection.

**User Stories & Tasks:**

* **Story:** As a platform operator, schema changes are applied automatically on upgrade.
  * **Task:** Implement `migrations.py` — migration framework with version tracking table (`schema_migrations`). Each migration is a function that receives a database connection and applies DDL changes. `run_migrations(target_version)` applies all pending migrations in order. Migrations must be idempotent (check if change already applied).
    * *Identified Blockers/Dependencies:* None.
  * **Task:** Define migration for adding `enforcement_level` and `network_policy` columns to `sessions` table (if not present in initial schema).
    * *Identified Blockers/Dependencies:* Migration framework.

* **Story:** As a daemon startup task, I can detect and clean up orphaned sessions.
  * **Task:** Implement `get_sessions_by_status_and_age(status, older_than)` — query sessions in `creating` state with `created_at` older than configurable threshold (default 5 minutes). Used by daemon startup to detect partially-created sessions from a previous crash.
    * *Identified Blockers/Dependencies:* None.

---

## 5. Error Handling

| Error Condition | Handling |
|---|---|
| Database file not writable | Raise `DatabaseError` on `initialize()` — fatal |
| Schema initialization failure | Log error, raise `DatabaseError` — fatal |
| Unique constraint violation (e.g., duplicate session ID) | Raise `ConflictError` |
| Foreign key constraint violation | Raise `IntegrityError` with details |
| Migration failure | Log error, do not proceed — daemon cannot start |
| Database locked (concurrent write) | SQLite WAL mode handles this; retry up to 3x with backoff |
| Database corruption | Detect via `PRAGMA integrity_check`, log fatal error, require manual recovery |
