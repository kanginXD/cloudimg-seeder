"""Tests for qemu-img wrappers."""

from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from cloudimg_seeder import qemu_img
from cloudimg_seeder.disk import OutputFormat
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.qemu_img import ImageInfo


def test_image_info(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "disk.qcow2"
    path.write_bytes(b"x")

    def fake_run(args: list[str]) -> CompletedProcess[str]:
        return CompletedProcess(
            args,
            0,
            stdout=json.dumps({"virtual-size": 4096, "format": "qcow2"}),
            stderr="",
        )

    monkeypatch.setattr(qemu_img, "_run_qemu_img", fake_run)
    info = qemu_img.image_info(path)
    assert info == ImageInfo(virtual_size=4096, format="qcow2")
    assert qemu_img.image_virtual_size(path) == 4096


def test_image_info_bad_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "disk.qcow2"
    path.write_bytes(b"x")

    def bad_run(_args: list[str]) -> CompletedProcess[str]:
        return CompletedProcess([], 0, stdout="not-json", stderr="")

    monkeypatch.setattr(qemu_img, "_run_qemu_img", bad_run)
    with pytest.raises(QemuError, match="image info"):
        qemu_img.image_info(path)


def test_image_info_missing_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "disk.qcow2"
    path.write_bytes(b"x")

    def fake_run(args: list[str]) -> CompletedProcess[str]:
        return CompletedProcess(
            args, 0, stdout=json.dumps({"virtual-size": 4096}), stderr=""
        )

    monkeypatch.setattr(qemu_img, "_run_qemu_img", fake_run)
    with pytest.raises(QemuError, match="image info"):
        qemu_img.image_info(path)


def test_convert_image_passes_explicit_src_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "in.img"
    dst = tmp_path / "out" / "disk.raw"
    src.write_bytes(b"x")
    seen: list[tuple[list[str], bool]] = []

    def fake_run(args: list[str], *, capture_stdout: bool) -> CompletedProcess[str]:
        seen.append((args, capture_stdout))
        return CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(qemu_img, "_run", fake_run)
    qemu_img.convert_image(src, dst, OutputFormat.RAW, src_format="qcow2")
    args, capture_stdout = seen[0]
    assert args[:2] == ["convert", "-p"]
    assert "-f" in args
    assert args[args.index("-f") + 1] == "qcow2"
    assert "-O" in args
    assert args[args.index("-O") + 1] == "raw"
    assert capture_stdout is False
    assert dst.parent.is_dir()


def test_convert_image_inherits_stdout_for_progress_bar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "in.img"
    dst = tmp_path / "out.qcow2"
    src.write_bytes(b"x")
    seen_kwargs: dict[str, object] = {}

    def fake_binary(_name: str) -> str:
        return "/usr/bin/qemu-img"

    def fake_subprocess_run(
        _args: list[str], **kwargs: object
    ) -> CompletedProcess[str]:
        seen_kwargs.update(kwargs)
        return CompletedProcess([], 0, stdout=None, stderr="")

    monkeypatch.setattr(qemu_img, "find_qemu_binary", fake_binary)
    monkeypatch.setattr(qemu_img.subprocess, "run", fake_subprocess_run)
    qemu_img.convert_image(src, dst, OutputFormat.QCOW2, src_format="raw")
    assert seen_kwargs["stdout"] is None


def test_resize_image_grows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "disk.qcow2"
    path.write_bytes(b"x")

    def info_of(_path: Path) -> ImageInfo:
        return ImageInfo(virtual_size=1024, format="qcow2")

    monkeypatch.setattr(qemu_img, "image_info", info_of)
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

    def info_of(_path: Path) -> ImageInfo:
        return ImageInfo(virtual_size=2048, format="qcow2")

    monkeypatch.setattr(qemu_img, "image_info", info_of)
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
