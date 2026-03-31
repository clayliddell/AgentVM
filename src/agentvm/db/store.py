"""Metadata persistence via SQLite.

Ref: METADATA-STORE-LLD §3.2
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import structlog  # type: ignore[import-not-found]

logger = structlog.get_logger()


class MetadataStore:
    """Async metadata store backed by SQLite (WAL mode).

    Ref: METADATA-STORE-LLD §3.2
    """

    def __init__(self, db_path: str = "/var/lib/agentvm/metadata.db") -> None:
        """Initialize metadata store settings.

        Args:
            db_path: Path to SQLite database file.

        Returns:
            None

        Ref: METADATA-STORE-LLD §3.2
        """

        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    async def initialize(self) -> None:
        """Open database, enable WAL mode, create schema, run migrations.

        Ref: METADATA-STORE-LLD §3.2
        """

        path = Path(self._db_path)
        if self._db_path != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=OFF")
        self._create_schema()
        logger.info("metadata_store_initialized")

    async def close(self) -> None:
        """Close database connection.

        Ref: METADATA-STORE-LLD §3.2
        """

        if self._conn is not None:
            self._conn.close()
            self._conn = None
        logger.info("metadata_store_closed")

    async def create_session(self, session: dict[str, Any]) -> str:
        """Insert session record.

        Ref: METADATA-STORE-LLD §3.2
        """

        session_id = str(session["id"])
        now = _utc_now()
        self._execute(
            """
            INSERT INTO sessions (id, owner, status, created_at, updated_at, data)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                str(session.get("owner", "")),
                str(session.get("status", "creating")),
                str(session.get("created_at", now)),
                now,
                json.dumps(session),
            ),
        )
        return session_id

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve session by ID.

        Ref: METADATA-STORE-LLD §3.2
        """

        row = self._query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
        return _decode_row(row) if row is not None else None

    async def update_session(self, session_id: str, updates: dict[str, Any]) -> None:
        """Update session fields.

        Ref: METADATA-STORE-LLD §3.2
        """

        current = await self.get_session(session_id)
        if current is None:
            return
        merged = {**current, **updates}
        self._execute(
            """
            UPDATE sessions
            SET owner = ?, status = ?, updated_at = ?, data = ?
            WHERE id = ?
            """,
            (
                str(merged.get("owner", "")),
                str(merged.get("status", "")),
                _utc_now(),
                json.dumps(merged),
                session_id,
            ),
        )

    async def list_sessions(
        self, owner: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List sessions with optional owner and status filters.

        Ref: METADATA-STORE-LLD §3.2
        """

        query = "SELECT * FROM sessions WHERE 1=1"
        params: list[object] = []
        if owner is not None:
            query += " AND owner = ?"
            params.append(owner)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at ASC"
        rows = self._query_all(query, tuple(params))
        return [_decode_row(row) for row in rows]

    async def delete_session(self, session_id: str) -> None:
        """Delete session and related records.

        Ref: METADATA-STORE-LLD §3.2
        """

        vm_rows = self._query_all(
            "SELECT id FROM vms WHERE session_id = ?", (session_id,)
        )
        vm_ids = [str(row["id"]) for row in vm_rows]

        self._execute("DELETE FROM vms WHERE session_id = ?", (session_id,))
        self._execute("DELETE FROM proxies WHERE session_id = ?", (session_id,))
        self._execute("DELETE FROM shared_folders WHERE session_id = ?", (session_id,))
        self._execute("DELETE FROM network_rules WHERE session_id = ?", (session_id,))
        self._execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        for vm_id in vm_ids:
            self._execute("DELETE FROM resource_allocations WHERE vm_id = ?", (vm_id,))

    async def get_sessions_by_status_and_age(
        self, status: str, older_than: str
    ) -> list[dict[str, Any]]:
        """Find sessions in a given state older than threshold.

        Ref: METADATA-STORE-LLD §3.2
        """

        minutes = _parse_minutes(older_than)
        threshold = datetime.now(tz=UTC) - timedelta(minutes=minutes)
        rows = self._query_all(
            "SELECT * FROM sessions WHERE status = ? AND created_at <= ?",
            (status, threshold.isoformat()),
        )
        return [_decode_row(row) for row in rows]

    async def create_vm(self, vm: dict[str, Any]) -> str:
        """Insert VM record.

        Ref: METADATA-STORE-LLD §3.2
        """

        vm_id = str(vm["id"])
        self._execute(
            """
            INSERT INTO vms
            (
                id,
                session_id,
                name,
                status,
                base_image,
                cpu_cores,
                memory_mb,
                disk_gb,
                created_at,
                data
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vm_id,
                str(vm.get("session_id", "")),
                str(vm.get("name", "")),
                str(vm.get("status", "creating")),
                str(vm.get("base_image", "")),
                _as_int(vm.get("cpu_cores", 0)),
                _as_int(vm.get("memory_mb", 0)),
                _as_int(vm.get("disk_gb", 0)),
                str(vm.get("created_at", _utc_now())),
                json.dumps(vm),
            ),
        )
        return vm_id

    async def get_vm(self, vm_id: str) -> dict[str, Any] | None:
        """Retrieve VM by ID.

        Ref: METADATA-STORE-LLD §3.2
        """

        row = self._query_one("SELECT * FROM vms WHERE id = ?", (vm_id,))
        return _decode_row(row) if row is not None else None

    async def get_vm_by_session(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve VM for a session.

        Ref: METADATA-STORE-LLD §3.2
        """

        row = self._query_one(
            "SELECT * FROM vms WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        )
        return _decode_row(row) if row is not None else None

    async def get_vms_by_image(self, base_image: str) -> list[dict[str, Any]]:
        """Retrieve VMs referencing an image.

        Ref: METADATA-STORE-LLD §3.2
        """

        rows = self._query_all("SELECT * FROM vms WHERE base_image = ?", (base_image,))
        return [_decode_row(row) for row in rows]

    async def update_vm(self, vm_id: str, updates: dict[str, Any]) -> None:
        """Update VM fields.

        Ref: METADATA-STORE-LLD §3.2
        """

        current = await self.get_vm(vm_id)
        if current is None:
            return
        merged = {**current, **updates}
        self._execute(
            """
            UPDATE vms
            SET
                session_id = ?,
                name = ?,
                status = ?,
                base_image = ?,
                cpu_cores = ?,
                memory_mb = ?,
                disk_gb = ?,
                data = ?
            WHERE id = ?
            """,
            (
                str(merged.get("session_id", "")),
                str(merged.get("name", "")),
                str(merged.get("status", "")),
                str(merged.get("base_image", "")),
                _as_int(merged.get("cpu_cores", 0)),
                _as_int(merged.get("memory_mb", 0)),
                _as_int(merged.get("disk_gb", 0)),
                json.dumps(merged),
                vm_id,
            ),
        )

    async def delete_vm(self, vm_id: str) -> None:
        """Delete VM record.

        Ref: METADATA-STORE-LLD §3.2
        """

        self._execute("DELETE FROM resource_allocations WHERE vm_id = ?", (vm_id,))
        self._execute("DELETE FROM vms WHERE id = ?", (vm_id,))

    async def list_vms(self, status: str | None = None) -> list[dict[str, Any]]:
        """List VMs, optionally filtered by status.

        Ref: METADATA-STORE-LLD §3.2
        """

        if status is None:
            rows = self._query_all("SELECT * FROM vms", ())
        else:
            rows = self._query_all("SELECT * FROM vms WHERE status = ?", (status,))
        return [_decode_row(row) for row in rows]

    def get_active_vms(self) -> list[dict[str, Any]]:
        """Return active VM rows for capacity reconciliation.

        Ref: HOST-MANAGER-LLD Section 5.2
        """

        rows = self._query_all(
            "SELECT * FROM vms WHERE status IN ('running', 'creating')",
            (),
        )
        return [_decode_row(row) for row in rows]

    async def create_proxy(self, proxy: dict[str, Any]) -> int:
        """Insert proxy record.

        Ref: METADATA-STORE-LLD §3.2
        """

        cursor = self._execute(
            (
                "INSERT INTO proxies (session_id, port, pid, status, data) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            (
                str(proxy.get("session_id", "")),
                _as_int(proxy.get("port", 0)),
                _as_int(proxy.get("pid", 0)),
                str(proxy.get("status", "running")),
                json.dumps(proxy),
            ),
        )
        return _lastrowid(cursor)

    async def get_proxy_by_session(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve proxy for a session.

        Ref: METADATA-STORE-LLD §3.2
        """

        row = self._query_one(
            "SELECT * FROM proxies WHERE session_id = ?", (session_id,)
        )
        return _decode_row(row) if row is not None else None

    async def update_proxy(self, session_id: str, updates: dict[str, Any]) -> None:
        """Update proxy fields.

        Ref: METADATA-STORE-LLD §3.2
        """

        current = await self.get_proxy_by_session(session_id)
        if current is None:
            return
        merged = {**current, **updates}
        self._execute(
            (
                "UPDATE proxies SET port = ?, pid = ?, status = ?, data = ? "
                "WHERE session_id = ?"
            ),
            (
                _as_int(merged.get("port", 0)),
                _as_int(merged.get("pid", 0)),
                str(merged.get("status", "")),
                json.dumps(merged),
                session_id,
            ),
        )

    async def delete_proxy(self, session_id: str) -> None:
        """Delete proxy record.

        Ref: METADATA-STORE-LLD §3.2
        """

        self._execute("DELETE FROM proxies WHERE session_id = ?", (session_id,))

    async def create_shared_folder(self, folder: dict[str, Any]) -> int:
        """Insert shared folder record.

        Ref: METADATA-STORE-LLD §3.2
        """

        cursor = self._execute(
            "INSERT INTO shared_folders (session_id, host_path, data) VALUES (?, ?, ?)",
            (
                str(folder.get("session_id", "")),
                str(folder.get("host_path", "")),
                json.dumps(folder),
            ),
        )
        return _lastrowid(cursor)

    async def get_shared_folder_by_session(
        self, session_id: str
    ) -> dict[str, Any] | None:
        """Retrieve shared folder for a session.

        Ref: METADATA-STORE-LLD §3.2
        """

        row = self._query_one(
            "SELECT * FROM shared_folders WHERE session_id = ?",
            (session_id,),
        )
        return _decode_row(row) if row is not None else None

    async def delete_shared_folder(self, session_id: str) -> None:
        """Delete shared folder record.

        Ref: METADATA-STORE-LLD §3.2
        """

        self._execute("DELETE FROM shared_folders WHERE session_id = ?", (session_id,))

    async def create_resource_allocation(self, allocation: dict[str, Any]) -> int:
        """Insert resource allocation record.

        Ref: METADATA-STORE-LLD §3.2
        """

        cursor = self._execute(
            """
            INSERT INTO resource_allocations
            (vm_id, cpu_cores, memory_mb, disk_gb, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(allocation.get("vm_id", "")),
                _as_int(allocation.get("cpu_cores", 0)),
                _as_int(allocation.get("memory_mb", 0)),
                _as_int(allocation.get("disk_gb", 0)),
                json.dumps(allocation),
            ),
        )
        return _lastrowid(cursor)

    async def get_allocation_by_vm(self, vm_id: str) -> dict[str, Any] | None:
        """Retrieve resource allocation for a VM.

        Ref: METADATA-STORE-LLD §3.2
        """

        row = self._query_one(
            "SELECT * FROM resource_allocations WHERE vm_id = ?",
            (vm_id,),
        )
        return _decode_row(row) if row is not None else None

    async def delete_allocation(self, vm_id: str) -> None:
        """Delete resource allocation record.

        Ref: METADATA-STORE-LLD §3.2
        """

        self._execute("DELETE FROM resource_allocations WHERE vm_id = ?", (vm_id,))

    async def insert_audit_event(self, event: dict[str, Any]) -> int:
        """Insert audit log entry.

        Ref: METADATA-STORE-LLD §3.2
        """

        cursor = self._execute(
            (
                "INSERT INTO audit_log (session_id, event_type, timestamp, data) "
                "VALUES (?, ?, ?, ?)"
            ),
            (
                str(event.get("session_id", "")),
                str(event.get("event_type", "unknown")),
                str(event.get("timestamp", _utc_now())),
                json.dumps(event),
            ),
        )
        return _lastrowid(cursor)

    async def query_audit_log(
        self,
        session_id: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query audit log with optional filters.

        Ref: METADATA-STORE-LLD §3.2
        """

        query = "SELECT * FROM audit_log WHERE 1=1"
        params: list[object] = []
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = self._query_all(query, tuple(params))
        return [_decode_row(row) for row in rows]

    async def create_network_rule(self, rule: dict[str, Any]) -> int:
        """Insert network rule record.

        Ref: METADATA-STORE-LLD §3.2
        """

        cursor = self._execute(
            """
            INSERT INTO network_rules
            (session_id, domain, action, source, created_at, removed_at, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(rule.get("session_id", "")),
                str(rule.get("domain", "")),
                str(rule.get("action", "allow")),
                str(rule.get("source", "runtime")),
                str(rule.get("created_at", _utc_now())),
                rule.get("removed_at"),
                json.dumps(rule),
            ),
        )
        return _lastrowid(cursor)

    async def get_network_rules(
        self, session_id: str, active_only: bool = True
    ) -> list[dict[str, Any]]:
        """Retrieve network rules for a session.

        Ref: METADATA-STORE-LLD §3.2
        """

        if active_only:
            rows = self._query_all(
                (
                    "SELECT * FROM network_rules "
                    "WHERE session_id = ? AND removed_at IS NULL"
                ),
                (session_id,),
            )
        else:
            rows = self._query_all(
                "SELECT * FROM network_rules WHERE session_id = ?",
                (session_id,),
            )
        return [_decode_row(row) for row in rows]

    async def deactivate_network_rule(self, rule_id: int) -> None:
        """Mark rule as removed.

        Ref: METADATA-STORE-LLD §3.2
        """

        self._execute(
            "UPDATE network_rules SET removed_at = ? WHERE id = ?",
            (_utc_now(), rule_id),
        )

    async def deactivate_all_network_rules(self, session_id: str) -> None:
        """Mark all rules for a session as removed.

        Ref: METADATA-STORE-LLD §3.2
        """

        self._execute(
            "UPDATE network_rules SET removed_at = ? WHERE session_id = ?",
            (_utc_now(), session_id),
        )

    async def delete_network_rules(self, session_id: str) -> None:
        """Delete all network rules for a session.

        Ref: METADATA-STORE-LLD §3.2
        """

        self._execute("DELETE FROM network_rules WHERE session_id = ?", (session_id,))

    async def get_schema_version(self) -> int:
        """Return schema version.

        Ref: METADATA-STORE-LLD §3.2
        """

        row = self._query_one("PRAGMA user_version", ())
        if row is None:
            return 0
        return int(row[0])

    async def run_migrations(self, target_version: int) -> None:
        """Set schema version as migration placeholder.

        Ref: METADATA-STORE-LLD §3.2
        """

        self._execute(f"PRAGMA user_version={int(target_version)}", ())

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("metadata store not initialized")
        return self._conn

    def _execute(self, query: str, params: tuple[object, ...]) -> sqlite3.Cursor:
        conn = self._connection()
        cursor = conn.execute(query, params)
        conn.commit()
        return cursor

    def _query_one(self, query: str, params: tuple[object, ...]) -> sqlite3.Row | None:
        conn = self._connection()
        cursor = conn.execute(query, params)
        row = cursor.fetchone()
        return cast(sqlite3.Row | None, row)

    def _query_all(self, query: str, params: tuple[object, ...]) -> list[sqlite3.Row]:
        conn = self._connection()
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        return list(rows)

    def _create_schema(self) -> None:
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                owner TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                data TEXT NOT NULL
            )
            """,
            (),
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS vms (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                name TEXT,
                status TEXT,
                base_image TEXT,
                cpu_cores INTEGER,
                memory_mb INTEGER,
                disk_gb INTEGER,
                created_at TEXT,
                data TEXT NOT NULL
            )
            """,
            (),
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE,
                port INTEGER,
                pid INTEGER,
                status TEXT,
                data TEXT NOT NULL
            )
            """,
            (),
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS shared_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE,
                host_path TEXT,
                data TEXT NOT NULL
            )
            """,
            (),
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS resource_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vm_id TEXT UNIQUE,
                cpu_cores INTEGER,
                memory_mb INTEGER,
                disk_gb INTEGER,
                data TEXT NOT NULL
            )
            """,
            (),
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                event_type TEXT,
                timestamp TEXT,
                data TEXT NOT NULL
            )
            """,
            (),
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS network_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                domain TEXT,
                action TEXT,
                source TEXT,
                created_at TEXT,
                removed_at TEXT,
                data TEXT NOT NULL
            )
            """,
            (),
        )


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(str(row["data"]))
    if not isinstance(payload, dict):
        payload = {}
    for key in tuple(row.keys()):
        if key == "data":
            continue
        payload.setdefault(key, row[key])
    return payload


def _parse_minutes(value: str) -> int:
    text = value.strip().lower()
    if text.endswith("minutes"):
        return int(text.replace("minutes", "").strip())
    if text.endswith("minute"):
        return int(text.replace("minute", "").strip())
    return int(text)


def _as_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    raise ValueError(f"cannot convert {type(value)!r} to int")


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("sqlite did not return lastrowid")
    return int(row_id)
