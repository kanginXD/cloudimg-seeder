"""QEMU guest control: argv, EDK2 firmware, serial, and QMP."""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import shutil
import subprocess
import sys
from enum import Enum
from pathlib import Path

from qemu.qmp import QMPClient

logger = logging.getLogger("cloudimg_seeder")

CLOUD_INIT_FINISHED = re.compile(
    r"Cloud-init.*finished|cloud-init has finished",
    re.IGNORECASE,
)

_EDK2_CODE_NAME = "edk2-aarch64-code.fd"
_EDK2_VARS_NAME = "edk2-aarch64-vars.fd"
_EMPTY_VARS_BYTES = 64 * 1024 * 1024


class GuestArch(str, Enum):
    ARM64 = "arm64"
    AMD64 = "amd64"


class QemuError(Exception):
    pass


def normalize_arch(value: str) -> GuestArch:
    key = value.lower().replace("-", "_")
    if key in {"arm64", "aarch64"}:
        return GuestArch.ARM64
    if key in {"amd64", "x86_64"}:
        return GuestArch.AMD64
    raise QemuError(f"invalid arch: {value} (use arm64 or amd64)")


def detect_host_arch() -> GuestArch:
    return normalize_arch(platform.machine())


def detect_arch_from_name(name: str) -> GuestArch | None:
    lower = name.lower()
    if re.search(r"arm64|aarch64", lower):
        return GuestArch.ARM64
    if re.search(r"amd64|x86_64|x86-64", lower):
        return GuestArch.AMD64
    return None


def resolve_arch(disk: Path, explicit: GuestArch | None) -> GuestArch:
    if explicit is not None:
        return explicit
    from_name = detect_arch_from_name(disk.name)
    if from_name is not None:
        return from_name
    return detect_host_arch()


def default_output_path(disk: Path, cwd: Path | None = None) -> Path:
    """Return cwd/{stem}.qcow2, or {stem}-cloudinit.qcow2 if that equals disk."""
    base = cwd if cwd is not None else Path.cwd()
    stem = disk.stem if disk.suffix else disk.name
    out = (base / f"{stem}.qcow2").resolve()
    if disk.resolve() == out:
        out = (base / f"{stem}-cloudinit.qcow2").resolve()
    return out


def require_cmd(name: str, hint: str | None = None) -> str:
    path = shutil.which(name)
    if path is None:
        if hint:
            raise QemuError(f"missing '{name}'. Install with: {hint}")
        raise QemuError(f"missing '{name}'")
    return path


def convert_to_qcow2(src: Path, dst: Path) -> None:
    require_cmd("qemu-img", "brew install qemu")
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["qemu-img", "convert", "-p", "-O", "qcow2", str(src), str(dst)],
        check=True,
    )


