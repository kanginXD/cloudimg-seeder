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
_PROBE_SCRIPT_PATH = "/var/lib/cloud/cloudimg-seeder-probe.sh"

# Written by the guest probe once cloud-init reaches a final state.
STATUS_LINE = re.compile(rb"^cloudimg-seeder-status (\d+)$")

# bootcmd runs at the "init" stage, well before "modules:final", so the
# probe is armed long before cloud-init can finish. It must detach fully
# (setsid, all three fds redirected): cloud-init status --wait blocks on
# cloud-final.service, and cloud-init itself waits on bootcmd's own stdio,
# so an attached probe would deadlock the boot it is trying to observe.
VENDOR_DATA = f"""\
#cloud-config
write_files:
  - path: {_PROBE_SCRIPT_PATH}
    permissions: '0755'
    content: |
      #!/bin/sh
      cloud-init status --wait >/dev/null 2>&1
      echo "cloudimg-seeder-status $?" > {_STATUS_PORT_PATH}
bootcmd:
  - setsid {_PROBE_SCRIPT_PATH} </dev/null >/dev/null 2>&1 &
""".encode()
