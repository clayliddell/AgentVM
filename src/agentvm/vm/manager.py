"""VM lifecycle and status management.

Ref: VM-MANAGER-LLD Section 3.1
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class VMSpec:
    """Requested VM specification.

    Ref: VM-MANAGER-LLD Section 3.1
    """

    vm_id: str
    session_id: str
    image_id: str
    cpu_cores: int
    memory_mb: int
    disk_gb: int


@dataclass(frozen=True)
class VMConnectionInfo:
    """Connection information for a created VM.

    Ref: VM-MANAGER-LLD Section 3.2
    """

    vm_id: str
    ssh_host: str
    ssh_port: int


@dataclass(frozen=True)
class VMStatus:
    """Current status for one VM.

    Ref: VM-MANAGER-LLD Section 3.2
    """

    vm_id: str
    session_id: str
    state: str
    cpu_percent: float
    memory_mb: int


class VMManager:
    """Coordinates VM metadata and runtime state.

    Ref: VM-MANAGER-LLD Section 5.1
    """

    def __init__(
        self,
        metadata_store: object,
        *,
        capacity_manager: object | None = None,
        runtime_state_provider: Any | None = None,
    ) -> None:
        """Initialize VM manager dependencies.

        Args:
            metadata_store: Backing metadata persistence component.
            capacity_manager: Optional capacity checker dependency.
            runtime_state_provider: Optional callable returning runtime state.

        Returns:
            None

        Ref: VM-MANAGER-LLD Section 5.1
        """

        self._store = metadata_store
        self._capacity_manager = capacity_manager
        self._runtime_state_provider = runtime_state_provider

    async def create_vm(self, spec: VMSpec) -> VMConnectionInfo:
        """Persist a VM record and return connection information.

        Args:
            spec: Requested VM specification.

        Returns:
            VMConnectionInfo: Initial VM connection information.

        Ref: VM-MANAGER-LLD Section 3.1
        """

        create_vm = getattr(self._store, "create_vm", None)
        if not callable(create_vm):
            raise ValueError("metadata store missing create_vm()")

        create_vm_call = cast(
            Callable[[dict[str, object]], Awaitable[object]],
            create_vm,
        )

        await create_vm_call(
            {
                "id": spec.vm_id,
                "session_id": spec.session_id,
                "base_image": spec.image_id,
                "cpu_cores": spec.cpu_cores,
                "memory_mb": spec.memory_mb,
                "disk_gb": spec.disk_gb,
                "status": "creating",
            }
        )
        return VMConnectionInfo(vm_id=spec.vm_id, ssh_host="127.0.0.1", ssh_port=22)

    async def destroy_vm(self, vm_id: str) -> None:
        """Delete VM metadata.

        Args:
            vm_id: VM identifier.

        Returns:
            None

        Ref: VM-MANAGER-LLD Section 3.1
        """

        delete_vm = getattr(self._store, "delete_vm", None)
        if not callable(delete_vm):
            raise ValueError("metadata store missing delete_vm()")
        delete_vm_call = cast(Callable[[str], Awaitable[object]], delete_vm)
        await delete_vm_call(vm_id)

    async def get_vm_status(self, vm_id: str) -> VMStatus:
        """Return current VM status.

        Args:
            vm_id: VM identifier.

        Returns:
            VMStatus: Current VM state and metrics.

        Raises:
            ValueError: If the VM record is not found.

        Ref: VM-MANAGER-LLD Section 3.1
        """

        get_vm = getattr(self._store, "get_vm", None)
        if not callable(get_vm):
            raise ValueError("metadata store missing get_vm()")

        get_vm_call = cast(Callable[[str], Awaitable[object]], get_vm)
        vm_record = await get_vm_call(vm_id)
        if not isinstance(vm_record, dict):
            raise ValueError(f"vm not found: {vm_id}")

        state = str(vm_record.get("status", "unknown"))
        cpu_percent = 0.0
        memory_mb = int(vm_record.get("memory_mb", 0))

        if callable(self._runtime_state_provider):
            runtime_state = self._runtime_state_provider(vm_id)
            if isinstance(runtime_state, dict):
                state = str(runtime_state.get("state", state))
                cpu_percent = float(runtime_state.get("cpu_percent", cpu_percent))
                memory_mb = int(runtime_state.get("memory_mb", memory_mb))

        session_id = str(vm_record.get("session_id", ""))
        return VMStatus(
            vm_id=vm_id,
            session_id=session_id,
            state=state,
            cpu_percent=cpu_percent,
            memory_mb=memory_mb,
        )

    def check_host_capacity(self, spec: VMSpec) -> object:
        """Check whether host capacity can satisfy the VM specification.

        Args:
            spec: Requested VM specification.

        Returns:
            object: Capacity check result from capacity manager.

        Ref: VM-MANAGER-LLD Section 3.1
        """

        if self._capacity_manager is None:
            raise ValueError("capacity manager not configured")

        check_spec = getattr(self._capacity_manager, "check_spec", None)
        if not callable(check_spec):
            raise ValueError("capacity manager missing check_spec()")
        return check_spec(spec.cpu_cores, spec.memory_mb, spec.disk_gb)
