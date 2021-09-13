import click

import configparser

class Install(click.ParamType):
    name = 'Install'

    def __init__(self, exist=True, resolve_install=False) -> None:
        super().__init__()
        self.exist = exist
        self.resolve_install = resolve_install

    def convert(self, value, param, ctx):
        installs: configparser.ConfigParser = ctx.obj.installs

        if self.exist:
            if not isinstance(value, configparser.SectionProxy):
                if not installs.has_section(value):
                    self.fail(f'install {value} does not exist.', param, ctx)
                elif self.resolve_install:
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
        else:
            ctx.fail('primary install not set. Use `mons set-primary` to set it.')

    return value

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

class CommandWithDefaultOptions(click.Command):
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
