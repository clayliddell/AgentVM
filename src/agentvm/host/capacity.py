"""Host capacity detection and allocation tracking.

Ref: HOST-MANAGER-LLD Section 5.2
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from agentvm.config import AgentVMConfig


@dataclass(frozen=True)
class HostCapacity:
    """Current host resource capacity.

    Ref: HOST-MANAGER-LLD Section 3.1
    """

    total_cpu: int
    available_cpu: int
    total_memory_mb: int
    available_memory_mb: int
    total_disk_gb: int
    available_disk_gb: int
    active_vm_count: int
    max_vm_count: int


@dataclass(frozen=True)
class CapacityCheckResult:
    """Result of checking a requested VM spec against capacity.

    Ref: HOST-MANAGER-LLD Section 3.1
    """

    sufficient: bool
    available_cpu: int
    available_memory_mb: int
    available_disk_gb: int
    shortfall: str | None


@dataclass(frozen=True)
class _Allocation:
    cpu_cores: int
    memory_mb: int
    disk_gb: int


class CapacityManager:
    """Tracks host capacity and current allocations.

    Ref: HOST-MANAGER-LLD Section 5.2
    """

    def __init__(
        self,
        config: AgentVMConfig,
        *,
        cpuinfo_path: Path = Path("/proc/cpuinfo"),
        meminfo_path: Path = Path("/proc/meminfo"),
        statvfs: Callable[[str], os.statvfs_result] = os.statvfs,
    ) -> None:
        """Initialize a capacity manager.

        Args:
            config: Runtime AgentVM configuration.
            cpuinfo_path: Path to the host cpuinfo file.
            meminfo_path: Path to the host meminfo file.
            statvfs: Callable used to inspect filesystem capacity.

        Returns:
            None

        Ref: HOST-MANAGER-LLD Section 5.2
        """

        self._config = config
        self._cpuinfo_path = cpuinfo_path
        self._meminfo_path = meminfo_path
        self._statvfs = statvfs
        self._allocations: dict[str, _Allocation] = {}

    def get_capacity(self) -> HostCapacity:
        """Return current host resource availability.

        Returns:
            HostCapacity: Aggregate host capacity and free resources.

        Ref: HOST-MANAGER-LLD Section 3.1
        """

        total_cpu = self._read_cpu_total()
        reserved_cpu = len(set(self._config.resources.reserved_cores))
        allocated_cpu = sum(entry.cpu_cores for entry in self._allocations.values())
        available_cpu = max(total_cpu - reserved_cpu - allocated_cpu, 0)

        total_memory_mb = self._read_memory_total_mb()
        allocated_memory_mb = sum(
            entry.memory_mb for entry in self._allocations.values()
        )
        available_memory_mb = max(
            total_memory_mb
            - self._config.resources.reserved_memory_mb
            - allocated_memory_mb,
            0,
        )

        total_disk_gb, available_disk_gb = self._read_disk_capacity_gb()
        allocated_disk_gb = sum(entry.disk_gb for entry in self._allocations.values())
        available_disk_gb = max(available_disk_gb - allocated_disk_gb, 0)

        return HostCapacity(
            total_cpu=total_cpu,
            available_cpu=available_cpu,
            total_memory_mb=total_memory_mb,
            available_memory_mb=available_memory_mb,
            total_disk_gb=total_disk_gb,
            available_disk_gb=available_disk_gb,
            active_vm_count=len(self._allocations),
            max_vm_count=self._config.host.max_vms,
        )

    def check_spec(
        self, cpu_cores: int, memory_mb: int, disk_gb: int
    ) -> CapacityCheckResult:
        """Check if requested resources fit current availability.

        Args:
            cpu_cores: Requested vCPU count.
            memory_mb: Requested memory in MiB.
            disk_gb: Requested disk size in GiB.

        Returns:
            CapacityCheckResult: Sufficiency and shortfall details.

        Ref: HOST-MANAGER-LLD Section 3.1
        """

        capacity = self.get_capacity()
        shortfalls: list[str] = []

        if capacity.active_vm_count >= capacity.max_vm_count:
            shortfalls.append("vm_count")
        if cpu_cores > capacity.available_cpu:
            shortfalls.append("cpu")
        if memory_mb > capacity.available_memory_mb:
            shortfalls.append("memory")
        if disk_gb > capacity.available_disk_gb:
            shortfalls.append("disk")

        if shortfalls:
            return CapacityCheckResult(
                sufficient=False,
                available_cpu=capacity.available_cpu,
                available_memory_mb=capacity.available_memory_mb,
                available_disk_gb=capacity.available_disk_gb,
                shortfall=", ".join(shortfalls),
            )

        return CapacityCheckResult(
            sufficient=True,
            available_cpu=capacity.available_cpu,
            available_memory_mb=capacity.available_memory_mb,
            available_disk_gb=capacity.available_disk_gb,
            shortfall=None,
        )

    def allocate(
        self, vm_id: str, cpu_cores: int, memory_mb: int, disk_gb: int
    ) -> None:
        """Record resource allocation for one VM.

        Args:
            vm_id: Unique VM identifier.
            cpu_cores: Allocated vCPU count.
            memory_mb: Allocated memory in MiB.
            disk_gb: Allocated disk size in GiB.

        Returns:
            None

        Raises:
            ValueError: If an allocation already exists for ``vm_id``.

        Ref: HOST-MANAGER-LLD Section 3.1
        """

        if vm_id in self._allocations:
            raise ValueError(f"allocation already exists for vm_id={vm_id}")

        self._allocations[vm_id] = _Allocation(
            cpu_cores=cpu_cores,
            memory_mb=memory_mb,
            disk_gb=disk_gb,
        )

    def release(self, vm_id: str) -> None:
        """Release resource allocation for one VM.

        Args:
            vm_id: Unique VM identifier.

        Returns:
            None

        Ref: HOST-MANAGER-LLD Section 3.1
        """

        self._allocations.pop(vm_id, None)

    async def reconcile_allocations(self, metadata_store: object) -> None:
        """Rebuild allocation tracking from metadata records.

        Args:
            metadata_store: Store implementing ``get_active_vms`` or ``list_vms``.

        Returns:
            None

        Ref: HOST-MANAGER-LLD Section 5.2
        """

        vms = await self._fetch_active_vms(metadata_store)

        rebuilt: dict[str, _Allocation] = {}
        for vm in vms:
            vm_id = str(vm.get("id", vm.get("vm_id", "")))
            if not vm_id:
                continue

            try:
                rebuilt[vm_id] = _Allocation(
                    cpu_cores=_to_int(vm["cpu_cores"]),
                    memory_mb=_to_int(vm["memory_mb"]),
                    disk_gb=_to_int(vm["disk_gb"]),
                )
            except (KeyError, TypeError, ValueError):
                continue

        self._allocations = rebuilt

    async def _fetch_active_vms(
        self, metadata_store: object
    ) -> list[dict[str, object]]:
        """Retrieve active VMs from metadata store.

        Ref: HOST-MANAGER-LLD Section 5.2
        """

        response: object

        if hasattr(metadata_store, "get_active_vms"):
            get_active_vms = getattr(metadata_store, "get_active_vms")  # noqa: B009
            response = get_active_vms()
        elif hasattr(metadata_store, "list_vms"):
            list_vms = getattr(metadata_store, "list_vms")  # noqa: B009
            try:
                response = list_vms(status="running")
            except TypeError:
                response = list_vms()
        else:
            raise TypeError(
                "metadata_store must implement get_active_vms() or list_vms()"
            )

        if inspect.isawaitable(response):
            response = await _resolve(cast(Awaitable[object], response))

        if not isinstance(response, list):
            raise TypeError("metadata_store VM query must return list[dict]")

        active: list[dict[str, object]] = []
        for item in response:
            if not isinstance(item, dict):
                continue

            status_value = item.get("status", "running")
            status = str(status_value).lower()
            if status not in {"running", "creating"}:
                continue

            active.append(item)

        return active

    def _read_cpu_total(self) -> int:
        """Read total logical CPU count.

        Ref: HOST-MANAGER-LLD Section 5.2
        """

        try:
            cpuinfo = self._cpuinfo_path.read_text(encoding="utf-8")
        except OSError:
            fallback = os.cpu_count()
            return fallback if fallback is not None else 1

        total = sum(1 for line in cpuinfo.splitlines() if line.startswith("processor"))
        if total > 0:
            return total

        fallback = os.cpu_count()
        return fallback if fallback is not None else 1

    def _read_memory_total_mb(self) -> int:
        """Read total host memory in MB.

        Ref: HOST-MANAGER-LLD Section 5.2
        """

        try:
            for line in self._meminfo_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    total_kb = int(parts[1])
                    return total_kb // 1024
        except (OSError, ValueError, IndexError):
            pass

        return 0

    def _read_disk_capacity_gb(self) -> tuple[int, int]:
        """Read total and available disk in GB for storage base directory.

        Ref: HOST-MANAGER-LLD Section 5.2
        """

        try:
            stat = self._statvfs(self._config.storage.base_dir)
        except OSError:
            return (0, 0)

        total_bytes = stat.f_frsize * stat.f_blocks
        available_bytes = stat.f_frsize * stat.f_bavail
        gib = 1024**3
        return (total_bytes // gib, available_bytes // gib)


def _to_int(value: object) -> int:
    """Convert metadata value into an integer.

    Ref: HOST-MANAGER-LLD Section 5.2
    """

    if isinstance(value, bool):
        raise TypeError("booleans are not valid numeric values")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    if isinstance(value, (bytes, bytearray)):
        return int(value)
    raise TypeError("value is not int-convertible")


async def _resolve(value: Awaitable[object]) -> object:
    """Await and return value from metadata query.

    Ref: HOST-MANAGER-LLD Section 5.2
    """

    return await value
