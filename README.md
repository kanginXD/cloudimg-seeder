# cloudimg-seeder

Cloud-init, baked in. No QEMU ritual, no seed-ISO juggling — one command,
ready disk.

## Requirements

- Python 3.11+
- QEMU (`qemu-img`, `qemu-system-aarch64` and/or `qemu-system-x86_64`)

arm64 guests require EDK2 firmware shipped with QEMU (`edk2-aarch64-*.fd`).

## Install

TODO: publish via `pipx` and a Homebrew tap.

## Usage

```text
cloudimg-seeder DISK USER_DATA [OPTIONS]
```

Example:

```text
# Default: qcow2 output, grow to 20G
cloudimg-seeder resolute-server-cloudimg-arm64.img user-data.yml \
  -o resolute-seeded.qcow2 --size 20G

# Apple Virtualization / raw disk
cloudimg-seeder resolute-server-cloudimg-arm64.img user-data.yml \
  -o resolute-seeded.raw --output-format raw --size 20G

# Explicit guest architecture
cloudimg-seeder resolute-server-cloudimg-amd64.img user-data.yml \
  --arch amd64 -o resolute-seeded.qcow2
```

| Option | Default | Notes |
| --- | --- | --- |
| `-m`, `--meta-data` | `instance-id: cloudimg-seeder` | NoCloud meta-data file |
| `--arch` | from filename, else host | `arm64` or `amd64` |
| `-o`, `--output` | `{cwd}/{stem}.{ext}` | Clash with `DISK` → `{stem}-cloudinit.{ext}` |
| `--output-format` | `qcow2` | See formats below |
| `--size` | (unchanged) | Grow virtual size before boot (e.g. `20G`); shrink rejected |
| `--cpus` | `2` | |
| `--memory-mb` | `2048` | |
| `--timeout-sec` | `1200` | Cloud-init wait |

`--output-format` values (local disk files only):

`qcow2`, `qcow`, `qed`, `raw`, `vmdk`, `vhdx`, `vdi`, `vpc`, `parallels`, `dmg`

## Notes

Guest architecture is detected automatically from the disk filename or the
host. To use a different architecture, pass `--arch` explicitly.

## IMPORTANT: UTM - Apple Virtualization

- You MUST use `--output-format raw` (Apple Virtualization does not accept
  qcow2).
- You MUST leave the drive’s Read Only option unchecked. A read-only disk
  causes an internal virtualization error and stops the VM.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
