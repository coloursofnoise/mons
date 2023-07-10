import errno
import os
import pathlib
import sys
from importlib import reload

import pytest

import mons.install
from mons.mons import cli as mons_cli
from mons.version import Version


def pytest_collection_modifyitems(session, config, items):
    module = pathlib.Path(os.path.dirname(__file__))
    for item in items:
        if module == item.path.parent:
            item.add_marker(pytest.mark.slow_integration_test)


# We only need to log this warning once for each test run
log_test_install_warning = True


@pytest.fixture(scope="function")
def test_install_path(pytestconfig: pytest.Config, cache: pytest.Cache):
    # prioritize cmdline arg so that it can be changed
    install_path: str = pytestconfig.getoption("mons_test_install", cache.get("mons/test_install", None))  # type: ignore

    if not install_path:
        global log_test_install_warning
        if log_test_install_warning:
            log_test_install_warning = True
            pytest.skip(
                "Test install not configured. Use the `--mons-test-install` cmdline flag to provide a test install."
            )
        pytest.skip()

    if os.path.exists(install_path):
        install_path = os.path.abspath(install_path)
        cache.set("mons/test_install", install_path)
        return install_path
    else:
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), install_path)


@pytest.fixture(scope="function")
def test_install(runner, test_name, test_install_path, monkeypatch):
    # use a stable version number for default branch detection
    monkeypatch.setattr(
        mons.install, "parseExeInfo", lambda *args: (Version(1, 4030, 0), "FNA")
    )

    install_name = f"_pytest_{test_name}"
    result = runner.invoke(mons_cli, ["add", install_name, test_install_path])
    if result.exit_code != 0:
        pytest.skip(result.output)
    return install_name


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("MONS_DEBUG", "true")


@pytest.fixture(autouse=True)
def isolated_filesystem(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Isolate all referenced files to temp folder"""
    user_dirs = ["config", "cache", "data"]
    ret = dict()
    for dir in user_dirs:
        monkeypatch.setattr(
            f"mons.config.PlatformDirs.user_{dir}_dir", os.path.join(tmp_path, dir)
        )
        ret[f"{dir}_dir"] = os.path.join(tmp_path, dir)
    # reload the config module to re-assign global constants
    reload(sys.modules["mons.config"])
    return ret
