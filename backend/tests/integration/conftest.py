"""Conftest for integration tests — auto-skips if Docker is unavailable."""

import shutil
import subprocess

import pytest


def _docker_available() -> bool:
    """Check if Docker CLI is available and the daemon is reachable."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _docker_compose_available() -> bool:
    """Check if Docker Compose V2 is available."""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def pytest_collection_modifyitems(config, items):
    """Auto-skip integration tests when Docker is not available.

    Tests marked with @pytest.mark.no_docker are excluded from
    the Docker availability check (they only need in-memory backends).
    """
    if not _docker_available():
        skip_marker = pytest.mark.skip(reason="Docker is not available")
        for item in items:
            if "integration" in item.keywords and "no_docker" not in item.keywords:
                item.add_marker(skip_marker)
    elif not _docker_compose_available():
        skip_marker = pytest.mark.skip(reason="Docker Compose V2 is not available")
        for item in items:
            if "integration" in item.keywords and "no_docker" not in item.keywords:
                item.add_marker(skip_marker)
