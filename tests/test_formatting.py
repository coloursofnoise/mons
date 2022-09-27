import pytest

from mons.formatting import *


@pytest.mark.parametrize("input, expected", [(1299999, "1.2 MiB")])
def test_format_bytes(input, expected):
    assert format_bytes(input) == expected


@pytest.mark.parametrize(
    "input, expected",
    [
        (
            {"foo": "value", "bar": "value"},
            """
foo\tvalue
bar\tvalue
""".strip(),
        ),
        (
            {"foo": "value", "foobarbaz": "value"},
            """
foo      \tvalue
foobarbaz\tvalue
""".strip(),
        ),
        ({}, ""),
    ],
)
def test_format_columns(input, expected):
    assert format_columns(input) == expected
