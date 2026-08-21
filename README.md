# cloudimg-seeder

Cloud-init, baked in. No QEMU ritual, no seed-ISO juggling — one command,
ready disk.

## Requirements

- Python 3.11+
- QEMU (`qemu-img`, `qemu-system-aarch64` and/or `qemu-system-x86_64`)

arm64 guests need EDK2/AAVMF firmware from the QEMU install (for example
`edk2-aarch64-*.fd`, `AAVMF_CODE.fd`, or `QEMU_EFI.fd`).

## Install QEMU

macOS:

```text
brew install qemu
```

Debian/Ubuntu:

```text
sudo apt install qemu-system qemu-utils qemu-efi-aarch64
```

Fedora:

```text
sudo dnf install qemu-system-x86 qemu-system-aarch64 qemu-img edk2-aarch64
```

Windows:

```text
winget install SoftwareFreedomConservancy.QEMU
```

Add the QEMU `bin` directory to `PATH` if `qemu-img` is not found.

## Install

```text
uv tool install git+https://github.com/kanginXD/cloudimg-seeder
```

Or run without installing:

```text
uvx --from git+https://github.com/kanginXD/cloudimg-seeder cloudimg-seeder --help
```

PyPI and Homebrew distribution are not yet set up.

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
| `-q`, `--quiet` | off | Do not write guest serial to stderr |
| `--serial-log` | (none) | Write guest serial to a plain-text file |
| `-v`, `--verbose` | off | Enable debug logging |
| `--version` | | Print the version and exit |

`--output-format` values (local disk files only):

`qcow2`, `qcow`, `qed`, `raw`, `vmdk`, `vhdx`, `vdi`, `vpc`, `parallels`, `dmg`

## Notes

Guest architecture is detected automatically from the disk filename or the
host. To use a different architecture, pass `--arch` explicitly.

For libvirt, prefer `--output-format qcow2`. For Hyper-V, prefer
`--output-format vhdx`.

The guest boots with a SLIRP-backed NIC, giving cloud-init outbound network
access (package installs, remote data sources) during the seed run; no
inbound port is exposed to the host.

Completion is detected from cloud-init's default `final_message` on the
guest serial console. If user-data overrides `final_message`, completion
falls back to `--timeout-sec`: the guest is powered down once the timeout
elapses, whether or not cloud-init has actually finished.

arm64 firmware discovery checks `$QEMU_DATADIR` first, then the QEMU
binary's own data directory, then common package-manager install paths. Set
`QEMU_DATADIR` to override discovery for a non-standard QEMU install.

## IMPORTANT: UTM - Apple Virtualization (macOS)

- You MUST use `--output-format raw` (Apple Virtualization does not accept
  qcow2).
- You MUST leave the drive’s Read Only option unchecked. A read-only disk
  causes an internal virtualization error and stops the VM.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
