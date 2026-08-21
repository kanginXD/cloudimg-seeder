"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from cloudimg_seeder import firmware


@pytest.fixture(autouse=True)
def _reset_firmware_search_cache() -> Iterator[None]:
    """Firmware directory discovery is cached per process; isolate tests."""
    firmware._firmware_search_dirs_cached.cache_clear()
    yield
    firmware._firmware_search_dirs_cached.cache_clear()
