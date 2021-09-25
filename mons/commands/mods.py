import click
from click import echo_via_pager, echo

import os

from gettext import ngettext

from ..clickExt import *
from ..mons import UserInfo, pass_userinfo
from ..mons import cli as mons_cli
from ..utils import *
from ..version import Version

@click.group(name='mods', help='Manage Everest mods')
@click.pass_context
def cli(ctx):
    pass

@cli.command(name='list', hidden=True)
@click.argument('name', type=Install(), required=False, callback=default_primary)
@pass_userinfo
def list_mods(userinfo: UserInfo, name):
    basePath = os.path.join(os.path.dirname(userinfo.installs[name]['path']), 'Mods')
    files = os.listdir(basePath)
    if os.name == 'nt':
        for meta in installed_mods(basePath, include_folder=True, valid_only=False, include_blacklisted=True):
            echo(f'{meta.Name}\t{meta.Version}', nl=False)
            echo('(disabled)' if meta.Blacklisted else '')
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

def resolve_dependencies(
    install,
    mods_folder: str,
    mod_meta: Union[ModMeta, List[ModMeta]],
    update_dict=None,
    installed_list: List[ModMeta]=None,
):
    everest_dep = None
    everest_min = Version(1, 0, 0)
    echo('Resolving dependencies...')
    update_dict = update_dict or get_mod_list()
    installed_list = installed_list or installed_mods(mods_folder, include_folder=True, include_blacklisted=True, with_size=True)
    installed = {mod.Name: mod for mod in installed_list}
    if isinstance(mod_meta, List):
        sorted_deps = combined_dependencies(mod_meta)
        sorted_deps.sort(key=lambda dep: dep.Name)
    else:
        sorted_deps = sorted(mod_meta.Dependencies, key=lambda dep: dep.Name)
    ignored_deps = []
    for dep in sorted_deps:
        if dep.Name == 'Everest':
            everest_dep = dep
            ignored_deps.append(dep)
        elif dep.Name not in installed and dep.Name not in update_dict:
            if click.confirm(f'Dependency {dep.Name} could not be resolved. Continue?', abort=True):
                ignored_deps.append(dep)

    if not everest_dep:
        raise Exception('Encountered everest.yaml with no Everest dependency.')
    else:
        everest_min = everest_dep.Version

    sorted_deps = list(set(sorted_deps) - set(ignored_deps))

    for dep in sorted_deps:
        if dep.Name in installed:
            existing = installed[dep.Name]
            if not existing.Version.satisfies(dep.Version):
                echo(f'Dependency {dep.Name} {dep.Version} not satisfied by installed: {existing.Name} {existing.Version}')
                if dep.Name in update_dict and Version.parse(update_dict[dep.Name]['Version']).satisfies(dep.Version):
                    text = 'Update mod?' if not existing.Blacklisted else 'Enable mod and update?'
                    if click.confirm(text, default=True):
                        enable_mod(mods_folder, os.path.basename(existing.Path))
                        download_with_progress(update_dict[dep.Name]['URL'], existing.Path, f'Updating mod: {existing.Name}', atomic=True)
                else:
                    echo('No updates found.')
            elif not existing.Blacklisted:
                echo(f'Dependency {dep.Name} {dep.Version} already met: {existing.Name} {existing.Version}')
            else:
                echo(f'Dependency {dep.Name} {dep.Version} met but blacklisted: {existing.Name} {existing.Version}')
                if click.confirm('Enable mod?', default=True):
                    enable_mod(mods_folder, os.path.basename(existing.Path))
                    dep.Blacklisted = False
            continue

        echo(f'Dependency: {dep.Name} {dep.Version}')
        file = download_with_progress(str(update_dict[dep.Name]['URL']), None, 'Downloading', clear=True)
        meta = read_mod_info(file)
        if meta:
            echo(f'  Installed: {meta.Name} {meta.Version}')
            for dep in meta.Dependencies:
                if dep.Name == 'Everest':
                    if not everest_min.satisfies(dep.Version):
                        everest_min = dep.Version
                    break
            filename = meta.Name + '.zip'
            write_with_progress(
                file,
                os.path.join(mods_folder, filename),
                label=f'Saving file to {filename}',
                atomic=True,
                clear=True,
            )

    current_everest = Version(1, install.getint('EverestBuild', fallback=0), 0)
    if not current_everest.satisfies(everest_min):
        echo(f'Installed Everest ({current_everest}) does not satisfy minimum requirement ({everest_min}.')
        if click.confirm('Update Everest?'):
            mons_cli.main(args=['install', install.name, str(everest_min)])

