import argparse
import os
import sys
import urllib.request
import zipfile
from contextlib import contextmanager

import pytest

from mons.utils import find_celeste_asm
from mons.version import Version

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
    config.addinivalue_line(
        "markers", "data_file_zip: pass arguments to the data_file_zip fixture"
    )
    config.addinivalue_line(
        "markers",
        "data_file_download: pass arguments to the data_file_download fixture",
    )
    config.addinivalue_line(
        "markers",
        "mock_filesystem: pass arguments to the mock_filesystem fixture",
    )


@pytest.hookimpl(tryfirst=True)  # pyright:ignore[reportUntypedFunctionDecorator]
def pytest_collection_modifyitems(session, config, items):
    items.sort(key=lambda i: 0 if i.get_closest_marker("prioritize") else 1)


must_pass_failed = None


# https://stackoverflow.com/a/59392344
def pytest_runtest_makereport(item, call):
    global must_pass_failed
    if not must_pass_failed and item.get_closest_marker(name="must_pass"):
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


def pytest_make_parametrize_id(config, val, argname):
    if isinstance(val, Version):
        return str(val)


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
def data_file_zip(request: pytest.FixtureRequest, tmp_path):
    marker = request.node.get_closest_marker("data_file_zip")
    data = marker.args[0] if marker else request.param
    filenames = []
    for i, file in enumerate(data if isinstance(data, list) else [data]):
        filenames.append(os.path.join(tmp_path, f"data_file_{i}.zip"))
        # indicator for missing file
        if data is None:
            continue

        with zipfile.ZipFile(filenames[i], "w") as zip:
            for filename, filedata in file.items():
                zip.writestr(filename, filedata)
    yield tuple(filenames)


@pytest.fixture
def data_file_download(request: pytest.FixtureRequest, cache):
    marker = request.node.get_closest_marker("data_file_download")
    url, filename = marker.args if marker else request.param
    dest = os.path.join(cache.mkdir("mons_" + request.module.__name__), filename)
    if not os.path.exists(dest):
        urllib.request.urlretrieve(url, dest)
    assert os.path.isfile(dest), "File download failed"
    yield dest


@pytest.fixture
def test_name(request):
    yield request.node.name


@pytest.fixture(autouse=True)
def assertion_msg():
    @contextmanager
    def assertion_msg(msg: str):
        try:
            yield
        except AssertionError as e:
            e.args = (e.args[0] + "\n" + msg,)
            raise

    return assertion_msg


@pytest.fixture()
def mock_filesystem(request, tmp_path):
    marker = request.node.get_closest_marker("mock_filesystem")
    if marker:
        mockup = marker.args[0]
        walk = marker.kwargs.get("walk", False)
    else:
        mockup = request.param
        walk = False
    root = os.path.join(tmp_path, "mock_fs")
    os.mkdir(root)

    if not mockup:
        yield root
        return

    paths = list()

    def create_fs(root, mockup):
        if isinstance(mockup, dict):
            for dir, contents in mockup.items():
                path = os.path.join(root, dir)
                os.mkdir(path)
                paths.append(path)
                create_fs(path, contents)
        elif isinstance(mockup, (list, tuple)):
            for node in mockup:
                create_fs(root, node)
        else:
            assert isinstance(mockup, str)
            path = os.path.join(root, mockup)
            if mockup.endswith("/"):
                os.mkdir(path)
            else:
                with open(path, "x"):
                    pass
            paths.append(path)

    create_fs(root, mockup)

    # set consistent last modified/accessed times for created paths
    for i, path in enumerate(paths):
        os.utime(path, (i, i))

    yield os.walk(root) if walk else root
