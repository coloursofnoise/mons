from io import BufferedReader, BytesIO
import os
import configparser
import json
import yaml
from yaml.scanner import ScannerError

from datetime import datetime
import hashlib
import xxhash
import zipfile
import shutil

import urllib.request
import urllib.parse
import urllib.response

from click import echo, progressbar

import dnfile # https://github.com/malwarefrank/dnfile
from dnfile.mdtable import AssemblyRefRow
from pefile import DIRECTORY_ENTRY # https://github.com/erocarrera/pefile

from .config import *
from .version import Version
from .errors import *
from .clickExt import tempprogressbar

from typing import IO, Union, List, Dict, Any, cast

VANILLA_HASH = {
    'f1c4967fa8f1f113858327590e274b69': ('1.4.0.0', 'FNA'),
    '107cd146973f2c5ec9fb0b4f81c1588a': ('1.4.0.0', 'XNA'),
}

def fileExistsInFolder(path: str, filename: str, forceName=True, log=False) -> Union[str,None]:
    installPath = None
    if os.path.isfile(path):
        if not forceName or os.path.basename(path) == filename:
            installPath = path
        elif log:
            echo(f'error: file `{installPath}` must be called {filename}')
    elif os.path.isdir(path):
        if os.path.isfile(os.path.join(path, filename)):
            installPath = os.path.join(path, filename)
        elif log:
            echo(f'error: {filename} file could not be found in `{installPath}`')
    elif log:
        echo(f'error: `{path}` could not be resolved')
    return installPath

def getMD5Hash(path: str) -> str:
    with open(path, "rb") as f:
        file_hash = hashlib.md5()
        chunk = f.read(8129)
        while chunk:
            file_hash.update(chunk)
            chunk = f.read(8129)
    return file_hash.hexdigest()

def unpack(zip: zipfile.ZipFile, root: str, prefix=''):
    totalSize = 0
    for zipinfo in zip.infolist():
        if not prefix or zipinfo.filename.startswith(prefix):
            totalSize += zipinfo.file_size

    with progressbar(length=totalSize, label='Extracting') as bar:
        for zipinfo in zip.infolist():
            if not prefix or zipinfo.filename.startswith(prefix):
                zip.extract(zipinfo, root)
                bar.update(zipinfo.file_size)

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

def folder_size(start_path = '.'):
    total_size = 0
    for dirpath, _, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)

    return total_size

