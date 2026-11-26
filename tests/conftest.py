"""Lua 5.1 test harness: lupa runtime + WoW stub + addon loader driven by the .toc."""

from pathlib import Path

import pytest

try:
    import lupa.lua51 as lupa_rt

    RUNTIME_NAME = "lupa.lua51"
except ImportError:  # pragma: no cover
    import lupa.luajit21 as lupa_rt

    RUNTIME_NAME = "lupa.luajit21"

print(f"[xporbs] Lua runtime: {RUNTIME_NAME}")

ROOT = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent


def toc_files():
    """Addon file list from the .toc: every non-blank, non-comment line."""
    out = []
    for line in (ROOT / "XPOrbs.toc").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line.replace("\\", "/"))
    return out


def addon_files():
    """toc_files() minus the bundled third-party libraries (Libs/) and the XML templates: only Lua is loaded here."""
    return [f for f in toc_files() if not f.startswith("Libs/") and f.endswith(".lua")]


def make_runtime():
    lua = lupa_rt.LuaRuntime(unpack_returned_tuples=True)
    ns = lua.table()
    ns["fixtureDir"] = str(TESTS / "fixtures").replace("\\", "/")
    loader = lua.eval("function(src, name) return loadstring(src, name) end")

    def load_chunk(path: Path, chunkname: str):
        fn = loader(path.read_text(encoding="utf-8"), "@" + chunkname)
        if fn is None:
            raise RuntimeError(f"failed to compile {chunkname}")
        return fn

    return lua, ns, load_chunk


@pytest.fixture
def env():
    """Fresh runtime with the stub loaded (addon files not yet loaded)."""
    lua, ns, load_chunk = make_runtime()
    load_chunk(TESTS / "wowstub.lua", "wowstub.lua")(ns)

    class Env:
        pass

    e = Env()
    e.lua, e.ns, e.load_chunk = lua, ns, load_chunk
    e.G = lua.globals()

    def load_addon():
        for rel in addon_files():
            load_chunk(ROOT / rel, rel)("XPOrbs", ns)

    e.load_addon = load_addon
    return e


@pytest.fixture
def xpgain(env):
    """The real enUS XP-gain globals (tests/fixtures/xpgain_enUS.lua) as a plain Lua table."""
    fn = env.load_chunk(TESTS / "fixtures" / "xpgain_enUS.lua", "xpgain_enUS.lua")
    t = env.lua.table()
    env.lua.eval("function(fn, t) setfenv(fn, t); fn() end")(fn, t)
    return t


def lua_list(t):
    """Lua array table -> Python list."""
    return [t[i] for i in range(1, len(t) + 1)]
