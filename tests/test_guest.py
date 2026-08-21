"""Tests for guest argv construction and lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.console import SerialOptions
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.guest import GuestFirmware, build_qemu_argv, run_headless_qemu
from cloudimg_seeder.serial import CLOUD_INIT_FINISHED
from cloudimg_seeder.transport import GuestEndpoints, TcpEndpoint


def _endpoints(qmp: int, serial: int) -> GuestEndpoints:
    return GuestEndpoints(qmp=TcpEndpoint(qmp), serial=TcpEndpoint(serial))


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
        endpoints=_endpoints(qmp=4444, serial=5555),
        cpus=2,
        memory_mb=2048,
        accel="hvf",
        binary="/usr/bin/qemu-system-aarch64",
        firmware=GuestFirmware(code=code, vars_store=vars_fd),
    )
    joined = " ".join(argv)
    assert argv[0] == "/usr/bin/qemu-system-aarch64"
    assert "virt,accel=hvf" in argv
    assert "tcp:127.0.0.1:5555,server=on,wait=off" in argv
    assert "tcp:127.0.0.1:4444,server=on,wait=off" in argv
    assert "if=pflash" in joined
    assert "highmem" not in joined
    assert "kernel-irqchip" not in joined
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
        endpoints=_endpoints(qmp=1, serial=2),
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
        endpoints=_endpoints(qmp=10, serial=20),
        cpus=4,
        memory_mb=1024,
        accel="kvm",
        binary="qemu-system-x86_64",
    )
    assert argv[0] == "qemu-system-x86_64"
    assert "q35" in argv
    assert "host" in argv
    assert "kvm" in argv


def test_build_qemu_argv_amd64_whpx_no_irqchip_override(tmp_path: Path) -> None:
    disk = tmp_path / "disk.qcow2"
    iso = tmp_path / "seed.iso"
    disk.write_bytes(b"x")
    iso.write_bytes(b"x")
    argv = build_qemu_argv(
        arch=GuestArch.AMD64,
        disk=disk,
        seed_iso=iso,
        endpoints=_endpoints(qmp=10, serial=20),
        cpus=2,
        memory_mb=1024,
        accel="whpx",
        binary="qemu-system-x86_64",
    )
    assert "whpx" in argv
    assert "kernel-irqchip" not in " ".join(argv)


def test_build_qemu_argv_amd64_tcg_uses_cpu_max(tmp_path: Path) -> None:
    disk = tmp_path / "disk.qcow2"
    iso = tmp_path / "seed.iso"
    disk.write_bytes(b"x")
    iso.write_bytes(b"x")
    argv = build_qemu_argv(
        arch=GuestArch.AMD64,
        disk=disk,
        seed_iso=iso,
        endpoints=_endpoints(qmp=10, serial=20),
        cpus=2,
        memory_mb=1024,
        accel="tcg",
        binary="qemu-system-x86_64",
    )
    assert "max" in argv
    assert "qemu64" not in argv


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
            endpoints=_endpoints(qmp=1, serial=2),
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
        endpoints=_endpoints(qmp=1, serial=2),
        cpus=1,
        memory_mb=512,
        accel="tcg",
        binary="qemu-system-x86_64",
    )
    drive_args = [a for a in argv if "file=" in a]
    assert any(",," in a for a in drive_args)


def test_build_qemu_argv_uses_unix_endpoints(tmp_path: Path) -> None:
    from cloudimg_seeder.transport import UnixEndpoint

    disk = tmp_path / "disk.qcow2"
    iso = tmp_path / "seed.iso"
    disk.write_bytes(b"x")
    iso.write_bytes(b"x")
    endpoints = GuestEndpoints(
        qmp=UnixEndpoint(tmp_path / "qmp.sock"),
        serial=UnixEndpoint(tmp_path / "serial.sock"),
    )
    argv = build_qemu_argv(
        arch=GuestArch.AMD64,
        disk=disk,
        seed_iso=iso,
        endpoints=endpoints,
        cpus=1,
        memory_mb=512,
        accel="tcg",
        binary="qemu-system-x86_64",
    )
    joined = " ".join(argv)
    assert f"unix:{tmp_path / 'qmp.sock'}" in joined
    assert f"unix:{tmp_path / 'serial.sock'}" in joined
    assert "tcp:" not in joined


def test_cloud_init_reexport() -> None:
    assert CLOUD_INIT_FINISHED.search("Cloud-init v. 24.1 finished at Tue.")


@pytest.mark.asyncio
async def test_run_headless_drains_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drained: list[bool] = []

    def fake_drain() -> None:
        drained.append(True)

    monkeypatch.setattr("cloudimg_seeder.guest.drain_stdin", fake_drain)

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

    class TimingOutSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> None:
            raise TimeoutError

    async def boom_qmp(*_a: object, **_k: object) -> None:
        raise OSError("qmp down")

    monkeypatch.setattr(
        "cloudimg_seeder.guest.asyncio.create_subprocess_exec",
        fake_exec,
    )
    monkeypatch.setattr("cloudimg_seeder.guest.SerialSession", TimingOutSession)
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
            serial=SerialOptions(show_serial=False),
        )
    assert drained == [True]


@pytest.mark.asyncio
async def test_serial_region_closes_before_powerdown_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the powerdown step message used to be emitted while the
    guest-serial region was still open, so it landed inside the rules (and,
    after unterminated guest output, on the guest's own last line)."""
    import io
    import logging

    from rich.console import Console

    from cloudimg_seeder.console import SerialOptions
    from cloudimg_seeder.console.ui import StepHandler, Ui

    buf = io.StringIO()
    ui = Ui(console=Console(file=buf, width=70))
    logger = logging.getLogger("cloudimg_seeder")
    previous = logger.handlers[:]
    logger.handlers = [StepHandler(ui)]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    def no_drain() -> None:
        return None

    def tcg_accel(_arch: GuestArch) -> str:
        return "tcg"

    def x86_binary(_name: str) -> str:
        return "qemu-system-x86_64"

    def true_argv(**_kwargs: object) -> list[str]:
        return ["true"]

    monkeypatch.setattr("cloudimg_seeder.guest.drain_stdin", no_drain)
    monkeypatch.setattr("cloudimg_seeder.guest.accel_for_guest", tcg_accel)
    monkeypatch.setattr("cloudimg_seeder.guest.find_qemu_binary", x86_binary)
    monkeypatch.setattr("cloudimg_seeder.guest.build_qemu_argv", true_argv)

    class Proc:
        returncode = 0

        def kill(self) -> None:
            return None

        async def wait(self) -> int:
            return 0

    async def fake_exec(*_a: object, **_k: object) -> Proc:
        return Proc()

    class GuestTalksThenStops:
        def __init__(self, **kwargs: object) -> None:
            self._display = kwargs["display"]

        async def run(self) -> None:
            # Ends mid-line, exactly as a chunk boundary at the cloud-init
            # completion match does.
            self._display.write("Cloud-init v. 26.1 finished at Fri")  # type: ignore[attr-defined]

    async def fake_powerdown(*_a: object, **_k: object) -> None:
        logging.getLogger("cloudimg_seeder").info(
            "cloud-init finished; sending ACPI powerdown"
        )

    monkeypatch.setattr(
        "cloudimg_seeder.guest.asyncio.create_subprocess_exec", fake_exec
    )
    monkeypatch.setattr("cloudimg_seeder.guest.SerialSession", GuestTalksThenStops)
    monkeypatch.setattr("cloudimg_seeder.guest.qmp_powerdown_and_wait", fake_powerdown)

    disk = tmp_path / "d.qcow2"
    iso = tmp_path / "s.iso"
    disk.write_bytes(b"x")
    iso.write_bytes(b"x")
    try:
        await run_headless_qemu(
            arch=GuestArch.AMD64,
            disk=disk,
            seed_iso=iso,
            workdir=tmp_path,
            cpus=1,
            memory_mb=512,
            timeout_sec=5,
            serial=SerialOptions(ui=ui),
        )
    finally:
        logger.handlers = previous

    lines = buf.getvalue().splitlines()
    guest_line = next(i for i, ln in enumerate(lines) if "Cloud-init v. 26.1" in ln)
    close_rule = next(i for i, ln in enumerate(lines) if "end guest serial" in ln)
    step = next(i for i, ln in enumerate(lines) if "sending ACPI powerdown" in ln)

    # The guest's unterminated line stands alone, the region closes, and only
    # then does cloudimg-seeder speak.
    assert lines[guest_line] == "Cloud-init v. 26.1 finished at Fri"
    assert guest_line < close_rule < step
