import os
import typing as t
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from string import Formatter

from mons import fs
from mons.utils import find_celeste_asm
from mons.utils import getMD5Hash
from mons.utils import parseExeInfo
from mons.utils import VANILLA_HASH
from mons.version import NOVERSION
from mons.version import Version


@dataclass
class Install:
    name: str
    path: fs.Directory
    overlay_base: t.Optional[fs.Directory] = None

    @property
    def asm(self):
        return find_celeste_asm(self.path)

    @property
    def mod_folder(self):
        return fs.joindir(self.path, "Mods")

    _cache: t.Dict[str, t.Any] = field(default_factory=dict, init=False)

    def _set_cache_value(self, key, value):
        if value is not None:
            self._cache[key] = value
        elif key in self._cache:
            del self._cache[key]

    def get_cache(self):
        return self._cache

    @property
    def hash(self) -> t.Optional[str]:
        return self._cache.get("hash", None)

    @hash.setter
    def hash(self, value: t.Optional[str]):
        self._set_cache_value("hash", value)

    @property
    def celeste_version(self):
        return Version.parse(self._cache.get("celeste_version", None))

    @celeste_version.setter
    def celeste_version(self, value: t.Optional[Version]):
        self._set_cache_value("celeste_version", value and str(value))

    @property
    def everest_version(self) -> t.Optional[Version]:
        version: t.Optional[str] = self._cache.get("everest_version", None)
        return Version.parse(version) if version else None

    @everest_version.setter
    def everest_version(self, value: t.Optional[Version]):
        self._set_cache_value("everest_version", value and str(value))

    @property
    def framework(self):
        framework = str(self._cache.get("framework", "").upper())
        if framework == "FNA" or framework == "XNA":
            return framework
        return None

    @framework.setter
    def framework(self, value: t.Optional[t.Literal["FNA", "XNA"]]):
        self._set_cache_value("framework", value)

    _cache_loader: t.Optional[t.Callable[["Install"], bool]] = field(default=None)

    def version_string(self):
        self.update_cache(read_exe=True)

        version_str = str(self.celeste_version) or "unknown"
        if self.framework:
            version_str += f"-{self.framework.upper()}"

        if isinstance(self.everest_version, NOVERSION):
            version_str += " + Everest(unknown version)"
        elif self.everest_version:
            version_str += f" + {self.everest_version}"

        return version_str

    @t.overload
    def update_cache(self, data: t.Dict[str, t.Any]):
        ...

    @t.overload
    def update_cache(self, *, read_exe: bool):
        ...

    def update_cache(
        self, data: t.Optional[t.Dict[str, t.Any]] = None, *, read_exe: bool = False
    ):
        if data:
            for attr, val in data.items():
                self._set_cache_value(attr, val)

        hash = getMD5Hash(self.asm)
        if self.hash == hash:
            # Cache is up to date
            return

        if self._cache_loader and self._cache_loader(self) and self.hash == hash:
            return

        # If updating the cache gets interrupted, don't leave it partially populated.
        new_data = self._cache.copy()

        new_data.update(
            {"hash": hash, "celeste_version": None, "everest_version": None}
        )
        has_everest = False

        version = VANILLA_HASH.get(hash, None)
        if version:
            new_data["celeste_version"], new_data["framework"] = version
            new_data["everest_version"] = None
        else:
            orig_path = os.path.join(self.path, "orig", "Celeste.exe")
            if fs.isfile(orig_path):
                orig_hash = getMD5Hash(orig_path)
                new_data["celeste_version"], new_data["framework"] = VANILLA_HASH.get(
                    orig_hash, (None, None)
                )
                has_everest = True

        if read_exe and has_everest:
            new_data["everest_version"], new_data["framework"] = parseExeInfo(self.asm)

        for attr, val in new_data.items():
            self._set_cache_value(attr, val and str(val))

    def __str__(self) -> str:
        return f"{self.name} {self.version_string()}"

    def __format__(self, format_spec: str):
        if not format_spec:
            return super().__format__(format_spec)
        data = asdict(self)
        format_fields = [f[1] for f in Formatter().parse(format_spec) if f[1]]
        if "version_string" in format_fields:
            data["version_string"] = self.version_string()
        if "version" in format_fields:
            data["version"] = self.version_string()
        return format_spec.format_map(data)
