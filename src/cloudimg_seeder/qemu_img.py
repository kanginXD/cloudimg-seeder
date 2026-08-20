"""qemu-img subprocess wrappers."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from cloudimg_seeder.disk import OutputFormat, assert_grow_only
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.host import find_qemu_binary

logger = logging.getLogger("cloudimg_seeder")


def _run_qemu_img(args: list[str]) -> subprocess.CompletedProcess[str]:
    binary = find_qemu_binary("qemu-img")
    result = subprocess.run(
        [binary, *args],
        capture_output=True,
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


def image_virtual_size(path: Path) -> int:
    result = _run_qemu_img(["info", "--output=json", str(path)])
    try:
        payload = json.loads(result.stdout)
        virtual_size = payload["virtual-size"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise QemuError(f"failed to read virtual size: {path}") from exc
    if not isinstance(virtual_size, int) or virtual_size < 0:
        raise QemuError(f"invalid virtual-size for {path}")
    return virtual_size


def convert_image(src: Path, dst: Path, fmt: OutputFormat) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run_qemu_img(["convert", "-p", "-O", fmt.value, str(src), str(dst)])


def convert_to_qcow2(src: Path, dst: Path) -> None:
    convert_image(src, dst, OutputFormat.QCOW2)


def resize_image(path: Path, size: str) -> None:
    """Grow ``path`` to absolute ``size``. Refuse shrink; equal is a no-op."""
    current = image_virtual_size(path)
    target = assert_grow_only(current, size)
    if target is None:
        logger.info("size unchanged (%s bytes); skip resize", current)
        return
    _run_qemu_img(["resize", str(path), size.strip()])
    logger.info("resized to %s (%s bytes)", size.strip(), target)
