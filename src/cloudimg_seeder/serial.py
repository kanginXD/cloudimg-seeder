"""Guest serial connection: decode, match cloud-init completion, feed display."""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import re
import time
from dataclasses import dataclass, field

from cloudimg_seeder.console.display import SerialDisplay
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.probe import STATUS_LINE
from cloudimg_seeder.transport import Endpoint

# Matches cloud-init's default final_message ("Cloud-init v. {version}
# finished at {timestamp}. Datasource {datasource}.  Up {uptime} seconds").
# A custom final_message in user-data is not matched; this is only the
# fallback signal when the status probe (see probe.py) is unavailable.
CLOUD_INIT_FINISHED = re.compile(r"Cloud-init v\..*finished at", re.IGNORECASE)

_CONNECT_ATTEMPTS = 50
_CONNECT_DELAY_SEC = 0.1
# After completion is signalled the guest is still writing: the tail of
# cloud-init's final line arrives after the signal that matched it. Reading
# continues until the console falls quiet for this long, bounded by
# _SETTLE_MAX_SEC in case the guest keeps talking.
_SETTLE_QUIET_SEC = 0.3
_SETTLE_MAX_SEC = 2.0
# Cap on the buffered, not-yet-newline-terminated tail: bounds memory if the
# guest emits an unbroken stream with no newlines.
_LINE_BUF_MAX = 8192


class IdleTimeoutError(QemuError):
    """No guest serial output for longer than ``idle_timeout_sec``.

    QEMU is presumably still running, unlike the other QemuError cases
    raised from this module: the caller needs to distinguish this to force
    a quit rather than treat it as an already-dead guest.
    """


@dataclass
class SerialSession:
    """Read guest serial until cloud-init finishes; feed ``display``.

    ``idle_timeout_sec`` bounds consecutive silence on the console, not
    total run time: it resets on every non-empty read. ``None`` waits
    indefinitely.

    Reading ends on a completion signal: a console match of
    ``CLOUD_INIT_FINISHED``, or ``request_stop`` from a caller holding its
    own signal. Either signal is followed by a settle pass that drains what
    the guest is still writing. Callers must stop the session through
    ``request_stop`` rather than cancelling the task, which would truncate
    the console mid-line.
    """

    endpoint: Endpoint
    process: asyncio.subprocess.Process
    display: SerialDisplay
    idle_timeout_sec: float | None = None
    connect_attempts: int = _CONNECT_ATTEMPTS
    connect_delay_sec: float = _CONNECT_DELAY_SEC
    settle_quiet_sec: float = _SETTLE_QUIET_SEC
    settle_max_sec: float = _SETTLE_MAX_SEC
    _stop: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)

    def request_stop(self) -> None:
        """Ask ``run`` to settle and return; safe to call before ``run``."""
        self._stop.set()

    async def run(self) -> None:
        reader, writer = await self._open()
        # Per-session: a chunk boundary can split a multi-byte character, and
        # an incremental decoder is the only way to carry that half-decoded
        # tail to the next read instead of corrupting it.
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        buf = ""
        last_activity = time.monotonic()
        try:
            while True:
                self._ensure_running()
                if self._stop.is_set():
                    await self._settle(reader, decoder)
                    return
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=1.0)
                except TimeoutError:
                    self._check_idle(last_activity)
                    continue
                if not chunk:
                    self._ensure_running()
                    self._check_idle(last_activity)
                    await asyncio.sleep(0.1)
                    continue
                last_activity = time.monotonic()
                text = decoder.decode(chunk)
                self.display.write(text)
                buf += text
                if CLOUD_INIT_FINISHED.search(buf):
                    await self._settle(reader, decoder)
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

    async def _settle(
        self,
        reader: asyncio.StreamReader,
        decoder: codecs.IncrementalDecoder,
    ) -> None:
        """Drain what the guest writes after completion, then return.

        Ends on ``settle_quiet_sec`` of silence, on end of stream, on guest
        exit, or after ``settle_max_sec`` overall. The idle timeout does not
        apply here: silence is the expected outcome.
        """
        deadline = time.monotonic() + self.settle_max_sec
        while True:
            if self.process.returncode is not None:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                chunk = await asyncio.wait_for(
                    reader.read(4096),
                    timeout=min(self.settle_quiet_sec, remaining),
                )
            except TimeoutError:
                return
            if not chunk:
                return
            self.display.write(decoder.decode(chunk))

    def _check_idle(self, last_activity: float) -> None:
        if self.idle_timeout_sec is None:
            return
        idle_for = time.monotonic() - last_activity
        if idle_for >= self.idle_timeout_sec:
            raise IdleTimeoutError(f"no guest output for {int(idle_for)}s")

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


@dataclass
class StatusSession:
    """Read the guest status channel for the probe's exit-code sentinel.

    Returns the ``cloud-init status --wait`` exit code once the guest probe
    (see ``probe.py``) writes it. Returns ``None`` if the connection or the
    QEMU process ends first, meaning the probe never ran or never finished.
    """

    endpoint: Endpoint
    process: asyncio.subprocess.Process
    connect_attempts: int = _CONNECT_ATTEMPTS
    connect_delay_sec: float = _CONNECT_DELAY_SEC

    async def run(self) -> int | None:
        try:
            reader, writer = await self._open()
        except QemuError:
            return None
        try:
            buf = b""
            while True:
                if self.process.returncode is not None:
                    return None
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=1.0)
                except TimeoutError:
                    continue
                if not chunk:
                    if self.process.returncode is not None:
                        return None
                    await asyncio.sleep(0.1)
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    match = STATUS_LINE.match(line.strip())
                    if match:
                        return int(match.group(1))
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def _open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        for _ in range(self.connect_attempts):
            if self.process.returncode is not None:
                raise QemuError("QEMU exited before status channel was ready")
            try:
                return await self.endpoint.open()
            except OSError:
                await asyncio.sleep(self.connect_delay_sec)
        raise QemuError(f"status channel not ready ({self.endpoint.address})")
