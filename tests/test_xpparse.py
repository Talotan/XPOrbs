"""XPParse: patterns from format strings and chat-message parsing, using the real enUS client strings."""

import pytest
from conftest import lua_list


@pytest.fixture
def parser(env, xpgain):
    env.load_addon()
    return env.ns.XPParse.Build(xpgain)


def parse(p, msg, readable=None):
    return p.Parse(p, msg, readable)


# ---- PatternFrom ----------------------------------------------------------------------------------------------


def test_pattern_from_plain(env):
    env.load_addon()
    pattern, order = env.ns.XPParse.PatternFrom("%s dies, you gain %d experience.")
    assert pattern == "^(.-) dies%, you gain (%d+) experience%.$"
    assert lua_list(order) == [1, 2]


def test_pattern_from_positional(env):
    env.load_addon()
    pattern, order = env.ns.XPParse.PatternFrom("%2$d XP von %1$s")
    assert pattern == "^(%d+) XP von (.-)$"
    assert lua_list(order) == [2, 1]


def test_pattern_from_escapes_magic(env):
    env.load_addon()
    pattern, _ = env.ns.XPParse.PatternFrom("(+%d%%) [x] a-b")
    assert pattern == "^%(%+(%d+)%%%) %[x%] a%-b$"


def test_pattern_from_non_string(env):
    env.load_addon()
    assert env.ns.XPParse.PatternFrom(None) is None
    assert env.ns.XPParse.PatternFrom(5) is None


# ---- Build ----------------------------------------------------------------------------------------------------


def test_identical_exhaustion_formats_make_one_pattern(env, xpgain):
    env.load_addon()
    assert xpgain.COMBATLOG_XPGAIN_EXHAUSTION1 == xpgain.COMBATLOG_XPGAIN_EXHAUSTION2
    p = env.ns.XPParse.Build(xpgain)
    patterns = [e.pattern for e in lua_list(p.entries)]
    assert len(patterns) == len(set(patterns))
    # FIRSTPERSON 3 + EX1(=EX2) 3 + EX4(=EX5) 3 + UNNAMED 3 + QUEST 1 = 13 unique; third-person is ignored
    assert len(patterns) == 13


def test_build_skips_non_strings_and_missing(env):
    env.load_addon()
    g = env.lua.table_from(
        {"COMBATLOG_XPGAIN_FIRSTPERSON": 42, "COMBATLOG_XPGAIN_EXHAUSTION3": None}
    )
    p = env.ns.XPParse.Build(g)
    assert len(p.entries) == 0
    assert parse(p, "Kobold dies, you gain 90 experience.") is None


# ---- Parse: the real wordings ---------------------------------------------------------------------------------


def test_parse_plain(parser):
    r = parse(parser, "Kobold dies, you gain 90 experience.")
    assert (r.mob, r.amount, r.kind) == ("Kobold", 90, "kill")
    assert r.rested is None and r.penalty is None


def test_parse_rested_exhaustion1(parser):
    r = parse(parser, "Kobold dies, you gain 90 experience. (+45 exp Rested bonus)")
    assert (r.mob, r.amount, r.kind, r.rested) == ("Kobold", 90, "kill", 45)
    assert r.penalty is None


def test_parse_rested_without_plus_sign(parser):
    r = parse(parser, "Kobold dies, you gain 90 experience. (45 exp Rested bonus)")
    assert r.rested == 45 and r.amount == 90 and r.mob == "Kobold"


def test_parse_rested_plus_group(parser):
    r = parse(
        parser,
        "Kobold dies, you gain 90 experience. (+45 exp Rested bonus, +10 group bonus)",
    )
    assert (r.mob, r.amount, r.kind, r.rested) == ("Kobold", 90, "kill", 45)


def test_parse_group_only(parser):
    r = parse(parser, "Kobold dies, you gain 90 experience. (+10 group bonus)")
    assert (r.mob, r.amount, r.kind) == ("Kobold", 90, "kill")
    assert r.rested is None


def test_parse_raid_penalty_only(parser):
    r = parse(parser, "Kobold dies, you gain 90 experience. (-10 raid penalty)")
    assert (r.mob, r.amount, r.kind) == ("Kobold", 90, "kill")
    assert r.rested is None


def test_parse_rested_plus_raid(parser):
    r = parse(
        parser,
        "Kobold dies, you gain 90 experience. (+45 exp Rested bonus, -10 raid penalty)",
    )
    assert (r.mob, r.amount, r.rested) == ("Kobold", 90, 45)


