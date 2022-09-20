#!/usr/bin/env python
import os
import typing as t
from importlib import import_module

import click

import mons.clickExt as clickExt
from mons.config import UserInfo


@click.group(cls=clickExt.CatchErrorsGroup)
@click.pass_context
@click.version_option()
def cli(ctx: click.Context):
    ctx.obj = ctx.with_resource(UserInfo())


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("command", nargs=-1)
@click.pass_context
def help(ctx: click.Context, command: t.List[str]):
    """Display help text for a command"""
    # No args means print program help
    if len(command) < 1 and ctx.parent:
        click.echo(cli.get_help(ctx.parent))
        exit(0)

    group = cli
    for cmd_name in command:
        cmd = group.get_command(ctx, cmd_name)
        if not cmd:
            click.echo(
                str(click.BadArgumentUsage(f"No such command '{cmd_name}'.", ctx))
            )
            exit(click.BadArgumentUsage.exit_code)

        if isinstance(cmd, click.Group):
            group = cmd
            continue
        else:
            click.echo(cmd.get_help(ctx))
            exit(0)


cmd_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "commands"))
for filename in os.listdir(cmd_folder):
    if filename.endswith(".py") and not filename.startswith("__"):
        import_module(f"mons.commands.{filename[:-3]}")
