"""Tests for seed orchestration with injectable backends."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.console import SerialLogFormat, SerialOptions
from cloudimg_seeder.disk import OutputFormat
from cloudimg_seeder.errors import CloudInitError, QemuError, SeedError
from cloudimg_seeder.probe import VENDOR_DATA
from cloudimg_seeder.seeder import SeedConfig, seed


class FakeImages:
    def __init__(self, virtual_size: int = 1024, image_format: str = "raw") -> None:
        self.virtual_size_value = virtual_size
        self.image_format_value = image_format
        self.converted: list[tuple[Path, Path, OutputFormat]] = []
        self.resized: list[tuple[Path, str]] = []

    def virtual_size(self, path: Path) -> int:
        return self.virtual_size_value

    def image_format(self, path: Path) -> str:
        return self.image_format_value

    def convert(self, src: Path, dst: Path, fmt: OutputFormat) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(fmt.value.encode())
        self.converted.append((src, dst, fmt))

    def resize(self, path: Path, size: str) -> None:
        self.resized.append((path, size))


async def _noop_guest(**_kwargs: object) -> None:
    return None


def _fake_qemu_img(_name: str) -> str:
    return "/usr/bin/qemu-img"


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Path]:
    disk = tmp_path / "ubuntu-amd64.img"
    user = tmp_path / "user-data.yml"
    disk.write_bytes(b"disk")
    user.write_text("#cloud-config\n")
    return disk, user


@pytest.mark.asyncio
async def test_seed_passes_serial_options(
    tmp_path: Path,
    inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disk, user = inputs
    out = tmp_path / "out.qcow2"
    log = tmp_path / "serial.log"
    seen: dict[str, object] = {}

    async def capture_guest(**kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(
        "cloudimg_seeder.seeder.find_qemu_binary",
        _fake_qemu_img,
    )
    await seed(
        SeedConfig(
            disk=disk,
            user_data=user,
            output=out,
            arch=GuestArch.AMD64,
            show_serial=False,
            serial_log=log,
            serial_log_format=SerialLogFormat.RAW,
        ),
        images=FakeImages(),
        run_guest=capture_guest,
    )
    serial = seen.get("serial")
    assert isinstance(serial, SerialOptions)
    assert serial.show_serial is False
    assert serial.serial_log == log
    assert serial.serial_log_format is SerialLogFormat.RAW


@pytest.mark.asyncio
async def test_seed_passes_idle_timeout_and_strict(
    tmp_path: Path,
    inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disk, user = inputs
    out = tmp_path / "out.qcow2"
    seen: dict[str, object] = {}

    async def capture_guest(**kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(
        "cloudimg_seeder.seeder.find_qemu_binary",
        _fake_qemu_img,
    )
    await seed(
        SeedConfig(
            disk=disk,
            user_data=user,
            output=out,
            arch=GuestArch.AMD64,
            idle_timeout_sec=300,
            strict=True,
        ),
        images=FakeImages(),
        run_guest=capture_guest,
    )
    assert seen.get("idle_timeout_sec") == 300.0
    assert seen.get("strict") is True


@pytest.mark.asyncio
async def test_seed_default_idle_timeout_is_none(
    tmp_path: Path,
    inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disk, user = inputs
    out = tmp_path / "out.qcow2"
    seen: dict[str, object] = {}

    async def capture_guest(**kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(
        "cloudimg_seeder.seeder.find_qemu_binary",
        _fake_qemu_img,
    )
    await seed(
        SeedConfig(disk=disk, user_data=user, output=out, arch=GuestArch.AMD64),
        images=FakeImages(),
        run_guest=capture_guest,
    )
    assert seen.get("idle_timeout_sec") is None
    assert seen.get("strict") is False


@pytest.mark.asyncio
async def test_seed_writes_vendor_data_probe(
    tmp_path: Path,
    inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disk, user = inputs
    out = tmp_path / "out.qcow2"
    seen: dict[str, object] = {}

    def capture_iso(
        dest: Path, _user_data: bytes, _meta_data: bytes | None, **kwargs: object
    ) -> Path:
        seen.update(kwargs)
        dest.write_bytes(b"iso")
        return dest

    monkeypatch.setattr(
        "cloudimg_seeder.seeder.find_qemu_binary",
        _fake_qemu_img,
    )
    monkeypatch.setattr("cloudimg_seeder.seeder.build_seed_iso", capture_iso)
    await seed(
        SeedConfig(disk=disk, user_data=user, output=out, arch=GuestArch.AMD64),
        images=FakeImages(),
        run_guest=_noop_guest,
    )
    assert seen.get("vendor_data") == VENDOR_DATA


@pytest.mark.asyncio
async def test_seed_converts_source_with_explicit_format(
    tmp_path: Path,
    inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disk, user = inputs
    out = tmp_path / "out.raw"
    images = FakeImages(image_format="vmdk")
    monkeypatch.setattr(
        "cloudimg_seeder.seeder.find_qemu_binary",
        _fake_qemu_img,
    )
    result = await seed(
        SeedConfig(
            disk=disk,
            user_data=user,
            output=out,
            arch=GuestArch.AMD64,
            output_format=OutputFormat.RAW,
            size="2K",
        ),
        images=images,
        run_guest=_noop_guest,
    )
    assert result == out.resolve()
    assert out.read_bytes() == b"raw"
    assert len(images.resized) == 1
    # source -> qcow2, then qcow2 -> raw
    assert [c[2] for c in images.converted] == [OutputFormat.QCOW2, OutputFormat.RAW]


@pytest.mark.asyncio
async def test_seed_shrink_rejected(
    tmp_path: Path,
    inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disk, user = inputs
    images = FakeImages(virtual_size=10_000)
    monkeypatch.setattr(
        "cloudimg_seeder.seeder.find_qemu_binary",
        _fake_qemu_img,
    )
    with pytest.raises(SeedError, match="refusing to shrink"):
        await seed(
            SeedConfig(
                disk=disk,
                user_data=user,
                output=tmp_path / "o.qcow2",
                size="1K",
            ),
            images=images,
            run_guest=_noop_guest,
        )


@pytest.mark.asyncio
async def test_seed_invalid_size_maps_to_seed_error(
    tmp_path: Path,
    inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disk, user = inputs
    monkeypatch.setattr(
        "cloudimg_seeder.seeder.find_qemu_binary",
        _fake_qemu_img,
    )
    with pytest.raises(SeedError, match="invalid size"):
        await seed(
            SeedConfig(
                disk=disk,
                user_data=user,
                output=tmp_path / "o.qcow2",
                size="20GB",
            ),
            images=FakeImages(),
            run_guest=_noop_guest,
        )


@pytest.mark.asyncio
async def test_seed_missing_disk(tmp_path: Path) -> None:
    user = tmp_path / "user-data.yml"
    user.write_text("x")
    with pytest.raises(SeedError, match="disk not found"):
        await seed(
            SeedConfig(disk=tmp_path / "missing.img", user_data=user),
            images=FakeImages(),
            run_guest=_noop_guest,
        )


@pytest.mark.asyncio
async def test_seed_missing_user_data(tmp_path: Path) -> None:
    disk = tmp_path / "disk.img"
    disk.write_bytes(b"x")
    with pytest.raises(SeedError, match="user-data not found"):
        await seed(
            SeedConfig(disk=disk, user_data=tmp_path / "missing.yml"),
            images=FakeImages(),
            run_guest=_noop_guest,
        )


@pytest.mark.asyncio
async def test_seed_maps_qemu_error(
    tmp_path: Path,
    inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disk, user = inputs
    monkeypatch.setattr(
        "cloudimg_seeder.seeder.find_qemu_binary",
        _fake_qemu_img,
    )

    async def boom(**_kwargs: object) -> None:
        raise QemuError("guest failed")

    with pytest.raises(SeedError, match="guest failed"):
        await seed(
            SeedConfig(
                disk=disk,
                user_data=user,
                output=tmp_path / "o.qcow2",
                arch=GuestArch.AMD64,
            ),
            images=FakeImages(),
            run_guest=boom,
        )


@pytest.mark.asyncio
async def test_seed_maps_cloud_init_error(
    tmp_path: Path,
    inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disk, user = inputs
    monkeypatch.setattr(
        "cloudimg_seeder.seeder.find_qemu_binary",
        _fake_qemu_img,
    )

    async def boom(**_kwargs: object) -> None:
        raise CloudInitError("cloud-init failed (exit 1)")

    with pytest.raises(SeedError, match="cloud-init failed"):
        await seed(
            SeedConfig(
                disk=disk,
                user_data=user,
                output=tmp_path / "o.qcow2",
                arch=GuestArch.AMD64,
            ),
            images=FakeImages(),
            run_guest=boom,
        )
