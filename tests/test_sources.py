"""S4: per-source origins. Quest turn-ins and exploration XP take their own start point (Sources.lua + the matcher's
source hints); everything else keeps the old centre point, and kills are never delayed or reclassified."""

import pytest
from conftest import lua_list
from test_killmatcher import Rig
from test_m5 import build

CENTRE = (
    960,
    702,
)  # UIParent 1920x1080: 50% width, 65% height (the old non-kill point)
QUEST_DEFAULT = (576, 648)  # 30% width, 60% height
EXPLORE_DEFAULT = (960, 810)  # 50% width, 75% height


class World:
    """The whole addon on the M2/M3/M5 stubs, Orbs:Burst replaced by a recorder."""

    def __init__(self, env, **build_options):
        self.e = build(env, **build_options)
        self.ns, self.stub, self.lua = env.ns, env.stub, env.lua
        env.db.debug = True
        env.db.questBursts = True
        self.calls = self.lua.table()
        self.ns.Orbs = self.lua.eval(
            "function(calls) return { Burst = function(self, a) calls[#calls + 1] = a end } end"
        )(self.calls)
        self.world_frame = self.frame("WorldFrame")
        self.xp = 0

    def frame(self, name, cx=0, cy=0, shown=True, rect=None):
        f = self.stub.namedFrame(name)
        f.cx, f.cy, f.shown = cx, cy, shown
        if rect:  # left, bottom, width, height
            f.left, f.bottom, f.width, f.height = rect
        return f

    def gain(self, amount):
        self.xp += amount
        self.stub.setXP(self.xp)

    def run(self, seconds):
        self.e.run(seconds)

    def fire(self, event, *args):
        self.ns.fire(event, *args)

    def cursor(self, x, y, over):
        self.stub.cursor.x, self.stub.cursor.y = x, y
        self.stub.focus = over

    def bursts(self):
        return [self.calls[i] for i in range(1, len(self.calls) + 1)]

    def log(self):
        return [str(x) for x in lua_list(self.e.db.log)] if self.e.db.log else []

    def burst_lines(self):
        return [
            line for line in self.log() if " BURST " in line or line.startswith("BURST")
        ]

    def errors(self):
        return [
            line
            for line in self.log()
            if "Sources error" in line or "poll error" in line
        ]


@pytest.fixture
def w(env):
    return World(env)


def point(burst):
    return (burst["x"], burst["y"])


# ---------------------------------------------------------------- quests


def test_quest_xp_after_the_turn_in_starts_at_the_cursor_over_the_quest_window(w):
    w.frame("QuestFrame", 700, 400, rect=(500, 200, 400, 400))
    button = w.frame("CompleteButton", 700, 400)
    w.cursor(700, 400, button)
    w.fire("QUEST_TURNED_IN", 11, 120, 5)
    w.gain(120)
    w.run(1.0)
    (burst,) = w.bursts()
    assert point(burst) == (700, 400) and burst["kind"] == "other"
    (line,) = w.burst_lines()
    assert (
        "kind=other" in line
        and "origin=cursor" in line
        and line.endswith("source=quest")
    )


def test_quest_xp_before_the_turn_in_still_gets_the_quest_origin(w):
    w.frame("QuestFrame", 700, 400, rect=(200, 100, 700, 500))
    button = w.frame("CompleteButton", 700, 400)
    w.cursor(300, 250, button)
    w.gain(120)
    w.run(0.1)
    w.fire("QUEST_TURNED_IN", 11, 120, 5)
    w.run(1.0)
    (burst,) = w.bursts()
    assert point(burst) == (300, 250)
    assert w.burst_lines()[0].endswith("source=quest")


def test_world_focus_uses_the_cached_quest_window_centre(w):
    quest_frame = w.frame("QuestFrame", 500, 620)
    w.cursor(900, 500, w.world_frame)
    w.fire("QUEST_COMPLETE")
    quest_frame.shown = False  # the window is gone by the time the reward is paid
    w.fire("QUEST_FINISHED")
    w.fire("QUEST_TURNED_IN", 11, 90, 0)
    w.gain(90)
    w.run(1.0)
    (burst,) = w.bursts()
    assert point(burst) == (500, 620)
    assert "origin=questwindow" in w.burst_lines()[0]


