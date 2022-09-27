import os
import shutil
import urllib.request
import zipfile

import pytest

from mons.mons import cli as mons_cli

TEST_INSTALL = "_mons_testing"
GITHUB_REPO = "https://github.com/EverestAPI/Everest"


def setup_install(runner, test_install):
    if runner.invoke(mons_cli, ["add", TEST_INSTALL, test_install]).exit_code != 0:
        pytest.skip()


def test_install(runner, test_install, cache: pytest.Cache):
    setup_install(runner, test_install)

    # install preferred branch (defaults to stable)
    result = runner.invoke(mons_cli, ["install", TEST_INSTALL])
    assert result.exit_code == 0, result.output
    assert "Install success" in result.output


def try_get_artifact(test_install):
    install_dir = os.path.dirname(test_install)
    if os.path.exists(os.path.join(install_dir, "olympus-build.zip")):
        return os.path.join(install_dir, "olympus-build.zip")
    elif os.path.exists(os.path.join(install_dir, "main.zip")):
        return os.path.join(install_dir, "main.zip")
    else:
        pytest.skip("Everest build artifact not available")


def test_install_url(runner, test_install):
    url = "file://" + try_get_artifact(test_install)

    setup_install(runner, test_install)

    result = runner.invoke(mons_cli, ["install", TEST_INSTALL, "--url", url])
    assert result.exit_code == 0, result.output
    assert "Install success" in result.output


def test_install_zip(runner, test_install):
    url = try_get_artifact(test_install)

    setup_install(runner, test_install)

    result = runner.invoke(mons_cli, ["install", TEST_INSTALL, "--zip", url])
    assert result.exit_code == 0, result.output
    assert "Install success" in result.output


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

    setup_install(runner, test_install)

    result = runner.invoke(mons_cli, ["install", TEST_INSTALL, f"--src={source_dir}"])
    assert result.exit_code == 0, result.output
    assert "Install success" in result.output
