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


class ScriptedReader:
    """A reader returning one scripted chunk per ``read()`` call.

    ``asyncio.StreamReader`` coalesces everything fed before the first
    ``read()`` into one chunk, so it cannot pin a byte boundary at a
    specific offset. This can.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, n: int) -> bytes:
        del n
        if self._chunks:
            return self._chunks.pop(0)
        return b""
