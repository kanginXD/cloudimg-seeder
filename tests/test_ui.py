"""Tests for the Rich-backed terminal presentation layer."""

from __future__ import annotations

import io
import logging

import pytest
from rich.console import Console

from cloudimg_seeder.console.ui import RichProgressSink, StepHandler, Ui
from tests.support import FakeTty


def _console(
    *, tty: bool, environ: dict[str, str] | None = None, width: int = 60
) -> tuple[Console, io.StringIO]:
    buf = FakeTty() if tty else io.StringIO()
    console = Console(file=buf, width=width, _environ=environ or {})
    return console, buf


def test_ansi_capable_plain_tty() -> None:
    console, _ = _console(tty=True, environ={"TERM": "xterm-256color"})
    assert Ui(console=console).ansi_capable is True


def test_ansi_capable_false_when_not_a_terminal() -> None:
    console, _ = _console(tty=False, environ={"TERM": "xterm-256color"})
    assert Ui(console=console).ansi_capable is False


def test_ansi_capable_false_under_no_color() -> None:
    console, _ = _console(tty=True, environ={"TERM": "xterm", "NO_COLOR": "1"})
    assert Ui(console=console).ansi_capable is False


def test_ansi_capable_false_under_term_dumb() -> None:
    # Regression: TERM=dumb clears color_system but leaves is_terminal and
    # no_color untouched, so both of those alone are insufficient.
    console, _ = _console(tty=True, environ={"TERM": "dumb"})
    assert Ui(console=console).ansi_capable is False


def test_rule_title_is_not_parsed_as_markup() -> None:
    console, buf = _console(tty=False)
    Ui(console=console).rule("[end guest serial]")
    assert "[end guest serial]" in buf.getvalue()


def test_message_renders_bracketed_text_literally() -> None:
    console, buf = _console(tty=False)
    Ui(console=console).message("output: seeded/a[b]c.qcow2")
    assert "seeded/a[b]c.qcow2" in buf.getvalue()
    assert "▸" in buf.getvalue()


def test_message_suppressed_when_steps_off() -> None:
    console, buf = _console(tty=False)
    Ui(console=console, show_steps=False).message("hidden")
    assert buf.getvalue() == ""


def test_error_always_renders_even_when_steps_off() -> None:
    console, buf = _console(tty=False)
    Ui(console=console, show_steps=False).error("boom [with brackets]")
    assert "boom [with brackets]" in buf.getvalue()


def test_write_raw_passes_bytes_through_untouched() -> None:
    console, buf = _console(tty=False)
    Ui(console=console).write_raw("guest \x1b[32mgreen\x1b[0m\n")
    assert buf.getvalue() == "guest \x1b[32mgreen\x1b[0m\n"


def test_message_starts_on_new_line_after_unterminated_raw_write() -> None:
    """Regression: a step message logged while the guest's last serial line
    had no trailing newline was appended to that line."""
    console, buf = _console(tty=False)
    ui = Ui(console=console)
    ui.write_raw("Cloud-init v. 26.1 finished at Fri")
    ui.message("cloud-init finished; sending ACPI powerdown")
    lines = buf.getvalue().splitlines()
    assert lines[0] == "Cloud-init v. 26.1 finished at Fri"
    assert lines[1].startswith("▸ cloud-init finished")


def test_error_starts_on_new_line_after_unterminated_raw_write() -> None:
    console, buf = _console(tty=False)
    ui = Ui(console=console)
    ui.write_raw("partial guest line")
    ui.error("boom")
    lines = buf.getvalue().splitlines()
    assert lines[0] == "partial guest line"
    assert lines[1].startswith("✗ boom")


def test_rule_starts_on_new_line_after_unterminated_raw_write() -> None:
    console, buf = _console(tty=False)
    ui = Ui(console=console)
    ui.write_raw("partial guest line")
    ui.rule("end guest serial")
    lines = buf.getvalue().splitlines()
    assert lines[0] == "partial guest line"
    assert "end guest serial" in lines[1]


def test_no_spurious_blank_line_when_raw_write_ended_cleanly() -> None:
    console, buf = _console(tty=False)
    ui = Ui(console=console)
    ui.write_raw("complete guest line\n")
    ui.message("next step")
    assert buf.getvalue().splitlines() == [
        "complete guest line",
        "▸ next step",
    ]


def test_trailing_carriage_return_counts_as_line_start() -> None:
    console, buf = _console(tty=False)
    ui = Ui(console=console)
    ui.write_raw("progress 50%\r")
    ui.message("next step")
    # CR already returned the cursor to column 0; no extra newline is added.
    assert "\r\n" not in buf.getvalue()


def test_message_suppressed_by_show_steps_still_tracks_cursor() -> None:
    """A muted step must not leave the cursor state wrong for the next rule."""
    console, buf = _console(tty=False)
    ui = Ui(console=console, show_steps=False)
    ui.write_raw("partial guest line")
    ui.message("muted")
    ui.error("boom")
    lines = buf.getvalue().splitlines()
    assert lines[0] == "partial guest line"
    assert lines[1].startswith("✗ boom")


def test_new_progress_disabled_when_not_a_terminal() -> None:
    console, _ = _console(tty=False)
    bar = Ui(console=console).new_progress()
    assert bar.disable is True


def test_new_progress_disabled_when_steps_off() -> None:
    console, _ = _console(tty=True, environ={"TERM": "xterm"})
    bar = Ui(console=console, show_steps=False).new_progress()
    assert bar.disable is True


def test_rich_progress_sink_reports_no_frames_when_disabled() -> None:
    console, buf = _console(tty=False)
    sink = RichProgressSink(Ui(console=console))
    sink.start("converting to qcow2")
    sink.advance(50.0)
    sink.finish()
    assert buf.getvalue() == ""


def test_rich_progress_sink_advance_before_start_is_a_noop() -> None:
    console, _ = _console(tty=False)
    sink = RichProgressSink(Ui(console=console))
    sink.advance(50.0)  # must not raise


@pytest.mark.parametrize(
    ("level", "marker"),
    [
        (logging.INFO, "▸"),
        (logging.WARNING, "!"),
        (logging.ERROR, "✗"),
    ],
)
def test_step_handler_selects_marker_by_level(level: int, marker: str) -> None:
    console, buf = _console(tty=False)
    logger = logging.getLogger("cloudimg_seeder.test_step_handler")
    logger.handlers.clear()
    logger.addHandler(StepHandler(Ui(console=console)))
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.log(level, "message")
    assert marker in buf.getvalue()
    assert "message" in buf.getvalue()


def test_step_handler_bracketed_message_not_mangled() -> None:
    console, buf = _console(tty=False)
    logger = logging.getLogger("cloudimg_seeder.test_step_handler_brackets")
    logger.handlers.clear()
    logger.addHandler(StepHandler(Ui(console=console)))
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.info("output: %s", "seeded/a[b]c.qcow2")
    assert "seeded/a[b]c.qcow2" in buf.getvalue()
