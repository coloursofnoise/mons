import click
import pytest
import yaml

import mons.clickExt
import mons.commands.mods
from mons.commands.mods import resolve_dependencies
from mons.commands.mods import resolve_exclusive_dependencies
from mons.commands.mods import resolve_mods
from mons.modmeta import ModMeta

mod_db = {}
dep_graph = {}


@pytest.fixture(autouse=True)
def fake_mod_db(monkeypatch):
    monkeypatch.setattr(mons.commands.mods, "fetch_mod_db", lambda *args: mod_db)
    monkeypatch.setattr(
        mons.commands.mods, "fetch_dependency_graph", lambda *args: dep_graph
    )


@pytest.fixture(autouse=True)
def stub_confirm_ext(monkeypatch):
    def abort(*args, **kwargs):
        raise click.Abort()

    monkeypatch.setattr(mons.clickExt, "confirm_ext", abort)


# better display names for parametrized tests
def id_modmeta(val):
    if isinstance(val, list) and all(isinstance(mod, ModMeta) for mod in val):
        mod_names = [mod.Name for mod in val]
        test_name = ""
        for c, d in zip(max(mod_names, key=len), min(mod_names, key=len)):
            if c != d:
                break
            test_name += c
        return test_name.strip("_")
    if isinstance(val, str):
        return f'"{val}"'
    if hasattr(val, "expected_exception"):
        return val.expected_exception  # type:ignore


def modmeta_for(name):
    try:
        return ModMeta(
            {"Name": name, **mod_db.get(name, {"Version": "1.0.0"}), **dep_graph[name]}
        )
    except KeyError:
        return name


TEST_MOD = "TestMod"


mod_db.update(
    {
        TEST_MOD: {
            "URL": "https://gamebanana.com/mmdl/12345",
            "MirrorURL": "https://testmirror.test",
            "Version": "1.0.0",
            "GameBananaId": 12345,
            "LastUpdate": 0,
        },
        "TestHelper": {
            "URL": "https://gamebanana.com/mmdl/54321",
            "MirrorURL": "https://testmirror.test",
            "Version": "1.0.0",
            "GameBananaId": 54321,
            "LastUpdate": 0,
        },
    }
)


dep_graph.update(
    {
        TEST_MOD: {
            "Dependencies": [{"Name": "TestHelper", "Version": "1.0.0"}],
            "OptionalDependencies": [],
        },
        "TestHelper": {},
    }
)


@pytest.mark.parametrize(
    ("input", "expect"),
    [
        pytest.param(TEST_MOD, TEST_MOD, id="Mod Name"),
        pytest.param(
            f"https://gamebanana.com/mods/{mod_db[TEST_MOD]['GameBananaId']}",
            TEST_MOD,
            id="GameBanana Page",
        ),
        pytest.param(
            f"everest:{mod_db[TEST_MOD]['URL']},Mod,00000",
            TEST_MOD,
            id="1-Click Install",
        ),
        pytest.param(str(mod_db[TEST_MOD]["GameBananaId"]), TEST_MOD, id="Mod ID"),
    ],
)
def test_resolve_mods(input, expect):
    (resolved, unresolved) = resolve_mods(None, [input])
    assert resolved and not unresolved
    assert resolved[0].Meta.Name == expect


@pytest.mark.data_file_zip(
    {
        "everest.yaml": yaml.safe_dump(
            [
                {
                    "Name": TEST_MOD,
                    "Version": "1.0.0",
                }
            ]
        )
    }
)
def test_resolve_mods_zip(data_file_zip):
    (resolved, unresolved) = resolve_mods(None, data_file_zip)
    assert resolved and not unresolved
    assert resolved[0].Meta.Name == TEST_MOD


@pytest.mark.parametrize(
    ("input", "expect"),
    [
        pytest.param(
            "https://drive.google.com/file/d/filename.zip",
            "https://drive.google.com/uc?export=download&id=filename.zip",
            id="Google Drive",
        ),
        pytest.param("fake://mod/path", "fake://mod/path", id="URL"),
    ],
)
def test_resolve_mods_unresolved(input, expect):
    (resolved, unresolved) = resolve_mods(None, [input])
    assert unresolved and not resolved
    assert unresolved[0] == expect


