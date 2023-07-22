import os
import typing as t
import zipfile

import xxhash
import yaml
from yaml.scanner import ScannerError

from mons import fs
from mons.baseUtils import find
from mons.errors import EmptyFileError
from mons.version import NOVERSION
from mons.version import Version


class ModMeta_Base:
    """Mod Name and Version"""

    def __init__(self, name: str, version: t.Union[str, Version]):
        self.Name = name
        if isinstance(version, str):
            version = Version.parse(version)
        self.Version = version

    @classmethod
    def _from_dict(cls, data: t.Dict[str, t.Any]):
        return cls(str(data["Name"]), str(data.get("Version", NOVERSION)))

    def __repr__(self) -> str:
        return f"{self.Name}: {self.Version}"


class ModMeta_Deps:
    """Mod Dependencies and Optional Dependencies"""

    def __init__(
        self,
        dependencies: t.List[ModMeta_Base],
        optionals: t.List[ModMeta_Base],
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
                ModMeta_Base._from_dict(dep)  # pyright: ignore[reportPrivateUsage]
                for dep in data["Dependencies"]
            ],
            [
                ModMeta_Base._from_dict(dep)  # pyright: ignore[reportPrivateUsage]
                for dep in data["OptionalDependencies"]
            ],
        )


class ModMeta(ModMeta_Base, ModMeta_Deps):
    """Combination of :type:`ModMeta_Base` and :type:`ModMeta_Deps`"""

    Hash: t.Optional[str]
    Path: str = ""
    Blacklisted: t.Optional[bool] = False

    def __init__(self, data: t.Dict[str, t.Any]):
        ModMeta_Base.__init__(
            self, str(data["Name"]), str(data.get("Version", "NoVersion"))
        )
        ModMeta_Deps.__init__(
            self,
            [ModMeta_Base._from_dict(dep) for dep in data.get("Dependencies", [])],
            [
                ModMeta_Base._from_dict(dep)
                for dep in data.get("OptionalDependencies", [])
            ],
        )
        self.DLL = str(data["DLL"]) if "DLL" in data else None
        self.Size = int(data["Size"]) if "Size" in data else 0

    @classmethod
    def placeholder(cls, path: fs.Path):
        basename = os.path.basename(path)
        meta = None
        if fs.isdir(path):
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

    @property
    def Size(self):
        return self.Meta.Size

    def __str__(self) -> str:
        return str(self.Meta)


class UpdateInfo:
    def __init__(
        self,
        meta: ModMeta,
        new: Version,
        url: str,
        mirror: t.Optional[str] = None,
        size=0,
    ):
        self.Meta = meta
        self.New = new
        self.Url = url
        self.Mirror = mirror if mirror else url
        self._size = size

    @property
    def Size(self):
        return self._size and self._size - self.Meta.Size

    @property
    def New_Meta(self):
        return ModMeta_Base(self.Meta.Name, self.New)

    def __str__(self) -> str:
        return str(self.Meta) + " -> " + str(self.New)


def read_mod_info(mod: t.Union[str, t.IO[bytes]], folder_size=False, with_hash=False):
    meta = None
    try:
        if not isinstance(mod, str) or fs.isfile(mod) and zipfile.is_zipfile(mod):
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
                        meta.Size = zip.fp.tell()

        elif fs.isdir(mod):
            everest_file = fs.find_file(mod, ("everest.yaml", "everest.yml"))
            if everest_file:
                with open(
                    os.path.join(mod, everest_file), encoding="utf-8-sig"
                ) as file:
                    yml = yaml.safe_load(file)
                    if yml is None:
                        raise EmptyFileError()
                    meta = ModMeta(yml[0])
                meta.Size = fs.folder_size(mod) if folder_size else 0
    except (EmptyFileError, ScannerError):
        return None
    except Exception:
        return None

    if meta:
        meta.Path = mod if isinstance(mod, str) else ""
    return meta
