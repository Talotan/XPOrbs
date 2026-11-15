"""DB schema migrations: v2 colours, v4 origin dropped / kill style; the removed `probe` key is dropped."""


def load(env, db=None):
    if db is not None:
        env.G.XPOrbsDB = env.lua.table_from(db, recursive=True)
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    return env.G.XPOrbsDB


def rgb(c):
    return (c[1], c[2], c[3])


def test_fresh_db_is_v3_with_new_colours(env):
    db = load(env)
    assert db.version == 4
    assert rgb(db.color) == (0.20, 0.50, 1.00)
    assert rgb(db.restedColor) == (1.0, 0.30, 0.85)


def test_old_defaults_are_migrated(env):
    db = load(env, {"version": 1, "color": [0.35, 0.65, 1.0], "restedColor": [0.7, 0.45, 1.0], "cap": 25})
    assert db.version == 4
    assert rgb(db.color) == (0.20, 0.50, 1.00)
    assert rgb(db.restedColor) == (1.0, 0.30, 0.85)
    assert db.cap == 25


def test_old_defaults_with_float_noise_and_nil_version(env):
    db = load(env, {"color": [0.3501, 0.6499, 1.0], "restedColor": [0.7, 0.4501, 0.9999]})
    assert db.version == 4
    assert rgb(db.color) == (0.20, 0.50, 1.00)
    assert rgb(db.restedColor) == (1.0, 0.30, 0.85)


def test_custom_colours_are_kept(env):
    db = load(env, {"version": 1, "color": [0.1, 0.9, 0.2], "restedColor": [0.7, 0.45, 1.0]})
    assert rgb(db.color) == (0.1, 0.9, 0.2)
    assert rgb(db.restedColor) == (1.0, 0.30, 0.85)


def test_v2_db_is_not_migrated_again(env):
    # a user who deliberately picked the old blue after v2 keeps it
    db = load(env, {"version": 2, "color": [0.35, 0.65, 1.0]})
    assert rgb(db.color) == (0.35, 0.65, 1.0)


def test_v2_db_gets_v3_migration_but_keeps_other_values(env):
    db = load(env, {"version": 2, "probe": True, "origin": "plate", "cap": 12, "color": [0.35, 0.65, 1.0]})
    assert db.version == 4
    assert db.probe is None and db.origin is None
    assert db.cap == 12
    assert rgb(db.color) == (0.35, 0.65, 1.0)  # schema-2 colour migration does not run again


def test_v1_db_gets_both_migrations(env):
    db = load(env, {"version": 1, "probe": True, "origin": "plate", "color": [0.35, 0.65, 1.0]})
    assert db.version == 4 and db.probe is None and db.origin is None
    assert rgb(db.color) == (0.20, 0.50, 1.00)


def test_v3_db_drops_probe_and_origin_and_gets_style(env):
    db = load(env, {"version": 3, "probe": True, "origin": "plate", "corpsePop": True})
    assert db.version == 4 and db.probe is None
    assert db.origin is None and db.corpsePop is None and db.style == "popstream"


def test_v4_db_keeps_its_style(env):
    db = load(env, {"version": 4, "style": "crossfade"})
    assert db.style == "crossfade" and db.version == 4


def test_fresh_db_defaults(env):
    db = load(env)
    assert db.probe is None and db.origin is None
    assert db.enabled is True and db.questBursts is True and db.showAtMax is False
