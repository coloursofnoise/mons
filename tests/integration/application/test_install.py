import os
import shutil
import urllib.request
import zipfile

import outputs
import pytest

from mons.mons import cli as mons_cli

GITHUB_REPO = "https://github.com/EverestAPI/Everest"


def test_install_default(runner, test_install):
    # install preferred branch (defaults to stable)
    result = runner.invoke(mons_cli, ["install", test_install])
    assert result.exit_code == 0, result.output
    assert outputs.INSTALL_SUCCESS in result.output


def test_install_branch(runner, test_install):
    result = runner.invoke(mons_cli, ["install", test_install, "stable"])
    assert result.exit_code == 0, result.output
    assert outputs.INSTALL_SUCCESS in result.output


def test_install_url(runner, test_install):
    url = f"{GITHUB_REPO}/releases/latest/download/main.zip"

    result = runner.invoke(mons_cli, ["install", test_install, url])
    assert result.exit_code == 0, result.output
    assert outputs.INSTALL_SUCCESS in result.output


def test_install_zip(runner, test_install, tmp_path):
    url = f"{GITHUB_REPO}/releases/latest/download/olympus-build.zip"
    file = os.path.join(tmp_path, "olympus-build.zip")
    urllib.request.urlretrieve(url, file)

    assert os.path.isfile(file)

    result = runner.invoke(mons_cli, ["install", test_install, file])
    assert result.exit_code == 0, result.output
    assert outputs.INSTALL_SUCCESS in result.output


@pytest.mark.xfail(
    not (shutil.which("dotnet") or shutil.which("msbuild")),
    reason="no .NET build tool found",
    run=False,
)
def test_install_src(runner, test_install, tmp_path):
    dest = os.path.join(tmp_path, "stable.zip")
    urllib.request.urlretrieve(f"{GITHUB_REPO}/archive/refs/heads/stable.zip", dest)

    with zipfile.ZipFile(dest, "r") as zip:
        zip.extractall(tmp_path)

    source_dir = os.path.join(tmp_path, "Everest-stable")
    assert os.listdir(source_dir), "Failed to download source artifact: " + source_dir

    result = runner.invoke(mons_cli, ["install", test_install, "--src", source_dir])
    assert result.exit_code == 0, result.output
    assert outputs.INSTALL_SUCCESS in result.output
