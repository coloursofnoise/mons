#!/usr/bin/env python

#region IMPORTS
import sys
import os
import configparser
import importlib
from enum import Enum, auto

import hashlib
import shutil
import subprocess

import urllib.request
import zipfile
import json
import io

import dnfile # https://github.com/malwarefrank/dnfile
from pefile import DIRECTORY_ENTRY # https://github.com/erocarrera/pefile

from typing import Union, Tuple, List, Dict, Any
from pprint import pprint
#endregion

#region CONSTANTS
PLUGIN_MODULE = 'bin'

USER_FOLDER = './usr'
CONFIG_FILE = f'{USER_FOLDER}/config.ini'
INSTALLS_FILE = f'{USER_FOLDER}/installs.ini'
CACHE_FILE = f'{USER_FOLDER}/cache.ini'
PLUGIN_FOLDER = './bin'

#Config, Installs, Cache
Config_DEFAULT = {}
Installs_DEFAULT = {
    'PreferredBranch': 'stable',
}
Cache_DEFAULT = {
    'CelesteVersion': '1.4.0.0',
    'Everest': False,
    'Hash': 'f1c4967fa8f1f113858327590e274b69',
}

VANILLA_HASH = {
    'f1c4967fa8f1f113858327590e274b69': ('1.4.0.0', 'FNA'),
    '107cd146973f2c5ec9fb0b4f81c1588a': ('1.4.0.0', 'XNA'),
}

#endregion

#region UTILITIES
#region COMMAND UTILS
Commands = {}
class Command:
    def __init__(self, func, desc, argSpec, flagSpec):
        self.f = func
        self.desc = desc
        self.flagSpec = flagSpec
        self.argSpec = argSpec

    def __call__(self, args):
        args, flags, res = splitFlags(args, self.flagSpec)
        if res == 'help':
            print(self.desc)
        elif self.argSpec and not validateArgs(args, self.argSpec):
            return
        elif res:
            return self.f(args, flags)
        elif res == None:
            return self.f(args)

def command(func=None, makeGlobal=False, desc:str='', argSpec={}, flagSpec={}):
    def add_command(func):
        command = func.__name__.replace('_', '-')
        if command in Commands:
            raise ValueError(f'Duplicate command: {command}')
        Commands[command] = Command(func, desc or command, argSpec, flagSpec)
        if (makeGlobal):
            return func

    return add_command(func) if callable(func) else add_command

def splitFlags(args, flagSpec):
    if flagSpec == None:
        return args, None, None

    positional = []
    flags = {}

    i = 0
    while i < len(args):
        if args[i].startswith('--'):
            flag = args[i][2:]
            if flag == 'help':
                return None, None, 'help'
            if flag not in flagSpec:
                raise ValueError(f'unknown flag `{flag}`')
            if flagSpec[flag] is None:
                flags[flag] = None
            elif flagSpec[flag] is str:
                i += 1
                flags[flag] = args[i]
        else:
            positional.append(args[i])
        i += 1
    return positional, flags, True

class ArgType(Enum):
    INSTALL = auto()
    ANY = auto()

def validateArgs(args, argSpec):
    argCount = len(argSpec)
    for i in range(len(args)):
        if argSpec[i] == ArgType.INSTALL and args[i] not in Installs.sections():
            print(f'error: install `{args[0]}` does not exist.')
            return False
        if argSpec[i] == ArgType.ANY:
            pass
    return True
#endregion

def loadConfig(file, default) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    file = resolvePath(file, local=True)
    if os.path.isfile(file):
        config.read(file)
    else:
        config['DEFAULT'] = default
        os.makedirs(resolvePath(USER_FOLDER, local=True), exist_ok=True)
        with open(file, 'x') as f:
            config.write(f)
    return config

def saveConfig(config, file) -> bool:
    with open(resolvePath(file, local=True), 'w') as f:
        config.write(f)

def loadPlugins():
    if os.path.exists(resolvePath(PLUGIN_FOLDER, local=True)):
        for file in os.listdir(resolvePath(PLUGIN_FOLDER, local=True)):
            name, ext = os.path.splitext(file)
            if ext == '.py':
                plugin = importlib.import_module(f'{PLUGIN_MODULE}.{name}')
                if not (hasattr(plugin, 'PREFIX') and hasattr(plugin, 'main')):
                    print(f'Plugin {plugin} not loaded:')
                    print('Plugins must include a \'PREFIX\' constant and \'main\' function')
                    continue
                Commands[plugin.PREFIX] = plugin.main

