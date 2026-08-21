"""Guest architecture detection and normalization."""

from __future__ import annotations

import platform
from enum import StrEnum
from pathlib import Path

from cloudimg_seeder.errors import InvalidInputError


class GuestArch(StrEnum):
    ARM64 = "arm64"
    AMD64 = "amd64"


def normalize_arch(value: str) -> GuestArch:
    key = value.lower()
    if key in {"arm64", "aarch64"}:
        return GuestArch.ARM64
    if key in {"amd64", "x86_64", "x86-64"}:
        return GuestArch.AMD64
    raise InvalidInputError(f"invalid arch: {value} (use arm64 or amd64)")


def detect_host_arch() -> GuestArch:
    return normalize_arch(platform.machine())


def detect_arch_from_name(name: str) -> GuestArch | None:
    lower = name.lower()
    if "arm64" in lower or "aarch64" in lower:
        return GuestArch.ARM64
    if "amd64" in lower or "x86_64" in lower or "x86-64" in lower:
        return GuestArch.AMD64
    return None


def resolve_arch(disk: Path, explicit: GuestArch | None) -> GuestArch:
    """Resolve guest arch: explicit option, else filename, else host."""
    if explicit is not None:
        return explicit
    from_name = detect_arch_from_name(disk.name)
    if from_name is not None:
        return from_name
    return detect_host_arch()