def test_cursor_over_a_non_quest_frame_uses_the_cached_quest_window(w):
    # a keyboard turn-in with the mouse resting over the chat frame must not start the orbs there
    quest_frame = w.frame("QuestFrame", 500, 620, rect=(300, 420, 400, 400))
    chat = w.frame("ChatFrame1", 150, 150, rect=(0, 0, 300, 300))
    w.cursor(150, 150, chat)
    w.fire("QUEST_COMPLETE")
    quest_frame.shown = False
    w.fire("QUEST_TURNED_IN", 11, 90, 0)
    w.gain(90)
    w.run(1.0)
    assert point(w.bursts()[0]) == (500, 620)
    assert "origin=questwindow" in w.burst_lines()[0]


def test_cursor_inside_the_cached_quest_window_rect_is_the_origin(w):
    quest_frame = w.frame("QuestFrame", 500, 620, rect=(300, 420, 400, 400))
    w.cursor(
        650, 450, w.world_frame
    )  # over the window's button, which has closed by the turn-in
    w.fire("QUEST_COMPLETE")
    quest_frame.shown = False
    w.fire("QUEST_TURNED_IN", 11, 90, 0)
    w.gain(90)
    w.run(1.0)
    assert point(w.bursts()[0]) == (650, 450)
    assert "origin=cursor" in w.burst_lines()[0]


def test_cursor_over_a_visible_frame_with_no_quest_window_uses_the_default(w):
    chat = w.frame("ChatFrame1", 150, 150, rect=(0, 0, 300, 300))
    w.cursor(150, 150, chat)
    w.fire("QUEST_TURNED_IN", 11, 90, 0)
    w.gain(90)
    w.run(1.0)
    assert point(w.bursts()[0]) == QUEST_DEFAULT
    assert "origin=questdefault" in w.burst_lines()[0]


def test_a_visible_quest_frame_is_read_live_at_the_turn_in(w):
    w.frame("QuestFrame", 450, 700)
    w.cursor(900, 500, w.world_frame)
    w.fire("QUEST_TURNED_IN", 11, 90, 0)
    w.gain(90)
    w.run(1.0)
    assert point(w.bursts()[0]) == (450, 700)


def test_a_known_replacement_window_wins_over_blizzards_quest_frame(w):
    w.frame("QuestFrame", 100, 100)
    w.frame("DaylightUINpc", 640, 500)
    w.cursor(900, 500, w.world_frame)
    w.fire("QUEST_COMPLETE")
    w.fire("QUEST_TURNED_IN", 11, 90, 0)
    w.gain(90)
    w.run(1.0)
    assert point(w.bursts()[0]) == (640, 500)


def test_a_window_parked_off_screen_is_not_an_origin(w):
    w.frame("QuestFrame", -3000, 500)
    w.cursor(900, 500, w.world_frame)
    w.fire("QUEST_COMPLETE")
    w.fire("QUEST_TURNED_IN", 11, 90, 0)
    w.gain(90)
    w.run(1.0)
    assert point(w.bursts()[0]) == QUEST_DEFAULT


def test_no_cursor_frame_and_no_window_uses_the_left_of_centre_default(w):
    w.cursor(900, 500, w.world_frame)
    w.fire("QUEST_TURNED_IN", 11, 90, 0)
    w.gain(90)
    w.run(1.0)
    (burst,) = w.bursts()
    assert point(burst) == QUEST_DEFAULT
    assert "origin=questdefault" in w.burst_lines()[0]


