"""Tests for qemu-img wrappers."""

from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from cloudimg_seeder import qemu_img
from cloudimg_seeder.disk import OutputFormat
from cloudimg_seeder.errors import QemuError


def test_image_virtual_size(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "disk.qcow2"
    path.write_bytes(b"x")

    def fake_run(args: list[str]) -> CompletedProcess[str]:
        return CompletedProcess(
            args, 0, stdout=json.dumps({"virtual-size": 4096}), stderr=""
        )

    monkeypatch.setattr(qemu_img, "_run_qemu_img", fake_run)
    assert qemu_img.image_virtual_size(path) == 4096


def test_image_virtual_size_bad_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "disk.qcow2"
    path.write_bytes(b"x")

    def bad_run(_args: list[str]) -> CompletedProcess[str]:
        return CompletedProcess([], 0, stdout="not-json", stderr="")

    monkeypatch.setattr(qemu_img, "_run_qemu_img", bad_run)
    with pytest.raises(QemuError, match="virtual size"):
        qemu_img.image_virtual_size(path)


def test_convert_image_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "in.img"
    dst = tmp_path / "out" / "disk.raw"
    src.write_bytes(b"x")
    seen: list[list[str]] = []

    def fake_run(args: list[str]) -> CompletedProcess[str]:
        seen.append(args)
        return CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(qemu_img, "_run_qemu_img", fake_run)
    qemu_img.convert_image(src, dst, OutputFormat.RAW)
    assert seen[0][:3] == ["convert", "-p", "-O"]
    assert seen[0][3] == "raw"
    assert dst.parent.is_dir()


def test_resize_image_grows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "disk.qcow2"
    path.write_bytes(b"x")

    def size_of(_path: Path) -> int:
        return 1024

    monkeypatch.setattr(qemu_img, "image_virtual_size", size_of)
    seen: list[list[str]] = []

    def fake_run(args: list[str]) -> CompletedProcess[str]:
        seen.append(args)
        return CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(qemu_img, "_run_qemu_img", fake_run)
    qemu_img.resize_image(path, "2K")
    assert seen[0][0] == "resize"


def test_resize_image_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "disk.qcow2"
    path.write_bytes(b"x")

    def size_of(_path: Path) -> int:
        return 2048

    monkeypatch.setattr(qemu_img, "image_virtual_size", size_of)
    called = False

    def fake_run(args: list[str]) -> CompletedProcess[str]:
        nonlocal called
        called = True
        return CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(qemu_img, "_run_qemu_img", fake_run)
    qemu_img.resize_image(path, "2K")
    assert not called


def test_run_qemu_img_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_binary(_name: str) -> str:
        return "/usr/bin/qemu-img"

    monkeypatch.setattr(qemu_img, "find_qemu_binary", fake_binary)

    def fake_subprocess(*_a: object, **_k: object) -> CompletedProcess[str]:
        return CompletedProcess([], 1, stdout="", stderr="boom")

    monkeypatch.setattr(qemu_img.subprocess, "run", fake_subprocess)
    with pytest.raises(QemuError, match="boom"):
        qemu_img._run_qemu_img(["info", "x"])
