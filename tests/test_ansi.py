"""Tests for streaming ANSI stripper."""

from __future__ import annotations

from cloudimg_seeder.console.ansi import AnsiStripper, strip_ansi


def test_strip_sgr() -> None:
    assert strip_ansi("\x1b[32mOK\x1b[0m") == "OK"


def test_keep_sgr_drops_dsr() -> None:
    assert strip_ansi("\x1b[32mOK\x1b[0m\x1b[6n", keep_sgr=True) == "\x1b[32mOK\x1b[0m"


def test_strip_dsr_query() -> None:
    assert strip_ansi("before\x1b[6nafter") == "beforeafter"


def test_strip_osc_bel() -> None:
    assert strip_ansi("\x1b]0;title\x07hi") == "hi"


def test_split_csi_across_chunks_keep_sgr() -> None:
    s = AnsiStripper(keep_sgr=True)
    assert s.feed("a\x1b[3") == "a"
    assert s.feed("2mOK\x1b[6n") == "\x1b[32mOK"
    assert s.flush() == ""


def test_split_csi_across_chunks_strip_all() -> None:
    s = AnsiStripper()
    assert s.feed("a\x1b[3") == "a"
    assert s.feed("2mOK\x1b[0m") == "OK"
    assert s.flush() == ""


def test_incomplete_escape_flush_drops() -> None:
    s = AnsiStripper()
    assert s.feed("x\x1b[") == "x"
    assert s.flush() == ""


def test_plain_passthrough() -> None:
    assert strip_ansi("hello\nworld") == "hello\nworld"
