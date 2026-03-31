from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agentvm.config import AgentVMConfig
from agentvm.host.capacity import CapacityManager, _to_int


def test_get_capacity_accounts_for_reserved_and_allocated_resources(
    tmp_path: Path,
) -> None:
    config = AgentVMConfig.load()
    manager = _build_manager(
        tmp_path,
        config=config,
        cpuinfo="processor : 0\nprocessor : 1\nprocessor : 2\nprocessor : 3\n",
        meminfo="MemTotal:       16777216 kB\n",
        total_gb=120,
        available_gb=80,
    )

    manager.allocate("vm-1", cpu_cores=1, memory_mb=2048, disk_gb=10)
    capacity = manager.get_capacity()

    assert capacity.total_cpu == 4
    assert capacity.available_cpu == 1
    assert capacity.total_memory_mb == 16384
    assert capacity.available_memory_mb == 10240
    assert capacity.total_disk_gb == 120
    assert capacity.available_disk_gb == 70
    assert capacity.active_vm_count == 1


def test_check_spec_returns_shortfall_for_multiple_constraints(tmp_path: Path) -> None:
    manager = _build_manager(
        tmp_path,
        cpuinfo="processor : 0\nprocessor : 1\n",
        meminfo="MemTotal:       4194304 kB\n",
        total_gb=50,
        available_gb=5,
    )

    result = manager.check_spec(cpu_cores=4, memory_mb=8192, disk_gb=20)

    assert result.sufficient is False
    assert result.shortfall == "cpu, memory, disk"


def test_check_spec_includes_vm_count_shortfall_when_host_is_full(
    tmp_path: Path,
) -> None:
    config = AgentVMConfig.load()
    manager = _build_manager(
        tmp_path,
        config=config,
        cpuinfo="processor : 0\nprocessor : 1\nprocessor : 2\n",
        meminfo="MemTotal:       16777216 kB\n",
        total_gb=200,
        available_gb=200,
    )

    for index in range(config.host.max_vms):
        manager.allocate(f"vm-{index}", cpu_cores=0, memory_mb=0, disk_gb=0)

    result = manager.check_spec(cpu_cores=1, memory_mb=512, disk_gb=1)
    assert result.sufficient is False
    assert result.shortfall == "vm_count"


def test_check_spec_returns_sufficient_when_capacity_exists(tmp_path: Path) -> None:
    manager = _build_manager(
        tmp_path,
        cpuinfo="processor : 0\nprocessor : 1\nprocessor : 2\nprocessor : 3\n",
        meminfo="MemTotal:       16777216 kB\n",
        total_gb=200,
        available_gb=200,
    )

    result = manager.check_spec(cpu_cores=1, memory_mb=1024, disk_gb=1)
    assert result.sufficient is True
    assert result.shortfall is None


def test_allocate_and_release_update_capacity_state(tmp_path: Path) -> None:
    manager = _build_manager(
        tmp_path,
        cpuinfo="processor : 0\nprocessor : 1\nprocessor : 2\n",
        meminfo="MemTotal:       8388608 kB\n",
        total_gb=100,
        available_gb=100,
    )

    before = manager.get_capacity()
    manager.allocate("vm-a", cpu_cores=1, memory_mb=1024, disk_gb=5)
    after_allocate = manager.get_capacity()
    manager.release("vm-a")
    after_release = manager.get_capacity()

    assert before.active_vm_count == 0
    assert after_allocate.active_vm_count == 1
    assert after_allocate.available_cpu == before.available_cpu - 1
    assert after_release.active_vm_count == 0
    assert after_release.available_cpu == before.available_cpu


def test_allocate_raises_for_duplicate_vm_id(tmp_path: Path) -> None:
    manager = _build_manager(
        tmp_path,
        cpuinfo="processor : 0\n",
        meminfo="MemTotal:       1024 kB\n",
        total_gb=10,
        available_gb=10,
    )
    manager.allocate("vm-a", cpu_cores=1, memory_mb=1, disk_gb=1)

    with pytest.raises(ValueError):
        manager.allocate("vm-a", cpu_cores=1, memory_mb=1, disk_gb=1)


@pytest.mark.anyio()
async def test_reconcile_allocations_rebuilds_from_metadata_store(
    tmp_path: Path,
) -> None:
    manager = _build_manager(
        tmp_path,
        cpuinfo="processor : 0\nprocessor : 1\nprocessor : 2\nprocessor : 3\n",
        meminfo="MemTotal:       16777216 kB\n",
        total_gb=100,
        available_gb=100,
    )

    class FakeStore:
        def list_vms(self) -> list[dict[str, object]]:
            return [
                {
                    "id": "vm-active",
                    "cpu_cores": 2,
                    "memory_mb": 4096,
                    "disk_gb": 25,
                    "status": "running",
                },
                {
                    "id": "vm-creating",
                    "cpu_cores": 1,
                    "memory_mb": 1024,
                    "disk_gb": 5,
                    "status": "creating",
                },
                {
                    "id": "vm-stopped",
                    "cpu_cores": 1,
                    "memory_mb": 1024,
                    "disk_gb": 5,
                    "status": "stopped",
                },
            ]

    await manager.reconcile_allocations(FakeStore())
    capacity = manager.get_capacity()

    assert capacity.active_vm_count == 2
    assert capacity.available_cpu == 0


