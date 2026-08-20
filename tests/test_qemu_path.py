"""Tests for QEMU drive path escaping."""

from __future__ import annotations

from pathlib import Path

from cloudimg_seeder.qemu_path import qemu_drive_path


def test_qemu_drive_path_forward_slashes(tmp_path: Path) -> None:
    path = tmp_path / "disk.qcow2"
    path.write_bytes(b"x")
    escaped = qemu_drive_path(path)
    assert "\\" not in escaped
    assert escaped.endswith("/disk.qcow2")


def test_qemu_drive_path_escapes_comma(tmp_path: Path) -> None:
    path = tmp_path / "a,b.qcow2"
    path.write_bytes(b"x")
    escaped = qemu_drive_path(path)
    assert ",," in escaped
    assert escaped.count(",") >= 2
