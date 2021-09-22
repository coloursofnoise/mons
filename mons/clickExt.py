import click
from click._termui_impl import ProgressBar

import shutil

import os
import sys
import configparser
from gettext import ngettext

from .errors import MaybeDefault

class UnhandledError(click.ClickException):
    def __init__(self, message):
        super().__init__(message)

class CatchErrorsGroup(click.Group):
    def main(self, args=None, prog_name=None, complete_var=None, standalone_mode=True, windows_expand_args=True, **extra):
        debug = False
        try:
            debug = '--debug' in sys.argv
            if debug and not args:
                sys.argv.remove('--debug')
            super().main(args=args, prog_name=prog_name, complete_var=complete_var, standalone_mode=standalone_mode, windows_expand_args=windows_expand_args, **extra)
        except Exception as e:
            if debug:
                click.echo('\033[0;31m', nl=False)
                raise
            else:
                click.echo(f'\033[0;31m{type(e).__name__}: {e}\033[0m')
                click.echo(f'''An unhandled exception was encountered.
Use the --debug flag to disable clean exception handling.''')

class Install(click.ParamType):
    name = 'Install'

    def __init__(self, exist=True, resolve_install=False, check_path=True) -> None:
        super().__init__()
        self.exist = exist
        self.resolve_install = resolve_install
        self.validate_path = check_path

    def convert(self, value, param, ctx):
        installs: configparser.ConfigParser = ctx.obj.installs

        if self.exist:
            if not isinstance(value, configparser.SectionProxy):
                if not installs.has_section(value):
                    if not param.required:
                        raise MaybeDefault(default_primary(ctx, param, None))
                    else:
                        self.fail(f'install {value} does not exist.', param, ctx)

                path = installs[value]['Path']
                if self.validate_path:
                    error = None
                    if not os.path.exists(path):
                        error = 'does not exist.'
                    elif not os.path.basename(path) == 'Celeste.exe':
                        error = 'does not point to Celeste.exe'

                    if error:
                        raise click.UsageError(f'''install {value} does not have a valid path:
\033[0;31m{path} {error}\033[0m
Use the `set-path` command to assign a new path.''', ctx)

                if self.resolve_install:
                    value = installs[value]
        else:
            if installs.has_section(value):
                self.fail(f'install {value} already exists.', param, ctx)

        return value

def default_primary(ctx: click.Context, param, value):
    if value is None:
        config: configparser.ConfigParser = ctx.obj.config
        if config.has_option('user', 'primaryInstall'):
            value = config.get('user', 'primaryInstall')
            if isinstance(param.type, Install) and param.type.resolve_install:
                value = ctx.obj.installs[value]

        else:
            ctx.fail('primary install not set. Use `mons set-primary` to set it.')

    return value

class DefaultArgsCommand(click.Command):
    def parse_args(self, ctx: click.Context, cmdArgs):
        if not cmdArgs and self.no_args_is_help and not ctx.resilient_parsing:
            click.echo(ctx.get_help(), color=ctx.color)
            ctx.exit()

        parser = self.make_parser(ctx)
        d_idx = 0
        while True:
            opts, args, param_order = parser.parse_args(args=cmdArgs.copy())

            params = click.core.iter_params_for_processing(param_order, self.get_params(ctx))
            maybe_default = False
            for param in params:
                try:
                    value, args = param.handle_parse_result(ctx, opts, args)
                except MaybeDefault as d:
                    cmdArgs.insert(d_idx, d.value)
                    d_idx += 1
                    maybe_default = True
                    break

            if not maybe_default:
                break

        if args and not ctx.allow_extra_args and not ctx.resilient_parsing:
            ctx.fail(
                ngettext(
                    "Got unexpected extra argument ({args})",
                    "Got unexpected extra arguments ({args})",
                    len(args),
                ).format(args=" ".join(map(str, args)))
            )

        ctx.args = args
        return args

class DefaultOption(click.Option):
    """ Mark this option as being a _default option """
    register_default = True

    def __init__(self, param_decls=[], **attrs):
        param_decls = [decl + '_default' for decl in param_decls] or None
        super(DefaultOption, self).__init__(param_decls, **attrs)
        self.hidden = True

class ExplicitOption(click.Option):
    def get_help_record(self, ctx):
        help = super(ExplicitOption, self).get_help_record(ctx)
        if help:
            return (help[0].replace(' ', '[=', 1) + ']',) + help[1:]

class CommandWithDefaultOptions(DefaultArgsCommand):
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

if os.name == "nt":
    BEFORE_BAR = "\r"
    CLEAR_BAR = "\r"
else:
    BEFORE_BAR = "\r\033[?25l"
    CLEAR_BAR = "\033[?25h\r"

class TempProgressBar(ProgressBar):
    def render_finish(self) -> None:
        if self.is_hidden:
            return

        self.file.write(BEFORE_BAR)
        self.file.write(" " * (shutil.get_terminal_size().columns - len(CLEAR_BAR)))
        self.file.write(CLEAR_BAR)
        self.file.flush()

def tempprogressbar(
    iterable = None,
    length = None,
    label = None,
    show_eta: bool = True,
    show_percent = None,
    show_pos: bool = False,
    item_show_func = None,
    fill_char: str = "#",
    empty_char: str = "-",
    bar_template: str = "%(label)s  [%(bar)s]  %(info)s",
    info_sep: str = "  ",
    width: int = 36,
    file = None,
    color = None,
    update_min_steps: int = 1,
) -> TempProgressBar:
    color = click.globals.resolve_color_default(color)
    return TempProgressBar(
        iterable=iterable,
        length=length,
        show_eta=show_eta,
        show_percent=show_percent,
        show_pos=show_pos,
        item_show_func=item_show_func,
        fill_char=fill_char,
        empty_char=empty_char,
        bar_template=bar_template,
        info_sep=info_sep,
        file=file,
        label=label,
        width=width,
        color=color,
        update_min_steps=update_min_steps,
    )