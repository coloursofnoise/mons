import itertools
from typing import Iterable, Sequence, Tuple, Any, cast
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
from ..formatting import format_bytes

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
@click.option('-s', '--search', help='Filter mods with a regex pattern.', metavar='QUERY')
@click.option('-v', '--verbose', is_flag=True, help='Be verbose.')
@pass_userinfo
def list_mods(userinfo: UserInfo, enabled, valid, name, dll, dir, dependency, search, verbose):
    '''List installed mods.'''
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
        gen = filter(lambda meta: next(filter(lambda d: dependency == d.Name, meta.Dependencies), cast(Any, None)), gen)

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

def prompt_mod_selection(options: Dict, max: int=-1) -> Union[ModDownload,None]:
    matchKeys = sorted(options.keys(), key=lambda key: options[key]['LastUpdate'], reverse=True)
    selection = None
    if len(matchKeys) == 1:
        key = matchKeys[0]
        echo(f'Mod found: {key} {options[key]["Version"]}')
        options[key]['Name'] = key
        selection = ModDownload(options[key], options[key]["URL"])

    if len(matchKeys) > 1:
        echo('Mods found:')
        idx = 1
        for key in matchKeys:
            if max > -1 and idx > max:
                break
            echo(f'  [{idx}] {key} {options[key]["Version"]}')
            idx += 1

        choice = click.prompt('Select mod to add', type=click.IntRange(0, idx), default=0, show_default=False)
        if choice:
            key = matchKeys[choice-1]
            echo(f'Selected mod: {key} {options[key]["Version"]}')
            options[key]['Name'] = key
            selection = ModDownload(options[key], options[key]["URL"])
        else:
            echo('Aborted!')
    return selection

def resolve_dependencies(mods: Iterable[ModMeta]):
    dependency_graph = get_dependency_graph()
    echo('Resolving dependencies...')
    deps = combined_dependencies(mods, dependency_graph)
    sorted_deps = sorted(deps.values(), key=lambda dep: dep.Name)

    return sorted_deps

def get_mod_download(mod, mod_list):
    mod_info = mod_list[mod]
    mod_info['Name'] = mod
    return ModDownload(ModMeta(mod_info), mod_info['URL'], mod_info['MirrorURL'])

def resolve_mods(mods: Sequence[str]) -> Tuple[List[ModDownload], List[str]]:
    resolved = list()
    unresolved = list()
    mod_list = get_mod_list()
    for mod in mods:
        download = None
        url = None

        # Install from local filesystem
        if mod.endswith('.zip') and (os.path.exists(mod) or mod.startswith('file://')):
            if not mod.startswith('file://'):
                mod = 'file://' + os.path.abspath(mod)
            meta = read_mod_info(mod[len('file://'):])
            if meta:
                download = ModDownload(meta, mod, None)
                echo(f'Mod found: {meta}')

        # Mod ID match
        elif mod in mod_list:
            mod_info = mod_list[mod]
            mod_info['Name'] = mod
            download = ModDownload(ModMeta(mod_info), mod_info['URL'], mod_info['MirrorURL'])
            echo(f'Mod found: {mod} {mod_info["Version"]}')

        # GameBanana submission URL
        elif mod.startswith(('https://gamebanana.com/mods', 'http://gamebanana.com/mods')) and mod.split('/')[-1].isdigit():
            modID = int(mod.split('/')[-1])
            matches = {key: val for key, val in mod_list.items() if modID == val['GameBananaId']}
            if len(matches) > 0:
                download = prompt_mod_selection(matches)
            else:
                downloads = json.load(download_with_progress(
                    f'https://gamebanana.com/apiv5/Mod/{modID}?_csvProperties=_aFiles',
                    None,
                    'Retrieving download list')
                )['_aFiles']
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

        elif mod.startswith(('http://', 'https://')) and mod.endswith('.zip'):
            url = mod

        # Possible GameBanana Submission ID
        elif mod.isdigit():
            modID = int(mod)
            matches = {key: val for key, val in mod_list.items() if modID == val['GameBananaId']}
            if len(matches) > 0:
                download = prompt_mod_selection(matches)

        if download:
            resolved.append(download)
        elif url:
            unresolved.append(url)
        else:
            raise click.ClickException(f'Mod \'{mod}\' could not be resolved.')

    return resolved, unresolved


