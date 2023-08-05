import json
import os
import pathlib
from contextlib import contextmanager

import click
import pytest
from click.testing import CliRunner

from mons import downloading
from mons import sources
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
def ctx(runner):
    @click.command
    def cli():
        pass

    ctx = click.Context(cli)
    with ctx:
        yield ctx


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


@pytest.fixture
def runner_result(runner, assertion_msg):
    @contextmanager
    def runner_result(*args, **kwargs):
        result = runner.invoke(*args, **kwargs)
        error_msg = "=" * 10 + "\nCOMMAND OUTPUT\n\n" + result.output + "=" * 10
        with assertion_msg(error_msg):
            yield result

    return runner_result


@pytest.fixture(autouse=True)
def mock_sources(monkeypatch, request: pytest.FixtureRequest):
    _open_url = downloading.open_url

    def mocked_open_url(request, *args, **kwargs):
        if isinstance(request, str) and request.startswith("file://"):
            return _open_url(request, *args, **kwargs)
        pytest.fail(
            f"Attempted to make a forbidden request. Currently patched: {implemented}"
        )

    implemented = list()
    for module in (downloading, sources):
        monkeypatch.setattr(
            module,
            "open_url",
            mocked_open_url,
        )

    data_path = os.path.join(os.path.dirname(request.path), "_data")
    requesters = [attr for attr in dir(sources) if attr.startswith("fetch_")]

    for attr in requesters:
        module_patch = getattr(request.module, attr, None)
        if module_patch:
            monkeypatch.setattr(sources, attr, module_patch)
            implemented.append(attr)
        elif os.path.exists(data_path) and attr[len("fetch_") :] in os.listdir(
            data_path
        ):
            data_file = os.path.join(data_path, attr[len("fetch_") :])

            def read_data_file(*args, **kwargs):
                with open(data_file) as f:
                    return json.load(f)

            monkeypatch.setattr(sources, attr, read_data_file)
            implemented.append(attr)
