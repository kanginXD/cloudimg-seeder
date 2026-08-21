"""Tests for the presentation-agnostic progress protocol."""

from __future__ import annotations

from cloudimg_seeder.progress import NullProgress, ProgressSink, progress_task


def test_null_progress_accepts_all_calls() -> None:
    sink = NullProgress()
    sink.start("converting")
    sink.advance(50.0)
    sink.finish()  # must not raise


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def start(self, label: str) -> None:
        self.events.append(("start", label))

    def advance(self, percent: float) -> None:
        self.events.append(("advance", percent))

    def finish(self) -> None:
        self.events.append(("finish", None))


def test_progress_task_brackets_start_and_finish() -> None:
    sink = _RecordingSink()
    with progress_task(sink, "converting to raw") as task:
        assert task is sink
        task.advance(42.0)
    assert sink.events == [
        ("start", "converting to raw"),
        ("advance", 42.0),
        ("finish", None),
    ]


def test_progress_task_finishes_even_on_exception() -> None:
    sink = _RecordingSink()
    try:
        with progress_task(sink, "converting"):
            raise ValueError("boom")
    except ValueError:
        pass
    assert sink.events[-1] == ("finish", None)


def test_recording_sink_satisfies_protocol() -> None:
    sink: ProgressSink = _RecordingSink()
    sink.start("x")
    sink.advance(1.0)
    sink.finish()
