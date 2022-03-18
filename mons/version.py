class Version:
    def __init__(self, major: int, minor: int, build: int = -1, revision: int = -1):
        self.Major = major
        self.Minor = minor
        self.Build = build
        self.Revision = revision

    @classmethod
    def parse(cls, version: str) -> "Version":
        if version == "NoVersion":
            return Version(1, 0)

        # discard semver prerelease version
        strArr = version.split("-", maxsplit=1)[0].split(".")
        if 4 > len(strArr) < 2 or not all(n.isdigit() for n in strArr):
            raise ValueError("%s is not a valid Version string" % version)
        arr = list(map(int, strArr))
        arr += [-1] * (4 - len(arr))
        return Version(*arr)

    def satisfies(self, required: "Version"):
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

    def __str__(self):
        out = "{}.{}".format(self.Major, self.Minor)
        if self.Build != -1:
            out += ".{}".format(self.Build)
            if self.Revision != -1:
                out += ".{}".format(self.Revision)
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
