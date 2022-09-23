import pytest
from click.testing import CliRunner

from mons.mons import cli as mons_cli


@pytest.fixture(scope="function")
def runner(request):
    return CliRunner()


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