def resolvePath(*paths: str, local=False) -> str:
    root = ""
    if local:
        root = os.path.dirname(__file__)
    return os.path.normpath(os.path.join(root, *paths))

def fileExistsInFolder(path: str, filename: str, forceName=True, log=False) -> str:
    installPath = None
    if os.path.isfile(path):
        if not forceName or os.path.basename(path) == filename:
            installPath = path
        elif log:
            print(f'error: file `{installPath}` must be called {filename}')
    elif os.path.isdir(path):
        if os.path.isfile(os.path.join(path, filename)):
            installPath = os.path.join(path, filename)
        elif log:
            print(f'error: {filename} file could not be found in `{installPath}`')
    elif log:
        print(f'error: `{path}` could not be resolved')
    return installPath

def getMD5Hash(path: str) -> str:
    with open(path, "rb") as f:
        file_hash = hashlib.md5()
        chunk = f.read(8129)
        while chunk:
            file_hash.update(chunk)
            chunk = f.read(8129)
    return file_hash.hexdigest()

def getCelesteVersion(path, hash=None):
    hash = hash or getMD5Hash(path)
    version = VANILLA_HASH.get(hash, '')
    if version:
        return version, True

    orig_path = os.path.join(os.path.dirname(path), 'orig', 'Celeste.exe')
    if os.path.isfile(orig_path):
        hash = getMD5Hash(orig_path)
        version = VANILLA_HASH.get(hash, '')
        if version:
            return version, False

    return None, False