@pytest.mark.parametrize("reward", ["secret", 0, None])
def test_unreadable_or_zero_reward_takes_the_nearest_delta(w, reward):
    w.cursor(900, 500, w.world_frame)
    w.fire(
        "QUEST_COMPLETE"
    )  # the open dialog is what lets an amount-less hint claim a delta
    w.fire("QUEST_TURNED_IN", 11, w.stub.SECRET if reward == "secret" else reward, 0)
    w.gain(77)
    w.run(1.0)
    (burst,) = w.bursts()
    assert point(burst) == QUEST_DEFAULT
    assert w.burst_lines()[0].endswith("source=quest")


def test_a_delta_that_differs_from_the_reward_still_takes_the_quest_origin(w):
    # XP boosts, food or a level-cap clip make the real XP differ from the reported reward
    w.cursor(900, 500, w.world_frame)
    w.fire("QUEST_TURNED_IN", 11, 120, 0)
    w.gain(150)
    w.run(1.0)
    (burst,) = w.bursts()
    assert point(burst) == QUEST_DEFAULT
    assert w.burst_lines()[0].endswith("source=quest")


def test_a_delta_long_after_the_turn_in_stays_plain_other(w):
    w.cursor(900, 500, w.world_frame)
    w.fire("QUEST_TURNED_IN", 11, 120, 0)
    w.run(0.8)  # beyond the matcher's nearest window
    w.gain(50)
    w.run(1.0)
    (burst,) = w.bursts()
    assert point(burst) == CENTRE
    assert w.burst_lines()[0].endswith(
        "origin=centre plate=no est=none w=0.00 restedSrc=none source=other"
    )


# ---------------------------------------------------------------- exploration


def test_exploration_message_then_delta_starts_at_the_zone_text(w):
    w.frame("SubZoneTextFrame", 960, 900)
    w.fire("CHAT_MSG_SYSTEM", "Discovered Goldshire: 150 experience gained")
    w.gain(150)
    w.run(1.0)
    (burst,) = w.bursts()
    assert point(burst) == (960, 900)
    (line,) = w.burst_lines()
    assert "origin=zonetext" in line and line.endswith("source=explore")


def test_exploration_delta_then_message_with_the_default_top_centre(w):
    w.gain(150)
    w.run(0.1)
    w.fire("CHAT_MSG_SYSTEM", "Discovered Goldshire: 150 experience gained.")
    w.run(1.0)
    (burst,) = w.bursts()
    assert point(burst) == EXPLORE_DEFAULT
    assert "origin=exploredefault" in w.burst_lines()[0]


def test_a_hidden_zone_text_is_not_used(w):
    w.frame("SubZoneTextFrame", 960, 900, shown=False)
    w.frame("ZoneTextFrame", 960, 950)
    w.fire("CHAT_MSG_SYSTEM", "Discovered Goldshire: 150 experience gained")
    w.gain(150)
    w.run(1.0)
    assert point(w.bursts()[0]) == (960, 950)


def test_other_system_messages_and_other_amounts_are_not_exploration(w):
    w.fire("CHAT_MSG_SYSTEM", "You are now Rested.")
    w.fire("CHAT_MSG_SYSTEM", "Discovered Goldshire: 150 experience gained")
    w.run(0.8)  # the 40 XP lands too long after the discovery to belong to it
    w.gain(40)
    w.run(1.0)
    (burst,) = w.bursts()
    assert point(burst) == CENTRE
    assert w.burst_lines()[0].endswith("source=other")


# ---------------------------------------------------------------- everything else, kills, safety


def test_an_unrelated_delta_stays_other_at_the_old_centre_point(w):
    w.gain(30)
    w.run(1.0)
    (burst,) = w.bursts()
    assert point(burst) == CENTRE and burst["kind"] == "other"
    (line,) = w.burst_lines()
    assert "origin=centre" in line and line.endswith("source=other")


