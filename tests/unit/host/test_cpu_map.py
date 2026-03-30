from __future__ import annotations

from pathlib import Path

import pytest

from agentvm.host.cpu_map import (
    CPUMapManager,
    _format_cpuset,
    _parse_cpu_list,
    detect_nested_virt_support,
)


def test_detect_nested_virt_support_true_when_intel_module_enabled(
    tmp_path: Path,
) -> None:
    nested_file = tmp_path / "kvm_intel" / "parameters" / "nested"
    nested_file.parent.mkdir(parents=True, exist_ok=True)
    nested_file.write_text("Y\n", encoding="utf-8")

    assert detect_nested_virt_support(tmp_path) is True


def test_detect_nested_virt_support_uses_amd_fallback(tmp_path: Path) -> None:
    nested_file = tmp_path / "kvm_amd" / "parameters" / "nested"
    nested_file.parent.mkdir(parents=True, exist_ok=True)
    nested_file.write_text("1\n", encoding="utf-8")

    assert detect_nested_virt_support(tmp_path) is True


def test_detect_nested_virt_support_returns_false_when_missing(tmp_path: Path) -> None:
    assert detect_nested_virt_support(tmp_path) is False


def test_get_topology_parses_sysfs_and_allocates_cores(tmp_path: Path) -> None:
    cpu_sys, node_sys, module_sys = _build_standard_layout(tmp_path)
    manager = CPUMapManager(
        cpu_sys_path=cpu_sys, node_sys_path=node_sys, module_sys_path=module_sys
    )

    topology = manager.get_topology()
    cpuset, numa_node = manager.allocate_cores(
        count=2, reserved=[0], already_allocated=[]
    )

    assert topology.total_cores == 4
    assert topology.cores_per_socket == 2
    assert topology.numa_nodes == 1
    assert topology.cores_per_numa == [4]
    assert topology.hyperthread_pairs[0] == 2
    assert topology.hyperthread_pairs[1] == 3
    assert topology.nested_virtualization is False
    assert cpuset == "1,3"
    assert numa_node == 0


def test_allocate_cores_uses_fallback_when_numa_is_missing(tmp_path: Path) -> None:
    cpu_sys = tmp_path / "cpu"
    module_sys = tmp_path / "module"
    _write_cpu_topology(cpu_sys, cpu_id=0, core_id=0, package_id=0, siblings="0")
    _write_cpu_topology(cpu_sys, cpu_id=1, core_id=1, package_id=0, siblings="1")

    manager = CPUMapManager(
        cpu_sys_path=cpu_sys,
        node_sys_path=tmp_path / "node",
        module_sys_path=module_sys,
    )

    cpuset, node = manager.allocate_cores(count=1, reserved=[], already_allocated=[])
    assert cpuset == "0"
    assert node == 0


def test_allocate_cores_raises_when_invalid_request(tmp_path: Path) -> None:
    cpu_sys, node_sys, module_sys = _build_standard_layout(tmp_path)
    manager = CPUMapManager(
        cpu_sys_path=cpu_sys, node_sys_path=node_sys, module_sys_path=module_sys
    )

    with pytest.raises(ValueError):
        manager.allocate_cores(count=0, reserved=[], already_allocated=[])

    with pytest.raises(ValueError):
        manager.allocate_cores(count=3, reserved=[0], already_allocated=[1, 2, 3])


def test_get_topology_handles_invalid_cpu_and_node_entries(tmp_path: Path) -> None:
    cpu_sys = tmp_path / "cpu"
    node_sys = tmp_path / "node"
    module_sys = tmp_path / "module"

    invalid_cpu = cpu_sys / "cpux" / "topology"
    invalid_cpu.mkdir(parents=True, exist_ok=True)

    (node_sys / "nodeX").mkdir(parents=True, exist_ok=True)

    manager = CPUMapManager(
        cpu_sys_path=cpu_sys, node_sys_path=node_sys, module_sys_path=module_sys
    )
    topology = manager.get_topology()

    assert topology.total_cores == 1
    assert topology.numa_nodes == 1
    assert topology.cores_per_numa == [1]


def test_release_cores_is_noop(tmp_path: Path) -> None:
    cpu_sys, node_sys, module_sys = _build_standard_layout(tmp_path)
    manager = CPUMapManager(
        cpu_sys_path=cpu_sys, node_sys_path=node_sys, module_sys_path=module_sys
    )
    manager.release_cores([0, 1])


def test_parse_cpu_list_and_format_cpuset_cover_edge_cases() -> None:
    assert _parse_cpu_list("0-2,4,6-7") == [0, 1, 2, 4, 6, 7]
    assert _parse_cpu_list("  ") == []
    assert _format_cpuset([1, 2, 3, 7, 8, 10]) == "1-3,7-8,10"
    assert _format_cpuset([]) == ""


def _build_standard_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    cpu_sys = tmp_path / "cpu"
    node_sys = tmp_path / "node"
    module_sys = tmp_path / "module"

    _write_cpu_topology(cpu_sys, cpu_id=0, core_id=0, package_id=0, siblings="0,2")
    _write_cpu_topology(cpu_sys, cpu_id=1, core_id=1, package_id=0, siblings="1,3")
    _write_cpu_topology(cpu_sys, cpu_id=2, core_id=0, package_id=0, siblings="0,2")
    _write_cpu_topology(cpu_sys, cpu_id=3, core_id=1, package_id=0, siblings="1,3")

    node0 = node_sys / "node0" / "cpulist"
    node0.parent.mkdir(parents=True, exist_ok=True)
    node0.write_text("0-3\n", encoding="utf-8")

    nested_file = module_sys / "kvm_intel" / "parameters" / "nested"
    nested_file.parent.mkdir(parents=True, exist_ok=True)
    nested_file.write_text("N\n", encoding="utf-8")
    return (cpu_sys, node_sys, module_sys)


def _write_cpu_topology(
    cpu_sys: Path,
    *,
    cpu_id: int,
    core_id: int,
    package_id: int,
    siblings: str,
) -> None:
    base = cpu_sys / f"cpu{cpu_id}" / "topology"
    base.mkdir(parents=True, exist_ok=True)
    (base / "core_id").write_text(f"{core_id}\n", encoding="utf-8")
    (base / "physical_package_id").write_text(f"{package_id}\n", encoding="utf-8")
    (base / "thread_siblings_list").write_text(f"{siblings}\n", encoding="utf-8")
