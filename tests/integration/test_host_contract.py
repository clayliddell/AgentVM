"""Integration contract tests for host manager boundaries.

Ref: HOST-MANAGER-LLD Section 3
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentvm.config import AgentVMConfig, StorageConfig
from agentvm.host import CapacityCheckResult, CapacityManager, HostCapacity


class _FakeStore:
    def get_active_vms(self) -> list[dict[str, object]]:
        return [
            {
                "id": "vm-1",
                "status": "running",
                "cpu_cores": 2,
                "memory_mb": 2048,
                "disk_gb": 10,
            }
        ]


@pytest.mark.integration
@pytest.mark.contract
def test_capacity_manager_when_reading_and_reconciling_returns_documented_contract(
    tmp_path: Path,
) -> None:
    cpuinfo = tmp_path / "cpuinfo"
    meminfo = tmp_path / "meminfo"
    cpuinfo.write_text("processor\t: 0\nprocessor\t: 1\n", encoding="utf-8")
    meminfo.write_text("MemTotal:       4194304 kB\n", encoding="utf-8")

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    config = AgentVMConfig(storage=StorageConfig(base_dir=str(storage_dir)))

    manager = CapacityManager(config, cpuinfo_path=cpuinfo, meminfo_path=meminfo)
    manager.reconcile_allocations(_FakeStore())

    capacity = manager.get_capacity()
    result = manager.check_spec(cpu_cores=1, memory_mb=256, disk_gb=1)

    assert isinstance(capacity, HostCapacity)
    assert isinstance(capacity.available_cpu, int)
    assert isinstance(capacity.available_memory_mb, int)
    assert isinstance(capacity.available_disk_gb, int)
    assert isinstance(result, CapacityCheckResult)
    assert isinstance(result.sufficient, bool)
