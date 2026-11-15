"""Plate geometry fallbacks: plate unmeasurable -> proxy frame, forbidden plates, late plates, failure counters."""

from test_plates_stub import Game


def _same(g, a, b):
    return g.env.lua.eval("rawequal")(a, b)


def _entry(g, unit="nameplate1"):
    return g.ns.Plates.entries[unit]


def _make_unmeasurable(g, plate):
    g.env.lua.eval(
        'function(p) p.GetCenter = function() error("Can\'t measure restricted regions") end end'
    )(plate)


def test_plate_measurable_uses_method_a(env):
    g = Game(env)
    g.plate(guid="G1", cx=700, cy=400)
    g.tick(0.05)
    s = g.ns.Plates.stats
    assert s.okA >= 1 and s.okB == 0 and s.errA == 0
    e = _entry(g)
    assert (e.x, e.y) == (700, 400)
    assert e.proxy is None


def test_unmeasurable_plate_falls_back_to_proxy(env):
    g = Game(env)
    plate = g.plate(guid="G1", cx=700, cy=400)
    _make_unmeasurable(g, plate)
    g.tick(0.05)
    e = _entry(g)
    proxy = e.proxy
    assert proxy is not None
    # The proxy is anchored CENTER-to-CENTER on the plate.
    pt = proxy.points[1]
    assert pt[1] == "CENTER" and _same(g, pt[2], plate) and pt[3] == "CENTER"
    # In game the proxy's centre follows the plate; emulate that.
    proxy.cx, proxy.cy = 640, 360
    g.tick(0.05)
    s = g.ns.Plates.stats
    assert s.errA >= 1 and s.okB >= 1
    assert (e.x, e.y) == (640, 360)
    assert g.has_log("GEOM_ERR method=A err=")
    assert sum("GEOM_ERR method=A" in line for line in g.log()) == 1  # logged once


def test_proxy_released_to_pool_on_removal(env):
    g = Game(env)
    plate = g.plate(guid="G1", cx=700, cy=400)
    _make_unmeasurable(g, plate)
    g.tick(0.05)
    proxy = _entry(g).proxy
    g.stub.removePlate("nameplate1", True)
    assert proxy.shown is False
    assert len(proxy.points) == 0
    # The next unmeasurable plate reuses the pooled proxy.
    plate2 = g.plate("nameplate2", guid="G2")
    _make_unmeasurable(g, plate2)
    g.tick(0.05)
    assert _same(g, _entry(g, "nameplate2").proxy, proxy)


def test_forbidden_plate_is_counted_and_skipped(env):
    g = Game(env)
    plate = g.plate(guid="G1", cx=700, cy=400)
    g.env.lua.eval("function(p) p.IsForbidden = function() return true end end")(plate)
    g.tick(0.05)
    assert g.ns.Plates.stats.forbidden >= 1
    assert (
        g.ns.Plates.stats.okA == 1
    )  # only the sample taken at add time, before it was marked forbidden


def test_late_plate_is_picked_up_by_sampler(env):
    g = Game(env)
    plate = g.plate(guid="G1", cx=700, cy=400)
    g.stub.plates["nameplate1"] = None
    _entry(g).plate = None
    _entry(g).x = None
    g.tick(0.05)
    assert g.ns.Plates.stats.noPlate >= 1
    g.stub.plates["nameplate1"] = plate
    g.tick(0.05)
    assert (_entry(g).x, _entry(g).y) == (700, 400)


def test_kill_from_unmeasurable_plate_gets_proxy_origin(env):
    g = Game(env, probe=False)
    g.fake_orbs_on()
    plate = g.plate(guid="G1", name="Boar", cx=700, cy=400)
    _make_unmeasurable(g, plate)
    g.tick(0.05)
    _entry(g).proxy.cx, _entry(g).proxy.cy = 512, 300
    g.tick(0.05)
    g.ns.fire("UNIT_DIED", "G1")
    g.chat()
    g.tick(0.1)
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (960, 626.4)  # plate proxies no longer feed the stream origin


def test_geom_status_line(env):
    g = Game(env)
    g.ns.commands.status()
    chat = [str(g.stub.chat[i]) for i in range(1, len(g.stub.chat) + 1)]
    assert any("geom: okA=" in line for line in chat)
