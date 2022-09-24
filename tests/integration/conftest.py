import os
import pathlib

import pytest

from mons.mons import cli as mons_cli


def pytest_collection_modifyitems(session, config, items):
    module = pathlib.Path(os.path.dirname(__file__))
    for item in items:
        if module in item.path.parents:
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
