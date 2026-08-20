"""Tests for EDK2 firmware discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.firmware import (
    find_edk2_aarch64_code,
    find_edk2_aarch64_vars,
    firmware_search_dirs,
    prepare_edk2_aarch64_vars,
)


def test_find_code_via_qemu_datadir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = tmp_path / "edk2-aarch64-code.fd"
    code.write_bytes(b"code")
    monkeypatch.setenv("QEMU_DATADIR", str(tmp_path))

    def fake_binary(_name: str) -> str:
        return "/usr/bin/qemu-system-aarch64"

    def no_datadir(_binary: str) -> None:
        return None

    monkeypatch.setattr("cloudimg_seeder.firmware.find_qemu_binary", fake_binary)
    monkeypatch.setattr("cloudimg_seeder.firmware._print_datadir", no_datadir)
    monkeypatch.setattr("cloudimg_seeder.firmware._brew_qemu_share", lambda: None)
    assert find_edk2_aarch64_code() == code


def test_find_code_binary_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindir = tmp_path / "bin"
    share = tmp_path / "share" / "qemu"
    share.mkdir(parents=True)
    bindir.mkdir()
    binary = bindir / "qemu-system-aarch64"
    binary.write_bytes(b"x")
    code = share / "AAVMF_CODE.fd"
    code.write_bytes(b"code")
    monkeypatch.delenv("QEMU_DATADIR", raising=False)

    def no_datadir(_binary: str) -> None:
        return None

    monkeypatch.setattr("cloudimg_seeder.firmware._print_datadir", no_datadir)
    monkeypatch.setattr("cloudimg_seeder.firmware._brew_qemu_share", lambda: None)
    assert find_edk2_aarch64_code(str(binary)) == code


def test_find_code_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QEMU_DATADIR", raising=False)

    def empty_dirs(_binary: str | None = None) -> list[Path]:
        return []

    monkeypatch.setattr(
        "cloudimg_seeder.firmware.firmware_search_dirs",
        empty_dirs,
    )
    with pytest.raises(QemuError, match="EDK2 aarch64 firmware not found"):
        find_edk2_aarch64_code()


def test_find_vars_next_to_code(tmp_path: Path) -> None:
    code = tmp_path / "edk2-aarch64-code.fd"
    vars_fd = tmp_path / "edk2-aarch64-vars.fd"
    code.write_bytes(b"c")
    vars_fd.write_bytes(b"v")
    assert find_edk2_aarch64_vars(code) == vars_fd


def test_prepare_vars_copy(tmp_path: Path) -> None:
    code = tmp_path / "edk2-aarch64-code.fd"
    vars_src = tmp_path / "edk2-aarch64-vars.fd"
    code.write_bytes(b"c")
    vars_src.write_bytes(b"vars-template")
    dest = tmp_path / "out-vars.fd"
    prepare_edk2_aarch64_vars(dest, code)
    assert dest.read_bytes() == b"vars-template"


def test_prepare_vars_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_vars(_code: Path | None = None) -> None:
        return None

    monkeypatch.setattr(
        "cloudimg_seeder.firmware.find_edk2_aarch64_vars",
        no_vars,
    )
    dest = tmp_path / "empty-vars.fd"
    prepare_edk2_aarch64_vars(dest)
    assert dest.stat().st_size == 64 * 1024 * 1024


def test_firmware_search_dirs_includes_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QEMU_DATADIR", str(tmp_path))

    def missing_binary(_name: str) -> str:
        raise QemuError("missing")

    monkeypatch.setattr("cloudimg_seeder.firmware.find_qemu_binary", missing_binary)
    monkeypatch.setattr("cloudimg_seeder.firmware._brew_qemu_share", lambda: None)
    dirs = firmware_search_dirs()
    assert tmp_path in dirs
