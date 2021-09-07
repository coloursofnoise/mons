import click
from click import echo

import os
import subprocess
import io

from mons.mons import cli
from mons.utils import *
from mons.clickExt import *

@cli.command(no_args_is_help=True)
@click.argument('name', type=Install(exist=False))
@click.argument('path', type=click.Path(exists=True, resolve_path=True))
#@click.option('--set-primary', is_flag=True, help='set as default install for commands')
@click.pass_obj
def add(userInfo, name, path):
    installPath = fileExistsInFolder(path, 'Celeste.exe', forceName=False, log=True)

    if installPath:
        userInfo.installs[name] = {
            'Path': installPath,
        }
        echo(f'found Celeste.exe: {installPath}')
        echo('caching install info...')
        print(buildVersionString(getInstallInfo(userInfo, name)))

@cli.command(no_args_is_help=True)
@click.argument('old', type=Install(exist=True))
@click.argument('new', type=Install(exist=False))
@click.pass_obj
def rename(userInfo, old, new):
    if not userInfo.installs.has_section(new):
        userInfo.installs[new] = userInfo.installs.pop(old)
    else:
        echo(f'error: install `{new}` already exists.')

@cli.command(no_args_is_help=True)
@click.argument('name', type=Install())
@click.argument('path', type=click.Path(exists=True, resolve_path=True))
@click.pass_obj
def set_path(userInfo, name, path):
    installPath = fileExistsInFolder(path, 'Celeste.exe', forceName=False, log=True)
    if installPath:
        userInfo.installs[name]['Path'] = installPath
        echo(f'found Celeste.exe: {installPath}')
        print('caching install info...', end='\r')
        print(buildVersionString(getInstallInfo(userInfo, name)))

@cli.command(no_args_is_help=True)
@click.argument('name', type=Install())
@click.pass_obj
def remove(userInfo, name):
    userInfo.installs.remove_section(name)
    userInfo.cache.remove_section(name)

@cli.command(no_args_is_help=True)
@click.argument('name', type=Install(resolve_install=True))
@click.argument('branch')
def set_branch(name, branch):
    name['preferredBranch'] = branch

@cli.command()
@click.pass_obj
def list(userInfo):
    for install in userInfo.installs.sections():
        info = buildVersionString(getInstallInfo(userInfo, install))
        echo('{}:\t{}'.format(install, info))

@cli.command(no_args_is_help=True)
@click.argument('name', type=Install())
@click.option('-v', '--verbose', is_flag=True)
@click.pass_obj
def info(userInfo, name, verbose):
    info = getInstallInfo(userInfo, name)
    if verbose:
        echo('\n'.join('{}:\t{}'.format(k, v) for k, v in info.items()))
    else:
        echo(buildVersionString(info))

@cli.command(no_args_is_help=True)
@click.argument('name', type=Install())
@click.argument('versionSpec')
@click.option('-v', '--verbose', is_flag=True, help='be verbose')
@click.option('--latest', is_flag=True, help='latest available build, branch-ignorant')
@click.option('--zip', 
    type=click.Path(exists=True, dir_okay=False, resolve_path=True), 
    help='install from local zip artifact')
@click.option('--src', 
    type=click.Path(exists=True, file_okay=False, resolve_path=True), 
    help='build and install from source folder')
