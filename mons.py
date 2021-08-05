#!/usr/bin/env python

#region IMPORTS
import sys
import os
import configparser
import importlib

import hashlib
import subprocess

import urllib.request
import zipfile
import json

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
    'f1c4967fa8f1f113858327590e274b69': '1.4.0.0',
}

#endregion

#region UTILITIES
Commands = {}
class Command:
    def __init__(self, func, desc, flagSpec):
        self.f = func
        self.desc = desc
        self.flagSpec = flagSpec

    def __call__(self, args):
        args, flags, res = splitFlags(args, self.flagSpec)
        if res == 'help':
            print(self.desc)
        elif res:
            return self.f(args, flags)
        elif res == None:
            return self.f(args)

def command(func=None, makeGlobal=False, desc:str='', flagSpec={}):
    def add_command(func):
        command = func.__name__.replace('_', '-')
        if command in Commands:
            raise ValueError(f'Duplicate command: {command}')
        Commands[command] = Command(func, desc or command, flagSpec)
        if (makeGlobal):
            return func

    return add_command(func) if callable(func) else add_command

def splitFlags(args, flagSpec):
    if not flagSpec:
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

def loadConfig(file, default) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    file = resolvePath(file)
    if os.path.isfile(file):
        config.read(file)
    else:
        config['DEFAULT'] = default
        os.makedirs(resolvePath(USER_FOLDER), exist_ok=True)
        with open(file, 'x') as f:
            config.write(f)
    return config

def saveConfig(config, file) -> bool:
    with open(resolvePath(file), 'w') as f:
        config.write(f)

def loadPlugins():
    for file in os.listdir(resolvePath(PLUGIN_FOLDER)):
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
    return os.path.join(root, *paths)

def getMD5Hash(path: str) -> str:
    with open(path, "rb") as f:
        file_hash = hashlib.md5()
        while chunk := f.read(8192):
            file_hash.update(chunk)
    return file_hash.hexdigest()

def getCelesteVersion(path, hash=None):
    hash = hash or getMD5Hash(path)
    if (version := VANILLA_HASH.get(hash, '')):
        return version, True

    orig_path = os.path.join(os.path.dirname(path), 'orig', 'Celeste.exe')
    if os.path.isfile(orig_path):
        hash = getMD5Hash(orig_path)
        if (version := VANILLA_HASH.get(hash, '')):
            return version, False

    return None, False

def parseExeInfo(path):
    pe = dnfile.dnPE(path, fast_load=True)
    pe.parse_data_directories(directories=DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR'])
    stringHeap: dnfile.stream.StringsHeap = pe.net.metadata.streams_list[1]

    #heapSize = stringHeap.sizeof()
    hasEverest = False
    everestBuild = None

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
                info['CelesteVersion'] = VANILLA_HASH[origHash]
        else:
            info['Everest'] = False

        info['Framework'] = framework

    info['Hash'] = mainHash
    Cache[install] = info.copy() # otherwise it makes all keys in info lowercase
    return info

def buildVersionString(installInfo: Dict[str, Any]) -> str:
    versionStr = installInfo.get('CelesteVersion', 'unknown')
    if framework := installInfo.get('Framework', None):
        versionStr += f'-{framework.lower()}'
    if everestBuild := installInfo.get('EverestBuild', None):
        versionStr += f' + 1.{everestBuild}.0'
    elif hasEverest := installInfo.get('Everest', None):
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
    return False

def downloadBuild(build: int):
    return urllib.request.urlopen(f'https://dev.azure.com/EverestAPI/Everest/_apis/build/builds/{build - 700}/artifacts?artifactName=olympus-build&api-version=6.0&%24format=zip')
#endregion

#region COMMANDS
@command(makeGlobal=True)
def help(args, flags):
    print('''
usage: mons [--version] [--help]
            <command> [<args>]
'''.lstrip())
    print('Available commands:')
    pprint(Commands.keys())

@command(desc='''usage: add <name> <pathspec>...

    --set-primary   set as default install for commands''')
def add(args, flags):
    path = os.path.abspath(args[1])
    installPath = ''
    if os.path.isfile(path) and os.path.splitext(path)[1] == '.exe':
        installPath = path
    elif os.path.isdir(path) and os.path.isfile(os.path.join(path, 'Celeste.exe')):
        installPath = os.path.join(path, 'Celeste.exe')

    if installPath:
        Installs[args[0]] = {
            'Path': installPath,
        }
        print(f'found Celeste.exe: {installPath}')
        print('caching install info...')
        getInstallInfo(args[0])
    else:
        print(f'Could not find Celeste.exe {installPath}')

@command(desc='''usage: mons rename <old> <new>''')
def rename(args, flags):
    if Installs.has_section(args[0]):
        if not Installs.has_section(args[1]):
            Installs[args[1]] = Installs.pop(args[0])
        else:
            print(f'error: install `{args[1]}` already exists.')
    else:
        print(f'error: install `{args[0]}` does not exist.')

@command(desc='''usage: mons set-path <name> <pathSpec>

    --relative  resolve path relative to existing''')
def set_path(args, flags):
    # use add command stuff for this
    Installs[args[0]]['Path'] = resolvePath(args[1])

@command
def set_branch(args, flags):
    Installs[args[0]]['preferredBranch'] = args[1]

@command
def list(args, flags):
    print('Current Installs:')
    pprint(Installs.sections())

@command(
    desc='''usage: mons info <name> [--verbose]''',
    flagSpec={ 'verbose': None }
)
def info(args, flags):
    info = getInstallInfo(args[0])
    if 'verbose' in flags:
        print("\n".join("{}:\t{}".format(k, v) for k, v in info.items()))
    else:
        print(buildVersionString(info))

@command
def install(args, flags):
    path = Installs[args[0]]['Path']
    success = False

    build = parseVersionSpec(args[1])
    if build:
        response = downloadBuild(build)

    if response and response:
        artifactPath = os.path.join(os.path.dirname(path), 'olympus-build.zip')
        print(f'Downloading to file: {artifactPath}...')
        with open(artifactPath, 'wb') as file:
            file.write(response.read())

        with open(artifactPath, 'rb') as file:
            print(f'Opening file {artifactPath}...')
            with zipfile.ZipFile(file, mode='r') as artifact:
                with zipfile.ZipFile(artifact.open('olympus-build/build.zip')) as build:
                    print('Extracting files...')
                    build.extractall(os.path.dirname(path))
                    success = True

    if success:
        print('Success! Starting MiniInstaller:')
        installer_ret = subprocess.run(os.path.join(os.path.dirname(path), 'MiniInstaller.exe'), cwd=os.path.dirname(path))
        if installer_ret.returncode == 0:
            print('Computing new hash for cache...')
            peHash = getMD5Hash(path)
            Cache[args[0]].update({
                'Hash': peHash,
                'Everest': str(True),
            })

@command(desc='''usage: mons launch <name> <flags>''', flagSpec=None)
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