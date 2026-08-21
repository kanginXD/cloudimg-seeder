"""Tests for QMP/serial endpoint allocation."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cloudimg_seeder import transport
from cloudimg_seeder.transport import TcpEndpoint, UnixEndpoint, allocate_endpoints


def test_posix_uses_unix_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport.sys, "platform", "linux")
    # A directory shaped like seed()'s real workdir, not pytest's tmp_path:
    # tmp_path nests several extra components under the OS temp root
    # (pytest-of-<user>/pytest-<n>/<test-name><n>) and can itself exceed
    # AF_UNIX's sun_path limit on macOS, which would make this test exercise
    # the TCP fallback instead of the Unix-socket path it exists to cover.
    with tempfile.TemporaryDirectory(prefix="cloudimg-seeder-") as workdir:
        endpoints = allocate_endpoints(Path(workdir))
        assert isinstance(endpoints.qmp, UnixEndpoint)
        assert isinstance(endpoints.serial, UnixEndpoint)
        assert isinstance(endpoints.status, UnixEndpoint)
        assert endpoints.qmp.path.parent == Path(workdir)
        assert (
            len({endpoints.qmp.path, endpoints.serial.path, endpoints.status.path}) == 3
        )


def test_windows_uses_tcp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport.sys, "platform", "win32")
    ports = iter([1111, 2222, 3333])
    monkeypatch.setattr(transport, "_allocate_tcp_port", lambda: next(ports))
    endpoints = allocate_endpoints(tmp_path)
    assert isinstance(endpoints.qmp, TcpEndpoint)
    assert isinstance(endpoints.serial, TcpEndpoint)
    assert isinstance(endpoints.status, TcpEndpoint)
    assert len({endpoints.qmp.port, endpoints.serial.port, endpoints.status.port}) == 3


def test_falls_back_to_tcp_when_path_too_long(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transport.sys, "platform", "linux")
    ports = iter([3333, 4444, 5555])
    monkeypatch.setattr(transport, "_allocate_tcp_port", lambda: next(ports))
    deep = tmp_path / ("x" * 200)
    endpoints = allocate_endpoints(deep)
    assert isinstance(endpoints.qmp, TcpEndpoint)
    assert isinstance(endpoints.serial, TcpEndpoint)
    assert isinstance(endpoints.status, TcpEndpoint)


def test_unix_endpoint_qemu_arg(tmp_path: Path) -> None:
    endpoint = UnixEndpoint(tmp_path / "qmp.sock")
    assert endpoint.qemu_arg == f"unix:{tmp_path / 'qmp.sock'},server=on,wait=off"
    assert endpoint.address == str(tmp_path / "qmp.sock")


def test_unix_endpoint_chardev_arg(tmp_path: Path) -> None:
    endpoint = UnixEndpoint(tmp_path / "status.sock")
    assert endpoint.chardev_arg("cistatus") == (
        f"socket,id=cistatus,path={tmp_path / 'status.sock'},server=on,wait=off"
    )


def test_tcp_endpoint_qemu_arg() -> None:
    endpoint = TcpEndpoint(4444)
    assert endpoint.qemu_arg == "tcp:127.0.0.1:4444,server=on,wait=off"
    assert endpoint.address == ("127.0.0.1", 4444)


def test_tcp_endpoint_chardev_arg() -> None:
    endpoint = TcpEndpoint(4444)
    assert endpoint.chardev_arg("cistatus") == (
        "socket,id=cistatus,host=127.0.0.1,port=4444,server=on,wait=off"
    )


@pytest.mark.asyncio
async def test_tcp_endpoint_open_uses_open_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_open_connection(host: str, port: int) -> tuple[str, str]:
        calls.append((host, port))
        return "reader", "writer"

    monkeypatch.setattr(transport.asyncio, "open_connection", fake_open_connection)
    result = await TcpEndpoint(4444).open()
    assert calls == [("127.0.0.1", 4444)]
    assert result == ("reader", "writer")


@pytest.mark.asyncio
async def test_unix_endpoint_open_uses_open_unix_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def fake_open_unix_connection(path: str) -> tuple[str, str]:
        calls.append(path)
        return "reader", "writer"

    monkeypatch.setattr(
        transport.asyncio, "open_unix_connection", fake_open_unix_connection
    )
    sock_path = tmp_path / "x.sock"
    result = await UnixEndpoint(sock_path).open()
    assert calls == [str(sock_path)]
    assert result == ("reader", "writer")
