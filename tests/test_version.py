import operator as op

import pytest

from mons.version import NOVERSION
from mons.version import Version


@pytest.mark.parametrize(
    ("version", "expect"),
    [
        pytest.param(None, None, id="None = None"),
        pytest.param("NoVersion", NOVERSION(), id='"NoVersion" = NOVERSION'),
        pytest.param("1.2.3.4", Version(1, 2, 3, 4), id='"1.2.3.4" = 1.2.3.4'),
        pytest.param(
            "1.2.3-pre", Version(1, 2, 3, Tag="pre"), id='"1.2.3-pre" = 1.2.3-pre'
        ),
        pytest.param(
            "1.2.3+meta", Version(1, 2, 3, Tag="meta"), id='"1.2.3+meta" = 1.2.3+meta'
        ),
    ],
)
def test_version_parse(version, expect):
    assert str(Version.parse(version)) == str(expect)


@pytest.mark.parametrize(
    ("version", "required"),
    [
        pytest.param(Version(1, 2, 3, 4), Version(1, 2, 3, 4), id="equal"),
        pytest.param(Version(2, 2), Version(2, 1), id="minor"),
        pytest.param(Version(1, 2, 3, 1), Version(1, 2, 3, 0), id="revision"),
        pytest.param(Version(0, 0), Version(5, 1), id="0.0.0"),
    ],
)
def test_version_satisfies(version, required):
    assert version.satisfies(required)


@pytest.mark.parametrize(
    ("version", "required"),
    [
        pytest.param(Version(1, 1, 1, 0), Version(1, 1, 1, 1), id="revision"),
        pytest.param(Version(1, 2, 3, 4), Version(1, 3, 2, 4), id="minor"),
        pytest.param(Version(1, 0), Version(2, 0), id="major"),
    ],
)
def test_version_satisfies_fail(version, required):
    assert not version.satisfies(required)


@pytest.mark.parametrize(
    ("left", "right", "comparison"),
    [
        (Version(1, 2, 3, 4), Version(1, 2, 3, 4), op.eq),
        (Version(1, 2, 3, 4), Version(1, 0, 0, 0), op.ne),
        (Version(1, 2, 3, 4), Version(1, 2, 3, 3), op.gt),
        (Version(1, 2, 3, 4), Version(1, 3, 3, 4), op.lt),
    ],
)
def test_version_compare(left, right, comparison):
    assert comparison(left, right)
