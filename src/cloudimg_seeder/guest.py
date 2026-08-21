"""Headless QEMU guest: argv, QMP, and lifecycle."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from qemu.qmp import QMPClient, QMPError

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.console import SerialDisplay, SerialOptions, drain_stdin
from cloudimg_seeder.errors import CloudInitError, QemuError
from cloudimg_seeder.firmware import find_edk2_aarch64_code, prepare_edk2_aarch64_vars
from cloudimg_seeder.host import accel_for_guest, find_qemu_binary
from cloudimg_seeder.probe import STATUS_PORT_NAME
from cloudimg_seeder.qemu_path import qemu_drive_path
from cloudimg_seeder.serial import (
    CLOUD_INIT_FINISHED,
    IdleTimeoutError,
    SerialSession,
    StatusSession,
)
from cloudimg_seeder.transport import Endpoint, GuestEndpoints, allocate_endpoints

logger = logging.getLogger("cloudimg_seeder")

_EDK2_VARS_NAME = "edk2-aarch64-vars.fd"
_CONNECT_ATTEMPTS = 50
_CONNECT_DELAY_SEC = 0.1
_STATUS_CHARDEV_ID = "cistatus"
# How long to wait for the status probe after the console already matched
# cloud-init's final_message: the two race with no guaranteed order.
_STATUS_GRACE_SEC = 15.0
# Bound on the serial session's own shutdown once the status probe has
# decided completion; it settles first so the console keeps the tail the
# guest was still writing.
_SERIAL_STOP_SEC = 10.0

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
            "-device",
            "virtio-serial",
            "-chardev",
            endpoints.status.chardev_arg(_STATUS_CHARDEV_ID),
            "-device",
            f"virtserialport,chardev={_STATUS_CHARDEV_ID},name={STATUS_PORT_NAME}",
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


async def _wait_for_completion(
    serial_session: SerialSession, status_session: StatusSession
) -> int | None:
    """Run both sessions; return the probe's exit code, or None if unknown.

    The probe result is authoritative when it arrives. If the console
    matches cloud-init's final_message first, wait a grace window for the
    probe before concluding status is unknown: the two race with no
    guaranteed order.

    When the probe decides first, the serial session is asked to stop and
    given ``_SERIAL_STOP_SEC`` to settle, so console output is not cut off
    mid-line. Its outcome does not affect the returned status.
    """
    serial_task = asyncio.create_task(serial_session.run())
    status_task = asyncio.create_task(status_session.run())
    try:
        done, _ = await asyncio.wait(
            {serial_task, status_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if status_task in done:
            serial_session.request_stop()
            await asyncio.wait({serial_task}, timeout=_SERIAL_STOP_SEC)
            return status_task.result()

        exc = serial_task.exception()
        if exc is not None:
            raise exc
        try:
            return await asyncio.wait_for(status_task, timeout=_STATUS_GRACE_SEC)
        except TimeoutError:
            return None
    finally:
        for task in (serial_task, status_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(serial_task, status_task, return_exceptions=True)


def _check_status(status_code: int | None, *, strict: bool) -> None:
    """Raise CloudInitError on cloud-init failure; warn on unknown/degraded."""
    if status_code is None:
        logger.warning("cloud-init status unknown; probe did not respond")
        return
    if status_code == 0:
        return
    if status_code == 2 and not strict:
        logger.warning("cloud-init finished degraded (exit %s)", status_code)
        return
    raise CloudInitError(f"cloud-init failed (exit {status_code})")


async def run_headless_qemu(
    *,
    arch: GuestArch,
    disk: Path,
    seed_iso: Path,
    workdir: Path,
    cpus: int,
    memory_mb: int,
    idle_timeout_sec: float | None,
    strict: bool,
    serial: SerialOptions,
) -> None:
    """Boot disk with seed_iso until cloud-init finishes, then power down.

    Streams serial via SerialDisplay. Completion is decided by the guest
    status probe (see probe.py) reporting ``cloud-init status --wait``'s
    exit code over a dedicated virtio-serial channel; when the probe never
    responds, completion falls back to matching cloud-init's default
    final_message on the console and status is treated as unknown.
    idle_timeout_sec bounds consecutive console silence, not total run
    time; None waits indefinitely. Raises QemuError on idle timeout or
    unexpected guest exit, and CloudInitError when cloud-init itself failed
    (or finished degraded, under strict). Drains TTY stdin after the run.
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
    if idle_timeout_sec is None:
        logger.warning("no idle timeout set; waiting indefinitely for cloud-init")

    status_code: int | None = None
    process = await asyncio.create_subprocess_exec(*argv)
    try:
        try:
            # The serial region is scoped to serial streaming alone, so it is
            # closed before powerdown logs anything and guest output never
            # interleaves with cloudimg-seeder's own lines. idle_timeout_sec
            # bounds console silence; powerdown carries its own timeouts.
            with SerialDisplay(
                ui=serial.ui,
                show_serial=serial.show_serial,
                serial_log=serial.serial_log,
                serial_log_format=serial.serial_log_format,
            ) as display:
                serial_session = SerialSession(
                    endpoint=endpoints.serial,
                    process=process,
                    display=display,
                    idle_timeout_sec=idle_timeout_sec,
                )
                status_session = StatusSession(
                    endpoint=endpoints.status, process=process
                )
                status_code = await _wait_for_completion(serial_session, status_session)
            await qmp_powerdown_and_wait(endpoints.qmp, process)
        except IdleTimeoutError as exc:
            logger.warning("%s; forcing quit", exc)
            try:
                await qmp_powerdown_and_wait(endpoints.qmp, process, force_quit=True)
            except (QemuError, QMPError, OSError):
                process.kill()
                await process.wait()
            raise
    finally:
        drain_stdin()
        if process.returncode is None:
            process.kill()
            await process.wait()

    _check_status(status_code, strict=strict)
