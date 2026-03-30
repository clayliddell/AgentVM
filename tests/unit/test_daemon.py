"""Tests for daemon graceful shutdown.

Ref: DAEMON-ENTRYPOINT-LLD §5.2
"""

from __future__ import annotations

import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentvm.daemon import (
    DRAIN_TIMEOUT_SECONDS,
    _DaemonState,
    _close_store,
    graceful_shutdown,
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
        shutting_down=False,
    )
    state.store.close = AsyncMock()
    return state


class TestGracefulShutdown:
    """Tests for graceful_shutdown signal handler.

    Ref: DAEMON-ENTRYPOINT-LLD §5.2
    """

    def test_graceful_shutdown_sets_server_should_exit(
        self, mock_state: _DaemonState
    ) -> None:
        """Signal handler sets server.should_exit = True to stop API."""
        with patch("agentvm.daemon._state", mock_state):
            graceful_shutdown(signal.SIGTERM, None)

        assert mock_state.server.should_exit is True

    def test_graceful_shutdown_drains_sessions(self, mock_state: _DaemonState) -> None:
        """Signal handler calls drain_all_sessions with configured timeout."""
        with patch("agentvm.daemon._state", mock_state):
            graceful_shutdown(signal.SIGTERM, None)

        mock_state.session_manager.drain_all_sessions.assert_called_once_with(
            timeout=DRAIN_TIMEOUT_SECONDS
        )

    def test_graceful_shutdown_stops_metrics_exporter(
        self, mock_state: _DaemonState
    ) -> None:
        """Signal handler stops the Prometheus metrics exporter."""
        with patch("agentvm.daemon._state", mock_state):
            graceful_shutdown(signal.SIGTERM, None)

        mock_state.metrics.stop_exporter.assert_called_once()

    def test_graceful_shutdown_marks_shutting_down(
        self, mock_state: _DaemonState
    ) -> None:
        """Signal handler sets shutting_down flag to prevent double shutdown."""
        with patch("agentvm.daemon._state", mock_state):
            graceful_shutdown(signal.SIGTERM, None)

        assert mock_state.shutting_down is True

    def test_graceful_shutdown_ignores_duplicate_signal(
        self, mock_state: _DaemonState
    ) -> None:
        """Second signal is ignored — drain/stop not called again."""
        mock_state.shutting_down = True
        with patch("agentvm.daemon._state", mock_state):
            graceful_shutdown(signal.SIGTERM, None)

        mock_state.session_manager.drain_all_sessions.assert_not_called()
        mock_state.metrics.stop_exporter.assert_not_called()

    def test_graceful_shutdown_handles_none_components(self) -> None:
        """Shutdown works when components are not yet initialized."""
        state = _DaemonState(
            server=None,
            session_manager=None,
            metrics=None,
            store=None,
            shutting_down=False,
        )
        with patch("agentvm.daemon._state", state):
            graceful_shutdown(signal.SIGTERM, None)

        assert state.shutting_down is True

    def test_graceful_shutdown_order_drain_before_metrics_stop(
        self, mock_state: _DaemonState
    ) -> None:
        """Drain happens before metrics stop (correct shutdown order)."""
        call_order: list[str] = []
        mock_state.session_manager.drain_all_sessions.side_effect = lambda **kw: (
            call_order.append("drain")
        )
        mock_state.metrics.stop_exporter.side_effect = lambda: call_order.append(
            "metrics_stop"
        )

        with patch("agentvm.daemon._state", mock_state):
            graceful_shutdown(signal.SIGTERM, None)

        assert call_order == ["drain", "metrics_stop"]

    @pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
    def test_graceful_shutdown_handles_both_signals(
        self, mock_state: _DaemonState, sig: int
    ) -> None:
        """Both SIGTERM and SIGINT trigger graceful shutdown."""
        with patch("agentvm.daemon._state", mock_state):
            graceful_shutdown(sig, None)

        assert mock_state.shutting_down is True
        assert mock_state.server.should_exit is True


class TestCloseStore:
    """Tests for async store close after server stops."""

    @pytest.mark.asyncio()
    async def test_close_store_calls_store_close(self) -> None:
        """_close_store calls store.close() when store is set."""
        state = _DaemonState(store=MagicMock())
        state.store.close = AsyncMock()

        with patch("agentvm.daemon._state", state):
            await _close_store()

        state.store.close.assert_called_once()

    @pytest.mark.asyncio()
    async def test_close_store_handles_none_store(self) -> None:
        """_close_store is a no-op when store is None."""
        state = _DaemonState(store=None)

        with patch("agentvm.daemon._state", state):
            await _close_store()


class TestRegisterSignalHandlers:
    """Tests for signal handler registration."""

    def test_register_signal_handlers_registers_sigterm(self) -> None:
        """register_signal_handlers installs handler for SIGTERM."""
        register_signal_handlers()
        assert signal.getsignal(signal.SIGTERM) is graceful_shutdown
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    def test_register_signal_handlers_registers_sigint(self) -> None:
        """register_signal_handlers installs handler for SIGINT."""
        register_signal_handlers()
        assert signal.getsignal(signal.SIGINT) is graceful_shutdown
        signal.signal(signal.SIGINT, signal.SIG_DFL)
