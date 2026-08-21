"""Guest serial display sinks: stderr policy and optional log file."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import TextIO

from cloudimg_seeder.console.ansi import AnsiStripper
from cloudimg_seeder.console.capability import stderr_ansi_capable


@dataclass
class SerialOptions:
    quiet: bool = False
    serial_log: Path | None = None


@dataclass
class _LogSink:
    """Plain-text serial log file: all escapes stripped before writing."""

    file: TextIO
    stripper: AnsiStripper = field(default_factory=lambda: AnsiStripper(keep_sgr=False))

    def write(self, text: str) -> None:
        plain = self.stripper.feed(text)
        if plain:
            self.file.write(plain)
            self.file.flush()

    def close(self) -> None:
        leftover = self.stripper.flush()
        if leftover:
            self.file.write(leftover)
            self.file.flush()
        self.file.close()


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
    _log: _LogSink | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        capable = (
            self.ansi_capable
            if self.ansi_capable is not None
            else stderr_ansi_capable(self.stream)
        )
        self.ansi_capable = capable
        self._stderr_stripper = AnsiStripper(keep_sgr=capable)
        if self.serial_log is not None:
            self.serial_log.parent.mkdir(parents=True, exist_ok=True)
            log_file = self.serial_log.open("w", encoding="utf-8", newline="")
            self._log = _LogSink(file=log_file)

    def write(self, text: str) -> None:
        if not text:
            return
        if not self.quiet:
            shown = self._stderr_stripper.feed(text)
            if shown:
                print(shown, end="", file=self.stream, flush=True)
        if self._log is not None:
            self._log.write(text)

    def close(self) -> None:
        if not self.quiet:
            leftover = self._stderr_stripper.flush()
            if leftover:
                print(leftover, end="", file=self.stream, flush=True)
        if self._log is not None:
            self._log.close()
            self._log = None

    def __enter__(self) -> SerialDisplay:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
