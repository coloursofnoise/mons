#!/usr/bin/env python
import click

from .clickExt import *
from .config import *

pass_userinfo = click.make_pass_decorator(UserInfo)


@click.group(cls=CatchErrorsGroup)
@click.pass_context
@click.version_option()
def cli(ctx: click.Context):
    ctx.obj = ctx.with_resource(UserInfo())


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("command", nargs=-1)
@click.pass_context
def help(ctx: click.Context, command):
    """Display help text for a command"""
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


from .commands import main, mods

cli.add_command(mods.cli)
