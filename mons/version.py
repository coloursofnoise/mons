import typing as t
from dataclasses import dataclass


@dataclass(frozen=True)
class Version:
    Major: int
    Minor: int
    Build: int = -1
    Revision: int = -1
    Tag: str = ""

    @t.overload
    @classmethod
    def parse(cls, version: str) -> "Version":
        ...

    @t.overload
    @classmethod
    def parse(cls, version: None) -> None:
        ...

    @classmethod
    def parse(cls, version: t.Optional[str]) -> t.Optional["Version"]:
        if version is None:
            return None

        if not version or version.lower() in ["noversion", "none", "null"]:
            return NOVERSION()

        if version.isdigit():
            return cls(int(version), 0)

        # separate semver prerelease version and/or build metadata
        part = version.partition("-")
        if "+" in part[0]:
            part = "".join(part).partition("+")
        version, _, tag = part

        strArr = version.split(".")
        if 4 > len(strArr) < 2 or not all(n.isdigit() for n in strArr):
            raise ValueError("%s is not a valid Version string." % version)
        arr = list(map(int, strArr))
        arr += [-1] * (4 - len(arr))
        return cls(*arr, tag)  # type: ignore

    @classmethod
    def is_valid(cls, version: str):
        try:
            return not isinstance(cls.parse(version), NOVERSION)
        except ValueError:
            return False

    def satisfies(self, required: "Version"):
        """Checks if this version satisfies the :param:`required` version."""
        # Special case: Always True if version == 0.0.*
        if self.Major == 0 and self.Minor == 0:
            return True

        # Major version, breaking changes, must match.
        if self.Major != required.Major:
            return False
        # Minor version, non-breaking changes, installed can't be lower than what we depend on.
        if self.Minor < required.Minor:
            return False
        # "Build" is "PATCH" in semver, but we'll also check for it and "Revision".
        if self.Minor == required.Minor and self.Build < required.Build:
            return False
        if (
            self.Minor == required.Minor
            and self.Build == required.Build
            and self.Revision < required.Revision
        ):
            return False

        return True

    def supersedes(self, compare: "Version"):
        """Checks if this version is greater than :param:`compare`.

        Raises :type:`ValueError` if major versions differ.
        """
        if self.Major != compare.Major:
            raise ValueError(
                "Incompatible Major versions: {} != {}".format(
                    self.Major, compare.Major
                )
            )
        return self > compare

    def __str__(self):
        out = "{}.{}".format(self.Major, self.Minor)
        if self.Build != -1:
            out += ".{}".format(self.Build)
            if self.Revision != -1:
                out += ".{}".format(self.Revision)
        if self.Tag:
            out += "-{}".format(self.Tag)
        return out

    def __gt__(self, other: "Version"):
        if self.Major > other.Major:
            return True
        elif self.Major == other.Major and self.Minor > other.Minor:
            return True
        elif (
            self.Major == other.Major
            and self.Minor == other.Minor
            and self.Build > other.Build
        ):
            return True
        elif (
            self.Major == other.Major
            and self.Minor == other.Minor
            and self.Build == other.Build
            and self.Revision > other.Revision
        ):
            return True
        return False


class NOVERSION(Version):
    def __init__(self):
        super().__init__(0, 0)

    def satisfies(self, *_):
        return True

    def supersedes(self, *_):
        return False

    def __str__(self) -> str:
        return "NOVERSION"

    def __gt__(self, other):
        return False
