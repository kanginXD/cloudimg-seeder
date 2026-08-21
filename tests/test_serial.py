"""Tests for SerialSession."""

from __future__ import annotations

import asyncio
import io
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from cloudimg_seeder.console.display import SerialDisplay
from cloudimg_seeder.console.ui import Ui
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.serial import (
    CLOUD_INIT_FINISHED,
    IdleTimeoutError,
    SerialSession,
    StatusSession,
)
from cloudimg_seeder.transport import TcpEndpoint
from tests.support import ScriptedReader


def _ui() -> tuple[Ui, io.StringIO]:
    buf = io.StringIO()
    return Ui(console=Console(file=buf, width=60)), buf


_FINAL_MESSAGE = (
    "Cloud-init v. 24.1.3 finished at Tue, 01 Jan 2024 00:00:00 +0000. "
    "Datasource DataSourceNoCloud.  Up 12.34 seconds"
)


def test_cloud_init_finished_regex() -> None:
    assert CLOUD_INIT_FINISHED.search(_FINAL_MESSAGE)
    assert CLOUD_INIT_FINISHED.search("still booting") is None
    # A custom final_message overriding the default is not matched; the
    # status probe (see probe.py) is the primary completion signal, so this
    # only means status is reported as unknown if the probe is unavailable.
    assert CLOUD_INIT_FINISHED.search("cloud-init has finished") is None


