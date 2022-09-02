import os
import typing as t
from configparser import SectionProxy
from pydoc import classname

from mons.utils import getMD5Hash
from mons.utils import parseExeInfo
from mons.utils import VANILLA_HASH


class Install:

    DEFAULTS: t.Dict[str, str]

    def __init__(
        self, name: str, path: str, cache: t.Optional[SectionProxy] = None, data=None
    ) -> None:
        self.name = name
        assert os.path.exists(path)
        self.path = path
        self.cache = cache or dict()
        self.data: t.Dict[str, str] = data or dict()

    def update_cache(self, read_exe=True):
        hash = getMD5Hash(self.path)
        if self.cache.get("Hash", "") == hash:
            # Cache is up to date
            return

        self.cache["Hash"] = hash
        self.cache["Everest"] = str(True)
        self.cache["CelesteVersion"] = ""

        version = VANILLA_HASH.get(hash, None)
        if version:
            self.cache["CelesteVersion"], self.cache["Framework"] = version
            self.cache["Everest"] = str(False)

        else:
            orig_path = os.path.join(os.path.dirname(self.path), "orig", "Celeste.exe")
            if os.path.isfile(orig_path):
                orig_hash = getMD5Hash(orig_path)
                version = VANILLA_HASH.get(orig_hash, None)
                if version:
                    self.cache["CelesteVersion"], self.cache["Framework"] = version
                    # If orig_hash is known but hash is not, then Celeste.exe has been modified
                    self.cache["Everest"] = str(True)

        if read_exe and self.cache["Everest"]:
            (
                self.cache["Everest"],
                self.cache["EverestBuild"],
                self.cache["Framework"],
            ) = map(str, parseExeInfo(self.path))

    def version_string(self):
        self.update_cache(read_exe=False)

        versionStr = self.cache.get("CelesteVersion", "unknown")
        framework = self.cache.get("Framework", None)
        if framework:
            versionStr += f"-{framework.lower()}"
        everestBuild = self.cache.get("EverestBuild", None)
        if everestBuild:
            versionStr += f" + 1.{everestBuild}.0"
        elif str(self.cache.get("Everest", None)) == "True":
            versionStr += " + Everest(unknown version)"
        return versionStr

    def get_cache(self):
        self.update_cache()
        return self.cache

    def __setitem__(self, name, value):
        self.data[name] = value

    def __getitem__(self, name):
        return self.data.get(name, "") or Install.DEFAULTS.get(name, "")

    def serialize(self):
        return {**self.data, "path": self.path}