def test_resolve_mods_fail(caplog):
    fake_mod = "FakeMod"
    with pytest.raises(click.Abort):
        resolve_mods(None, (*mod_db.keys(), fake_mod))
    assert f"Mod '{fake_mod}' could not be resolved" in caplog.text


dep_graph.update(
    {
        "Simple": {},
        "Nested": {
            "Dependencies": [{"Name": "Nested_1", "Version": "1.0.0"}],
            "OptionalDependencies": [],
        },
        **{
            "Nested_1": {
                "Dependencies": [{"Name": "Nested_2", "Version": "1.0.0"}],
                "OptionalDependencies": [],
            },
            **{
                "Nested_2": {
                    "Dependencies": [],
                    "OptionalDependencies": [],
                },
            },
        },
        "Version_Bump_Lower": {
            "Dependencies": [{"Name": "Version_Bump_Dep", "Version": "1.2.0"}],
            "OptionalDependencies": [],
        },
        "Version_Bump_Higher": {
            "Dependencies": [{"Name": "Version_Bump_Dep", "Version": "1.5.0"}],
            "OptionalDependencies": [],
        },
        "Version_Bump_Optional": {
            "Dependencies": [{"Name": "Version_Bump_Optional_Dep", "Version": "1.5.0"}],
            "OptionalDependencies": [
                {"Name": "Version_Bump_Optional_Dep", "Version": "1.7.0"}
            ],
        },
    }
)


@pytest.mark.parametrize(
    ("mods", "expect"),
    [
        pytest.param([], "[]", id="Empty"),
        pytest.param([modmeta_for("Simple")], "[]"),
        pytest.param(
            [modmeta_for("Nested")],
            "[Nested_1: 1.0.0, Nested_2: 1.0.0]",
        ),
        pytest.param(
            [
                modmeta_for("Version_Bump_Lower"),
                modmeta_for("Version_Bump_Higher"),
                modmeta_for("Version_Bump_Lower"),  # make sure order doesn't matter
            ],
            "[Version_Bump_Dep: 1.5.0]",
        ),
    ],
    ids=id_modmeta,
)
def test_resolve_dependencies(mods, expect):
    dependencies, _opt_deps = resolve_dependencies(mods)
    assert str(dependencies) == expect


dep_graph.update(
    {
        "Opt_Deps_Nested": {
            "Dependencies": [],
            "OptionalDependencies": [{"Name": "Opt_Deps_Nested_1", "Version": "1.0.0"}],
        },
        **{
            "Opt_Deps_Nested_1": {
                "Dependencies": [{"Name": "Opt_Deps_Nested_Dep", "Version": "1.0.0"}],
                "OptionalDependencies": [
                    {"Name": "Opt_Deps_Nested_Opt", "Version": "1.0.0"}
                ],
            },
            **{
                "Opt_Deps_Nested_Dep": {},
                "Opt_Deps_Nested_Opt": {},
            },
        },
        "Opt_Deps_Shadowed": {
            "Dependencies": [{"Name": "Opt_Deps_Shadowed_Dep", "Version": "1.3.0"}],
            "OptionalDependencies": [
                {"Name": "Opt_Deps_Shadowed_Dep", "Version": "1.6.2"}
            ],
        },
    }
)


@pytest.mark.parametrize(
    ("mods", "expect", "expect_opt"),
    [
        ([modmeta_for("Opt_Deps_Nested")], "[]", "[Opt_Deps_Nested_1: 1.0.0]"),
        ([modmeta_for("Opt_Deps_Shadowed")], "[Opt_Deps_Shadowed_Dep: 1.6.2]", "[]"),
    ],
    ids=id_modmeta,
)
def test_resolve_dependencies_optional(mods, expect, expect_opt):
    deps, opt_deps = resolve_dependencies(mods)
    assert str(opt_deps) == expect_opt
    assert str(deps) == expect


