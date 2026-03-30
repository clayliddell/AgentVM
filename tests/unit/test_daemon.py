"""Tests for daemon graceful shutdown.

Ref: DAEMON-ENTRYPOINT-LLD §5.2
"""

from __future__ import annotations

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentvm.daemon import (
    DRAIN_TIMEOUT_SECONDS,
    _async_graceful_shutdown,
    _DaemonState,
    _signal_handler,
    register_signal_handlers,
)
from agentvm.session.manager import DrainResult


@pytest.fixture()
def mock_state() -> _DaemonState:
    """Create a _DaemonState with mocked components."""
    state = _DaemonState(
        server=MagicMock(),
        session_manager=MagicMock(),
        metrics=MagicMock(),
        store=MagicMock(),
        shutting_down=asyncio.Event(),
    )
    state.store.close = AsyncMock()
    state.session_manager.drain_all_sessions = AsyncMock(return_value=DrainResult())
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
        with patch("agentvm.daemon._state", mock_state):
            await _async_graceful_shutdown()

        assert mock_state.server.should_exit is True

    @pytest.mark.asyncio()
    async def test_async_graceful_shutdown_drains_sessions(
        self, mock_state: _DaemonState
    ) -> None:
        """Shutdown calls drain_all_sessions with configured timeout."""
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
        with patch("agentvm.daemon._state", mock_state):
            await _async_graceful_shutdown()

        mock_state.metrics.stop_exporter.assert_called_once()

    @pytest.mark.asyncio()
    async def test_async_graceful_shutdown_closes_store(
        self, mock_state: _DaemonState
    ) -> None:
        """Shutdown closes the metadata store."""
        with patch("agentvm.daemon._state", mock_state):
            await _async_graceful_shutdown()

        mock_state.store.close.assert_called_once()

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
            shutting_down=asyncio.Event(),
        )
        with patch("agentvm.daemon._state", state):
            await _async_graceful_shutdown()

    @pytest.mark.asyncio()
    async def test_async_graceful_shutdown_order(
        self, mock_state: _DaemonState
    ) -> None:
        """Drain happens before metrics stop before store close."""
        call_order: list[str] = []

        async def track_drain(**kwargs: object) -> DrainResult:
            call_order.append("drain")
            return DrainResult()

        mock_state.session_manager.drain_all_sessions = AsyncMock(
            side_effect=track_drain
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

    @pytest.mark.asyncio()
    async def test_async_graceful_shutdown_warns_on_drain_timeout(
        self, mock_state: _DaemonState
    ) -> None:
        """Shutdown logs warning when drain times out with sessions remaining."""
        mock_state.session_manager.drain_all_sessions = AsyncMock(
            return_value=DrainResult(incomplete=True, remaining=3)
        )

        with (
            patch("agentvm.daemon._state", mock_state),
            patch("agentvm.daemon.logger") as mock_logger,
        ):
            await _async_graceful_shutdown()

        mock_logger.warning.assert_any_call(
            "drain_timeout",
            remaining=3,
        )


class TestSignalHandler:
    """Tests for signal handler that delegates to async shutdown."""

    def test_signal_handler_schedules_async_shutdown(self) -> None:
        """Signal handler schedules async shutdown via call_soon."""
        mock_loop = MagicMock()
        mock_loop.call_soon = MagicMock()

        state = _DaemonState(
            server=MagicMock(),
            shutting_down=asyncio.Event(),
        )
        with (
            patch("agentvm.daemon._state", state),
            patch("agentvm.daemon.asyncio.get_running_loop", return_value=mock_loop),
        ):
            _signal_handler(signal.SIGTERM, None)

        mock_loop.call_soon.assert_called_once()

    def test_signal_handler_sets_shutdown_flag(self) -> None:
        """Signal handler sets shutting_down flag before scheduling."""
        mock_loop = MagicMock()

        state = _DaemonState(
            server=MagicMock(),
            shutting_down=asyncio.Event(),
        )
        with (
            patch("agentvm.daemon._state", state),
            patch("agentvm.daemon.asyncio.get_running_loop", return_value=mock_loop),
        ):
            _signal_handler(signal.SIGTERM, None)

        assert state.shutting_down.is_set() is True

    def test_signal_handler_ignores_duplicate_signal(self) -> None:
        """Second signal is ignored when shutting_down flag is set."""
        mock_loop = MagicMock()
        mock_loop.call_soon = MagicMock()

        state = _DaemonState(
            server=MagicMock(),
            shutting_down=asyncio.Event(),
        )
        state.shutting_down.set()

        with (
            patch("agentvm.daemon._state", state),
            patch("agentvm.daemon.asyncio.get_running_loop", return_value=mock_loop),
        ):
            _signal_handler(signal.SIGTERM, None)
            _signal_handler(signal.SIGINT, None)

        mock_loop.call_soon.assert_not_called()

    def test_signal_handler_handles_no_running_loop(self) -> None:
        """Signal handler handles RuntimeError when no event loop."""
        state = _DaemonState(
            server=MagicMock(),
            shutting_down=asyncio.Event(),
        )
        with (
            patch("agentvm.daemon._state", state),
            patch(
                "agentvm.daemon.asyncio.get_running_loop",
                side_effect=RuntimeError(),
            ),
        ):
            _signal_handler(signal.SIGTERM, None)

        # Flag should still be set even when no event loop
        assert state.shutting_down.is_set() is True


class TestRegisterSignalHandlers:
    """Tests for signal handler registration."""

    def test_register_signal_handlers_registers_sigterm(self) -> None:
        """register_signal_handlers installs handler for SIGTERM."""
        prev_handler = signal.getsignal(signal.SIGTERM)
        try:
            register_signal_handlers()
            assert signal.getsignal(signal.SIGTERM) is _signal_handler
        finally:
            signal.signal(signal.SIGTERM, prev_handler)

    def test_register_signal_handlers_registers_sigint(self) -> None:
        """register_signal_handlers installs handler for SIGINT."""
        prev_handler = signal.getsignal(signal.SIGINT)
        try:
            register_signal_handlers()
            assert signal.getsignal(signal.SIGINT) is _signal_handler
        finally:
            signal.signal(signal.SIGINT, prev_handler)
