"""Storage directory management.

Ref: STORAGE-MANAGER-LLD Section 5.1
"""

from __future__ import annotations

from pathlib import Path

from agentvm.config import StorageConfig


class StorageManager:
    """Ensures required on-disk storage layout exists.

    Ref: STORAGE-MANAGER-LLD Section 5.1
    """

    def __init__(self, storage_config: StorageConfig) -> None:
        """Initialize storage manager.

        Args:
            storage_config: Storage path configuration.

        Returns:
            None

        Ref: STORAGE-MANAGER-LLD Section 5.1
        """

        self._config = storage_config

    def ensure_storage_tree(self) -> None:
        """Create required storage directories if missing.

        Returns:
            None

        Ref: STORAGE-MANAGER-LLD Section 5.1
        """

        for path in (
            self._config.base_dir,
            self._config.base_images_dir,
            self._config.vm_data_dir,
            self._config.shared_dir,
            self._config.proxy_dir,
        ):
            Path(path).mkdir(parents=True, exist_ok=True)
