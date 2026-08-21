"""The single owner of terminal presentation.

Nothing else in the package imports ``rich``. Library modules report through
``logging`` and ``ProgressSink``; this module decides how that is rendered.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text
from rich.theme import Theme

if sys.version_info >= (3, 12):
    from typing import override
else:  # requires-python floor is 3.11; typing.override is 3.12+

    def override(func):  # type: ignore[no-redef]
        return func


_THEME = Theme(
    {
        "seeder.step": "cyan",
        "seeder.warn": "yellow",
        "seeder.error": "bold red",
        "seeder.rule": "dim",
    }
)

_STEP_MARKER = "▸"
_WARN_MARKER = "!"
_ERROR_MARKER = "✗"

# Level -> (marker, style). Anything below WARNING renders as a step.
_LEVEL_RENDERING: dict[int, tuple[str, str]] = {
    logging.WARNING: (_WARN_MARKER, "seeder.warn"),
    logging.ERROR: (_ERROR_MARKER, "seeder.error"),
    logging.CRITICAL: (_ERROR_MARKER, "seeder.error"),
}


@dataclass
class Ui:
    """Terminal output surface for everything the user sees on stderr."""

    console: Console = field(
        default_factory=lambda: Console(stderr=True, theme=_THEME, highlight=False)
    )
    show_steps: bool = True
    # Column state for the shared terminal cursor. Rich assumes it owns the
    # cursor and always begins a renderable at column 0; ``write_raw``
    # bypasses Rich, so only this class can know where the cursor actually
    # is. Every rendering path below reconciles the two.
    _at_line_start: bool = field(default=True, init=False, repr=False)

    @property
    def ansi_capable(self) -> bool:
        """True when guest serial may keep its own SGR codes.

        All three checks are independent: ``TERM=dumb`` clears
        ``color_system`` but leaves ``is_terminal`` and ``no_color`` alone,
        and ``NO_COLOR`` clears neither ``is_terminal`` nor ``color_system``.
        """
        return (
            self.console.is_terminal
            and not self.console.no_color
            and self.console.color_system is not None
        )

    def _ensure_line_start(self) -> None:
        """Put the cursor at column 0 before Rich renders anything.

        Without this, a renderable started after raw output that did not end
        in a newline is appended to the guest's last line instead of
        beginning its own.
        """
        if self._at_line_start:
            return
        self.console.file.write("\n")
        self.console.file.flush()
        self._at_line_start = True

    def rule(self, title: str) -> None:
        """Draw a titled separator.

        The title is wrapped in ``Text`` because ``Console.rule`` parses a
        plain ``str`` title as console markup, which silently deletes any
        bracketed run.
        """
        self._ensure_line_start()
        self.console.rule(Text(title), style="seeder.rule")
        self._at_line_start = True

    def write_raw(self, text: str) -> None:
        """Write bytes through untouched, bypassing Rich.

        Guest serial carries its own escapes and line structure; routing it
        through ``Console.print`` would re-wrap and re-interpret it. Never
        call this while a progress region is active — a raw write into a live
        region corrupts it. Convert and boot are sequential phases, so the
        two never overlap.
        """
        if not text:
            return
        self.console.file.write(text)
        self.console.file.flush()
        # A trailing CR leaves the cursor at column 0 just as LF does, so the
        # next renderable may start there (overwriting the guest's line, which
        # is what the guest asked for by emitting CR).
        self._at_line_start = text.endswith(("\n", "\r"))

    def message(self, text: str, *, level: int = logging.INFO) -> None:
        """Render one attributable cloudimg-seeder line."""
        if not self.show_steps:
            return
        marker, style = _LEVEL_RENDERING.get(level, (_STEP_MARKER, "seeder.step"))
        self._ensure_line_start()
        self.console.print(Text(f"{marker} {text}", style=style))
        self._at_line_start = True

    def error(self, text: str) -> None:
        """Render a fatal error. Always shown, even when steps are muted."""
        self._ensure_line_start()
        self.console.print(Text(f"{_ERROR_MARKER} {text}", style="seeder.error"))
        self._at_line_start = True

    def new_progress(self) -> Progress:
        """An unstarted percent bar, inert when stderr is not a terminal."""
        return Progress(
            TextColumn("  {task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
            disable=not self.console.is_terminal or not self.show_steps,
        )

    def start_progress(self) -> Progress:
        """Begin a live progress region on a fresh line."""
        self._ensure_line_start()
        bar = self.new_progress()
        bar.start()
        return bar

    def stop_progress(self, bar: Progress) -> None:
        """End a live progress region; it erases itself and leaves column 0."""
        bar.stop()
        self._at_line_start = True


@dataclass
class RichProgressSink:
    """``ProgressSink`` backed by a Rich progress bar."""

    ui: Ui
    _bar: Progress | None = field(default=None, init=False, repr=False)
    _task: TaskID | None = field(default=None, init=False, repr=False)

    def start(self, label: str) -> None:
        bar = self.ui.start_progress()
        self._bar = bar
        self._task = bar.add_task(label, total=100.0)

    def advance(self, percent: float) -> None:
        if self._bar is None or self._task is None:
            return
        self._bar.update(self._task, completed=percent)

    def finish(self) -> None:
        if self._bar is not None:
            self.ui.stop_progress(self._bar)
        self._bar = None
        self._task = None


class StepHandler(logging.Handler):
    """Render log records as attributable cloudimg-seeder lines.

    Keeps library modules on plain ``logging`` while presentation stays here.
    Messages are rendered via ``Text``, so a record containing a bracketed
    path is shown literally instead of being parsed as markup.
    """

    def __init__(self, ui: Ui, level: int = logging.NOTSET) -> None:
        super().__init__(level=level)
        self.ui = ui

    @override
    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.ui.message(record.getMessage(), level=record.levelno)
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)
