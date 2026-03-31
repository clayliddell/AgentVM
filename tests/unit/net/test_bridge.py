from __future__ import annotations

import re

import pytest

from agentvm.net.bridge import BridgeManager


def test_allocate_vm_interface_returns_vnet_name_and_mac() -> None:
    manager = BridgeManager()

    vnet_name, mac_address = manager.allocate_vm_interface("session-1")

    assert vnet_name == "vnet0"
    assert re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", mac_address) is not None
    first_octet = int(mac_address.split(":")[0], 16)
    assert (first_octet & 0b10) == 0b10
    assert (first_octet & 0b1) == 0


def test_allocate_vm_interface_allocates_unique_interfaces_per_session() -> None:
    manager = BridgeManager()

    first_vnet, first_mac = manager.allocate_vm_interface("session-1")
    second_vnet, second_mac = manager.allocate_vm_interface("session-2")

    assert first_vnet == "vnet0"
    assert second_vnet == "vnet1"
    assert first_mac != second_mac


def test_allocate_vm_interface_is_idempotent_for_same_session() -> None:
    manager = BridgeManager()

    first = manager.allocate_vm_interface("session-1")
    second = manager.allocate_vm_interface("session-1")

    assert second == first


def test_allocate_vm_interface_retries_when_mac_is_already_allocated() -> None:
    sequence = iter(
        [
            "02:11:22:33:44:55",
            "02:11:22:33:44:55",
            "02:66:77:88:99:aa",
            AssertionError("unexpected extra mac_factory call"),
        ]
    )

    def mac_factory() -> str:
        value = next(sequence)
        if isinstance(value, Exception):
            raise value
        return value

    manager = BridgeManager(mac_factory=mac_factory)
    manager.allocate_vm_interface("session-1")

    _, second_mac = manager.allocate_vm_interface("session-2")

    assert second_mac == "02:66:77:88:99:aa"


def test_allocate_vm_interface_raises_when_unique_mac_exhausted() -> None:
    manager = BridgeManager(mac_factory=lambda: "02:11:22:33:44:55")
    manager.allocate_vm_interface("session-1")

    with pytest.raises(RuntimeError, match="maximum retries"):
        manager.allocate_vm_interface("session-2")


def test_allocate_vm_interface_rejects_empty_session_id() -> None:
    manager = BridgeManager()

    with pytest.raises(ValueError, match="session_id"):
        manager.allocate_vm_interface("   ")


def test_deallocate_vm_interface_releases_mac_for_reuse() -> None:
    sequence = iter(
        [
            "02:11:22:33:44:55",
            "02:66:77:88:99:aa",
            "02:11:22:33:44:55",
        ]
    )
    manager = BridgeManager(mac_factory=lambda: next(sequence))

    manager.allocate_vm_interface("session-1")
    manager.allocate_vm_interface("session-2")
    manager.deallocate_vm_interface("session-1")

    _, mac_address = manager.allocate_vm_interface("session-3")

    assert mac_address == "02:11:22:33:44:55"