@click.option('--no-build', is_flag=True, help='use with --src to install without building')
@click.option('--launch', is_flag=True, help='launch Celeste after installing')
@click.pass_obj
def install(userInfo, name, versionspec, verbose, latest, zip, src, no_build, launch):
    path = userInfo.installs[name]['Path']
    installDir = os.path.dirname(path)
    success = False

    sourceDir = None
    artifactPath = None
    build = None
    if src:
        sourceDir = src
        if not sourceDir:
            print('--src flag set without a directory specified')
            return

        build_success = 0 if no_build else 1
        if not no_build:
            if shutil.which('dotnet'):
                build_success = subprocess.run('dotnet build', cwd=sourceDir).returncode
            elif shutil.which('msbuild'):
                build_success = ret = subprocess.run(['msbuild', '-v:m'], cwd=sourceDir).returncode
            else:
                print('unable to build: could not find `dotnet` or `msbuild` on PATH')

        if build_success == 0:
            print('copying files...')
            copy_recursive_force(os.path.join(sourceDir, 'Celeste.Mod.mm', 'bin', 'Debug', 'net452'),
                installDir,
                ignore=lambda path, names : [name for name in names if isUnchanged(path, installDir, name)]
            )
            copy_recursive_force(os.path.join(sourceDir, 'MiniInstaller', 'bin', 'Debug', 'net452'),
                installDir,
                ignore=lambda path, names : [name for name in names if isUnchanged(path, installDir, name)]
            )
            success = True

    elif zip:
        artifactPath = zip
    elif versionspec.startswith('file://'):
        artifactPath = versionspec[len('file://'):]

    if artifactPath:
        print(f'unzipping {os.path.basename(artifactPath)}')
        with zipfile.ZipFile(artifactPath) as wrapper:
            try:
                entry = wrapper.open('olympus-build/build.zip') # Throws KeyError if not present
                with zipfile.ZipFile(entry) as artifact:
                    unpack(artifact, installDir)
                    success = True
            except KeyError:
                unpack(wrapper, installDir, 'main/')
                success = True

    elif not sourceDir:
        build = parseVersionSpec(versionspec)
        if not build:
            print('Build number could not be retrieved!')
            return

        print('downloading metadata')
        try:
            meta = getBuildDownload(build, 'olympus-meta')
            with zipfile.ZipFile(io.BytesIO(meta.read())) as file:
                size = int(file.read('olympus-meta/size.txt').decode('utf-16'))
        except:
            size = 0

        if size > 0:
            print('downloading olympus-build.zip')
            response = getBuildDownload(build, 'olympus-build')
            artifactPath = os.path.join(installDir, 'olympus-build.zip')
            print(f'to file {artifactPath}')
            blocksize = max(4096, size//100)
            with open(artifactPath, 'wb') as file:
                progress = 0
                while True:
                    buf = response.read(blocksize)
                    if not buf:
                        break
                    file.write(buf)
                    progress += len(buf)
                    printProgressBar(progress, size, 'downloading:')
                printProgressBar(size, size, 'downloading:')
            with zipfile.ZipFile(artifactPath) as wrapper:
                with zipfile.ZipFile(wrapper.open('olympus-build/build.zip')) as artifact:
                    unpack(artifact, installDir)
                    success = True

        else:
            print('downloading main.zip')
            response = getBuildDownload(build, 'main')
            artifactPath = os.path.join(installDir, 'main.zip')
            print(f'to file {artifactPath}')
            with open(artifactPath, 'wb') as file:
                file.write(response.read())
            print('unzipping main.zip')
            with zipfile.ZipFile(artifactPath) as artifact:
                unpack(artifact, installDir, 'main/')
                success = True

    if success:
        print('running MiniInstaller...')
        stdout = None if verbose else subprocess.DEVNULL
        installer_ret = subprocess.run(os.path.join(installDir, 'MiniInstaller.exe'), stdout=stdout, stderr=subprocess.STDOUT, cwd=installDir)
        if installer_ret.returncode == 0:
            print('install success')
            if build:
                peHash = getMD5Hash(path)
                userInfo.cache[name].update({
                    'Hash': peHash,
                    'Everest': str(True),
                    'EverestBuild': str(build),
                })
            else:
                getInstallInfo(userInfo, name)
                print('install info cached')
            if launch:
                print('launching Celeste')
                subprocess.Popen(path)

@cli.command(context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True,
))
@click.argument('name', type=Install())
@click.pass_context
def launch(ctx, name):
    installs = ctx.obj.installs
    if os.path.exists(installs[name]['Path']):
        path = installs[name]['Path']
        subprocess.Popen([path] + ctx.args)
