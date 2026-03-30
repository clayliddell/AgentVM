"""CPU topology and nested virtualization detection.

Ref: HOST-MANAGER-LLD Section 5.1
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CPUTopology:
    """Discovered host CPU topology.

    Ref: HOST-MANAGER-LLD Section 3.2
    """

    total_cores: int
    cores_per_socket: int
    numa_nodes: int
    cores_per_numa: list[int]
    hyperthread_pairs: dict[int, int]
    nested_virtualization: bool


def detect_nested_virt_support(sys_module_path: Path = Path("/sys/module")) -> bool:
    """Detect nested virtualization support from KVM module parameters.

    Args:
        sys_module_path: Root path that contains KVM module parameter files.

    Returns:
        bool: ``True`` when nested virtualization is enabled.

    Ref: HOST-MANAGER-LLD Section 5.1
    """

    candidate_files = (
        sys_module_path / "kvm_intel" / "parameters" / "nested",
        sys_module_path / "kvm_amd" / "parameters" / "nested",
    )

    for candidate in candidate_files:
        try:
            value = candidate.read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        if value in {"y", "1", "true"}:
            return True

    return False


class CPUMapManager:
    """Reads host CPU layout from sysfs.

    Ref: HOST-MANAGER-LLD Section 5.1
    """

    def __init__(
        self,
        *,
        cpu_sys_path: Path = Path("/sys/devices/system/cpu"),
        node_sys_path: Path = Path("/sys/devices/system/node"),
        module_sys_path: Path = Path("/sys/module"),
    ) -> None:
        """Initialize CPU map manager paths.

        Args:
            cpu_sys_path: Root CPU sysfs directory.
            node_sys_path: Root NUMA node sysfs directory.
            module_sys_path: Root module sysfs directory.

        Returns:
            None

        Ref: HOST-MANAGER-LLD Section 5.1
        """

        self._cpu_sys_path = cpu_sys_path
        self._node_sys_path = node_sys_path
        self._module_sys_path = module_sys_path

    def get_topology(self) -> CPUTopology:
        """Read topology from sysfs.

        Returns:
            CPUTopology: Host topology including NUMA and sibling data.

        Ref: HOST-MANAGER-LLD Section 3.2
        """

        cpu_ids = self._discover_cpu_ids()
        if not cpu_ids:
            cpu_ids = [0]

        package_to_cores: dict[int, set[int]] = {}
        hyperthread_pairs: dict[int, int] = {}

        for cpu_id in cpu_ids:
            cpu_path = self._cpu_sys_path / f"cpu{cpu_id}" / "topology"
            core_id = self._read_int(cpu_path / "core_id", default=cpu_id)
            package_id = self._read_int(cpu_path / "physical_package_id", default=0)

            package_to_cores.setdefault(package_id, set()).add(core_id)
            self._collect_hyperthread_pairs(
                cpu_path / "thread_siblings_list", hyperthread_pairs
            )

        numa_cores = self._discover_numa_cores()
        if not numa_cores:
            numa_cores = {0: cpu_ids}

        cores_per_numa = [len(cores) for _, cores in sorted(numa_cores.items())]
        cores_per_socket = max(
            (len(cores) for cores in package_to_cores.values()), default=len(cpu_ids)
        )

        return CPUTopology(
            total_cores=len(cpu_ids),
            cores_per_socket=cores_per_socket,
            numa_nodes=len(numa_cores),
            cores_per_numa=cores_per_numa,
            hyperthread_pairs=hyperthread_pairs,
            nested_virtualization=detect_nested_virt_support(self._module_sys_path),
        )

    def allocate_cores(
        self,
        count: int,
        reserved: list[int],
        already_allocated: list[int],
    ) -> tuple[str, int]:
        """Allocate CPU cores while honoring reservations.

        Args:
            count: Number of cores to allocate.
            reserved: Cores reserved for host/system usage.
            already_allocated: Cores currently assigned to other VMs.

        Returns:
            tuple[str, int]: Cpuset string and selected NUMA node id.

        Raises:
            ValueError: If ``count`` is non-positive or insufficient cores exist.

        Ref: HOST-MANAGER-LLD Section 3.2
        """

        if count <= 0:
            raise ValueError("count must be positive")

        topology = self.get_topology()
        blocked = set(reserved) | set(already_allocated)
        for reserved_core in reserved:
            sibling = topology.hyperthread_pairs.get(reserved_core)
            if sibling is not None:
                blocked.add(sibling)

        numa_cores = self._discover_numa_cores()
        if not numa_cores:
            numa_cores = {0: list(range(topology.total_cores))}

        for node_id, cores in sorted(numa_cores.items()):
            available = [core for core in cores if core not in blocked]
            if len(available) >= count:
                selected = available[:count]
                return (_format_cpuset(selected), node_id)

        fallback = [core for core in range(topology.total_cores) if core not in blocked]
        if len(fallback) < count:
            raise ValueError("insufficient unallocated CPU cores")

        selected = fallback[:count]
        return (_format_cpuset(selected), 0)

    def release_cores(self, cores: list[int]) -> None:
        """Release cores back to pool.

        Args:
            cores: Core ids to release.

        Returns:
            None

        Ref: HOST-MANAGER-LLD Section 3.2
        """

        _ = cores

    def _discover_cpu_ids(self) -> list[int]:
        cpu_ids: list[int] = []
        for candidate in self._cpu_sys_path.glob("cpu[0-9]*"):
            name = candidate.name
            try:
                cpu_ids.append(int(name[3:]))
            except ValueError:
                continue
        cpu_ids.sort()
        return cpu_ids

    def _discover_numa_cores(self) -> dict[int, list[int]]:
        numa: dict[int, list[int]] = {}
        for candidate in self._node_sys_path.glob("node[0-9]*"):
            name = candidate.name
            try:
                node_id = int(name[4:])
            except ValueError:
                continue

            cpulist_path = candidate / "cpulist"
            try:
                cpulist = cpulist_path.read_text(encoding="utf-8").strip()
            except OSError:
                continue

            numa[node_id] = _parse_cpu_list(cpulist)

        return numa

    def _collect_hyperthread_pairs(
        self,
        siblings_file: Path,
        output: dict[int, int],
    ) -> None:
        try:
            siblings_raw = siblings_file.read_text(encoding="utf-8").strip()
        except OSError:
            return

        siblings = _parse_cpu_list(siblings_raw)
        if len(siblings) != 2:
            return

        first, second = siblings
        output[first] = second
        output[second] = first

    def _read_int(self, path: Path, *, default: int) -> int:
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return default


def _parse_cpu_list(value: str) -> list[int]:
    cpus: list[int] = []
    for segment in value.split(","):
        segment = segment.strip()
        if not segment:
            continue
        if "-" not in segment:
            cpus.append(int(segment))
            continue

        start_raw, end_raw = segment.split("-", 1)
        start = int(start_raw)
        end = int(end_raw)
        cpus.extend(range(start, end + 1))

    return sorted(set(cpus))


def _format_cpuset(cores: list[int]) -> str:
    ordered = sorted(set(cores))
    if not ordered:
        return ""

    ranges: list[str] = []
    start = ordered[0]
    end = ordered[0]

    for core in ordered[1:]:
        if core == end + 1:
            end = core
            continue

        ranges.append(str(start) if start == end else f"{start}-{end}")
        start = core
        end = core

    ranges.append(str(start) if start == end else f"{start}-{end}")
    return ",".join(ranges)
