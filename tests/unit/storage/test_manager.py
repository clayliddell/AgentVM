from __future__ import annotations

from pathlib import Path

from agentvm.config import StorageConfig
from agentvm.storage.manager import StorageManager


def _storage_config(tmp_path: Path) -> StorageConfig:
    return StorageConfig(
        base_dir=str(tmp_path / "agentvm"),
        base_images_dir=str(tmp_path / "agentvm" / "base"),
        vm_data_dir=str(tmp_path / "agentvm" / "vms"),
        shared_dir=str(tmp_path / "agentvm" / "shared"),
        proxy_dir=str(tmp_path / "agentvm" / "proxy"),
    )


def test_ensure_storage_tree_creates_required_directories(tmp_path: Path) -> None:
    manager = StorageManager(_storage_config(tmp_path))

    manager.ensure_storage_tree()

    expected = [
        tmp_path / "agentvm",
        tmp_path / "agentvm" / "base",
        tmp_path / "agentvm" / "vms",
        tmp_path / "agentvm" / "shared",
        tmp_path / "agentvm" / "proxy",
    ]
    assert all(path.is_dir() for path in expected)


def test_ensure_storage_tree_is_idempotent(tmp_path: Path) -> None:
    manager = StorageManager(_storage_config(tmp_path))

    manager.ensure_storage_tree()
    manager.ensure_storage_tree()

    assert (tmp_path / "agentvm" / "vms").is_dir()
