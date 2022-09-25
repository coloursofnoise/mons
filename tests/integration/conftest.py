import os
import pathlib

import pytest
from click.testing import CliRunner

from mons.mons import cli as mons_cli


def pytest_collection_modifyitems(session, config, items):
    module = pathlib.Path(os.path.dirname(__file__))
    for item in items:
        if module == item.path.parent:
            item.add_marker(pytest.mark.integration_test)


def get_commands(cli, *, prefix=""):
    for cmd in cli.commands.values():
        if hasattr(cmd, "commands"):
            yield from get_commands(cmd, prefix=prefix + f"{cmd.name} ")
        else:
            cmd.qualified_name = prefix + cmd.name
            yield cmd


@pytest.fixture(
    scope="module",
    params=list(get_commands(mons_cli)),
    ids=lambda cmd: cmd.qualified_name,
)
def command(request):
    yield request.param


@pytest.fixture(scope="function")
def runner():
    """
    runner.isolated_filesystem isn't necessary because mons never operates directly on the working directory
    but if it did:

    ```
    with runner.isolated_filesystem(temp_dir=tmp_path):
        yield runner
    ```
    """
    return CliRunner()
