"""Progress reporting protocol, free of any presentation dependency."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol


class ProgressSink(Protocol):
    """Receives percent-complete updates for one long-running operation.

    Implementations render however they like; the library layer only
    reports. ``start`` and ``finish`` bracket a single operation.
    """

    def start(self, label: str) -> None: ...

    def advance(self, percent: float) -> None: ...

    def finish(self) -> None: ...


class NullProgress:
    """Discards every update. Default when no sink is supplied.

    Parameter names mirror ``ProgressSink`` so the two stay
    keyword-compatible, which is why the arguments go unused here.
    """

    def start(self, label: str) -> None:  # noqa: ARG002
        return None

    def advance(self, percent: float) -> None:  # noqa: ARG002
        return None

    def finish(self) -> None:
        return None


class progress_task:  # noqa: N801
    """Bracket one operation on ``sink``, closing it even on failure."""

    def __init__(self, sink: ProgressSink, label: str) -> None:
        self._sink = sink
        self._label = label

    def __enter__(self) -> ProgressSink:
        self._sink.start(self._label)
        return self._sink

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._sink.finish()
