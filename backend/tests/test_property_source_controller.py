"""Property-based tests for invalid source name rejection.

Uses the Hypothesis library to verify that any string NOT in the set of
recognized source names causes POST /source to return HTTP 400 with
available sources listed in the error message.

# Feature: backend-infrastructure, Property 5: Invalid Source Name Rejection

**Validates: Requirements 5.3**
"""

from __future__ import annotations

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings
from fastapi.testclient import TestClient

from digital_twin_engine.api.app import create_app
from digital_twin_engine.api.source_controller import AVAILABLE_SOURCES


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies
# ---------------------------------------------------------------------------

# Strategy for strings that are NOT valid source names.
# We generate arbitrary text and filter out any that happen to be in
# AVAILABLE_SOURCES (currently just "cmapss_replay").
invalid_source_names = st.text(
    alphabet=st.characters(
        categories=("L", "N", "P", "S", "Z"),
        exclude_characters="\x00",
    ),
    min_size=0,
    max_size=100,
).filter(lambda s: s not in AVAILABLE_SOURCES)


# ---------------------------------------------------------------------------
# Property 5: Invalid Source Name Rejection
# ---------------------------------------------------------------------------


class TestProperty5InvalidSourceNameRejection:
    """Property 5: Invalid Source Name Rejection.

    For any string that is not in the set of recognized source names,
    a POST request to /source with that string as the source field SHALL
    return HTTP 400, and the response body SHALL indicate the available
    valid source names.

    **Validates: Requirements 5.3**
    """

    @pytest.fixture(autouse=True)
    def setup_client(self):
        """Create a fresh TestClient for each test method."""
        app = create_app()
        self.client = TestClient(app)

    @given(source_name=invalid_source_names)
    @settings(max_examples=100, deadline=None)
    def test_invalid_source_returns_400(self, source_name: str):
        """POST /source with any invalid source name SHALL return HTTP 400."""
        response = self.client.post("/source", json={"source": source_name})

        assert response.status_code == 400, (
            f"Expected HTTP 400 for source={source_name!r}, "
            f"got {response.status_code}"
        )

    @given(source_name=invalid_source_names)
    @settings(max_examples=100, deadline=None)
    def test_invalid_source_response_lists_available_sources(self, source_name: str):
        """The error response SHALL list available source names."""
        response = self.client.post("/source", json={"source": source_name})

        assert response.status_code == 400

        body = response.json()

        # Response must contain an "error" field
        assert "error" in body, (
            f"Response body missing 'error' field: {body}"
        )

        error_msg = body["error"]

        # The error message must mention each available source
        for available_source in sorted(AVAILABLE_SOURCES):
            assert available_source in error_msg, (
                f"Error message should list available source '{available_source}', "
                f"but got: {error_msg}"
            )
