"""Cloud-init ISO generation and management.

Ref: STORAGE-MANAGER-LLD Section 5.3
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CloudInitConfig:
    """Configuration for cloud-init ISO generation.

    Ref: STORAGE-MANAGER-LLD Section 3.1
    """

    ssh_public_key: str
    hostname: str
    proxy_base_url: str
    proxy_dummy_key: str
    shared_folder_mount: str
    network_gateway: str
    network_address: str
    dns_servers: list[str]


class CloudInitManager:
    """Manages cloud-init ISO lifecycle for VMs.

    Ref: STORAGE-MANAGER-LLD Section 5.3
    """

    def __init__(
        self,
        vm_data_dir: str = "/var/lib/agentvm/vms",
    ) -> None:
        """Initialize the cloud-init manager.

        Args:
            vm_data_dir: Base directory for VM storage.

        Returns:
            None
        """

        self._vm_data_dir = Path(vm_data_dir)

    def _vm_dir(self, vm_id: str) -> Path:
        """Return the VM-specific directory path."""

        return self._vm_data_dir / f"vm-{vm_id}"

    def _iso_path(self, vm_id: str) -> Path:
        """Return the expected cloud-init ISO path for a VM."""

        return self._vm_dir(vm_id) / "cloud-init.iso"

    def generate_cloud_init_iso(self, vm_id: str, config: CloudInitConfig) -> str:
        """Generate a cloud-init ISO for a VM.

        Creates user-data and meta-data files, then builds an ISO
        using genisoimage.

        Args:
            vm_id: Unique VM identifier.
            config: Cloud-init configuration.

        Returns:
            str: Absolute path to the generated ISO file.

        Raises:
            DependencyError: If genisoimage is not installed.
            OSError: If ISO generation fails.

        Ref: STORAGE-MANAGER-LLD Section 5.3
        """

        vm_dir = self._vm_dir(vm_id)
        vm_dir.mkdir(parents=True, exist_ok=True)

        user_data = self._build_user_data(config)
        meta_data = self._build_meta_data(vm_id, config.hostname)

        user_data_path = vm_dir / "user-data"
        meta_data_path = vm_dir / "meta-data"

        user_data_path.write_text(user_data, encoding="utf-8")
        meta_data_path.write_text(meta_data, encoding="utf-8")

        iso_path = self._iso_path(vm_id)

        try:
            subprocess.run(  # noqa: S603
                [  # noqa: S607
                    "genisoimage",
                    "-output",
                    str(iso_path),
                    "-volid",
                    "cidata",
                    "-joliet",
                    "-rock",
                    str(user_data_path),
                    str(meta_data_path),
                ],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError as exc:
            raise DependencyError(
                "genisoimage is not installed. "
                "Install it with: apt-get install genisoimage"
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
            raise OSError(
                f"genisoimage failed (exit {exc.returncode}): {stderr}"
            ) from exc

        return str(iso_path)

    def delete_cloud_init_iso(self, vm_id: str) -> None:
        """Delete the cloud-init ISO and intermediate files for a VM.

        Removes the ISO, user-data, and meta-data files. Idempotent:
        does not raise if files do not exist.

        Args:
            vm_id: Unique VM identifier.

        Returns:
            None

        Ref: STORAGE-MANAGER-LLD Section 5.4
        """

        vm_dir = self._vm_dir(vm_id)
        for name in ("cloud-init.iso", "user-data", "meta-data"):
            path = vm_dir / name
            if path.exists():
                path.unlink()

    def _build_user_data(self, config: CloudInitConfig) -> str:
        """Build cloud-init user-data content.

        Uses yaml.safe_dump to serialize values, preventing injection
        via YAML metacharacters in user-provided strings.
        """

        proxy_env_block = (
            f"OPENAI_BASE_URL={config.proxy_base_url}\n"
            f"OPENAI_API_KEY={config.proxy_dummy_key}\n"
            f"ANTHROPIC_BASE_URL={config.proxy_base_url}\n"
            f"ANTHROPIC_API_KEY={config.proxy_dummy_key}\n"
        )

        quoted_mount = shlex.quote(config.shared_folder_mount)

        cloud_config = {
            "hostname": config.hostname,
            "ssh_authorized_keys": [config.ssh_public_key],
            "write_files": [
                {
                    "path": "/etc/environment.d/agentvm-proxy.conf",
                    "content": proxy_env_block,
                },
            ],
            "runcmd": [
                f"mkdir -p {quoted_mount}",
                (
                    f"grep -q {quoted_mount} /etc/fstab || "
                    f"echo {quoted_mount} 9p trans=virtio,version=9p2000.L 0 0 "
                    ">> /etc/fstab"
                ),
                f"mount {quoted_mount} || true",
                "systemctl restart systemd-networkd || true",
            ],
            "bootcmd": [
                (
                    "cat > /etc/systemd/network/10-eth0.network << 'EOF'\n"
                    "[Match]\n"
                    "Name=eth0\n"
                    "[Network]\n"
                    f"Address={config.network_address}\n"
                    f"Gateway={config.network_gateway}\n"
                    f"DNS={', '.join(config.dns_servers)}\n"
                    "EOF"
                ),
            ],
        }

        return "#cloud-config\n" + yaml.safe_dump(
            cloud_config, default_flow_style=False, sort_keys=False
        )

    def _build_meta_data(self, vm_id: str, hostname: str) -> str:
        """Build cloud-init meta-data content."""

        return f"instance-id: {vm_id}\nlocal-hostname: {hostname}\n"


class DependencyError(RuntimeError):
    """Raised when a required external dependency is missing."""
