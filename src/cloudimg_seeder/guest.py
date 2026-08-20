"""Headless QEMU guest: argv construction, serial wait, and QMP powerdown."""

from __future__ import annotations

import asyncio
import logging
import re
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

from qemu.qmp import QMPClient

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.firmware import find_edk2_aarch64_code, prepare_edk2_aarch64_vars
from cloudimg_seeder.host import accel_for_guest, accel_qemu_arg, find_qemu_binary
from cloudimg_seeder.qemu_path import qemu_drive_path

logger = logging.getLogger("cloudimg_seeder")

CLOUD_INIT_FINISHED = re.compile(
    r"Cloud-init.*finished|cloud-init has finished",
    re.IGNORECASE,
)

_EDK2_VARS_NAME = "edk2-aarch64-vars.fd"
_CONNECT_ATTEMPTS = 50
_CONNECT_DELAY_SEC = 0.1


@dataclass(frozen=True)
class GuestPorts:
    qmp: int
    serial: int


def allocate_localhost_ports() -> GuestPorts:
    """Bind two ephemeral ports on 127.0.0.1 and return their numbers."""

    def _one() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    return GuestPorts(qmp=_one(), serial=_one())


@dataclass(frozen=True)
class GuestFirmware:
    code: Path
    vars_store: Path


def prepare_arm64_firmware(workdir: Path) -> GuestFirmware:
    binary = find_qemu_binary("qemu-system-aarch64")
    code = find_edk2_aarch64_code(binary)
    vars_store = prepare_edk2_aarch64_vars(workdir / _EDK2_VARS_NAME, code)
    return GuestFirmware(code=code, vars_store=vars_store)


def build_qemu_argv(
    *,
    arch: GuestArch,
    disk: Path,
    seed_iso: Path,
    ports: GuestPorts,
    cpus: int,
    memory_mb: int,
    accel: str,
    binary: str,
    firmware: GuestFirmware | None = None,
) -> list[str]:
    """Build QEMU argv. Pure aside from path escaping; no filesystem search."""
    accel_arg = accel_qemu_arg(accel)
    disk_file = qemu_drive_path(disk)
    iso_file = qemu_drive_path(seed_iso)
    argv: list[str]

    if arch is GuestArch.ARM64:
        if firmware is None:
            raise QemuError("arm64 guest requires firmware paths")
        code_file = qemu_drive_path(firmware.code)
        vars_file = qemu_drive_path(firmware.vars_store)
        argv = [binary]
        if accel != "tcg":
            argv.extend(
                [
                    "-machine",
                    f"virt,accel={accel_arg},highmem=on",
                    "-cpu",
                    "host",
                ]
            )
        else:
            argv.extend(["-machine", "virt", "-accel", "tcg", "-cpu", "max"])
        argv.extend(
            [
                "-drive",
                f"if=pflash,format=raw,readonly=on,file={code_file}",
                "-drive",
                f"if=pflash,format=raw,file={vars_file}",
            ]
        )
    elif arch is GuestArch.AMD64:
        argv = [binary, "-machine", "q35"]
        if accel != "tcg":
            argv.extend(["-accel", accel_arg, "-cpu", "host"])
        else:
            argv.extend(["-accel", "tcg", "-cpu", "qemu64"])
    else:
        raise QemuError(f"unsupported arch: {arch}")

    argv.extend(
        [
            "-smp",
            str(cpus),
            "-m",
            str(memory_mb),
            "-display",
            "none",
            "-serial",
            f"tcp:127.0.0.1:{ports.serial},server=on,wait=off",
            "-qmp",
            f"tcp:127.0.0.1:{ports.qmp},server=on,wait=off",
            "-nic",
            "user,model=virtio-net-pci",
            "-device",
            "virtio-rng-pci",
            "-drive",
            f"if=virtio,format=qcow2,file={disk_file}",
            "-drive",
            f"if=virtio,format=raw,readonly=on,file={iso_file}",
        ]
    )
    return argv


