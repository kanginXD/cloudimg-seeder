# Contributing

Runtime dependency: QEMU (`qemu-img`, `qemu-system-aarch64` and/or
`qemu-system-x86_64`). arm64 guests need EDK2 firmware from the QEMU
install (`edk2-aarch64-*.fd`).

```text
brew install qemu
```

Tooling is managed with [mise](https://mise.jdx.dev/). From the repo root:

```text
mise trust && mise install
uv sync --group dev
```

Commits: [Conventional Commits](https://www.conventionalcommits.org/),
imperative subject.