@cli.command(no_args_is_help=True, cls=DefaultArgsCommand)
@click.argument('name', type=Install(), required=False, callback=default_primary)
@click.argument('mods', nargs=-1)
@click.option('--search', is_flag=True, help='Use the Celeste mod search API to find a mod.')
@click.option('--random', is_flag=True, hidden=True)
@click.option('--deps/--no-deps', is_flag=True, default=True)
@click.option('--optional-deps/--no-optional-deps', is_flag=True, default=False)
@pass_userinfo
def add(userinfo: UserInfo, name, mods: Tuple[str, ...], search, random, deps, optional_deps):
    '''Add a mod.

    MOD can be a mod ID, local path, zip file, GameBanana page, or GameBanana submission ID.'''
    install = userinfo.installs[name]
    mod_folder = os.path.join(os.path.dirname(install['path']), 'Mods')
    mod_list = get_mod_list()

    installed_list = installed_mods(mod_folder, valid=True, with_size=True)
    installed_list = {meta.Name: meta for meta in installed_list}
    
    resolved: List[ModDownload] = list()
    unresolved: List[str] = list()

    if random:
        unresolved = [urllib.request.urlopen('https://max480-random-stuff.appspot.com/celeste/random-map').url]

    elif not mods:
        raise click.UsageError('Missing argument \'MODS\'')

    # Query mod search API
    elif search:
        mod_list = get_mod_list()
        search_result = search_mods(' '.join(mods))
        matches = {}
        for item in search_result:
            matches.update({mod: data for mod, data in mod_list.items() if data['GameBananaId'] == item['itemid']})

        if len(matches) < 1:
            echo('No results found.')
            return
        
        match = prompt_mod_selection(matches, max=9)
        if match:
            resolved = [match]
    
    else:
        resolved, unresolved = resolve_mods(mods)

    if len(unresolved) > 0:
        echo('The following mods could not be resolved:')
        for s in unresolved:
            echo(f'\t{s}')
        download_size = sum(get_download_size(url) for url in unresolved)
        echo(f'Downloading them all will use up to {format_bytes(download_size)} disk space.')
        if click.confirm('Download and attempt to resolve them before continuing?', True):
            for url in unresolved:
                file = download_with_progress(url, None, f"Downloading {url}", clear=True)
                meta = read_mod_info(file)
                if meta:
                    if meta.Name in installed_list:
                        if os.path.isdir(installed_list[meta.Name].Path):
                            raise IsADirectoryError("Could not overwrite non-zipped mod.")
                        write_with_progress(file, installed_list[meta.Name].Path, atomic=True, clear=True)
                    else:
                        resolved.append(ModDownload(meta, url))
                elif click.confirm('This file does not seem to be an Everest mod. Install anyways?'):
                    filename = click.prompt('Save as file')
                    if filename:
                        filename = filename if filename.endswith('.zip') else filename + '.zip'
                        write_with_progress(file, os.path.join(mod_folder, filename), atomic=True, clear=True)
                else:
                    echo(f'Skipped install for {url}.')

            unresolved = []

    if len(resolved) > 0:
        resolved = [mod for mod in resolved if not mod.Meta.Name in installed_list]

        dependencies = resolve_dependencies(map(lambda d: d.Meta, resolved))
        deps_install: List = []; deps_update: List[UpdateInfo] = []; deps_blacklisted: List[ModMeta] = []
        for dep in dependencies:
            if dep.Name in installed_list:
                installed_mod = installed_list[dep.Name]
                if installed_mod.Version.satisfies(dep.Version):
                    if installed_mod.Blacklisted:
                        deps_blacklisted.append(installed_mod)
                else:
                    deps_update.append(UpdateInfo(installed_mod, dep.Version, mod_list[dep.Name]['URL']))
            else:
                deps_install.append(dep)

        deps_install, unregistered = partition(lambda mod: mod.Name in mod_list, deps_install)
        deps_install = [get_mod_download(mod.Name, mod_list) for mod in deps_install if mod.Name in mod_list]
        count = len(deps_install) + len(resolved)
        if count > 0:
            echo(f"\t{count} To Install:")
            for download in itertools.chain(deps_install, resolved):
                echo(f"{download.Meta.Name}: {download.Meta.Version}")
        count = len(deps_update)
        if count > 0:
            echo(f"\t{count}To Update:")
            for mod in deps_update:
                echo(f"{mod.Old.Name}: {mod.New}")
        count = len(deps_blacklisted)
        if count > 0:
            echo(f"\t{count}To Enable:")
            for mod in deps_blacklisted:
                echo(f"{mod.Name}: {mod.Version}")

        download_size = sum(
            get_download_size(mod.Url, mod.Old.Size) if isinstance(mod, UpdateInfo) else mod.Meta.Size
            for mod in itertools.chain(resolved, deps_install, deps_update)
        )

        if download_size >= 0:
            echo(f'After this operation, an additional {format_bytes(download_size)} disk space will be used')
        else:
            echo(f'After this operation, {format_bytes(abs(download_size))} disk space will be freed')

        click.confirm('Continue?', default=True, abort=True)

        for mod in deps_install:
            download_with_progress(mod.Url, os.path.join(mod_folder, mod.Meta.Name + '.zip'), f'{mod.Meta.Name}: {mod.Url}', True, True)
        for mod in deps_update:
            if os.path.isdir(mod.Old.Path):
                echo("Could not update unzipped mod: " + os.path.basename(mod.Old.Path))
            else:
                download_with_progress(mod.Url, mod.Old.Path, f'{mod.Old.Name}: {mod.Url}', True, True)
        for mod in itertools.chain(deps_update, deps_blacklisted):
            filename = os.path.basename(mod.Old.Path if isinstance(mod, UpdateInfo) else mod.Path)
            enable_mod(mod_folder, filename)
        for mod in resolved:
            download_with_progress(mod.Url, os.path.join(mod_folder, mod.Meta.Name + '.zip'), f'{mod.Meta.Name}: {mod.Url}', True, True)

        everest_min = next((dep.Version for dep in unregistered if dep.Name == 'Everest'), Version(1, 0, 0))
        current_everest = Version(1, install.getint('EverestBuild', fallback=0), 0)
        if not current_everest.satisfies(everest_min):
            echo(f'Installed Everest ({current_everest}) does not satisfy minimum requirement ({everest_min}).')
            if click.confirm('Update Everest?', True):
                mons_cli.main(args=['install', install.name, str(everest_min)])


