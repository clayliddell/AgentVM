"""Tests for daemon graceful shutdown.

Ref: DAEMON-ENTRYPOINT-LLD §5.2
"""

from __future__ import annotations

import signal
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentvm.daemon import (
    DRAIN_TIMEOUT_SECONDS,
    _DaemonState,
    _async_graceful_shutdown,
    _signal_handler,
    register_signal_handlers,
)


@pytest.fixture()
def mock_state() -> _DaemonState:
    """Create a _DaemonState with mocked components."""
    state = _DaemonState(
        server=MagicMock(),
        session_manager=MagicMock(),
        metrics=MagicMock(),
        store=MagicMock(),
        shutting_down=threading.Event(),
    )
    return state


class TestAsyncGracefulShutdown:
    """Tests for async graceful shutdown.

    Ref: DAEMON-ENTRYPOINT-LLD §5.2
    """

    @pytest.mark.asyncio()
    async def test_async_graceful_shutdown_sets_server_should_exit(
        self, mock_state: _DaemonState
    ) -> None:
        """Shutdown sets server.should_exit = True to stop API."""
        mock_state.store.close = AsyncMock()
        with patch("agentvm.daemon._state", mock_state):
            await _async_graceful_shutdown()

        assert mock_state.server.should_exit is True

    @pytest.mark.asyncio()
    async def test_async_graceful_shutdown_drains_sessions(
        self, mock_state: _DaemonState
    ) -> None:
        """Shutdown calls drain_all_sessions with configured timeout."""
        mock_state.store.close = AsyncMock()
        with patch("agentvm.daemon._state", mock_state):
            await _async_graceful_shutdown()

        mock_state.session_manager.drain_all_sessions.assert_called_once_with(
            timeout=DRAIN_TIMEOUT_SECONDS
        )

    @pytest.mark.asyncio()
    async def test_async_graceful_shutdown_stops_metrics_exporter(
        self, mock_state: _DaemonState
    ) -> None:
        """Shutdown stops the Prometheus metrics exporter."""
        mock_state.store.close = AsyncMock()
        with patch("agentvm.daemon._state", mock_state):
            await _async_graceful_shutdown()

        mock_state.metrics.stop_exporter.assert_called_once()

    @pytest.mark.asyncio()
    async def test_async_graceful_shutdown_closes_store(
        self, mock_state: _DaemonState
    ) -> None:
        """Shutdown closes the metadata store."""
        mock_state.store.close = AsyncMock()
        with patch("agentvm.daemon._state", mock_state):
            await _async_graceful_shutdown()

        mock_state.store.close.assert_called_once()

    @pytest.mark.asyncio()
    async def test_async_graceful_shutdown_sets_event(
        self, mock_state: _DaemonState
    ) -> None:
        """Shutdown sets the shutting_down event to prevent double shutdown."""
        mock_state.store.close = AsyncMock()
        with patch("agentvm.daemon._state", mock_state):
            await _async_graceful_shutdown()

        assert mock_state.shutting_down.is_set() is True

    @pytest.mark.asyncio()
    async def test_async_graceful_shutdown_ignores_duplicate_signal(
        self, mock_state: _DaemonState
    ) -> None:
        """Second signal is ignored when shutting_down event is set."""
        mock_state.shutting_down.set()
        with patch("agentvm.daemon._state", mock_state):
            await _async_graceful_shutdown()

        mock_state.session_manager.drain_all_sessions.assert_not_called()

    @pytest.mark.asyncio()
    async def test_async_graceful_shutdown_handles_none_components(
        self, mock_state: _DaemonState
    ) -> None:
        """Shutdown works when components are not yet initialized."""
        state = _DaemonState(
            server=None,
            session_manager=None,
            metrics=None,
            store=None,
            shutting_down=threading.Event(),
        )
        with patch("agentvm.daemon._state", state):
            await _async_graceful_shutdown()

        assert state.shutting_down.is_set() is True

    @pytest.mark.asyncio()
    async def test_async_graceful_shutdown_order(
        self, mock_state: _DaemonState
    ) -> None:
        """Drain happens before metrics stop before store close."""
        call_order: list[str] = []
        mock_state.session_manager.drain_all_sessions.side_effect = lambda **kw: (
            call_order.append("drain")
        )
        mock_state.metrics.stop_exporter.side_effect = lambda: call_order.append(
            "metrics_stop"
        )
        mock_state.store.close = AsyncMock(
            side_effect=lambda: call_order.append("store_close")
        )

        with patch("agentvm.daemon._state", mock_state):
            await _async_graceful_shutdown()

        assert call_order == ["drain", "metrics_stop", "store_close"]


class TestSignalHandler:
    """Tests for signal handler that delegates to async shutdown."""

    def test_signal_handler_schedules_async_shutdown(self) -> None:
        """Signal handler schedules async shutdown via call_soon."""
        mock_loop = MagicMock()
        mock_loop.call_soon = MagicMock()

        with patch("agentvm.daemon.asyncio.get_running_loop", return_value=mock_loop):
            _signal_handler(signal.SIGTERM, None)

        mock_loop.call_soon.assert_called_once()

    def test_signal_handler_handles_no_running_loop(self) -> None:
        """Signal handler handles RuntimeError when no event loop."""
        with patch(
            "agentvm.daemon.asyncio.get_running_loop",
            side_effect=RuntimeError(),
        ):
            _signal_handler(signal.SIGTERM, None)


class TestRegisterSignalHandlers:
    """Tests for signal handler registration."""

    def test_register_signal_handlers_registers_sigterm(self) -> None:
        """register_signal_handlers installs handler for SIGTERM."""
        register_signal_handlers()
        assert signal.getsignal(signal.SIGTERM) is _signal_handler
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    def test_register_signal_handlers_registers_sigint(self) -> None:
        """register_signal_handlers installs handler for SIGINT."""
        register_signal_handlers()
        assert signal.getsignal(signal.SIGINT) is _signal_handler
        signal.signal(signal.SIGINT, signal.SIG_DFL)
