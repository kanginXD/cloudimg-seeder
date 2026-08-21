"""Guest serial display sinks: console framing and optional log file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import TextIO

from cloudimg_seeder.console.ansi import AnsiStripper
from cloudimg_seeder.console.ui import Ui

_RULE_OPEN = "guest serial"
_RULE_CLOSE = "end guest serial"


@dataclass
class SerialOptions:
    """How guest serial should be presented and recorded."""

    show_serial: bool = True
    serial_log: Path | None = None
    ui: Ui = field(default_factory=Ui)


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
    """Write guest serial to the console and/or a plain-text log file.

    Console output is delimited by ``guest serial`` rules so it is never
    confused with cloudimg-seeder's own lines. The rules are emitted lazily,
    so a boot that produces no serial leaves no empty framed region. Guest
    text is written raw: an ANSI-capable console keeps the guest's SGR colors
    while host-querying escapes are dropped, and a dumb or redirected console
    strips all escapes. ``serial_log`` always receives plain text.
    """

    ui: Ui
    show_serial: bool = True
    serial_log: Path | None = None
    _stripper: AnsiStripper = field(init=False, repr=False)
    _log: _LogSink | None = field(default=None, init=False, repr=False)
    _opened: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._stripper = AnsiStripper(keep_sgr=self.ui.ansi_capable)
        if self.serial_log is not None:
            self.serial_log.parent.mkdir(parents=True, exist_ok=True)
            log_file = self.serial_log.open("w", encoding="utf-8", newline="")
            self._log = _LogSink(file=log_file)

    def _show(self, text: str) -> None:
        if not text:
            return
        if not self._opened:
            self.ui.rule(_RULE_OPEN)
            self._opened = True
        self.ui.write_raw(text)

    def write(self, text: str) -> None:
        if not text:
            return
        if self.show_serial:
            self._show(self._stripper.feed(text))
        if self._log is not None:
            self._log.write(text)

    def close(self) -> None:
        if self.show_serial:
            self._show(self._stripper.flush())
            if self._opened:
                self.ui.rule(_RULE_CLOSE)
                self._opened = False
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
