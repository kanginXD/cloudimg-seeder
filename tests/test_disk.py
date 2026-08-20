"""Tests for disk format, size, and output path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudimg_seeder.disk import (
    OutputFormat,
    assert_grow_only,
    default_output_path,
    format_suffix,
    parse_size,
)
from cloudimg_seeder.errors import QemuError


def test_format_suffix() -> None:
    assert format_suffix(OutputFormat.QCOW2) == ".qcow2"
    assert format_suffix(OutputFormat.VPC) == ".vhd"
    assert format_suffix(OutputFormat.PARALLELS) == ".hdd"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("512", 512),
        ("1K", 1024),
        ("1M", 1024**2),
        ("20G", 20 * 1024**3),
        ("1t", 1024**4),
    ],
)
def test_parse_size(text: str, expected: int) -> None:
    assert parse_size(text) == expected


def test_parse_size_invalid() -> None:
    with pytest.raises(QemuError, match="invalid size"):
        parse_size("20GB")


def test_assert_grow_only_grows() -> None:
    assert assert_grow_only(1024, "2K") == 2048


def test_assert_grow_only_equal() -> None:
    assert assert_grow_only(2048, "2K") is None


def test_assert_grow_only_shrink() -> None:
    with pytest.raises(QemuError, match="refusing to shrink"):
        assert_grow_only(4096, "2K")


def test_default_output_path_non_clash(tmp_path: Path) -> None:
    disk = tmp_path / "image.img"
    disk.write_bytes(b"x")
    out = default_output_path(disk, OutputFormat.QCOW2, cwd=tmp_path)
    assert out == (tmp_path / "image.qcow2").resolve()


def test_default_output_path_clash(tmp_path: Path) -> None:
    disk = tmp_path / "image.qcow2"
    disk.write_bytes(b"x")
    out = default_output_path(disk, OutputFormat.QCOW2, cwd=tmp_path)
    assert out == (tmp_path / "image-cloudinit.qcow2").resolve()
