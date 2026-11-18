"""Fallback lint (no luacheck available): syntax check + accidental-global-write detection.

Each addon file is compiled with loadstring, then run in a sandbox env whose __newindex
records every global write. Only XPOrbsDB and SLASH_XPORBS1 may be created.
"""

import pytest
from conftest import ROOT, TESTS, addon_files, make_runtime

ALLOWED_WRITES = {
    "XPOrbsDB",
    "SLASH_XPORBS1",
    "XPOrbs_OnAddonCompartmentClick",
    "XPOrbs_OnAddonCompartmentEnter",
    "XPOrbs_OnAddonCompartmentLeave",
}

SANDBOX = """
return function(fns, ns, fire)
    local writes = {}
    local env = setmetatable({}, {
        __index = _G,
        __newindex = function(t, k, v)
            writes[#writes + 1] = tostring(k)
            rawset(t, k, v)
        end,
    })
    for _, fn in ipairs(fns) do
        setfenv(fn, env)
        fn("XPOrbs", ns)
    end
    fire("ADDON_LOADED", "XPOrbs")
    return writes
end
"""


def addon_lua_files():
    files = [ROOT / p for p in addon_files() if p.endswith(".lua")]
    for extra in ROOT.glob("**/*.lua"):
        rel = extra.relative_to(ROOT)
        if rel.parts[0] in ("tests", ".venv", "tools", "Libs"):
            continue
        if extra not in files:
            files.append(extra)  # catches files that exist but aren't in the toc yet
    return files


@pytest.mark.parametrize("path", addon_lua_files(), ids=lambda p: p.name)
def test_syntax(path):
    lua, _, _ = make_runtime()
    loader = lua.eval("function(src, name) return loadstring(src, name) end")
    result = loader(path.read_text(encoding="utf-8"), "@" + path.name)
    # loadstring returns (nil, err) on failure; unpack_returned_tuples gives us the tuple.
    assert not isinstance(result, tuple), f"syntax error: {result}"
    assert result is not None


def test_no_accidental_globals():
    lua, ns, load_chunk = make_runtime()
    load_chunk(TESTS / "wowstub.lua", "wowstub.lua")(ns)
    fns = lua.table_from([load_chunk(ROOT / rel, rel) for rel in addon_files() if rel.endswith(".lua")])
    sandbox = lua.execute(SANDBOX)
    writes = set(sandbox(fns, ns, ns.fire).values())
    assert writes <= ALLOWED_WRITES, f"unexpected global writes: {sorted(writes - ALLOWED_WRITES)}"
