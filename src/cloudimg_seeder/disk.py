"""Disk image formats, size parsing, and default output paths."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

from cloudimg_seeder.errors import QemuError


class OutputFormat(str, Enum):
    """Local disk image formats suitable as hypervisor disk files.

    Excludes qemu-img protocol and filter drivers (http, nbd, vvfat, …).
    """

    QCOW2 = "qcow2"
    QCOW = "qcow"
    QED = "qed"
    RAW = "raw"
    VMDK = "vmdk"
    VHDX = "vhdx"
    VDI = "vdi"
    VPC = "vpc"
    PARALLELS = "parallels"
    DMG = "dmg"


_FORMAT_SUFFIX: dict[OutputFormat, str] = {
    OutputFormat.QCOW2: ".qcow2",
    OutputFormat.QCOW: ".qcow",
    OutputFormat.QED: ".qed",
    OutputFormat.RAW: ".raw",
    OutputFormat.VMDK: ".vmdk",
    OutputFormat.VHDX: ".vhdx",
    OutputFormat.VDI: ".vdi",
    OutputFormat.VPC: ".vhd",
    OutputFormat.PARALLELS: ".hdd",
    OutputFormat.DMG: ".dmg",
}

_SIZE_RE = re.compile(r"^(\d+)([bBkKmMgGtTpPeE])?$")
_SIZE_SUFFIX_BYTES = {
    "b": 1,
    "k": 1024,
    "m": 1024**2,
    "g": 1024**3,
    "t": 1024**4,
    "p": 1024**5,
    "e": 1024**6,
}


def format_suffix(fmt: OutputFormat) -> str:
    return _FORMAT_SUFFIX[fmt]


def default_output_path(
    disk: Path,
    fmt: OutputFormat = OutputFormat.QCOW2,
    cwd: Path | None = None,
) -> Path:
    """Return cwd/{stem}{ext}, or {stem}-cloudinit{ext} if that equals disk."""
    base = cwd if cwd is not None else Path.cwd()
    stem = disk.stem if disk.suffix else disk.name
    ext = format_suffix(fmt)
    out = (base / f"{stem}{ext}").resolve()
    if disk.resolve() == out:
        out = (base / f"{stem}-cloudinit{ext}").resolve()
    return out


def parse_size(size: str) -> int:
    """Parse a qemu-img absolute SIZE string to bytes (1024-based suffixes)."""
    text = size.strip()
    match = _SIZE_RE.fullmatch(text)
    if match is None:
        raise QemuError(f"invalid size: {size!r} (use qemu-img form, e.g. 20G or 512M)")
    value = int(match.group(1))
    suffix = (match.group(2) or "b").lower()
    return value * _SIZE_SUFFIX_BYTES[suffix]


def assert_grow_only(current_bytes: int, target_size: str) -> int | None:
    """Validate grow-only resize.

    Returns target bytes when growth is needed, or None when size is unchanged.
    Raises QemuError when the target would shrink.
    """
    target = parse_size(target_size)
    if target < current_bytes:
        raise QemuError(
            f"refusing to shrink disk: target {target_size} ({target} bytes) < "
            f"current {current_bytes} bytes"
        )
    if target == current_bytes:
        return None
    return target
