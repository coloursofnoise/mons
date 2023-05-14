import argparse
import os
import sys

import pytest

from mons.utils import find_celeste_asm

PLATFORM_MARKS = set("darwin linux win32".split())


def path_exists(path):
    if os.path.exists(path):
        try:
            return find_celeste_asm(path)
        except FileNotFoundError as e:
            raise argparse.ArgumentTypeError(e)
    raise argparse.ArgumentTypeError(f"Path {path} does not exist.")


def pytest_addoption(parser: pytest.Parser, pluginmanager):
    parser.addoption(
        "--mons-test-install", "--mons", type=path_exists, dest="mons_test_install"
    )


def pytest_configure(config: pytest.Config):
    for plat in PLATFORM_MARKS:
        config.addinivalue_line(
            "markers", f"{plat}: mark this test as platform-specific"
        )
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
    # must_pass test checks
    if must_pass_failed is not None:
        pytest.skip(f"must_pass test failed ({must_pass_failed.name})")

    # platform-specific test checks
    supported_platforms = PLATFORM_MARKS.intersection(
        mark.name for mark in item.iter_markers()
    )
    plat = sys.platform
    if supported_platforms and plat not in supported_platforms:
        pytest.skip("cannot run on platform {}".format(plat))


@pytest.fixture
def data_file(request, tmp_path):
    data = request.param
    data_file = os.path.join(tmp_path, "data_file")

    # indicator for missing file
    if data is None:
        yield data_file
        return

    with open(data_file, "w") as file:
        file.write(data)
    yield data_file


@pytest.fixture
def test_name(request):
    yield request.node.name
