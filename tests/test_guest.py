"""Tests for guest argv and serial cloud-init detection."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.guest import (
    CLOUD_INIT_FINISHED,
    GuestFirmware,
    GuestPorts,
    allocate_localhost_ports,
    build_qemu_argv,
    stream_serial_until_cloud_init,
)


def test_allocate_localhost_ports() -> None:
    ports = allocate_localhost_ports()
    assert ports.qmp > 0
    assert ports.serial > 0
    assert ports.qmp != ports.serial


def test_build_qemu_argv_arm64_native(tmp_path: Path) -> None:
    disk = tmp_path / "disk.qcow2"
    iso = tmp_path / "seed.iso"
    code = tmp_path / "code.fd"
    vars_fd = tmp_path / "vars.fd"
    for p in (disk, iso, code, vars_fd):
        p.write_bytes(b"x")
    argv = build_qemu_argv(
        arch=GuestArch.ARM64,
        disk=disk,
        seed_iso=iso,
        ports=GuestPorts(qmp=4444, serial=5555),
        cpus=2,
        memory_mb=2048,
        accel="hvf",
        binary="/usr/bin/qemu-system-aarch64",
        firmware=GuestFirmware(code=code, vars_store=vars_fd),
    )
    joined = " ".join(argv)
    assert argv[0] == "/usr/bin/qemu-system-aarch64"
    assert "virt,accel=hvf,highmem=on" in argv
    assert "tcp:127.0.0.1:5555,server=on,wait=off" in argv
    assert "tcp:127.0.0.1:4444,server=on,wait=off" in argv
    assert "if=pflash" in joined
    assert "unix:" not in joined


def test_build_qemu_argv_arm64_tcg(tmp_path: Path) -> None:
    disk = tmp_path / "disk.qcow2"
    iso = tmp_path / "seed.iso"
    code = tmp_path / "code.fd"
    vars_fd = tmp_path / "vars.fd"
    for p in (disk, iso, code, vars_fd):
        p.write_bytes(b"x")
    argv = build_qemu_argv(
        arch=GuestArch.ARM64,
        disk=disk,
        seed_iso=iso,
        ports=GuestPorts(qmp=1, serial=2),
        cpus=1,
        memory_mb=512,
        accel="tcg",
        binary="qemu-system-aarch64",
        firmware=GuestFirmware(code=code, vars_store=vars_fd),
    )
    assert "-accel" in argv
    assert "tcg" in argv
    assert "max" in argv


def test_build_qemu_argv_amd64_native(tmp_path: Path) -> None:
    disk = tmp_path / "disk.qcow2"
    iso = tmp_path / "seed.iso"
    disk.write_bytes(b"x")
    iso.write_bytes(b"x")
    argv = build_qemu_argv(
        arch=GuestArch.AMD64,
        disk=disk,
        seed_iso=iso,
        ports=GuestPorts(qmp=10, serial=20),
        cpus=4,
        memory_mb=1024,
        accel="kvm",
        binary="qemu-system-x86_64",
    )
    assert argv[0] == "qemu-system-x86_64"
    assert "q35" in argv
    assert "host" in argv
    assert "kvm" in argv


def test_build_qemu_argv_amd64_whpx(tmp_path: Path) -> None:
    disk = tmp_path / "disk.qcow2"
    iso = tmp_path / "seed.iso"
    disk.write_bytes(b"x")
    iso.write_bytes(b"x")
    argv = build_qemu_argv(
        arch=GuestArch.AMD64,
        disk=disk,
        seed_iso=iso,
        ports=GuestPorts(qmp=10, serial=20),
        cpus=2,
        memory_mb=1024,
        accel="whpx",
        binary="qemu-system-x86_64",
    )
    assert "whpx,kernel-irqchip=off" in argv


def test_build_qemu_argv_amd64_tcg(tmp_path: Path) -> None:
    disk = tmp_path / "disk.qcow2"
    iso = tmp_path / "seed.iso"
    disk.write_bytes(b"x")
    iso.write_bytes(b"x")
    argv = build_qemu_argv(
        arch=GuestArch.AMD64,
        disk=disk,
        seed_iso=iso,
        ports=GuestPorts(qmp=10, serial=20),
        cpus=2,
        memory_mb=1024,
        accel="tcg",
        binary="qemu-system-x86_64",
    )
    assert "qemu64" in argv


def test_build_qemu_argv_arm64_requires_firmware(tmp_path: Path) -> None:
    disk = tmp_path / "disk.qcow2"
    iso = tmp_path / "seed.iso"
    disk.write_bytes(b"x")
    iso.write_bytes(b"x")
    with pytest.raises(QemuError, match="firmware"):
        build_qemu_argv(
            arch=GuestArch.ARM64,
            disk=disk,
            seed_iso=iso,
            ports=GuestPorts(qmp=1, serial=2),
            cpus=1,
            memory_mb=512,
            accel="tcg",
            binary="qemu-system-aarch64",
            firmware=None,
        )


def test_build_qemu_argv_escapes_comma_in_path(tmp_path: Path) -> None:
    disk = tmp_path / "a,b.qcow2"
    iso = tmp_path / "seed.iso"
    disk.write_bytes(b"x")
    iso.write_bytes(b"x")
    argv = build_qemu_argv(
        arch=GuestArch.AMD64,
        disk=disk,
        seed_iso=iso,
        ports=GuestPorts(qmp=1, serial=2),
        cpus=1,
        memory_mb=512,
        accel="tcg",
        binary="qemu-system-x86_64",
    )
    drive_args = [a for a in argv if "file=" in a]
    assert any(",," in a for a in drive_args)


def test_cloud_init_finished_regex() -> None:
    assert CLOUD_INIT_FINISHED.search("Cloud-init v. 24.1 finished")
    assert CLOUD_INIT_FINISHED.search("cloud-init has finished")
    assert CLOUD_INIT_FINISHED.search("CLOUD-INIT HAS FINISHED") is not None
    assert CLOUD_INIT_FINISHED.search("still booting") is None


@pytest.mark.asyncio
async def test_stream_serial_detects_finished(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = asyncio.StreamReader()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = MagicMock(return_value=asyncio.sleep(0))

    async def fake_open(host: str, port: int) -> tuple[object, object]:
        reader.feed_data(b"Cloud-init v. 24 finished at ...\n")
        reader.feed_eof()
        return reader, writer

    monkeypatch.setattr("cloudimg_seeder.guest.asyncio.open_connection", fake_open)
    process = MagicMock()
    process.returncode = None
    await stream_serial_until_cloud_init(5555, process)


@pytest.mark.asyncio
async def test_stream_serial_process_dies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_open(host: str, port: int) -> tuple[object, object]:
        raise OSError("refused")

    monkeypatch.setattr("cloudimg_seeder.guest.asyncio.open_connection", fake_open)
    monkeypatch.setattr("cloudimg_seeder.guest._CONNECT_ATTEMPTS", 2)
    monkeypatch.setattr("cloudimg_seeder.guest._CONNECT_DELAY_SEC", 0)
    process = MagicMock()
    process.returncode = 1
    with pytest.raises(QemuError, match="before serial"):
        await stream_serial_until_cloud_init(5555, process)