def test_kills_are_never_delayed_or_reclassified_by_a_quest_hint(w):
    w.fire("QUEST_COMPLETE")  # a hint is expected
    w.cursor(900, 500, w.world_frame)
    w.fire("QUEST_TURNED_IN", 11, 50, 0)  # same amount as the kill below
    w.stub.addPlate(
        "nameplate1",
        w.lua.table_from({"guid": "G1", "name": "Boar", "cx": 300, "cy": 200}),
    )
    w.run(0.05)
    w.fire("UNIT_DIED", "G1")
    w.fire("CHAT_MSG_COMBAT_XP_GAIN", "Boar dies, you gain 50 experience.")
    w.gain(50)
    w.run(0.1)  # shorter than every wait in the matcher
    (burst,) = w.bursts()
    assert burst["kind"] == "kill"
    w.run(3.0)
    assert [b["kind"] for b in w.bursts()] == [
        "kill"
    ]  # the hint expired unused; nothing became "other"
    assert "source=" not in w.burst_lines()[0]


def test_secret_values_never_throw(w):
    secret = w.stub.SECRET
    w.frame("QuestFrame", secret, secret)
    w.frame("SubZoneTextFrame", secret, secret)
    w.cursor(secret, secret, secret)
    w.fire("QUEST_COMPLETE")
    w.fire("QUEST_TURNED_IN", secret, secret, secret)
    w.fire("CHAT_MSG_SYSTEM", secret)
    w.gain(60)
    w.run(1.0)
    w.fire("CHAT_MSG_SYSTEM", "Discovered Goldshire: 60 experience gained")
    w.gain(60)
    w.run(1.0)
    assert w.errors() == []
    assert [point(b) for b in w.bursts()] == [QUEST_DEFAULT, EXPLORE_DEFAULT]


def test_missing_apis_never_throw(env):
    w = World(env, mouse_foci=False)
    w.lua.execute("GetCursorPosition = nil; GetMouseFocus = nil")
    w.fire("QUEST_TURNED_IN", 11, 60, 0)
    w.gain(60)
    w.run(1.0)
    assert w.errors() == [] and point(w.bursts()[0]) == QUEST_DEFAULT


def test_no_onupdate_remains_once_everything_has_settled(w):
    w.cursor(900, 500, w.world_frame)
    w.fire("QUEST_COMPLETE")
    w.fire("QUEST_TURNED_IN", 11, 60, 0)
    w.fire(
        "CHAT_MSG_SYSTEM", "Discovered Goldshire: 150 experience gained"
    )  # a hint nobody claims
    w.gain(60)
    w.run(0.2)
    assert (
        w.ns.Kills.pollFrame.scripts.OnUpdate is not None
    )  # the scan below does see a live poller
    w.run(4.0)
    assert [f for f in lua_list(w.stub.frames) if f.scripts.OnUpdate is not None] == []
    assert w.ns.Kills.matcher.Pending(w.ns.Kills.matcher) == 0


def test_sources_registers_only_its_own_events(w):
    registered = w.ns.Sources.registered
    assert {k: registered[k] for k in registered} == {
        "QUEST_TURNED_IN": True,
        "QUEST_COMPLETE": True,
        "QUEST_PROGRESS": True,
        "QUEST_FINISHED": True,
        "CHAT_MSG_SYSTEM": True,
    }


# ---------------------------------------------------------------- matcher (pure logic)


@pytest.fixture
def rig(env):
    return Rig(env)


def hint(rig, **kw):
    rig.m.AddSourceHint(rig.m, rig.tbl(**kw))


def test_matcher_hint_before_delta(rig):
    hint(rig, source="quest", amount=120, x=10, y=20, label="cursor")
    rig.at(0.1)
    rig.delta(120)
    rig.at(0.6)
    (b,) = rig.poll()
    assert (b.kind, b.source, b.x, b.y, b.label, b.amount) == (
        "other",
        "quest",
        10,
        20,
        "cursor",
        120,
    )
    assert rig.m.Pending(rig.m) == 0 or rig.poll() == []


def test_matcher_hint_after_delta_within_the_wait(rig):
    rig.delta(120)
    rig.at(0.3)
    hint(rig, source="explore", amount=120, x=1, y=2, label="zonetext")
    rig.at(0.45)
    (b,) = rig.poll()
    assert b.source == "explore" and (b.x, b.y) == (1, 2)


