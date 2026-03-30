"""AgentVM daemon entrypoint — initialization, signal handling, graceful shutdown.

Ref: DAEMON-ENTRYPOINT-LLD §3, §5.2
"""

from __future__ import annotations

import signal
from dataclasses import dataclass
from types import FrameType

import structlog
import uvicorn

from agentvm.config import AgentVMConfig
from agentvm.db.store import MetadataStore
from agentvm.observe.metrics import MetricsCollector
from agentvm.session.manager import SessionManager

logger = structlog.get_logger()

DRAIN_TIMEOUT_SECONDS = 60
"""Max seconds to wait for session drain during shutdown.

Ref: DAEMON-ENTRYPOINT-LLD §2 (DE-NFR-02)
"""


@dataclass
class _DaemonState:
    """Internal state container for daemon components.

    Holds references to all long-lived components so that signal handlers
    and the shutdown sequence can access them.
    """

    server: uvicorn.Server | None = None
    session_manager: SessionManager | None = None
    metrics: MetricsCollector | None = None
    store: MetadataStore | None = None
    shutting_down: bool = False


_state = _DaemonState()


def graceful_shutdown(signum: int, frame: FrameType | None) -> None:
    """Handle SIGTERM/SIGINT — stop API server, drain sessions, close store.

    Ref: DAEMON-ENTRYPOINT-LLD §3 (shutdown sequence), §5.2
    """
    if _state.shutting_down:
        logger.warning("shutdown_already_in_progress", signal=signum)
        return

    _state.shutting_down = True
    logger.info("shutdown_signal_received", signal=signum)

    # 1. Stop accepting new API requests
    #    Ref: DAEMON-ENTRYPOINT-LLD §3 step 1
    if _state.server is not None:
        _state.server.should_exit = True

    # 2. Drain active sessions
    #    Ref: DAEMON-ENTRYPOINT-LLD §3 step 2
    if _state.session_manager is not None:
        _state.session_manager.drain_all_sessions(timeout=DRAIN_TIMEOUT_SECONDS)

    # 3. Stop metrics exporter
    #    Ref: DAEMON-ENTRYPOINT-LLD §3 step 3
    if _state.metrics is not None:
        _state.metrics.stop_exporter()

    logger.info("daemon_shutdown_complete")


async def _close_store() -> None:
    """Close metadata store connection asynchronously.

    Ref: DAEMON-ENTRYPOINT-LLD §3 step 4
    """
    if _state.store is not None:
        await _state.store.close()


def register_signal_handlers() -> None:
    """Register SIGTERM and SIGINT handlers for graceful shutdown.

    Ref: DAEMON-ENTRYPOINT-LLD §3 step 15
    """
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)


async def run_daemon(config: AgentVMConfig) -> None:
    """Run the daemon with uvicorn, wiring all components.

    Ref: DAEMON-ENTRYPOINT-LLD §3 (full startup sequence)
    """
    # Stub: initialize components
    _state.store = MetadataStore()
    await _state.store.initialize()

    _state.session_manager = SessionManager()

    _state.metrics = MetricsCollector()
    if config.observability.metrics_enabled:
        _state.metrics.start_exporter(config.observability.metrics_port)

    # Build uvicorn server (so we can access server.should_exit)
    # Ref: DAEMON-ENTRYPOINT-LLD §3 step 16
    from agentvm.api.app import create_app

    app = create_app()
    uvicorn_config = uvicorn.Config(
        app,
        host=config.api.host,
        port=config.api.port,
        log_level=config.observability.log_level.lower(),
    )
    _state.server = uvicorn.Server(uvicorn_config)

    # Register signal handlers before blocking on serve
    # Ref: DAEMON-ENTRYPOINT-LLD §3 step 15
    register_signal_handlers()

    logger.info(
        "daemon_starting",
        host=config.api.host,
        port=config.api.port,
    )

    # Run server (blocks until should_exit is set)
    server = _state.server
    assert server is not None
    await server.serve()

    # After server stops, close store asynchronously
    # Ref: DAEMON-ENTRYPOINT-LLD §3 step 4
    await _close_store()
