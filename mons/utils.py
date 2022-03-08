from io import BytesIO
import os
import atexit
import configparser
import json
import tempfile
import yaml
from yaml.scanner import ScannerError

import hashlib
import xxhash
import zipfile
import gzip
import shutil
from contextlib import contextmanager

import urllib.request
import urllib.parse
import urllib.response
opener=urllib.request.build_opener()
opener.addheaders=[('User-Agent','Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/36.0.1941.0 Safari/537.36')]
urllib.request.install_opener(opener)
from http.client import HTTPResponse

from click import echo, Abort
from tqdm import tqdm

import dnfile # https://github.com/malwarefrank/dnfile
from dnfile.mdtable import AssemblyRefRow
from pefile import DIRECTORY_ENTRY # https://github.com/erocarrera/pefile

from .config import *
from .version import Version
from .errors import *

from typing import IO, Generic, Iterable, Iterator, Tuple, Union, List, Dict, cast, TypeVar, Optional

VANILLA_HASH = {
    'f1c4967fa8f1f113858327590e274b69': ('1.4.0.0', 'FNA'),
    '107cd146973f2c5ec9fb0b4f81c1588a': ('1.4.0.0', 'XNA'),
}

T = TypeVar('T')

def flip(b:Optional[T]) -> Optional[T]:
    if b is None:
        return None
    return cast(Optional[T], not b)

def partition(pred, iterable:Iterable[T]) -> Tuple[List[T], List[T]]:
    trues: List[T] = []
    falses: List[T] = []
    for item in iterable:
        if pred(item):
            trues.append(item)
        else:
            falses.append(item)
    return trues, falses

def multi_partition(*predicates, iterable:Iterable[T]) -> Tuple[List[T], ...]:
    results: List[List[T]] = [[] for _ in predicates]
    results.append([])

    for item in iterable:
        i = 0
        matched = False
        for pred in predicates:
            if pred(item):
                results[i].append(item)
                matched = True
                break
            i += 1
        if not matched:
            results[-1].append(item)

    return tuple(results)


def tryExec(func, *params):
    try:
        func(*params)
    except:
        pass

def fileExistsInFolder(path: str, filename: str, forceName=True, log=False) -> Union[str,None]:
    installPath = None
    if os.path.isfile(path):
        if not forceName or os.path.basename(path) == filename:
            installPath = path
        elif log:
            echo(f'Error: file `{installPath}` must be called {filename}')
    elif os.path.isdir(path):
        if os.path.isfile(os.path.join(path, filename)):
            installPath = os.path.join(path, filename)
        elif log:
            echo(f'Error: {filename} file could not be found in `{installPath}`')
    elif log:
        echo(f'Error: `{path}` could not be resolved')
    return installPath

def find(iter:Iterable[T], matches:Iterable[T]):
    return next((match for match in iter if match in matches), None)


def find_file(path:str, files:Iterable[str]):
    for file in files:
        if os.path.isfile(os.path.join(path, file)):
            return file
    return None

def getMD5Hash(path: str) -> str:
    with open(path, "rb") as f:
        file_hash = hashlib.md5()
        chunk = f.read(8129)
        while chunk:
            file_hash.update(chunk)
            chunk = f.read(8129)
    return file_hash.hexdigest()

def unpack(zip: zipfile.ZipFile, root: str, prefix='', label='Extracting'):
    totalSize = 0
    for zipinfo in zip.infolist():
        if not prefix or zipinfo.filename.startswith(prefix):
            totalSize += zipinfo.file_size

    with tqdm(total=totalSize, desc=label) as bar:
        for zipinfo in zip.infolist():
            if not zipinfo.filename or zipinfo.filename.endswith('/'):
                continue

            if prefix:
                if not zipinfo.filename.startswith(prefix):
                    continue
                zipinfo.filename = zipinfo.filename[len(prefix):]

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

def get_download_size(url: str, initial_size: int=0):
    request = urllib.request.Request(url, method='HEAD')
    return int(urllib.request.urlopen(request).headers['Content-Length']) - initial_size

