"""Cloud-init ISO generation and management.

Ref: STORAGE-MANAGER-LLD Section 5.3
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
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

        if not shutil.which("genisoimage"):
            raise DependencyError(
                "genisoimage is not installed. "
                "Install it with: apt-get install genisoimage"
            )

        subprocess.run(  # noqa: S603, S607
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

        return str(iso_path)

    def delete_cloud_init_iso(self, vm_id: str) -> None:
        """Delete the cloud-init ISO for a VM.

        Idempotent: does not raise if the ISO does not exist.

        Args:
            vm_id: Unique VM identifier.

        Returns:
            None

        Ref: STORAGE-MANAGER-LLD Section 5.4
        """

        iso_path = self._iso_path(vm_id)
        if iso_path.exists():
            iso_path.unlink()

    def _build_user_data(self, config: CloudInitConfig) -> str:
        """Build cloud-init user-data content."""

        dns_list = ", ".join(f"{ip}" for ip in config.dns_servers)

        return (  # noqa: UP032
            "#cloud-config\n"
            "hostname: {hostname}\n"
            "ssh_authorized_keys:\n"
            "  - {ssh_key}\n"
            "write_files:\n"
            "  - path: /etc/environment.d/agentvm-proxy.conf\n"
            "    content: |\n"
            "      OPENAI_BASE_URL={proxy_base_url}\n"
            "      OPENAI_API_KEY={proxy_key}\n"
            "      ANTHROPIC_BASE_URL={proxy_base_url}\n"
            "      ANTHROPIC_API_KEY={proxy_key}\n"
            "runcmd:\n"
            "  - mkdir -p {mount}\n"
            "  - |-\n"
            "    grep -q '{mount}' /etc/fstab || \\\n"
            "    echo 'host_shared {mount} 9p trans=virtio,version=9p2000.L 0 0' >> /etc/fstab\n"  # noqa: E501
            "  - mount {mount} || true\n"
            "  - systemctl restart systemd-networkd || true\n"
            "bootcmd:\n"
            "  - |\n"
            "    cat > /etc/systemd/network/10-eth0.network << 'EOF'\n"
            "    [Match]\n"
            "    Name=eth0\n"
            "    [Network]\n"
            "    Address=10.0.0.0/24\n"
            "    Gateway={gateway}\n"
            "    DNS={dns}\n"
            "    EOF\n"
        ).format(
            hostname=config.hostname,
            ssh_key=config.ssh_public_key,
            proxy_base_url=config.proxy_base_url,
            proxy_key=config.proxy_dummy_key,
            mount=config.shared_folder_mount,
            gateway=config.network_gateway,
            dns=dns_list,
        )

    def _build_meta_data(self, vm_id: str, hostname: str) -> str:
        """Build cloud-init meta-data content."""

        return (  # noqa: UP032
            "instance-id: {vm_id}\nlocal-hostname: {hostname}\n"
        ).format(vm_id=vm_id, hostname=hostname)


class DependencyError(RuntimeError):
    """Raised when a required external dependency is missing."""