dep_graph.update(
    {
        "Error_Major_Ver": {
            "Dependencies": [
                {"Name": "Error_Major_Ver_Dep", "Version": "1.5.0"},
                {"Name": "Error_Major_Ver_Dep", "Version": "2.1.0"},
            ],
            "OptionalDependencies": [],
        },
        "Error_Major_Ver_Opt": {
            "Dependencies": [{"Name": "Error_Major_Ver_Opt_Dep", "Version": "1.5.0"}],
            "OptionalDependencies": [
                {"Name": "Error_Major_Ver_Opt_Dep", "Version": "2.1.0"}
            ],
        },
        "Error_Unfulfilled": {
            "Dependencies": [{"Name": "Error_Unfulfilled", "Version": "1.5.0"}],
            "OptionalDependencies": [],
        },
        "Error_Unfulfilled_Opt": {
            "Dependencies": [],
            "OptionalDependencies": [
                {"Name": "Error_Unfulfilled_Opt", "Version": "1.5.0"}
            ],
        },
    }
)


@pytest.mark.parametrize(
    ("mods", "raises"),
    [
        (
            [modmeta_for("Error_Major_Ver")],
            pytest.raises(
                ValueError, match=r"Incompatible dependencies.*different major version"
            ),
        ),
        (
            [modmeta_for("Error_Major_Ver_Opt")],
            pytest.raises(
                ValueError, match=r"Incompatible dependencies.*different major version"
            ),
        ),
        (
            [modmeta_for("Error_Unfulfilled")],
            pytest.raises(
                ValueError,
                match=r"Incompatible dependencies.*\(explicit\) does not satisfy dependency",
            ),
        ),
        (
            [modmeta_for("Error_Unfulfilled_Opt")],
            pytest.raises(
                ValueError,
                match=r"Incompatible dependencies.*\(explicit\) does not satisfy optional dependency",
            ),
        ),
    ],
    ids=id_modmeta,
)
def test_resolve_dependencies_fail(mods, raises):
    with raises:
        resolve_dependencies(mods)


installed_mods = {
    mod.Name: mod
    for mod in [
        ModMeta({"Name": "No_Deps", "Version": "1.0.0"}),
        ModMeta(
            {
                "Name": "Shared_Deps",
                "Version": "1.0.0",
                "Dependencies": [
                    {"Name": "Shared_Deps_Dep", "Version": "1.0.0"},
                ],
            }
        ),
        *[
            ModMeta({"Name": "Shared_Deps_Dep", "Version": "1.0.0"}),
        ],
        ModMeta(
            {
                "Name": "Exclusive_Deps",
                "Version": "1.0.0",
                "Dependencies": [
                    {"Name": "Exclusive_Deps_Dep", "Version": "1.0.0"},
                ],
            }
        ),
        *[ModMeta({"Name": "Exclusive_Deps_Dep", "Version": "1.0.0"})],
        ModMeta(
            {
                "Name": "Shared_Exclusive_Deps",
                "Version": "1.0.0",
                "Dependencies": [
                    {"Name": "Shared_Deps_Dep", "Version": "1.0.0"},
                    {"Name": "Shared_Exclusive_Deps_Dep", "Version": "1.0.0"},
                ],
            }
        ),
        *[
            ModMeta({"Name": "Shared_Exclusive_Deps_Dep", "Version": "1.0.0"}),
        ],
    ]
}


@pytest.mark.parametrize(
    ("mods", "expect"),
    [
        ([installed_mods["No_Deps"]], "[]"),
        ([installed_mods["Shared_Deps"]], "[]"),
        ([installed_mods["Exclusive_Deps"]], "[Exclusive_Deps_Dep: 1.0.0]"),
        (
            [installed_mods["Shared_Exclusive_Deps"]],
            "[Shared_Exclusive_Deps_Dep: 1.0.0]",
        ),
    ],
    ids=id_modmeta,
)
def test_resolve_exclusive_dependencies(mods, expect):
    deps = resolve_exclusive_dependencies(mods, installed_mods)
    assert str(deps) == expect
