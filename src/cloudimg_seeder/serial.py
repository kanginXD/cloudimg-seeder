"""Guest serial TCP session: decode, match cloud-init, feed display."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from cloudimg_seeder.console.display import SerialDisplay
from cloudimg_seeder.errors import QemuError

CLOUD_INIT_FINISHED = re.compile(
    r"Cloud-init.*finished|cloud-init has finished",
    re.IGNORECASE,
)

_CONNECT_ATTEMPTS = 50
_CONNECT_DELAY_SEC = 0.1
_MATCH_BUF_MAX = 1_000_000
_MATCH_BUF_KEEP = 500_000


@dataclass
class SerialSession:
    """Read guest serial until cloud-init finishes; feed ``display``."""

    port: int
    process: asyncio.subprocess.Process
    display: SerialDisplay
    connect_attempts: int = _CONNECT_ATTEMPTS
    connect_delay_sec: float = _CONNECT_DELAY_SEC

    async def run(self) -> None:
        reader, writer = await self._open()
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
                text = chunk.decode(errors="replace")
                self.display.write(text)
                buf += text
                if CLOUD_INIT_FINISHED.search(buf):
                    return
                if len(buf) > _MATCH_BUF_MAX:
                    buf = buf[-_MATCH_BUF_KEEP:]
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

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
                return await asyncio.open_connection("127.0.0.1", self.port)
            except OSError:
                await asyncio.sleep(self.connect_delay_sec)
        raise QemuError(f"serial not ready on 127.0.0.1:{self.port}")