_download_interrupt = False

def read_with_progress(
    input,
    output,
    size=0,
    blocksize=4096,
    label: Optional[str]='',
    clear_progress: Optional[bool]=False,
):
    with tqdm(total=size, desc=label, leave=(not clear_progress), unit_scale=True, unit='b', delay=0.4, disable=False) as bar:
        while True:
            if _download_interrupt:
                raise Abort

            buf = input.read(blocksize)
            if not buf:
                break
            output.write(buf)
            bar.update(len(buf))

def download_with_progress(
    src: Union[str, urllib.request.Request, HTTPResponse],
    dest: Optional[str],
    label: Optional[str]=None,
    atomic: Optional[bool]=False,
    clear: Optional[bool]=False,
    *,
    response_handler=None,
):
    if not dest and atomic:
        raise ValueError('atomic download cannot be used without destination file')

    response = urllib.request.urlopen(src, timeout=5) if isinstance(src, (str, urllib.request.Request)) else src
    content = response_handler(response) if response_handler else response
    size = int(response.headers.get('Content-Length') or 100)
    blocksize = 8192
    
    with temporary_file(persist=False) if atomic else nullcontext(dest) as file:
        with open(file, 'wb') if file else nullcontext(BytesIO()) as io:
            read_with_progress(content, io, size, blocksize, label, clear)

            if dest is None and isinstance(io, BytesIO):
                # io will not be closed by contextmanager because it used nullcontext
                io.seek(0)
                return io
        
        if atomic:
            dest = cast(str, dest)
            if os.path.isfile(dest):
                os.remove(dest)
            shutil.move(cast(str, file), dest)

    return BytesIO()

@contextmanager
def relocated_file(src, dest):
    file = shutil.move(src, dest)
    try:
        yield file
    finally:
        shutil.move(file, src)

@contextmanager
def copied_file(src, dest):
    file = shutil.copy(src, dest)
    try:
        yield file
    finally:
        os.remove(file)

@contextmanager
def temporary_file(persist=False):
    fd, path = tempfile.mkstemp(suffix='_mons')
    if persist:
        atexit.register(tryExec, os.remove, path)
    os.close(fd)
    try:
        yield path
    finally:
        if not persist and os.path.isfile(path):
            os.remove(path)


@contextmanager
def nullcontext(ret: T) -> Iterator[T]:
    yield ret

class GeneratorWithLen(Generic[T]):
    def __init__(self, gen:Iterator[T], length: int):
        self.gen = gen
        self.length = length
    
    def __iter__(self):
        return self.gen

    def __next__(self):
        return next(self.gen)

    def __len__(self):
        return self.length


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
    with tqdm(total=heapSize, desc='Scanning exe', leave=False) as bar:
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

def getInstallInfo(userInfo: UserInfo, install: str) -> configparser.SectionProxy:
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
    userInfo.cache[install] = info # otherwise it makes all keys in info lowercase
    return userInfo.cache[install]

def buildVersionString(installInfo: configparser.SectionProxy) -> str:
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
            versionStr += ' + Everest(unknown version)'
    return versionStr

def updateCache(userInfo: UserInfo, install: str):
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

def parseVersionSpec(string: str):
    if string.startswith('1.') and string.endswith('.0'):
        string = string[2:-2]
    if string.isdigit():
        buildnumber = int(string)
    else:
        buildnumber = getLatestBuild(string)

    return buildnumber

def getLatestBuild(branch: str):
    base_URL = 'https://dev.azure.com/EverestAPI/Everest/_apis/build/builds?'
    filters = [
        'definitions=3',
        'statusFilter=completed',
        'resultFilter=succeeded',
        'branchName={0}'.format(branch
            if branch == '' or branch.startswith(('refs/heads/', 'refs/pull/'))
            else 'refs/heads/' + branch),
        'api-version=6.0',
        '$top=1',
    ]
    request = base_URL + '&'.join(filters)
    response = json.load(urllib.request.urlopen(request))
    if response['count'] < 1:
        return None
    elif response['count'] > 1:
        raise Exception('Unexpected number of builds: {0}'.format(response['count']))

    build = response['value'][0]
    id = build['id']
    try:
        return int(id) + 700
    except:
        pass
    return None