@cli.command(hidden=True)
@click.argument('name', type=Install(resolve_install=True), required=False, callback=default_primary)
@click.argument('mod')
def remove(name, mod):
    pass


@cli.command()
@click.argument('name', type=Install(resolve_install=True), required=False, callback=default_primary)
#@click.argument('mod', required=False)
@click.option('--all', is_flag=True, help='Update all installed mods.')
@click.option('--enabled', is_flag=True, help='Update all currently enabled mods.', default=None)
@click.option('--upgrade-only', is_flag=True, help='Only update if latest file is a higher version')
@pass_userinfo
def update(userinfo, name, all, enabled, upgrade_only):
    '''Update installed mods.'''
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
                    updates.append(update)
                    total_size += server['Size'] - update.Old.Size


    if not has_updates:
        echo('All mods up to date')
        return

    echo(ngettext(
        f'{len(updates)} update found',
        f'{len(updates)} updates found',
        len(updates)))

    if total_size >= 0:
        echo(f'After this operation, an additional {total_size} B disk space will be used')
    else:
        echo(f'After this operation, {abs(total_size)} B disk space will be freed')


    if not click.confirm('Continue?', default=True):
        return

    for update in updates:
        try:
            download_with_progress(update.Url, update.Old.Path, f'Downloading mod: {update.Old.Name}', atomic=True)
        except:
            if update.Url != update.Mirror:
                download_with_progress(update.Mirror, update.Old.Path, f'Downloading mod: {update.Old.Name}', atomic=True)
