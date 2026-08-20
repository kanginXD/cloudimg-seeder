"""Tests for the Typer CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cloudimg_seeder.cli import app
from cloudimg_seeder.errors import SeedError
from cloudimg_seeder.seeder import SeedConfig

runner = CliRunner()


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Seed cloud-init" in result.stdout or "cloud image" in result.stdout.lower()
    assert "--quiet" in result.stdout
    assert "--serial-log" in result.stdout


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
