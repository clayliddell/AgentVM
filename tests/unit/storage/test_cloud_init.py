"""Tests for cloud-init ISO management.

Ref: STORAGE-MANAGER-LLD Section 5.3
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

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
        network_address="10.0.0.0/24",
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

    def test_removes_user_data_and_meta_data(self, tmp_path: Path) -> None:
        vm_dir = tmp_path / f"vm-{VM_ID}"
        vm_dir.mkdir(parents=True)
        for name in ("cloud-init.iso", "user-data", "meta-data"):
            (vm_dir / name).write_text(f"fake {name}", encoding="utf-8")

        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        manager.delete_cloud_init_iso(VM_ID)

        assert not (vm_dir / "cloud-init.iso").exists()
        assert not (vm_dir / "user-data").exists()
        assert not (vm_dir / "meta-data").exists()


class TestGenerateCloudInitIso:
    """Tests for CloudInitManager.generate_cloud_init_iso."""

    def test_raises_dependency_error_when_genisoimage_missing(
        self, tmp_path: Path
    ) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))

        with (
            patch(
                "agentvm.storage.cloud_init.subprocess.run",
                side_effect=FileNotFoundError("genisoimage"),
            ),
            pytest.raises(DependencyError),
        ):
            manager.generate_cloud_init_iso(VM_ID, _make_config())

    def test_raises_os_error_on_genisoimage_failure(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        error = subprocess.CalledProcessError(1, "genisoimage", stderr=b"fail")
        error.stderr = b"disk full"

        with (
            patch(
                "agentvm.storage.cloud_init.subprocess.run",
                side_effect=error,
            ),
            pytest.raises(OSError, match="genisoimage failed"),
        ):
            manager.generate_cloud_init_iso(VM_ID, _make_config())

    def test_creates_iso_with_genisoimage(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        mock_run = patch(
            "agentvm.storage.cloud_init.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0),
        )

        with mock_run as run_mock:
            iso_path = manager.generate_cloud_init_iso(VM_ID, _make_config())

        assert iso_path.endswith("cloud-init.iso")
        assert "genisoimage" in str(run_mock.call_args_list)
        vm_dir = tmp_path / f"vm-{VM_ID}"
        assert vm_dir.exists()
        assert (vm_dir / "user-data").exists()
        assert (vm_dir / "meta-data").exists()

    def test_user_data_contains_ssh_key(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        config = _make_config()

        user_data = manager._build_user_data(config)
        parsed = _parse_user_data(user_data)

        assert config.ssh_public_key in parsed["ssh_authorized_keys"]

    def test_user_data_contains_proxy_env_vars(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        config = _make_config()

        user_data = manager._build_user_data(config)
        parsed = _parse_user_data(user_data)

        content = parsed["write_files"][0]["content"]
        assert config.proxy_base_url in content
        assert config.proxy_dummy_key in content
        assert "OPENAI_BASE_URL" in content
        assert "OPENAI_API_KEY" in content
        assert "ANTHROPIC_BASE_URL" in content
        assert "ANTHROPIC_API_KEY" in content

    def test_user_data_contains_hostname(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        config = _make_config()

        user_data = manager._build_user_data(config)
        parsed = _parse_user_data(user_data)

        assert parsed["hostname"] == config.hostname

    def test_user_data_contains_shared_folder_mount(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        config = _make_config()

        user_data = manager._build_user_data(config)
        parsed = _parse_user_data(user_data)

        runcmd_text = " ".join(parsed["runcmd"])
        assert config.shared_folder_mount in runcmd_text

    def test_user_data_contains_network_address(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        config = _make_config()

        user_data = manager._build_user_data(config)
        parsed = _parse_user_data(user_data)

        bootcmd_text = " ".join(parsed["bootcmd"])
        assert config.network_address in bootcmd_text
        assert config.network_gateway in bootcmd_text

    def test_meta_data_format(self, tmp_path: Path) -> None:
        manager = CloudInitManager(vm_data_dir=str(tmp_path))
        config = _make_config()

        meta_data = manager._build_meta_data(VM_ID, config.hostname)

        lines = meta_data.splitlines()
        assert lines[0] == f"instance-id: {VM_ID}"
        assert lines[1] == f"local-hostname: {config.hostname}"


def _parse_user_data(user_data: str) -> dict:
    """Parse cloud-init user-data YAML, skipping the #cloud-config header."""

    assert user_data.startswith("#cloud-config\n")
    return yaml.safe_load(user_data)
