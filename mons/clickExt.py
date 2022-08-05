import configparser
import os
import sys
from traceback import format_exception_only
from traceback import format_tb
from urllib import parse

import click

from mons.errors import TTYError


def confirm_ext(*params, skip=None, **attrs):
    if skip != None:
        return skip
    if not os.isatty(sys.stdin.fileno()):
        raise TTYError("not a tty.\nUse '--yes' to skip confirmation prompts.")

    return click.confirm(*params, **attrs)


class CatchErrorsGroup(click.Group):
    def main(self, args=None, *params, **extra):
        debug = False
        try:
            debug = "--debug" in sys.argv
            if debug and not args:
                sys.argv.remove("--debug")
            super().main(args=args, *params, **extra)
        except Exception as e:
            if debug or os.environ.get("MONS_DEBUG", "false") == "true":
                click.echo(f"\033[0;31mAn unhandled exception has occurred.\033[0m")
                click.echo("".join(format_tb(e.__traceback__)), nl=False)
                click.echo(
                    f'\033[0;31m{"".join(format_exception_only(type(e), e))}', nl=False
                )
            else:
                click.echo(f"\033[0;31m{type(e).__name__}: {e}\033[0m")
                click.echo(
                    f"""An unhandled exception has occurred.
Use the --debug flag to disable clean exception handling."""
                )


class Install(click.ParamType):
    name = "Install"

    def __init__(
        self, exist: bool = True, resolve_install: bool = False, check_path: bool = True
    ) -> None:
        super().__init__()
        self.exist = exist
        self.resolve_install = resolve_install
        self.validate_path = check_path

    def convert(self, value, param, ctx):
        if not ctx:
            return value
        installs: configparser.ConfigParser = ctx.obj.installs

        if self.exist:
            if not isinstance(value, configparser.SectionProxy):
                try:
                    Install.validate_install(
                        value, validate_path=self.validate_path, ctx=ctx
                    )
                except ValueError as err:
                    self.fail(err, param, ctx)
                except FileNotFoundError as err:
                    raise click.UsageError(err, ctx)

                if self.resolve_install:
                    value = installs[value]
        else:
            if installs.has_section(value):
                self.fail(f"Install {value} already exists.", param, ctx)

        return value

    @classmethod
    def validate_install(cls, install: str, validate_path=True, ctx=None):
        ctx = ctx or click.get_current_context()
        installs = ctx.obj.installs
        if not installs.has_section(install):
            raise ValueError(f"Install {install} does not exist")

        path = installs[install]["Path"]
        if validate_path:
            error = None
            if not os.path.exists(path):
                error = "does not exist."
            elif not os.path.basename(path) == "Celeste.exe":
                error = "does not point to Celeste.exe"

            if error:
                raise FileNotFoundError(
                    f"""Install {install} does not have a valid path:
\033[0;31m{path} {error}\033[0m
Use `set-path` to assign a new path."""
                )


class URL(click.ParamType):
    name = "URL"

    def __init__(
        self, default_scheme=None, valid_schemes=None, require_path=False
    ) -> None:
        super().__init__()
        self.default_scheme = default_scheme
        self.valid_schemes = valid_schemes
        self.require_path = require_path

    def convert(self, value, param, ctx):
        if isinstance(value, parse.ParseResult):
            return value

        try:
            parsed_url = parse.urlparse(value)

            if self.require_path and not parsed_url.path:
                self.fail("Path component required for URL.", param, ctx)
            if not parsed_url.scheme and self.default_scheme:
                parsed_url._replace(scheme=self.default_scheme)
            if self.valid_schemes and parsed_url.scheme not in self.valid_schemes:
                self.fail(f"URI scheme '{parsed_url.scheme}' not allowed.", param, ctx)

            return parsed_url
        except ValueError:
            self.fail(f"{value} is not a valid URL.", param, ctx)


class DefaultOption(click.Option):
    """Mark this option as being a _default option"""

    register_default = True

    def __init__(self, param_decls=[], **attrs):
        param_decls = [decl + "_default" for decl in param_decls] or None
        super(DefaultOption, self).__init__(param_decls, **attrs)
        self.hidden = True


class ExplicitOption(click.Option):
    """Fix the help string for this option to display as an optional argument"""

    def get_help_record(self, ctx):
        help = super(ExplicitOption, self).get_help_record(ctx)
        if help:
            return (help[0].replace(" ", "[=", 1) + "]",) + help[1:]

    def sphinx_get_help_record(self, help_func):
        help = help_func(self)
        return (help[0].replace(" ", "[=", 1) + "]",) + help[1:]


class PlaceHolder(click.Argument):
    """Mark this argument as a placeholder that isn't processed"""

    register_placeholder = True


class CommandExt(click.Command):
    """Command implementation for extended option and argument types"""

    def make_parser(self, ctx):
        """Strip placeholder params"""
        self.params = [
            a for a in self.params if not getattr(a, "register_placeholder", None)
        ]
        return super().make_parser(ctx)

    def parse_args(self, ctx, args):
        """Translate any opt to opt_default as needed"""
        options = [
            o for o in ctx.command.params if getattr(o, "register_default", None)
        ]
        prefixes = {
            p.replace("_default", "")
            for p in sum((o.opts for o in options), [])
            if p.startswith("--")
        }
        for i, a in enumerate(args):
            a = a.split("=", 1)
            if a[0] in prefixes and len(a) == 1:
                args[i] = a[0] + "_default"

        return super(CommandExt, self).parse_args(ctx, args)
