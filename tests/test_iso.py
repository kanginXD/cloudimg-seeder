"""Tests for NoCloud CIDATA ISO construction."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pycdlib
import pytest
from pycdlib.pycdlibexception import PyCdlibInvalidInput

from cloudimg_seeder.iso import DEFAULT_INSTANCE_ID, build_seed_iso


def _read_joliet(iso_path: Path, joliet_path: str) -> bytes:
    iso = pycdlib.PyCdlib()
    iso.open(str(iso_path))
    try:
        buf = BytesIO()
        iso.get_file_from_iso_fp(buf, joliet_path=joliet_path)
        return buf.getvalue()
    finally:
        iso.close()


def test_build_seed_iso_with_meta(tmp_path: Path) -> None:
    dest = tmp_path / "seed.iso"
    build_seed_iso(dest, b"#cloud-config\n", b"instance-id: test\n")
    assert dest.is_file()
    assert _read_joliet(dest, "/user-data") == b"#cloud-config\n"
    assert _read_joliet(dest, "/meta-data") == b"instance-id: test\n"


def test_build_seed_iso_default_meta(tmp_path: Path) -> None:
    dest = tmp_path / "seed.iso"
    build_seed_iso(dest, b"user", None)
    meta = _read_joliet(dest, "/meta-data")
    assert meta == f"instance-id: {DEFAULT_INSTANCE_ID}\n".encode()


def test_build_seed_iso_with_vendor_data(tmp_path: Path) -> None:
    dest = tmp_path / "seed.iso"
    build_seed_iso(dest, b"#cloud-config\n", None, vendor_data=b"#cloud-config\nx: 1\n")
    assert _read_joliet(dest, "/vendor-data") == b"#cloud-config\nx: 1\n"


def test_build_seed_iso_without_vendor_data(tmp_path: Path) -> None:
    dest = tmp_path / "seed.iso"
    build_seed_iso(dest, b"#cloud-config\n", None)
    with pytest.raises(PyCdlibInvalidInput):
        _read_joliet(dest, "/vendor-data")
