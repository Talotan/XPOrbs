"""M3: plate tracker + kill pipeline, driven through the WoW stub (stubs_m3.lua)."""

import pytest
from conftest import TESTS, lua_list

CHAT = "Boar dies, you gain 50 experience."
CHAT_RESTED = "Boar dies, you gain 50 experience. (+25 exp Rested bonus)"


class Game:
    def __init__(self, env, probe=True, debug=True):
        self.env = env
        self.ns = env.ns
        self.stub = env.ns.stub
        env.load_chunk(TESTS / "stubs_m3.lua", "stubs_m3.lua")(env.ns)
        env.load_addon()
        env.ns.fire("ADDON_LOADED", "XPOrbs")
        self.db = env.G.XPOrbsDB
        self.db.debug = debug
        self.db.probe = probe
        self.stub.xp, self.stub.xpMax = 0, 1000
        env.ns.fire("PLAYER_ENTERING_WORLD")
        self.calls = env.lua.table()
        self.fake_orbs = None

    def fake_orbs_on(self):
        self.ns.Orbs = self.env.lua.eval(
            "function(calls) return { Burst = function(self, a) calls[#calls + 1] = a end } end"
        )(self.calls)

    def plate(self, unit="nameplate1", **opts):
        return self.stub.addPlate(unit, self.env.lua.table_from(opts))

    def tick(self, dt, n=1):
        for _ in range(n):
            self.stub.tick(dt)

    def chat(self, msg=CHAT):
        self.ns.fire("CHAT_MSG_COMBAT_XP_GAIN", msg)

    def log(self):
        return [str(x) for x in lua_list(self.db.log)] if self.db.log else []

    def has_log(self, needle):
        return any(needle in line for line in self.log())

    def stats(self):
        s = self.ns.Kills.matcher.Stats(self.ns.Kills.matcher)
        return {
            k: s[k] for k in ("tier1", "tier2", "tier3", "tier4", "dropped", "other")
        }

    def bursts(self):
        return [self.calls[i] for i in range(1, len(self.calls) + 1)]


@pytest.fixture
def game(env):
    return Game(env)


def test_tier2_plate_removed_dead_then_chat(env):
    g = Game(env, probe=False)
    g.fake_orbs_on()
    g.plate(guid="G1", name="Boar", cx=700, cy=400)
    g.tick(0.05)  # sampler runs
    g.stub.removePlate("nameplate1", True)
    g.chat()
    g.tick(0.1)
    assert g.stats()["tier2"] == 1 and g.stats()["tier1"] == 0
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (700, 400)
    assert b["n"] == 14 and b["scale"] == 1 and b["nPurple"] == 0 and b["kind"] == "kill"
    assert g.has_log(
        "BURST tier=2 kind=kill amount=50 rested=nil hadXY=true origin=plate probe=false"
    )


def test_tier1_unit_died_guid_match(env):
    g = Game(env)
    g.plate(guid="G1", name="Boar", cx=300, cy=200)
    g.tick(0.05)
    env.ns.fire("UNIT_DIED", "G1")
    g.stub.removePlate(
        "nameplate1", True
    )  # removal after UNIT_DIED must not add a second death
    g.chat()
    g.tick(0.1)
    assert g.stats()["tier1"] == 1 and g.stats()["tier2"] == 0
    assert g.has_log("UNIT_DIED guidReadable=true matched=true")
    assert g.has_log(
        "BURST tier=1 kind=kill amount=50 rested=nil hadXY=true origin=plate probe=true"
    )


def test_unit_died_after_tier2_is_not_a_duplicate(env):
    g = Game(env)
    g.plate(guid="G1", cx=300, cy=200)
    g.tick(0.05)
    g.stub.removePlate("nameplate1", True)
    env.ns.fire(
        "UNIT_DIED", "G1"
    )  # late: matches the held entry, which already has its tier-2 death
    g.chat()
    g.tick(2.0)
    s = g.stats()
    assert s["tier2"] == 1 and s["tier1"] == 0 and s["dropped"] == 0


def test_unit_died_matches_held_plate_when_not_dead_at_removal(env):
    g = Game(env)
    g.plate(guid="G1", cx=300, cy=200)
    g.tick(0.05)
    g.stub.removePlate(
        "nameplate1", False
    )  # health not yet zero when the plate went away
    env.ns.fire("UNIT_DIED", "G1")
    g.chat()
    g.tick(0.1)
    assert g.stats()["tier1"] == 1


