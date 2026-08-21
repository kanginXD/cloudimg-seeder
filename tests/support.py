"""Shared test doubles, not collected as a test module."""

from __future__ import annotations

import sys
from io import StringIO

if sys.version_info >= (3, 12):
    from typing import override
else:  # requires-python floor is 3.11; typing.override is 3.12+

    def override(func):  # type: ignore[no-redef]
        return func


class FakeTty(StringIO):
    """An in-memory stream that reports itself as a terminal."""

    @override
    def isatty(self) -> bool:
        return True