@cli.command()
@click.argument('name', type=Install(), required=False, callback=default_primary)
@click.argument('mod')
@click.option('--search', is_flag=True)
@pass_userinfo
def add(userinfo: UserInfo, name, mod: str, search):
    install = userinfo.installs[name]
    url = None
    filename = None
    file = None
    mod_list = None
    installed = None

    # Query mod search API
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

    # Install from local filesystem
    elif os.path.exists(mod):
        file = mod

    # Install direct from URL
    elif mod.endswith('.zip') and mod.startswith(('http://', 'https://', 'file://')):
        echo('Attempting direct file download:')
        # Change User-Agent for discord, etc... downloads
        opener=urllib.request.build_opener()
        opener.addheaders=[('User-Agent','Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/36.0.1941.0 Safari/537.36')]
        urllib.request.install_opener(opener)
        url = mod

    else:
        mod_list = get_mod_list()
        
        # Mod ID match
        if mod in mod_list:
            echo(f'Mod found: {mod} {mod_list[mod]["Version"]}')
            url = str(mod_list[mod]['URL'])

        # GameBanana submission URL
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

        # Possible GameBanana Submission ID
        elif mod.isdigit():
            modID = int(mod)
            matches = {key: val for key, val in mod_list.items() if modID == val['GameBananaId']}
            url = prompt_mod_selection(matches)

    if url:
        file = download_with_progress(url, None, 'Downloading', clear=True)
    
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
                os.path.join(os.path.dirname(install['path']), 'Mods', filename),
                label=f'Saving file to {filename}',
                atomic=True
            )
        if meta:
            resolve_dependencies(userinfo.cache[name], os.path.join(os.path.dirname(install['path']), 'Mods'), meta, mod_list, installed)


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
@pass_userinfo
def update(userinfo, name, all):
    if not all:
        raise click.UsageError('this command can currently only be used with the --all option')

    mod_list = get_mod_list()
    updates: List[UpdateInfo] = []
    if all:
        mods_folder = os.path.join(os.path.dirname(name['path']), 'Mods')
        installed = installed_mods(mods_folder, with_size=True)
        updater_blacklist = os.path.join(mods_folder, 'updaterblacklist.txt')
        updater_blacklist = os.path.exists(updater_blacklist) and read_blacklist(updater_blacklist)
        for meta in installed:
            if meta.Name in mod_list and (not updater_blacklist or os.path.basename(meta.Path) not in updater_blacklist):
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
    
    echo(ngettext(
        f'{len(updates)} update available:',
        f'{len(updates)} updates available:',
        len(updates)))
    for update in updates:
        echo(f'  {update.Old.Name}: {update.Old.Version} -> {update.New}')
    
    if total_size >= 0:
        echo(f'After this operation, an additional {total_size} B disk space will be used')
    else:
        echo(f'After this operation, {abs(total_size)} B disk space will be freed')
    
    if not click.confirm('Continue?', default=True):
        return

    new_metas = []
    for update in updates:
        download_with_progress(update.Url, update.Old.Path, f'Downloading mod: {update.Old.Name}', atomic=True)
        new_metas.append(read_mod_info(update.Old.Path))
    resolve_dependencies(
        userinfo.cache[name.name],
        os.path.join(os.path.dirname(name['path']), 'Mods'),
        new_metas,
        mod_list,
        None,
    )