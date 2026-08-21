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
    """Write guest serial to stderr and/or a plain-text log file.

    ANSI-capable stderr keeps SGR colors but drops host-querying escapes.
    Dumb / non-TTY stderr strips all escapes. ``--serial-log`` always
    receives plain text (all escapes stripped).
    """

    quiet: bool = False
    serial_log: Path | None = None
    ansi_capable: bool | None = None
    stream: TextIO = field(default_factory=lambda: sys.stderr)
    _stderr_stripper: AnsiStripper = field(init=False, repr=False)
    _log_stripper: AnsiStripper | None = field(default=None, init=False, repr=False)
    _log: TextIO | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        capable = (
            self.ansi_capable
            if self.ansi_capable is not None
            else stderr_ansi_capable(self.stream)
        )
        self.ansi_capable = capable
        self._stderr_stripper = AnsiStripper(keep_sgr=capable)
        if self.serial_log is not None:
            path = self.serial_log
            path.parent.mkdir(parents=True, exist_ok=True)
            self._log = path.open("w", encoding="utf-8", newline="")
            self._log_stripper = AnsiStripper(keep_sgr=False)

    def write(self, text: str) -> None:
        if not text:
            return
        if not self.quiet:
            shown = self._stderr_stripper.feed(text)
            if shown:
                print(shown, end="", file=self.stream, flush=True)
        if self._log is not None and self._log_stripper is not None:
            plain = self._log_stripper.feed(text)
            if plain:
                self._log.write(plain)
                self._log.flush()

    def close(self) -> None:
        if not self.quiet:
            leftover = self._stderr_stripper.flush()
            if leftover:
                print(leftover, end="", file=self.stream, flush=True)
        if self._log is not None and self._log_stripper is not None:
            leftover = self._log_stripper.flush()
            if leftover:
                self._log.write(leftover)
                self._log.flush()
            self._log.close()
            self._log = None
            self._log_stripper = None
