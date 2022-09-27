import operator as op

import pytest

from mons.version import Version


@pytest.mark.parametrize(
    ("version", "expect"),
    [
        ("NoVersion", Version(1, 0)),
        ("1.2.3.4", Version(1, 2, 3, 4)),
        ("1.2.3-pre", Version(1, 2, 3)),
    ],
)
def test_version_parse(version, expect):
    assert Version.parse(version) == expect


@pytest.mark.parametrize(
    ("version", "required", "expect"),
    [
        (Version(1, 2, 3, 4), Version(1, 2, 3, 4), True),
        (Version(1, 2, 3, 4), Version(1, 2, 3, 3), False),
        (Version(1, 2, 3, 4), Version(1, 3, 2, 4), True),
        (Version(1, 2, 3, 4), Version(2, 2, 3, 4), False),
    ],
)
def test_version_satisfies(version, required, expect):
    assert required.satisfies(version) == expect


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
