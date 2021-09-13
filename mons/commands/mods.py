import click
from click import echo_via_pager, echo

import os

import semver

from mons.clickExt import *
from mons.mons import UserInfo, pass_userinfo
from mons.utils import *

@click.group(name='mods', help='Manage Everest mods')
@click.pass_context
def cli(ctx):
    pass

@cli.command(hidden=True)
@click.argument('name', type=Install(), required=False, callback=default_primary)
@pass_userinfo
def list(userinfo: UserInfo, name):
    basePath = os.path.join(os.path.dirname(userinfo.installs[name]['path']), 'Mods')
    files = os.listdir(basePath)
    if os.name == 'nt':
        for file in files:
            meta = read_mod_info(os.path.join(basePath, file))
            if meta:
                echo(f'{meta.Name}\t{meta.Version}')
    else:
        echo_via_pager(files)

@cli.command(hidden=True)
@click.argument('search')
def search(search):
    mod_list = get_mod_list()
    if search in mod_list:
        echo(mod_list[search]['GameBananaId'])
        return
    
    search_result = search_mods(search)
    for item in search_result:
        match = [mod for mod, data in mod_list.items() if data['GameBananaId'] == item['itemid']]
        for m in match:
            echo(m)
        if len(match) < 1:
            echo(item['itemid'])

@cli.command(hidden=True)
@click.argument('name', type=Install(resolve_install=True), required=False, callback=default_primary)
@click.argument('mod')
def add(name, mod):
    pass

@cli.command(hidden=True)
@click.argument('name', type=Install(resolve_install=True), required=False, callback=default_primary)
@click.argument('mod')
def remove(name, mod):
    pass

@cli.command()
@click.argument('name', type=Install(resolve_install=True), required=False, callback=default_primary)
#@click.argument('mod', required=False)
@click.option('--all', is_flag=True, help='Update all currently enabled mods.')
#@click.option('--upgrade-only', is_flag=True) # Only update if latest file has a higher version
def update(name, all):
    if not all:
        raise click.UsageError('this command can currently only be used with the --all option')

    mod_list = get_mod_list()
    updates: List[UpdateInfo] = []
    if all:
        installed = installed_mods(os.path.join(os.path.dirname(name['path']), 'Mods'))
        for meta in installed:
            if meta.Name in mod_list:
                server = mod_list[meta.Name]
                latest_hash = server['xxHash'][0]
                if meta.Hash and latest_hash != meta.Hash:
                    update = UpdateInfo(
                        meta,
                        semver.VersionInfo.parse(server['Version']),
                        server['URL'],
                    )
                    updates.append(update)

    total_size = 0
    for update in updates:
        total_size += int(urllib.request.urlopen(update.Url).headers['Content-Length']) - update.Old.Size

    if len(updates) < 1:
        echo('All mods up to date')
        return
    
    echo(f'{len(updates)} updates available:')
    for update in updates:
        echo(f'  {update.Old.Name}: {update.Old.Version} -> {update.New}')
    
    if total_size >= 0:
        echo(f'After this operation, an additional {total_size} B disk space will be used')
    else:
        echo(f'After this operation, {abs(total_size)} B disk space will be freed')
    
    if not click.confirm('Continue?', default=True):
        return

    for update in updates:
        download_with_progress(update.Url, update.Old.Path, f'Downloading mod: {update.Old.Name}', atomic=True)
