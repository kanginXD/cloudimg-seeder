"""Tests for the Typer CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cloudimg_seeder.cli import app
from cloudimg_seeder.console import SerialOptions
from cloudimg_seeder.errors import SeedError
from cloudimg_seeder.seeder import SeedConfig

runner = CliRunner()


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Seed cloud-init" in result.stdout or "cloud image" in result.stdout.lower()
    assert "--quiet" in result.stdout
    assert "--serial-log" in result.stdout
    assert "--verbose" in result.stdout
    assert "--version" in result.stdout


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "cloudimg-seeder" in result.stdout


def test_cli_passes_quiet_and_serial_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disk = tmp_path / "disk.img"
    user = tmp_path / "user-data.yml"
    disk.write_bytes(b"x")
    user.write_text("#cloud-config\n")
    out = tmp_path / "seeded.qcow2"
    log = tmp_path / "serial.log"
    seen: dict[str, object] = {}

    async def fake_seed(config: SeedConfig) -> Path:
        seen["quiet"] = config.quiet
        seen["serial_log"] = config.serial_log
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(
        app,
        [str(disk), str(user), "-o", str(out), "-q", "--serial-log", str(log)],
    )
    assert result.exit_code == 0
    assert seen["quiet"] is True
    assert Path(str(seen["serial_log"])) == log.resolve()


def test_cli_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    disk = tmp_path / "disk.img"
    user = tmp_path / "user-data.yml"
    disk.write_bytes(b"x")
    user.write_text("#cloud-config\n")
    out = tmp_path / "seeded.qcow2"

    async def fake_seed(config: object) -> Path:
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(app, [str(disk), str(user), "-o", str(out)])
    assert result.exit_code == 0
    assert str(out) in result.stdout


def test_cli_seed_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    disk = tmp_path / "disk.img"
    user = tmp_path / "user-data.yml"
    disk.write_bytes(b"x")
    user.write_text("#cloud-config\n")

    async def fake_seed(config: object) -> Path:
        raise SeedError("boom")

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(app, [str(disk), str(user)])
    assert result.exit_code == 1
    assert "boom" in result.output


def test_cli_seed_error_message_with_brackets_is_not_mangled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disk = tmp_path / "disk.img"
    user = tmp_path / "user-data.yml"
    disk.write_bytes(b"x")
    user.write_text("#cloud-config\n")

    async def fake_seed(config: object) -> Path:
        raise SeedError("qemu-img failed (convert [-p] -O raw): boom")

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(app, [str(disk), str(user)])
    assert result.exit_code == 1
    assert "[-p]" in result.output


def test_cli_verbose_enables_debug_logging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disk = tmp_path / "disk.img"
    user = tmp_path / "user-data.yml"
    disk.write_bytes(b"x")
    user.write_text("#cloud-config\n")
    out = tmp_path / "seeded.qcow2"

    async def fake_seed(config: object) -> Path:
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(app, [str(disk), str(user), "-o", str(out), "-v"])
    assert result.exit_code == 0

    import logging

    assert logging.getLogger("cloudimg_seeder").level == logging.DEBUG


def test_cli_repeated_invocations_do_not_duplicate_log_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disk = tmp_path / "disk.img"
    user = tmp_path / "user-data.yml"
    disk.write_bytes(b"x")
    user.write_text("#cloud-config\n")
    out = tmp_path / "seeded.qcow2"

    async def fake_seed(config: object) -> Path:
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    runner.invoke(app, [str(disk), str(user), "-o", str(out)])
    runner.invoke(app, [str(disk), str(user), "-o", str(out)])

    import logging

    assert len(logging.getLogger("cloudimg_seeder").handlers) == 1


def test_serial_options_reexport_available() -> None:
    assert SerialOptions().quiet is False
