"""Exception types for cloudimg-seeder."""

from __future__ import annotations


class SeedError(Exception):
    """User-facing failure during seed or CLI handling."""


class QemuError(Exception):
    """QEMU or qemu-img failure. Mapped to SeedError at the seeder boundary."""
