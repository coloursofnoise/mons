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
