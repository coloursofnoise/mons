import errno
import os
import pathlib

import pytest


def pytest_collection_modifyitems(session, config, items):
    module = pathlib.Path(os.path.dirname(__file__))
    for item in items:
        if module == item.path.parent:
            item.add_marker(pytest.mark.slow_integration_test)


# We only need to log this warning once for each test run
log_test_install_warning = True


@pytest.fixture(scope="function")
def test_install(pytestconfig: pytest.Config, cache: pytest.Cache):
    # prioritize cmdline arg so that it can be changed
    install_path = pytestconfig.getoption("mons_test_install", None)  # type: ignore
    if not install_path:
        install_path = cache.get("mons/test_install", None)

    if not install_path:
        global log_test_install_warning
        if log_test_install_warning:
            log_test_install_warning = True
            pytest.skip(
                "Test install not configured. Use the `--mons-test-install` cmdline flag to provide a test install."
            )
        pytest.skip()

    if os.path.exists(install_path):  # type: ignore
        cache.set("mons/test_install", install_path)
        return install_path
    else:
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), install_path)


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("MONS_DEBUG", "true")


@pytest.fixture(autouse=True)
def isolated_filesystem(monkeypatch, tmp_path):
    """Isolate all referenced files to temp folder"""
    monkeypatch.setattr("mons.config.config_dir", os.path.join(tmp_path, ".config"))
    return {"config_dir": os.path.join(tmp_path, ".config")}
