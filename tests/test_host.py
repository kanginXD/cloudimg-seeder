"""Tests for host accel, binary lookup, and install hints."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.host import (
    accel_for_guest,
    find_qemu_binary,
    host_accel,
    qemu_install_hint,
)


def test_qemu_install_hint_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cloudimg_seeder.host.platform.system", lambda: "Darwin")
    assert "brew" in qemu_install_hint()


def test_qemu_install_hint_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cloudimg_seeder.host.platform.system", lambda: "Linux")
    hint = qemu_install_hint()
    assert "qemu" in hint.lower()


def test_qemu_install_hint_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cloudimg_seeder.host.platform.system", lambda: "Windows")
    assert "winget" in qemu_install_hint()


def test_host_accel_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cloudimg_seeder.host.platform.system", lambda: "Darwin")
    assert host_accel() == "hvf"


def test_host_accel_linux_kvm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cloudimg_seeder.host.platform.system", lambda: "Linux")
    kvm = MagicMock()
    kvm.exists.return_value = True

    def path_factory(p: str | Path) -> Any:
        return kvm if str(p) == "/dev/kvm" else Path(p)

    def always_access(*_args: object, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr("cloudimg_seeder.host.Path", path_factory)
    monkeypatch.setattr("cloudimg_seeder.host.os.access", always_access)
    assert host_accel() == "kvm"


def test_host_accel_linux_no_kvm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cloudimg_seeder.host.platform.system", lambda: "Linux")
    kvm = MagicMock()
    kvm.exists.return_value = False

    def path_factory(p: str | Path) -> Any:
        return kvm if str(p) == "/dev/kvm" else Path(p)

    monkeypatch.setattr("cloudimg_seeder.host.Path", path_factory)
    assert host_accel() == "tcg"


def test_host_accel_windows_whpx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cloudimg_seeder.host.platform.system", lambda: "Windows")
    windir = tmp_path / "Windows"
    dll = windir / "System32" / "WinHvPlatform.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"x")
    monkeypatch.delenv("SYSTEMROOT", raising=False)
    monkeypatch.setenv("WINDIR", str(windir))
    assert host_accel() == "whpx"


def test_host_accel_windows_prefers_systemroot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cloudimg_seeder.host.platform.system", lambda: "Windows")
    windir = tmp_path / "Windows"
    dll = windir / "System32" / "WinHvPlatform.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"x")
    monkeypatch.setenv("SYSTEMROOT", str(windir))
    monkeypatch.setenv("WINDIR", str(tmp_path / "wrong"))
    assert host_accel() == "whpx"


def test_host_accel_windows_no_whpx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cloudimg_seeder.host.platform.system", lambda: "Windows")
    windir = tmp_path / "Windows"
    (windir / "System32").mkdir(parents=True)
    monkeypatch.delenv("SYSTEMROOT", raising=False)
    monkeypatch.setenv("WINDIR", str(windir))
    assert host_accel() == "tcg"


def test_host_accel_other(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cloudimg_seeder.host.platform.system", lambda: "FreeBSD")
    assert host_accel() == "tcg"


def test_accel_for_guest_cross_arch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cloudimg_seeder.host.detect_host_arch",
        lambda: GuestArch.AMD64,
    )
    monkeypatch.setattr("cloudimg_seeder.host.host_accel", lambda: "kvm")
    assert accel_for_guest(GuestArch.ARM64) == "tcg"


def test_accel_for_guest_same_arch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cloudimg_seeder.host.detect_host_arch",
        lambda: GuestArch.AMD64,
    )
    monkeypatch.setattr("cloudimg_seeder.host.host_accel", lambda: "kvm")
    assert accel_for_guest(GuestArch.AMD64) == "kvm"


def test_find_qemu_binary_which(monkeypatch: pytest.MonkeyPatch) -> None:
    def which(name: str) -> str:
        return f"/usr/bin/{name}"

    monkeypatch.setattr("cloudimg_seeder.host.shutil.which", which)
    assert find_qemu_binary("qemu-img") == "/usr/bin/qemu-img"


def test_find_qemu_binary_windows_program_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cloudimg_seeder.host.platform.system", lambda: "Windows")

    def which(_name: str) -> None:
        return None

    monkeypatch.setattr("cloudimg_seeder.host.shutil.which", which)
    pf = tmp_path / "Program Files" / "qemu"
    pf.mkdir(parents=True)
    exe = pf / "qemu-img.exe"
    exe.write_bytes(b"x")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert find_qemu_binary("qemu-img") == str(exe)


def test_find_qemu_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cloudimg_seeder.host.platform.system", lambda: "Linux")

    def which(_name: str) -> None:
        return None

    monkeypatch.setattr("cloudimg_seeder.host.shutil.which", which)
    with pytest.raises(QemuError, match="missing"):
        find_qemu_binary("qemu-img")
