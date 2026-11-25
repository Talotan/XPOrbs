-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Core: loaded first. Owns the saved-variable schema (defaults, slider ranges, migration from older saves and
-- sanitising of hand-edited ones), the debug log ring (ns:Log), the style helpers shared by the options and the
-- kill pipeline, and the /xporbs slash command table (other files add their own entries to ns.commands).

ns.defaults = {
    enabled = true,
    -- size, density and opacity are the ACTIVE values of the current orb shape (everything else reads these): each
    -- shape keeps its own in shapeLook, swapped in by ns.SetOrbShape and written through by ns.SetLook
    density = 100, -- orb multiplier in % (100 = normal), see OrbMath.Count
    cap = 40,
    size = 14,
    opacity = 100, -- orb opacity in % (every orb texture except the arrival flash)
    flightTime = 1.0, -- seconds; used when flightMode is "time"
    flightMode = "speed", -- "speed" (orbs fly at a constant speed, so a longer way takes longer) or "time" (a fixed time)
    flightSpeed = 100, -- % of Orbs.lua's reference speed; used when flightMode is "speed"
    -- the Forever XP bar is purple (blue when rested); orbs are additive, so these are full-brightness versions
    color = { 0.72, 0.28, 1.00 },
    classColor = false, -- true: normal (non-rested) orbs use the player's class colour instead of `color`
    restedTint = true,
    restedColor = { 0.15, 0.38, 1.00 },
    trail = true,
    trailOpacity = 100, -- % of the normal trail alpha, every shape (0 draws no trail); dimmed in the UI with trail off
    questBursts = true, -- bursts for quest and other non-kill XP
    exploreBursts = true, -- bursts for exploration XP (a saved save without it copies questBursts, see InitDB)
    targetFrame = nil,
    showAtMax = false, -- at max level: a small burst of orbs flies to the portrait when an engaged hostile dies
    sound = true, -- chime as orbs arrive (new installs; a save keeps what it stored)
    -- which chime: "glass", "coin", "swish" or "pixel" (media/chime/<volume>/<voice>1-6.ogg)
    soundVoice = "glass",
    soundVolume = 100, -- chime volume in percent: pre-rendered files per level, see ns.ranges and tools/make_sounds.py
    debug = false,
    previewCluster = false, -- the orb preview window's "Cluster" tickbox: orbs pile up overlapping instead of tidy
    -- where orbs start when the mob's position is unknown: "wide" (a zoom-scaled oval) or "off" (one point, kept for
    -- future quest/exploration streams); Orbs.lua UNKNOWN. Not an Options control.
    unknownOrigin = "wide",
    -- the "Zoom-scaled spread" tickbox: the spawn spread of located orbs (pop rings, the stream's start disc) scales
    -- with camera zoom like the unknown oval (x1 at zoom 15); false = the fixed spread
    zoomSpread = true,
    style = "popstream", -- kill style (schema 6): "popstream", "crossfade" or "stream" (Direct Stream)
    -- Popstream's sub-choice: "nameplate" (pop on the nameplate) or "direct" (pop at the estimate)
    popMode = "nameplate",
    flightPath = "smooth", -- how orbs fly: "smooth" (the plain curve), "chaos" (erratic) or "helix" (spiralling)
    orbShape = "starlight", -- how orbs are drawn: "starlight", "retro" (pixel art), "globe" or "crackle" (SHAPE_LABEL)
    -- blend, pulse, sparkle and crackleSpeed are active values too (like size): the current shape's own, kept in
    -- shapeLook. The UI only shows the ones that apply to a shape: Outline (db.blend) for retro/globe/crackle, Sparkle
    -- for retro, Pulsing for globe, Crackle speed for crackle
    blend = "natural", -- the Outline option: "natural" (additive glow, no outline) or "solid" (opaque with a dark rim)
    pulse = false, -- Globe orbs gently swell and shrink
    sparkle = true,
    crackleSpeed = 100, -- Crackle's bolt animation rate in % (200 = the bolts change twice as fast)
    -- the look each orb shape remembers (see ns.SHAPE_LOOK_KEYS); a missing or broken entry gets these. Retro's size
    -- is "screen px per art pixel" (ns.RETRO_SIZE_RANGE), the others' is the orb size in px
    shapeLook = {
        starlight = { size = 14, density = 100, opacity = 100, blend = "natural", pulse = false, sparkle = true,
            crackleSpeed = 100 },
        retro = { size = 2, density = 75, opacity = 100, blend = "natural", pulse = false, sparkle = true,
            crackleSpeed = 100 },
        globe = { size = 14, density = 100, opacity = 100, blend = "natural", pulse = false, sparkle = true,
            crackleSpeed = 100 },
        crackle = { size = 14, density = 100, opacity = 100, blend = "natural", pulse = false, sparkle = true,
            crackleSpeed = 100 },
    },
    glow = true, -- arrival flash on/off
    -- "bar" (horizontal flash on the fill edge), "vertical" (the same flash upright, filling bottom to top) or "round"
    -- (circular glow at the frame centre)
    glowShape = "bar",
    glowIntensity = 100, -- arrival flash strength in percent (25-200): scales its alpha and, a little, its size
    glowOffsetX = 0, -- UIParent px added to the landing point (where orbs aim and the glow is drawn)
    glowOffsetY = 0,
    setupDismissed = false, -- true: the "find your XP bar" window (Setup.lua) never opens by itself
    -- the minimap button (Minimap.lua); LibDBIcon also keeps its own minimapPos in here, so unknown keys must survive
    minimap = { hide = false },
    -- zoom-aware mob anchor (Orbs.lua): orbs sit (zoomA + zoomB / max(cameraZoom, zoomMin)) px below the plate;
    -- the defaults are a least-squares fit to in-game calibration points.
    -- Not in ns.ranges on purpose: these are calibrated with /xporbs calib, not sliders.
    zoomAnchor = true,
    zoomA = 5,
    zoomB = 175,
    zoomMin = 5,
    zoomPoints = {}, -- calibration samples { z = camera zoom, off = px below the plate }, newest last, at most 8
}