def download_with_progress(
    src,
    dest: Union[str, None],
    label: str=None,
    atomic: bool=False,
    clear: bool=False
):
    if not dest and atomic:
        raise ValueError('atomic download cannot be used without destination file')

    response = urllib.request.urlopen(src) if isinstance(src, str) else src
    size = int(response.headers.get('content-length'))
    blocksize = max(4096, size//100)
    temp_dest = ''
    if dest is None:
        io = BytesIO()
    elif atomic:
        # yyyyMMdd-HHmmss
        temp_dest = f'tmpdownload-{datetime.now().strftime("%Y%m%d-%H%M%S")}.zip.part'
        temp_dest = os.path.join(os.path.dirname(dest), temp_dest)
        io = open(temp_dest, 'wb')
    else:
        io = open(dest, 'wb')
    bar = tempprogressbar if clear else progressbar
    with bar(length=size, label=label) as bar:
        while True:
            buf = response.read(blocksize)
            if not buf:
                break
            io.write(buf)
            bar.update(len(buf))

    if dest is None and isinstance(io, BytesIO):
        io.seek(0)
        return io
    io.close()

    if dest and atomic:
        if os.path.isfile(dest):
            os.remove(dest)
        shutil.move(temp_dest, dest)

    return BytesIO()

def write_with_progress(
    src: Union[BufferedReader, BytesIO, str],
    dest: str,
    label: str=None,
    atomic: bool=False,
    clear: bool=False,
):
    src = open(src, mode='rb') if isinstance(src, str) else src

    temp_dest = ''
    if atomic:
        # yyyyMMdd-HHmmss
        temp_dest = f'tmpdownload-{datetime.now().strftime("%Y%m%d-%H%M%S")}.zip.part'
        temp_dest = os.path.join(os.path.dirname(dest), temp_dest)
        io = open(temp_dest, 'wb')
    else:
        io = open(dest, 'wb')

    src.seek(0, os.SEEK_END)
    size = src.tell()
    src.seek(0)
    blocksize = max(4096, size//100)
    with io as file:
        bar = tempprogressbar if clear else progressbar
        with bar(length=size, label=label) as bar:
            while True:
                buf = src.read(blocksize)
                if not buf:
                    break
                file.write(buf)
                bar.update(len(buf))

    src.close()
    if atomic:
        if os.path.isfile(dest):
            os.remove(dest)
        shutil.move(temp_dest, dest)

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
    echo('Loading exe...\r', nl=False)
    pe = dnfile.dnPE(path, fast_load=True)
    pe.parse_data_directories(directories=DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR'])
    stringHeap: dnfile.stream.StringsHeap = pe.net.metadata.streams_list[1]

    hasEverest = False
    everestBuild = None

    heapSize = stringHeap.sizeof()
    i = 0
    with tempprogressbar(length=heapSize, label='Scanning exe') as bar:
        while i < len(stringHeap.__data__):
            string = stringHeap.get(i)
            if string is None:
                break
            if string == 'EverestModule':
                hasEverest = True
            if str(string).startswith('EverestBuild'):
                everestBuild = string[len('EverestBuild'):]
                hasEverest = True
                break
            inc = max(len(string), 1)
            i += inc
            bar.update(inc)

    assemRef = pe.net.mdtables.AssemblyRef
    framework = 'FNA' if any(cast(AssemblyRefRow, row).Name == 'FNA' for row in assemRef.rows) else 'XNA'

    return hasEverest, everestBuild, framework

def getInstallInfo(userInfo, install) -> Union[Dict[str, Any], configparser.SectionProxy]:
    path = userInfo.installs[install]['Path']
    mainHash = getMD5Hash(path)
    if userInfo.cache.has_section(install) and userInfo.cache[install].get('Hash', '') == mainHash:
        return userInfo.cache[install]

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
    userInfo.cache[install] = info.copy() # otherwise it makes all keys in info lowercase
    return info

def buildVersionString(installInfo: Union[Dict[str, Any], configparser.SectionProxy]) -> str:
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

def updateCache(userInfo, install):
    path = userInfo.installs[install]['Path']
    newHash = getMD5Hash(path)

    celesteversion, vanilla = getCelesteVersion(path)
    userInfo.cache[install] = {
        'Hash': newHash,
        'Everest': not vanilla,
    }

    if celesteversion:
        userInfo.cache[install]['CelesteVersion'] = celesteversion
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
    echo(f'error: `{branch}` branch could not be found')
    return False

def getBuildDownload(build: int, artifactName='olympus-build'):
    return urllib.request.urlopen(f'https://dev.azure.com/EverestAPI/Everest/_apis/build/builds/{build - 700}/artifacts?artifactName={artifactName}&api-version=6.0&%24format=zip')

class ModMeta():
    Hash: Union[str, None]
    Path: str
    Size: int
    Blacklisted: bool=False

    def __init__(self, data: Dict):
        self.Name:str = str(data['Name'])
        self.Version = Version.parse(str(data['Version']))
        self.Dependencies = [ModMeta(dep) for dep in data['Dependencies']] if 'Dependencies' in data else []
        self.OptionalDependencies = [ModMeta(dep) for dep in data['OptionalDependencies']] if 'OptionalDependencies' in data else []

class UpdateInfo():
    def __init__(self, old: ModMeta, new: Version, url: str, mirror: str=None):
        self.Old = old
        self.New = new
        self.Url = url
        self.Mirror = mirror if mirror else url

def read_mod_info(mod: Union[str, IO[bytes]], with_size=False):
    meta = None
    try:
        if not isinstance(mod, str) or os.path.isfile and zipfile.is_zipfile(mod):
            with zipfile.ZipFile(mod) as zip:
                if 'everest.yaml' in zip.namelist():
                    yml = yaml.safe_load(zip.read('everest.yaml').decode('utf-8-sig'))
                    if yml is None:
                        raise EmptyFileError()
                    meta = ModMeta(yml[0])
                    if zip.fp:
                        zip.fp.seek(0)
                        meta.Hash = xxhash.xxh64_hexdigest(zip.fp.read())
                        zip.fp.seek(0, os.SEEK_END)
                        meta.Size = zip.fp.tell() if with_size else 0

        elif os.path.isdir(mod) and os.path.isfile(os.path.join(mod, 'everest.yaml')):
            with open(os.path.join(mod, 'everest.yaml'), encoding='utf-8-sig') as file:
                yml = yaml.safe_load(file)
                if yml is None:
                    raise EmptyFileError()
                meta = ModMeta(yml[0])
            meta.Size = folder_size(mod) if with_size else 0
    except (EmptyFileError, ScannerError):
        return None
    except Exception:
        echo(mod)
        raise

    if meta:
        meta.Path = mod if isinstance(mod, str) else ''
    return meta

def get_mod_list():
    update_url = urllib.request.urlopen('https://everestapi.github.io/modupdater.txt').read()
    return yaml.safe_load(download_with_progress(update_url.decode(), None, 'Downloading update list'))

def search_mods(search):
    search = urllib.parse.quote_plus(search)
    url = f'https://max480-random-stuff.appspot.com/celeste/gamebanana-search?q={search}'
    response = urllib.request.urlopen(url)
    return yaml.safe_load(response.read())

def read_blacklist(path: str):
    with open(path) as file:
        return [m.strip() for m in file.readlines() if not m.startswith('#')]

def installed_mods(path: str, include_folder=False, valid_only=True, include_blacklisted=False, with_size=False):
    files = os.listdir(path)
    if os.path.isfile(os.path.join(path, 'blacklist.txt')):
        blacklist = read_blacklist(os.path.join(path, 'blacklist.txt'))
        if not include_blacklisted:
            files = filter(lambda m: m not in blacklist, files)

    mods: List[ModMeta] = []
    for file in files:
        if include_folder or not os.path.isdir(os.path.join(path, file)):
            mod = read_mod_info(os.path.join(path, file), with_size=with_size)
            if not mod:
                continue
            if blacklist and file in blacklist:
                mod.Blacklisted = True
            mods.append(mod)
    return mods

def enable_mod(path: str, mod: str):
    blacklist_path = os.path.join(path, 'blacklist.txt')
    if os.path.isfile(blacklist_path):
        with open(blacklist_path) as file:
            blacklist = file.readlines()
        i = 0
        while i < len(blacklist):
            if blacklist[i].strip() == mod:
                blacklist[i] = '#' + blacklist[i]
            i += 1
        with open(blacklist_path, mode='w') as file:
            file.writelines(blacklist)