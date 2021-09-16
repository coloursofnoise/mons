import click
from click import echo_via_pager, echo

import os

from mons.clickExt import *
from mons.mons import UserInfo, pass_userinfo
from mons.utils import *
from mons.version import Version

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
            echo('entry not found: ' + str(item['itemid']))

def prompt_mod_selection(options: Dict, max: int=-1):
    matchKeys = sorted(options.keys(), key=lambda key: options[key]['LastUpdate'], reverse=True)
    url = None
    if len(matchKeys) == 1:
        key = matchKeys[0]
        echo(f'Mod found: {key} {options[key]["Version"]}')
        url = str(options[key]['URL'])

    if len(matchKeys) > 1:
        echo('Mods found:')
        idx = 1
        for key in matchKeys:
            if max > -1 and idx > max:
                break
            echo(f'  [{idx}] {key} {options[key]["Version"]}')
            idx += 1

        selection = click.prompt('Select mod to add', type=click.IntRange(0, idx), default=0, show_default=False)
        if selection:
            key = matchKeys[selection-1]
            echo(f'Selected mod: {key} {options[key]["Version"]}')
            url = str(options[key]['URL'])
        else:
            echo('Aborted!')
    return url

@cli.command()
@click.argument('name', type=Install(resolve_install=True), required=False, callback=default_primary)
@click.argument('mod')
@click.option('--search', is_flag=True)
def add(name, mod: str, search):
    url = None
    filename = None
    file = None

    if search:
        mod_list = get_mod_list()
        search_result = search_mods(mod)
        matches = {}
        for item in search_result:
            matches.update({mod: data for mod, data in mod_list.items() if data['GameBananaId'] == item['itemid']})

        if len(matches) < 1:
            echo('No results found.')
            return
        
        url = prompt_mod_selection(matches, max=9)

    elif os.path.exists(mod):
        file = mod

    elif mod.endswith('.zip') and mod.startswith(('http://', 'https://', 'file://')):
        echo('Attempting direct file download:')
        # Change User-Agent for discord, etc... downloads
        opener=urllib.request.build_opener()
        opener.addheaders=[('User-Agent','Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/36.0.1941.0 Safari/537.36')]
        urllib.request.install_opener(opener)
        url = mod

    else:
        mod_list = get_mod_list()
        
        if mod in mod_list:
            echo(f'Mod found: {mod} {mod_list[mod]["Version"]}')
            url = str(mod_list[mod]['URL'])

        if mod.startswith(('https://gamebanana.com/mods', 'http://gamebanana.com/mods')) and mod.split('/')[-1].isdigit():
            modID = int(mod.split('/')[-1])
            matches = {key: val for key, val in mod_list.items() if modID == val['GameBananaId']}
            if len(matches) > 0:
                url = prompt_mod_selection(matches)
            else:
                echo('Mod not found in database!')
                downloads = json.load(download_with_progress(
                    f'https://gamebanana.com/apiv5/Mod/{modID}?_csvProperties=_aFiles',
                    None,
                    'Retrieving download list'))['_aFiles']
                echo('Available downloads:')
                idx = 1
                for d in downloads:
                    echo(f'  [{idx}] {d["_sFile"]} {d["_sDescription"]}')
                    idx += 1

                selection = click.prompt('Select file to download', type=click.IntRange(0, idx), default=0, show_default=False)
                if selection:
                    d = downloads[selection-1]
                    echo(f'Selected file: {d["_sFile"]}')
                    url = str(d['_sDownloadUrl'])
                else:
                    echo('Aborted!')

        elif mod.isdigit():
            modID = int(mod)
            matches = {key: val for key, val in mod_list.items() if modID == val['GameBananaId']}
            url = prompt_mod_selection(matches)

    if url:
        file = download_with_progress(url, None, 'Downloading')
    
    if file:
        meta = read_mod_info(file)
        if meta:
            echo(f'Downloaded mod: {meta.Name} {meta.Version}')
            filename = meta.Name + '.zip'
        elif click.confirm('everest.yaml is missing or malformed. Install anyways?'):
            filename = filename or click.prompt('Save As')

        if filename:
            if not filename.endswith('.zip'):
                filename += '.zip'
            write_with_progress(
                file,
                os.path.join(os.path.dirname(name['path']), 'Mods', filename),
                label=f'Saving file to {filename}',
                atomic=True
            )


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
        installed = installed_mods(os.path.join(os.path.dirname(name['path']), 'Mods'), with_size=True)
        for meta in installed:
            if meta.Name in mod_list:
                server = mod_list[meta.Name]
                latest_hash = server['xxHash'][0]
                if meta.Hash and latest_hash != meta.Hash:
                    update = UpdateInfo(
                        meta,
                        Version.parse(server['Version']),
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
