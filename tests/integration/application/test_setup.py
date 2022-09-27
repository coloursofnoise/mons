import typing as t

import pytest

from mons.mons import cli as mons_cli

if t.TYPE_CHECKING:
    from click.testing import CliRunner

TEST_INSTALL = "_mons_testing"


@pytest.mark.prioritize
@pytest.mark.must_pass
def test_add(runner: "CliRunner", test_install):
    result = runner.invoke(mons_cli, ["add", TEST_INSTALL, test_install])
    assert result.exit_code == 0, result.output
    assert "Found Celeste.exe" in result.output


def setup_install(runner: "CliRunner", test_install):
    result = runner.invoke(mons_cli, ["add", TEST_INSTALL, test_install])
    if result.exit_code != 0:
        pytest.skip(result.output)


def test_rename(runner, test_install):
    RENAMED_INSTALL = TEST_INSTALL + "_renamed"

    setup_install(runner, test_install)

    result = runner.invoke(mons_cli, ["rename", TEST_INSTALL, RENAMED_INSTALL])
    assert result.exit_code == 0, result.output
    assert "Renamed install" in result.output


def test_set_path(runner, test_install):
    setup_install(runner, test_install)

    result = runner.invoke(mons_cli, ["set-path", TEST_INSTALL, test_install])
    assert result.exit_code == 0, result.output
    assert "Found Celeste.exe" in result.output


def test_remove(runner: "CliRunner", test_install):
    setup_install(runner, test_install)

    result = runner.invoke(mons_cli, ["remove", TEST_INSTALL, "--force"])
    assert result.exit_code == 0, result.output
    assert f"Removed install {TEST_INSTALL}" in result.output


def test_list(runner: "CliRunner", test_install):
    result = runner.invoke(mons_cli, ["list"])
    assert result.exit_code != 0
    assert "No installs found" in result.output

    setup_install(runner, test_install)

    result = runner.invoke(mons_cli, ["list"])
    assert result.exit_code == 0, result.output
    assert TEST_INSTALL in result.output


def test_show(runner: "CliRunner", test_install):
    setup_install(runner, test_install)

    result = runner.invoke(mons_cli, ["show", TEST_INSTALL])
    assert result.exit_code == 0, result.output
    assert TEST_INSTALL in result.output
