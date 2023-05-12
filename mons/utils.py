import errno
import hashlib
import os
import re
import time
import typing as t
import urllib.parse
import urllib.request
import zipfile
from contextlib import contextmanager

import dnfile  # https://github.com/malwarefrank/dnfile
from click import echo
from pefile import (  # pyright:ignore[reportMissingTypeStubs]
    DIRECTORY_ENTRY,
)  # https://github.com/erocarrera/pefile
from tqdm import tqdm

from mons import fs
from mons.baseUtils import GeneratorWithLen
from mons.modmeta import ModMeta
from mons.modmeta import read_mod_info
from mons.version import NOVERSION
from mons.version import Version


VANILLA_HASH: t.Dict[str, t.Tuple[Version, t.Literal["FNA", "XNA"]]] = {
    "f1c4967fa8f1f113858327590e274b69": (Version(1, 4, 0, 0), "FNA"),
    "107cd146973f2c5ec9fb0b4f81c1588a": (Version(1, 4, 0, 0), "XNA"),
}


@contextmanager
def timed_progress(msg: str):
    """Times execution of the current context, then prints :param:`msg` with :func:`tqdm.write`.

    :param msg: Message to be printed. Formatted with a `time` kwarg."""
    start = time.perf_counter()
    yield
    end = time.perf_counter()
    # Carriage return ensures msg is printed properly even after multiple progress bars
    tqdm.write("\r" + msg.format(time=end - start))


def find_celeste_asm(path: fs.Path):
    if fs.isfile(path):
        if os.path.basename(path) == "Celeste.exe":
            return path

        if os.uname().sysname != "nt" and os.path.basename(path) == "Celeste.dll":
            return path

    elif fs.isdir(path):
        if os.path.basename(path) == "Celeste.app":
            path = fs.joindir(path, "Resources")

        if fs.isfile(os.path.join(path, "Celeste.exe")):
            return fs.joinfile(path, "Celeste.exe")

        if os.uname().sysname != "nt" and fs.isfile(os.path.join(path, "Celeste.dll")):
            return fs.joinfile(path, "Celeste.dll")

    raise FileNotFoundError(
        errno.ENOENT,
        f"'{'Celeste.exe' if os.uname().sysname == 'nt' else 'Celeste.exe or Celeste.dll'}' could not be found in '{path}'",
        path,
    )


def getMD5Hash(path: fs.File):
    with open(path, "rb") as f:
        file_hash = hashlib.md5()
        chunk = f.read(8129)
        while chunk:
            file_hash.update(chunk)
            chunk = f.read(8129)
    return file_hash.hexdigest()


def unpack(zip: zipfile.ZipFile, root: fs.Directory, prefix="", label="Extracting"):
    totalSize = 0
    for zipinfo in zip.infolist():
        if not prefix or zipinfo.filename.startswith(prefix):
            totalSize += zipinfo.file_size

    with tqdm(total=totalSize, desc=label, leave=False) as bar:
        for zipinfo in zip.infolist():
            if not zipinfo.filename or zipinfo.filename.endswith("/"):
                continue

            if prefix:
                if not zipinfo.filename.startswith(prefix):
                    continue
                zipinfo.filename = zipinfo.filename[len(prefix) :]

            zip.extract(zipinfo, root)
            bar.update(zipinfo.file_size)


class EverestHandler(urllib.request.BaseHandler):
    def everest_open(self, req: urllib.request.Request):
        parsed_url = urllib.parse.urlparse(req.full_url)
        gb_url = re.match("^(https://gamebanana.com/mmdl/.*),.*,.*$", parsed_url.path)
        download_url = gb_url[1] if gb_url else parsed_url.path
        req.full_url = download_url
        return self.parent.open(req)


opener = urllib.request.build_opener(EverestHandler)
opener.addheaders = [
    (
        "User-Agent",
        "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/36.0.1941.0 Safari/537.36",
    )
]
urllib.request.install_opener(opener)


def parseExeInfo(path: fs.File):
    echo("Reading exe...\r", nl=False)
    pe = dnfile.dnPE(path, fast_load=True)
    pe.parse_data_directories(
        directories=DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR"]
    )

    assert pe.net

    stringHeap: dnfile.stream.StringsHeap = pe.net.metadata.streams_list[1]  # type: ignore

    hasEverest = False
    everestBuild = None

    heapSize = stringHeap.sizeof()
    i = 0
    with tqdm(total=heapSize, desc="Scanning exe", leave=False) as bar:
        while i < len(stringHeap.__data__):
            string = stringHeap.get(i)
            if string is None:
                break
            string = str(string)
            if string == "EverestModule":
                hasEverest = True
            if string.startswith("EverestBuild"):
                everestBuild = string[len("EverestBuild") :]
                hasEverest = True
                break
            inc = max(len(string), 1)
            i += inc
            bar.update(inc)

    assemRef = pe.net.mdtables.AssemblyRef
    assert assemRef
    framework = "FNA" if any(row.Name == "FNA" for row in assemRef.rows) else "XNA"

    if everestBuild:
        return Version(1, int(everestBuild), 0), framework
    if hasEverest:
        return NOVERSION(), framework

    return None, framework


def parse_build_number(string: str):
    if string.startswith("1.") and string.endswith(".0"):
        string = string[2:-2]
    if string.isdigit():
        buildnumber = int(string)
    else:
        buildnumber = None

    return buildnumber


def read_blacklist(path: fs.File):
    with open(path) as file:
        return [m.strip() for m in file.readlines() if not m.startswith("#")]


def installed_mods(
    path: fs.Directory,
    *,
    dirs: t.Optional[bool] = None,
    valid: t.Optional[bool] = None,
    blacklisted: t.Optional[bool] = None,
    with_size=False,
    with_hash=False,
) -> t.Iterator[ModMeta]:
    files = os.listdir(path)
    blacklist = None
    if os.path.isfile(os.path.join(path, "blacklist.txt")):
        blacklist = read_blacklist(fs.joinfile(path, "blacklist.txt"))
        if blacklisted is not None:
            files = list(filter(lambda m: blacklisted ^ (m in blacklist), files))
    elif blacklisted:
        files = []

    def _iter():
        for file in files:
            modpath = fs.joinpath(path, file)
            if dirs is not None:
                if dirs ^ bool(fs.isdir(modpath)):
                    continue

            mod = read_mod_info(modpath, with_size=with_size, with_hash=with_hash)
            if valid is not None:
                if valid ^ bool(mod):
                    continue
            mod = mod or ModMeta.placeholder(modpath)
            if not mod:
                continue
            if blacklist and file in blacklist:
                mod.Blacklisted = True
            yield mod

    return GeneratorWithLen(_iter(), len(files))


def enable_mods(path: str, *mods: str):
    blacklist_path = os.path.join(path, "blacklist.txt")
    if os.path.isfile(blacklist_path):
        with open(blacklist_path) as file:
            blacklist = file.readlines()
        i = 0
        while i < len(blacklist):
            if blacklist[i].strip() in mods:
                blacklist[i] = "#" + blacklist[i]
            i += 1
        with open(blacklist_path, mode="w") as file:
            file.writelines(blacklist)
