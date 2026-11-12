"""DB schema v2: new default colours, old defaults migrated, custom colours kept."""


def load(env, db=None):
    if db is not None:
        env.G.XPOrbsDB = env.lua.table_from(db, recursive=True)
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    return env.G.XPOrbsDB


def rgb(c):
    return (c[1], c[2], c[3])


def test_fresh_db_is_v2_with_new_colours(env):
    db = load(env)
    assert db.version == 2
    assert rgb(db.color) == (0.20, 0.50, 1.00)
    assert rgb(db.restedColor) == (1.0, 0.30, 0.85)


def test_old_defaults_are_migrated(env):
    db = load(env, {"version": 1, "color": [0.35, 0.65, 1.0], "restedColor": [0.7, 0.45, 1.0], "cap": 25})
    assert db.version == 2
    assert rgb(db.color) == (0.20, 0.50, 1.00)
    assert rgb(db.restedColor) == (1.0, 0.30, 0.85)
    assert db.cap == 25


def test_old_defaults_with_float_noise_and_nil_version(env):
    db = load(env, {"color": [0.3501, 0.6499, 1.0], "restedColor": [0.7, 0.4501, 0.9999]})
    assert db.version == 2
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
