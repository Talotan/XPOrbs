local ADDON, ns = ...

ns.defaults = {
    enabled = true,
    density = 100, -- orb multiplier in % (100 = normal), see OrbMath.Count
    cap = 40,
    size = 14,
    flightTime = 0.75,
    color = { 0.20, 0.50, 1.00 },
    classColor = false, -- true: normal (non-rested) orbs use the player's class colour instead of `color`
    restedTint = true,
    restedColor = { 1.0, 0.30, 0.85 },
    trail = true,
    questBursts = true,
    targetFrame = nil,
    showAtMax = false,
    debug = false,
    style = "popstream", -- kill style: "popstream" (pop at the nameplate, then stream), "crossfade" or "stream"
    glow = true, -- arrival flash on/off
    glowShape = "bar", -- "bar" (horizontal flash on the fill edge) or "round" (circular glow at the frame centre)
    glowIntensity = 100, -- arrival flash strength in percent (25-200): scales its alpha and, a little, its size
    glowOffsetX = 0, -- UIParent px added to the landing point (where orbs aim and the glow is drawn)
    glowOffsetY = 0,
}

-- Modules add lines to /xporbs status by appending functions that return a string (or nil).
ns.statusProviders = {}

local LOG_MAX = 500

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

local SCHEMA = 4
local OLD_COLOR, OLD_RESTED = { 0.35, 0.65, 1.0 }, { 0.7, 0.45, 1.0 }

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
end

function ns:InitDB()
    if type(XPOrbsDB) ~= "table" then
        XPOrbsDB = {}
    end
    migrate(XPOrbsDB)
    deepFill(XPOrbsDB, ns.defaults)
    XPOrbsDB.version = SCHEMA
    ns.db = XPOrbsDB
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
    log[#log + 1] = GetTime() .. " " .. text
    while #log > LOG_MAX do
        table.remove(log, 1)
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
    say("/xporbs status - show addon state")
    say("/xporbs test [pct] [rested] [style] - fire a test burst on your target")
    say("/xporbs style popstream|crossfade|stream - kill burst style")
    say("/xporbs pop on|off - alias: popstream / stream")
    say("/xporbs pick [clear] - click to pick the XP bar frame (clear = auto-detect)")
    say("/xporbs reset - restore default settings")
    say("/xporbs options - open the settings panel")
end

function commands.debug(arg)
    if arg == "on" then
        ns.db.debug = true
    elseif arg == "off" then
        ns.db.debug = false
    else
        say("usage: /xporbs debug on|off (currently " .. (ns.db.debug and "on" or "off") .. ")")
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
        if k ~= "version" and k ~= "log" and k ~= "debug" then
            db[k] = nil
        end
    end
    deepFill(db, ns.defaults)
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
        fn(string.lower(rest or ""))
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
