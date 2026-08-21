"""qemu-img subprocess wrappers."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cloudimg_seeder.disk import OutputFormat, assert_grow_only
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.host import find_qemu_binary

logger = logging.getLogger("cloudimg_seeder")


@dataclass(frozen=True)
class ImageInfo:
    virtual_size: int
    format: str


def _run(args: list[str], *, capture_stdout: bool) -> subprocess.CompletedProcess[str]:
    binary = find_qemu_binary("qemu-img")
    result = subprocess.run(
        [binary, *args],
        stdout=subprocess.PIPE if capture_stdout else None,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        cmd = " ".join([binary, *args])
        if detail:
            raise QemuError(f"qemu-img failed ({cmd}): {detail}")
        raise QemuError(f"qemu-img failed ({cmd})")
    return result


def _run_qemu_img(args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(args, capture_stdout=True)


def image_info(path: Path) -> ImageInfo:
    result = _run_qemu_img(["info", "--output=json", str(path)])
    try:
        payload = json.loads(result.stdout)
        virtual_size = payload["virtual-size"]
        fmt = payload["format"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise QemuError(f"failed to read image info: {path}") from exc
    if not isinstance(virtual_size, int) or virtual_size < 0:
        raise QemuError(f"invalid virtual-size for {path}")
    if not isinstance(fmt, str) or not fmt:
        raise QemuError(f"invalid format for {path}")
    return ImageInfo(virtual_size=virtual_size, format=fmt)


def image_virtual_size(path: Path) -> int:
    return image_info(path).virtual_size


def convert_image(src: Path, dst: Path, fmt: OutputFormat, *, src_format: str) -> None:
    """Convert src to fmt at dst. src_format is required and passed as -f,
    since qemu-img would otherwise probe the (potentially untrusted) input.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(
        ["convert", "-p", "-f", src_format, "-O", fmt.value, str(src), str(dst)],
        capture_stdout=False,
    )


def resize_image(path: Path, size: str) -> None:
    """Grow ``path`` to absolute ``size``. Refuse shrink; equal is a no-op."""
    current = image_info(path).virtual_size
    target = assert_grow_only(current, size)
    if target is None:
        logger.info("size unchanged (%s bytes); skip resize", current)
        return
    _run_qemu_img(["resize", str(path), size.strip()])
    logger.info("resized to %s (%s bytes)", size.strip(), target)