local ZOOM_POINTS_MAX = 8

-- Slider ranges { min, max, step }: the options panel builds its sliders from these and InitDB clamps saved values
-- to them, so a hand-edited or corrupt SavedVariables file can't feed the renderer nonsense.
ns.ranges = {
    density = { 25, 400, 25 },
    cap = { 5, 80, 1 },
    size = { 8, 32, 1 },
    opacity = { 20, 100, 5 },
    crackleSpeed = { 50, 200, 10 },
    trailOpacity = { 0, 100, 5 },
    flightTime = { 0.4, 1.5, 0.05 },
    flightSpeed = { 50, 250, 10 },
    glowOffsetX = { -100, 100, 1 },
    glowOffsetY = { -100, 100, 1 },
    glowIntensity = { 25, 200, 5 },
    soundVolume = { 100, 250, 25 }, -- one folder of chime files per step: media/chime/<volume>/
}

-- Modules add lines to /xporbs status by appending functions that return a string (or nil).
ns.statusProviders = {}

local LOG_MAX = 500
local LOG_SLACK = 100 -- the ring is trimmed back to LOG_MAX in one pass once it is this far over

local function deepFill(target, source)
    for k, v in pairs(source) do
        if type(v) == "table" then
            if type(target[k]) ~= "table" then
                target[k] = {}
            end
            deepFill(target[k], v)
        elseif target[k] == nil then
            target[k] = v
        end
    end
end

local SCHEMA = 6

