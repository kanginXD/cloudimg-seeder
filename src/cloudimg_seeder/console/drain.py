"""Non-blocking drain of queued TTY stdin (late DSR replies)."""

from __future__ import annotations

import os
import sys
import time
from typing import TextIO

_SETTLE_ROUNDS = 5
_SETTLE_DELAY_SEC = 0.02


def drain_stdin(stream: TextIO | None = None) -> None:
    """Discard already-queued stdin bytes when stdin is a TTY.

    Best-effort: errors are ignored. Brief settle passes catch late
    terminal replies after guest CSI was printed.
    """
    inp = stream if stream is not None else sys.stdin
    try:
        if not inp.isatty():
            return
    except OSError:
        return

    if sys.platform == "win32":
        _drain_windows()
        return
    _drain_posix(inp)


def _drain_posix(inp: TextIO) -> None:
    try:
        fd = inp.fileno()
    except (OSError, AttributeError, ValueError):
        return

    blocking: bool | None
    try:
        blocking = os.get_blocking(fd)
    except (OSError, AttributeError):
        blocking = None

    try:
        if blocking is not None:
            os.set_blocking(fd, False)
        for round_i in range(_SETTLE_ROUNDS):
            _read_available(fd)
            if round_i + 1 < _SETTLE_ROUNDS:
                time.sleep(_SETTLE_DELAY_SEC)
    finally:
        if blocking is not None:
            try:
                os.set_blocking(fd, blocking)
            except OSError:
                pass


def _read_available(fd: int) -> None:
    while True:
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            return
        except InterruptedError:
            continue
        except OSError:
            return
        if not chunk:
            return


def _drain_windows() -> None:
    try:
        import msvcrt
    except ImportError:
        return
    try:
        for round_i in range(_SETTLE_ROUNDS):
            while msvcrt.kbhit():  # type: ignore[attr-defined]
                msvcrt.getwch()  # type: ignore[attr-defined]
            if round_i + 1 < _SETTLE_ROUNDS:
                time.sleep(_SETTLE_DELAY_SEC)
    except OSError:
        return
