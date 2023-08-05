import os
import typing as t
import zipfile

import pytest
import yaml

import mons.commands.mods
import mons.install
from mons.mons import cli as mons_cli


@pytest.fixture(autouse=True)
def temp_mod_folder(monkeypatch, tmp_path):
    mod_folder = os.path.join(tmp_path, "Mods")
    os.mkdir(mod_folder)
    monkeypatch.setattr(mons.install.Install, "mod_folder", mod_folder)
    return mod_folder


mod_db = {}
dep_graph = {}
installed_mods: t.Dict[str, t.Dict[str, str]] = {}


@pytest.fixture(autouse=True)
def fake_mod_db(monkeypatch, temp_mod_folder):
    monkeypatch.setattr(mons.commands.mods, "fetch_mod_db", lambda *args: mod_db)
    monkeypatch.setattr(
        mons.commands.mods, "fetch_dependency_graph", lambda *args: dep_graph
    )


def fake_mod_db_request(request, temp_mod_folder, monkeypatch):
    monkeypatch.setattr(mons.commands.mods, "fetch_mod_db", lambda *args: request.param)


@pytest.fixture
def fake_mods(temp_mod_folder):
    for filename, data in installed_mods.items():
        mod_file = os.path.join(temp_mod_folder, filename)
        with zipfile.ZipFile(mod_file, "w") as zip:
            for filename, filedata in data.items():
                zip.writestr(filename, filedata)
    return None


@pytest.fixture
def fake_mods_request(request, temp_mod_folder):
    mods = request.param
    for mod in mods:
        filepath = os.path.join(temp_mod_folder, f"{mod}.zip")
        with zipfile.ZipFile(filepath, "w") as zip:
            zip.writestr(
                "everest.yaml",
                yaml.dump(
                    [
                        {
                            "Name": mod,
                            "Version": "2.2.2",
                        }
                    ]
                ),
            )
    return mods


mod_db.update(
    {
        "Installed": {
            "URL": "",
            "Version": "1.0.0",
            "GameBananaId": 12345,
            "LastUpdate": 0,
        },
        "Outdated": {
            "URL": "",
            "Version": "1.0.0",
            "GameBananaId": 12345,
            "LastUpdate": 0,
        },
        "Missing": {
            "URL": "",
            "Version": "1.0.0",
            "GameBananaId": 12345,
            "LastUpdate": 0,
        },
    }
)


def test_mods_add_none(runner_result, test_install):
    with runner_result(mons_cli, ["mods", "add", test_install, "--yes"]) as result:
        assert result.exit_code == 0
        assert "No mods to add." in result.output


@pytest.mark.parametrize(
    "data_file_zip",
    [
        {
            "everest.yaml": yaml.dump(
                [
                    {
                        "Name": "TestMod",
                        "Version": "1.0.0",
                    }
                ]
            )
        }
    ],
    indirect=("data_file_zip",),
)
def test_mods_add_zip(runner_result, test_install, data_file_zip, temp_mod_folder):
    with runner_result(
        mons_cli, ["mods", "add", test_install, *data_file_zip, "--yes"]
    ) as result:
        assert result.exit_code == 0
        assert "TestMod" in result.output
        assert "Installed mods" in result.output

    assert os.path.isfile(os.path.join(temp_mod_folder, "TestMod.zip")), os.listdir(
        temp_mod_folder
    )


@pytest.mark.data_file_zip(
    {
        "everest.yaml": yaml.dump(
            [
                {
                    "Name": "TestMod",
                    "Version": "1.0.0",
                }
            ]
        )
    }
)
def test_mods_add_stdin(runner_result, test_install, data_file_zip, temp_mod_folder):
    with open(data_file_zip[0]) as stdin, runner_result(
        mons_cli, ["mods", "add", test_install, "-", "--yes"], input=stdin
    ) as result:
        assert result.exit_code == 0
        assert "TestMod" in result.output
        assert "Installed mods" in result.output

    assert os.path.isfile(os.path.join(temp_mod_folder, "TestMod.zip")), os.listdir(
        temp_mod_folder
    )


@pytest.mark.data_file_zip(
    {
        "everest.yaml": yaml.dump(
            [
                {
                    "Name": "TestMod",
                    "Version": "1.0.0",
                }
            ]
        )
    }
)
def test_mods_add_blacklisted(
    runner_result, test_install, data_file_zip, temp_mod_folder
):
    blacklist = os.path.join(temp_mod_folder, "blacklist.txt")
    with open(blacklist, "w") as blacklist_file:
        blacklist_file.write("TestMod.zip")

    with runner_result(
        mons_cli, ["mods", "add", test_install, *data_file_zip, "--yes"]
    ) as result:
        assert result.exit_code == 0
        assert (
            "The following mods will be automatically removed from the blacklist"
            in result.output
        )

    with open(blacklist) as blacklist_file:
        contents = blacklist_file.read()
        assert "#TestMod.zip" in contents, contents


