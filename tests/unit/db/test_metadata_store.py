"""Tests for MetadataStore CRUD operations.

Ref: METADATA-STORE-LLD §5.3
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest

from agentvm.db.store import MetadataStore


@pytest.fixture()
async def store() -> AsyncGenerator[MetadataStore, None]:
    db = MetadataStore(db_path=":memory:")
    await db.initialize()
    try:
        yield db
    finally:
        await db.close()


@pytest.mark.anyio()
async def test_session_crud_and_filters(store: MetadataStore) -> None:
    now = datetime.now(tz=UTC).isoformat()
    session = {
        "id": "session-1",
        "owner": "alice",
        "status": "creating",
        "created_at": now,
    }

    session_id = await store.create_session(session)
    assert session_id == "session-1"

    fetched = await store.get_session("session-1")
    assert fetched is not None
    assert fetched["owner"] == "alice"

    updated = await store.update_session("session-1", {"status": "running"})
    assert updated is True
    running = await store.list_sessions(owner="alice", status="running")
    assert len(running) == 1
    assert running[0]["id"] == "session-1"

    assert await store.update_session("missing", {"status": "running"}) is False

    await store.delete_session("session-1")
    assert await store.get_session("session-1") is None


@pytest.mark.anyio()
async def test_get_sessions_by_status_and_age(store: MetadataStore) -> None:
    old = (datetime.now(tz=UTC) - timedelta(minutes=10)).isoformat()
    new = datetime.now(tz=UTC).isoformat()
    await store.create_session(
        {"id": "old", "owner": "a", "status": "creating", "created_at": old}
    )
    await store.create_session(
        {"id": "new", "owner": "a", "status": "creating", "created_at": new}
    )

    orphaned = await store.get_sessions_by_status_and_age("creating", "5 minutes")
    assert [entry["id"] for entry in orphaned] == ["old"]


@pytest.mark.anyio()
async def test_vm_crud_and_lookup_helpers(store: MetadataStore) -> None:
    vm = {
        "id": "vm-1",
        "session_id": "session-1",
        "name": "vm-1",
        "status": "creating",
        "base_image": "ubuntu-24.04-amd64",
        "cpu_cores": 2,
        "memory_mb": 4096,
        "disk_gb": 20,
    }
    await store.create_vm(vm)

    fetched = await store.get_vm("vm-1")
    assert fetched is not None
    assert fetched["name"] == "vm-1"

    updated = await store.update_vm("vm-1", {"status": "running"})
    assert updated is True
    by_session = await store.get_vm_by_session("session-1")
    assert by_session is not None
    assert by_session["status"] == "running"

    by_image = await store.get_vms_by_image("ubuntu-24.04-amd64")
    assert len(by_image) == 1
    assert by_image[0]["id"] == "vm-1"

    active = await store.get_active_vms()
    assert len(active) == 1

    assert await store.update_vm("missing", {"status": "running"}) is False

    await store.delete_vm("vm-1")
    assert await store.get_vm("vm-1") is None


@pytest.mark.anyio()
async def test_proxy_shared_folder_and_allocation_crud(store: MetadataStore) -> None:
    await store.create_proxy(
        {
            "session_id": "session-1",
            "port": 23760,
            "pid": 1234,
            "status": "running",
        }
    )
    proxy = await store.get_proxy_by_session("session-1")
    assert proxy is not None
    assert proxy["port"] == 23760

    await store.update_proxy("session-1", {"status": "stopped"})
    updated_proxy = await store.get_proxy_by_session("session-1")
    assert updated_proxy is not None
    assert updated_proxy["status"] == "stopped"
    await store.delete_proxy("session-1")
    assert await store.get_proxy_by_session("session-1") is None

    await store.create_shared_folder(
        {"session_id": "session-1", "host_path": "/var/lib/agentvm/shared/session-1"}
    )
    folder = await store.get_shared_folder_by_session("session-1")
    assert folder is not None
    assert folder["host_path"].endswith("session-1")
    await store.delete_shared_folder("session-1")
    assert await store.get_shared_folder_by_session("session-1") is None

    await store.create_resource_allocation(
        {"vm_id": "vm-1", "cpu_cores": 2, "memory_mb": 2048, "disk_gb": 10}
    )
    allocation = await store.get_allocation_by_vm("vm-1")
    assert allocation is not None
    assert allocation["cpu_cores"] == 2
    await store.delete_allocation("vm-1")
    assert await store.get_allocation_by_vm("vm-1") is None


@pytest.mark.anyio()
async def test_audit_log_query_and_schema_version(store: MetadataStore) -> None:
    await store.insert_audit_event(
        {
            "session_id": "session-1",
            "event_type": "session.create",
            "timestamp": datetime.now(tz=UTC).isoformat(),
        }
    )
    events = await store.query_audit_log(session_id="session-1", limit=10)
    assert len(events) == 1
    assert events[0]["event_type"] == "session.create"

    await store.run_migrations(2)
    assert await store.get_schema_version() == 2


@pytest.mark.anyio()
async def test_parse_minutes_rejects_invalid_prefix_text(store: MetadataStore) -> None:
    await store.create_session(
        {"id": "session-1", "owner": "alice", "status": "creating"}
    )

    with pytest.raises(ValueError):
        await store.get_sessions_by_status_and_age("creating", "minutes5")


@pytest.mark.anyio()
async def test_get_vm_tolerates_invalid_json_payload(store: MetadataStore) -> None:
    store._execute(
        (
            "INSERT INTO vms (id, session_id, name, status, base_image, cpu_cores, "
            "memory_mb, disk_gb, created_at, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?)"
        ),
        (
            "vm-bad-json",
            "session-1",
            "vm-bad-json",
            "running",
            "ubuntu",
            1,
            512,
            10,
            datetime.now(tz=UTC).isoformat(),
            "not-json",
        ),
    )

    fetched = await store.get_vm("vm-bad-json")

    assert fetched is not None
    assert fetched["id"] == "vm-bad-json"
    assert fetched["status"] == "running"


@pytest.mark.anyio()
async def test_get_vm_tolerates_non_dict_json_payload(store: MetadataStore) -> None:
    store._execute(
        (
            "INSERT INTO vms (id, session_id, name, status, base_image, cpu_cores, "
            "memory_mb, disk_gb, created_at, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?)"
        ),
        (
            "vm-bad-payload",
            "session-1",
            "vm-bad-payload",
            "running",
            "ubuntu",
            1,
            512,
            10,
            datetime.now(tz=UTC).isoformat(),
            "[]",
        ),
    )

    fetched = await store.get_vm("vm-bad-payload")

    assert fetched is not None
    assert fetched["id"] == "vm-bad-payload"
    assert fetched["status"] == "running"


@pytest.mark.anyio()
async def test_network_rules_crud(store: MetadataStore) -> None:
    rule_id = await store.create_network_rule(
        {
            "session_id": "session-1",
            "domain": "example.com",
            "action": "allow",
            "source": "runtime",
        }
    )

    active = await store.get_network_rules("session-1")
    assert len(active) == 1
    assert active[0]["domain"] == "example.com"

    await store.deactivate_network_rule(rule_id)
    assert await store.get_network_rules("session-1") == []

    await store.create_network_rule(
        {
            "session_id": "session-1",
            "domain": "another.example",
            "action": "block",
            "source": "runtime",
        }
    )
    await store.deactivate_all_network_rules("session-1")
    all_rules = await store.get_network_rules("session-1", active_only=False)
    assert len(all_rules) == 2
    assert all(rule.get("removed_at") is not None for rule in all_rules)

    await store.delete_network_rules("session-1")
    assert await store.get_network_rules("session-1", active_only=False) == []


@pytest.mark.anyio()
async def test_delete_session_cascades_related_records(store: MetadataStore) -> None:
    await store.create_session(
        {"id": "session-1", "owner": "alice", "status": "running"}
    )
    await store.create_vm(
        {
            "id": "vm-1",
            "session_id": "session-1",
            "name": "vm-1",
            "status": "running",
            "base_image": "ubuntu",
            "cpu_cores": 1,
            "memory_mb": 512,
            "disk_gb": 10,
        }
    )
    await store.create_proxy({"session_id": "session-1", "port": 1, "pid": 2})
    await store.create_shared_folder(
        {"session_id": "session-1", "host_path": "/var/lib/agentvm/shared/sf"}
    )
    await store.create_resource_allocation(
        {"vm_id": "vm-1", "cpu_cores": 1, "memory_mb": 512, "disk_gb": 10}
    )
    await store.create_network_rule(
        {"session_id": "session-1", "domain": "example.com", "action": "allow"}
    )

    await store.delete_session("session-1")

    assert await store.get_session("session-1") is None
    assert await store.get_vm("vm-1") is None
    assert await store.get_proxy_by_session("session-1") is None
    assert await store.get_shared_folder_by_session("session-1") is None
    assert await store.get_allocation_by_vm("vm-1") is None
    assert await store.get_network_rules("session-1", active_only=False) == []
