"""Headless QEMU guest: argv, QMP, and lifecycle."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from qemu.qmp import QMPClient, QMPError

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.console import SerialDisplay, SerialOptions, drain_stdin
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.firmware import find_edk2_aarch64_code, prepare_edk2_aarch64_vars
from cloudimg_seeder.host import accel_for_guest, find_qemu_binary
from cloudimg_seeder.qemu_path import qemu_drive_path
from cloudimg_seeder.serial import CLOUD_INIT_FINISHED, SerialSession
from cloudimg_seeder.transport import Endpoint, GuestEndpoints, allocate_endpoints

logger = logging.getLogger("cloudimg_seeder")

_EDK2_VARS_NAME = "edk2-aarch64-vars.fd"
_CONNECT_ATTEMPTS = 50
_CONNECT_DELAY_SEC = 0.1

__all__ = [
    "CLOUD_INIT_FINISHED",
    "GuestFirmware",
    "build_qemu_argv",
    "prepare_arm64_firmware",
    "qmp_powerdown_and_wait",
    "run_headless_qemu",
]


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
    endpoints: GuestEndpoints,
    cpus: int,
    memory_mb: int,
    accel: str,
    binary: str,
    firmware: GuestFirmware | None = None,
) -> list[str]:
    """Build QEMU argv. Pure aside from path escaping; no filesystem search."""
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
            argv.extend(["-machine", f"virt,accel={accel}", "-cpu", "host"])
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
            argv.extend(["-accel", accel, "-cpu", "host"])
        else:
            argv.extend(["-accel", "tcg", "-cpu", "max"])
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
            endpoints.serial.qemu_arg,
            "-qmp",
            endpoints.qmp.qemu_arg,
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


async def qmp_powerdown_and_wait(
    qmp_endpoint: Endpoint,
    process: asyncio.subprocess.Process,
    *,
    force_quit: bool = False,
) -> None:
    qmp = QMPClient("cloudimg-seeder")
    for _ in range(_CONNECT_ATTEMPTS):
        if process.returncode is not None and not force_quit:
            raise QemuError("QEMU exited before QMP was ready")
        try:
            await qmp.connect(qmp_endpoint.address)
            break
        except (QMPError, OSError):
            await asyncio.sleep(_CONNECT_DELAY_SEC)
    else:
        raise QemuError(f"QMP not ready ({qmp_endpoint.address})")

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
        except (QMPError, OSError) as exc:
            logger.debug("qmp disconnect failed: %s", exc)

    try:
        await asyncio.wait_for(process.wait(), timeout=60.0)
    except TimeoutError:
        process.kill()
        await process.wait()


async def _boot_until_shutdown(
    endpoints: GuestEndpoints,
    process: asyncio.subprocess.Process,
    display: SerialDisplay,
) -> None:
    session = SerialSession(endpoint=endpoints.serial, process=process, display=display)
    await session.run()
    await qmp_powerdown_and_wait(endpoints.qmp, process)


async def run_headless_qemu(
    *,
    arch: GuestArch,
    disk: Path,
    seed_iso: Path,
    workdir: Path,
    cpus: int,
    memory_mb: int,
    timeout_sec: float,
    serial: SerialOptions,
) -> None:
    """Boot disk with seed_iso until cloud-init finishes, then power down.

    Streams serial via SerialDisplay. Raises QemuError on timeout or
    unexpected guest exit. Drains TTY stdin after the run.
    """
    endpoints = allocate_endpoints(workdir)
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
        endpoints=endpoints,
        cpus=cpus,
        memory_mb=memory_mb,
        accel=accel,
        binary=binary,
        firmware=firmware,
    )
    logger.info("starting QEMU (%s, %s cpus, %sM)", arch.value, cpus, memory_mb)

    with SerialDisplay(quiet=serial.quiet, serial_log=serial.serial_log) as display:
        process = await asyncio.create_subprocess_exec(*argv)
        try:
            try:
                await asyncio.wait_for(
                    _boot_until_shutdown(endpoints, process, display),
                    timeout=timeout_sec,
                )
            except TimeoutError:
                logger.warning(
                    "timeout after %ss waiting for cloud-init; forcing quit",
                    int(timeout_sec),
                )
                try:
                    await qmp_powerdown_and_wait(
                        endpoints.qmp, process, force_quit=True
                    )
                except (QemuError, QMPError, OSError):
                    process.kill()
                    await process.wait()
                raise QemuError("timed out waiting for cloud-init to finish") from None
        finally:
            drain_stdin()
            if process.returncode is None:
                process.kill()
                await process.wait()
