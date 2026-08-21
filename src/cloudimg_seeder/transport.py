"""Local transport endpoints for QMP and guest serial connections."""

from __future__ import annotations

import asyncio
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Historical maximum sun_path length across BSD/Linux; using the smaller
# bound keeps a fallback margin.
_UNIX_PATH_MAX = 104


class Endpoint(Protocol):
    """One QEMU chardev endpoint (a QMP or serial connection point)."""

    @property
    def qemu_arg(self) -> str:
        """Value for a QEMU ``-qmp``/``-serial`` chardev address."""
        ...

    @property
    def address(self) -> str | tuple[str, int]:
        """Address accepted by ``QMPClient.connect()`` and used in messages."""
        ...

    async def open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Connect as a client and return a reader/writer pair."""
        ...


@dataclass(frozen=True)
class UnixEndpoint:
    """Unix domain socket endpoint, private to the owning temp directory."""

    path: Path

    @property
    def qemu_arg(self) -> str:
        return f"unix:{self.path},server=on,wait=off"

    @property
    def address(self) -> str:
        return str(self.path)

    async def open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_unix_connection(str(self.path))


@dataclass(frozen=True)
class TcpEndpoint:
    """Loopback TCP endpoint, used where AF_UNIX is unavailable."""

    port: int

    @property
    def qemu_arg(self) -> str:
        return f"tcp:127.0.0.1:{self.port},server=on,wait=off"

    @property
    def address(self) -> tuple[str, int]:
        return ("127.0.0.1", self.port)

    async def open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_connection("127.0.0.1", self.port)


@dataclass(frozen=True)
class GuestEndpoints:
    qmp: Endpoint
    serial: Endpoint


def _allocate_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _unix_endpoint(workdir: Path, name: str) -> UnixEndpoint | None:
    path = workdir / name
    if len(str(path).encode()) >= _UNIX_PATH_MAX:
        return None
    return UnixEndpoint(path)


def allocate_endpoints(workdir: Path) -> GuestEndpoints:
    """Allocate QMP and serial endpoints for one guest run.

    Unix sockets under ``workdir`` on POSIX: the directory is private to
    this process (mode 0700), so no other local user can reach QMP or the
    guest serial console. Falls back to loopback TCP when ``workdir`` would
    push the socket path past ``sun_path``, and always on Windows, where
    QEMU has no reliable AF_UNIX support.
    """
    if sys.platform != "win32":
        qmp = _unix_endpoint(workdir, "qmp.sock")
        serial = _unix_endpoint(workdir, "serial.sock")
        if qmp is not None and serial is not None:
            return GuestEndpoints(qmp=qmp, serial=serial)
    return GuestEndpoints(
        qmp=TcpEndpoint(_allocate_tcp_port()),
        serial=TcpEndpoint(_allocate_tcp_port()),
    )
