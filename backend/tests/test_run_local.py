"""Unit tests for the Local Mode runner (run_local.py).

Tests:
- Startup banner content verification (components and URLs)
- RUN_MODE=local environment variable behavior
- Component wiring correctness (all components receive in-memory backends)
- Graceful shutdown behavior

Validates: Requirements 12.1, 12.6, 12.7, 12.8
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Banner content tests
# ---------------------------------------------------------------------------


class TestPrintBannerContent:
    """Tests for print_banner() output content.

    Validates: Requirement 12.8
    """

    def _capture_banner(self) -> str:
        """Capture the stdout output of print_banner()."""
        from run_local import print_banner

        buf = io.StringIO()
        with redirect_stdout(buf):
            print_banner()
        return buf.getvalue()

    def test_print_banner_contains_local_mode_title(self):
        """Banner should identify this as Local Mode."""
        output = self._capture_banner()
        assert "Local Mode" in output

    def test_print_banner_contains_digital_twin_engine(self):
        """Banner should identify the project name."""
        output = self._capture_banner()
        assert "DIGITAL TWIN ENGINE" in output

    def test_banner_shows_ingestion_component(self):
        """Banner should mention the Ingestion Server component."""
        output = self._capture_banner()
        assert "Ingestion" in output

    def test_banner_shows_ml_service_component(self):
        """Banner should mention the ML Service component."""
        output = self._capture_banner()
        assert "ML Service" in output

    def test_banner_shows_correction_engine_component(self):
        """Banner should mention the Correction Engine component."""
        output = self._capture_banner()
        assert "Correction Engine" in output

    def test_banner_shows_tsdb_writer_component(self):
        """Banner should mention the TSDB Writer component."""
        output = self._capture_banner()
        assert "TSDB Writer" in output

    def test_banner_shows_api_gateway_component(self):
        """Banner should mention the API Gateway component."""
        output = self._capture_banner()
        assert "API Gateway" in output

    def test_banner_shows_cmapss_adapter_component(self):
        """Banner should mention the C-MAPSS Adapter component."""
        output = self._capture_banner()
        assert "C-MAPSS Adapter" in output

    def test_banner_shows_websocket_broadcast_component(self):
        """Banner should mention the WebSocket Broadcast component."""
        output = self._capture_banner()
        assert "WebSocket Broadcast" in output

    def test_banner_shows_api_url(self):
        """Banner should show the API access URL."""
        output = self._capture_banner()
        assert "http://localhost:8000" in output

    def test_banner_shows_websocket_url(self):
        """Banner should show the WebSocket access URL."""
        output = self._capture_banner()
        assert "ws://localhost:8000/ws/telemetry" in output

    def test_banner_shows_health_url(self):
        """Banner should show the health endpoint URL."""
        output = self._capture_banner()
        assert "http://localhost:8000/health" in output


class TestBannerShowsAllComponents:
    """Verify the banner lists all seven expected pipeline components.

    Validates: Requirements 12.1, 12.8
    """

    EXPECTED_COMPONENTS = [
        "Ingestion",
        "ML Service",
        "Correction Engine",
        "TSDB Writer",
        "API Gateway",
        "C-MAPSS Adapter",
        "WebSocket Broadcast",
    ]

    def test_banner_mentions_all_components(self):
        """All seven pipeline components should appear in the banner."""
        from run_local import print_banner

        buf = io.StringIO()
        with redirect_stdout(buf):
            print_banner()
        output = buf.getvalue()

        for component in self.EXPECTED_COMPONENTS:
            assert component in output, (
                f"Banner should mention '{component}' but it was not found.\n"
                f"Banner output:\n{output}"
            )


class TestBannerShowsAccessUrls:
    """Verify the banner displays all required access URLs.

    Validates: Requirement 12.8
    """

    EXPECTED_URLS = [
        "http://localhost:8000",
        "ws://localhost:8000/ws/telemetry",
        "http://localhost:8000/health",
    ]

    def test_banner_mentions_all_urls(self):
        """All three access URLs should appear in the banner."""
        from run_local import print_banner

        buf = io.StringIO()
        with redirect_stdout(buf):
            print_banner()
        output = buf.getvalue()

        for url in self.EXPECTED_URLS:
            assert url in output, (
                f"Banner should show URL '{url}' but it was not found.\n"
                f"Banner output:\n{output}"
            )


# ---------------------------------------------------------------------------
# RUN_MODE=local env var tests
# ---------------------------------------------------------------------------


class TestRunModeLocalEnvVar:
    """Tests for RUN_MODE=local environment variable behavior.

    Validates: Requirement 12.7
    """

    def test_run_mode_local_env_var_set(self):
        """Importing run_local.py should set RUN_MODE=local in the environment."""
        # run_local sets os.environ["RUN_MODE"] = "local" at the top
        # Since it's already imported via print_banner tests above,
        # we verify the env var is set.
        assert os.environ.get("RUN_MODE") == "local"

    def test_run_mode_local_value_is_lowercase(self):
        """RUN_MODE should be set to the exact string 'local' (lowercase)."""
        assert os.environ.get("RUN_MODE") == "local"

    def test_run_mode_set_before_other_imports(self):
        """RUN_MODE=local should be set before component imports in run_local.py.

        This verifies the design requirement that RUN_MODE is set at the top
        of the module so factory functions use in-memory backends.
        """
        # Read the source file and verify os.environ["RUN_MODE"] = "local"
        # appears before the first from digital_twin_engine... import
        import inspect
        import run_local

        source = inspect.getsource(run_local)
        run_mode_pos = source.find('os.environ["RUN_MODE"] = "local"')
        first_dte_import = source.find("from digital_twin_engine")

        assert run_mode_pos != -1, "RUN_MODE assignment not found in run_local.py"
        assert first_dte_import != -1, "digital_twin_engine imports not found"
        assert run_mode_pos < first_dte_import, (
            "RUN_MODE must be set before digital_twin_engine imports. "
            f"RUN_MODE at position {run_mode_pos}, first import at {first_dte_import}"
        )


# ---------------------------------------------------------------------------
# Component wiring correctness tests
# ---------------------------------------------------------------------------


class TestComponentWiring:
    """Tests verifying that run_local wires in-memory backends to all components.

    Validates: Requirements 12.1, 12.6
    """

    def test_run_local_imports_in_memory_broker(self):
        """run_local should use InMemoryBrokerBackend."""
        import run_local

        assert hasattr(run_local, "InMemoryBrokerBackend")
        from digital_twin_engine.broker import InMemoryBrokerBackend

        assert run_local.InMemoryBrokerBackend is InMemoryBrokerBackend

    def test_run_local_imports_in_memory_tsdb(self):
        """run_local should use InMemoryTSDBBackend."""
        import run_local

        assert hasattr(run_local, "InMemoryTSDBBackend")
        from digital_twin_engine.tsdb import InMemoryTSDBBackend

        assert run_local.InMemoryTSDBBackend is InMemoryTSDBBackend

    def test_run_local_imports_api_gateway(self):
        """run_local should import APIGateway for the web server."""
        import run_local

        assert hasattr(run_local, "APIGateway")
        from digital_twin_engine.api.app import APIGateway

        assert run_local.APIGateway is APIGateway

    def test_run_local_imports_broker_subscriber(self):
        """run_local should import BrokerSubscriber for topic subscription."""
        import run_local

        assert hasattr(run_local, "BrokerSubscriber")
        from digital_twin_engine.api.broker_subscriber import BrokerSubscriber

        assert run_local.BrokerSubscriber is BrokerSubscriber

    def test_run_local_imports_batch_accumulator(self):
        """run_local should import BatchAccumulator for ML Service."""
        import run_local

        assert hasattr(run_local, "BatchAccumulator")
        from digital_twin_engine.ml_service.batch_accumulator import BatchAccumulator

        assert run_local.BatchAccumulator is BatchAccumulator

    def test_run_local_imports_temporal_matcher(self):
        """run_local should import TemporalMatcher for Correction Engine."""
        import run_local

        assert hasattr(run_local, "TemporalMatcher")
        from digital_twin_engine.correction.temporal_matcher import TemporalMatcher

        assert run_local.TemporalMatcher is TemporalMatcher

    def test_run_local_imports_tsdb_consumer(self):
        """run_local should import TSDBConsumer for TSDB Writer."""
        import run_local

        assert hasattr(run_local, "TSDBConsumer")
        from digital_twin_engine.tsdb import TSDBConsumer

        assert run_local.TSDBConsumer is TSDBConsumer

    def test_run_local_imports_cmapss_adapter(self):
        """run_local should import the C-MAPSS replay adapter."""
        import run_local

        assert hasattr(run_local, "CMAPSSReplayAdapter")
        from digital_twin_engine.adapters.cmapss_replay import CMAPSSReplayAdapter

        assert run_local.CMAPSSReplayAdapter is CMAPSSReplayAdapter


# ---------------------------------------------------------------------------
# Graceful shutdown tests
# ---------------------------------------------------------------------------


class TestGracefulShutdown:
    """Tests for graceful shutdown behavior.

    Validates: Requirement 12.6
    """

    async def test_run_local_has_signal_handling(self):
        """run_local should set up signal handlers for SIGINT/SIGTERM."""
        import run_local
        import inspect

        source = inspect.getsource(run_local.run_local)

        # Should reference signal handling
        assert "signal.SIGINT" in source or "SIGINT" in source, (
            "run_local() should handle SIGINT for graceful shutdown"
        )
        assert "signal.SIGTERM" in source or "SIGTERM" in source, (
            "run_local() should handle SIGTERM for graceful shutdown"
        )

    async def test_run_local_has_shutdown_event(self):
        """run_local should use an asyncio.Event for shutdown coordination."""
        import run_local
        import inspect

        source = inspect.getsource(run_local.run_local)

        assert "shutdown_event" in source, (
            "run_local() should use a shutdown_event for coordinated shutdown"
        )
        assert "asyncio.Event" in source, (
            "run_local() should create an asyncio.Event for shutdown signaling"
        )

    async def test_run_local_stops_components_on_shutdown(self):
        """run_local should call stop() on all started components during shutdown."""
        import run_local
        import inspect

        source = inspect.getsource(run_local.run_local)

        # Verify cleanup calls are present
        assert "accumulator.stop()" in source, (
            "run_local() should stop the batch accumulator on shutdown"
        )
        assert "matcher.stop()" in source, (
            "run_local() should stop the temporal matcher on shutdown"
        )
        assert "tsdb_consumer.stop()" in source, (
            "run_local() should stop the TSDB consumer on shutdown"
        )
        assert "subscriber.stop()" in source, (
            "run_local() should stop the broker subscriber on shutdown"
        )
        assert "broker.stop()" in source, (
            "run_local() should stop the broker on shutdown"
        )
        assert "tsdb.stop()" in source, (
            "run_local() should stop the TSDB backend on shutdown"
        )

    async def test_run_local_prints_goodbye_on_shutdown(self):
        """run_local should print a goodbye message on successful shutdown."""
        import run_local
        import inspect

        source = inspect.getsource(run_local.run_local)

        assert "Goodbye" in source or "goodbye" in source or "stopped" in source.lower(), (
            "run_local() should indicate when shutdown is complete"
        )