@pytest.mark.asyncio
async def test_session_detects_finished(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = asyncio.StreamReader()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = MagicMock(return_value=asyncio.sleep(0))

    async def fake_open(host: str, port: int) -> tuple[object, object]:
        reader.feed_data(_FINAL_MESSAGE.encode())
        reader.feed_eof()
        return reader, writer

    monkeypatch.setattr(
        "cloudimg_seeder.transport.asyncio.open_connection",
        fake_open,
    )
    process = MagicMock()
    process.returncode = None
    ui, buf = _ui()
    display = SerialDisplay(ui=ui)
    session = SerialSession(
        endpoint=TcpEndpoint(5555), process=process, display=display
    )
    await session.run()
    assert "Cloud-init" in buf.getvalue()
    display.close()


@pytest.mark.asyncio
async def test_multibyte_split_across_reads_is_not_corrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: chunk.decode(errors="replace") corrupted a character split
    across two reads instead of carrying its bytes to the next one."""
    text = "부팅 완료 ✓\n"
    raw = text.encode("utf-8")
    split = 5  # lands inside a multi-byte character, not on its boundary
    chunk_a, chunk_b = raw[:split], raw[split:] + _FINAL_MESSAGE.encode()
    reader = ScriptedReader([chunk_a, chunk_b])
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = MagicMock(return_value=asyncio.sleep(0))

    async def fake_open(host: str, port: int) -> tuple[object, object]:
        return reader, writer

    monkeypatch.setattr("cloudimg_seeder.transport.asyncio.open_connection", fake_open)
    process = MagicMock()
    process.returncode = None
    ui, buf = _ui()
    display = SerialDisplay(ui=ui)
    session = SerialSession(
        endpoint=TcpEndpoint(5555), process=process, display=display
    )
    await session.run()
    display.close()
    assert text in buf.getvalue()
    assert "�" not in buf.getvalue()


@pytest.mark.asyncio
async def test_settle_keeps_reading_after_the_console_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the run ended on the match itself, so the rest of
    cloud-init's final line was never read."""
    head, tail = _FINAL_MESSAGE.split("finished at", 1)
    head += "finished at"
    reader = asyncio.StreamReader()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = MagicMock(return_value=asyncio.sleep(0))

    async def feed_tail() -> None:
        await asyncio.sleep(0.05)
        reader.feed_data(tail.encode())
        reader.feed_eof()

    async def fake_open(host: str, port: int) -> tuple[object, object]:
        reader.feed_data(head.encode())
        asyncio.get_running_loop().create_task(feed_tail())
        return reader, writer

    monkeypatch.setattr("cloudimg_seeder.transport.asyncio.open_connection", fake_open)
    process = MagicMock()
    process.returncode = None
    ui, buf = _ui()
    display = SerialDisplay(ui=ui)
    session = SerialSession(
        endpoint=TcpEndpoint(5555), process=process, display=display
    )
    await session.run()
    display.close()
    assert "Up 12.34 seconds" in buf.getvalue()


@pytest.mark.asyncio
async def test_request_stop_settles_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = asyncio.StreamReader()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = MagicMock(return_value=asyncio.sleep(0))

    async def fake_open(host: str, port: int) -> tuple[object, object]:
        reader.feed_data(b"still writing when the probe reported\n")
        reader.feed_eof()
        return reader, writer

    monkeypatch.setattr("cloudimg_seeder.transport.asyncio.open_connection", fake_open)
    process = MagicMock()
    process.returncode = None
    ui, buf = _ui()
    display = SerialDisplay(ui=ui)
    session = SerialSession(
        endpoint=TcpEndpoint(5555), process=process, display=display
    )
    session.request_stop()
    await session.run()
    display.close()
    assert "still writing when the probe reported" in buf.getvalue()


@pytest.mark.asyncio
async def test_truncated_tail_is_flushed_at_end_of_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    truncated = "부".encode()[:1]  # one byte of a three-byte character
    reader = ScriptedReader([_FINAL_MESSAGE.encode() + truncated])
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = MagicMock(return_value=asyncio.sleep(0))

    async def fake_open(host: str, port: int) -> tuple[object, object]:
        return reader, writer

    monkeypatch.setattr("cloudimg_seeder.transport.asyncio.open_connection", fake_open)
    process = MagicMock()
    process.returncode = None
    ui, buf = _ui()
    display = SerialDisplay(ui=ui)
    session = SerialSession(
        endpoint=TcpEndpoint(5555), process=process, display=display
    )
    await session.run()
    display.close()
    assert "seconds�" in buf.getvalue()


@pytest.mark.asyncio
async def test_session_process_dies_before_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_open(host: str, port: int) -> tuple[object, object]:
        raise OSError("refused")

    monkeypatch.setattr(
        "cloudimg_seeder.transport.asyncio.open_connection",
        fake_open,
    )
    process = MagicMock()
    process.returncode = 1
    ui, _buf = _ui()
    display = SerialDisplay(ui=ui, show_serial=False)
    session = SerialSession(
        endpoint=TcpEndpoint(5555),
        process=process,
        display=display,
        connect_attempts=2,
        connect_delay_sec=0,
    )
    with pytest.raises(QemuError, match="before serial"):
        await session.run()


@pytest.mark.asyncio
async def test_idle_timeout_raises_when_no_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = ScriptedReader([])  # every read() returns b""
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = MagicMock(return_value=asyncio.sleep(0))

    async def fake_open(host: str, port: int) -> tuple[object, object]:
        return reader, writer

    monkeypatch.setattr("cloudimg_seeder.transport.asyncio.open_connection", fake_open)
    process = MagicMock()
    process.returncode = None
    ui, _buf = _ui()
    display = SerialDisplay(ui=ui, show_serial=False)
    session = SerialSession(
        endpoint=TcpEndpoint(5555),
        process=process,
        display=display,
        idle_timeout_sec=0.05,
    )
    with pytest.raises(IdleTimeoutError, match="no guest output"):
        await session.run()


@pytest.mark.asyncio
async def test_idle_timeout_none_waits_through_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = ScriptedReader([b"", b"", _FINAL_MESSAGE.encode()])
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = MagicMock(return_value=asyncio.sleep(0))

    async def fake_open(host: str, port: int) -> tuple[object, object]:
        return reader, writer

    monkeypatch.setattr("cloudimg_seeder.transport.asyncio.open_connection", fake_open)
    process = MagicMock()
    process.returncode = None
    ui, buf = _ui()
    display = SerialDisplay(ui=ui)
    session = SerialSession(
        endpoint=TcpEndpoint(5555), process=process, display=display
    )
    await session.run()
    assert "Cloud-init" in buf.getvalue()
    display.close()


@pytest.mark.asyncio
async def test_status_session_returns_probe_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = ScriptedReader([b"cloudimg-seeder-status 0\n"])
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = MagicMock(return_value=asyncio.sleep(0))

    async def fake_open(host: str, port: int) -> tuple[object, object]:
        return reader, writer

    monkeypatch.setattr("cloudimg_seeder.transport.asyncio.open_connection", fake_open)
    process = MagicMock()
    process.returncode = None
    session = StatusSession(endpoint=TcpEndpoint(5555), process=process)
    assert await session.run() == 0


@pytest.mark.asyncio
async def test_status_session_sentinel_split_across_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    line = b"cloudimg-seeder-status 2\n"
    split = 10
    reader = ScriptedReader([line[:split], line[split:]])
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = MagicMock(return_value=asyncio.sleep(0))

    async def fake_open(host: str, port: int) -> tuple[object, object]:
        return reader, writer

    monkeypatch.setattr("cloudimg_seeder.transport.asyncio.open_connection", fake_open)
    process = MagicMock()
    process.returncode = None
    session = StatusSession(endpoint=TcpEndpoint(5555), process=process)
    assert await session.run() == 2


@pytest.mark.asyncio
async def test_status_session_returns_none_when_guest_exits_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_open(host: str, port: int) -> tuple[object, object]:
        raise OSError("refused")

    monkeypatch.setattr("cloudimg_seeder.transport.asyncio.open_connection", fake_open)
    process = MagicMock()
    process.returncode = 0
    session = StatusSession(
        endpoint=TcpEndpoint(5555),
        process=process,
        connect_attempts=2,
        connect_delay_sec=0,
    )
    assert await session.run() is None
