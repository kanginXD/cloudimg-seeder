"""Host OS helpers: QEMU binaries, install hints, and acceleration."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

from cloudimg_seeder.arch import GuestArch, detect_host_arch
from cloudimg_seeder.errors import QemuError


def qemu_install_hint() -> str:
    system = platform.system()
    if system == "Darwin":
        return "brew install qemu"
    if system == "Linux":
        return (
            "install qemu-system (and qemu-efi-aarch64 or edk2-aarch64 "
            "for arm64 guests) via your package manager"
        )
    if system == "Windows":
        return (
            "winget install SoftwareFreedomConservancy.QEMU "
            "and ensure qemu-img is on PATH"
        )
    return "install QEMU and ensure qemu-img is on PATH"


def _windows_qemu_dirs() -> list[Path]:
    dirs: list[Path] = []
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(key)
        if root:
            dirs.append(Path(root) / "qemu")
    return dirs


def find_qemu_binary(name: str) -> str:
    """Locate a QEMU binary on PATH, or under Windows Program Files."""
    path = shutil.which(name)
    if path is not None:
        return path
    if platform.system() == "Windows":
        for directory in _windows_qemu_dirs():
            for candidate in (directory / f"{name}.exe", directory / name):
                if candidate.is_file():
                    return str(candidate)
    raise QemuError(f"missing '{name}'. Install with: {qemu_install_hint()}")


def prefer_native_accel(guest: GuestArch) -> bool:
    return guest is detect_host_arch()


def _whpx_available() -> bool:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    dll = Path(windir) / "System32" / "WinHvPlatform.dll"
    return dll.is_file()


def host_accel() -> str:
    """Return the preferred host accelerator name (hvf, kvm, whpx, or tcg)."""
    system = platform.system()
    if system == "Darwin":
        return "hvf"
    if system == "Linux":
        kvm = Path("/dev/kvm")
        if kvm.exists() and os.access(kvm, os.R_OK | os.W_OK):
            return "kvm"
        return "tcg"
    if system == "Windows":
        if _whpx_available():
            return "whpx"
        return "tcg"
    return "tcg"


def accel_for_guest(guest: GuestArch) -> str:
    """Accelerator for guest; falls back to tcg when guest arch differs from host."""
    if not prefer_native_accel(guest):
        return "tcg"
    return host_accel()


def accel_qemu_arg(accel: str) -> str:
    """Value for -accel (or machine accel=) including WHPX irqchip option."""
    if accel == "whpx":
        return "whpx,kernel-irqchip=off"
    return accel
