"""Guest-side cloud-init exit-status probe.

Emits ``cloud-init status --wait``'s exit code over a dedicated
virtio-serial port, so the host can distinguish "cloud-init's final
message appeared on the console" from "cloud-init actually succeeded".
"""

from __future__ import annotations

import re

# QEMU device name for the status virtserialport; the guest addresses the
# matching /dev/virtio-ports/<name> node, independent of enumeration order.
STATUS_PORT_NAME = "org.cloudimg-seeder.status"

_STATUS_PORT_PATH = f"/dev/virtio-ports/{STATUS_PORT_NAME}"

# Written by the guest probe once cloud-init reaches a final state.
STATUS_LINE = re.compile(rb"^cloudimg-seeder-status (\d+)$")

_PROBE_CMD = (
    "cloud-init status --wait >/dev/null 2>&1; "
    f'echo "cloudimg-seeder-status $?" > {_STATUS_PORT_PATH}'
)

# bootcmd runs at the "init" stage, well before "modules:final", so the
# probe is armed long before cloud-init can finish. It is a self-contained
# command with no dependency on write_files or any other module: bootcmd
# runs before write_files in cloud-init's default module order, so a probe
# script created by write_files would not exist yet when bootcmd tries to
# launch it. It must detach fully (setsid, all three fds redirected):
# cloud-init status --wait blocks until cloud-init's own Final stage
# completes, and cloud-init itself waits on bootcmd's own stdio, so an
# attached probe would deadlock the boot it is trying to observe.
VENDOR_DATA = f"""\
#cloud-config
bootcmd:
  - |
    setsid sh -c '{_PROBE_CMD}' </dev/null >/dev/null 2>&1 &
""".encode()
