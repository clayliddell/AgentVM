"""AgentVM daemon entrypoint — initialization, signal handling, graceful shutdown.

Ref: DAEMON-ENTRYPOINT-LLD §3, §5.2
"""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field
from types import FrameType

import structlog
import uvicorn

from agentvm.api.app import create_app
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
    shutting_down: asyncio.Event = field(default_factory=asyncio.Event)


_state = _DaemonState()


async def _async_graceful_shutdown() -> None:
    """Async graceful shutdown to be called from the event loop.

    The shutting_down flag is set by the signal handler before this task
    is scheduled, so we don't re-check it here.

    Ref: DAEMON-ENTRYPOINT-LLD §3 (shutdown sequence), §5.2
    """
    logger.info("daemon_shutdown_started")

    # 1. Stop accepting new API requests
    #    Ref: DAEMON-ENTRYPOINT-LLD §3 step 1
    if _state.server is not None:
        _state.server.should_exit = True

    # 2. Drain active sessions
    #    Ref: DAEMON-ENTRYPOINT-LLD §3 step 2
    if _state.session_manager is not None:
        drain_result = await _state.session_manager.drain_all_sessions(
            timeout=DRAIN_TIMEOUT_SECONDS
        )
        if drain_result.incomplete:
            logger.warning(
                "drain_timeout",
                remaining=drain_result.remaining,
            )

    # 3. Stop metrics exporter
    #    Ref: DAEMON-ENTRYPOINT-LLD §3 step 3
    if _state.metrics is not None:
        _state.metrics.stop_exporter()

    # 4. Close metadata store
    #    Ref: DAEMON-ENTRYPOINT-LLD §3 step 4
    if _state.store is not None:
        await _state.store.close()

    logger.info("daemon_shutdown_complete")


def _signal_handler(signum: int, frame: FrameType | None) -> None:
    """Signal handler that delegates to async shutdown in event loop.

    Sets the shutdown flag immediately (before scheduling) to prevent
    duplicate shutdown tasks from rapid successive signals.
    """
    if _state.shutting_down.is_set():
        return

    # Set flag immediately to prevent re-entry from second signal before
    # the scheduled task runs.
    _state.shutting_down.set()
    logger.info("shutdown_signal_received", signal=signum)

    try:
        loop = asyncio.get_running_loop()
        loop.call_soon(lambda: asyncio.create_task(_async_graceful_shutdown()))
    except RuntimeError:
        pass


def register_signal_handlers() -> None:
    """Register SIGTERM and SIGINT handlers for graceful shutdown.

    Uses signal handlers that delegate to the event loop to avoid blocking.

    Ref: DAEMON-ENTRYPOINT-LLD §3 step 15
    """
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)


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
    await _state.server.serve()
