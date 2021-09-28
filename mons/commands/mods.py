import click
from click import echo_via_pager, echo

import os

from gettext import ngettext
import re
from concurrent import futures

from ..clickExt import *
from ..mons import UserInfo, pass_userinfo
from ..mons import cli as mons_cli
from ..utils import *
from ..version import Version

@click.group(name='mods', help='Manage Everest mods')
@click.pass_context
def cli(ctx):
    pass


def format_mod_info(meta: ModMeta):
    out = meta.Name
    if meta.Blacklisted:
        out += '\t(disabled)'
    out += '\n\t{}'.format(meta.Version)
    out += '\n\t{}'.format(os.path.basename(meta.Path))
    if os.path.isdir(meta.Path):
        out += '/'
    out += '\n'
    return out

@cli.command(name='list', help='List installed mods.')
@click.argument('name', type=Install(), required=False, callback=default_primary)
@click.option('--enabled/--disabled', help='Filter by enabled/disabled mods.', default=None)
@click.option('--valid/--invalid', help='Filter mods with valid everest.yaml.', default=None)
@click.option('--dll/--no-dll', help='List mods that register DLLs.', default=None)
@click.option('--dir/--zip', 'dir', flag_value=True, help='List mods in folders/zips.', default=None)
@click.option('--no-zip/--no-dir', 'dir', flag_value=False, hidden=True, default=None)
@click.option('-d', '--dependency', help='Filter mods by dependency.', metavar='MODID')
@click.option('-s', '--search', help='Search for mods with a regex pattern.', metavar='QUERY')
@click.option('-v', '--verbose', is_flag=True, help='Be verbose.')
@pass_userinfo
def list_mods(userinfo: UserInfo, enabled, valid, name, dll, dir, dependency, search, verbose):
    if valid == False:
        if dll == True:
            raise click.UsageError('--invalid and --dll options are incompatible.')
        if dependency:
            raise click.UsageError('--invalid and --dependency options are incompatible.')

    basePath = os.path.join(os.path.dirname(userinfo.installs[name]['path']), 'Mods')

    installed = installed_mods(
        basePath,
        dirs=dir,
        valid=valid,
        blacklisted=enabled
    )

    gen = installed
    if dll is not None:
        gen = filter(lambda meta: not dll ^ bool(meta.DLL), gen)

    if dependency:
        gen = filter(lambda meta: next(filter(lambda d: dependency == d.Name, meta.Dependencies), None), gen)

    if search:
        pattern = re.compile(search, flags=re.I)
        gen = filter(
            lambda meta: bool(pattern.search(meta.Name) or pattern.search(os.path.basename(meta.Path))),
            gen)

    if verbose:
        gen = (format_mod_info(meta) for meta in gen)
    else:
        gen = (f'{meta.Name}\t{meta.Version}' + ('\t(disabled)' if meta.Blacklisted else '') + '\n'
            for meta in gen)

    if os.name == 'nt':
        for mod in gen:
            echo(mod, nl=False)
    else:
        # Currently broken on Windows
        echo_via_pager(gen)

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
            raise click.UsageError('Entry not found: ' + str(item['itemid']))

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
    installed_temp = installed_list or installed_mods(mods_folder, valid=True, with_size=True)
    installed = {mod.Name: mod for mod in installed_temp}
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
            resolve_dependencies(userinfo.cache[name], os.path.join(os.path.dirname(install['path']), 'Mods'), meta, mod_list)


@cli.command(hidden=True)
@click.argument('name', type=Install(resolve_install=True), required=False, callback=default_primary)
@click.argument('mod')
def remove(name, mod):
    pass


def get_size_diff(mod, url, old):
    request = urllib.request.Request(url, method='HEAD')
    return int(urllib.request.urlopen(request).headers['Content-Length']) - old

@cli.command()
@click.argument('name', type=Install(resolve_install=True), required=False, callback=default_primary)
#@click.argument('mod', required=False)
@click.option('--all', is_flag=True, help='Update all installed mods.')
@click.option('--enabled', is_flag=True, help='Update all currently enabled mods.', default=None)
@click.option('--upgrade-only', is_flag=True, help='Only update if latest file is a higher version')
@pass_userinfo
def update(userinfo, name, all, enabled, upgrade_only):
    if not (all or enabled):
        raise click.UsageError('this command can currently only be used with the --all or --enabled option')

    mod_list = get_mod_list()
    updates: List[UpdateInfo] = []
    has_updates = False
    total_size = 0
    if all:
        enabled = None
    if all or enabled:
        mods_folder = os.path.join(os.path.dirname(name['path']), 'Mods')
        installed = installed_mods(mods_folder, blacklisted=enabled, dirs=False, valid=True, with_size=True, with_hash=True)
        updater_blacklist = os.path.join(mods_folder, 'updaterblacklist.txt')
        updater_blacklist = os.path.exists(updater_blacklist) and read_blacklist(updater_blacklist)
        with futures.ThreadPoolExecutor() as executor:
            requests: List[futures.Future] = []
            for meta in installed:
                if meta.Name in mod_list and (not updater_blacklist or os.path.basename(meta.Path) not in updater_blacklist):
                    server = mod_list[meta.Name]
                    latest_hash = server['xxHash'][0]
                    latest_version = Version.parse(server['Version'])
                    if meta.Hash and latest_hash != meta.Hash and (not upgrade_only or latest_version > meta.Version):
                        update = UpdateInfo(
                            meta,
                            latest_version,
                            server['URL'],
                        )
                        if not has_updates:
                            echo('Updates available:')
                            has_updates = True
                        echo(f'  {update.Old.Name}: {update.Old.Version} -> {update.New}')
                        requests.append(executor.submit(get_size_diff, update.Old.Name, update.Url, update.Old.Size))
                        updates.append(update)

            for req in requests:
                total_size += req.result()

    if not has_updates:
        echo('All mods up to date')
        return

    echo(ngettext(
        f'{len(updates)} update found',
        f'{len(updates)} updates found',
        int(has_updates) + 1))

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
    )