"""Render parsed guest serial as an interpreted plain-text log.

Guest serial commonly overwrites progress lines with carriage returns and
cursor-movement CSI sequences (percent counters, spinners). Stripping only
the escape bytes and writing what remains leaves those overwrites
concatenated on one unreadable line. This renderer instead tracks a cursor
within the current line, so the log records what a terminal would finally
have displayed for each line.
"""

from __future__ import annotations

from typing import TextIO

_TAB_STOP = 8
# Cap on one rendered line's length. Sibling bound: serial._LINE_BUF_MAX.
_MAX_LINE = 8192


def _param_int(params: str, default: int) -> int:
    head = params.split(";", 1)[0].split(":", 1)[0]
    if not head:
        return default
    try:
        return int(head)
    except ValueError:
        return default


class PlainTextRenderer:
    """``AnsiSink`` that writes one interpreted line per newline to ``file``."""

    def __init__(self, file: TextIO) -> None:
        self._file = file
        self._line: list[str] = []
        self._col = 0

    def text(self, text: str) -> None:
        for ch in text:
            self._put(ch)

    def execute(self, char: str) -> None:
        if char in ("\n", "\v", "\f"):
            self._commit()
        elif char == "\r":
            self._col = 0
        elif char == "\b":
            self._col = max(0, self._col - 1)
        elif char == "\t":
            self._col = min(_MAX_LINE - 1, (self._col // _TAB_STOP + 1) * _TAB_STOP)
        # other C0 controls have no rendering effect here

    def csi(
        self, params: str, intermediates: str, final: str, private: bool, raw: str
    ) -> None:
        del raw
        if intermediates or private:
            return
        if final == "K":
            self._erase_line(_param_int(params, 0))
        elif final == "C":
            self._col = min(_MAX_LINE - 1, self._col + max(1, _param_int(params, 1)))
        elif final == "D":
            self._col = max(0, self._col - max(1, _param_int(params, 1)))
        elif final == "G":
            self._col = max(0, min(_MAX_LINE - 1, _param_int(params, 1) - 1))

    def close(self) -> None:
        # Only a line that received content is worth a final, unterminated
        # record; a bare cursor move with nothing typed is not a line.
        if self._line:
            self._commit()

    def _put(self, ch: str) -> None:
        if self._col >= _MAX_LINE:
            self._commit()
        while len(self._line) <= self._col:
            self._line.append(" ")
        self._line[self._col] = ch
        self._col += 1

    def _erase_line(self, mode: int) -> None:
        if mode == 0:
            del self._line[self._col :]
        elif mode == 1:
            for i in range(min(self._col, len(self._line))):
                self._line[i] = " "
        elif mode == 2:
            self._line.clear()
            self._col = 0

    def _commit(self) -> None:
        # Explicit newlines commit unconditionally, including a blank line.
        self._file.write("".join(self._line).rstrip() + "\n")
        self._file.flush()
        self._line.clear()
        self._col = 0
