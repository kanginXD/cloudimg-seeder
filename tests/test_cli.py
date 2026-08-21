"""Tests for the Typer CLI."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cloudimg_seeder.cli import app
from cloudimg_seeder.console import SerialLogFormat, SerialOptions
from cloudimg_seeder.errors import SeedError
from cloudimg_seeder.seeder import SeedConfig

runner = CliRunner()


@pytest.fixture
def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    disk = tmp_path / "disk.img"
    user = tmp_path / "user-data.yml"
    disk.write_bytes(b"x")
    user.write_text("#cloud-config\n")
    return disk, user


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Seed cloud-init" in result.stdout or "cloud image" in result.stdout.lower()
    assert "--quiet" in result.stdout
    assert "--serial-log" in result.stdout
    assert "--serial-log-format" in result.stdout
    assert "--verbose" in result.stdout
    assert "--no-serial" in result.stdout
    assert "--version" in result.stdout
    assert "--idle-timeout-sec" in result.stdout
    assert "--strict" in result.stdout
    assert "Guest" in result.stdout
    assert "Output" in result.stdout
    assert "Console" in result.stdout


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "cloudimg-seeder" in result.stdout


def test_cli_stdout_carries_only_the_result_path(
    tmp_path: Path, _inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: stdout must never carry step/progress output, since
    scripts do `OUT=$(cloudimg-seeder ...)`."""
    disk, user = _inputs
    out = tmp_path / "seeded.qcow2"

    async def fake_seed(config: SeedConfig, **_kwargs: object) -> Path:
        logging.getLogger("cloudimg_seeder").info("a step message")
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(app, [str(disk), str(user), "-o", str(out)])
    assert result.exit_code == 0
    assert result.stdout == f"{out}\n"
    assert "a step message" in result.stderr
    assert "a step message" not in result.stdout


def test_cli_passes_show_serial_and_serial_log(
    tmp_path: Path, _inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    disk, user = _inputs
    out = tmp_path / "seeded.qcow2"
    log = tmp_path / "serial.log"
    seen: dict[str, object] = {}

    async def fake_seed(config: SeedConfig, **_kwargs: object) -> Path:
        seen["show_serial"] = config.show_serial
        seen["serial_log"] = config.serial_log
        seen["serial_log_format"] = config.serial_log_format
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(
        app,
        [
            str(disk),
            str(user),
            "-o",
            str(out),
            "--no-serial",
            "--serial-log",
            str(log),
            "--serial-log-format",
            "raw",
        ],
    )
    assert result.exit_code == 0
    assert seen["show_serial"] is False
    assert Path(str(seen["serial_log"])) == log.resolve()
    assert seen["serial_log_format"] is SerialLogFormat.RAW


def test_cli_serial_log_format_defaults_to_plain(
    tmp_path: Path, _inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    disk, user = _inputs
    out = tmp_path / "seeded.qcow2"
    seen: dict[str, object] = {}

    async def fake_seed(config: SeedConfig, **_kwargs: object) -> Path:
        seen["serial_log_format"] = config.serial_log_format
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(app, [str(disk), str(user), "-o", str(out)])
    assert result.exit_code == 0
    assert seen["serial_log_format"] is SerialLogFormat.PLAIN


def test_cli_quiet_silences_steps_but_keeps_result(
    tmp_path: Path, _inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    disk, user = _inputs
    out = tmp_path / "seeded.qcow2"
    seen: dict[str, object] = {}

    async def fake_seed(config: SeedConfig, **_kwargs: object) -> Path:
        seen["show_serial"] = config.show_serial
        logging.getLogger("cloudimg_seeder").info("should not appear")
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(app, [str(disk), str(user), "-o", str(out), "-q"])
    assert result.exit_code == 0
    assert seen["show_serial"] is False
    assert result.stderr == ""
    assert result.stdout == f"{out}\n"


def test_cli_success(
    tmp_path: Path, _inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    disk, user = _inputs
    out = tmp_path / "seeded.qcow2"

    async def fake_seed(config: object, **_kwargs: object) -> Path:
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(app, [str(disk), str(user), "-o", str(out)])
    assert result.exit_code == 0
    assert str(out) in result.stdout


def test_cli_seed_error(
    tmp_path: Path, _inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    disk, user = _inputs

    async def fake_seed(config: object, **_kwargs: object) -> Path:
        raise SeedError("boom")

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(app, [str(disk), str(user)])
    assert result.exit_code == 1
    assert "boom" in result.stderr


def test_cli_seed_error_message_with_brackets_is_not_mangled(
    tmp_path: Path, _inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    disk, user = _inputs

    async def fake_seed(config: object, **_kwargs: object) -> Path:
        raise SeedError("qemu-img failed (convert [-p] -O raw): boom")

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(app, [str(disk), str(user)])
    assert result.exit_code == 1
    assert "[-p]" in result.stderr


def test_cli_verbose_enables_debug_logging(
    tmp_path: Path, _inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    disk, user = _inputs
    out = tmp_path / "seeded.qcow2"

    async def fake_seed(config: object, **_kwargs: object) -> Path:
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(app, [str(disk), str(user), "-o", str(out), "-v"])
    assert result.exit_code == 0
    assert logging.getLogger("cloudimg_seeder").level == logging.DEBUG


def test_cli_repeated_invocations_do_not_duplicate_log_handlers(
    tmp_path: Path, _inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    disk, user = _inputs
    out = tmp_path / "seeded.qcow2"

    async def fake_seed(config: object, **_kwargs: object) -> Path:
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    runner.invoke(app, [str(disk), str(user), "-o", str(out)])
    runner.invoke(app, [str(disk), str(user), "-o", str(out)])
    assert len(logging.getLogger("cloudimg_seeder").handlers) == 1


def test_serial_options_reexport_available() -> None:
    assert SerialOptions().show_serial is True


def test_cli_default_idle_timeout_and_strict(
    tmp_path: Path, _inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    disk, user = _inputs
    out = tmp_path / "seeded.qcow2"
    seen: dict[str, object] = {}

    async def fake_seed(config: SeedConfig, **_kwargs: object) -> Path:
        seen["idle_timeout_sec"] = config.idle_timeout_sec
        seen["strict"] = config.strict
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(app, [str(disk), str(user), "-o", str(out)])
    assert result.exit_code == 0
    assert seen["idle_timeout_sec"] is None
    assert seen["strict"] is False


def test_cli_passes_idle_timeout_and_strict(
    tmp_path: Path, _inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    disk, user = _inputs
    out = tmp_path / "seeded.qcow2"
    seen: dict[str, object] = {}

    async def fake_seed(config: SeedConfig, **_kwargs: object) -> Path:
        seen["idle_timeout_sec"] = config.idle_timeout_sec
        seen["strict"] = config.strict
        return out

    monkeypatch.setattr("cloudimg_seeder.cli.seed", fake_seed)
    result = runner.invoke(
        app,
        [
            str(disk),
            str(user),
            "-o",
            str(out),
            "--idle-timeout-sec",
            "300",
            "--strict",
        ],
    )
    assert result.exit_code == 0
    assert seen["idle_timeout_sec"] == 300
    assert seen["strict"] is True
