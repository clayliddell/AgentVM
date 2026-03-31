"""Metadata persistence via SQLite.

Ref: METADATA-STORE-LLD §3.2
"""

from __future__ import annotations

import structlog  # type: ignore[import-not-found]

logger = structlog.get_logger()


class MetadataStore:
    """Async metadata store backed by SQLite (WAL mode).

    Ref: METADATA-STORE-LLD §3.2
    """

    async def initialize(self) -> None:
        """Open database, enable WAL, create schema, run migrations.

        Ref: METADATA-STORE-LLD §3.2
        """
        logger.info("metadata_store_initialized")

    async def close(self) -> None:
        """Close database connection.

        Ref: METADATA-STORE-LLD §3.2
        """
        logger.info("metadata_store_closed")
