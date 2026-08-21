"""NoCloud CIDATA ISO construction."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pycdlib

DEFAULT_INSTANCE_ID = "cloudimg-seeder"


def build_seed_iso(
    dest: Path,
    user_data: bytes,
    meta_data: bytes | None,
    vendor_data: bytes | None = None,
) -> Path:
    """Write a CIDATA ISO with user-data, meta-data, and vendor-data at dest.

    meta_data None uses ``instance-id: cloudimg-seeder``. vendor_data None
    omits the vendor-data file.
    """
    if meta_data is None:
        meta_data = f"instance-id: {DEFAULT_INSTANCE_ID}\n".encode()

    iso = pycdlib.PyCdlib()
    iso.new(joliet=3, rock_ridge="1.09", vol_ident="CIDATA")

    try:
        iso.add_fp(
            BytesIO(user_data),
            len(user_data),
            "/USERDATA.;1",
            rr_name="user-data",
            joliet_path="/user-data",
        )
        iso.add_fp(
            BytesIO(meta_data),
            len(meta_data),
            "/METADATA.;1",
            rr_name="meta-data",
            joliet_path="/meta-data",
        )
        if vendor_data is not None:
            iso.add_fp(
                BytesIO(vendor_data),
                len(vendor_data),
                "/VENDORDA.;1",
                rr_name="vendor-data",
                joliet_path="/vendor-data",
            )
        iso.write(str(dest))
    finally:
        iso.close()

    return dest
