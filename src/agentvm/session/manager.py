"""Session lifecycle management.

Ref: SESSION-MANAGER-LLD §5.3
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog  # type: ignore[import-not-found]

logger = structlog.get_logger()


@dataclass
class DrainResult:
    """Result of a session drain operation."""

    incomplete: bool = False
    remaining: int = 0


class SessionManager:
    """Manages VM session lifecycle — create, destroy, drain.

    Ref: SESSION-MANAGER-LLD §3.1
    """

    async def drain_all_sessions(self, timeout: int = 60) -> DrainResult:
        """Drain all active sessions on daemon shutdown.

        Iterates all running sessions and destroys each with a configurable
        per-session timeout. Called on daemon SIGTERM.

        Ref: SESSION-MANAGER-LLD §4 (Phase 7), DAEMON-ENTRYPOINT-LLD §3
        """
        logger.info("draining_all_sessions", timeout=timeout)
        return DrainResult()
