#!/usr/bin/env python

import click

from .config import *
from .clickExt import *

pass_userinfo = click.make_pass_decorator(UserInfo)

@click.group(cls=CatchErrorsGroup)
@click.pass_context
@click.version_option()
def cli(ctx: click.Context):
    ctx.obj = ctx.with_resource(UserInfo())

from .commands import main, mods
cli.add_command(mods.cli)
