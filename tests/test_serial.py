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
from cloudimg_seeder.serial import CLOUD_INIT_FINISHED, SerialSession
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
    # caller falls back to --timeout-sec in that case.
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
