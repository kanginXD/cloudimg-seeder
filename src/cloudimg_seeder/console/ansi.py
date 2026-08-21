"""Streaming ECMA-48 parser for guest serial: event-based, cross-chunk safe.

Implements the DEC ANSI parser state table (vt100.net/emu/dec_ansi_parser),
adapted from bytes to ``str`` codepoints, plus the 8-bit C1 introducers and
the BEL string terminator xterm accepts alongside ST. Recognized sequences
are dispatched as events on an ``AnsiSink``; nothing is buffered across
``feed`` calls except a sequence in progress, and that state is bounded by
``_MAX_SEQ_LEN``, so a malformed or unterminated sequence can hide at most
that many characters rather than the rest of the stream.

Deviations from the reference table, both required by real guest output:

- ``:`` (0x3A) is a CSI parameter byte, not a route to CSI_IGNORE. DEC VTs
  have no sub-parameters, but xterm, vte, and libvterm do, and ISO 8613-6
  truecolor SGR (``ESC[38:2::255:0:0m``) depends on it.
- OSC also terminates on BEL (0x07), the xterm extension, not only on ST.

The DCS, SOS, PM, and APC states collapse into one STRING state: the
reference table only distinguishes them by which callback fires, and this
parser fires none for string-family sequences.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Protocol


class AnsiSink(Protocol):
    """Receives parsed guest serial output."""

    def text(self, text: str) -> None:
        """One or more consecutive printable characters."""
        ...

    def execute(self, char: str) -> None:
        """A single C0 control character outside any sequence."""
        ...

    def csi(
        self, params: str, intermediates: str, final: str, private: bool, raw: str
    ) -> None:
        """A complete CSI sequence. ``raw`` is its verbatim 7-bit form."""
        ...


class _State(Enum):
    GROUND = auto()
    ESCAPE = auto()
    ESC_INTERMEDIATE = auto()
    CSI_ENTRY = auto()
    CSI_PARAM = auto()
    CSI_INTERMEDIATE = auto()
    CSI_IGNORE = auto()
    OSC = auto()
    STRING = auto()


# Cap on characters consumed while not in GROUND. A sequence longer than this
# is malformed or unterminated; abandoning it and resuming in GROUND bounds
# both memory and how long guest output can be hidden. Sibling bound:
# serial._LINE_BUF_MAX.
_MAX_SEQ_LEN = 4096


def _is_c0(o: int) -> bool:
    """C0 controls the parser executes rather than consuming structurally."""
    return o <= 0x1F and o not in (0x18, 0x1A, 0x1B)


def _is_param(o: int) -> bool:
    return 0x30 <= o <= 0x3B  # digits, ':', ';'


def _is_private_marker(o: int) -> bool:
    return 0x3C <= o <= 0x3F  # '<', '=', '>', '?'


def _is_intermediate(o: int) -> bool:
    return 0x20 <= o <= 0x2F


def _is_final(o: int) -> bool:
    return 0x40 <= o <= 0x7E


class AnsiParser:
    """Parse a guest serial stream, dispatching events to ``sink``."""

    def __init__(self, sink: AnsiSink) -> None:
        self._sink = sink
        self._state = _State.GROUND
        self._seq: list[str] = []
        self._params: list[str] = []
        self._intermediates: list[str] = []
        self._csi_private = False
        self._seq_len = 0

    def feed(self, text: str) -> None:
        run: list[str] = []
        for ch in text:
            o = ord(ch)
            if self._anywhere(o):
                if run:
                    self._sink.text("".join(run))
                    run.clear()
                self._track_seq_len()
                continue
            if self._state is _State.GROUND:
                if o < 0x20:
                    if run:
                        self._sink.text("".join(run))
                        run.clear()
                    self._sink.execute(ch)
                else:
                    run.append(ch)
                continue
            if run:
                self._sink.text("".join(run))
                run.clear()
            self._dispatch(ch, o)
            self._track_seq_len()
        if run:
            self._sink.text("".join(run))

    def reset(self) -> None:
        """Discard any sequence in progress and return to GROUND."""
        self._state = _State.GROUND
        self._seq.clear()
        self._params.clear()
        self._intermediates.clear()
        self._csi_private = False
        self._seq_len = 0

    def _track_seq_len(self) -> None:
        if self._state is _State.GROUND:
            self._seq_len = 0
            return
        self._seq_len += 1
        if self._seq_len > _MAX_SEQ_LEN:
            self.reset()

    def _anywhere(self, o: int) -> bool:
        if o in (0x18, 0x1A):  # CAN, SUB: abort
            self.reset()
            return True
        if o == 0x1B:  # ESC: abort, restart
            self.reset()
            self._state = _State.ESCAPE
            return True
        if o == 0x9B:  # 8-bit CSI
            self.reset()
            self._state = _State.CSI_ENTRY
            self._seq = ["\x1b", "["]
            return True
        if o == 0x9D:  # 8-bit OSC
            self.reset()
            self._state = _State.OSC
            return True
        if o in (0x90, 0x98, 0x9E, 0x9F):  # DCS, SOS, PM, APC
            self.reset()
            self._state = _State.STRING
            return True
        if o == 0x9C:  # 8-bit ST outside a string: no-op
            self.reset()
            return True
        if 0x80 <= o <= 0x9F:  # other C1: drop
            self.reset()
            return True
        return False

    def _dispatch(self, ch: str, o: int) -> None:
        match self._state:
            case _State.ESCAPE:
                self._escape(ch, o)
            case _State.ESC_INTERMEDIATE:
                self._esc_intermediate(ch, o)
            case _State.CSI_ENTRY:
                self._csi_entry(ch, o)
            case _State.CSI_PARAM:
                self._csi_param(ch, o)
            case _State.CSI_INTERMEDIATE:
                self._csi_intermediate(ch, o)
            case _State.CSI_IGNORE:
                self._csi_ignore(ch, o)
            case _State.OSC:
                self._osc(o)
            case _State.STRING:
                pass  # payload swallowed; ends via _anywhere or overflow
            case _State.GROUND:  # pragma: no cover - handled in feed()
                pass

    def _escape(self, ch: str, o: int) -> None:
        if o == 0x5B:  # [
            self._state = _State.CSI_ENTRY
            self._seq = ["\x1b", "["]
            return
        if o == 0x5D:  # ]
            self._state = _State.OSC
            return
        if ch in "PX^_":  # DCS, SOS, PM, APC
            self._state = _State.STRING
            return
        if _is_intermediate(o):
            self._state = _State.ESC_INTERMEDIATE
            return
        if _is_c0(o):
            self._sink.execute(ch)
            return
        if o == 0x7F:
            return
        # Any other 0x30-0x7E is a single-character escape (ESC c, ESC 7,
        # ST = ESC \, ...): dispatched to nothing, sequence ends here.
        self.reset()

    def _esc_intermediate(self, ch: str, o: int) -> None:
        if _is_intermediate(o):
            return
        if _is_c0(o):
            self._sink.execute(ch)
            return
        if o == 0x7F:
            return
        self.reset()

    def _csi_entry(self, ch: str, o: int) -> None:
        if _is_final(o):
            self._dispatch_csi(ch)
            return
        if _is_private_marker(o):
            self._csi_private = True
            self._params.append(ch)
            self._seq.append(ch)
            self._state = _State.CSI_PARAM
            return
        if _is_param(o):
            self._params.append(ch)
            self._seq.append(ch)
            self._state = _State.CSI_PARAM
            return
        if _is_intermediate(o):
            self._intermediates.append(ch)
            self._seq.append(ch)
            self._state = _State.CSI_INTERMEDIATE
            return
        if _is_c0(o):
            self._sink.execute(ch)
            return
        if o == 0x7F:
            return
        self._state = _State.CSI_IGNORE

    def _csi_param(self, ch: str, o: int) -> None:
        if _is_final(o):
            self._dispatch_csi(ch)
            return
        if _is_param(o):
            self._params.append(ch)
            self._seq.append(ch)
            return
        if _is_private_marker(o):  # private marker not at sequence start
            self._state = _State.CSI_IGNORE
            return
        if _is_intermediate(o):
            self._intermediates.append(ch)
            self._seq.append(ch)
            self._state = _State.CSI_INTERMEDIATE
            return
        if _is_c0(o):
            self._sink.execute(ch)
            return
        if o == 0x7F:
            return
        self._state = _State.CSI_IGNORE

    def _csi_intermediate(self, ch: str, o: int) -> None:
        if _is_final(o):
            self._dispatch_csi(ch)
            return
        if _is_intermediate(o):
            self._intermediates.append(ch)
            self._seq.append(ch)
            return
        if _is_c0(o):
            self._sink.execute(ch)
            return
        if o == 0x7F:
            return
        self._state = _State.CSI_IGNORE

    def _csi_ignore(self, ch: str, o: int) -> None:
        if _is_final(o):
            self.reset()  # malformed CSI: no dispatch
            return
        if _is_c0(o):
            self._sink.execute(ch)

    def _osc(self, o: int) -> None:
        if o == 0x07:  # BEL
            self.reset()

    def _dispatch_csi(self, final: str) -> None:
        raw = "".join(self._seq) + final
        params = "".join(self._params)
        intermediates = "".join(self._intermediates)
        private = self._csi_private
        self.reset()
        self._sink.csi(params, intermediates, final, private, raw)
