import itertools
import time
from urllib.parse import ParseResult
import click
from click import echo_via_pager, echo

import os
import shutil

from gettext import ngettext
import re

from ..clickExt import *
from ..mons import UserInfo, pass_userinfo
from ..mons import cli as mons_cli
from ..utils import *
from ..downloading import download_threaded
from ..version import Version
from ..formatting import format_bytes

import typing as t

@click.group(name='mods', help='Manage Everest mods')
@click.pass_context
def cli(ctx):
    pass


def format_mod_info(meta: ModMeta):
    out = meta.Name
    if meta.Blacklisted:
        out += '\t(disabled)'
    out += '\n\tVersion: {}'.format(meta.Version)
    out += '\n\tFile: {}'.format(os.path.basename(meta.Path))
    if os.path.isdir(meta.Path):
        out += '/'
    out += '\n'
    return out

@cli.command(name='list', help='List installed mods.', no_args_is_help=True)
@click.argument('name', type=Install())
@click.option('--enabled/--disabled', help='Filter by enabled/disabled mods.', default=None)
@click.option('--valid/--invalid', help='Filter mods with valid everest.yaml.', default=None)
@click.option('--dll/--no-dll', help='Filter mods that register DLLs.', default=None)
@click.option('--dir/--zip', 'dir', flag_value=True, help='Filter mods in folders/zips.', default=None)
@click.option('--no-zip/--no-dir', 'dir', flag_value=False, hidden=True, default=None)
@click.option('-d', '--dependency', help='Filter mods by dependency.', metavar='MODID')
@click.option('-s', '--search', help='Filter mods with a regex pattern.', metavar='QUERY')
@click.option('-v', '--verbose', is_flag=True, help='Enable verbose logging.')
@pass_userinfo
def list_mods(userinfo: UserInfo, enabled, valid, name, dll, dir, dependency, search, verbose):
    '''List installed mods.'''
    if valid == False:
        if dll == True:
            raise click.BadOptionUsage('--dll', '--dll cannot be used with the --invalid flag.')
        if dependency:
            raise click.BadOptionUsage('--dependency', '--dependency cannot be used with the --invalid flag.')

    basePath = os.path.join(os.path.dirname(userinfo.installs[name]['path']), 'Mods')

    installed = installed_mods(
        basePath,
        dirs=dir,
        valid=valid,
        blacklisted=flip(enabled)
    )

    gen = installed
    if dll is not None:
        gen = filter(lambda meta: not dll ^ bool(meta.DLL), gen)

    if dependency:
        gen = filter(lambda meta: next(filter(lambda d: dependency == d.Name, meta.Dependencies), t.cast(t.Any, None)), gen)

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

def prompt_mod_selection(options: t.Dict, max: int=-1) -> t.Union[ModDownload,None]:
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

    return selection

def resolve_dependencies(mods: t.Iterable[ModMeta], database = None):
    database = database or get_dependency_graph()
    deps = combined_dependencies(mods, database)
    sorted_deps = sorted(deps.values(), key=lambda dep: dep.Name)

    return sorted_deps

def get_mod_download(mod, mod_list):
    mod_info = mod_list[mod]
    mod_info['Name'] = mod
    return ModDownload(ModMeta(mod_info), mod_info['URL'], mod_info['MirrorURL'])

