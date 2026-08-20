# cloudimg-seeder

Bake NoCloud cloud-init into a standalone qcow2 with headless QEMU.

```text
cloudimg-seeder DISK USER_DATA [-m META] [--arch arm64|amd64] [-o OUTPUT]
                [--size SIZE] [--cpus N] [--memory-mb N] [--timeout-sec N]
```

Stdout: absolute path of the output qcow2.
Stderr: progress and guest serial.

## Dependencies

- Python 3.10+
- QEMU: `qemu-img`, plus `qemu-system-aarch64` and/or `qemu-system-x86_64`

```text
brew install qemu
```

## Install

```text
uv sync
uv run cloudimg-seeder --help
```

## Behavior

- Does not modify `DISK`; converts a copy to qcow2, then boots that copy.
- Default output: `{cwd}/{stem}.qcow2`. If that path is the input disk,
  uses `{stem}-cloudinit.qcow2`.
- `--size` grows the output virtual size before boot (qemu-img suffixes,
  e.g. `20G`). Shrink is rejected. Root partition/FS growth relies on
  guest cloud-init `growpart` / `resizefs`.
- `--arch` defaults from the disk filename, otherwise the host.
- arm64 guests need EDK2 firmware shipped with QEMU (`edk2-aarch64-*.fd`).
- Without `--meta-data`, meta-data is `instance-id: cloudimg-seeder`.
- UTM Apple Virtualization accepts arm64 guests only; amd64 needs UTM’s
  QEMU backend.
