local ADDON, ns = ...

ns.defaults = {
    enabled = true,
    density = 100,
    cap = 40,
    size = 14,
    flightTime = 0.75,
    color = { 0.35, 0.65, 1.0 },
    restedTint = true,
    restedColor = { 0.7, 0.45, 1.0 },
    trail = true,
    questBursts = true,
    targetFrame = nil,
    showAtMax = false,
    debug = false,
    probe = true, -- M3: log kill bursts instead of drawing them; M4 flips this to false
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

function ns:InitDB()
    if type(XPOrbsDB) ~= "table" then
        XPOrbsDB = {}
    end
    deepFill(XPOrbsDB, ns.defaults)
    XPOrbsDB.version = 1
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
    say("/xporbs test [pct] - fire a test burst")
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