def test_parse_exhaustion4_penalty_is_not_rested(parser):
    r = parse(
        parser, "Kobold dies, you gain 30 experience. (-15 exp Exhausted penalty)"
    )
    assert (r.mob, r.amount, r.kind) == ("Kobold", 30, "kill")
    assert r.rested is None
    assert r.penalty == 15


def test_parse_exhaustion5_penalty_group(parser):
    r = parse(
        parser,
        "Kobold dies, you gain 30 experience. (-15 exp Exhausted penalty, +5 group bonus)",
    )
    assert (r.mob, r.amount, r.rested, r.penalty) == ("Kobold", 30, None, 15)


def test_parse_unnamed_is_other(parser):
    r = parse(parser, "You gain 250 experience.")
    assert r.kind == "other" and r.amount == 250 and r.mob is None


def test_parse_unnamed_group_is_other(parser):
    r = parse(parser, "You gain 250 experience. (+25 group bonus)")
    assert r.kind == "other" and r.amount == 250 and r.mob is None


def test_parse_quest_is_other_with_rested(parser):
    r = parse(parser, "You gain 500 experience. (+250 exp Rested bonus)")
    assert r.kind == "other" and r.amount == 500 and r.mob is None and r.rested == 250


def test_parse_third_person_ignored(parser):
    assert parse(parser, "Arthas gains 90 experience.") is None


def test_reject_unrelated_message(parser):
    assert parse(parser, "You have entered a rested area.") is None
    assert parse(parser, "") is None


def test_parse_non_string_and_secret(parser):
    assert parse(parser, None) is None
    assert parse(parser, 12) is None
    assert (
        parse(parser, "Kobold dies, you gain 90 experience.", lambda v: False) is None
    )
    assert (
        parse(parser, "Kobold dies, you gain 90 experience.", lambda v: True).amount
        == 90
    )


@pytest.mark.parametrize(
    "mob",
    ["Defias Pillager", "Gath'Ilzogg", "Lord Kazzak, the Doomwalker", "Mr. Smite-Bot"],
)
def test_mob_names_with_spaces_and_punctuation(parser, mob):
    plain = parse(parser, f"{mob} dies, you gain 120 experience.")
    assert (plain.mob, plain.amount) == (mob, 120)
    rested = parse(
        parser,
        f"{mob} dies, you gain 120 experience. (+60 exp Rested bonus, +12 group bonus)",
    )
    assert (rested.mob, rested.amount, rested.rested) == (mob, 120, 60)


def test_plain_pattern_does_not_shadow_rested(parser):
    """Longest-first plus the $ anchor: a rested message must not come back as a plain kill."""
    r = parse(
        parser, "Defias Pillager dies, you gain 90 experience. (+45 exp Rested bonus)"
    )
    assert r.rested == 45 and r.mob == "Defias Pillager"


# ---- positional-format fake -----------------------------------------------------------------------------------


def test_positional_format_fake(env):
    env.load_addon()
    g = env.lua.table_from({"COMBATLOG_XPGAIN_FIRSTPERSON": "%2$d XP von %1$s"})
    p = env.ns.XPParse.Build(g)
    r = parse(p, "75 XP von Kobold")
    assert (r.mob, r.amount, r.kind) == ("Kobold", 75, "kill")


# ---- flow: chat "other" messages never feed the matcher -----------------------------------------------------


def test_other_kind_is_not_a_matcher_input(env, parser):
    """Caller contract (Kills.lua): only kind == 'kill' goes to AddKillXP; the PLAYER_XP_UPDATE delta yields 'other'."""
    clock = [0.0]
    m = env.ns.KillMatcher.New(env.lua.table_from({"now": lambda: clock[0]}))
    for msg in (
        "You gain 250 experience.",
        "You gain 500 experience. (+250 exp Rested bonus)",
    ):
        r = parse(parser, msg)
        assert r.kind == "other"
        if r.kind == "kill":  # what the caller does
            m.AddKillXP(m, env.lua.table_from({"amount": r.amount}))
    m.AddDelta(m, 250)
    clock[0] = 0.4
    bursts = lua_list(m.Poll(m))
    assert [(b.kind, b.amount) for b in bursts] == [("other", 250)]
    assert m.Stats(m).tier4 == 0