def resolve_mods(mods: t.Sequence[str]) -> t.Tuple[t.List[ModDownload], t.List[str]]:
    resolved = list()
    unresolved = list()
    mod_list = get_mod_list()

    for mod in mods:
        parsed_url = urllib.parse.urlparse(mod)
        download = None
        url = None

        # Special case to try to resolve 1-Click install links through mod database
        if parsed_url.scheme == 'everest':
            match = re.match('^(https://gamebanana.com/mmdl/.*),.*,.*$', parsed_url.path)
            if match:
                gb_url = match[1]
                matches = {key: val for key, val in mod_list.items() if gb_url == val['URL']}
                if len(matches) > 0:
                    download = prompt_mod_selection(matches)
                else:
                    parsed_url = urllib.parse.urlparse(gb_url)

        # Install from local filesystem
        if (mod.endswith('.zip') and os.path.exists(mod)):
            parsed_url = ParseResult('file', '', os.path.abspath(mod), '', '', '')
            meta = read_mod_info(parsed_url.path)
            if meta:
                download = ModDownload(meta, urllib.parse.urlunparse(parsed_url))
                echo(f'Mod found: {meta}')

        # Mod ID match
        elif mod in mod_list:
            mod_info = mod_list[mod]
            mod_info['Name'] = mod
            download = ModDownload(ModMeta(mod_info), mod_info['URL'], mod_info['MirrorURL'])
            echo(f'Mod found: {mod} {mod_info["Version"]}')

        # GameBanana submission URL
        elif parsed_url.scheme in ('http', 'https') and parsed_url.netloc == 'gamebanana.com' and parsed_url.path.startswith('/mods') and parsed_url.path.split('/')[-1].isdigit():
            modID = int(parsed_url.path.split('/')[-1])
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

        # Google Drive share URL
        elif parsed_url.scheme in ('http', 'https') and parsed_url.netloc == 'drive.google.com' and parsed_url.path.startswith('/file/d/'):
            file_id = parsed_url.path[len('/file/d/'):].split('/')[0]
            url = 'https://drive.google.com/uc?export=download&id=' + file_id

        elif parsed_url.scheme and parsed_url.path:
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


