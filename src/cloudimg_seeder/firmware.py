"""EDK2 aarch64 firmware discovery for QEMU."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.host import find_qemu_binary, qemu_install_hint

_EMPTY_VARS_BYTES = 64 * 1024 * 1024

_CODE_NAMES = (
    "edk2-aarch64-code.fd",
    "AAVMF_CODE.fd",
    "QEMU_EFI.fd",
    "QEMU_EFI-pflash.raw",
)

_VARS_NAMES = (
    "edk2-aarch64-vars.fd",
    "AAVMF_VARS.fd",
    "QEMU_VARS.fd",
)


def _brew_qemu_share() -> Path | None:
    if shutil.which("brew") is None:
        return None
    try:
        result = subprocess.run(
            ["brew", "--prefix", "qemu"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    prefix = result.stdout.strip()
    if not prefix:
        return None
    return Path(prefix) / "share" / "qemu"


def _print_datadir(binary: str) -> Path | None:
    try:
        result = subprocess.run(
            [binary, "-print-datadir"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_dir() else None


def _dirs_from_binary(binary: str) -> list[Path]:
    bindir = Path(binary).resolve().parent
    return [
        bindir / "share" / "qemu",
        bindir.parent / "share" / "qemu",
        bindir / "share",
    ]


def firmware_search_dirs(binary: str | None = None) -> list[Path]:
    """Ordered candidate directories for EDK2 aarch64 firmware files."""
    dirs: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        resolved = path
        if resolved in seen:
            return
        seen.add(resolved)
        dirs.append(resolved)

    env = os.environ.get("QEMU_DATADIR")
    if env:
        add(Path(env))

    if binary is None:
        try:
            binary = find_qemu_binary("qemu-system-aarch64")
        except QemuError:
            binary = None

    if binary is not None:
        for d in _dirs_from_binary(binary):
            add(d)
        add(_print_datadir(binary))

    add(_brew_qemu_share())
    for fixed in (
        Path("/usr/share/qemu"),
        Path("/usr/share/AAVMF"),
        Path("/usr/share/qemu-efi-aarch64"),
        Path("/usr/share/edk2/aarch64"),
        Path("/opt/homebrew/share/qemu"),
        Path("/usr/local/share/qemu"),
    ):
        add(fixed)

    return dirs


def find_edk2_aarch64_code(binary: str | None = None) -> Path:
    for directory in firmware_search_dirs(binary):
        for name in _CODE_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    raise QemuError(
        f"EDK2 aarch64 firmware not found. Install with: {qemu_install_hint()}"
    )


def find_edk2_aarch64_vars(code: Path | None = None) -> Path | None:
    """Locate a vars template next to code or in search dirs; None if missing."""
    if code is not None:
        for name in _VARS_NAMES:
            candidate = code.parent / name
            if candidate.is_file():
                return candidate
    for directory in firmware_search_dirs():
        for name in _VARS_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def prepare_edk2_aarch64_vars(dest: Path, code: Path | None = None) -> Path:
    """Copy the EDK2 vars template to dest, or create a 64 MiB empty store."""
    vars_src = find_edk2_aarch64_vars(code)
    if vars_src is not None:
        shutil.copy(vars_src, dest)
    else:
        dest.write_bytes(b"\0" * _EMPTY_VARS_BYTES)
    return dest
