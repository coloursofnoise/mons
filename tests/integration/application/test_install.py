import os
import shutil
import urllib.request
import zipfile

import outputs
import pytest

import mons.commands.main
from mons.mons import cli as mons_cli

GITHUB_REPO = "https://github.com/EverestAPI/Everest"


@pytest.fixture(autouse=True)
def mock_installer(monkeypatch):
    monkeypatch.setattr(mons.commands.main, "run_installer", lambda *args: True)


def test_install_default(runner_result, test_install):
    # install preferred branch (defaults to stable)
    with runner_result(mons_cli, ["install", test_install]) as result:
        assert result.exit_code == 0
        assert outputs.INSTALL_SUCCESS in result.output


def test_install_branch(runner_result, test_install):
    with runner_result(mons_cli, ["install", test_install, "stable"]) as result:
        assert result.exit_code == 0
        assert outputs.INSTALL_SUCCESS in result.output


def test_install_url(runner_result, test_install):
    url = f"{GITHUB_REPO}/releases/latest/download/main.zip"

    with runner_result(mons_cli, ["install", test_install, url]) as result:
        assert result.exit_code == 0
        assert outputs.INSTALL_SUCCESS in result.output


def test_install_zip(runner_result, test_install, cache):
    url = f"{GITHUB_REPO}/releases/latest/download/olympus-build.zip"
    file = os.path.join(cache.mkdir("mons_test_install"), "olympus-build.zip")
    if not os.path.exists(file):
        urllib.request.urlretrieve(url, file)

    assert os.path.isfile(file)

    with runner_result(mons_cli, ["install", test_install, file]) as result:
        assert result.exit_code == 0
        assert outputs.INSTALL_SUCCESS in result.output


def test_install_stdin(runner_result, test_install, cache):
    url = f"{GITHUB_REPO}/releases/latest/download/olympus-build.zip"
    file = os.path.join(cache.mkdir("mons_test_install"), "olympus-build.zip")
    if not os.path.exists(file):
        urllib.request.urlretrieve(url, file)

    assert os.path.isfile(file)

    with open(file) as data:
        with runner_result(
            mons_cli, ["install", test_install, "-"], input=data
        ) as result:
            assert result.exit_code == 0
            assert outputs.INSTALL_SUCCESS in result.output


@pytest.mark.xfail(
    not (shutil.which("dotnet") or shutil.which("msbuild")),
    reason="no .NET build tool found",
    run=False,
)
def test_install_src(runner_result, test_install, cache):
    source_dir = os.path.join(cache.mkdir("mons_test_install"), "Everest-stable")
    if not os.path.exists(source_dir):
        dest = os.path.join(cache.mkdir("mons_test_install"), "stable.zip")
        if not os.path.exists(dest):
            urllib.request.urlretrieve(
                f"{GITHUB_REPO}/archive/refs/heads/stable.zip", dest
            )

        with zipfile.ZipFile(dest, "r") as zip:
            zip.extractall(cache.mkdir("mons_test_install"))

    assert os.listdir(source_dir), "Failed to download source artifact: " + source_dir

    with runner_result(
        mons_cli, ["install", test_install, "--src", source_dir]
    ) as result:
        assert result.exit_code == 0
        assert outputs.INSTALL_SUCCESS in result.output