@cli.command(no_args_is_help=True)
@click.argument('name', type=Install())
@click.argument('mods', nargs=-1)
@click.option('--search', is_flag=True, help='Use the Celeste mod search API to find a mod.')
@click.option('--random', is_flag=True, help='Install a random mod.')
@click.option('--no-deps', is_flag=True, default=False, help='Skip installing dependencies.')
@click.option('--optional-deps', is_flag=True, default=False, hidden=True)
@click.option('--yes', '-y', is_flag=True, default=None, help='Skip confirmation prompts.')
@pass_userinfo
def add(userinfo: UserInfo, name, mods: t.Tuple[str, ...], search, random, no_deps, optional_deps, yes):
    '''Add one or more mods.

    MODS can be one or more of: mod ID, local zip, zip URL, 1-Click install link, Google Drive share link, GameBanana page, or GameBanana submission ID.'''
    install = userinfo.installs[name]
    install_cache = userinfo.cache[name]
    mod_folder = os.path.join(os.path.dirname(install['path']), 'Mods')
    mod_list = get_mod_list()

    installed_list = installed_mods(mod_folder, valid=True, with_size=True)
    installed_list = {
        meta.Name: meta 
        for meta in tqdm(installed_list, desc='Reading Installed Mods', leave=False, unit='')
    }

    resolved: t.List[ModDownload] = list()
    unresolved: t.List[str] = list()

    if random:
        mods = (urllib.request.urlopen('https://max480-random-stuff.appspot.com/celeste/random-map').url,)

    def process_zip(zip, name):
        meta = read_mod_info(zip)
        if meta:
            if meta.Name in installed_list:
                if os.path.isdir(installed_list[meta.Name].Path):
                    raise IsADirectoryError("Could not overwrite non-zipped mod.")
                shutil.move(zip, installed_list[meta.Name].Path)
            else:
                resolved.append(ModDownload(meta, f'file:{urllib.request.pathname2url(zip)}'))
        elif click.confirm(f'\'{name}\' does not seem to be an Everest mod.\nInstall anyways?'):
            filename = click.prompt('Save as file')
            if filename:
                filename = filename if filename.endswith('.zip') else filename + '.zip'
                shutil.move(zip, os.path.join(mod_folder, filename))
        else:
            echo(f'Skipped install for {name}.')

    if not mods:
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
            exit()
        
        match = prompt_mod_selection(matches, max=9)
        if not match:
            raise click.Abort()
        resolved = [match]

    # Read from stdin
    elif mods == ('-',):
        with click.open_file('-', mode='rb') as stdin:
            with temporary_file(persist=True) as temp:
                if stdin.isatty():
                    raise TTYError('no input.')
                with click.open_file(temp, mode='wb') as file:
                    read_with_progress(stdin, file, label='Reading from stdin', clear_progress=True)
                process_zip(temp, 'stdin')

    else:
        resolved, unresolved = resolve_mods(mods)

    if len(unresolved) > 0:
        echo('The following mods could not be resolved:')
        for s in unresolved:
            echo(f'\t{s}')
        download_size = sum(get_download_size(url) for url in unresolved)
        echo(f'Downloading them all will use up to {format_bytes(download_size)} disk space.')
        if confirm_ext('Download and attempt to resolve them before continuing?', True, skip=yes):
            for url in unresolved:
                with temporary_file(persist=True) as file:
                    download_with_progress(url, file, f"Downloading {url}", clear=True)
                    process_zip(file, url)

            unresolved = []

    if len(resolved) > 0:
        installed, resolved = partition(lambda mod: mod.Meta.Name in installed_list, resolved)
        if len(installed) > 0:
            echo('Already installed:')
            for mod in installed:
                echo(installed_list[mod.Meta.Name])

    if len(resolved) > 0:
        if not no_deps:
            echo('Resolving dependencies...')
            dependencies = resolve_dependencies(map(lambda d: d.Meta, resolved))
            special, dependencies = partition(lambda mod: mod.Name in ('Celeste', 'Everest'), dependencies)
            deps_install: t.List = []; deps_update: t.List[UpdateInfo] = []; deps_blacklisted: t.List[ModMeta] = []
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
            if len(unregistered) > 0:
                echo(f'{len(unregistered)} dependencies could not be found:')
                for mod in unregistered:
                    echo(mod)
                click.confirm('Skip missing dependencies?', default=True, abort=True)

            deps_install = [get_mod_download(mod.Name, mod_list) for mod in deps_install]
        else:
            deps_install = deps_update = deps_blacklisted = []
        count = len(deps_install) + len(resolved)
        if count > 0:
            echo(f"\t{count} To Install:")
            for download in itertools.chain(deps_install, resolved):
                echo(download.Meta)
        count = len(deps_update)
        if count > 0:
            echo(f"\t{count} To Update:")
            for mod in deps_update:
                echo(f"{mod.Old} -> {mod.New}")
        count = len(deps_blacklisted)
        if count > 0:
            echo(f"\t{count} To Enable:")
            for mod in deps_blacklisted:
                echo(mod)

        # Hack to allow assigning to a variable out of scope
        download_size_ref = [0]
        def download_size_key(mod: t.Union[UpdateInfo, ModDownload]):
            size = get_download_size(mod.Url, mod.Old.Size) if isinstance(mod, UpdateInfo) else mod.Meta.Size
            download_size_ref[0] += size
            return size

        sorted_dep_downloads = sorted(
            itertools.chain(deps_install, deps_update),
            key = download_size_key
        )
        sorted_main_downloads = sorted(resolved, key = download_size_key)

        download_size = download_size_ref[0]
        if download_size >= 0:
            echo(f'After this operation, an additional {format_bytes(download_size)} disk space will be used')
        else:
            echo(f'After this operation, {format_bytes(abs(download_size))} disk space will be freed')

        confirm_ext('Continue?', default=True, abort=True, skip=yes)

        start = time.perf_counter()
        for mod in itertools.chain((mod.Old for mod in deps_update), deps_blacklisted):
            enable_mod(mod_folder, os.path.basename(mod.Path))

        download_threaded(mod_folder, sorted_dep_downloads, late_downloads=sorted_main_downloads, thread_count=10)
        end = time.perf_counter()
        tqdm.write(str.format('Downloaded files in {:.3f} seconds.', end-start))

        if no_deps:
            exit()

        everest_min = next((dep.Version for dep in special if dep.Name == 'Everest'), Version(1, 0, 0))
        current_everest = Version(1, install_cache.getint('everestbuild', fallback=0), 0)
        if not current_everest.satisfies(everest_min):
            echo(f'Installed Everest ({current_everest}) does not satisfy minimum requirement ({everest_min}).')
            if confirm_ext('Update Everest?', True, skip=yes):
                mons_cli.main(args=['install', install.name, str(everest_min)])