def test_secret_values_fall_through_to_tier4(env):
    g = Game(env)
    secret = g.stub.SECRET
    g.plate(guid=secret, name=secret, cx=secret, cy=secret)
    g.stub.units["nameplate1"].dead = secret
    g.stub.units["nameplate1"].hp = secret
    g.tick(0.05, 3)
    env.ns.fire("UNIT_DIED", secret)
    g.stub.removePlate("nameplate1")
    g.chat()
    g.tick(0.6)
    s = g.stats()
    assert s["tier4"] == 1 and s["tier1"] == 0 and s["tier2"] == 0
    assert env.ns.Plates.stats["secretGeom"] > 0
    assert g.has_log("UNIT_DIED guidReadable=false matched=false")
    assert g.has_log("PLATE_REMOVED deadReadable=false")


def test_unreadable_guid_on_unit_died_falls_through_to_tier2(env):
    g = Game(env)
    g.plate(guid=g.stub.SECRET, cx=500, cy=300)
    g.tick(0.05)
    env.ns.fire("UNIT_DIED", g.stub.SECRET)
    g.stub.removePlate("nameplate1", True)
    g.chat()
    g.tick(0.1)
    s = g.stats()
    assert s["tier2"] == 1 and s["tier1"] == 0


def test_everything_secret_does_not_crash(env):
    g = Game(env)
    g.plate(guid="G1", cx=1, cy=1)
    g.stub.secretAll = True
    g.tick(0.05, 3)
    env.ns.fire("UNIT_DIED", "G1")
    g.stub.removePlate("nameplate1", True)
    g.chat()
    g.stub.setXP(50)
    g.tick(1.0, 3)
    assert (
        env.ns.Plates.TargetEntry(env.ns.Plates) is None or True
    )  # must simply not raise
    assert not g.has_log("error")


def test_held_plate_ttl_expires(env):
    g = Game(env)
    g.plate(guid="G1", cx=300, cy=200)
    g.stub.removePlate("nameplate1", False)
    plates = env.ns.Plates
    assert plates.FindByGUID(plates, "G1") is not None
    assert plates.HeldCount(plates) == 1
    g.tick(1.9)
    assert plates.FindByGUID(plates, "G1") is not None
    g.tick(0.2)
    assert plates.FindByGUID(plates, "G1") is None
    assert plates.HeldCount(plates) == 0


def test_sampler_and_poller_go_idle(env):
    g = Game(env)
    plates, kills = env.ns.Plates, env.ns.Kills
    assert not plates.SamplerActive(plates) and not kills.PollActive(kills)
    assert g.stub.updaters() == 0
    g.plate(guid="G1", cx=300, cy=200)
    assert plates.SamplerActive(plates)
    g.stub.removePlate("nameplate1", True)
    assert not plates.SamplerActive(plates)
    g.chat()
    assert kills.PollActive(kills)
    g.tick(0.1)
    assert kills.PollActive(kills)  # chat paired; the delta is still owed for up to 1 s
    g.tick(0.5, 4)
    assert not kills.PollActive(kills)
    assert g.stub.updaters() == 0


def test_friendly_plate_does_not_start_sampler(env):
    g = Game(env)
    g.plate(guid="F1", canAttack=False)
    assert not env.ns.Plates.SamplerActive(env.ns.Plates)


def test_sampler_is_throttled_to_about_30hz(env):
    g = Game(env)
    p = g.plate(guid="G1", cx=100, cy=100)
    ok0 = env.ns.Plates.stats["okGeom"]
    g.tick(0.01, 3)  # below 1/30 s in total
    assert env.ns.Plates.stats["okGeom"] == ok0
    g.tick(0.01)
    assert env.ns.Plates.stats["okGeom"] == ok0 + 1
    p.cx = 200
    g.tick(0.05)
    assert env.ns.Plates.entries["nameplate1"]["x"] == 200


def test_amountcheck_logged_equal_and_unequal(env):
    g = Game(env)
    g.chat()
    g.stub.setXP(50)
    assert g.has_log("AMOUNTCHECK chat=50 delta=50 equal=true")
    g.tick(1.0, 2)
    g.chat(
        CHAT_RESTED
    )  # chat says 50 but the bar moved by 75 (rested double-counted by the client)
    g.stub.setXP(125)
    assert g.has_log("AMOUNTCHECK chat=50 delta=75 equal=false")


def test_amountcheck_delta_before_chat(env):
    g = Game(env)
    g.stub.setXP(50)
    g.chat()
    assert g.has_log("AMOUNTCHECK chat=50 delta=50 equal=true")


def test_amountcheck_not_logged_outside_window(env):
    g = Game(env)
    g.chat()
    g.tick(1.5)
    g.stub.setXP(50)
    assert not g.has_log("AMOUNTCHECK")


def test_probe_on_never_calls_orbs(env):
    g = Game(env, probe=True)
    g.fake_orbs_on()
    g.plate(guid="G1", cx=300, cy=200)
    g.tick(0.05)
    g.stub.removePlate("nameplate1", True)
    g.chat()
    g.stub.setXP(50)
    g.tick(0.5, 4)
    assert len(g.bursts()) == 0
    assert g.stats()["tier2"] == 1


