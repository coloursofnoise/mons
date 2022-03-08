import click

import os
import sys
import configparser

class CatchErrorsGroup(click.Group):
    def main(self, args=None, prog_name=None, complete_var=None, standalone_mode=True, windows_expand_args=True, **extra):
        debug = False
        try:
            debug = '--debug' in sys.argv
            if debug and not args:
                sys.argv.remove('--debug')
            super().main(args=args, prog_name=prog_name, complete_var=complete_var, standalone_mode=standalone_mode, windows_expand_args=windows_expand_args, **extra)
        except Exception as e:
            if debug or os.environ.get("MONS_DEBUG", 'false') == 'true':
                click.echo('\033[0;31m', nl=False)
                raise
            else:
                click.echo(f'\033[0;31m{type(e).__name__}: {e}\033[0m')
                click.echo(f'''An unhandled exception was encountered.
Use the --debug flag to disable clean exception handling.''')

class Install(click.ParamType):
    name = 'Install'

    def __init__(self, exist: bool=True, resolve_install: bool=False, check_path: bool=True) -> None:
        super().__init__()
        self.exist = exist
        self.resolve_install = resolve_install
        self.validate_path = check_path

    def convert(self, value, param, ctx):
        installs: configparser.ConfigParser = ctx.obj.installs

        if self.exist:
            if not isinstance(value, configparser.SectionProxy):
                if not installs.has_section(value):
                    self.fail(f'Install {value} does not exist.', param, ctx)

                path = installs[value]['Path']
                if self.validate_path:
                    error = None
                    if not os.path.exists(path):
                        error = 'does not exist.'
                    elif not os.path.basename(path) == 'Celeste.exe':
                        error = 'does not point to Celeste.exe'

                    if error:
                        raise click.UsageError(f'''Install {value} does not have a valid path:
\033[0;31m{path} {error}\033[0m
Use the `set-path` command to assign a new path.''', ctx)

                if self.resolve_install:
                    value = installs[value]
        else:
            if installs.has_section(value):
                self.fail(f'Install {value} already exists.', param, ctx)

        return value

class DefaultOption(click.Option):
    """ Mark this option as being a _default option """
    register_default = True

    def __init__(self, param_decls=[], **attrs):
        param_decls = [decl + '_default' for decl in param_decls] or None
        super(DefaultOption, self).__init__(param_decls, **attrs)
        self.hidden = True

class ExplicitOption(click.Option):
    """ Fix the help string for this option to display as an optional argument """
    def get_help_record(self, ctx):
        help = super(ExplicitOption, self).get_help_record(ctx)
        if help:
            return (help[0].replace(' ', '[=', 1) + ']',) + help[1:]

class CommandWithDefaultOptions(click.Command):
    """ Command implementation for `DefaultOption` and `ExplicitOption` option types """
    def parse_args(self, ctx, args):
        """ Translate any opt to opt_default as needed """
        options = [o for o in ctx.command.params
                   if getattr(o, 'register_default', None)]
        prefixes = {p.replace('_default', '')
                    for p in sum([o.opts for o in options], [])
                    if p.startswith('--')}
        for i, a in enumerate(args):
            a = a.split('=', 1)
            if a[0] in prefixes and len(a) == 1:
                args[i] = a[0] + '_default'

        return super(CommandWithDefaultOptions, self).parse_args(ctx, args)