@cli.command(no_args_is_help=True)
@click.argument('name', type=Install(resolve_install=True))
@click.argument('mods', nargs=-1)
@click.option('--trim-deps', is_flag=True, help='Also remove any exclusive dependencies.')
@click.option('--force', '-f', is_flag=True, default=False, help='Ignore errors and confirmation prompts.')
def remove(name, mods, trim_dependencies, force):
    '''Remove installed mods.'''
    mod_folder = os.path.join(os.path.dirname(name['Path']), 'Mods')
    installed_list = installed_mods(mod_folder, valid=True, with_size=True)
    installed_list = t.cast(t.Dict[str, ModMeta], {
        meta.Name: meta
        for meta in tqdm(installed_list, desc='Reading Installed Mods', leave=False, unit='')
    })

    resolved, unresolved = partition(lambda mod: mod in installed_list, mods)

    if len(unresolved) > 0:
        echo('The following mods could not be found:')
        for mod in unresolved:
            echo(f'\t{mod}')
        confirm_ext('Continue anyways?', skip=force, abort=True)

    metas = [installed_list[mod] for mod in resolved]

    echo(str(len(metas)) + ' mods will be removed:')
    for mod in metas:
        echo(f'\t{mod}')

    removable = []
    if trim_dependencies:
        all_dependencies = resolve_dependencies([meta for meta in installed_list.values() if not meta.Name in mods], installed_list)

        dependencies = resolve_dependencies(metas, {mod: meta for mod, meta in installed_list.items() if mod in mods})

        removable = set(dep.Name for dep in dependencies).difference(set(dep.Name for dep in all_dependencies))
        removable = [installed_list[dep] for dep in removable if dep in installed_list]

        echo(str(len(removable)) + ' dependencies will also be removed:')
        for dep in removable:
            echo(f'\t{dep}')

    total_size = sum((mod.Size for mod in itertools.chain(metas, removable)))
    echo(f'After this operation, {format_bytes(total_size)} disk space will be freed.')

    if not force:
        click.confirm('Remove mods?', abort=True)

    folders = []
    with click.progressbar(label='Deleting files', length=len(removable) + len(metas)) as progress:
        for mod in itertools.chain(removable, metas):
            # This should be handled by catching IsADirectoryError but for some reason it raises PermissionError instead so...
            if os.path.isdir(mod.Path):
                folders.append(mod)
            else:
                os.remove(mod.Path)
            progress.update(1)

    if len(folders) > 0:
        echo('The following unzipped mods were not removed:')
        for mod in folders:
            echo(f'\t{mod} ({os.path.basename(mod.Path)}/)')


@cli.command(no_args_is_help=True)
@click.argument('name', type=Install(resolve_install=True))
#@click.argument('mod', required=False)
@click.option('--all', is_flag=True, help='Update all installed mods.')
@click.option('--enabled', is_flag=True, help='Update currently enabled mods.', default=None)
@click.option('--upgrade-only', is_flag=True, help='Only update if new file has a higher version.')
@pass_userinfo
def update(userinfo, name, all, enabled, upgrade_only):
    '''Update installed mods.'''
    if not all:
        raise click.UsageError('this command can currently only be used with the --all option')

    mod_list = get_mod_list()
    updates: t.List[UpdateInfo] = []
    has_updates = False
    total_size = 0 
    if all:
        mods_folder = os.path.join(os.path.dirname(name['path']), 'Mods')
        installed = installed_mods(mods_folder, blacklisted=flip(enabled), dirs=False, valid=True, with_size=True, with_hash=True)
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
                    echo(f'\t{update.Old} -> {update.New}')
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
        echo(f'After this operation, an additional {format_bytes(total_size)} disk space will be used')
    else:
        echo(f'After this operation, {format_bytes(abs(total_size))} disk space will be freed')


    if not click.confirm('Continue?', default=True):
        return


    start = time.perf_counter()
    download_threaded('', updates, thread_count=10)
    end = time.perf_counter()
    tqdm.write(str.format('Downloaded files in {:.3f} seconds.', end-start))