def getBuildDownload(build: int, artifactName: str='olympus-build'):
    return urllib.request.urlopen(f'https://dev.azure.com/EverestAPI/Everest/_apis/build/builds/{build - 700}/artifacts?artifactName={artifactName}&api-version=6.0&%24format=zip')

class _ModMeta_Base():
    def __init__(self, name:str, version:Union[str, Version]):
        self.Name = name
        if isinstance(version, str):
            version = Version.parse(version)
        self.Version = version

    @classmethod
    def fromDict(cls, data):
        return _ModMeta_Base(str(data['Name']), str(data['Version']))

    def __repr__(self) -> str:
        return f'{self.Name}: {self.Version}'

class _ModMeta_Deps():
    def __init__(
        self,
        dependencies:List[_ModMeta_Base],
        optionals:List[_ModMeta_Base],
    ):
        self.Dependencies = dependencies
        self.OptionalDependencies = optionals
        assert isinstance(self.Dependencies, List)

    @classmethod
    def fromDict(cls, data):
        return _ModMeta_Deps(
            [_ModMeta_Base.fromDict(dep) for dep in data['Dependencies']],
            [_ModMeta_Base.fromDict(dep) for dep in data['OptionalDependencies']]
        )

class ModMeta(_ModMeta_Base,_ModMeta_Deps):
    Hash: Optional[str]
    Path: str
    Blacklisted: Optional[bool]=False

    def __init__(self, data: Dict):
        _ModMeta_Base.__init__(self, str(data['Name']), str(data['Version']))
        _ModMeta_Deps.__init__(self,
            [_ModMeta_Base.fromDict(dep) for dep in data.get('Dependencies', [])],
            [_ModMeta_Base.fromDict(dep) for dep in data.get('OptionalDependencies', [])]
        )
        self.DLL = str(data['DLL']) if 'DLL' in data else None
        self.Size = int(data['Size']) if 'Size' in data else 0

class ModDownload():
    def __init__(self, meta: Union[ModMeta, Dict], url: str, mirror: Optional[str]=None):
        if isinstance(meta, Dict):
            meta = ModMeta(meta)
        self.Meta = meta
        self.Url = url
        self.Mirror = mirror if mirror else url

def _merge_dependencies(dict, dep: _ModMeta_Base):
    if dep.Name in dict:
        if dep.Version.Major != dict[dep.Name].Version.Major:
            raise ValueError('Incompatible dependencies encountered: ' + \
                f'{dep.Name} {dep.Version} vs {dep.Name} {dict[dep.Name].Version}')
        elif dep.Version > dict[dep.Name].Version:
            dict[dep.Name] = dep
    else:
        dict[dep.Name] = dep

def recurse_dependencies(mods: Iterable[_ModMeta_Base], dependency_graph, dict):
    for mod in mods:
        _merge_dependencies(dict, mod)
        if mod.Name in dependency_graph:
            recurse_dependencies(_ModMeta_Deps.fromDict(dependency_graph[mod.Name]).Dependencies, dependency_graph, dict)

def combined_dependencies(mods: Iterable[_ModMeta_Base], dependency_graph) -> Dict[str, _ModMeta_Base]:
    deps = {}
    for mod in mods:
        dependencies = None
        if mod.Name in dependency_graph:
            dependencies = _ModMeta_Deps.fromDict(dependency_graph[mod.Name]).Dependencies
        elif isinstance(mod, _ModMeta_Deps):
            dependencies = mod.Dependencies
        if dependencies:
            recurse_dependencies(dependencies, dependency_graph, deps)
    return deps

class UpdateInfo():
    def __init__(self, old: ModMeta, new: Version, url: str, mirror: Optional[str]=None):
        self.Old = old
        self.New = new
        self.Url = url
        self.Mirror = mirror if mirror else url

