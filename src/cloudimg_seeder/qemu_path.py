"""Escape paths for QEMU -drive file= values."""

from __future__ import annotations

from pathlib import Path


def qemu_drive_path(path: Path) -> str:
    """Return a path string safe for QEMU drive option lists.

    Commas are doubled. Resolved paths use forward slashes so Windows
    backslashes do not break option parsing.
    """
    text = path.resolve().as_posix()
    return text.replace(",", ",,")
