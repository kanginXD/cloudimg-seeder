"""Host stderr ANSI capability detection."""

from __future__ import annotations

import os
import sys
from typing import Protocol


class SupportsIsATty(Protocol):
    def isatty(self) -> bool: ...


def stderr_ansi_capable(
    stream: SupportsIsATty | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> bool:
    """Return True when guest serial may keep CSI/SGR on stderr.

    Requires a TTY stderr, TERM not ``dumb``, and NO_COLOR unset or empty.
    """
    out: SupportsIsATty = stream if stream is not None else sys.stderr
    env = environ if environ is not None else os.environ
    if not out.isatty():
        return False
    if env.get("TERM", "") == "dumb":
        return False
    return env.get("NO_COLOR", "") == ""
