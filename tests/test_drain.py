"""Tests for stdin drain helper."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock

import pytest

from cloudimg_seeder.console import drain as drain_mod
from cloudimg_seeder.console.drain import drain_stdin


def test_drain_non_tty_noop() -> None:
    stream = StringIO("queued")
    drain_stdin(stream)
    assert stream.getvalue() == "queued"


def test_drain_posix_reads_until_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drain_mod.sys, "platform", "linux")
    reads = [b"abc", b";1R", b""]

    def fake_read(_fd: int, _n: int) -> bytes:
        return reads.pop(0) if reads else b""

    def get_blocking(_fd: int) -> bool:
        return True

    def set_blocking(_fd: int, _value: bool) -> None:
        return None

    stream = MagicMock()
    stream.isatty.return_value = True
    stream.fileno.return_value = 0
    monkeypatch.setattr(drain_mod.os, "get_blocking", get_blocking)
    monkeypatch.setattr(drain_mod.os, "set_blocking", set_blocking)
    monkeypatch.setattr(drain_mod.os, "read", fake_read)
    drain_stdin(stream)
    assert reads == []


def test_drain_isatty_oserror_noop() -> None:
    stream = MagicMock()
    stream.isatty.side_effect = OSError("gone")
    drain_stdin(stream)