def parseExeInfo(path):
    print('loading exe...', end='\r')
    pe = dnfile.dnPE(path, fast_load=True)
    pe.parse_data_directories(directories=DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR'])
    stringHeap: dnfile.stream.StringsHeap = pe.net.metadata.streams_list[1]

    hasEverest = False
    everestBuild = None

    heapSize = stringHeap.sizeof()
    i = 0
    while i < len(stringHeap.__data__):
        string = stringHeap.get(i)
        if string == 'EverestModule':
            hasEverest = True
        if string.startswith('EverestBuild'):
            everestBuild = string[len('EverestBuild'):]
            hasEverest = True
            break
        i += max(len(string), 1)
        printProgressBar(i, heapSize, 'scanning exe:', persist=False)

    assemRef = pe.net.mdtables.AssemblyRef
    framework = 'FNA' if any(row.Name == 'FNA' for row in assemRef.rows) else 'XNA'

    return hasEverest, everestBuild, framework

def getInstallInfo(install) -> Union[Dict[str, Any], configparser.SectionProxy]:
    path = Installs[install]['Path']
    mainHash = getMD5Hash(path)
    if Cache.has_section(install) and Cache[install].get('Hash', '') == mainHash:
        return Cache[install]

    if mainHash in VANILLA_HASH:
        version, framework = VANILLA_HASH[mainHash]
        info = {
            'Everest': False,
            'CelesteVersion': version,
            'Framework': framework,
            # EverestBuild: None
        }
    else:
        hasEverest, everestBuild, framework = parseExeInfo(path)
        info = {}
        if hasEverest:
            info['Everest'] = True
            if everestBuild:
                info['EverestBuild'] = everestBuild

            origHash = getMD5Hash(os.path.join(os.path.dirname(path), 'orig', 'Celeste.exe'))
            if origHash in VANILLA_HASH:
                info['CelesteVersion'], _ = VANILLA_HASH[origHash]
        else:
            info['Everest'] = False

        info['Framework'] = framework

    info['Hash'] = mainHash
    Cache[install] = info.copy() # otherwise it makes all keys in info lowercase
    return info

def buildVersionString(installInfo: Dict[str, Any]) -> str:
    versionStr = installInfo.get('CelesteVersion', 'unknown')
    framework = installInfo.get('Framework', None)
    if framework:
        versionStr += f'-{framework.lower()}'
    everestBuild = installInfo.get('EverestBuild', None)
    if everestBuild:
        versionStr += f' + 1.{everestBuild}.0'
    else:
        hasEverest = installInfo.get('Everest', None)
        if hasEverest:
            versionStr += f' + Everest(unknown version)'
    return versionStr

def updateCache(install):
    path = Installs[install]['Path']
    newHash = getMD5Hash(path)

    celesteversion, vanilla = getCelesteVersion(path)
    Cache[install] = {
        'Hash': newHash,
        'Everest': not vanilla,
    }

    if celesteversion:
        Cache[install]['CelesteVersion'] = celesteversion
    pass

def parseVersionSpec(string: str) -> int:
    if string.startswith('1.') and string.endswith('.0'):
        string = string[2:-2]
    if string.isdigit():
        buildnumber = int(string)
    else:
        buildnumber = getLatestBuild(string)

    return buildnumber

def getLatestBuild(branch: str) -> int:
    builds = json.loads(urllib.request.urlopen('https://dev.azure.com/EverestAPI/Everest/_apis/build/builds?api-version=6.0').read())['value']
    for build in builds:
        if not (build['status'] == 'completed' and build['result'] == 'succeeded'):
            continue
        if not (build['reason'] == 'manual' or build['reason'] == 'individualCI'):
            continue

        if not branch or branch == build['sourceBranch'].replace('refs/heads/', ''):
            try:
                return int(build['id']) + 700
            except:
                pass
    print(f'error: `{branch}` branch could not be found')
    return False

def getBuildDownload(build: int, artifactName='olympus-build'):
    return urllib.request.urlopen(f'https://dev.azure.com/EverestAPI/Everest/_apis/build/builds/{build - 700}/artifacts?artifactName={artifactName}&api-version=6.0&%24format=zip')

def unpack(zip: zipfile.ZipFile, root: str, prefix=''):
    totalSize = 0
    for zipinfo in zip.infolist():
        if not prefix or zipinfo.filename.startswith(prefix):
            totalSize += zipinfo.file_size

    progress = 0
    for zipinfo in zip.infolist():
        if not prefix or zipinfo.filename.startswith(prefix):
            zip.extract(zipinfo, root)
            progress += zipinfo.file_size
            printProgressBar(progress, totalSize, 'extracting:')

# shutils.copytree(dirs_exist_ok) replacement https://stackoverflow.com/a/15824216
def copy_recursive_force(src, dest, ignore=None):
    if os.path.isdir(src):
        if not os.path.isdir(dest):
            os.makedirs(dest)
        files = os.listdir(src)
        if ignore is not None:
            ignored = ignore(src, files)
        else:
            ignored = set()
        for f in files:
            if f not in ignored:
                copy_recursive_force(os.path.join(src, f),
                                    os.path.join(dest, f),
                                    ignore)
    else:
        shutil.copyfile(src, dest)

def isUnchanged(src, dest, file):
    srcFile = os.path.join(src, file)
    destFile = os.path.join(dest, file)
    if os.path.exists(destFile):
        return os.stat(destFile).st_mtime - os.stat(srcFile).st_mtime >= 0
    return False

# Print iterations progress - https://stackoverflow.com/a/34325723
def printProgressBar (iteration, total, prefix = '', suffix = '', decimals = 1, length = 50, fill = '/', printEnd = "\r", persist=True):
    """
    Call in a loop to create terminal progress bar
    @params:
        iteration   - Required  : current iteration (Int)
        total       - Required  : total iterations (Int)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        length      - Optional  : character length of bar (Int)
        fill        - Optional  : bar fill character (Str)
        printEnd    - Optional  : end character (e.g. "\r", "\r\n") (Str)
    """
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filledLength = int(length * iteration // total)
    bar = fill * filledLength + '-' * (length - filledLength)
    output = f'\r{prefix} |{bar}| {percent}% {suffix}'
    print(output, end = printEnd)
    # Print New Line on Complete
    if persist and iteration == total: 
        print()
    elif not persist and iteration == total:
        print('\r' + (' ' * len(output)), end='\r')

#endregion

#region COMMANDS
@command(makeGlobal=True)
def help(args, flags):
    print('''
usage: mons [--version] [--help]
            <command> [<args>]
'''.strip())
    print('Available commands:')
    pprint(Commands.keys())

@command(desc='''usage: add <name> <pathspec>...

    --set-primary   set as default install for commands''')
def add(args, flags):
    path = os.path.abspath(args[1])
    installPath = fileExistsInFolder(path, 'Celeste.exe', forceName=False, log=True)

    if installPath:
        Installs[args[0]] = {
            'Path': installPath,
        }
        print(f'found Celeste.exe: {installPath}')
        print('caching install info...')
        getInstallInfo(args[0])

@command(desc='''usage: mons rename <old> <new>''',
    argSpec=[ArgType.INSTALL]
)
def rename(args, flags):
    if not Installs.has_section(args[1]):
        Installs[args[1]] = Installs.pop(args[0])
    else:
        print(f'error: install `{args[1]}` already exists.')

@command(desc='''usage: mons set-path <name> <pathSpec>''',
    argSpec=[ArgType.INSTALL]
)
def set_path(args, flags):
    path = os.path.abspath(args[1])
    installPath = fileExistsInFolder(path, 'Celeste.exe', forceName=False, log=True)
    if installPath:
        Installs[args[0]]['Path'] = installPath
        print(f'found Celeste.exe: {installPath}')
        print('caching install info...')
        getInstallInfo(args[0])

@command(desc='''usage: mons remove <name>''',
    argSpec=[ArgType.INSTALL]
)
def remove(args, flags):
    Installs.remove_section(args[0])
    Cache.remove_section(args[0])

@command(desc='''usage: mons set-branch <name> <branch>''',
    argSpec=[ArgType.INSTALL]
)
def set_branch(args, flags):
    Installs[args[0]]['preferredBranch'] = args[1]

@command(desc='''usage: mons list''')
def list(args, flags):
    for install in Installs.sections():
        info = buildVersionString(getInstallInfo(install))
        print('{}:\t{}'.format(install, info))

@command(
    desc='''usage: mons info <name> [--verbose]''',
    flagSpec={ 'verbose': None },
    argSpec=[ArgType.INSTALL]
)
def info(args, flags):
    info = getInstallInfo(args[0])
    if 'verbose' in flags:
        print('\n'.join('{}:\t{}'.format(k, v) for k, v in info.items()))
    else:
        print(buildVersionString(info))

@command(desc='''
usage: mons install <name> [<options>] <versionspec>

    --verbose\tbe verbose

    --latest\tlatest available build, branch-ignorant
    --zip <file>\tinstall from local zip artifact
    --src <file>\tbuild and install from source folder

    --launch\tlaunch Celeste after installing
'''.strip(),
    argSpec=[ArgType.INSTALL, ArgType.ANY],
    flagSpec={
        'latest': None,
        'zip': str,
        'src': str,
        'launch': None,
        'verbose': None,
    }
)
def install(args, flags):
    path = Installs[args[0]]['Path']
    installDir = os.path.dirname(path)
    success = False

    sourceDir = None
    artifactPath = None
    build = None
    if 'src' in flags:
        sourceDir = flags['src']
        if not sourceDir:
            print('--src flag set without a directory specified')
            return

        ret = None
        if shutil.which('dotnet'):
            ret = subprocess.run('dotnet build', cwd=sourceDir)
        elif shutil.which('msbuild'):
            ret = subprocess.run(['msbuild', '-v:m'], cwd=sourceDir)
        else:
            print('unable to build: could not find `dotnet` or `msbuild` on PATH')

        if ret.returncode == 0:
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

    elif 'zip' in flags:
        artifactPath = resolvePath(flags['zip'])
    elif args[1].startswith('file://'):
        artifactPath = args[1][len('file://'):]

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
        build = parseVersionSpec(args[1])
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
        stdout = None if 'verbose' in flags else subprocess.DEVNULL
        installer_ret = subprocess.run(os.path.join(installDir, 'MiniInstaller.exe'), stdout=stdout, stderr=subprocess.STDOUT, cwd=installDir)
        if installer_ret.returncode == 0:
            print('install success')
            if build:
                peHash = getMD5Hash(path)
                Cache[args[0]].update({
                    'Hash': peHash,
                    'Everest': str(True),
                    'EverestBuild': str(build),
                })
            else:
                getInstallInfo(args[0])
                print('install info cached')
            if 'launch' in flags:
                print('launching Celeste')
                subprocess.Popen(path)

@command(desc='''usage: mons launch <name> <flags>''', 
    flagSpec=None,
    argSpec=[ArgType.INSTALL]
)
def launch(args):
    if os.path.exists(Installs[args[0]]['Path']):
        args[0] = Installs[args[0]]['Path']
        subprocess.Popen(args)
#endregion

#region MAIN
def main():
    if (len(sys.argv) < 2 or sys.argv[1] == '--help'):
        Commands['help'](sys.argv[2:])
        return

    command = sys.argv[1]
    if command in Commands:
        Commands[command](sys.argv[2:])
    else:
        print(f'mons: `{command}` is not a mons command. See `mons --help`.')


if __name__ == '__main__':
    global Config, Installs, Cache
    Config = loadConfig(CONFIG_FILE, Config_DEFAULT)
    Installs = loadConfig(INSTALLS_FILE, Installs_DEFAULT)
    Cache = loadConfig(CACHE_FILE, Cache_DEFAULT)

    loadPlugins()

    main()

    saveConfig(Config, CONFIG_FILE)
    saveConfig(Installs, INSTALLS_FILE)
    saveConfig(Cache, CACHE_FILE)
#endregion