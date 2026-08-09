"""Property-based tests for backend factory correctness.

Uses the Hypothesis library to verify that:
- The create_broker factory returns the correct backend class for valid broker
  type strings, and raises ValueError for any invalid type string (Property 8).
- The create_tsdb factory returns the correct backend class for valid TSDB type
  strings, and raises ValueError for any invalid type string (Property 9).

Validates: Requirements 13.3, 13.4
"""

# Feature: backend-infrastructure, Property 8: Broker Factory Correctness
# Feature: backend-infrastructure, Property 9: TSDB Factory Correctness

from __future__ import annotations

import os
from unittest.mock import patch

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from digital_twin_engine.backends import (
    create_broker,
    create_tsdb,
    VALID_BROKER_TYPES,
    VALID_TSDB_TYPES,
)
from digital_twin_engine.broker import (
    InMemoryBrokerBackend,
    KafkaBrokerBackend,
    RedisBrokerBackend,
)
from digital_twin_engine.tsdb import InMemoryTSDBBackend


# ---------------------------------------------------------------------------
# Mapping from valid type strings to expected backend classes
# ---------------------------------------------------------------------------

BROKER_TYPE_TO_CLASS = {
    "memory": InMemoryBrokerBackend,
    "kafka": KafkaBrokerBackend,
    "redis": RedisBrokerBackend,
}

# For TSDB we use class names because influxdb_client and asyncpg may not be
# installed in all test environments (they are lazy-imported by the factory).
TSDB_TYPE_TO_CLASS_NAME = {
    "memory": "InMemoryTSDBBackend",
    "influxdb": "InfluxDBBackend",
    "timescaledb": "TimescaleDBBackend",
}


# ---------------------------------------------------------------------------
# Custom Hypothesis Strategies
# ---------------------------------------------------------------------------

# Strategy for valid broker types with case/whitespace variations.
# Produces tuples of (canonical_type, variant_string) so we can verify the
# correct class is returned regardless of casing/whitespace.
valid_broker_type_variants = st.sampled_from(list(VALID_BROKER_TYPES)).flatmap(
    lambda base: st.tuples(
        st.just(base),
        st.sampled_from([
            base,
            base.upper(),
            base.capitalize(),
            f"  {base}  ",
            f" {base.upper()} ",
            f"\t{base}\t",
        ]),
    )
)

# Strategy for invalid broker types: random strings that do NOT normalize to
# a valid broker type via lower().strip(). Excludes null characters which
# cannot be set as environment variable values.
invalid_broker_types = st.text(
    alphabet=st.characters(
        categories=("L", "N", "P"),
        exclude_characters="\x00",
    ),
    min_size=0,
    max_size=50,
).filter(lambda s: s.lower().strip() not in VALID_BROKER_TYPES)

# Strategy for valid TSDB type strings with case/whitespace variations.
valid_tsdb_type_variants = st.sampled_from(list(VALID_TSDB_TYPES)).flatmap(
    lambda base: st.tuples(
        st.just(base),
        st.sampled_from([
            base,
            base.upper(),
            base.capitalize(),
            f"  {base}  ",
            f" {base.upper()} ",
            f"\t{base}\t",
        ]),
    )
)

# Strategy for invalid TSDB type strings — excludes null characters.
invalid_tsdb_types = st.text(
    alphabet=st.characters(
        categories=("L", "N", "P"),
        exclude_characters="\x00",
    ),
    min_size=0,
    max_size=50,
).filter(lambda s: s.lower().strip() not in VALID_TSDB_TYPES)



# ---------------------------------------------------------------------------
# Property 8: Broker Factory Correctness
# ---------------------------------------------------------------------------


