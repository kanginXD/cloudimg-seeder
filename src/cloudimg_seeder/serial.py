"""Guest serial connection: decode, match cloud-init completion, feed display."""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import re
from dataclasses import dataclass

from cloudimg_seeder.console.display import SerialDisplay
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.transport import Endpoint

# Matches cloud-init's default final_message ("Cloud-init v. {version}
# finished at {timestamp}. Datasource {datasource}.  Up {uptime} seconds").
# A custom final_message in user-data is not matched; --timeout-sec bounds
# the wait in that case.
CLOUD_INIT_FINISHED = re.compile(r"Cloud-init v\..*finished at", re.IGNORECASE)

_CONNECT_ATTEMPTS = 50
_CONNECT_DELAY_SEC = 0.1
# Cap on the buffered, not-yet-newline-terminated tail: bounds memory if the
# guest emits an unbroken stream with no newlines.
_LINE_BUF_MAX = 8192


@dataclass
class SerialSession:
    """Read guest serial until cloud-init finishes; feed ``display``."""

    endpoint: Endpoint
    process: asyncio.subprocess.Process
    display: SerialDisplay
    connect_attempts: int = _CONNECT_ATTEMPTS
    connect_delay_sec: float = _CONNECT_DELAY_SEC

    async def run(self) -> None:
        reader, writer = await self._open()
        # Per-session: a chunk boundary can split a multi-byte character, and
        # an incremental decoder is the only way to carry that half-decoded
        # tail to the next read instead of corrupting it.
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        buf = ""
        try:
            while True:
                self._ensure_running()
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=1.0)
                except TimeoutError:
                    continue
                if not chunk:
                    self._ensure_running()
                    await asyncio.sleep(0.1)
                    continue
                text = decoder.decode(chunk)
                self.display.write(text)
                buf += text
                if CLOUD_INIT_FINISHED.search(buf):
                    return
                newline = buf.rfind("\n")
                if newline != -1:
                    buf = buf[newline + 1 :]
                elif len(buf) > _LINE_BUF_MAX:
                    buf = buf[-_LINE_BUF_MAX:]
        finally:
            tail = decoder.decode(b"", final=True)
            if tail:
                self.display.write(tail)
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    def _ensure_running(self) -> None:
        if self.process.returncode is not None:
            raise QemuError(
                "QEMU exited before cloud-init finished (see serial output above)"
            )

    async def _open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        for _ in range(self.connect_attempts):
            if self.process.returncode is not None:
                raise QemuError("QEMU exited before serial was ready")
            try:
                return await self.endpoint.open()
            except OSError:
                await asyncio.sleep(self.connect_delay_sec)
        raise QemuError(f"serial not ready ({self.endpoint.address})")