def test_probe_off_calls_orbs_once_with_expected_n(env):
    g = Game(env, probe=False)
    g.fake_orbs_on()
    g.plate(guid="G1", cx=300, cy=200)
    g.tick(0.05)
    g.stub.removePlate("nameplate1", True)
    g.chat()
    g.stub.setXP(50)  # delta claims the kill: no extra "other" burst
    g.tick(0.5, 4)
    (b,) = g.bursts()
    assert b["n"] == 14  # 5% of a level -> (3 + 5 * sqrt(5)) at multiplier 100
    assert b["scale"] == 1 and b["nPurple"] == 0 and b["kind"] == "kill"
    assert (b["x"], b["y"]) == (300, 200)


def test_probe_off_rested_split(env):
    g = Game(env, probe=False)
    g.fake_orbs_on()
    g.plate(guid="G1", cx=300, cy=200)
    g.tick(0.05)
    g.stub.removePlate("nameplate1", True)
    g.chat(CHAT_RESTED)
    g.tick(0.1)
    (b,) = g.bursts()
    assert b["n"] == 14 and b["nPurple"] == 7  # floor(14 * 25 / 50 + 0.5)


def test_tier4_falls_back_to_target_then_screen_centre(env):
    g = Game(env, probe=False)
    g.fake_orbs_on()
    g.plate(guid="G1", cx=640, cy=360, isTarget=True)
    g.tick(0.05)
    g.chat()
    g.tick(0.6)
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (640, 360)
    assert g.has_log("tier=4 kind=kill amount=50 rested=nil hadXY=false origin=target")


def test_tier4_screen_centre_when_no_target(env):
    g = Game(env, probe=False)
    g.fake_orbs_on()
    g.chat()
    g.tick(0.6)
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (960, 702)
    assert g.has_log("origin=centre")


def test_target_entry_returns_numeric_xy_or_nil(env):
    g = Game(env)
    plates = env.ns.Plates
    assert plates.TargetEntry(plates) is None
    g.plate(guid="G1", cx=111, cy=222, isTarget=True)
    te = plates.TargetEntry(plates)
    assert te["x"] == 111 and te["y"] == 222
    g.stub.removePlate("nameplate1", True)
    g.stub.units["nameplate1"].isTarget = False
    env.ns.fire("PLAYER_TARGET_CHANGED")
    te = plates.TargetEntry(plates)  # cached last target position
    assert te["x"] == 111 and te["y"] == 222


def test_grey_mob_death_is_dropped_and_quest_is_other(env):
    g = Game(env)
    g.plate(guid="G1", cx=300, cy=200)
    g.tick(0.05)
    g.stub.removePlate("nameplate1", True)  # dead, but no XP message follows
    g.tick(0.5, 4)
    assert g.stats()["dropped"] == 1
    g.stub.setXP(400)  # quest turn-in: delta without a chat kill
    g.tick(0.5)
    assert g.stats()["other"] == 1
    assert g.has_log("BURST tier=4 kind=other amount=400")


def test_level_up_delta_wraps(env):
    g = Game(env)
    g.stub.xp, g.stub.xpMax = 900, 1000
    env.ns.fire("PLAYER_ENTERING_WORLD")
    env.ns.fire("PLAYER_LEVEL_UP")
    g.stub.setXP(50, 1200)
    assert g.has_log("XPUPDATE delta=150 leveled=true")
    assert g.has_log("PLAYER_LEVEL_UP")


def test_unit_died_registered_and_combat_log_never(env):
    g = Game(env)
    assert env.ns.Kills.unitDiedRegistered is True
    for f in g.stub.frames.values():
        assert f.events["COMBAT_LOG_EVENT_UNFILTERED"] is None


def test_unit_died_registration_failure_is_survived(env):
    lua_stub_fail = env.load_chunk(TESTS / "stubs_m3.lua", "stubs_m3.lua")
    lua_stub_fail(env.ns)
    env.ns.stub.failEvents["UNIT_DIED"] = True
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    assert env.ns.Kills.unitDiedRegistered is False


def test_status_lines(env):
    g = Game(env)
    g.plate(guid="G1", cx=1, cy=1)
    env.G.SlashCmdList.XPORBS("status")
    chat = [str(g.stub.chat[i]) for i in range(1, len(g.stub.chat) + 1)]
    assert any(
        "plates: tracked=1 held=0 secretGeom=0" in m and "sampler=active" in m
        for m in chat
    )
    assert any(
        "kills: tier1=0" in m and "probe=on" in m and "UNIT_DIED=yes" in m for m in chat
    )


def test_debug_off_logs_nothing(env):
    g = Game(env, debug=False)
    g.plate(guid="G1")
    g.chat()
    g.tick(1.0)
    assert not g.db.log
