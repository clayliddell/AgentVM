"""Bridge lifecycle and per-session interface allocation.

Ref: NETWORK-MANAGER-LLD Section 3.1
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

MAX_MAC_ALLOCATION_RETRIES = 1000


class BridgeManager:
    """Bridge lifecycle management.

    This manager currently assumes single-threaded access. Callers using it
    across threads must provide their own synchronization until network
    provisioning adds explicit locking.

    Ref: NETWORK-MANAGER-LLD Section 3.1
    """

    def __init__(
        self,
        *,
        bridge_name: str = "agentvm-br0",
        mac_factory: Callable[[], str] | None = None,
    ) -> None:
        """Initialize a bridge manager.

        Args:
            bridge_name: Host bridge name used for VM networking.
            mac_factory: Optional MAC generator for deterministic testing.

        Returns:
            None

        Ref: NETWORK-MANAGER-LLD Section 3.1
        """

        self._bridge_name = bridge_name
        self._mac_factory = mac_factory or self._generate_mac
        self._session_interfaces: dict[str, tuple[str, str]] = {}
        self._allocated_vnets: set[str] = set()
        self._allocated_macs: set[str] = set()
        self._next_vnet_index = 0

    def ensure_bridge(self) -> str:
        """Return the configured bridge name.

        This is a minimal startup implementation that treats bridge
        verification as a no-op until full network provisioning is added.
        TODO(CLA-26): replace this with real host bridge verification.

        Returns:
            str: Configured bridge name.

        Ref: NETWORK-MANAGER-LLD Section 3.1
        """

        return self._bridge_name

    def allocate_vm_interface(self, session_id: str) -> tuple[str, str]:
        """Allocate a unique vnet name and MAC address.

        Args:
            session_id: Session identifier.

        Returns:
            tuple[str, str]: ``(vnet_name, mac_address)``.

        Ref: NETWORK-MANAGER-LLD Section 3.1
        """

        if not session_id.strip():
            raise ValueError("session_id must be a non-empty string")

        existing = self._session_interfaces.get(session_id)
        if existing is not None:
            return existing

        vnet_name = self._allocate_vnet_name()
        mac_address = self._allocate_unique_mac()
        interface = (vnet_name, mac_address)

        self._session_interfaces[session_id] = interface
        self._allocated_vnets.add(vnet_name)
        self._allocated_macs.add(mac_address)
        return interface

    def deallocate_vm_interface(self, session_id: str) -> None:
        """Release a previously allocated interface for a session.

        Args:
            session_id: Session identifier.

        Returns:
            None

        Ref: NETWORK-MANAGER-LLD Section 3.1
        """

        interface = self._session_interfaces.pop(session_id, None)
        if interface is None:
            return

        vnet_name, mac_address = interface
        self._allocated_vnets.discard(vnet_name)
        self._allocated_macs.discard(mac_address)

    def _allocate_vnet_name(self) -> str:
        candidate = f"vnet{self._next_vnet_index}"
        self._next_vnet_index += 1
        return candidate

    def _allocate_unique_mac(self) -> str:
        for _ in range(MAX_MAC_ALLOCATION_RETRIES):
            try:
                candidate = self._mac_factory().lower()
            except StopIteration as exc:
                raise RuntimeError(
                    "mac_factory exhausted before producing a unique MAC"
                ) from exc
            if candidate not in self._allocated_macs:
                return candidate

        raise RuntimeError("failed to allocate a unique MAC after maximum retries")

    @staticmethod
    def _generate_mac() -> str:
        first_octet = secrets.randbelow(256)
        first_octet |= 0x02
        first_octet &= 0xFE
        remaining = [secrets.randbelow(256) for _ in range(5)]
        octets = [first_octet, *remaining]
        return ":".join(f"{value:02x}" for value in octets)
