"""Tests for SerialDisplay sinks."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from cloudimg_seeder.console.display import SerialDisplay


def test_capable_keeps_sgr_drops_dsr() -> None:
    buf = StringIO()
    display = SerialDisplay(quiet=False, ansi_capable=True, stream=buf)
    display.write("\x1b[32mOK\x1b[0m\x1b[6n")
    display.close()
    assert buf.getvalue() == "\x1b[32mOK\x1b[0m"


def test_dumb_strips() -> None:
    buf = StringIO()
    display = SerialDisplay(quiet=False, ansi_capable=False, stream=buf)
    display.write("\x1b[32mOK\x1b[0m")
    display.close()
    assert buf.getvalue() == "OK"


def test_quiet_no_stderr() -> None:
    buf = StringIO()
    display = SerialDisplay(quiet=True, ansi_capable=True, stream=buf)
    display.write("hello")
    display.close()
    assert buf.getvalue() == ""


def test_serial_log_matches_display(tmp_path: Path) -> None:
    buf = StringIO()
    log = tmp_path / "serial.log"
    display = SerialDisplay(
        quiet=False,
        ansi_capable=False,
        stream=buf,
        serial_log=log,
    )
    display.write("\x1b[31merr\x1b[0m\n")
    display.close()
    assert buf.getvalue() == "err\n"
    assert log.read_text(encoding="utf-8") == "err\n"


def test_quiet_with_serial_log(tmp_path: Path) -> None:
    buf = StringIO()
    log = tmp_path / "serial.log"
    display = SerialDisplay(
        quiet=True,
        ansi_capable=True,
        stream=buf,
        serial_log=log,
    )
    display.write("only-file")
    display.close()
    assert buf.getvalue() == ""
    assert log.read_text(encoding="utf-8") == "only-file"
