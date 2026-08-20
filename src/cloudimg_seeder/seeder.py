"""Seed orchestration: NoCloud ISO, qcow2 work copy, headless boot, convert."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cloudimg_seeder.arch import GuestArch, resolve_arch
from cloudimg_seeder.disk import (
    OutputFormat,
    assert_grow_only,
    default_output_path,
)
from cloudimg_seeder.errors import QemuError, SeedError
from cloudimg_seeder.guest import run_headless_qemu
from cloudimg_seeder.host import find_qemu_binary
from cloudimg_seeder.iso import build_seed_iso
from cloudimg_seeder.qemu_img import convert_image, convert_to_qcow2, image_virtual_size
from cloudimg_seeder.qemu_img import resize_image as default_resize_image

logger = logging.getLogger("cloudimg_seeder")

__all__ = ["SeedConfig", "SeedError", "seed"]


@dataclass(frozen=True)
class SeedConfig:
    disk: Path
    user_data: Path
    meta_data: Path | None = None
    output: Path | None = None
    arch: GuestArch | None = None
    size: str | None = None
    output_format: OutputFormat = OutputFormat.QCOW2
    cpus: int = 2
    memory_mb: int = 2048
    timeout_sec: int = 1200
    quiet: bool = False
    serial_log: Path | None = None


class ImageOps(Protocol):
    def virtual_size(self, path: Path) -> int: ...

    def convert_to_qcow2(self, src: Path, dst: Path) -> None: ...

    def convert_image(self, src: Path, dst: Path, fmt: OutputFormat) -> None: ...

    def resize(self, path: Path, size: str) -> None: ...


GuestRunner = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class DefaultImageOps:
    def virtual_size(self, path: Path) -> int:
        return image_virtual_size(path)

    def convert_to_qcow2(self, src: Path, dst: Path) -> None:
        convert_to_qcow2(src, dst)

    def convert_image(self, src: Path, dst: Path, fmt: OutputFormat) -> None:
        convert_image(src, dst, fmt)

    def resize(self, path: Path, size: str) -> None:
        default_resize_image(path, size)


async def seed(
    config: SeedConfig,
    *,
    images: ImageOps | None = None,
    run_guest: GuestRunner | None = None,
) -> Path:
    """Apply NoCloud cloud-init once and return the output disk path.

    Leaves ``config.disk`` unchanged. Seeds via a qcow2 working copy, then
    converts to ``output_format`` when it is not qcow2. On failure a partial
    output may remain.
    """
    images = images if images is not None else DefaultImageOps()
    run_guest = run_guest if run_guest is not None else run_headless_qemu

    if not config.disk.is_file():
        raise SeedError(f"disk not found: {config.disk}")
    if not config.user_data.is_file():
        raise SeedError(f"user-data not found: {config.user_data}")
    if config.meta_data is not None and not config.meta_data.is_file():
        raise SeedError(f"meta-data not found: {config.meta_data}")

    try:
        find_qemu_binary("qemu-img")

        disk = config.disk.resolve()
        user_data = config.user_data.resolve()
        meta_data = config.meta_data.resolve() if config.meta_data else None
        guest_arch = resolve_arch(disk, config.arch)
        out_fmt = config.output_format
        out_disk = (
            config.output.resolve()
            if config.output is not None
            else default_output_path(disk, out_fmt)
        )

        if config.size is not None:
            current = images.virtual_size(disk)
            assert_grow_only(current, config.size)

        logger.info("guest arch: %s", guest_arch.value)
        logger.info("output format: %s", out_fmt.value)
        logger.info("output: %s", out_disk)

        user_bytes = user_data.read_bytes()
        meta_bytes = meta_data.read_bytes() if meta_data is not None else None

        with tempfile.TemporaryDirectory(prefix="cloudimg-seeder-") as tmp:
            workdir = Path(tmp)
            seed_iso = workdir / "seed.iso"
            build_seed_iso(seed_iso, user_bytes, meta_bytes)

            if out_fmt is OutputFormat.QCOW2:
                work_qcow2 = out_disk
            else:
                work_qcow2 = workdir / "seeded.qcow2"

            images.convert_to_qcow2(disk, work_qcow2)
            if config.size is not None:
                images.resize(work_qcow2, config.size)
            await run_guest(
                arch=guest_arch,
                disk=work_qcow2,
                seed_iso=seed_iso,
                workdir=workdir,
                cpus=config.cpus,
                memory_mb=config.memory_mb,
                timeout_sec=float(config.timeout_sec),
                quiet=config.quiet,
                serial_log=config.serial_log,
            )
            if out_fmt is not OutputFormat.QCOW2:
                images.convert_image(work_qcow2, out_disk, out_fmt)
    except QemuError as exc:
        raise SeedError(str(exc)) from None

    logger.info("done")
    return out_disk