-- Kill styles (schema 6): three archetypes, Popstream with a Nameplate / Direct sub-choice. Every name a save, a slash
-- command or a test may hold -> { style, popMode (nil: keep the current one), true: switch Zoom-scaled spread on }.
-- The 1.1 / P2 names map as: streampop = Popstream (Direct), wide / mob (the dropped wide burst) = Popstream
-- (Nameplate) + Zoom-scaled spread.
local STYLE_ALIAS = {
    popstream = { "popstream" },
    crossfade = { "crossfade" },
    stream = { "stream" },
    directstream = { "stream" },
    streampop = { "popstream", "direct" },
    wide = { "popstream", "nameplate", true },
    mob = { "popstream", "nameplate", true },
}
ns.STYLE_ALIAS = STYLE_ALIAS
ns.STYLE_LABEL = { popstream = "Popstream", crossfade = "Crossfade", stream = "Direct Stream" }
ns.POPMODE_LABEL = { nameplate = "Nameplate", direct = "Direct" }
ns.PATH_ORDER = { "smooth", "chaos", "helix" }
ns.PATH_LABEL = { smooth = "Smooth", chaos = "Chaos", helix = "Helix" } -- the valid db.flightPath values
ns.SHAPE_ORDER = { "starlight", "retro", "globe", "crackle" }
ns.SHAPE_LABEL = { starlight = "Starlight", retro = "Retro", globe = "Globe", crackle = "Crackle" } -- valid db.orbShape
ns.SHAPE_ALIAS = { power = "crackle", wisp = "globe" } -- the first names of these shapes, still accepted
-- what each shape remembers
ns.SHAPE_LOOK_KEYS = { "size", "density", "opacity", "blend", "pulse", "sparkle", "crackleSpeed" }
local RETRO_SIZE_RANGE = { 1, 7, 1 } -- Retro's size is px per art pixel, not an orb size
ns.RETRO_SIZE_RANGE = RETRO_SIZE_RANGE
ns.RETRO_K = 24 / 14 -- Retro px per size unit: size 14 (Starlight's units) is a 24 px orb

-- The generic orb size, in the size units Starlight's db.size uses, of the active look. Retro stores px per art pixel,
-- so its orb (8 art pixels across) is db.size * 8 px, i.e. db.size * 8 / RETRO_K units; every other shape stores it.
function ns.OrbSize(db)
    if db.orbShape == "retro" then
        return db.size * 8 / ns.RETRO_K
    end
    return db.size
end

-- { min, max, step } of a SHAPE_LOOK_KEYS key for a shape; nil for the non-numeric keys.
function ns.ShapeRange(shape, key)
    if shape == "retro" and key == "size" then
        return RETRO_SIZE_RANGE
    end
    return ns.ranges[key]
end

-- The shape a name stands for (a current name or an old alias), or nil.
function ns.CanonShape(name)
    if type(name) ~= "string" then
        return nil
    end
    name = ns.SHAPE_ALIAS[name] or name
    return ns.SHAPE_LABEL[name] and name or nil
end

-- A shape's default for one of ns.SHAPE_LOOK_KEYS.
function ns.ShapeDefault(shape, key)
    local looks = ns.defaults.shapeLook
    return (looks[shape] or looks[ns.defaults.orbShape])[key]
end

-- The saved look entry of a shape (made when missing).
local function lookOf(db, shape)
    if type(db.shapeLook) ~= "table" then
        db.shapeLook = {}
    end
    if type(db.shapeLook[shape]) ~= "table" then
        db.shapeLook[shape] = {}
    end
    return db.shapeLook[shape]
end

-- Stores the active look (ns.SHAPE_LOOK_KEYS) as `shape`'s own.
local function storeLook(db, shape)
    local look = lookOf(db, shape)
    for _, key in ipairs(ns.SHAPE_LOOK_KEYS) do
        look[key] = db[key]
    end
end

-- Makes `shape`'s remembered look the active one.
local function loadLook(db, shape)
    local look = lookOf(db, shape)
    for _, key in ipairs(ns.SHAPE_LOOK_KEYS) do
        db[key] = look[key] == nil and ns.ShapeDefault(shape, key) or look[key]
    end
end

-- Switches the orb shape (any name or alias; false when it is none): the active look goes to the
-- old shape's entry and the new shape's come in. The one way the Options dropdown and /xporbs shape change it.
function ns.SetOrbShape(name)
    local shape = ns.CanonShape(name)
    if not shape then
        return false
    end
    local db = ns.db
    if not db then
        ns:InitDB()
        db = ns.db
    end
    if shape ~= db.orbShape then
        storeLook(db, ns.CanonShape(db.orbShape) or ns.defaults.orbShape)
        db.orbShape = shape
        loadLook(db, shape)
    end
    return true
end

-- Writes one of ns.SHAPE_LOOK_KEYS: the active value and the current shape's entry (what the controls do).
function ns.SetLook(key, value)
    local db = ns.db
    db[key] = value
    lookOf(db, ns.CanonShape(db.orbShape) or ns.defaults.orbShape)[key] = value
end

-- The renderer's own style for a style name (any alias) and a popMode: "popstream" (pop on the nameplate),
-- "streampop" (pop at the estimate, screen space), "crossfade" or "stream". Unknown names give the default.
function ns.RenderStyle(style, popMode)
    local alias = STYLE_ALIAS[style] or STYLE_ALIAS[ns.defaults.style]
    if alias[1] ~= "popstream" then
        return alias[1]
    end
    return (alias[2] or popMode) == "direct" and "streampop" or "popstream"
end

-- Player-facing name of the db's style, e.g. "Popstream (Nameplate)" or "Direct Stream".
function ns.StyleLabel(db)
    local style = db.style
    if style == "popstream" then
        return "Popstream (" .. (ns.POPMODE_LABEL[db.popMode] or "Nameplate") .. ")"
    end
    return ns.STYLE_LABEL[style] or tostring(style)
end

-- Writes a style name (any alias) into db; false when the name isn't one. Aliases that carry a popMode or the
-- zoom-scaled spread set them.
function ns.SetStyle(db, name)
    local alias = STYLE_ALIAS[name]
    if not alias then
        return false
    end
    db.style = alias[1]
    if alias[2] then
        db.popMode = alias[2]
    end
    if alias[3] then
        db.zoomSpread = true
    end
    return true
end
local OLD_COLOR, OLD_RESTED = { 0.35, 0.65, 1.0 }, { 0.7, 0.45, 1.0 }
-- the 1.0.x defaults, replaced by the schema-5 ones when a save still holds them
local V4_COLOR, V4_RESTED, V4_FLIGHT = { 0.20, 0.50, 1.00 }, { 1.0, 0.30, 0.85 }, 0.75

local function sameColour(colour, reference)
    if type(colour) ~= "table" then
        return false
    end
    for i = 1, 3 do
        if type(colour[i]) ~= "number" or math.abs(colour[i] - reference[i]) > 0.005 then
            return false
        end
    end
    return true
end

-- v2: new default colours. Only colours still equal to the old defaults are replaced (deepFill re-adds them).
-- v3: kills go live; the probe-only mode is gone (v0.17 also drops a stored `probe` key at every load).
-- v4: the stream origin is always the target frame (then the screen centre); the origin option is gone.
-- v5: purple/blue orbs to match the XP bar and a 1.0 s flight: only values still equal to the 1.0.x defaults are
-- replaced (a custom colour or flight time is kept).
-- v6: three kill styles. popstream -> Popstream (Nameplate), streampop -> Popstream (Direct), wide / mob -> Popstream
-- (Nameplate) with Zoom-scaled spread on (zoomSpread, new, default on), crossfade and stream unchanged, anything
-- else -> the default (STYLE_ALIAS).
-- v0.13 added classColor / glow / glowShape, v0.14 added glowIntensity / glowOffsetX / glowOffsetY and the orb shape
-- added orbShape: no schema bump, deepFill adds the missing keys (a stored false or an existing value is never
-- overwritten, a missing key gets the default).
local function migrate(db)
    local version = type(db.version) == "number" and db.version or 0
    if version < 2 then
        if sameColour(db.color, OLD_COLOR) then
            db.color = nil
        end
        if sameColour(db.restedColor, OLD_RESTED) then
            db.restedColor = nil
        end
    end
    db.probe = nil -- removed in v0.17; harmless if left behind, but there is nothing to read it
    if version < 4 then
        db.origin = nil
        db.corpsePop = nil
        db.style = "popstream"
    end
    if version < 5 then
        if sameColour(db.color, V4_COLOR) then
            db.color = nil
        end
        if sameColour(db.restedColor, V4_RESTED) then
            db.restedColor = nil
        end
        if type(db.flightTime) == "number" and math.abs(db.flightTime - V4_FLIGHT) <= 0.005 then
            db.flightTime = nil
        end
    end
    if version < 6 then
        if db.style == "popstream" then
            db.popMode = "nameplate" -- the 1.1 popstream (a v5 save has no popMode yet)
        end
        if not ns.SetStyle(db, db.style) then
            db.style = nil -- deepFill gives the default
        end
    end
end

local BOOLEANS = {
    "enabled", "classColor", "restedTint", "trail", "questBursts", "exploreBursts", "showAtMax", "debug", "glow",
    "sound", "zoomAnchor", "zoomSpread", "setupDismissed", "previewCluster",
}
local ZOOM_RANGES = { zoomA = { -100, 300 }, zoomB = { 0, 3000 }, zoomMin = { 0.5, 10 } }
ns.ZOOM_POINTS_MAX = ZOOM_POINTS_MAX
ns.zoomRanges = ZOOM_RANGES -- { min, max } per key; Calib.lua clamps fitted values with these
local COLOURS = { "color", "restedColor" }

local function copyColour(colour)
    return { colour[1], colour[2], colour[3] }
end

local function validColour(colour)
    if type(colour) ~= "table" then
        return false
    end
    for i = 1, 3 do
        local channel = colour[i]
        if type(channel) ~= "number" or channel ~= channel then
            return false
        end
    end
    return true
end

-- Forces every saved setting into a form the renderer can use: numbers clamped to their slider range (a non-number
-- becomes the default), colours three numbers in 0..1, enums one of their allowed words, flags real booleans. Never
-- throws and never touches the version, the log or unknown keys.
local function sanitize(db)
    local defaults, Snap = ns.defaults, ns.OrbMath.Snap
    for key, range in pairs(ns.ranges) do
        local value = Snap(db[key], range[1], range[2], range[3])
        if value == nil then
            value = defaults[key]
        end
        db[key] = value
    end
    for _, key in ipairs(COLOURS) do
        local colour = db[key]
        if validColour(colour) then
            for i = 1, 3 do
                colour[i] = math.max(0, math.min(1, colour[i]))
            end
        else
            db[key] = copyColour(defaults[key])
        end
    end
    -- the hue and saturation the colour picker last had per colour key (so black keeps its hue): { h, s } in 0..1 for
    -- the two colour keys; anything else is dropped. No default: it only exists once the player has used the picker.
    if db.colorHS ~= nil then
        local hs, cleanHS = db.colorHS, {}
        if type(hs) == "table" then
            for _, key in ipairs(COLOURS) do
                local pair = hs[key]
                if type(pair) == "table" and type(pair[1]) == "number" and type(pair[2]) == "number"
                    and pair[1] == pair[1] and pair[2] == pair[2]
                    and pair[1] >= 0 and pair[1] <= 1 and pair[2] >= 0 and pair[2] <= 1 then
                    cleanHS[key] = { pair[1], pair[2] }
                end
            end
        end
        db.colorHS = next(cleanHS) ~= nil and cleanHS or nil
    end
    -- an old name in a schema-6 save (hand-edited, or written by an older copy) is mapped like the v6 migration
    local styleName = db.style
    local isCurrentName = styleName == "popstream" or styleName == "crossfade" or styleName == "stream"
    if not isCurrentName and not ns.SetStyle(db, styleName) then
        db.style = defaults.style
    end
    if db.popMode ~= "nameplate" and db.popMode ~= "direct" then
        db.popMode = defaults.popMode
    end
    if db.flightMode ~= "speed" and db.flightMode ~= "time" then
        db.flightMode = defaults.flightMode
    end
    if not ns.PATH_LABEL[db.flightPath] then
        db.flightPath = defaults.flightPath
    end
    db.orbShape = ns.CanonShape(db.orbShape) or defaults.orbShape -- (maps the old names power and wisp)
    -- every shape's remembered look: missing, partial or broken entries fall back to that shape's defaults, values
    -- are snapped to the slider ranges (per shape: Retro's size has its own); then the current shape's entry becomes
    -- the active look. This must stay AFTER the first loop above, which snaps db.size with the plain 8-32 range:
    -- loadLook overwrites that with the shape's own value (and sets db.blend / pulse / sparkle).
    if type(db.shapeLook) ~= "table" then
        db.shapeLook = {}
    end
    for shape in pairs(ns.SHAPE_LABEL) do
        local look = lookOf(db, shape)
        for _, key in ipairs(ns.SHAPE_LOOK_KEYS) do
            local value, range = look[key], ns.ShapeRange(shape, key)
            if range then
                value = Snap(value, range[1], range[2], range[3])
            elseif key == "blend" then
                value = (value == "natural" or value == "solid") and value or nil
            elseif type(value) ~= "boolean" then
                value = nil -- pulse, sparkle
            end
            if value == nil then
                value = ns.ShapeDefault(shape, key)
            end
            look[key] = value
        end
    end
    loadLook(db, db.orbShape)
    if db.unknownOrigin ~= "off" and db.unknownOrigin ~= "wide" then -- also maps the dropped "late"/"inplace"
        db.unknownOrigin = defaults.unknownOrigin
    end
    if db.glowShape ~= "bar" and db.glowShape ~= "vertical" and db.glowShape ~= "round" then
        db.glowShape = defaults.glowShape
    end
    -- older voice names still load: glassa/glassb/brush/ding became glass/coin/swish/pixel (a saved "coin" is the
    -- original coin, which is what coin has always meant to released versions)
    local VOICE_ALIAS = { glassa = "glass", glassb = "coin", brush = "swish", ding = "pixel" }
    db.soundVoice = VOICE_ALIAS[db.soundVoice] or db.soundVoice
    if db.soundVoice ~= "glass" and db.soundVoice ~= "coin"
        and db.soundVoice ~= "swish" and db.soundVoice ~= "pixel" then
        db.soundVoice = defaults.soundVoice
    end
    for _, key in ipairs(BOOLEANS) do
        if type(db[key]) ~= "boolean" then
            db[key] = defaults[key]
        end
    end
    if type(db.minimap) ~= "table" then
        db.minimap = { hide = defaults.minimap.hide }
    elseif type(db.minimap.hide) ~= "boolean" then
        db.minimap.hide = defaults.minimap.hide -- other keys (LibDBIcon's minimapPos) are left alone
    end
    -- Saved settings that still hold the three old untouched defaults were never calibrated: give them the fitted
    -- curve. Any other combination is the player's own and stays (no schema bump needed).
    if db.zoomA == 10 and db.zoomB == 500 and db.zoomMin == 2 then
        db.zoomA, db.zoomB, db.zoomMin = defaults.zoomA, defaults.zoomB, defaults.zoomMin
    end
    for key, range in pairs(ZOOM_RANGES) do
        local value = db[key]
        if type(value) == "number" and value == value and value ~= math.huge and value ~= -math.huge then
            db[key] = math.max(range[1], math.min(range[2], value))
        else
            db[key] = defaults[key]
        end
    end
    local points, clean = db.zoomPoints, {}
    if type(points) == "table" then
        for _, point in ipairs(points) do
            local zoom, offset = type(point) == "table" and point.z, type(point) == "table" and point.off
            -- finite numbers only (x ~= x is the NaN test), zoom positive
            if type(zoom) == "number" and zoom == zoom and zoom > 0 and zoom ~= math.huge
                and type(offset) == "number" and offset == offset and math.abs(offset) ~= math.huge then
                clean[#clean + 1] = { z = zoom, off = offset }
            end
        end
    end
    while #clean > ZOOM_POINTS_MAX do
        table.remove(clean, 1) -- oldest dropped
    end
    db.zoomPoints = clean
    if db.targetFrame ~= nil and type(db.targetFrame) ~= "string" then
        db.targetFrame = nil
    end
end

-- The look revision: 2 = per-shape look (size / density / opacity / blend / pulse / sparkle). A save without a
-- shapeLook is the released 1.3.0 (Starlight only, no orbShape): its size, density and opacity become Starlight's look
-- and every other shape starts from its defaults (a save that does name a shape gives its look to that one).
-- db.lookRev records that this ran, so it happens once. Runs before deepFill so a missing key isn't filled first.
local LOOK_REV = 2

local function migrateLook(db)
    if type(db.lookRev) == "number" and db.lookRev >= LOOK_REV then
        return
    end
    if db.shapeLook == nil then
        local shape = ns.CanonShape(db.orbShape) or "starlight" -- 1.3.0 saved no orbShape: Starlight only
        db.orbShape = shape
        db.shapeLook = { [shape] = { size = db.size, density = db.density, opacity = db.opacity } }
    end
    db.lookRev = LOOK_REV
end

-- A save that has a flight time but no flight speed gets the speed that flies the same typical way in that time
-- (100 % = 1 s, see Orbs.lua REF_SPEED), once. Runs before deepFill so the missing speed isn't filled with 100 first.
local function migrateFlightSpeed(db)
    if db.flightSpeed == nil and type(db.flightTime) == "number" and db.flightTime > 0 then
        local r = ns.ranges.flightSpeed
        local speed = math.floor(100 / db.flightTime / r[3] + 0.5) * r[3]
        db.flightSpeed = math.max(r[1], math.min(r[2], speed))
    end
end

function ns:InitDB()
    if type(XPOrbsDB) ~= "table" then
        XPOrbsDB = {}
    end
    migrate(XPOrbsDB)
    -- exploreBursts was split off questBursts: a save that predates it keeps what the player chose for both
    if XPOrbsDB.exploreBursts == nil and type(XPOrbsDB.questBursts) == "boolean" then
        XPOrbsDB.exploreBursts = XPOrbsDB.questBursts
    end
    migrateLook(XPOrbsDB)
    migrateFlightSpeed(XPOrbsDB)
    deepFill(XPOrbsDB, ns.defaults)
    sanitize(XPOrbsDB)
    -- a save from a newer addon version keeps its number (stamping it down would make the next upgrade re-migrate)
    if type(XPOrbsDB.version) ~= "number" or XPOrbsDB.version < SCHEMA then
        XPOrbsDB.version = SCHEMA
    end
    ns.db = XPOrbsDB
end

-- True when the player is at the level cap. Unavailable APIs, errors and secret values count as "not at max".
-- /xporbs debug maxlevel on sets ns.debugForceMax (session only, never saved) so this can be tested below the cap.
function ns.AtMaxLevel()
    if ns.debugForceMax then
        return true
    end
    local okLevel, level = pcall(UnitLevel, "player")
    local okMax, maxLevel = pcall(GetMaxPlayerLevel)
    if okLevel and okMax and type(level) == "number" and type(maxLevel) == "number"
        and not (issecretvalue and (issecretvalue(level) or issecretvalue(maxLevel))) then
        return level >= maxLevel
    end
    return false
end

function ns:Log(fmt, ...)
    local db = ns.db
    if not db or not db.debug then
        return
    end
    local ok, text = pcall(string.format, fmt, ...)
    if not ok then
        text = "(log format error) " .. tostring(fmt)
    end
    local log = db.log
    if type(log) ~= "table" then
        log = {}
        db.log = log
    end
    local n = #log + 1
    log[n] = GetTime() .. " " .. text
    if n > LOG_MAX + LOG_SLACK then
        -- trim in one pass instead of shifting the whole array for every line over the limit
        local drop = n - LOG_MAX
        for i = 1, LOG_MAX do
            log[i] = log[i + drop]
        end
        for i = LOG_MAX + 1, n do
            log[i] = nil
        end
    end
end

local function say(msg)
    DEFAULT_CHAT_FRAME:AddMessage("|cff59a6ffXPOrbs|r: " .. msg)
end
ns.Print = say

-- Modules replace entries here (e.g. ns.commands.test = function(arg) ... end) instead of editing Core.lua.
local commands = {}
ns.commands = commands

function commands.help()
    say("commands:")
    say("/xporbs - open the settings panel (the same as /xporbs options)")
    say("/xporbs help - this list")
    say("/xporbs debug on|off - toggle debug logging")
    say("/xporbs debug maxlevel on|off - pretend to be at max level (this session only)")
    say("/xporbs sound on|off|glass|coin|swish|pixel - chime when orbs arrive (the name picks the sound)")
    say("/xporbs status - show addon state")
    say("/xporbs test [pct] [rested] [style] [smooth|chaos|helix] - fire a test burst on your target")
    say("/xporbs test stress [n] - fire n test bursts over about 2 seconds (default 20, max 100)")
    say("/xporbs perf [reset] - addon memory, driver frame time and pool usage")
    say("/xporbs style popstream [nameplate|direct] | crossfade | stream - kill style:")
    say("  Popstream (Nameplate): a pop on the nameplate, then a stream from the estimated mob position (pop needs "
        .. "the nameplate)")
    say("  Popstream (Direct): a pop at the estimated mob position that flows into the stream (no nameplate)")
    say("  Crossfade: a pop on the nameplate, the orbs reappear just above the bar (nameplate; estimate sets the "
        .. "direction)")
    say("  stream = Direct Stream: a plain stream from the estimated mob position (no pop, no nameplate)")
    say("/xporbs path smooth|chaos|helix - flight pathing: a clean arc, an erratic wobble or a spiral (no arg: show)")
    say("/xporbs shape starlight|retro|globe|crackle - orb shape: soft stars, pixel art, glowing globes or "
        .. "crackling orbs (no arg: show). Size, quantity and opacity are remembered per shape")
    say("/xporbs pulse on|off - Globe orbs gently swell and shrink (no arg: show)")
    say("/xporbs wide on|off - zoom-scaled spread: pops and stream starts spread wider when zoomed in, tighter "
        .. "zoomed out (on by default)")
    say("/xporbs unknown wide|off - where orbs start when the mob's position is unknown")
    say("/xporbs pop on|off - alias: popstream / stream")
    say("/xporbs pick [clear|FrameName] - click to pick the XP bar frame, or name it (clear = auto-detect)")
    say("/xporbs setup - open the XP bar setup window: pick the bar, set the glow shape and landing offset, and test")
    say("/xporbs zoomanchor on|off - anchor orbs on the mob's body using the camera zoom (no arg: show state)")
    say("/xporbs calib [off|reset|fit|save] - calibrate the zoom anchor on a targeted mob")
    say("/xporbs reset - restore default settings")
    say("/xporbs minimap on|off - show or hide the minimap button")
    say("/xporbs options - open the settings panel")
end

function commands.debug(arg)
    local force = string.match(arg or "", "^maxlevel%s*(%S*)")
    if force then
        if force == "on" then
            ns.debugForceMax = true
        elseif force == "off" then
            ns.debugForceMax = nil
        else
            say("usage: /xporbs debug maxlevel on|off (currently " .. (ns.debugForceMax and "on" or "off") .. ")")
            return
        end
        say("debug maxlevel " .. (ns.debugForceMax and "on" or "off") .. " (this session only)")
        return
    end
    if arg == "on" then
        ns.db.debug = true
    elseif arg == "off" then
        ns.db.debug = false
    else
        say("usage: /xporbs debug on|off|maxlevel on|off (currently " .. (ns.db.debug and "on" or "off") .. ")")
        return
    end
    say("debug " .. (ns.db.debug and "on" or "off"))
    if ns.Options and ns.Options.Refresh then
        ns.Options:Refresh()
    end
end

function commands.status()
    local db = ns.db
    local version = "?"
    if C_AddOns and C_AddOns.GetAddOnMetadata then
        local ok, versionText = pcall(C_AddOns.GetAddOnMetadata, ADDON, "Version")
        if ok and versionText then
            version = versionText
        end
    end
    say("XPOrbs " .. version .. " (db schema " .. tostring(db.version) .. "), enabled=" .. tostring(db.enabled)
        .. ", debug=" .. tostring(db.debug))
    local logCount = type(ns.db.log) == "table" and #ns.db.log or 0
    say("log entries: " .. logCount)
    for _, provider in ipairs(ns.statusProviders) do
        local ok, line = pcall(provider)
        if ok and line then
            say(line)
        elseif not ok then
            say("status error: " .. tostring(line))
        end
    end
end

-- /xporbs test, style, pop, pick, setup and options are defined by Orbs.lua, Target.lua, Setup.lua and Options.lua.

-- Restore every setting to its default. The schema version, the look revision, the debug flag and the log are kept.
function commands.reset()
    local db = ns.db
    for key in pairs(db) do
        if key ~= "version" and key ~= "log" and key ~= "debug" and key ~= "minimap"
            and key ~= "lookRev" then
            db[key] = nil
        end
    end
    -- LibDBIcon holds the minimap table itself and writes its own minimapPos in it: only hide is reset, in place
    if type(db.minimap) == "table" then
        db.minimap.hide = nil
    else
        db.minimap = nil
    end
    deepFill(db, ns.defaults)
    sanitize(db)
    if ns.Minimap then
        ns.Minimap.Reapply()
    end
    if ns.Options and ns.Options.Refresh then
        ns.Options:Refresh()
    end
    say("settings reset to defaults")
end

SLASH_XPORBS1 = "/xporbs"
SlashCmdList.XPORBS = function(input)
    if not ns.db then
        ns:InitDB()
    end
    local cmd, rest = string.match(input or "", "^%s*(%S*)%s*(.-)%s*$")
    cmd = string.lower(cmd or "")
    if cmd == "" then
        cmd = "options" -- no argument: the same as the minimap button's left-click
    end
    local fn = commands[cmd]
    if fn then
        fn(string.lower(rest or ""), rest or "") -- 2nd arg: the typed case, for pick FrameName
    else
        say("unknown command '" .. cmd .. "'")
        commands.help()
    end
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:SetScript("OnEvent", function(_, event, name)
    if event == "ADDON_LOADED" and name == ADDON then
        ns:InitDB()
    end
end)
ns.eventFrame = frame
