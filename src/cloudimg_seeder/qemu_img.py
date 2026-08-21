"""qemu-img subprocess wrappers."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cloudimg_seeder.disk import OutputFormat, assert_grow_only
from cloudimg_seeder.errors import QemuError
from cloudimg_seeder.host import find_qemu_binary

logger = logging.getLogger("cloudimg_seeder")

# qemu-img -p writes "    (12.34/100%)" per update. With stdout on a pipe it
# separates updates with newlines; on a TTY it rewrites one line with \r.
_PROGRESS_RE = re.compile(r"\((\d+(?:\.\d+)?)/100%\)")


@dataclass(frozen=True)
class ImageInfo:
    virtual_size: int
    format: str


def _fail(binary: str, args: list[str], detail: str) -> QemuError:
    cmd = " ".join([binary, *args])
    text = detail.strip()
    if text:
        return QemuError(f"qemu-img failed ({cmd}): {text}")
    return QemuError(f"qemu-img failed ({cmd})")


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run qemu-img to completion, capturing both streams."""
    binary = find_qemu_binary("qemu-img")
    result = subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise _fail(binary, args, result.stderr or result.stdout or "")
    return result


def _run_with_progress(
    args: list[str],
    on_progress: Callable[[float], None],
) -> None:
    """Run qemu-img, converting its progress frames into callback updates.

    stdout is captured rather than inherited: it keeps qemu-img's bar off the
    caller's stdout (which carries the machine-readable result path) and makes
    qemu-img emit newline-separated frames that are trivially parseable.
    """
    binary = find_qemu_binary("qemu-img")
    with subprocess.Popen(
        [binary, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    ) as proc:
        if proc.stdout is not None:
            for line in proc.stdout:
                for value in _PROGRESS_RE.findall(line):
                    on_progress(float(value))
        stderr = proc.stderr.read() if proc.stderr is not None else ""
    if proc.returncode != 0:
        raise _fail(binary, args, stderr)


def image_info(path: Path) -> ImageInfo:
    result = _run(["info", "--output=json", str(path)])
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


def convert_image(
    src: Path,
    dst: Path,
    fmt: OutputFormat,
    *,
    src_format: str,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """Convert src to fmt at dst.

    src_format is required and passed as -f, since qemu-img would otherwise
    probe the (potentially untrusted) input.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    args = ["convert", "-p", "-f", src_format, "-O", fmt.value, str(src), str(dst)]
    if on_progress is None:
        _run(args)
        return
    _run_with_progress(args, on_progress)


def resize_image(path: Path, size: str) -> None:
    """Grow ``path`` to absolute ``size``. Refuse shrink; equal is a no-op."""
    current = image_info(path).virtual_size
    target = assert_grow_only(current, size)
    if target is None:
        logger.info("size unchanged (%s bytes); skip resize", current)
        return
    _run(["resize", str(path), size.strip()])
    logger.info("resized to %s (%s bytes)", size.strip(), target)
