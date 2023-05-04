import os
import typing as t
from dataclasses import dataclass
from dataclasses import field

import typing_extensions as te

from mons import fs
from mons.utils import getMD5Hash
from mons.utils import parseExeInfo
from mons.utils import VANILLA_HASH
from mons.version import NOVERSION
from mons.version import Version


@dataclass
class Install:
    name: str
    path: fs.File

    @property
    def dir(self):
        return fs.dirname(self.path)

    _cache: t.Dict[str, t.Any] = field(default_factory=dict, init=False)

    def get_cache(self):
        return self._cache

    @property
    def hash(self) -> t.Optional[str]:
        return self._cache.get("hash", None)

    @hash.setter
    def hash(self, value: t.Optional[str]):
        self._cache["hash"] = value

    @property
    def celeste_version(self):
        return Version.parse(self._cache.get("celeste_version", None))

    @celeste_version.setter
    def celeste_version(self, value: t.Optional[Version]):
        self._cache["celeste_version"] = value and str(value)

    @property
    def everest_version(self):
        version = self._cache.get("everest_version", None)
        return Version.parse(version) if version else None

    @everest_version.setter
    def everest_version(self, value: t.Optional[Version]):
        self._cache["everest_version"] = value and str(value)

    @property
    def framework(self):
        framework = str(self._cache.get("framework", "").upper())
        if framework == "FNA" or framework == "XNA":
            return framework
        return None

    @framework.setter
    def framework(self, value: t.Optional[te.Literal["FNA", "XNA"]]):
        self._cache["framework"] = value

    _cache_loader: t.Optional[t.Callable[["Install"], bool]] = field(default=None)

    def version_string(self):
        self.update_cache(read_exe=True)

        version_str = str(self.celeste_version) or "unknown"
        if self.framework:
            version_str += f"-{self.framework.upper()}"

        if isinstance(self.everest_version, NOVERSION):
            version_str += f" + Everest(unknown version)"
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
            self._cache.update(data)

        hash = getMD5Hash(self.path)
        if self.hash == hash:
            # Cache is up to date
            return

        if self._cache_loader and self._cache_loader(self):
            return

        self.hash = hash
        self.celeste_version = None
        self.everest_version = None
        has_everest = False

        version = VANILLA_HASH.get(hash, None)
        if version:
            self.celeste_version, self.framework = version
            self.everest_version = None
        else:
            orig_path = os.path.join(os.path.dirname(self.path), "orig", "Celeste.exe")
            if fs.isfile(orig_path):
                orig_hash = getMD5Hash(orig_path)
                self.celeste_version, self.framework = VANILLA_HASH.get(
                    orig_hash, (None, None)
                )
                has_everest = True

        if read_exe and has_everest:
            self.everest_version, self.framework = parseExeInfo(self.path)
