"""Tests for seed orchestration with injectable backends."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.disk import OutputFormat
from cloudimg_seeder.errors import QemuError, SeedError
from cloudimg_seeder.seeder import SeedConfig, seed


class FakeImages:
    def __init__(self, virtual_size: int = 1024) -> None:
        self.virtual_size_value = virtual_size
        self.converted: list[tuple[Path, Path]] = []
        self.resized: list[tuple[Path, str]] = []
        self.final_converts: list[tuple[Path, Path, OutputFormat]] = []

    def virtual_size(self, path: Path) -> int:
        return self.virtual_size_value

    def convert_to_qcow2(self, src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"qcow2")
        self.converted.append((src, dst))

    def convert_image(self, src: Path, dst: Path, fmt: OutputFormat) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(fmt.value.encode())
        self.final_converts.append((src, dst, fmt))

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
            quiet=True,
            serial_log=log,
        ),
        images=FakeImages(),
        run_guest=capture_guest,
    )
    assert seen.get("quiet") is True
    assert seen.get("serial_log") == log


@pytest.mark.asyncio
async def test_seed_raw_converts(
    tmp_path: Path,
    inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disk, user = inputs
    out = tmp_path / "out.raw"
    images = FakeImages()
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
    assert len(images.final_converts) == 1


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
