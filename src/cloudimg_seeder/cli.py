"""CLI entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from importlib.metadata import version as _package_version
from pathlib import Path
from typing import Annotated

import typer

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.disk import OutputFormat
from cloudimg_seeder.seeder import SeedConfig, SeedError, seed

_LOGGER = logging.getLogger("cloudimg_seeder")

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _configure_logging(*, verbose: bool) -> None:
    # Idempotent: repeated invocations in one process (tests, library
    # embedding) must not accumulate duplicate handlers.
    _LOGGER.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("cloudimg-seeder: %(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)
    _LOGGER.propagate = False


def _version_callback(show: bool) -> None:
    if show:
        print(f"cloudimg-seeder {_package_version('cloudimg-seeder')}")
        raise typer.Exit()


@app.command()
def main(
    disk: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Cloud image (not modified).",
        ),
    ],
    user_data: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="NoCloud user-data.",
        ),
    ],
    meta_data: Annotated[
        Path | None,
        typer.Option(
            "-m",
            "--meta-data",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="NoCloud meta-data. Default: instance-id: cloudimg-seeder.",
        ),
    ] = None,
    arch: Annotated[
        GuestArch | None,
        typer.Option("--arch", help="Guest arch. Default: filename, else host."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "-o",
            "--output",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="Output disk path.",
            show_default="cwd/{stem}.{ext}",
        ),
    ] = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option(
            "--output-format",
            help="Output disk format (hypervisor file formats).",
        ),
    ] = OutputFormat.QCOW2,
    size: Annotated[
        str | None,
        typer.Option("--size", help="Grow output disk (e.g. 20G)."),
    ] = None,
    cpus: Annotated[
        int,
        typer.Option("--cpus", help="vCPUs.", min=1),
    ] = 2,
    memory_mb: Annotated[
        int,
        typer.Option("--memory-mb", help="Memory (MiB).", min=128),
    ] = 2048,
    timeout_sec: Annotated[
        int,
        typer.Option("--timeout-sec", help="Cloud-init wait timeout.", min=1),
    ] = 1200,
    quiet: Annotated[
        bool,
        typer.Option(
            "-q",
            "--quiet",
            help="Do not write guest serial to stderr.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("-v", "--verbose", help="Enable debug logging."),
    ] = False,
    serial_log: Annotated[
        Path | None,
        typer.Option(
            "--serial-log",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="Write guest serial to a plain-text file at PATH.",
        ),
    ] = None,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print the version and exit.",
            is_eager=True,
            callback=_version_callback,
        ),
    ] = False,
) -> None:
    """Seed cloud-init into a cloud image."""
    _configure_logging(verbose=verbose)
    config = SeedConfig(
        disk=disk,
        user_data=user_data,
        meta_data=meta_data,
        output=output,
        arch=arch,
        size=size,
        output_format=output_format,
        cpus=cpus,
        memory_mb=memory_mb,
        timeout_sec=timeout_sec,
        quiet=quiet,
        serial_log=serial_log,
    )
    try:
        result = asyncio.run(seed(config))
    except SeedError as exc:
        print(f"cloudimg-seeder: {exc}", file=sys.stderr)
        raise typer.Exit(code=1) from None

    print(result)


if __name__ == "__main__":
    app()
