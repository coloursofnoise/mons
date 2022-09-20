import os
import typing as t
import zipfile

import xxhash
import yaml
from click import echo
from yaml.scanner import ScannerError

import mons.fs as fs
from mons.baseUtils import find
from mons.errors import EmptyFileError
from mons.version import Version


class _ModMeta_Base:
    def __init__(self, name: str, version: t.Union[str, Version]):
        self.Name = name
        if isinstance(version, str):
            version = Version.parse(version)
        self.Version = version

    @classmethod
    def _from_dict(cls, data: t.Dict[str, t.Any]):
        return cls(str(data["Name"]), str(data.get("Version", "NoVersion")))

    def __repr__(self) -> str:
        return f"{self.Name}: {self.Version}"


class _ModMeta_Deps:
    def __init__(
        self,
        dependencies: t.List[_ModMeta_Base],
        optionals: t.List[_ModMeta_Base],
    ):
        self.Dependencies = dependencies
        self.OptionalDependencies = optionals
        assert isinstance(self.Dependencies, t.List)

    @classmethod
    def parse(cls, data: t.Any):
        if isinstance(data, cls):
            return data
        elif isinstance(data, t.Dict):
            return cls._from_dict(data)
        elif isinstance(data, t.List):
            return cls(data, [])
        else:
            raise ValueError()

    @classmethod
    def _from_dict(cls, data: t.Dict[str, t.Any]):
        return cls(
            [
                _ModMeta_Base._from_dict(dep)  # pyright: ignore[reportPrivateUsage]
                for dep in data["Dependencies"]
            ],
            [
                _ModMeta_Base._from_dict(dep)  # pyright: ignore[reportPrivateUsage]
                for dep in data["OptionalDependencies"]
            ],
        )


class ModMeta(_ModMeta_Base, _ModMeta_Deps):
    Hash: t.Optional[str]
    Path: str
    Blacklisted: t.Optional[bool] = False

    def __init__(self, data: t.Dict[str, t.Any]):
        _ModMeta_Base.__init__(
            self, str(data["Name"]), str(data.get("Version", "NoVersion"))
        )
        _ModMeta_Deps.__init__(
            self,
            [_ModMeta_Base._from_dict(dep) for dep in data.get("Dependencies", [])],
            [
                _ModMeta_Base._from_dict(dep)
                for dep in data.get("OptionalDependencies", [])
            ],
        )
        self.DLL = str(data["DLL"]) if "DLL" in data else None
        self.Size = int(data["Size"]) if "Size" in data else 0

    @classmethod
    def placeholder(cls, path: str):
        basename = os.path.basename(path)
        meta = None
        if os.path.isdir(path):
            meta = cls({"Name": "_dir_" + basename, "Version": Version(0, 0, 0)})

        elif zipfile.is_zipfile(path):
            name = os.path.splitext(basename)[0]
            meta = cls({"Name": "_zip_" + name, "Version": Version(0, 0, 0)})

        if meta:
            meta.Path = path
            return meta

        return None


class ModDownload:
    def __init__(
        self,
        meta: t.Union[ModMeta, t.Dict[str, t.Any]],
        url: str,
        mirror: t.Optional[str] = None,
    ):
        if isinstance(meta, t.Dict):
            meta = ModMeta(meta)
        self.Meta = meta
        self.Url = url
        self.Mirror = mirror if mirror else url


def _merge_dependencies(dict: t.Dict[str, _ModMeta_Base], dep: _ModMeta_Base):
    if dep.Name in dict:
        if dep.Version.Major != dict[dep.Name].Version.Major:
            raise ValueError(
                "Incompatible dependencies encountered: "
                + f"{dep.Name} {dep.Version} vs {dep.Name} {dict[dep.Name].Version}"
            )
        elif dep.Version > dict[dep.Name].Version:
            dict[dep.Name] = dep
    else:
        dict[dep.Name] = dep


def recurse_dependencies(
    mods: t.Iterable[_ModMeta_Base],
    database: t.Dict[str, t.Any],
    dict: t.Dict[str, ModMeta],
):
    for mod in mods:
        _merge_dependencies(dict, mod)  # type: ignore
        if mod.Name in database:
            recurse_dependencies(
                _ModMeta_Deps.parse(database[mod.Name]).Dependencies, database, dict
            )


def combined_dependencies(
    mods: t.Iterable[_ModMeta_Base], database: t.Dict[str, t.Any]
) -> t.Dict[str, _ModMeta_Base]:
    deps = {}
    for mod in mods:
        dependencies = None
        if mod.Name in database:
            dependencies = _ModMeta_Deps.parse(database[mod.Name]).Dependencies
        elif isinstance(mod, _ModMeta_Deps):
            dependencies = mod.Dependencies
        if dependencies:
            recurse_dependencies(dependencies, database, deps)
    return deps


class UpdateInfo:
    def __init__(
        self, old: ModMeta, new: Version, url: str, mirror: t.Optional[str] = None
    ):
        self.Old = old
        self.New = new
        self.Url = url
        self.Mirror = mirror if mirror else url


def read_mod_info(mod: t.Union[str, t.IO[bytes]], with_size=False, with_hash=False):
    meta = None
    try:
        if not isinstance(mod, str) or os.path.isfile(mod) and zipfile.is_zipfile(mod):
            with zipfile.ZipFile(mod) as zip:
                everest_file = find(zip.namelist(), ("everest.yaml", "everest.yml"))
                if everest_file:
                    yml = yaml.safe_load(zip.read(everest_file).decode("utf-8-sig"))
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
            everest_file = fs.find_file(mod, ("everest.yaml", "everest.yml"))
            if everest_file:
                with open(
                    os.path.join(mod, everest_file), encoding="utf-8-sig"
                ) as file:
                    yml = yaml.safe_load(file)
                    if yml is None:
                        raise EmptyFileError()
                    meta = ModMeta(yml[0])
                meta.Size = fs.folder_size(mod) if with_size else 0
    except (EmptyFileError, ScannerError):
        return None
    except Exception:
        echo(mod)
        raise

    if meta:
        meta.Path = mod if isinstance(mod, str) else ""
    return meta
