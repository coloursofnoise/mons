import os

import outputs
import pytest

from mons.mons import cli as mons_cli


@pytest.mark.prioritize
@pytest.mark.must_pass  # All other tests rely on `mons add`
def test_add(runner_result, test_install_path, test_name):
    with runner_result(mons_cli, ["add", test_name, test_install_path]) as result:
        assert result.exit_code == 0
        assert outputs.FOUND_INSTALL in result.output


def test_add_fail(runner_result, test_name, tmp_path):
    fake_path = os.path.join(tmp_path, "fake_path")
    with runner_result(mons_cli, ["add", test_name, fake_path]) as result:
        assert result.exception
        assert f"Path '{fake_path}' does not exist" in result.output

    os.mkdir(fake_path)
    with runner_result(mons_cli, ["add", test_name, fake_path]) as result:
        assert result.exception
        asm = "'Celeste.exe' or 'Celeste.dll'"
        assert f"{asm} could not be found" in result.output


def test_rename(runner_result, test_install):
    with runner_result(
        mons_cli, ["rename", test_install, f"{test_install}_renamed"]
    ) as result:
        assert result.exit_code == 0
        assert outputs.RENAMED_INSTALL in result.output


def test_set_path(runner_result, test_install, test_install_path):
    with runner_result(
        mons_cli, ["set-path", test_install, test_install_path]
    ) as result:
        assert result.exit_code == 0
        assert outputs.FOUND_INSTALL in result.output


def test_remove(runner_result, test_install):
    with runner_result(mons_cli, ["remove", test_install, "--force"]) as result:
        assert result.exit_code == 0
        assert outputs.REMOVED_INSTALL in result.output


def test_list(runner_result, test_install):
    with runner_result(mons_cli, ["list"]) as result:
        assert result.exit_code == 0
        assert test_install in result.output


def test_list_empty(runner_result):
    with runner_result(mons_cli, ["list"]) as result:
        assert result.exit_code != 0, result.output
        assert outputs.NO_INSTALLS_FOUND in result.output


def test_show(runner_result, test_install):
    with runner_result(mons_cli, ["show", test_install]) as result:
        assert result.exit_code == 0, result.output
        assert test_install in result.output


def test_launch(runner_result, test_install, test_install_path):
    with runner_result(mons_cli, ["launch", test_install, "--dry-run"]) as result:
        assert result.exit_code == 0, result.output
        assert (
            os.path.join(os.path.dirname(test_install_path), "Celeste") in result.output
        )
