"""Tests for guest argv construction."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.guest import (
    GuestFirmware,
    GuestPorts,
    allocate_localhost_ports,
    build_qemu_argv,
    run_headless_qemu,
)
from cloudimg_seeder.serial import CLOUD_INIT_FINISHED


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


def test_cloud_init_reexport() -> None:
    assert CLOUD_INIT_FINISHED.search("cloud-init has finished")


@pytest.mark.asyncio
async def test_run_headless_drains_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drained: list[bool] = []

    def fake_drain() -> None:
        drained.append(True)

    monkeypatch.setattr("cloudimg_seeder.guest.drain_stdin", fake_drain)
    monkeypatch.setattr(
        "cloudimg_seeder.guest.allocate_localhost_ports",
        lambda: GuestPorts(qmp=1, serial=2),
    )

    def fake_accel(_arch: GuestArch) -> str:
        return "tcg"

    def fake_binary(_name: str) -> str:
        return "qemu-system-x86_64"

    def fake_argv(**_kwargs: object) -> list[str]:
        return ["true"]

    monkeypatch.setattr("cloudimg_seeder.guest.accel_for_guest", fake_accel)
    monkeypatch.setattr("cloudimg_seeder.guest.find_qemu_binary", fake_binary)
    monkeypatch.setattr("cloudimg_seeder.guest.build_qemu_argv", fake_argv)

    class Proc:
        returncode = 0

        def kill(self) -> None:
            return None

        async def wait(self) -> int:
            return 0

    async def fake_exec(*_a: object, **_k: object) -> Proc:
        return Proc()

    async def boom_boot(*_a: object, **_k: object) -> None:
        raise TimeoutError

    async def boom_qmp(*_a: object, **_k: object) -> None:
        raise OSError("qmp down")

    monkeypatch.setattr(
        "cloudimg_seeder.guest.asyncio.create_subprocess_exec",
        fake_exec,
    )
    monkeypatch.setattr(
        "cloudimg_seeder.guest._boot_until_shutdown",
        boom_boot,
    )
    monkeypatch.setattr(
        "cloudimg_seeder.guest.qmp_powerdown_and_wait",
        boom_qmp,
    )

    disk = tmp_path / "d.qcow2"
    iso = tmp_path / "s.iso"
    disk.write_bytes(b"x")
    iso.write_bytes(b"x")
    with pytest.raises(QemuError, match="timed out"):
        await run_headless_qemu(
            arch=GuestArch.AMD64,
            disk=disk,
            seed_iso=iso,
            workdir=tmp_path,
            cpus=1,
            memory_mb=512,
            timeout_sec=1,
            quiet=True,
        )
    assert drained == [True]
