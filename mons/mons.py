#!/usr/bin/env python
import logging
import os
import shutil
import subprocess
import sys
import typing as t
from importlib import import_module

# namespace package support added in 3.10
if sys.version_info >= (3, 10):  # novermin
    from importlib.resources import files
else:
    from importlib_resources import files

import click

import mons.clickExt as clickExt
import mons.spec
from mons.config import Env
from mons.config import UserInfo
from mons.logging import ClickFormatter
from mons.logging import EchoHandler


# This should be the root module logger, even though __name__ is 'mons.mons'
logger = logging.getLogger("mons")


@click.group(
    cls=clickExt.CatchErrorsGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.pass_context
@click.version_option()
def cli(ctx: click.Context):
    """Install and manage mods for Celeste."""
    # Logging should not be setup in the global scope or it breaks pytest log capturing
    handler = EchoHandler()
    handler.setFormatter(ClickFormatter())
    logger.addHandler(handler)
    # Required to avoid duplicate logging from subprocesses, among other things
    logger.propagate = False

    ctx.obj = ctx.with_resource(UserInfo())
    # Inject another context as the parent
    env_ctx = click.Context(ctx.command, ctx.parent, obj=Env())
    ctx.parent = env_ctx


_SPEC_NAMES = [
    attr.lower() for attr in dir(mons.spec) if attr.isupper() and attr.endswith("SPEC")
]

_MAN_PAGES = {
    "": ("1", "mons"),
    "mons": ("1", "mons"),
    "mods": ("1", "mons-mods"),
    **dict.fromkeys(["config", "configuration"], ("5", "mons")),
    "glossary": ("7", "mons-glossary"),
    **dict.fromkeys(_SPEC_NAMES, ("7", "mons-glossary")),
    **dict.fromkeys(["overlay", "overlayfs"], ("7", "mons-overlayfs")),
}


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("command", nargs=-1)
@click.pass_context
def help(ctx: click.Context, command: t.List[str]):
    """Display help text for a command."""
    try:
        man_pages = files("mons.man")
    except FileNotFoundError:
        man_pages = None

    man_path = shutil.which("man")
    if man_pages and man_path and " ".join(command).lower() in _MAN_PAGES:
        cmd_str = " ".join(command).lower()
        env = os.environ
        if cmd_str in _SPEC_NAMES:
            # If using less, attempt to jump to the appropriate section.
            env["LESS"] = " ".join(
                filter(None, (env.get("LESS", None), r"+/^\s+" + cmd_str))
            )
        section, page = _MAN_PAGES[cmd_str]
        subprocess.run(
            [
                man_path,
                "--local-file",
                "-",
            ],
            env=env,
            # importlib.resources' joinpath only accepts one argument before 3.12
            input=man_pages.joinpath(f"man{section}")
            .joinpath(f"{page}.{section}")
            .read_bytes(),
        )
        return

    group = cli
    cmd_path = []
    for cmd_name in command:
        cmd_path.append(cmd_name)
        cmd = group.get_command(ctx, cmd_name)
        if not cmd:
            err_msg = "No help entry for '{}'.".format(" ".join(cmd_path))
            raise click.BadArgumentUsage(err_msg, ctx)

        if isinstance(cmd, click.Group):
            group = cmd
            continue
        else:
            # ctx currently thinks it's for the help command, this corrects the usage text
            ctx.info_name = " ".join(cmd_path)
            click.echo(cmd.get_help(ctx))
            exit(0)


cmd_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "commands"))
for filename in os.listdir(cmd_folder):
    if filename.endswith(".py") and not filename.startswith("__"):
        import_module(f"mons.commands.{filename[:-3]}")
