"""Tests for stderr ANSI capability detection."""

from __future__ import annotations

from cloudimg_seeder.console.capability import stderr_ansi_capable


class _Tty:
    def isatty(self) -> bool:
        return True


class _Pipe:
    def isatty(self) -> bool:
        return False


def test_capable_tty() -> None:
    assert stderr_ansi_capable(_Tty(), environ={"TERM": "xterm-256color"}) is True


def test_not_tty() -> None:
    assert stderr_ansi_capable(_Pipe(), environ={"TERM": "xterm"}) is False


def test_dumb_term() -> None:
    assert stderr_ansi_capable(_Tty(), environ={"TERM": "dumb"}) is False


def test_no_color() -> None:
    assert (
        stderr_ansi_capable(_Tty(), environ={"TERM": "xterm", "NO_COLOR": "1"}) is False
    )


def test_no_color_empty_allows() -> None:
    assert (
        stderr_ansi_capable(_Tty(), environ={"TERM": "xterm", "NO_COLOR": ""}) is True
    )
