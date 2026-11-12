local ADDON, ns = ...

ns.defaults = {
    enabled = true,
    density = 100, -- orb multiplier in % (100 = normal), see OrbMath.Count
    cap = 40,
    size = 14,
    flightTime = 0.75,
    color = { 0.20, 0.50, 1.00 },
    restedTint = true,
    restedColor = { 1.0, 0.30, 0.85 },
    trail = true,
    questBursts = true,
    targetFrame = nil,
    showAtMax = false,
    debug = false,
    style = "popstream", -- kill style: "popstream" (pop at the nameplate, then stream), "crossfade" or "stream"
    probe = false, -- true: log kill bursts instead of drawing them
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
-- v3: kills go live (probe off).
-- v4: the stream origin is always the target frame (then the screen centre); the origin option is gone.
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
    if v < 3 then
        db.probe = false
    end
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

local function notYet(name)
    say(name .. ": not yet implemented")
end

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
    say("/xporbs pick - pick the XP bar frame")
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

function commands.test()
    notYet("test")
end

function commands.pick()
    notYet("pick")
end

function commands.reset()
    notYet("reset")
end

function commands.options()
    notYet("options")
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
