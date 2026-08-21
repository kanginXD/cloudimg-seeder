"""Tests for qemu-img wrappers."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from subprocess import CompletedProcess
from types import TracebackType

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

    monkeypatch.setattr(qemu_img, "_run", fake_run)
    info = qemu_img.image_info(path)
    assert info == ImageInfo(virtual_size=4096, format="qcow2")
    assert qemu_img.image_virtual_size(path) == 4096


def test_image_info_bad_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "disk.qcow2"
    path.write_bytes(b"x")

    def bad_run(_args: list[str]) -> CompletedProcess[str]:
        return CompletedProcess([], 0, stdout="not-json", stderr="")

    monkeypatch.setattr(qemu_img, "_run", bad_run)
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

    monkeypatch.setattr(qemu_img, "_run", fake_run)
    with pytest.raises(QemuError, match="image info"):
        qemu_img.image_info(path)


def test_convert_image_without_progress_passes_explicit_src_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "in.img"
    dst = tmp_path / "out" / "disk.raw"
    src.write_bytes(b"x")
    seen: list[list[str]] = []

    def fake_run(args: list[str]) -> CompletedProcess[str]:
        seen.append(args)
        return CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(qemu_img, "_run", fake_run)
    qemu_img.convert_image(src, dst, OutputFormat.RAW, src_format="qcow2")
    args = seen[0]
    assert args[:2] == ["convert", "-p"]
    assert args[args.index("-f") + 1] == "qcow2"
    assert args[args.index("-O") + 1] == "raw"
    assert dst.parent.is_dir()


def _fake_qemu_img_binary(_name: str) -> str:
    return "/usr/bin/qemu-img"


class _FakePopen:
    """Stand-in for subprocess.Popen used by _run_with_progress."""

    def __init__(
        self, stdout_lines: list[str], stderr_text: str, returncode: int
    ) -> None:
        self.stdout = iter(stdout_lines)
        self.stderr = StringIO(stderr_text)
        self.returncode = returncode

    def __call__(self, *_a: object, **_k: object) -> _FakePopen:
        return self

    def __enter__(self) -> _FakePopen:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False


def test_convert_image_with_progress_reports_updates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "in.img"
    dst = tmp_path / "out.qcow2"
    src.write_bytes(b"x")
    monkeypatch.setattr(qemu_img, "find_qemu_binary", _fake_qemu_img_binary)
    fake = _FakePopen(
        stdout_lines=["    (0.00/100%)\n", "    (50.00/100%)\n", "    (100.00/100%)\n"],
        stderr_text="",
        returncode=0,
    )
    monkeypatch.setattr(qemu_img.subprocess, "Popen", fake)
    updates: list[float] = []
    qemu_img.convert_image(
        src, dst, OutputFormat.QCOW2, src_format="raw", on_progress=updates.append
    )
    assert updates == [0.0, 50.0, 100.0]


def test_convert_image_with_progress_does_not_leak_to_caller_stdout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression: qemu-img's -p bar must never reach the process's own
    stdout, which the CLI uses to print the machine-readable result path."""
    src = tmp_path / "in.img"
    dst = tmp_path / "out.qcow2"
    src.write_bytes(b"x")
    seen_kwargs: dict[str, object] = {}

    def fake_binary(_name: str) -> str:
        return "/usr/bin/qemu-img"

    def spying_popen(*args: object, **kwargs: object) -> object:
        seen_kwargs.update(kwargs)
        return _FakePopen(["    (100.00/100%)\n"], "", 0)

    monkeypatch.setattr(qemu_img, "find_qemu_binary", fake_binary)
    monkeypatch.setattr(qemu_img.subprocess, "Popen", spying_popen)
    qemu_img.convert_image(
        src, dst, OutputFormat.QCOW2, src_format="raw", on_progress=lambda _p: None
    )
    assert seen_kwargs["stdout"] is qemu_img.subprocess.PIPE


def test_convert_image_with_progress_failure_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "in.img"
    dst = tmp_path / "out.qcow2"
    src.write_bytes(b"x")
    monkeypatch.setattr(qemu_img, "find_qemu_binary", _fake_qemu_img_binary)
    fake = _FakePopen(stdout_lines=[], stderr_text="boom", returncode=1)
    monkeypatch.setattr(qemu_img.subprocess, "Popen", fake)
    with pytest.raises(QemuError, match="boom"):
        qemu_img.convert_image(
            src, dst, OutputFormat.QCOW2, src_format="raw", on_progress=lambda _p: None
        )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("    (0.00/100%)\n    (100.00/100%)\n", [0.0, 100.0]),
        ("    (0.00/100%)\r    (50.00/100%)\r    (100.00/100%)\r", [0.0, 50.0, 100.0]),
    ],
)
def test_progress_regex_parses_both_line_endings(
    text: str, expected: list[float]
) -> None:
    assert [float(m) for m in qemu_img._PROGRESS_RE.findall(text)] == expected


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

    monkeypatch.setattr(qemu_img, "_run", fake_run)
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

    monkeypatch.setattr(qemu_img, "_run", fake_run)
    qemu_img.resize_image(path, "2K")
    assert not called


def test_run_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_binary(_name: str) -> str:
        return "/usr/bin/qemu-img"

    monkeypatch.setattr(qemu_img, "find_qemu_binary", fake_binary)

    def fake_subprocess(*_a: object, **_k: object) -> CompletedProcess[str]:
        return CompletedProcess([], 1, stdout="", stderr="boom")

    monkeypatch.setattr(qemu_img.subprocess, "run", fake_subprocess)
    with pytest.raises(QemuError, match="boom"):
        qemu_img._run(["info", "x"])
