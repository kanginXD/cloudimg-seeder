"""CLI entry point."""

from __future__ import annotations

import asyncio
import logging
from importlib.metadata import version as _package_version
from pathlib import Path
from typing import Annotated

import typer

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.console import RichProgressSink, SerialLogFormat, StepHandler, Ui
from cloudimg_seeder.disk import OutputFormat
from cloudimg_seeder.seeder import SeedConfig, SeedError, seed

_LOGGER = logging.getLogger("cloudimg_seeder")

_PANEL_GUEST = "Guest"
_PANEL_OUTPUT = "Output"
_PANEL_CONSOLE = "Console"

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _configure_logging(ui: Ui, *, verbose: bool) -> None:
    # Idempotent: repeated invocations in one process (tests, library
    # embedding) must not accumulate duplicate handlers.
    _LOGGER.handlers.clear()
    _LOGGER.addHandler(StepHandler(ui))
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
            rich_help_panel=_PANEL_GUEST,
        ),
    ] = None,
    arch: Annotated[
        GuestArch | None,
        typer.Option(
            "--arch",
            help="Guest arch. Default: filename, else host.",
            rich_help_panel=_PANEL_GUEST,
        ),
    ] = None,
    cpus: Annotated[
        int,
        typer.Option("--cpus", help="vCPUs.", min=1, rich_help_panel=_PANEL_GUEST),
    ] = 2,
    memory_mb: Annotated[
        int,
        typer.Option(
            "--memory-mb",
            help="Memory (MiB).",
            min=128,
            rich_help_panel=_PANEL_GUEST,
        ),
    ] = 2048,
    timeout_sec: Annotated[
        int,
        typer.Option(
            "--timeout-sec",
            help="Cloud-init wait timeout.",
            min=1,
            rich_help_panel=_PANEL_GUEST,
        ),
    ] = 1200,
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
            rich_help_panel=_PANEL_OUTPUT,
        ),
    ] = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option(
            "--output-format",
            help="Output disk format (hypervisor file formats).",
            rich_help_panel=_PANEL_OUTPUT,
        ),
    ] = OutputFormat.QCOW2,
    size: Annotated[
        str | None,
        typer.Option(
            "--size",
            help="Grow output disk (e.g. 20G).",
            rich_help_panel=_PANEL_OUTPUT,
        ),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option(
            "-q",
            "--quiet",
            help="Silence all output except errors and the result path.",
            rich_help_panel=_PANEL_CONSOLE,
        ),
    ] = False,
    no_serial: Annotated[
        bool,
        typer.Option(
            "--no-serial",
            help="Hide guest serial, keeping progress and step messages.",
            rich_help_panel=_PANEL_CONSOLE,
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "-v",
            "--verbose",
            help="Enable debug logging.",
            rich_help_panel=_PANEL_CONSOLE,
        ),
    ] = False,
    serial_log: Annotated[
        Path | None,
        typer.Option(
            "--serial-log",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="Write guest serial to a file at PATH.",
            rich_help_panel=_PANEL_CONSOLE,
        ),
    ] = None,
    serial_log_format: Annotated[
        SerialLogFormat,
        typer.Option(
            "--serial-log-format",
            help="--serial-log rendering: interpreted lines, or the raw stream.",
            rich_help_panel=_PANEL_CONSOLE,
        ),
    ] = SerialLogFormat.PLAIN,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print the version and exit.",
            is_eager=True,
            callback=_version_callback,
            rich_help_panel=_PANEL_CONSOLE,
        ),
    ] = False,
) -> None:
    """Seed cloud-init into a cloud image."""
    ui = Ui(show_steps=not quiet)
    _configure_logging(ui, verbose=verbose)
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
        show_serial=not quiet and not no_serial,
        serial_log=serial_log,
        serial_log_format=serial_log_format,
    )
    try:
        result = asyncio.run(seed(config, progress=RichProgressSink(ui), ui=ui))
    except SeedError as exc:
        ui.error(str(exc))
        raise typer.Exit(code=1) from None

    print(result)


if __name__ == "__main__":
    app()
