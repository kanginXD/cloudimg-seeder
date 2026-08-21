"""Tests for the streaming ECMA-48 parser."""

from __future__ import annotations

import random

from cloudimg_seeder.console.ansi import AnsiParser
from cloudimg_seeder.console.filter import SgrFilter, strip_ansi


def test_strip_sgr() -> None:
    assert strip_ansi("\x1b[32mOK\x1b[0m") == "OK"


def test_keep_sgr_drops_dsr() -> None:
    assert strip_ansi("\x1b[32mOK\x1b[0m\x1b[6n", keep_sgr=True) == "\x1b[32mOK\x1b[0m"


def test_strip_dsr_query() -> None:
    assert strip_ansi("before\x1b[6nafter") == "beforeafter"


def test_strip_osc_bel() -> None:
    assert strip_ansi("\x1b]0;title\x07hi") == "hi"


def test_split_csi_across_chunks_keep_sgr() -> None:
    sink = SgrFilter(keep_sgr=True)
    parser = AnsiParser(sink)
    parser.feed("a\x1b[3")
    assert sink.drain() == "a"
    parser.feed("2mOK\x1b[6n")
    assert sink.drain() == "\x1b[32mOK"


def test_split_csi_across_chunks_strip_all() -> None:
    sink = SgrFilter()
    parser = AnsiParser(sink)
    parser.feed("a\x1b[3")
    assert sink.drain() == "a"
    parser.feed("2mOK\x1b[0m")
    assert sink.drain() == "OK"


def test_incomplete_escape_at_end_of_stream_is_dropped() -> None:
    sink = SgrFilter()
    parser = AnsiParser(sink)
    parser.feed("x\x1b[")
    assert sink.drain() == "x"
    parser.reset()
    assert sink.drain() == ""


def test_plain_passthrough() -> None:
    assert strip_ansi("hello\nworld") == "hello\nworld"


def test_can_aborts_sequence() -> None:
    """Regression: CAN was ignored and 'h' was consumed as a CSI final byte."""
    assert strip_ansi("\x1b[3\x18hello") == "hello"


def test_sub_aborts_sequence() -> None:
    assert strip_ansi("\x1b[3\x1ahello") == "hello"


def test_esc_restarts_sequence() -> None:
    """Regression: a fresh ESC must abandon a partial sequence, not extend it."""
    assert strip_ansi("\x1b[3\x1b[0mhi", keep_sgr=True) == "\x1b[0mhi"


def test_unterminated_osc_does_not_black_out_the_stream() -> None:
    """Regression: an unterminated OSC used to swallow every later chunk."""
    sink = SgrFilter()
    parser = AnsiParser(sink)
    parser.feed("boot ok\n\x1b]0;title")
    assert sink.drain() == "boot ok\n"
    parser.feed("x" * 100_000)
    parser.feed("hello\n")
    assert "hello\n" in sink.drain()


def test_st_terminates_osc() -> None:
    assert strip_ansi("\x1b]0;t\x1b\\hi") == "hi"


def test_dcs_terminated_by_st() -> None:
    assert strip_ansi("\x1bPq#0;2\x1b\\after") == "after"


def test_split_st_across_chunks() -> None:
    sink = SgrFilter()
    parser = AnsiParser(sink)
    parser.feed("\x1bPdata\x1b")
    assert sink.drain() == ""
    parser.feed("\\after")
    assert sink.drain() == "after"


def test_split_osc_across_chunks() -> None:
    sink = SgrFilter()
    parser = AnsiParser(sink)
    parser.feed("\x1b]0;ti")
    assert sink.drain() == ""
    parser.feed("tle\x07hi")
    assert sink.drain() == "hi"


def test_8bit_csi_introducer_consumes_payload() -> None:
    """Regression: a lone C1 CSI introducer left its payload as literal text."""
    assert strip_ansi("\x9b32mOK") == "OK"


def test_8bit_csi_sgr_is_reemitted_as_7bit() -> None:
    assert strip_ansi("\x9b32mOK", keep_sgr=True) == "\x1b[32mOK"


def test_8bit_osc_consumes_payload() -> None:
    assert strip_ansi("\x9d0;title\x9chi") == "hi"


def test_8bit_dcs_consumes_payload() -> None:
    assert strip_ansi("\x90q#0\x9chi") == "hi"


def test_keep_sgr_keeps_subparameter_truecolor() -> None:
    assert strip_ansi("\x1b[38:2::255:0:0mX", keep_sgr=True) == "\x1b[38:2::255:0:0mX"


def test_keep_sgr_drops_csi_with_intermediates() -> None:
    assert strip_ansi("\x1b[1 mX", keep_sgr=True) == "X"


def test_keep_sgr_drops_private_marker_csi() -> None:
    assert strip_ansi("\x1b[?1mX", keep_sgr=True) == "X"


def test_c0_controls_pass_through() -> None:
    assert strip_ansi("a\rb\tc\x07d") == "a\rb\tc\x07d"


def test_can_and_sub_are_consumed_in_ground() -> None:
    """Regression: CAN/SUB carry no display meaning; they only abort sequences."""
    assert strip_ansi("a\x18b\x1ac") == "abc"


def test_non_ascii_passes_through() -> None:
    assert strip_ansi("부팅 완료 ✓\n") == "부팅 완료 ✓\n"


_FUZZ_ALPHABET = list("\x1b[]P\\m n0123;:?<=>abcXYZ\x18\x1a\x9b\x9d\x90\x9c \t\r\n부✓")


def test_chunking_does_not_change_output() -> None:
    rng = random.Random(0)  # noqa: S311 - test fuzzing seed, not cryptographic
    for _ in range(200):
        length = rng.randint(0, 40)
        text = "".join(rng.choice(_FUZZ_ALPHABET) for _ in range(length))
        for keep_sgr in (False, True):
            whole = strip_ansi(text, keep_sgr=keep_sgr)

            sink = SgrFilter(keep_sgr=keep_sgr)
            parser = AnsiParser(sink)
            pos = 0
            while pos < len(text):
                step = rng.randint(1, 5)
                parser.feed(text[pos : pos + step])
                pos += step
            chunked = sink.drain()

            assert chunked == whole
            if not keep_sgr:
                assert "\x1b" not in chunked
                assert not any(0x80 <= ord(c) <= 0x9F for c in chunked)
