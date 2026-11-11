"""
Pytest session-wide hermetic database configuration.
Ensures zero test ever touches timeline_viewer.db even when invoked via bare pytest.
"""

from __future__ import annotations

from typing import Iterator

import pytest

from tests.hermetic_fixture import hermetic_db_environment


@pytest.fixture(scope="session", autouse=True)
def _activate_hermetic_db() -> Iterator[None]:
    with hermetic_db_environment():
        yield
