class Version:
    def __init__(self, major: int, minor: int, build: int=-1, revision: int=-1):
        self.Major = major
        self.Minor = minor
        self.Build = build
        self.Revision = revision

    @classmethod
    def parse(cls, version: str) -> 'Version':
        # discard semver prerelease version
        strArr = version.split('-', maxsplit=1)[0].split('.')
        if 4 > len(strArr) < 2 or not all(n.isdigit() for n in strArr):
            raise ValueError('%s is not a valid Version string' % version)
        arr = list(map(int, strArr))
        arr += [-1] * (4-len(arr))
        return Version(*arr)

    def satisfies(self, required: 'Version'):
        # Major version, breaking changes, must match.
        if self.Major != required.Major:
            return False
        # Minor version, non-breaking changes, installed can't be lower than what we depend on.
        if self.Minor < required.Minor:
            return False
        # "Build" is "PATCH" in semver, but we'll also check for it and "Revision".
        if self.Minor == required.Minor and self.Build < required.Build:
            return False
        if self.Minor == required.Minor and self.Build == required.Build and self.Revision < required.Revision:
            return False

        return True

    def __str__(self):
        out = '{0}.{1}'.format(self.Major, self.Minor)
        if self.Build != -1:
            out += '.{0}'.format(self.Build)
            if self.Revision != -1:
                out += '.{0}'.format(self.Revision)
        return out