@pytest.mark.data_file_zip(
    {
        "everest.yaml": yaml.dump(
            [
                {
                    "Name": "TestMod",
                    "Version": "1.0.0",
                }
            ]
        )
    }
)
def test_mods_add_skip_unzipped(
    runner_result, test_install, data_file_zip, temp_mod_folder
):
    mod_dir = os.path.join(temp_mod_folder, "TestMod")
    os.mkdir(mod_dir)
    with open(os.path.join(mod_dir, "everest.yaml"), "w") as testmodyaml:
        testmodyaml.write(yaml.dump([{"Name": "TestMod", "Version": "1.0.0"}]))

    with runner_result(
        mons_cli, ["mods", "add", test_install, *data_file_zip, "--yes"]
    ) as result:
        assert result.exit_code == 0
        assert "Unzipped mods will not be updated" in result.output


@pytest.mark.data_file_zip({"everest.yaml": yaml.dump("hi!")})
def test_mods_add_invalid_mod(
    runner_result, test_install, data_file_zip, temp_mod_folder
):
    with runner_result(
        mons_cli,
        ["mods", "add", test_install, f"file://{data_file_zip[0]}", "--force"],
        input="NotAMod.zip\n",
    ) as result:
        assert result.exit_code == 0
        assert "The following mods could not be resolved" in result.output

    mod_added = os.path.isfile(os.path.join(temp_mod_folder, "NotAMod.zip"))
    assert mod_added, os.listdir(temp_mod_folder)


installed_mods.update(
    {
        "Remove.zip": {
            "everest.yaml": yaml.dump(
                [
                    {
                        "Name": "Remove",
                        "Version": "1.0.0",
                    }
                ]
            )
        },
        "Remove_Recurse.zip": {
            "everest.yaml": yaml.dump(
                [
                    {
                        "Name": "Remove_Recurse",
                        "Version": "1.0.0",
                        "Dependencies": [
                            {"Name": "Remove_Recurse_Dep", "Version": "1.0.0"},
                            {"Name": "Remove_Recurse_Shared", "Version": "1.0.0"},
                        ],
                    }
                ]
            )
        },
        "Remove_Recurse_Dep.zip": {
            "everest.yaml": yaml.dump(
                [
                    {
                        "Name": "Remove_Recurse_Dep",
                        "Version": "1.0.0",
                    }
                ]
            )
        },
        "Remove_Recurse_Shared.zip": {
            "everest.yaml": yaml.dump(
                [
                    {
                        "Name": "Remove_Recurse_Shared",
                        "Version": "1.0.0",
                    }
                ]
            )
        },
        "Remove_Other.zip": {
            "everest.yaml": yaml.dump(
                [
                    {
                        "Name": "Remove_Other",
                        "Version": "1.0.0",
                        "Dependencies": [
                            {"Name": "Remove_Recurse_Shared", "Version": "1.0.0"}
                        ],
                    }
                ]
            )
        },
    }
)


def test_mods_remove(runner_result, test_install, temp_mod_folder, fake_mods):
    with runner_result(
        mons_cli, ["mods", "remove", test_install, "Remove", "--force"]
    ) as result:
        assert result.exit_code == 0

    assert not os.path.exists(os.path.join(temp_mod_folder, "Remove.zip")), os.listdir(
        temp_mod_folder
    )


def test_mods_remove_recurse(runner_result, test_install, temp_mod_folder, fake_mods):
    with runner_result(
        mons_cli,
        ["mods", "remove", test_install, "--recurse", "Remove_Recurse", "--force"],
    ) as result:
        assert result.exit_code == 0

    for filename in ["Remove_Recurse.zip", "Remove_Recurse_Dep.zip"]:
        filepath = os.path.join(temp_mod_folder, filename)
        assert not os.path.exists(filepath), os.listdir(temp_mod_folder)

    filepath = os.path.join(temp_mod_folder, "Remove_Recurse_Shared.zip")
    assert os.path.exists(filepath), os.listdir(temp_mod_folder)


def test_mods_remove_none(runner_result, test_install, temp_mod_folder, fake_mods):
    with runner_result(
        mons_cli, ["mods", "remove", test_install, "Non-Existent-Mod", "--force"]
    ) as result:
        assert result.exit_code == 0
        assert "No mods to remove." in result.output


def test_mods_update(runner_result, test_install, temp_mod_folder, fake_mods):
    with runner_result(mons_cli, ["mods", "update", test_install]) as result:
        assert result.exit_code == 0
        assert "All mods up to date" in result.output


def test_mods_list(runner_result, test_install, temp_mod_folder, fake_mods):
    with runner_result(mons_cli, ["mods", "list", test_install]) as result:
        assert result.exit_code == 0
        # strip .zip from filenames
        assert all(mod[:-4] in result.output for mod in installed_mods.keys())
