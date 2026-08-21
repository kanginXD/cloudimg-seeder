"""Tests for PlainTextRenderer."""

from __future__ import annotations

import io

from cloudimg_seeder.console.ansi import AnsiParser
from cloudimg_seeder.console.plaintext import PlainTextRenderer


def _render(text: str) -> str:
    buf = io.StringIO()
    renderer = PlainTextRenderer(buf)
    AnsiParser(renderer).feed(text)
    renderer.close()
    return buf.getvalue()


def test_carriage_return_overwrites_the_line() -> None:
    assert _render("50%\rdone\n") == "done\n"


def test_backspace_overwrites_one_column() -> None:
    assert _render("hellx\bo\n") == "hello\n"


def test_erase_to_end_of_line() -> None:
    assert _render("hello world\r\x1b[Khi\n") == "hi\n"


def test_erase_whole_line() -> None:
    assert _render("hello\x1b[2Kworld\n") == "world\n"


def test_tab_advances_to_next_stop() -> None:
    assert _render("a\tb\n") == "a       b\n"


def test_blank_line_is_preserved() -> None:
    assert _render("one\n\ntwo\n") == "one\n\ntwo\n"


def test_partial_line_flushed_on_close() -> None:
    assert _render("no trailing newline") == "no trailing newline\n"


def test_bare_cursor_move_with_no_content_produces_no_line() -> None:
    assert _render("\x1b[5C") == ""
