"""Tests for guest argv construction and lifecycle."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.console import SerialOptions
from cloudimg_seeder.errors import CloudInitError, QemuError
from cloudimg_seeder.guest import GuestFirmware, build_qemu_argv, run_headless_qemu
from cloudimg_seeder.probe import STATUS_PORT_NAME
from cloudimg_seeder.serial import CLOUD_INIT_FINISHED, IdleTimeoutError
from cloudimg_seeder.transport import GuestEndpoints, TcpEndpoint, UnixEndpoint


def _endpoints(qmp: int, serial: int, status: int = 6666) -> GuestEndpoints:
    return GuestEndpoints(
        qmp=TcpEndpoint(qmp), serial=TcpEndpoint(serial), status=TcpEndpoint(status)
    )


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
        endpoints=_endpoints(qmp=4444, serial=5555, status=7777),
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
    assert "virtio-serial" in argv
    assert "socket,id=cistatus,host=127.0.0.1,port=7777,server=on,wait=off" in argv
    assert f"virtserialport,chardev=cistatus,name={STATUS_PORT_NAME}" in argv


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
    disk = tmp_path / "disk.qcow2"
    iso = tmp_path / "seed.iso"
    disk.write_bytes(b"x")
    iso.write_bytes(b"x")
    endpoints = GuestEndpoints(
        qmp=UnixEndpoint(tmp_path / "qmp.sock"),
        serial=UnixEndpoint(tmp_path / "serial.sock"),
        status=UnixEndpoint(tmp_path / "status.sock"),
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
    assert f"path={tmp_path / 'status.sock'}" in joined
    assert "tcp:" not in joined


def test_cloud_init_reexport() -> None:
    assert CLOUD_INIT_FINISHED.search("Cloud-init v. 24.1 finished at Tue.")


class _Proc:
    returncode = 0

    def kill(self) -> None:
        return None

    async def wait(self) -> int:
        return 0


def _patch_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub argv construction and process spawning; leaves session classes
    and qmp_powerdown_and_wait for each test to patch."""

    def fake_accel(_arch: GuestArch) -> str:
        return "tcg"

    def fake_binary(_name: str) -> str:
        return "qemu-system-x86_64"

    def fake_argv(**_kwargs: object) -> list[str]:
        return ["true"]

    async def fake_exec(*_a: object, **_k: object) -> _Proc:
        return _Proc()

    monkeypatch.setattr("cloudimg_seeder.guest.accel_for_guest", fake_accel)
    monkeypatch.setattr("cloudimg_seeder.guest.find_qemu_binary", fake_binary)
    monkeypatch.setattr("cloudimg_seeder.guest.build_qemu_argv", fake_argv)
    monkeypatch.setattr(
        "cloudimg_seeder.guest.asyncio.create_subprocess_exec", fake_exec
    )


async def _run(
    tmp_path: Path, *, idle_timeout_sec: float | None = 5, strict: bool = False
) -> None:
    disk = tmp_path / "d.qcow2"
    iso = tmp_path / "s.iso"
    disk.write_bytes(b"x")
    iso.write_bytes(b"x")
    await run_headless_qemu(
        arch=GuestArch.AMD64,
        disk=disk,
        seed_iso=iso,
        workdir=tmp_path,
        cpus=1,
        memory_mb=512,
        idle_timeout_sec=idle_timeout_sec,
        strict=strict,
        serial=SerialOptions(show_serial=False),
    )


@pytest.mark.asyncio
async def test_run_headless_drains_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drained: list[bool] = []

    def fake_drain() -> None:
        drained.append(True)

    monkeypatch.setattr("cloudimg_seeder.guest.drain_stdin", fake_drain)
    _patch_boot(monkeypatch)

    class TimingOutSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> None:
            raise IdleTimeoutError("no guest output for 1s")

    class HangingStatusSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> int | None:
            await asyncio.sleep(100)
            return None

    async def boom_qmp(*_a: object, **_k: object) -> None:
        raise OSError("qmp down")

    monkeypatch.setattr("cloudimg_seeder.guest.SerialSession", TimingOutSession)
    monkeypatch.setattr("cloudimg_seeder.guest.StatusSession", HangingStatusSession)
    monkeypatch.setattr("cloudimg_seeder.guest.qmp_powerdown_and_wait", boom_qmp)

    with pytest.raises(QemuError, match="no guest output"):
        await _run(tmp_path, idle_timeout_sec=1)
    assert drained == [True]


