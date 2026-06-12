"""Hermetic test setup: MOCK_ORACLE before anything builds the singletons;
fresh mock state + cleared overrides per test."""
import os

import pytest

os.environ.setdefault("MOCK_ORACLE", "true")


@pytest.fixture(autouse=True)
def _reset_dependency_state(monkeypatch):
    """Fresh singletons (and therefore a fresh MockOracleRepository) per test."""
    monkeypatch.delenv("FLASHBACK_API_KEY", raising=False)
    from core import deps
    from main import app

    app.dependency_overrides.clear()
    deps.reset_singletons()
    yield
    app.dependency_overrides.clear()
    deps.reset_singletons()