class TestProperty8BrokerFactoryCorrectness:
    """Property 8: Broker Factory Correctness.

    For any valid BROKER_TYPE value in {memory, kafka, redis}, the create_broker
    factory function SHALL return an instance of the corresponding backend class
    (InMemoryBrokerBackend, KafkaBrokerBackend, RedisBrokerBackend respectively),
    and for any string not in that set, the factory SHALL raise a ValueError.

    **Validates: Requirements 13.3**
    """

    @given(data=valid_broker_type_variants)
    @settings(max_examples=100, deadline=None)
    def test_valid_broker_types_return_correct_class(
        self, data: tuple[str, str]
    ):
        """For any valid broker type (with case/whitespace variants), the factory
        returns an instance of the correct backend class."""
        base_type, variant = data

        # Ensure RUN_MODE is not set so it doesn't override the factory logic
        env = {k: v for k, v in os.environ.items() if k != "RUN_MODE"}
        with patch.dict(os.environ, env, clear=True):
            result = create_broker(variant)

        expected_class = BROKER_TYPE_TO_CLASS[base_type]
        assert isinstance(result, expected_class), (
            f"create_broker('{variant}') returned {type(result).__name__}, "
            f"expected {expected_class.__name__}"
        )

    @given(invalid_type=invalid_broker_types)
    @settings(max_examples=100, deadline=None)
    def test_invalid_broker_types_raise_value_error(self, invalid_type: str):
        """For any string that is not a valid broker type (after normalization),
        the factory raises ValueError with a helpful message."""
        # Ensure RUN_MODE is not set so it doesn't override the factory logic
        env = {k: v for k, v in os.environ.items() if k != "RUN_MODE"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError) as exc_info:
                create_broker(invalid_type)

        error_message = str(exc_info.value)

        # The error message should mention valid options
        for valid_type in VALID_BROKER_TYPES:
            assert valid_type in error_message, (
                f"ValueError message should list valid option '{valid_type}', "
                f"but got: {error_message}"
            )



# ---------------------------------------------------------------------------
# Property 9: TSDB Factory Correctness
# ---------------------------------------------------------------------------


class TestProperty9TSDBFactoryCorrectness:
    """Property 9: TSDB Factory Correctness.

    For any valid TSDB_TYPE value in {memory, influxdb, timescaledb}, the
    create_tsdb factory function SHALL return an instance of the corresponding
    backend class (InMemoryTSDBBackend, InfluxDBBackend, TimescaleDBBackend
    respectively), and for any string not in that set, the factory SHALL raise
    a ValueError.

    **Validates: Requirements 13.4**
    """

    @given(data=valid_tsdb_type_variants)
    @settings(max_examples=100, deadline=None)
    def test_valid_tsdb_type_returns_correct_backend_class(
        self, data: tuple[str, str]
    ):
        """For valid TSDB type strings, the factory returns the correct class."""
        base_type, variant = data

        # Clear RUN_MODE to avoid the local override
        env = {k: v for k, v in os.environ.items() if k != "RUN_MODE"}
        with patch.dict(os.environ, env, clear=True):
            backend = create_tsdb(variant)
            expected_class_name = TSDB_TYPE_TO_CLASS_NAME[base_type]
            actual_class_name = type(backend).__name__
            assert actual_class_name == expected_class_name, (
                f"create_tsdb('{variant}') returned {actual_class_name}, "
                f"expected {expected_class_name}"
            )

    @given(invalid_type=invalid_tsdb_types)
    @settings(max_examples=100, deadline=None)
    def test_invalid_tsdb_type_raises_value_error(self, invalid_type: str):
        """For invalid TSDB type strings, the factory raises ValueError."""
        # Clear RUN_MODE to avoid the local override
        env = {k: v for k, v in os.environ.items() if k != "RUN_MODE"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError) as exc_info:
                create_tsdb(invalid_type)
            # Verify the error message is helpful (lists valid options)
            error_msg = str(exc_info.value)
            for valid_type in VALID_TSDB_TYPES:
                assert valid_type in error_msg, (
                    f"ValueError message should list valid option '{valid_type}' "
                    f"but got: {error_msg}"
                )


# ---------------------------------------------------------------------------
# Property 10: RUN_MODE=local Overrides Backend Selection
# ---------------------------------------------------------------------------

from contextlib import contextmanager


