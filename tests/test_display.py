"""Tests for SerialDisplay sinks and guest-serial rule framing."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from cloudimg_seeder.console.display import SerialDisplay, SerialLogFormat
from cloudimg_seeder.console.ui import Ui
from tests.support import FakeTty


def _ui(*, tty: bool, width: int = 60) -> tuple[Ui, io.StringIO]:
    buf = FakeTty() if tty else io.StringIO()
    environ = {"TERM": "xterm-256color"} if tty else {}
    console = Console(file=buf, width=width, _environ=environ)
    return Ui(console=console), buf


def test_capable_keeps_sgr_drops_dsr() -> None:
    ui, buf = _ui(tty=True)
    display = SerialDisplay(ui=ui)
    display.write("\x1b[32mOK\x1b[0m\x1b[6n")
    display.close()
    assert "\x1b[32mOK\x1b[0m" in buf.getvalue()
    assert "\x1b[6n" not in buf.getvalue()


def test_dumb_strips() -> None:
    ui, buf = _ui(tty=False)
    display = SerialDisplay(ui=ui)
    display.write("\x1b[32mOK\x1b[0m")
    display.close()
    assert "\x1b[32m" not in buf.getvalue()
    assert "OK" in buf.getvalue()


def test_show_serial_false_writes_nothing() -> None:
    ui, buf = _ui(tty=False)
    display = SerialDisplay(ui=ui, show_serial=False)
    display.write("hello")
    display.close()
    assert buf.getvalue() == ""


def test_serial_log_is_plain_text(tmp_path: Path) -> None:
    ui, buf = _ui(tty=True)
    log = tmp_path / "serial.log"
    display = SerialDisplay(ui=ui, serial_log=log)
    display.write("\x1b[32mOK\x1b[0m\x1b[6n\n")
    display.close()
    assert "\x1b[32mOK\x1b[0m" in buf.getvalue()
    assert log.read_text(encoding="utf-8") == "OK\n"


def test_show_serial_false_with_serial_log_still_writes_file(tmp_path: Path) -> None:
    ui, buf = _ui(tty=True)
    log = tmp_path / "serial.log"
    display = SerialDisplay(ui=ui, show_serial=False, serial_log=log)
    display.write("\x1b[31monly-file\x1b[0m")
    display.close()
    assert buf.getvalue() == ""
    assert log.read_text(encoding="utf-8") == "only-file\n"


def test_serial_log_format_plain_interprets_carriage_return(tmp_path: Path) -> None:
    ui, _buf = _ui(tty=False)
    log = tmp_path / "serial.log"
    display = SerialDisplay(ui=ui, serial_log=log)
    display.write("50%\rdone\n")
    display.close()
    assert log.read_text(encoding="utf-8") == "done\n"


def test_serial_log_format_raw_preserves_escapes_and_cr(tmp_path: Path) -> None:
    ui, _buf = _ui(tty=False)
    log = tmp_path / "serial.log"
    display = SerialDisplay(
        ui=ui, serial_log=log, serial_log_format=SerialLogFormat.RAW
    )
    display.write("50%\r\x1b[32mdone\x1b[0m\n")
    display.close()
    # read_bytes, not read_text: Path.read_text applies universal-newline
    # translation on read, which would turn a lone \r into \n and hide
    # exactly the byte this test exists to check.
    assert log.read_bytes() == b"50%\r\x1b[32mdone\x1b[0m\n"


def test_no_serial_output_leaves_no_rules() -> None:
    """A boot that produces no serial must not leave an empty framed region."""
    ui, buf = _ui(tty=False)
    display = SerialDisplay(ui=ui)
    display.close()
    assert buf.getvalue() == ""


def test_serial_output_is_framed_by_rules() -> None:
    ui, buf = _ui(tty=False)
    display = SerialDisplay(ui=ui)
    display.write("line one\n")
    display.write("line two\n")
    display.close()
    out = buf.getvalue()
    assert "guest serial" in out
    assert "end guest serial" in out
    open_idx = out.index("guest serial")
    close_idx = out.index("end guest serial")
    assert open_idx < out.index("line one") < out.index("line two") < close_idx


def test_closing_rule_starts_on_a_fresh_line_after_unterminated_output() -> None:
    ui, buf = _ui(tty=False)
    display = SerialDisplay(ui=ui)
    display.write("no trailing newline")
    display.close()
    out = buf.getvalue()
    # The rule is a full-width line of dashes; it must not be glued onto
    # the end of the guest's last, newline-less line.
    close_line = next(line for line in out.splitlines() if "end guest serial" in line)
    assert "no trailing newline" not in close_line


def test_context_manager_closes_on_exit(tmp_path: Path) -> None:
    ui, buf = _ui(tty=False)
    log = tmp_path / "serial.log"
    with SerialDisplay(ui=ui, serial_log=log) as display:
        display.write("hello\x1b[6n")
    assert "hello" in buf.getvalue()
    assert log.read_text(encoding="utf-8") == "hello\n"


def test_context_manager_closes_on_exception(tmp_path: Path) -> None:
    ui, _buf = _ui(tty=False)
    log = tmp_path / "serial.log"
    with (
        pytest.raises(RuntimeError),
        SerialDisplay(ui=ui, serial_log=log) as display,
    ):
        display.write("partial")
        raise RuntimeError("boom")
    assert log.read_text(encoding="utf-8") == "partial\n"
