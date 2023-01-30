import errno
import hashlib
import json
import os
import re
import time
import typing as t
import urllib.parse
import urllib.request
import zipfile
from contextlib import contextmanager
from urllib.error import HTTPError

import dnfile  # https://github.com/malwarefrank/dnfile
import urllib3
import yaml
from click import echo
from pefile import DIRECTORY_ENTRY  # https://github.com/erocarrera/pefile
from tqdm import tqdm

from mons.baseUtils import GeneratorWithLen
from mons.downloading import download_with_progress
from mons.modmeta import ModMeta
from mons.modmeta import read_mod_info


VANILLA_HASH: t.Dict[str, t.Tuple[str, str]] = {
    "f1c4967fa8f1f113858327590e274b69": ("1.4.0.0", "FNA"),
    "107cd146973f2c5ec9fb0b4f81c1588a": ("1.4.0.0", "XNA"),
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


def find_celeste_file(path: str, file: str, force_name=True):
    if os.path.basename(path) == "Celeste.app":
        path = os.path.join(path, "Resources")

    ret = path
    if os.path.isdir(path):
        ret = os.path.join(path, file)
        if not os.path.exists(ret):
            raise FileNotFoundError(
                errno.ENOENT, f"File `{file}` could not be found in `{path}`", ret
            )
    elif force_name and not os.path.basename(path) == file:
        raise FileNotFoundError(errno.ENOENT, f"File `{file}` not found", path)
    return ret


def getMD5Hash(path: str):
    with open(path, "rb") as f:
        file_hash = hashlib.md5()
        chunk = f.read(8129)
        while chunk:
            file_hash.update(chunk)
            chunk = f.read(8129)
    return file_hash.hexdigest()


def unpack(zip: zipfile.ZipFile, root: str, prefix="", label="Extracting"):
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


def parseExeInfo(path: str):
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

    return hasEverest, everestBuild, framework


def parseVersionSpec(string: str):
    if string.startswith("1.") and string.endswith(".0"):
        string = string[2:-2]
    if string.isdigit():
        buildnumber = int(string)
    else:
        buildnumber = latest_build(string)

    return buildnumber


def latest_build(branch: str):
    if branch.startswith(("refs/heads/", "refs/pull/")):
        return latest_build_azure(branch)

    build_list = get_build_list()
    for build in build_list:
        if not branch or build["branch"] == branch:
            return int(build["version"])

    return None


def latest_build_azure(branch: str):
    response: urllib3.HTTPResponse = urllib3.PoolManager().request(
        "GET",
        "https://dev.azure.com/EverestAPI/Everest/_apis/build/builds",
        fields={
            "definitions": 3,
            "statusFilter": "completed",
            "resultFilter": "succeeded",
            "branchName": branch
            if branch == "" or branch.startswith(("refs/heads/", "refs/pull/"))
            else "refs/heads/" + branch,
            "api-version": 6.0,
            "$top": 1,
        },
    )

    data: t.Dict[str, t.Any] = json.loads(response.data.decode())
    if data["count"] < 1:
        return None
    elif data["count"] > 1:
        raise Exception("Unexpected number of builds: " + str(data["count"]))

    build = data["value"][0]
    id = build["id"]
    try:
        return int(id) + 700
    except:
        pass
    return None


def build_exists(build: int):
    build_list = get_build_list()
    if build in (int(b["version"]) for b in build_list):
        return True

    return build_exists_azure(build)


def build_exists_azure(build: int):
    try:
        urllib.request.urlopen(
            "https://dev.azure.com/EverestAPI/Everest/_apis/build/builds/"
            + str(build - 700)
        )
        return True
    except HTTPError as err:
        if err.code == 404:
            return False
        raise


updateURLLookup = {
    "main": "mainDownload",
    "olympus-meta": "olympusMetaDownload",
    "olympus-build": "olympusBuildDownload",
}


def fetch_build_artifact(build: int, artifactName: str) -> urllib3.HTTPResponse:
    build_list = get_build_list()
    for b in build_list:
        if build == int(b["version"]):
            return urllib3.PoolManager().request(
                "GET", b[updateURLLookup[artifactName]], preload_content=False
            )

    return fetch_build_artifact_azure(build, artifactName)


def fetch_build_artifact_azure(
    build: int, artifactName="olympus-build"
) -> urllib3.HTTPResponse:
    return urllib3.PoolManager().request(
        "GET",
        f"https://dev.azure.com/EverestAPI/Everest/_apis/build/builds/{build - 700}/artifacts",
        fields={
            "artifactName": artifactName,
            "api-version": 6.0,
            "$format": "zip",
        },
        preload_content=False,
    )


build_list = None


def get_build_list() -> t.List[t.Dict[str, t.Any]]:
    global build_list
    if build_list:
        return build_list

    update_url = (
        urllib.request.urlopen("https://everestapi.github.io/everestupdater.txt")
        .read()
        .decode()
        .strip()
    )

    build_list = yaml.safe_load(
        download_with_progress(update_url, None, "Downloading Build List", clear=True)
    )
    return build_list


mod_list = None


def get_mod_list() -> t.Dict[str, t.Any]:
    global mod_list
    if mod_list:
        return mod_list

    update_url = (
        urllib.request.urlopen("https://everestapi.github.io/modupdater.txt")
        .read()
        .decode()
        .strip()
    )
    mod_list = yaml.safe_load(
        download_with_progress(
            update_url,
            None,
            "Downloading Update List",
            clear=True,
        )
    )
    return mod_list


dependency_graph = None


def get_dependency_graph() -> t.Dict[str, t.Any]:
    global dependency_graph
    if dependency_graph:
        return dependency_graph

    dependency_graph = yaml.safe_load(
        download_with_progress(
            "https://max480-random-stuff.appspot.com/celeste/mod_dependency_graph.yaml?format=everestyaml",
            None,
            "Downloading Dependency Graph",
            clear=True,
        )
    )
    return dependency_graph


def search_mods(search: str):
    search = urllib.parse.quote_plus(search)
    url = (
        f"https://max480-random-stuff.appspot.com/celeste/gamebanana-search?q={search}"
    )
    response = urllib.request.urlopen(url)
    return json.loads(response.read())


def read_blacklist(path: str):
    with open(path) as file:
        return [m.strip() for m in file.readlines() if not m.startswith("#")]


def installed_mods(
    path: str,
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
        blacklist = read_blacklist(os.path.join(path, "blacklist.txt"))
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