def read_mod_info(mod: Union[str, IO[bytes]], with_size=False, with_hash=False):
    meta = None
    try:
        if not isinstance(mod, str) or os.path.isfile and zipfile.is_zipfile(mod):
            with zipfile.ZipFile(mod) as zip:
                everest_file = find(zip.namelist(), ('everest.yaml', 'everest.yml'))
                if everest_file:
                    yml = yaml.safe_load(zip.read(everest_file).decode('utf-8-sig'))
                    if yml is None:
                        raise EmptyFileError()
                    meta = ModMeta(yml[0])
                    if zip.fp:
                        zip.fp.seek(0)
                        if with_hash:
                            meta.Hash = xxhash.xxh64_hexdigest(zip.fp.read())
                        zip.fp.seek(0, os.SEEK_END)
                        meta.Size = zip.fp.tell() if with_size else 0

        elif os.path.isdir(mod):
            everest_file = find_file(mod, ('everest.yaml', 'everest.yml'))
            if everest_file:
                with open(os.path.join(mod, everest_file), encoding='utf-8-sig') as file:
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

def get_mod_list() -> Dict[str, Dict]:
    update_url = urllib.request.urlopen('https://everestapi.github.io/modupdater.txt').read()
    request = urllib.request.Request(update_url.decode(), headers={
        'User-Agent': 'mons/' + '; gzip',
        'Accept-Encoding': 'gzip'
    })
    return yaml.safe_load(download_with_progress(request, None, 'Downloading Update List', clear=True, response_handler=gzip.open))

def get_dependency_graph() -> Dict[str, Dict]:
    request = urllib.request.Request('https://max480-random-stuff.appspot.com/celeste/mod_dependency_graph.yaml?format=everestyaml', headers={
        'User-Agent': 'mons/' + '; gzip',
        'Accept-Encoding': 'gzip',
    })
    return yaml.safe_load(download_with_progress(request, None, 'Downloading Dependency Graph', clear=True, response_handler=gzip.open))

def search_mods(search):
    search = urllib.parse.quote_plus(search)
    url = f'https://max480-random-stuff.appspot.com/celeste/gamebanana-search?q={search}'
    response = urllib.request.urlopen(url)
    return yaml.safe_load(response.read())

def read_blacklist(path: str):
    with open(path) as file:
        return [m.strip() for m in file.readlines() if not m.startswith('#')]

def mod_placeholder(path: str):
    basename = os.path.basename(path)
    meta = None
    if os.path.isdir(path):
        meta = ModMeta({
            'Name': '_dir_' + basename,
            'Version': Version(0, 0, 0)
        })

    elif zipfile.is_zipfile(path):
        name = os.path.splitext(basename)[0]
        meta = ModMeta({
            'Name': '_zip_' + name,
            'Version': Version(0, 0, 0)
        })

    if meta:
        meta.Path = path
        return meta

    return None

def installed_mods(
    path: str,
    *,
    dirs: Optional[bool]=None,
    valid: Optional[bool]=None,
    blacklisted: Optional[bool]=None,
    with_size: bool=False,
    with_hash: bool=False,
) -> Iterator[ModMeta]:
    files = os.listdir(path)
    blacklist = None
    if os.path.isfile(os.path.join(path, 'blacklist.txt')):
        blacklist = read_blacklist(os.path.join(path, 'blacklist.txt'))
        if blacklisted is not None:
            files = list(filter(lambda m: blacklisted ^ (m in blacklist), files))
    elif blacklisted:
        files = []

    def _iter():
        for file in files:
            modpath = os.path.join(path, file)
            if dirs is not None:
                if dirs ^ bool(os.path.isdir(modpath)):
                    continue

            mod = read_mod_info(modpath, with_size=with_size, with_hash=with_hash)
            if valid is not None:
                if valid ^ bool(mod):
                    continue
            mod = mod or mod_placeholder(modpath)
            if not mod:
                continue
            if blacklist and file in blacklist:
                mod.Blacklisted = True
            yield mod
    return GeneratorWithLen(_iter(), len(files))

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