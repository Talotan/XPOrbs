-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Core: loaded first. Owns the saved-variable schema (defaults, slider ranges, migration from older saves and
-- sanitising of hand-edited ones), the debug log ring (ns:Log), the style helpers shared by the options and the
-- kill pipeline, and the /xporbs slash command table (other files add their own entries to ns.commands).

ns.defaults = {
    enabled = true,
    density = 100, -- orb multiplier in % (100 = normal), see OrbMath.Count
    cap = 40,
    size = 14,
    flightTime = 1.0,
    -- the Forever XP bar is purple (blue when rested); orbs are additive, so these are full-brightness versions
    color = { 0.72, 0.28, 1.00 },
    classColor = false, -- true: normal (non-rested) orbs use the player's class colour instead of `color`
    restedTint = true,
    restedColor = { 0.15, 0.38, 1.00 },
    trail = true,
    questBursts = true, -- bursts for quest and other non-kill XP
    exploreBursts = true, -- bursts for exploration XP (a saved save without it copies questBursts, see InitDB)
    targetFrame = nil,
    showAtMax = false, -- at max level: a small burst of orbs flies to the portrait when an engaged hostile dies
    sound = false, -- chime as orbs arrive
    soundVoice = "glass", -- which chime: "coin" or "glass" (media/chime/<volume>/coin1-6.ogg, glass1-6.ogg)
    soundVolume = 100, -- chime volume in percent: pre-rendered files per level, see ns.ranges and tools/make_sounds.py
    debug = false,
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
    flightTime = { 0.4, 1.5, 0.05 },
    glowOffsetX = { -100, 100, 1 },
    glowOffsetY = { -100, 100, 1 },
    glowIntensity = { 25, 200, 5 },
    soundVolume = { 25, 250, 25 }, -- one folder of chime files per step: media/chime/<volume>/
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
-- v0.13 added classColor / glow / glowShape and v0.14 added glowIntensity / glowOffsetX / glowOffsetY: no schema bump,
-- deepFill adds the missing keys (a stored false or an existing value is never overwritten, a missing key gets the
-- default).
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
    "sound", "zoomAnchor", "zoomSpread", "setupDismissed",
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
    -- an old name in a schema-6 save (hand-edited, or written by an older copy) is mapped like the v6 migration
    local styleName = db.style
    local isCurrentName = styleName == "popstream" or styleName == "crossfade" or styleName == "stream"
    if not isCurrentName and not ns.SetStyle(db, styleName) then
        db.style = defaults.style
    end
    if db.popMode ~= "nameplate" and db.popMode ~= "direct" then
        db.popMode = defaults.popMode
    end
    if not ns.PATH_LABEL[db.flightPath] then
        db.flightPath = defaults.flightPath
    end
    if db.unknownOrigin ~= "off" and db.unknownOrigin ~= "wide" then -- also maps the dropped "late"/"inplace"
        db.unknownOrigin = defaults.unknownOrigin
    end
    if db.glowShape ~= "bar" and db.glowShape ~= "vertical" and db.glowShape ~= "round" then
        db.glowShape = defaults.glowShape
    end
    if db.soundVoice ~= "coin" and db.soundVoice ~= "glass" then
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

function ns:InitDB()
    if type(XPOrbsDB) ~= "table" then
        XPOrbsDB = {}
    end
    migrate(XPOrbsDB)
    -- exploreBursts was split off questBursts: a save that predates it keeps what the player chose for both
    if XPOrbsDB.exploreBursts == nil and type(XPOrbsDB.questBursts) == "boolean" then
        XPOrbsDB.exploreBursts = XPOrbsDB.questBursts
    end
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
    say("/xporbs sound on|off|coin|glass - chime when orbs arrive (coin or glass picks the sound)")
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
    say("/xporbs path smooth|chaos|helix - flight style: a clean arc, an erratic wobble or a spiral (no arg: show)")
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

-- Restore every setting to its default. The schema version, the debug flag and the log are kept.
function commands.reset()
    local db = ns.db
    for key in pairs(db) do
        if key ~= "version" and key ~= "log" and key ~= "debug" and key ~= "minimap" then
            db[key] = nil
        end
    end
    -- LibDBIcon holds the minimap table itself, so it is emptied in place rather than replaced
    if type(db.minimap) == "table" then
        for key in pairs(db.minimap) do
            db.minimap[key] = nil
        end
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