@pytest.mark.asyncio
async def test_status_probe_wins_over_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The console never matches; the status probe alone decides completion."""
    _patch_boot(monkeypatch)
    monkeypatch.setattr("cloudimg_seeder.guest.drain_stdin", lambda: None)

    class HangingSerialSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> None:
            await asyncio.sleep(100)

    class ImmediateStatusSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> int:
            return 0

    async def fake_powerdown(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr("cloudimg_seeder.guest.SerialSession", HangingSerialSession)
    monkeypatch.setattr("cloudimg_seeder.guest.StatusSession", ImmediateStatusSession)
    monkeypatch.setattr("cloudimg_seeder.guest.qmp_powerdown_and_wait", fake_powerdown)

    await _run(tmp_path)  # does not raise; does not wait out the idle timeout


@pytest.mark.asyncio
async def test_console_match_waits_grace_window_for_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Console matches first; the probe's result still arrives inside the
    grace window and is honored."""
    _patch_boot(monkeypatch)
    monkeypatch.setattr("cloudimg_seeder.guest.drain_stdin", lambda: None)
    monkeypatch.setattr("cloudimg_seeder.guest._STATUS_GRACE_SEC", 2.0)

    class ImmediateSerialSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> None:
            return None

    class DelayedStatusSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> int:
            await asyncio.sleep(0.05)
            return 1

    async def fake_powerdown(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr("cloudimg_seeder.guest.SerialSession", ImmediateSerialSession)
    monkeypatch.setattr("cloudimg_seeder.guest.StatusSession", DelayedStatusSession)
    monkeypatch.setattr("cloudimg_seeder.guest.qmp_powerdown_and_wait", fake_powerdown)

    with pytest.raises(CloudInitError, match="exit 1"):
        await _run(tmp_path)


@pytest.mark.asyncio
async def test_console_match_status_unknown_after_grace_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Console matches first; the probe never responds within the grace
    window, so status is unknown and the run still succeeds."""
    _patch_boot(monkeypatch)
    monkeypatch.setattr("cloudimg_seeder.guest.drain_stdin", lambda: None)
    monkeypatch.setattr("cloudimg_seeder.guest._STATUS_GRACE_SEC", 0.05)

    class ImmediateSerialSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> None:
            return None

    class NeverRespondingStatusSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> int | None:
            await asyncio.sleep(100)
            return None

    async def fake_powerdown(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr("cloudimg_seeder.guest.SerialSession", ImmediateSerialSession)
    monkeypatch.setattr(
        "cloudimg_seeder.guest.StatusSession", NeverRespondingStatusSession
    )
    monkeypatch.setattr("cloudimg_seeder.guest.qmp_powerdown_and_wait", fake_powerdown)

    with caplog.at_level(logging.WARNING, logger="cloudimg_seeder"):
        await _run(tmp_path)  # does not raise
    assert "status unknown" in caplog.text


@pytest.mark.asyncio
async def test_cloud_init_error_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_boot(monkeypatch)
    monkeypatch.setattr("cloudimg_seeder.guest.drain_stdin", lambda: None)

    class ImmediateSerialSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> None:
            return None

    class ErrorStatusSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> int:
            return 1

    async def fake_powerdown(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr("cloudimg_seeder.guest.SerialSession", ImmediateSerialSession)
    monkeypatch.setattr("cloudimg_seeder.guest.StatusSession", ErrorStatusSession)
    monkeypatch.setattr("cloudimg_seeder.guest.qmp_powerdown_and_wait", fake_powerdown)

    with pytest.raises(CloudInitError, match="exit 1"):
        await _run(tmp_path)


@pytest.mark.asyncio
async def test_degraded_exit_2_warns_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_boot(monkeypatch)
    monkeypatch.setattr("cloudimg_seeder.guest.drain_stdin", lambda: None)

    class ImmediateSerialSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> None:
            return None

    class DegradedStatusSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> int:
            return 2

    async def fake_powerdown(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr("cloudimg_seeder.guest.SerialSession", ImmediateSerialSession)
    monkeypatch.setattr("cloudimg_seeder.guest.StatusSession", DegradedStatusSession)
    monkeypatch.setattr("cloudimg_seeder.guest.qmp_powerdown_and_wait", fake_powerdown)

    with caplog.at_level(logging.WARNING, logger="cloudimg_seeder"):
        await _run(tmp_path, strict=False)  # does not raise
    assert "degraded" in caplog.text


@pytest.mark.asyncio
async def test_degraded_exit_2_raises_under_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_boot(monkeypatch)
    monkeypatch.setattr("cloudimg_seeder.guest.drain_stdin", lambda: None)

    class ImmediateSerialSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> None:
            return None

    class DegradedStatusSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> int:
            return 2

    async def fake_powerdown(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr("cloudimg_seeder.guest.SerialSession", ImmediateSerialSession)
    monkeypatch.setattr("cloudimg_seeder.guest.StatusSession", DegradedStatusSession)
    monkeypatch.setattr("cloudimg_seeder.guest.qmp_powerdown_and_wait", fake_powerdown)

    with pytest.raises(CloudInitError, match="exit 2"):
        await _run(tmp_path, strict=True)


@pytest.mark.asyncio
async def test_serial_region_closes_before_powerdown_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the powerdown step message used to be emitted while the
    guest-serial region was still open, so it landed inside the rules (and,
    after unterminated guest output, on the guest's own last line)."""
    import io

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

    _patch_boot(monkeypatch)
    monkeypatch.setattr("cloudimg_seeder.guest.drain_stdin", lambda: None)

    class GuestTalksThenStops:
        def __init__(self, **kwargs: object) -> None:
            self._display = kwargs["display"]

        async def run(self) -> None:
            # Ends mid-line, exactly as a chunk boundary at the cloud-init
            # completion match does.
            self._display.write("Cloud-init v. 26.1 finished at Fri")  # type: ignore[attr-defined]

    class ImmediateStatusSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> int:
            return 0

    async def fake_powerdown(*_a: object, **_k: object) -> None:
        logging.getLogger("cloudimg_seeder").info(
            "cloud-init finished; sending ACPI powerdown"
        )

    monkeypatch.setattr("cloudimg_seeder.guest.SerialSession", GuestTalksThenStops)
    monkeypatch.setattr("cloudimg_seeder.guest.StatusSession", ImmediateStatusSession)
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
            idle_timeout_sec=5,
            strict=False,
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
