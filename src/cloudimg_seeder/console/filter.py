"""SGR-preserving text filter over ``AnsiParser`` output."""

from __future__ import annotations

from cloudimg_seeder.console.ansi import AnsiParser


class SgrFilter:
    """Collect parsed guest serial into plain text, keeping SGR colors.

    Passed to ``AnsiParser`` as its sink. When ``keep_sgr`` is True, CSI
    sequences that are pure SGR (no intermediates, no private marker, final
    byte ``m``) are re-emitted in their verbatim 7-bit form; every other
    sequence is dropped. CAN and SUB never reach a sink at all — the parser
    consumes them as sequence aborts.
    """

    def __init__(self, *, keep_sgr: bool = False) -> None:
        self._keep_sgr = keep_sgr
        self._out: list[str] = []

    def text(self, text: str) -> None:
        self._out.append(text)

    def execute(self, char: str) -> None:
        self._out.append(char)

    def csi(
        self, params: str, intermediates: str, final: str, private: bool, raw: str
    ) -> None:
        del params
        if self._keep_sgr and final == "m" and not intermediates and not private:
            self._out.append(raw)

    def drain(self) -> str:
        text = "".join(self._out)
        self._out.clear()
        return text


def strip_ansi(text: str, *, keep_sgr: bool = False) -> str:
    """Filter escapes from a complete string."""
    sink = SgrFilter(keep_sgr=keep_sgr)
    AnsiParser(sink).feed(text)
    return sink.drain()
