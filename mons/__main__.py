import sys

import click

from mons.mons import cli

if sys.version_info >= (3, 8):  # novermin
    from importlib.metadata import version

    version = version("mons")
else:
    import pkg_resources

    version = pkg_resources.get_distribution("mons").version

# Override built in version detection to fix issues when running as __main__
click.version_option(version=version, package_name="mons")(cli)

cli()
