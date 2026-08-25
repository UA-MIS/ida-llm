"""Shared fixtures for ida-core tests."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from ida_core.contracts import (
    ModelEntry,
    Quantization,
    SamplingParams,
    ServingConfig,
    ServingStack,
)
from ida_core.db import create_all, make_engine, make_session_factory


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """A fresh in-memory SQLite database with the full schema."""
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


@pytest.fixture
def serving_config() -> ServingConfig:
    return ServingConfig(
        model_id="mock-echo-1",
        registry_key="mock",
        serving_stack=ServingStack.MOCK,
        serving_version="ida-mock-model 0.1.0",
        quantization=Quantization.NONE,
        context_window=8192,
        sampling=SamplingParams(temperature=0.0, max_tokens=256, seed=1),
    )


@pytest.fixture
def model_entry(serving_config: ServingConfig) -> ModelEntry:
    return ModelEntry(
        key="mock",
        display_name="Mock model",
        base_url="http://mock-model:8000/v1",
        api_key_env=None,
        serving=serving_config,
    )
