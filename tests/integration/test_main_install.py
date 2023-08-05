import logging

import pytest
from click import ClickException

from mons.commands import main
from mons.version import Version


@pytest.mark.parametrize(
    "mock_filesystem",
    [
        pytest.param({}, id="empty_fs"),
        pytest.param(
            {"proj_1": ["unrelated.py", "different.csproj", "bin/"]},
            id="no_matching_csproj",
        ),
    ],
    indirect=True,
)
def test_determine_configuration_no_projects(mock_filesystem):
    with pytest.raises(ClickException, match="No projects found"):
        main.determine_configuration(mock_filesystem)


# These both result in the same error, but from different places
@pytest.mark.parametrize(
    "mock_filesystem",
    [
        pytest.param(
            {
                "proj_1": [
                    "proj_1.csproj",
                ]
            },
            id="no bin/",
        ),
        pytest.param({"proj_1": ["proj_1.csproj", "bin/"]}, id="empty bin/"),
    ],
    indirect=True,
)
def test_determine_configuration_no_artifacts(mock_filesystem):
    with pytest.raises(ClickException, match="No build artifacts"):
        main.determine_configuration(mock_filesystem)


@pytest.mark.mock_filesystem(
    {
        "proj_1": ["proj_1.csproj", {"bin": {"DEBUG": {"net452": "assembly.dll"}}}],
        "proj_2": ["proj_2.csproj", {"bin": {"DEBUG": {"core": "assembly.dll"}}}],
    }
)
def test_determine_configuration_no_common(caplog, mock_filesystem):
    assert main.determine_configuration(mock_filesystem) is None
    assert "No common output" in caplog.text


@pytest.mark.mock_filesystem(
    {
        "proj_1": [
            "proj_1.csproj",
            {
                "bin": {
                    "DEBUG": {
                        "common": "assembly.dll",
                        "other": "assembly.dll",
                    },
                    "RELEASE": {"net452": "assembly.dll"},
                }
            },
        ],
        "proj_2": [
            "proj_2.csproj",
            {
                "bin": {
                    "DEBUG": {"common": "assembly.dll"},
                    "RELEASE": {
                        "net452": "assembly.dll",
                        "other": "assembly.dll",
                    },
                }
            },
        ],
    }
)
def test_determine_configuration_most_recent(caplog, mock_filesystem):
    with caplog.at_level(logging.DEBUG, main.__name__):
        assert main.determine_configuration(mock_filesystem) == "RELEASE/net452"
        assert "Most recent" in caplog.text


@pytest.mark.mock_filesystem(
    {
        "proj_1": [
            "proj_1.csproj",
            {
                "bin": {
                    "DEBUG": {
                        "common": "assembly.dll",
                        "other": "assembly.dll",
                    },
                    "RELEASE": {"net452": "assembly.dll"},
                }
            },
        ],
        "proj_2": [
            "proj_2.csproj",
            {
                "bin": {
                    "DEBUG": {"common": "assembly.dll"},
                    "RELEASE": {
                        "other": "assembly.dll",
                    },
                }
            },
        ],
    }
)
def test_determine_configuration_one_shared(caplog, mock_filesystem):
    with caplog.at_level(logging.DEBUG, main.__name__):
        assert main.determine_configuration(mock_filesystem) == "DEBUG/common"
        assert "Only one" in caplog.text


def fetch_build_list(*args):
    builds = [
        {"branch": "dev", "version": 36},
        {"branch": "beta", "version": 35},
        {"branch": "dev", "version": 27},
        {"branch": "dev", "version": 26},
        {"branch": "beta", "version": 25},
        {"branch": "stable", "version": 20},
        {"branch": "dev", "version": 11},
        {"branch": "stable", "version": 10},
    ]
    for build in builds:
        build["mainDownload"] = ""
        build["mainFileSize"] = 0
    return builds


def fetch_latest_build_azure(source):
    if source == "refs/unknown":
        return None
    return 5


def fetch_build_artifact_azure(build):
    return ""


def build(build: int):
    return Version(1, build, 0)


@pytest.mark.parametrize(
    ("source", "result"),
    [
        pytest.param(build(20), build(20), id="stable version"),
        pytest.param(build(25), build(35), id="beta version"),
        # This test should pass, but currently only the minor version number is
        # checked anyways.
        pytest.param(Version(1, 20, 0, Tag="-beta+azure"), build(20)),
        pytest.param("http://test.domain/file.zip", None, id="url"),
        pytest.param(None, build(36), id="latest"),
        pytest.param("refs/heads/stable", build(5), id="azure"),
        pytest.param("stable", build(20)),
        pytest.param("beta", build(35)),
        pytest.param("27", build(27)),
        pytest.param("1.20.0", build(20)),
    ],
)
def test_fetch_artifact_source(ctx, source, result):
    version, _ = main.fetch_artifact_source(ctx, source)
    assert version == result


@pytest.mark.parametrize(
    "source",
    [
        # Currently only the minor version number is checked.
        pytest.param(Version(2, 10, 7, 2), marks=pytest.mark.xfail(strict=True)),
        ("refs/unknown"),
        ("unknown_string"),
        ("99"),
        ("NOVERSION"),
        # See above
        pytest.param("4.25.8+github", marks=pytest.mark.xfail(strict=True)),
    ],
)
def test_fetch_artifact_source_fail(ctx, source):
    with pytest.raises(NotImplementedError):
        main.fetch_artifact_source(ctx, source)


# This occurrs when no VERSIONSPEC is supplied and the current
# Everest branch cannot be determined
def test_fetch_artifact_source_unknown_branch(ctx):
    with pytest.raises(ClickException, match="Could not determine"):
        main.fetch_artifact_source(ctx, build(99))