def test_matcher_expected_source_adds_a_short_wait_and_only_then(rig):
    rig.m.ExpectSource(rig.m, 30)
    rig.delta(120)
    rig.at(0.45)
    assert rig.poll() == []  # held: a hint may still arrive
    hint(rig, source="quest", amount=120, x=5, y=6, label="cursor")
    rig.at(0.5)
    (b,) = rig.poll()
    assert b.source == "quest"


def test_matcher_expected_source_wait_is_capped(rig):
    rig.m.ExpectSource(rig.m, 30)
    rig.delta(120)
    rig.at(0.65)
    assert rig.poll() == []
    rig.at(0.71)
    (b,) = rig.poll()
    assert b.source is None and b.x is None  # 0.4 + 0.3 at most, then plain "other"


def test_matcher_without_expectation_does_not_wait(rig):
    rig.delta(120)
    rig.at(0.41)
    (b,) = rig.poll()
    assert b.source is None


def test_matcher_hint_with_a_different_amount_matches_by_time(rig):
    hint(rig, source="quest", amount=1000, x=1, y=2)
    rig.delta(1100)  # XP boost: more than the reported reward
    rig.at(0.5)
    (b,) = rig.poll()
    assert b.source == "quest" and (b.x, b.y) == (1, 2) and b.amount == 1100


def test_matcher_exact_amount_beats_a_nearer_inexact_hint(rig):
    hint(rig, source="quest", amount=500, x=1, y=1)  # exact, but further away
    rig.at(0.4)
    hint(rig, source="quest", amount=900, x=2, y=2)  # nearer, wrong amount
    rig.delta(500)
    rig.at(0.9)
    (b,) = rig.poll()
    assert (b.x, b.y) == (1, 1)


def test_matcher_inexact_hint_outside_the_window_does_not_match(rig):
    hint(rig, source="quest", amount=1000, x=1, y=2)
    rig.at(0.6)  # beyond nearestWindow
    rig.delta(1100)
    rig.at(1.1)
    (b,) = rig.poll()
    assert b.source is None


def test_matcher_hint_outside_the_time_window_does_not_match(rig):
    hint(rig, source="quest", amount=120)
    rig.at(1.5)
    rig.delta(
        120
    )  # 1.5 s after the hint: beyond the 1 s window, though the hint is still alive
    rig.at(1.95)
    (b,) = rig.poll()
    assert b.source is None


def test_matcher_amountless_hint_takes_only_a_close_delta(rig):
    rig.m.ExpectSource(rig.m, 30)
    hint(rig, source="quest", x=1, y=2)
    rig.at(0.7)
    rig.delta(33)  # 0.7 s from the hint: too far for an amount-less hint
    rig.at(1.5)  # deltaWait + the expected-source wait
    (b,) = rig.poll()
    assert b.source is None
    rig.at(1.3)
    hint(rig, source="quest", x=3, y=4)
    rig.delta(44)
    rig.at(1.8)
    (b,) = rig.poll()
    assert b.source == "quest" and (b.x, b.y) == (3, 4)


def test_matcher_amountless_hint_needs_an_expected_source(rig):
    hint(
        rig, source="quest", x=1, y=2
    )  # no dialog was open: nothing says this delta is the quest's
    rig.delta(33)
    rig.at(0.5)
    (b,) = rig.poll()
    assert b.source is None


def test_matcher_amountless_hint_does_not_take_a_delta_a_death_could_claim(rig):
    rig.m.ExpectSource(rig.m, 30)
    rig.death("d1")  # unpaired: its chat line is unreadable, the delta may be its XP
    hint(rig, source="quest", x=1, y=2)
    rig.at(0.1)
    rig.delta(33)
    rig.at(0.9)  # deltaWait + the expected-source wait
    (b,) = rig.poll()
    assert b.source is None and b.kind == "other"