async def _open_tcp(
    port: int,
    process: asyncio.subprocess.Process,
    *,
    label: str,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    for _ in range(_CONNECT_ATTEMPTS):
        if process.returncode is not None:
            raise QemuError(f"QEMU exited before {label} was ready")
        try:
            return await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(_CONNECT_DELAY_SEC)
    raise QemuError(f"{label} not ready on 127.0.0.1:{port}")


async def stream_serial_until_cloud_init(
    serial_port: int,
    process: asyncio.subprocess.Process,
) -> None:
    reader, writer = await _open_tcp(serial_port, process, label="serial")
    buf = ""
    try:
        while True:
            if process.returncode is not None:
                raise QemuError(
                    "QEMU exited before cloud-init finished (see serial output above)"
                )
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=1.0)
            except TimeoutError:
                continue
            if not chunk:
                if process.returncode is not None:
                    raise QemuError(
                        "QEMU exited before cloud-init finished "
                        "(see serial output above)"
                    )
                await asyncio.sleep(0.1)
                continue
            text = chunk.decode(errors="replace")
            print(text, end="", file=sys.stderr, flush=True)
            buf += text
            if CLOUD_INIT_FINISHED.search(buf):
                return
            if len(buf) > 1_000_000:
                buf = buf[-500_000:]
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def qmp_powerdown_and_wait(
    qmp_port: int,
    process: asyncio.subprocess.Process,
    *,
    force_quit: bool = False,
) -> None:
    qmp = QMPClient("cloudimg-seeder")
    for _ in range(_CONNECT_ATTEMPTS):
        if process.returncode is not None and not force_quit:
            raise QemuError("QEMU exited before QMP was ready")
        try:
            await qmp.connect(("127.0.0.1", qmp_port))
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(_CONNECT_DELAY_SEC)
    else:
        raise QemuError(f"QMP not ready on 127.0.0.1:{qmp_port}")

    try:
        if force_quit:
            await qmp.execute("quit")
        else:
            with qmp.listener("SHUTDOWN") as listener:
                logger.info("cloud-init finished; sending ACPI powerdown")
                await qmp.execute("system_powerdown")
                try:
                    await asyncio.wait_for(listener.get(), timeout=60.0)
                except TimeoutError:
                    logger.warning("QEMU did not exit after powerdown; forcing quit")
                    await qmp.execute("quit")
    finally:
        try:
            await qmp.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.debug("qmp disconnect failed: %s", exc)

    try:
        await asyncio.wait_for(process.wait(), timeout=60.0)
    except TimeoutError:
        process.kill()
        await process.wait()


async def _boot_until_shutdown(
    ports: GuestPorts,
    process: asyncio.subprocess.Process,
) -> None:
    await stream_serial_until_cloud_init(ports.serial, process)
    await qmp_powerdown_and_wait(ports.qmp, process)


async def run_headless_qemu(
    *,
    arch: GuestArch,
    disk: Path,
    seed_iso: Path,
    workdir: Path,
    cpus: int,
    memory_mb: int,
    timeout_sec: float,
) -> None:
    """Boot disk with seed_iso until cloud-init finishes, then power down.

    Streams serial console to stderr. Raises QemuError on timeout or
    unexpected guest exit.
    """
    ports = allocate_localhost_ports()
    accel = accel_for_guest(arch)
    firmware: GuestFirmware | None = None
    if arch is GuestArch.ARM64:
        binary = find_qemu_binary("qemu-system-aarch64")
        firmware = prepare_arm64_firmware(workdir)
    elif arch is GuestArch.AMD64:
        binary = find_qemu_binary("qemu-system-x86_64")
    else:
        raise QemuError(f"unsupported arch: {arch}")

    argv = build_qemu_argv(
        arch=arch,
        disk=disk,
        seed_iso=seed_iso,
        ports=ports,
        cpus=cpus,
        memory_mb=memory_mb,
        accel=accel,
        binary=binary,
        firmware=firmware,
    )
    logger.info("starting QEMU (%s, %s cpus, %sM)", arch.value, cpus, memory_mb)

    process = await asyncio.create_subprocess_exec(*argv)
    try:
        try:
            await asyncio.wait_for(
                _boot_until_shutdown(ports, process),
                timeout=timeout_sec,
            )
        except TimeoutError:
            logger.warning(
                "timeout after %ss waiting for cloud-init; forcing quit",
                int(timeout_sec),
            )
            try:
                await qmp_powerdown_and_wait(ports.qmp, process, force_quit=True)
            except Exception:  # noqa: BLE001
                process.kill()
                await process.wait()
            raise QemuError("timed out waiting for cloud-init to finish") from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
