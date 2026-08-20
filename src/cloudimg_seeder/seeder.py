from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cloudimg_seeder.iso import build_seed_iso
from cloudimg_seeder.qemu import (
    GuestArch,
    QemuError,
    convert_to_qcow2,
    default_output_path,
    image_virtual_size,
    parse_size,
    require_cmd,
    resize_qcow2,
    resolve_arch,
    run_headless_qemu,
)

logger = logging.getLogger("cloudimg_seeder")


class SeedError(Exception):
    pass


@dataclass(frozen=True)
class SeedConfig:
    disk: Path
    user_data: Path
    meta_data: Path | None = None
    output: Path | None = None
    arch: GuestArch | None = None
    size: str | None = None
    cpus: int = 2
    memory_mb: int = 2048
    timeout_sec: int = 1200


async def seed(config: SeedConfig) -> Path:
    """Apply NoCloud cloud-init once and return the standalone qcow2 path.

    Leaves ``config.disk`` unchanged. Writes the output qcow2 before the
    guest boots; on failure the partial output may remain.
    """
    if not config.disk.is_file():
        raise SeedError(f"disk not found: {config.disk}")
    if not config.user_data.is_file():
        raise SeedError(f"user-data not found: {config.user_data}")
    if config.meta_data is not None and not config.meta_data.is_file():
        raise SeedError(f"meta-data not found: {config.meta_data}")

    try:
        require_cmd("qemu-img", "brew install qemu")

        disk = config.disk.resolve()
        user_data = config.user_data.resolve()
        meta_data = config.meta_data.resolve() if config.meta_data else None
        guest_arch = resolve_arch(disk, config.arch)
        out_disk = (
            config.output.resolve()
            if config.output is not None
            else default_output_path(disk)
        )

        if config.size is not None:
            target = parse_size(config.size)
            current = image_virtual_size(disk)
            if target < current:
                raise SeedError(
                    f"refusing to shrink disk: target {config.size} "
                    f"({target} bytes) < current {current} bytes"
                )

        logger.info("guest arch: %s", guest_arch.value)
        logger.info("output: %s", out_disk)

        user_bytes = user_data.read_bytes()
        meta_bytes = meta_data.read_bytes() if meta_data is not None else None

        with tempfile.TemporaryDirectory(prefix="cloudimg-seeder-") as tmp:
            workdir = Path(tmp)
            seed_iso = workdir / "seed.iso"
            build_seed_iso(seed_iso, user_bytes, meta_bytes)
            convert_to_qcow2(disk, out_disk)
            if config.size is not None:
                resize_qcow2(out_disk, config.size)
            await run_headless_qemu(
                arch=guest_arch,
                disk=out_disk,
                seed_iso=seed_iso,
                workdir=workdir,
                cpus=config.cpus,
                memory_mb=config.memory_mb,
                timeout_sec=float(config.timeout_sec),
            )
    except QemuError as exc:
        raise SeedError(str(exc)) from None

    logger.info("done")
    return out_disk