def _qemu_share_dirs() -> list[Path]:
    dirs: list[Path] = []
    if shutil.which("brew") is not None:
        try:
            result = subprocess.run(
                ["brew", "--prefix", "qemu"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0:
            prefix = result.stdout.strip()
            if prefix:
                dirs.append(Path(prefix) / "share" / "qemu")
    dirs.extend(
        [
            Path("/opt/homebrew/share/qemu"),
            Path("/usr/local/share/qemu"),
        ]
    )
    return dirs


def find_edk2_aarch64_code() -> Path:
    for directory in _qemu_share_dirs():
        candidate = directory / _EDK2_CODE_NAME
        if candidate.is_file():
            return candidate
    raise QemuError(
        f"EDK2 aarch64 firmware not found ({_EDK2_CODE_NAME}). Reinstall qemu."
    )


def prepare_edk2_aarch64_vars(dest: Path) -> Path:
    """Copy the EDK2 vars template to dest, or create a 64 MiB empty store."""
    code = find_edk2_aarch64_code()
    code_dir = code.parent
    vars_src: Path | None = None
    same_dir = code_dir / _EDK2_VARS_NAME
    if same_dir.is_file():
        vars_src = same_dir
    else:
        for directory in _qemu_share_dirs():
            candidate = directory / _EDK2_VARS_NAME
            if candidate.is_file():
                vars_src = candidate
                break

    if vars_src is not None:
        shutil.copy(vars_src, dest)
    else:
        dest.write_bytes(b"\0" * _EMPTY_VARS_BYTES)
    return dest


def _host_accel() -> str:
    system = platform.system()
    if system == "Darwin":
        return "hvf"
    if system == "Linux":
        return "kvm"
    return "tcg"


def build_qemu_argv(
    *,
    arch: GuestArch,
    disk: Path,
    seed_iso: Path,
    qmp_sock: Path,
    serial_sock: Path,
    workdir: Path,
    cpus: int,
    memory_mb: int,
) -> list[str]:
    host_arch = detect_host_arch()
    accel = _host_accel()
    argv: list[str]

    if arch is GuestArch.ARM64:
        binary = require_cmd("qemu-system-aarch64", "brew install qemu")
        code_fd = find_edk2_aarch64_code()
        vars_fd = prepare_edk2_aarch64_vars(workdir / _EDK2_VARS_NAME)
        argv = [binary]
        if host_arch is GuestArch.ARM64 and accel != "tcg":
            argv.extend(
                [
                    "-machine",
                    f"virt,accel={accel},highmem=on",
                    "-cpu",
                    "host",
                ]
            )
        else:
            argv.extend(["-machine", "virt", "-accel", "tcg", "-cpu", "max"])
        argv.extend(
            [
                "-drive",
                f"if=pflash,format=raw,readonly=on,file={code_fd}",
                "-drive",
                f"if=pflash,format=raw,file={vars_fd}",
            ]
        )
    elif arch is GuestArch.AMD64:
        binary = require_cmd("qemu-system-x86_64", "brew install qemu")
        argv = [binary, "-machine", "q35"]
        if host_arch is GuestArch.AMD64 and accel != "tcg":
            argv.extend(["-accel", accel, "-cpu", "host"])
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
            f"unix:{serial_sock},server=on,wait=off",
            "-qmp",
            f"unix:{qmp_sock},server=on,wait=off",
            "-nic",
            "user,model=virtio-net-pci",
            "-device",
            "virtio-rng-pci",
            "-drive",
            f"if=virtio,format=qcow2,file={disk}",
            "-drive",
            f"if=virtio,format=raw,readonly=on,file={seed_iso}",
        ]
    )
    return argv


async def _wait_for_socket(path: Path, process: asyncio.subprocess.Process) -> None:
    for _ in range(50):
        if path.exists():
            return
        if process.returncode is not None:
            raise QemuError("QEMU failed to start")
        await asyncio.sleep(0.1)
    raise QemuError(f"socket not ready: {path}")


async def _stream_serial_until_cloud_init(
    serial_sock: Path,
    process: asyncio.subprocess.Process,
) -> None:
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    for _ in range(50):
        if process.returncode is not None:
            raise QemuError("QEMU exited before serial was ready")
        try:
            reader, writer = await asyncio.open_unix_connection(str(serial_sock))
            break
        except OSError:
            await asyncio.sleep(0.1)
    if reader is None or writer is None:
        raise QemuError("serial socket not ready")

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


async def _qmp_powerdown_and_wait(
    qmp_sock: Path,
    process: asyncio.subprocess.Process,
    *,
    force_quit: bool = False,
) -> None:
    qmp = QMPClient("cloudimg-seeder")
    await qmp.connect(str(qmp_sock))
    try:
        if force_quit:
            await qmp.execute("quit")
            return

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
    qmp_sock = workdir / "qmp.sock"
    serial_sock = workdir / "serial.sock"
    argv = build_qemu_argv(
        arch=arch,
        disk=disk,
        seed_iso=seed_iso,
        qmp_sock=qmp_sock,
        serial_sock=serial_sock,
        workdir=workdir,
        cpus=cpus,
        memory_mb=memory_mb,
    )
    logger.info("starting QEMU (%s, %s cpus, %sM)", arch.value, cpus, memory_mb)

    process = await asyncio.create_subprocess_exec(*argv)
    try:
        await _wait_for_socket(qmp_sock, process)
        try:
            await asyncio.wait_for(
                _boot_until_shutdown(serial_sock, qmp_sock, process),
                timeout=timeout_sec,
            )
        except TimeoutError:
            logger.warning(
                "timeout after %ss waiting for cloud-init; forcing quit",
                int(timeout_sec),
            )
            try:
                await _qmp_powerdown_and_wait(qmp_sock, process, force_quit=True)
            except Exception:  # noqa: BLE001
                process.kill()
                await process.wait()
            raise QemuError("timed out waiting for cloud-init to finish") from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def _boot_until_shutdown(
    serial_sock: Path,
    qmp_sock: Path,
    process: asyncio.subprocess.Process,
) -> None:
    await _stream_serial_until_cloud_init(serial_sock, process)
    await _qmp_powerdown_and_wait(qmp_sock, process)
