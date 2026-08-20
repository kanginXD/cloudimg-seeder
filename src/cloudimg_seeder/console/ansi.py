"""Streaming ECMA-48 filter for guest serial on the host terminal."""

from __future__ import annotations


class AnsiStripper:
    """Filter ESC sequences across chunk boundaries.

    When ``keep_sgr`` is False, all CSI/OSC/DCS-family sequences are removed.
    When True, CSI sequences whose final byte is ``m`` (SGR / colors) are
    kept; other escapes (including DSR queries such as ``ESC [ 6 n``) are
    removed so the host TTY does not emit stdin replies.
    """

    def __init__(self, *, keep_sgr: bool = False) -> None:
        self._keep_sgr = keep_sgr
        self._pending = ""

    def feed(self, text: str) -> str:
        data = self._pending + text
        self._pending = ""
        out: list[str] = []
        i = 0
        n = len(data)
        while i < n:
            ch = data[i]
            if ch == "\x1b":
                kept, rest = _consume_escape(data, i, keep_sgr=self._keep_sgr)
                if kept is None:
                    self._pending = data[i:]
                    break
                if kept:
                    out.append(kept)
                i = rest
                continue
            if "\x80" <= ch <= "\x9f":
                i += 1
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    def flush(self) -> str:
        """Drop any incomplete escape and return remaining plain text."""
        pending = self._pending
        self._pending = ""
        if not pending:
            return ""
        if pending.startswith("\x1b"):
            return ""
        return pending


def _consume_escape(
    data: str,
    start: int,
    *,
    keep_sgr: bool,
) -> tuple[str | None, int]:
    """Parse one escape at start.

    Returns (text_to_emit_or_empty_if_dropped, next_index).
    Incomplete returns (None, start).
    """
    n = len(data)
    if start >= n or data[start] != "\x1b":
        return ("", start)
    if start + 1 >= n:
        return (None, start)

    second = data[start + 1]
    if second == "[":  # CSI
        j = start + 2
        while j < n:
            c = data[j]
            if "\x40" <= c <= "\x7e":
                seq = data[start : j + 1]
                if keep_sgr and c == "m":
                    return (seq, j + 1)
                return ("", j + 1)
            j += 1
        return (None, start)

    if second == "]":  # OSC
        j = start + 2
        while j < n:
            if data[j] == "\x07":
                return ("", j + 1)
            if data[j] == "\x1b" and j + 1 < n and data[j + 1] == "\\":
                return ("", j + 2)
            j += 1
        return (None, start)

    if second in "PX^_":  # DCS / SOS / PM / APC
        j = start + 2
        while j < n:
            if data[j] == "\x1b" and j + 1 < n and data[j + 1] == "\\":
                return ("", j + 2)
            j += 1
        return (None, start)

    if "\x20" <= second <= "\x2f":
        j = start + 2
        while j < n:
            c = data[j]
            if "\x30" <= c <= "\x7e":
                return ("", j + 1)
            if not ("\x20" <= c <= "\x2f"):
                return ("", j + 1)
            j += 1
        return (None, start)

    return ("", start + 2)


def strip_ansi(text: str, *, keep_sgr: bool = False) -> str:
    """Filter escapes from a complete string."""
    stripper = AnsiStripper(keep_sgr=keep_sgr)
    return stripper.feed(text) + stripper.flush()
