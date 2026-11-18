-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

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
    questBursts = true,
    targetFrame = nil,
    showAtMax = false, -- at max level: a small burst of orbs flies to the portrait when an engaged hostile dies
    sound = false, -- chime as orbs arrive
    soundVoice = "glass", -- which chime: "coin" or "glass" (media/coin1-6.ogg, media/glass1-6.ogg)
    debug = false,
    style = "popstream", -- kill style: "popstream" (pop at the nameplate, then stream), "crossfade" or "stream"
    glow = true, -- arrival flash on/off
    glowShape = "bar", -- "bar" (horizontal flash on the fill edge) or "round" (circular glow at the frame centre)
    glowIntensity = 100, -- arrival flash strength in percent (25-200): scales its alpha and, a little, its size
    glowOffsetX = 0, -- UIParent px added to the landing point (where orbs aim and the glow is drawn)
    glowOffsetY = 0,
    -- the minimap button (Minimap.lua); LibDBIcon also keeps its own minimapPos in here, so unknown keys must survive
    minimap = { hide = false },
}

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
}

-- Modules add lines to /xporbs status by appending functions that return a string (or nil).
ns.statusProviders = {}

local LOG_MAX = 500
local LOG_SLACK = 100 -- the ring is trimmed back to LOG_MAX in one pass once it is this far over

local function deepFill(dst, src)
    for k, v in pairs(src) do
        if type(v) == "table" then
            if type(dst[k]) ~= "table" then
                dst[k] = {}
            end
            deepFill(dst[k], v)
        elseif dst[k] == nil then
            dst[k] = v
        end
    end
end

local SCHEMA = 5
local OLD_COLOR, OLD_RESTED = { 0.35, 0.65, 1.0 }, { 0.7, 0.45, 1.0 }
-- the 1.0.x defaults, replaced by the schema-5 ones when a save still holds them
local V4_COLOR, V4_RESTED, V4_FLIGHT = { 0.20, 0.50, 1.00 }, { 1.0, 0.30, 0.85 }, 0.75

local function sameColour(c, ref)
    if type(c) ~= "table" then
        return false
    end
    for i = 1, 3 do
        if type(c[i]) ~= "number" or math.abs(c[i] - ref[i]) > 0.005 then
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
-- v0.13 added classColor / glow / glowShape and v0.14 added glowIntensity / glowOffsetX / glowOffsetY: no schema bump,
-- deepFill adds the missing keys (a stored false or an existing value is never overwritten, a missing key gets the
-- default).
local function migrate(db)
    local v = type(db.version) == "number" and db.version or 0
    if v < 2 then
        if sameColour(db.color, OLD_COLOR) then
            db.color = nil
        end
        if sameColour(db.restedColor, OLD_RESTED) then
            db.restedColor = nil
        end
    end
    db.probe = nil -- removed in v0.17; harmless if left behind, but there is nothing to read it
    if v < 4 then
        db.origin = nil
        db.corpsePop = nil
        db.style = "popstream"
    end
    if v < 5 then
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
end

local BOOLEANS =
    { "enabled", "classColor", "restedTint", "trail", "questBursts", "showAtMax", "debug", "glow", "sound" }
local COLOURS = { "color", "restedColor" }

local function copyColour(c)
    return { c[1], c[2], c[3] }
end

local function validColour(c)
    if type(c) ~= "table" then
        return false
    end
    for i = 1, 3 do
        local v = c[i]
        if type(v) ~= "number" or v ~= v then
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
    for key, r in pairs(ns.ranges) do
        local v = Snap(db[key], r[1], r[2], r[3])
        if v == nil then
            v = defaults[key]
        end
        db[key] = v
    end
    for _, key in ipairs(COLOURS) do
        local c = db[key]
        if validColour(c) then
            for i = 1, 3 do
                c[i] = math.max(0, math.min(1, c[i]))
            end
        else
            db[key] = copyColour(defaults[key])
        end
    end
    if db.style ~= "popstream" and db.style ~= "crossfade" and db.style ~= "stream" then
        db.style = defaults.style
    end
    if db.glowShape ~= "bar" and db.glowShape ~= "round" then
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
    if db.targetFrame ~= nil and type(db.targetFrame) ~= "string" then
        db.targetFrame = nil
    end
end

function ns:InitDB()
    if type(XPOrbsDB) ~= "table" then
        XPOrbsDB = {}
    end
    migrate(XPOrbsDB)
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
    local okl, lvl = pcall(UnitLevel, "player")
    local okm, mx = pcall(GetMaxPlayerLevel)
    if okl and okm and type(lvl) == "number" and type(mx) == "number"
        and not (issecretvalue and (issecretvalue(lvl) or issecretvalue(mx))) then
        return lvl >= mx
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
    say("/xporbs help - this list")
    say("/xporbs debug on|off - toggle debug logging")
    say("/xporbs debug maxlevel on|off - pretend to be at max level (this session only)")
    say("/xporbs sound on|off|coin|glass - chime when orbs arrive (coin or glass picks the sound)")
    say("/xporbs status - show addon state")
    say("/xporbs test [pct] [rested] [style] - fire a test burst on your target")
    say("/xporbs test stress [n] - fire n test bursts over about 2 seconds (default 20, max 100)")
    say("/xporbs perf [reset] - addon memory, driver frame time and pool usage")
    say("/xporbs style popstream|crossfade|stream - kill burst style")
    say("/xporbs pop on|off - alias: popstream / stream")
    say("/xporbs pick [clear|FrameName] - click to pick the XP bar frame, or name it (clear = auto-detect)")
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
    local ver = "?"
    if C_AddOns and C_AddOns.GetAddOnMetadata then
        local ok, v = pcall(C_AddOns.GetAddOnMetadata, ADDON, "Version")
        if ok and v then
            ver = v
        end
    end
    say("XPOrbs " .. ver .. " (db schema " .. tostring(db.version) .. "), enabled=" .. tostring(db.enabled)
        .. ", debug=" .. tostring(db.debug))
    local n = type(ns.db.log) == "table" and #ns.db.log or 0
    say("log entries: " .. n)
    for _, provider in ipairs(ns.statusProviders) do
        local ok, line = pcall(provider)
        if ok and line then
            say(line)
        elseif not ok then
            say("status error: " .. tostring(line))
        end
    end
end

-- /xporbs test, style, pop, pick and options are defined by Orbs.lua, Target.lua and Options.lua.

-- Restore every setting to its default. The schema version, the debug flag and the log are kept.
function commands.reset()
    local db = ns.db
    for k in pairs(db) do
        if k ~= "version" and k ~= "log" and k ~= "debug" and k ~= "minimap" then
            db[k] = nil
        end
    end
    -- LibDBIcon holds the minimap table itself, so it is emptied in place rather than replaced
    if type(db.minimap) == "table" then
        for k in pairs(db.minimap) do
            db.minimap[k] = nil
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
        cmd = "help"
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
