#!/usr/bin/env python
import logging
import os
import typing as t
from importlib import import_module

import click

import mons.clickExt as clickExt
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


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("command", nargs=-1)
@click.pass_context
def help(ctx: click.Context, command: t.List[str]):
    """Display help text for a command."""

    # No args means print program help
    if len(command) < 1 and ctx.parent:
        click.echo(cli.get_help(ctx.parent))
        exit(0)

    group = cli
    cmd_path = []
    for cmd_name in command:
        cmd_path.append(cmd_name)
        cmd = group.get_command(ctx, cmd_name)
        if not cmd:
            err_msg = "No such command '{}.'".format(" ".join(cmd_path))
            click.echo(str(click.BadArgumentUsage(err_msg, ctx)))
            exit(click.BadArgumentUsage.exit_code)

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
