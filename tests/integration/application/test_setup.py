import os
import typing as t

import outputs
import pytest

from mons.mons import cli as mons_cli

if t.TYPE_CHECKING:
    from click.testing import CliRunner


@pytest.mark.prioritize
@pytest.mark.must_pass  # All other tests rely on `mons add`
def test_add(runner: "CliRunner", test_install_path, test_name):
    result = runner.invoke(mons_cli, ["add", test_name, test_install_path])
    assert result.exit_code == 0, result.output
    assert outputs.FOUND_INSTALL in result.output


def test_add_fail(runner: "CliRunner", test_name, tmp_path):
    fake_path = os.path.join(tmp_path, "fake_path")
    result = runner.invoke(mons_cli, ["add", test_name, fake_path])
    assert result.exception
    assert f"Path '{fake_path}' does not exist" in result.output

    os.mkdir(fake_path)
    result = runner.invoke(mons_cli, ["add", test_name, fake_path])
    assert result.exception
    asm = "Celeste.exe" if os.name == "nt" else "Celeste.exe or Celeste.dll"
    assert f"'{asm}' could not be found" in result.output


def test_rename(runner, test_install):
    result = runner.invoke(
        mons_cli, ["rename", test_install, f"{test_install}_renamed"]
    )
    assert result.exit_code == 0, result.output
    assert outputs.RENAMED_INSTALL in result.output


def test_set_path(runner, test_install, test_install_path):
    result = runner.invoke(mons_cli, ["set-path", test_install, test_install_path])
    assert result.exit_code == 0, result.output
    assert outputs.FOUND_INSTALL in result.output


def test_remove(runner: "CliRunner", test_install):
    result = runner.invoke(mons_cli, ["remove", test_install, "--force"])
    assert result.exit_code == 0, result.output
    assert outputs.REMOVED_INSTALL in result.output


def test_list(runner: "CliRunner", test_install):
    result = runner.invoke(mons_cli, ["list"])
    assert result.exit_code == 0, result.output
    assert test_install in result.output


def test_list_empty(runner: "CliRunner"):
    result = runner.invoke(mons_cli, ["list"])
    assert result.exit_code != 0, result.output
    assert outputs.NO_INSTALLS_FOUND in result.output


def test_show(runner: "CliRunner", test_install):
    result = runner.invoke(mons_cli, ["show", test_install])
    assert result.exit_code == 0, result.output
    assert test_install in result.output
