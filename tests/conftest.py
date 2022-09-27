import argparse
import os

import pytest

from mons.utils import find_celeste_file


def path_exists(path):
    if os.path.exists(path):
        try:
            return find_celeste_file(path, "Celeste.exe")
        except FileNotFoundError as e:
            raise argparse.ArgumentTypeError(e)
    raise argparse.ArgumentTypeError(f"Path {path} does not exist.")


def pytest_addoption(parser: pytest.Parser, pluginmanager):
    parser.addoption(
        "--mons-test-install", "--mons", type=path_exists, dest="mons_test_install"
    )


def pytest_configure(config: pytest.Config):
    config.addinivalue_line("markers", "prioritize: prioritize this test")
    config.addinivalue_line(
        "markers", "must_pass: this test must pass in order to continue"
    )


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session, config, items):
    items.sort(key=lambda i: 0 if i.get_closest_marker("prioritize") else 1)


must_pass_failed = None


# https://stackoverflow.com/a/59392344
def pytest_runtest_makereport(item, call):
    global must_pass_failed
    if not must_pass_failed and item.iter_markers(name="must_pass"):
        if call.excinfo is not None:
            must_pass_failed = item


def pytest_runtest_setup(item):
    if must_pass_failed is not None:
        pytest.skip(f"must_pass test failed ({must_pass_failed.name})")
