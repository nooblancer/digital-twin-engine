"""Integration tests for the Docker stack.

These tests require Docker and a running Docker Compose stack.
They are marked with @pytest.mark.integration and are skipped by default
during normal pytest execution. Run them explicitly with:

    pytest -m integration

Or in CI where Docker services are already running.
"""