@contextmanager
def _env_vars(**kwargs):
    """Temporarily set environment variables, restoring originals on exit."""
    old_values = {}
    for key, value in kwargs.items():
        old_values[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        yield
    finally:
        for key, old_value in old_values.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


# Strategy for environment-safe random strings (no null bytes)
_env_safe_text = st.text(
    alphabet=st.characters(blacklist_characters="\x00"),
    min_size=0,
    max_size=30,
)

# Strategy for BROKER_TYPE values: includes valid Docker Mode types and random strings
_broker_type_values = st.one_of(
    st.sampled_from(["kafka", "redis", "memory", "KAFKA", "Redis", "MEMORY"]),
    _env_safe_text,
)

# Strategy for TSDB_TYPE values: includes valid Docker Mode types and random strings
_tsdb_type_values = st.one_of(
    st.sampled_from(["influxdb", "timescaledb", "memory", "INFLUXDB", "TimescaleDB", "MEMORY"]),
    _env_safe_text,
)

# Strategy for RUN_MODE=local variations (case-insensitive check)
_run_mode_local_values = st.sampled_from(["local", "LOCAL", "Local", "lOcAl"])


class TestProperty10RunModeLocalOverride:
    """Property 10: RUN_MODE=local Overrides Backend Selection.

    When RUN_MODE=local is set, the factories SHALL always return in-memory
    backends regardless of any BROKER_TYPE or TSDB_TYPE value (including valid
    Docker Mode values like 'kafka', 'redis', 'influxdb', 'timescaledb').

    **Validates: Requirements 12.2, 12.3, 12.7, 13.3, 13.4**
    """

    @given(
        broker_type=_broker_type_values,
        run_mode=_run_mode_local_values,
    )
    @settings(max_examples=100)
    def test_create_broker_returns_in_memory_when_run_mode_local(
        self, broker_type: str, run_mode: str
    ):
        """create_broker() always returns InMemoryBrokerBackend when RUN_MODE=local."""
        with _env_vars(RUN_MODE=run_mode, BROKER_TYPE=broker_type):
            result = create_broker()

        assert isinstance(result, InMemoryBrokerBackend), (
            f"Expected InMemoryBrokerBackend when RUN_MODE={run_mode!r} and "
            f"BROKER_TYPE={broker_type!r}, got {type(result).__name__}"
        )

    @given(
        tsdb_type=_tsdb_type_values,
        run_mode=_run_mode_local_values,
    )
    @settings(max_examples=100)
    def test_create_tsdb_returns_in_memory_when_run_mode_local(
        self, tsdb_type: str, run_mode: str
    ):
        """create_tsdb() always returns InMemoryTSDBBackend when RUN_MODE=local."""
        with _env_vars(RUN_MODE=run_mode, TSDB_TYPE=tsdb_type):
            result = create_tsdb()

        assert isinstance(result, InMemoryTSDBBackend), (
            f"Expected InMemoryTSDBBackend when RUN_MODE={run_mode!r} and "
            f"TSDB_TYPE={tsdb_type!r}, got {type(result).__name__}"
        )

    @given(
        broker_type=_broker_type_values,
        tsdb_type=_tsdb_type_values,
        run_mode=_run_mode_local_values,
    )
    @settings(max_examples=100)
    def test_both_factories_return_in_memory_simultaneously(
        self, broker_type: str, tsdb_type: str, run_mode: str
    ):
        """Both factories return in-memory backends simultaneously when RUN_MODE=local."""
        with _env_vars(RUN_MODE=run_mode, BROKER_TYPE=broker_type, TSDB_TYPE=tsdb_type):
            broker = create_broker()
            tsdb = create_tsdb()

        assert isinstance(broker, InMemoryBrokerBackend), (
            f"Expected InMemoryBrokerBackend, got {type(broker).__name__} "
            f"with RUN_MODE={run_mode!r}, BROKER_TYPE={broker_type!r}"
        )
        assert isinstance(tsdb, InMemoryTSDBBackend), (
            f"Expected InMemoryTSDBBackend, got {type(tsdb).__name__} "
            f"with RUN_MODE={run_mode!r}, TSDB_TYPE={tsdb_type!r}"
        )

    @given(
        broker_type=st.sampled_from(["kafka", "redis"]),
        run_mode=_run_mode_local_values,
    )
    @settings(max_examples=100)
    def test_run_mode_local_overrides_valid_docker_broker_types(
        self, broker_type: str, run_mode: str
    ):
        """RUN_MODE=local overrides even valid Docker Mode broker types (kafka, redis)."""
        with _env_vars(RUN_MODE=run_mode, BROKER_TYPE=broker_type):
            result = create_broker()

        assert isinstance(result, InMemoryBrokerBackend), (
            f"RUN_MODE=local should override BROKER_TYPE={broker_type!r}, "
            f"but got {type(result).__name__}"
        )

    @given(
        tsdb_type=st.sampled_from(["influxdb", "timescaledb"]),
        run_mode=_run_mode_local_values,
    )
    @settings(max_examples=100)
    def test_run_mode_local_overrides_valid_docker_tsdb_types(
        self, tsdb_type: str, run_mode: str
    ):
        """RUN_MODE=local overrides even valid Docker Mode TSDB types (influxdb, timescaledb)."""
        with _env_vars(RUN_MODE=run_mode, TSDB_TYPE=tsdb_type):
            result = create_tsdb()

        assert isinstance(result, InMemoryTSDBBackend), (
            f"RUN_MODE=local should override TSDB_TYPE={tsdb_type!r}, "
            f"but got {type(result).__name__}"
        )
