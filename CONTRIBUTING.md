# Contributing

## Runtime dependency

QEMU (`qemu-img`, `qemu-system-aarch64` and/or `qemu-system-x86_64`). arm64
guests need EDK2/AAVMF firmware from the QEMU install.

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

Ensure `qemu-img` is on `PATH`.

## Development

Tooling is managed with [mise](https://mise.jdx.dev/). From the repo root:

```text
mise trust && mise install
uv sync --group dev
```

Run unit tests, lint, formatting, and type checking:

```text
mise run test
mise run lint
mise run fmt
mise run typecheck
```

Each task also runs directly via `uv`: `uv run pytest`, `uv run ruff check .`,
`uv run ruff format .`, `uv run pyrefly check`.

Staged changes: `prek run <hook-id>` for one hook, or `prek run <hook-id>
--all-files` to run a specific hook against the whole tree.

Commits: [Conventional Commits](https://www.conventionalcommits.org/),
imperative subject.