def test_matcher_inexact_hint_does_not_take_a_delta_a_death_could_claim(rig):
    # an exploration hint (always an amount) must not grab a kill's XP of another amount on timing alone
    rig.death("d1")
    hint(rig, source="explore", amount=40, x=1, y=2)
    rig.at(0.1)
    rig.delta(33)
    rig.at(0.9)
    (b,) = rig.poll()
    assert b.source is None and b.kind == "other"


def test_matcher_amountless_hint_does_not_take_a_delta_a_secret_marker_could_claim(rig):
    rig.m.ExpectSource(rig.m, 30)
    rig.m.AddSecretChat(rig.m)  # the matching death has not shown up yet
    hint(rig, source="quest", x=1, y=2)
    rig.at(0.1)
    rig.delta(33)
    rig.at(0.9)
    (b,) = rig.poll()
    assert b.source is None


def test_matcher_amountless_hint_takes_the_delta_once_the_death_expired(rig):
    rig.m.ExpectSource(rig.m, 30)
    rig.death("d1")
    rig.at(1.6)  # the death is past deathTTL and expires; the delta is quest XP
    hint(rig, source="quest", x=1, y=2)
    rig.delta(33)
    rig.at(2.1)
    out = rig.poll()
    assert [b.source for b in out] == ["quest"]


def test_matcher_picks_the_hint_closest_in_time_and_consumes_it(rig):
    hint(rig, source="quest", amount=50, x=1, y=1)
    rig.at(0.8)
    hint(rig, source="quest", amount=50, x=2, y=2)
    rig.delta(50)
    rig.delta(50)
    rig.at(1.3)
    first, second = rig.poll()
    assert (first.x, first.y) == (2, 2)  # the closer hint first
    assert (second.x, second.y) == (1, 1)  # then the other one, each hint used once
    rig.delta(50)
    rig.at(1.8)
    (third,) = rig.poll()
    assert third.source is None


def test_matcher_locate_is_called_at_emission_and_a_failing_one_is_harmless(rig):
    calls = []

    def locate():
        calls.append(rig.t)
        return 7, 8, "zonetext"

    hint(rig, source="explore", amount=10, locate=locate)
    rig.delta(10)
    assert calls == []
    rig.at(0.5)
    (b,) = rig.poll()
    assert calls == [0.5] and (b.x, b.y, b.label) == (7, 8, "zonetext")

    def broken():
        raise RuntimeError("boom")

    rig.at(1.0)
    hint(rig, source="explore", amount=11, locate=broken)
    rig.delta(11)
    rig.at(1.5)
    (b,) = rig.poll()
    assert b.source == "explore" and b.x is None


def test_matcher_unused_hints_expire_and_do_not_leave_work_pending(rig):
    hint(rig, source="quest", amount=10)
    assert rig.m.Pending(rig.m) == 1
    rig.at(2.1)
    assert rig.poll() == []
    assert rig.m.Pending(rig.m) == 0


def test_matcher_kills_ignore_hints(rig):
    hint(rig, source="quest", amount=90, x=1, y=1)
    rig.death("d1", tier=1)
    rig.at(0.1)
    rig.chat(90)
    rig.delta(90)
    (b,) = rig.poll()
    assert b.kind == "kill" and b.source is None and b.x is None


# ---------------------------------------------------------------- the exploration message reader


def test_amount_reader_reads_the_discovery_message(env):
    env.load_addon()
    read = env.ns.XPParse.AmountReader(env.G.ERR_ZONE_EXPLORED_XP)
    assert read("Discovered Elwynn Forest: 150 experience gained") == 150
    assert read("Discovered Elwynn Forest: 150 experience gained.") == 150
    assert read("Discovered: Elwynn Forest") is None
    assert read(None) is None


def test_amount_reader_is_safe_with_positional_arguments_and_bad_formats(env):
    env.load_addon()
    read = env.ns.XPParse.AmountReader("%2$d Erfahrung fuer %1$s")
    assert read("90 Erfahrung fuer Wald") == 90
    assert env.ns.XPParse.AmountReader("no arguments here") is None
    assert env.ns.XPParse.AmountReader(42) is None