@cli.command(no_args_is_help=True)
@click.argument('name', type=Install())
#@click.argument('mod', required=False)
@click.option('--all', is_flag=True, help='Resolve all installed mods.')
@click.option('--enabled', is_flag=True, help='Resolve currently enabled mods.', default=None)
@click.option('--no-update', is_flag=True, help='Don\'t update outdated dependencies.')
@pass_userinfo
def resolve(userinfo: UserInfo, name, all, enabled, no_update):
    '''Resolve any missing or outdated dependencies.'''
    if not all:
        raise click.UsageError('this command can currently only be used with the --all option')

    install = userinfo.installs[name]
    install_cache = userinfo.cache[name]

    mods_folder = os.path.join(os.path.dirname(install['path']), 'Mods')
    installed = installed_mods(mods_folder, valid=True, blacklisted=flip(enabled))
    installed = list(tqdm(installed, desc='Reading Installed Mods', leave=False, unit=''))
    installed_dict = {meta.Name: meta for meta in installed}

    deps = resolve_dependencies(installed)

    special, deps_installed, deps_missing = multi_partition(
        lambda meta: meta.Name in ('Celeste', 'Everest'),
        lambda meta: meta.Name in installed_dict,
        iterable = deps
    )

    deps_outdated = [
        dep for dep in deps_installed 
        if not installed_dict[dep.Name].Version.satisfies(dep.Version)
    ] if not no_update else []

    if len(deps_missing) + len(deps_outdated) < 1:
        return

    echo(f'{len(deps_missing) + len(deps_outdated)} dependencies missing{" or outdated" if len(deps_outdated) else ""}, attempting to resolve...')

    mod_list = get_mod_list()
    deps_install = [get_mod_download(mod.Name, mod_list) for mod in deps_missing if mod.Name in mod_list]
    deps_update = [
        UpdateInfo(installed_dict[dep.Name], dep.Version, mod_list[dep.Name]['URL'])
        for dep in deps_outdated if dep.Name in mod_list
    ]

    unresolved = (len(deps_missing) + len(deps_outdated)) - (len(deps_install) + len(deps_update))
    if unresolved != 0:
        echo(f'{unresolved} mods could not be resolved.')

    if len(deps_install) > 0:
        echo('\tTo Install:')
    for mod in deps_install:
        echo(mod.Meta)
    if len(deps_update) > 0:
        echo('\tTo Update:')
    for mod in deps_update:
        echo(f'{mod.Old} -> {mod.New}')

    download_size_ref = [0]
    def download_size_key(mod: t.Union[UpdateInfo, ModDownload]):
        size = get_download_size(mod.Url, mod.Old.Size) if isinstance(mod, UpdateInfo) else mod.Meta.Size
        download_size_ref[0] += size
        return size

    sorted_dep_downloads = sorted(itertools.chain(deps_install, deps_update), key = download_size_key)

    download_size = download_size_ref[0]
    if download_size >= 0:
        echo(f'After this operation, an additional {format_bytes(download_size)} disk space will be used')
    else:
        echo(f'After this operation, {format_bytes(abs(download_size))} disk space will be freed')

    click.confirm('Continue?', default=True, abort=True)

    start = time.perf_counter()
    download_threaded(mods_folder, sorted_dep_downloads, thread_count=10)
    end = time.perf_counter()
    tqdm.write(str.format('Downloaded files in {:.3f} seconds.', end-start))

    everest_min = next((dep.Version for dep in special if dep.Name == 'Everest'), Version(1, 0, 0))
    current_everest = Version(1, install_cache.getint('everestbuild', fallback=0), 0)
    if not current_everest.satisfies(everest_min):
        echo(f'Installed Everest ({current_everest}) does not satisfy minimum requirement ({everest_min}).')
        if click.confirm('Update Everest?', True):
            mons_cli.main(args=['install', install.name, str(everest_min)])
