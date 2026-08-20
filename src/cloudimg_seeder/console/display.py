"""Guest serial display sinks: stderr policy and optional log file."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from cloudimg_seeder.console.ansi import AnsiStripper
from cloudimg_seeder.console.capability import stderr_ansi_capable


@dataclass
class SerialOptions:
    quiet: bool = False
    serial_log: Path | None = None


@dataclass
class SerialDisplay:
    """Apply ANSI policy and write serial text to stderr and/or a log file.

    ANSI-capable stderr keeps SGR colors but drops host-querying escapes
    (for example DSR ``ESC [ 6 n``). Dumb / non-TTY stderr strips all escapes.
    """

    quiet: bool = False
    serial_log: Path | None = None
    ansi_capable: bool | None = None
    stream: TextIO = field(default_factory=lambda: sys.stderr)
    _stripper: AnsiStripper = field(init=False, repr=False)
    _log: TextIO | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        capable = (
            self.ansi_capable
            if self.ansi_capable is not None
            else stderr_ansi_capable(self.stream)
        )
        self.ansi_capable = capable
        self._stripper = AnsiStripper(keep_sgr=capable)
        if self.serial_log is not None:
            path = self.serial_log
            path.parent.mkdir(parents=True, exist_ok=True)
            self._log = path.open("w", encoding="utf-8", newline="")

    def write(self, text: str) -> None:
        if not text:
            return
        text = self._stripper.feed(text)
        if not text:
            return
        if not self.quiet:
            print(text, end="", file=self.stream, flush=True)
        if self._log is not None:
            self._log.write(text)
            self._log.flush()

    def close(self) -> None:
        leftover = self._stripper.flush()
        if leftover:
            if not self.quiet:
                print(leftover, end="", file=self.stream, flush=True)
            if self._log is not None:
                self._log.write(leftover)
                self._log.flush()
        if self._log is not None:
            self._log.close()
            self._log = None
