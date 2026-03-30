"""Tests for cloud-init ISO management.

Ref: STORAGE-MANAGER-LLD Section 5.3
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agentvm.storage.cloud_init import (
    CloudInitConfig,
    CloudInitManager,
    DependencyError,
)

VM_ID = "test-vm-001"


def _make_config() -> CloudInitConfig:
    return CloudInitConfig(
        ssh_public_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest",
        hostname="agentvm-test",
        proxy_base_url="http://10.0.0.1:23760/v1",
        proxy_dummy_key="sk-proxy-test",
        shared_folder_mount="/mnt/shared",
        network_gateway="10.0.0.1",
        dns_servers=["8.8.8.8", "8.8.4.4"],
    )


class TestDeleteCloudInitIso:
    """Tests for CloudInitManager.delete_cloud_init_iso."""

    def test_deletes_iso_when_it_exists(self, tmp_path: Path) -> None:
        vm_dir = tmp_path / f"vm-{VM_ID}"
        vm_dir.mkdir(parents=True)
        iso_file = vm_dir / "cloud-init.iso"
        iso_file.write_text("fake iso", encoding="utf-8")

        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        manager.delete_cloud_init_iso(VM_ID)

        assert not iso_file.exists()

    def test_is_idempotent_when_iso_does_not_exist(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))

        manager.delete_cloud_init_iso(VM_ID)

    def test_only_removes_iso_not_vm_dir(self, tmp_path: Path) -> None:
        vm_dir = tmp_path / f"vm-{VM_ID}"
        vm_dir.mkdir(parents=True)
        iso_file = vm_dir / "cloud-init.iso"
        iso_file.write_text("fake iso", encoding="utf-8")
        other_file = vm_dir / "disk.qcow2"
        other_file.write_text("fake disk", encoding="utf-8")

        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        manager.delete_cloud_init_iso(VM_ID)

        assert not iso_file.exists()
        assert other_file.exists()
        assert vm_dir.is_dir()


class TestGenerateCloudInitIso:
    """Tests for CloudInitManager.generate_cloud_init_iso."""

    def test_raises_when_genisoimage_missing(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))

        with (
            patch("shutil.which", return_value=None),
            pytest.raises(DependencyError),
        ):
            manager.generate_cloud_init_iso(VM_ID, _make_config())

    def test_creates_vm_dir_and_iso(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))

        iso_path = tmp_path / f"vm-{VM_ID}" / "cloud-init.iso"
        iso_path.parent.mkdir(parents=True)
        iso_path.write_bytes(b"fake-iso-content")

        result = manager._iso_path(VM_ID)
        assert result == iso_path

    def test_user_data_contains_ssh_key(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        config = _make_config()

        user_data = manager._build_user_data(config)

        assert config.ssh_public_key in user_data

    def test_user_data_contains_proxy_env_vars(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        config = _make_config()

        user_data = manager._build_user_data(config)

        assert "OPENAI_BASE_URL" in user_data
        assert "OPENAI_API_KEY" in user_data
        assert "ANTHROPIC_BASE_URL" in user_data
        assert "ANTHROPIC_API_KEY" in user_data
        assert config.proxy_base_url in user_data
        assert config.proxy_dummy_key in user_data

    def test_user_data_contains_hostname(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        config = _make_config()

        user_data = manager._build_user_data(config)

        assert config.hostname in user_data

    def test_user_data_contains_shared_folder_mount(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        config = _make_config()

        user_data = manager._build_user_data(config)

        assert config.shared_folder_mount in user_data

    def test_meta_data_contains_instance_id_and_hostname(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        config = _make_config()

        meta_data = manager._build_meta_data(VM_ID, config.hostname)

        assert VM_ID in meta_data
        assert config.hostname in meta_data