@pytest.mark.anyio()
async def test_reconcile_allocations_supports_async_get_active_vms(
    tmp_path: Path,
) -> None:
    manager = _build_manager(
        tmp_path,
        cpuinfo="processor : 0\nprocessor : 1\n",
        meminfo="MemTotal:       8388608 kB\n",
        total_gb=20,
        available_gb=20,
    )

    class AsyncStore:
        async def get_active_vms(self) -> list[dict[str, object]]:
            return [
                {"vm_id": "vm-x", "cpu_cores": "1", "memory_mb": "1024", "disk_gb": "2"}
            ]

    await manager.reconcile_allocations(AsyncStore())

    assert manager.get_capacity().active_vm_count == 1


@pytest.mark.anyio()
async def test_reconcile_allocations_ignores_invalid_vm_rows(tmp_path: Path) -> None:
    manager = _build_manager(
        tmp_path,
        cpuinfo="processor : 0\nprocessor : 1\n",
        meminfo="MemTotal:       8388608 kB\n",
        total_gb=20,
        available_gb=20,
    )

    class Store:
        def list_vms(self) -> list[object]:
            return [
                {"id": "", "cpu_cores": 1, "memory_mb": 1, "disk_gb": 1},
                {"id": "vm-missing", "cpu_cores": "x", "memory_mb": 1, "disk_gb": 1},
                10,
            ]

    await manager.reconcile_allocations(Store())
    assert manager.get_capacity().active_vm_count == 0


@pytest.mark.anyio()
async def test_reconcile_allocations_raises_for_invalid_store_contract(
    tmp_path: Path,
) -> None:
    manager = _build_manager(
        tmp_path,
        cpuinfo="processor : 0\n",
        meminfo="MemTotal:       1024 kB\n",
        total_gb=10,
        available_gb=10,
    )

    class NoVmMethods:
        pass

    class BadReturnStore:
        def list_vms(self) -> str:
            return "not-a-list"

    with pytest.raises(TypeError):
        await manager.reconcile_allocations(NoVmMethods())

    with pytest.raises(TypeError):
        await manager.reconcile_allocations(BadReturnStore())


def test_cpu_memory_and_disk_fallback_paths(tmp_path: Path) -> None:
    missing_cpu = tmp_path / "does-not-exist-cpuinfo"
    bad_mem = _write_file(tmp_path / "meminfo", "MemTotal: bad\n")

    def raising_statvfs(_path: str) -> _StatVFS:
        raise OSError("no disk")

    manager = CapacityManager(
        AgentVMConfig.load(),
        cpuinfo_path=missing_cpu,
        meminfo_path=bad_mem,
        statvfs=raising_statvfs,
    )

    capacity = manager.get_capacity()
    assert capacity.total_cpu >= 1
    assert capacity.total_memory_mb == 0
    assert capacity.total_disk_gb == 0
    assert capacity.available_disk_gb == 0


def test_cpu_count_falls_back_when_processor_lines_missing(tmp_path: Path) -> None:
    manager = _build_manager(
        tmp_path,
        cpuinfo="model name : fake\n",
        meminfo="MemTotal:       1024 kB\n",
        total_gb=10,
        available_gb=10,
    )

    assert manager.get_capacity().total_cpu >= 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [(5, 5), (5.6, 5), ("7", 7), (b"9", 9), (bytearray(b"11"), 11)],
)
def test_to_int_converts_supported_types(value: object, expected: int) -> None:
    assert _to_int(value) == expected


@pytest.mark.parametrize("value", [True, object()])
def test_to_int_rejects_invalid_types(value: object) -> None:
    with pytest.raises(TypeError):
        _to_int(value)


def _build_manager(
    tmp_path: Path,
    *,
    config: AgentVMConfig | None = None,
    cpuinfo: str,
    meminfo: str,
    total_gb: int,
    available_gb: int,
) -> CapacityManager:
    resolved_config = config if config is not None else AgentVMConfig.load()
    return CapacityManager(
        resolved_config,
        cpuinfo_path=_write_file(tmp_path / "cpuinfo", cpuinfo),
        meminfo_path=_write_file(tmp_path / "meminfo", meminfo),
        statvfs=_fake_statvfs(total_gb=total_gb, available_gb=available_gb),
    )


def _write_file(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _fake_statvfs(total_gb: int, available_gb: int) -> _StatVFSFn:
    def fake_statvfs(_path: str) -> _StatVFS:
        gib = 1024**3
        block_size = 4096
        return _StatVFS(
            f_frsize=block_size,
            f_blocks=(total_gb * gib) // block_size,
            f_bavail=(available_gb * gib) // block_size,
        )

    return fake_statvfs


class _StatVFS:
    def __init__(self, *, f_frsize: int, f_blocks: int, f_bavail: int) -> None:
        self.f_frsize = f_frsize
        self.f_blocks = f_blocks
        self.f_bavail = f_bavail


type _StatVFSFn = Callable[[str], _StatVFS]
