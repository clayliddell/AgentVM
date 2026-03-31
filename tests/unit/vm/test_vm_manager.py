from __future__ import annotations

from dataclasses import dataclass

import pytest

from agentvm.vm.manager import VMManager, VMSpec, VMStatus


@dataclass(frozen=True)
class _CapacityResult:
    sufficient: bool


class _FakeStore:
    def __init__(self) -> None:
        self.vms: dict[str, dict[str, object]] = {}

    async def create_vm(self, vm: dict[str, object]) -> None:
        vm_id = str(vm["id"])
        self.vms[vm_id] = dict(vm)

    async def get_vm(self, vm_id: str) -> dict[str, object] | None:
        return self.vms.get(vm_id)

    async def delete_vm(self, vm_id: str) -> None:
        self.vms.pop(vm_id, None)


def _spec(vm_id: str = "vm-1") -> VMSpec:
    return VMSpec(
        vm_id=vm_id,
        session_id="session-1",
        image_id="ubuntu-24.04-amd64",
        cpu_cores=2,
        memory_mb=4096,
        disk_gb=20,
    )


@pytest.mark.anyio()
async def test_create_vm_persists_vm_record() -> None:
    store = _FakeStore()
    manager = VMManager(store)

    info = await manager.create_vm(_spec())

    assert info.vm_id == "vm-1"
    assert info.ssh_host == "127.0.0.1"
    assert info.ssh_port == 22
    assert await store.get_vm("vm-1") is not None


@pytest.mark.anyio()
async def test_destroy_vm_removes_vm_record() -> None:
    store = _FakeStore()
    manager = VMManager(store)
    await manager.create_vm(_spec())

    await manager.destroy_vm("vm-1")

    assert await store.get_vm("vm-1") is None


@pytest.mark.anyio()
async def test_get_vm_status_returns_runtime_state_override() -> None:
    store = _FakeStore()
    manager = VMManager(
        store,
        runtime_state_provider=lambda vm_id: {
            "state": "running",
            "cpu_percent": 33.5,
            "memory_mb": 4200,
        },
    )
    await manager.create_vm(_spec())

    status = await manager.get_vm_status("vm-1")

    assert status == VMStatus(
        vm_id="vm-1",
        session_id="session-1",
        state="running",
        cpu_percent=33.5,
        memory_mb=4200,
    )


@pytest.mark.anyio()
async def test_get_vm_status_raises_when_vm_is_missing() -> None:
    manager = VMManager(_FakeStore())

    with pytest.raises(ValueError, match="vm not found"):
        await manager.get_vm_status("missing")


def test_check_host_capacity_delegates_to_capacity_manager() -> None:
    class _CapacityManager:
        def check_spec(
            self, cpu_cores: int, memory_mb: int, disk_gb: int
        ) -> _CapacityResult:
            assert cpu_cores == 2
            assert memory_mb == 4096
            assert disk_gb == 20
            return _CapacityResult(sufficient=True)

    manager = VMManager(_FakeStore(), capacity_manager=_CapacityManager())

    result = manager.check_host_capacity(_spec())

    assert result == _CapacityResult(sufficient=True)
