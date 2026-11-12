from conftest import RUNTIME_NAME, toc_files

ALLOWED_NEW_GLOBALS = {"XPOrbsDB", "SLASH_XPORBS1"}


def global_keys(G):
    return {k for k in G.keys()}


def test_runtime_is_lua51_family():
    assert RUNTIME_NAME in ("lupa.lua51", "lupa.luajit21")


def test_toc_lists_files():
    files = toc_files()
    assert files and files[0] == "Core.lua"


def test_files_load_and_only_expected_globals(env):
    before = global_keys(env.G)
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    new = global_keys(env.G) - before
    assert new == ALLOWED_NEW_GLOBALS
    # SlashCmdList.XPORBS is a field on an existing table, not a new global.
    assert env.G.SlashCmdList.XPORBS is not None
    assert env.G.SLASH_XPORBS1 == "/xporbs"


def test_defaults_filled_and_version_set(env):
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    db = env.G.XPOrbsDB
    assert db.version == 3
    assert db.density == 100 and db.cap == 40
    assert db.color[1] == 0.20
    assert db.debug is False


def test_other_addon_loaded_is_ignored(env):
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "SomethingElse")
    assert env.G.XPOrbsDB is None


def test_existing_db_keeps_values(env):
    env.G.XPOrbsDB = env.lua.table_from({"density": 250})
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    assert env.G.XPOrbsDB.density == 250
    assert env.G.XPOrbsDB.cap == 40


def test_log_ring_and_debug_gate(env):
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    env.ns.Log(env.ns, "ignored %d", 1)
    assert env.G.XPOrbsDB.log is None
    env.G.XPOrbsDB.debug = True
    for i in range(520):
        env.ns.Log(env.ns, "entry %d", i)
    env.ns.Log(env.ns, "bad %d", "notanumber")
    log = env.G.XPOrbsDB.log
    assert len(log) == 500
    assert "log format error" in log[500]


def test_slash_commands(env):
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    slash = env.G.SlashCmdList.XPORBS
    slash("help")
    assert any("/xporbs debug" in m for m in env.ns.stub.chat.values())
    slash("debug on")
    assert env.G.XPOrbsDB.debug is True
    slash("debug off")
    assert env.G.XPOrbsDB.debug is False
    slash("options")  # still a stub until M5
    assert "not yet implemented" in env.ns.stub.chat[len(env.ns.stub.chat)]
