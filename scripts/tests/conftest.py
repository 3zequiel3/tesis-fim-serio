"""Shared pytest config for scripts/tests."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: requires Docker/real services; not part of the fast suite"
    )
