"""Tests for SerialSession."""

from __future__ import annotations

import asyncio
from io import StringIO
from unittest.mock import MagicMock

import pytest

from cloudimg_seeder.console.display import SerialDisplay
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.serial import CLOUD_INIT_FINISHED, SerialSession


def test_cloud_init_finished_regex() -> None:
    assert CLOUD_INIT_FINISHED.search("Cloud-init v. 24.1 finished")
    assert CLOUD_INIT_FINISHED.search("cloud-init has finished")
    assert CLOUD_INIT_FINISHED.search("still booting") is None


@pytest.mark.asyncio
async def test_session_detects_finished(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = asyncio.StreamReader()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = MagicMock(return_value=asyncio.sleep(0))

    async def fake_open(host: str, port: int) -> tuple[object, object]:
        reader.feed_data(b"Cloud-init v. 24 finished at ...\n")
        reader.feed_eof()
        return reader, writer

    monkeypatch.setattr(
        "cloudimg_seeder.serial.asyncio.open_connection",
        fake_open,
    )
    process = MagicMock()
    process.returncode = None
    buf = StringIO()
    display = SerialDisplay(quiet=False, ansi_capable=True, stream=buf)
    session = SerialSession(port=5555, process=process, display=display)
    await session.run()
    assert "Cloud-init" in buf.getvalue()
    display.close()


@pytest.mark.asyncio
async def test_session_process_dies_before_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_open(host: str, port: int) -> tuple[object, object]:
        raise OSError("refused")

    monkeypatch.setattr(
        "cloudimg_seeder.serial.asyncio.open_connection",
        fake_open,
    )
    process = MagicMock()
    process.returncode = 1
    display = SerialDisplay(quiet=True, ansi_capable=True, stream=StringIO())
    session = SerialSession(
        port=5555,
        process=process,
        display=display,
        connect_attempts=2,
        connect_delay_sec=0,
    )
    with pytest.raises(QemuError, match="before serial"):
        await session.run()
