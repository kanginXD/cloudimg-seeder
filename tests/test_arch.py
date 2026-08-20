"""Tests for arch resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudimg_seeder.arch import (
    GuestArch,
    detect_arch_from_name,
    normalize_arch,
    resolve_arch,
)
from cloudimg_seeder.errors import QemuError


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("arm64", GuestArch.ARM64),
        ("aarch64", GuestArch.ARM64),
        ("ARM64", GuestArch.ARM64),
        ("amd64", GuestArch.AMD64),
        ("x86_64", GuestArch.AMD64),
        ("x86-64", GuestArch.AMD64),
        ("AMD64", GuestArch.AMD64),
    ],
)
def test_normalize_arch(value: str, expected: GuestArch) -> None:
    assert normalize_arch(value) is expected


def test_normalize_arch_invalid() -> None:
    with pytest.raises(QemuError, match="invalid arch"):
        normalize_arch("riscv64")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ubuntu-arm64.img", GuestArch.ARM64),
        ("cloud-aarch64.qcow2", GuestArch.ARM64),
        ("ubuntu-amd64.img", GuestArch.AMD64),
        ("disk-x86_64.img", GuestArch.AMD64),
        ("disk-x86-64.img", GuestArch.AMD64),
        ("plain.img", None),
    ],
)
def test_detect_arch_from_name(name: str, expected: GuestArch | None) -> None:
    assert detect_arch_from_name(name) is expected


def test_resolve_arch_explicit_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cloudimg_seeder.arch.detect_host_arch",
        lambda: GuestArch.ARM64,
    )
    disk = tmp_path / "ubuntu-arm64.img"
    disk.write_bytes(b"x")
    assert resolve_arch(disk, GuestArch.AMD64) is GuestArch.AMD64


def test_resolve_arch_from_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cloudimg_seeder.arch.detect_host_arch",
        lambda: GuestArch.AMD64,
    )
    disk = tmp_path / "ubuntu-arm64.img"
    disk.write_bytes(b"x")
    assert resolve_arch(disk, None) is GuestArch.ARM64


def test_resolve_arch_falls_back_to_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cloudimg_seeder.arch.detect_host_arch",
        lambda: GuestArch.AMD64,
    )
    disk = tmp_path / "plain.img"
    disk.write_bytes(b"x")
    assert resolve_arch(disk, None) is GuestArch.AMD64
