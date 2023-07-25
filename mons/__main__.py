from importlib.metadata import version

import click

from mons.mons import cli

version = version("mons")

# Override built in version detection to fix issues when running as __main__
click.version_option(version=version, package_name="mons")(cli)

cli()
