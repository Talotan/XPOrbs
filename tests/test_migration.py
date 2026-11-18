"""DB schema migrations: v2 colours, v4 origin dropped / kill style, v5 purple/blue colours and 1.0 s flight; the
removed `probe` key is dropped."""


def load(env, db=None):
    if db is not None:
        env.G.XPOrbsDB = env.lua.table_from(db, recursive=True)
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    return env.G.XPOrbsDB


def rgb(c):
    return (c[1], c[2], c[3])


def test_fresh_db_is_current_schema_with_new_colours(env):
    db = load(env)
    assert db.version == 5
    assert rgb(db.color) == (0.85, 0.38, 1.00)
    assert rgb(db.restedColor) == (0.15, 0.38, 1.00)


def test_old_defaults_are_migrated(env):
    db = load(env, {"version": 1, "color": [0.35, 0.65, 1.0], "restedColor": [0.7, 0.45, 1.0], "cap": 25})
    assert db.version == 5
    assert rgb(db.color) == (0.85, 0.38, 1.00)
    assert rgb(db.restedColor) == (0.15, 0.38, 1.00)
    assert db.cap == 25


def test_old_defaults_with_float_noise_and_nil_version(env):
    db = load(env, {"color": [0.3501, 0.6499, 1.0], "restedColor": [0.7, 0.4501, 0.9999]})
    assert db.version == 5
    assert rgb(db.color) == (0.85, 0.38, 1.00)
    assert rgb(db.restedColor) == (0.15, 0.38, 1.00)


def test_custom_colours_are_kept(env):
    db = load(env, {"version": 1, "color": [0.1, 0.9, 0.2], "restedColor": [0.7, 0.45, 1.0]})
    assert rgb(db.color) == (0.1, 0.9, 0.2)
    assert rgb(db.restedColor) == (0.15, 0.38, 1.00)


def test_v2_db_is_not_migrated_again(env):
    # a user who deliberately picked the old blue after v2 keeps it
    db = load(env, {"version": 2, "color": [0.35, 0.65, 1.0]})
    assert rgb(db.color) == (0.35, 0.65, 1.0)


def test_v2_db_gets_v3_migration_but_keeps_other_values(env):
    db = load(env, {"version": 2, "probe": True, "origin": "plate", "cap": 12, "color": [0.35, 0.65, 1.0]})
    assert db.version == 5
    assert db.probe is None and db.origin is None
    assert db.cap == 12
    assert rgb(db.color) == (0.35, 0.65, 1.0)  # schema-2 colour migration does not run again


def test_v1_db_gets_both_migrations(env):
    db = load(env, {"version": 1, "probe": True, "origin": "plate", "color": [0.35, 0.65, 1.0]})
    assert db.version == 5 and db.probe is None and db.origin is None
    assert rgb(db.color) == (0.85, 0.38, 1.00)


def test_v3_db_drops_probe_and_origin_and_gets_style(env):
    db = load(env, {"version": 3, "probe": True, "origin": "plate", "corpsePop": True})
    assert db.version == 5 and db.probe is None
    assert db.origin is None and db.corpsePop is None and db.style == "popstream"


def test_v4_db_keeps_its_style(env):
    db = load(env, {"version": 4, "style": "crossfade"})
    assert db.style == "crossfade" and db.version == 5


def test_fresh_db_defaults(env):
    db = load(env)
    assert db.probe is None and db.origin is None
    assert db.enabled is True and db.questBursts is True and db.showAtMax is False


# ---------------------------------------------------------------- schema 5 (1.1.0)


def test_fresh_db_has_the_new_defaults(env):
    db = load(env)
    assert db.version == 5 and db.flightTime == 1.0 and db.sound is False
    assert rgb(db.color) == (0.85, 0.38, 1.00) and rgb(db.restedColor) == (0.15, 0.38, 1.00)


def test_v4_old_defaults_get_the_new_ones(env):
    db = load(
        env,
        {"version": 4, "color": [0.20, 0.50, 1.00], "restedColor": [1.0, 0.30, 0.85], "flightTime": 0.75, "cap": 25},
    )
    assert db.version == 5
    assert rgb(db.color) == (0.85, 0.38, 1.00)
    assert rgb(db.restedColor) == (0.15, 0.38, 1.00)
    assert db.flightTime == 1.0
    assert db.cap == 25  # unrelated settings are untouched


def test_v4_old_defaults_with_float_noise_are_replaced(env):
    db = load(env, {"version": 4, "color": [0.2003, 0.4996, 1.0], "restedColor": [1.0, 0.3004, 0.8498], "flightTime": 0.7502})
    assert rgb(db.color) == (0.85, 0.38, 1.00) and rgb(db.restedColor) == (0.15, 0.38, 1.00)
    assert db.flightTime == 1.0


def test_v4_custom_values_are_kept(env):
    db = load(env, {"version": 4, "color": [0.1, 0.9, 0.2], "restedColor": [0.5, 0.5, 0.5], "flightTime": 0.6})
    assert db.version == 5
    assert rgb(db.color) == (0.1, 0.9, 0.2) and rgb(db.restedColor) == (0.5, 0.5, 0.5)
    assert db.flightTime == 0.6


def test_v4_only_the_old_default_values_are_replaced(env):
    # each value is judged on its own: the colour is custom, the flight time is still the old default
    db = load(env, {"version": 4, "color": [0.1, 0.9, 0.2], "flightTime": 0.75})
    assert rgb(db.color) == (0.1, 0.9, 0.2) and db.flightTime == 1.0


def test_v5_db_is_not_migrated_again(env):
    # a user who picks the old defaults after the 1.1.0 upgrade keeps them
    db = load(env, {"version": 5, "color": [0.20, 0.50, 1.00], "restedColor": [1.0, 0.30, 0.85], "flightTime": 0.75})
    assert rgb(db.color) == (0.20, 0.50, 1.00) and rgb(db.restedColor) == (1.0, 0.30, 0.85)
    assert db.flightTime == 0.75 and db.version == 5


def test_schema_4_goes_to_5_and_a_future_version_is_not_stamped_down(env):
    assert load(env, {"version": 4}).version == 5
    db = load(env, {"version": 9, "color": [0.20, 0.50, 1.00], "flightTime": 0.75})
    assert db.version == 9 and rgb(db.color) == (0.20, 0.50, 1.00)  # v >= 5: no migration, no stamp-down
