import os
import shutil
import zipfile

import outputs
import pytest

import mons.commands.main
from mons.mons import cli as mons_cli

# mock data for Everest build list in ./_data/build_list

GITHUB_REPO = "https://github.com/EverestAPI/Everest"


@pytest.fixture(autouse=True)
def mock_installer(monkeypatch):
    monkeypatch.setattr(mons.commands.main, "download_artifact", lambda *args: None)
    monkeypatch.setattr(mons.commands.main, "run_installer", lambda *args: True)


def test_install_default(runner_result, test_install):
    # install preferred branch, set to a stable version by `test_install` fixture
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


@pytest.mark.data_file_download(
    f"{GITHUB_REPO}/releases/latest/download/olympus-build.zip", "olympus-build.zip"
)
def test_install_zip(runner_result, test_install, data_file_download):
    with runner_result(
        mons_cli, ["install", test_install, data_file_download]
    ) as result:
        assert result.exit_code == 0
        assert outputs.INSTALL_SUCCESS in result.output


@pytest.mark.data_file_download(
    f"{GITHUB_REPO}/releases/latest/download/olympus-build.zip", "olympus-build.zip"
)
def test_install_stdin(runner_result, test_install, data_file_download):
    with open(data_file_download) as data:
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
@pytest.mark.data_file_download(
    f"{GITHUB_REPO}/archive/refs/heads/stable.zip", "stable.zip"
)
def test_install_src(runner_result, test_install, cache, data_file_download):
    source_dir = os.path.join(cache.mkdir("mons_test_install"), "Everest-stable")
    if not os.path.exists(source_dir):
        with zipfile.ZipFile(data_file_download, "r") as zip:
            zip.extractall(cache.mkdir("mons_test_install"))

    assert os.listdir(source_dir), "Failed to download source artifact: " + source_dir

    with runner_result(
        mons_cli, ["install", test_install, "--src", source_dir]
    ) as result:
        assert result.exit_code == 0
        assert outputs.INSTALL_SUCCESS in result.output
        assert "Building Everest source" in result.output

    # Previous command builds straight to `test_install.path`.
    # Build artifacts in in place so that `--no-build` is possible.
    mons.commands.main.build_source(source_dir, None, False, None, [])
    with runner_result(
        mons_cli, ["install", test_install, "--src", source_dir, "--no-build"]
    ) as result:
        assert result.exit_code == 0
        assert outputs.INSTALL_SUCCESS in result.output
        assert "Copying build artifacts" in result.output
