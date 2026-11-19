"""Release zip layout: what the packager would ship, under a top-level XPOrbs/ folder."""

import importlib.util
import re
import zipfile

import pytest
from conftest import ROOT, toc_files

spec = importlib.util.spec_from_file_location("xporbs_package", ROOT / "tools" / "package.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


@pytest.fixture(scope="module")
def zip_names_and_toc(tmp_path_factory):
    path = package.build(tmp_path_factory.mktemp("dist"))
    with zipfile.ZipFile(path) as z:
        return z.namelist(), z.read("XPOrbs/XPOrbs.toc").decode("utf-8")


def test_all_entries_under_addon_folder(zip_names_and_toc):
    names, _ = zip_names_and_toc
    assert names and all(n.startswith("XPOrbs/") for n in names)
    assert not any("\\" in n for n in names)


def test_toc_files_present(zip_names_and_toc):
    names, _ = zip_names_and_toc
    for rel in ["XPOrbs.toc", *toc_files()]:
        assert f"XPOrbs/{rel}" in names


@pytest.mark.parametrize("rel", [
        "media/orb.tga",
        "media/sparkle.tga",
        "media/flash.tga",
        "media/icon.tga",
        "media/icon-list.tga",
        "LICENSE",
        "Libs/README.md",
        "Libs/LibStub/LibStub.lua",
        "Libs/CallbackHandler-1.0/CallbackHandler-1.0.lua",
        "Libs/LibDataBroker-1.1/LibDataBroker-1.1.lua",
        "Libs/LibDBIcon-1.0/LibDBIcon-1.0.lua",
    ])
def test_required_files(zip_names_and_toc, rel):
    assert f"XPOrbs/{rel}" in zip_names_and_toc[0]


def test_dev_files_excluded(zip_names_and_toc):
    names, _ = zip_names_and_toc
    for n in names:
        rest = n.removeprefix("XPOrbs/")
        assert rest.split("/")[0] not in ("tests", "tools", "docs", ".github"), n
        assert rest not in ("pyproject.toml", "uv.lock"), n


def test_version_matches_repo_toc(zip_names_and_toc):
    _, toc = zip_names_and_toc
    pat = re.compile(r"^## Version:\s*(\S+)", re.MULTILINE)
    assert pat.search(toc).group(1) == pat.search((ROOT / "XPOrbs.toc").read_text(encoding="utf-8")).group(1)
