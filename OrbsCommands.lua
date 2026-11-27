-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- The slash commands and status lines that drive the renderer (Orbs.lua, loaded right before this file): /xporbs test
-- (and its stress run, and ns.TestKill for the Test Kill buttons), perf, style, flightmode, path, shape, pulse, wide,
-- unknown and pop, plus the status providers for orbs, kill style, unknown origin and orb shape. What they need from
-- Orbs.lua comes through Orbs:Info / PopInfo / BenchProbe / PerfReset, Orbs.ZoomAnchorY and Orbs.k.

local Orbs = ns.Orbs
local Target = ns.Target
local OrbMath = ns.OrbMath

local random = math.random
local floor, min, max = math.floor, math.min, math.max

local STRESS_TIME = 2.0 -- /xporbs test stress spreads its bursts over this many seconds
local STRESS_DEFAULT, STRESS_MAX = 20, 100
local POP_Y = Orbs.k.POP_Y -- offset of the pop frame from the plate centre (Orbs.lua)
local UNKNOWN_LEVEL = Orbs.k.UNKNOWN_LEVEL -- db.unknownOrigin -> level (Orbs.lua UNKNOWN.level)
local zoomAnchorY = Orbs.ZoomAnchorY

local function settings()
    if not ns.db then
        ns:InitDB()
    end
    return ns.db
end

local function readable(v)
    return not issecretvalue or not issecretvalue(v)
end

local function isNumber(v)
    return type(v) == "number" and readable(v)
end

-- Stream origin for /xporbs test (style = a render style). Popstream (Nameplate) follows the kill rule
-- (Target:StreamOrigin: the estimate P-hat, the portrait only without one); Direct Stream and Popstream (Direct) start
-- at the estimate too; otherwise target frame, else the cursor,
-- else the screen centre. Every read is
-- checked for secrecy and pcall'd. Returns x, y, label (x, y nil only when even the screen size is unreadable).
local function testOrigin(style, ex, ey)
    if style == "popstream" then
        local startX, startY, startLabel = Target:StreamOrigin(ex, ey)
        if startX then
            return startX, startY, startLabel
        end
    elseif (style == "stream" or style == "streampop") and isNumber(ex) and isNumber(ey) then
        return ex, ey, "estimate"
    end
    local frameX, frameY = Target:TargetFrameOrigin()
    if frameX then
        return frameX, frameY, "targetframe"
    end
    local okCursor, cursorX, cursorY = pcall(GetCursorPosition)
    local okScale, scale = pcall(UIParent.GetEffectiveScale, UIParent)
    if okCursor and okScale and isNumber(cursorX) and isNumber(cursorY) and isNumber(scale) and scale > 0 then
        return cursorX / scale, cursorY / scale, "cursor"
    end
    local okWidth, width = pcall(UIParent.GetWidth, UIParent)
    local okHeight, height = pcall(UIParent.GetHeight, UIParent)
    if okWidth and okHeight and isNumber(width) and isNumber(height) then
        return width / 2, height / 2, "centre"
    end
    return nil, nil, "centre"
end

-- Fires one test burst of pct % of a level. Returns the numbers the /xporbs test report prints.
local function fireTest(pct, rested, force, forceMode, path)
    local config = settings()
    local okXpMax, xpMax = pcall(UnitXPMax, "player")
    if not okXpMax or not isNumber(xpMax) or xpMax <= 0 then
        xpMax = 1000 -- max level, no data or a secret value: any positive number gives the same orb count
    end
    local gain = pct / 100 * xpMax
    local n, scale = OrbMath.Count(gain, xpMax, config.density, config.cap)
    local nPurple = 0
    if rested then
        local _
        _, nPurple = OrbMath.RestedSplit(n, gain, gain / 2)
    end
    -- the target's estimate (its GUID, when readable, finds a mouseover sample); no target = a keyboard-style estimate
    local guid
    local okGuid, targetGuid = pcall(UnitGUID, "target")
    if okGuid and readable(targetGuid) and type(targetGuid) == "string" then
        guid = targetGuid
    end
    local ex, ey, est, estW = ns.Mouseover:Estimate(guid)
    -- the options window's "Test target" stand-in (Preview.lua): a located mob with a nameplate, whatever is targeted
    -- Burst hangs the pop off the plate it is given at a style-dependent offset (the zoom anchor's body offset below
    -- BOTTOM, else POP_Y from the CENTER for the Popstream pop, else the BOTTOM itself), so the stand-in is told that
    -- offset and places its invisible anchor frame to cancel it: the pop lands on the model's chest whatever the
    -- zoom-anchor setting (Preview.lua).
    local standInPlate
    if ns.Preview then
        local popOffsetY = zoomAnchorY(config)
        if not popOffsetY then
            local renderStyle = ns.RenderStyle(force or config.style, forceMode or config.popMode)
            popOffsetY = renderStyle == "popstream" and POP_Y + (ns.Preview.ANCHOR_SIZE or 0) / 2 or 0
        end
        local okStandIn, plateFrame, bodyX, bodyY = pcall(ns.Preview.TestTarget, ns.Preview, popOffsetY)
        if okStandIn and plateFrame then
            standInPlate = plateFrame
            ex, ey, est, estW = bodyX, bodyY, "mouseover", 1 -- bodyY is already raised towards the pop anchor
        end
    end
    local x, y, label = testOrigin(ns.RenderStyle(force or config.style, forceMode or config.popMode), ex, ey)
    local mode = Orbs:Burst({
        x = x,
        y = y,
        plate = standInPlate or Target:TargetPlate(),
        n = n,
        scale = scale,
        nPurple = nPurple,
        kind = "test",
        style = force,
        popMode = forceMode,
        path = path,
        ex = ex,
        ey = ey,
        est = est,
        estW = estW,
        zoomFactor = standInPlate and 1 or nil, -- the stand-in's window is fixed: the camera must not size its pop
    })
    if standInPlate then
        pcall(ns.Preview.PlayDeath, ns.Preview) -- the stand-in dies as the orbs leave it
    end
    return n, scale, nPurple, est, estW, mode, label
end

-- /xporbs test stress [n]: n test bursts (1-15 % of a level each) spread over STRESS_TIME seconds, from one short-lived
-- OnUpdate frame that removes its own script when the last burst has fired.
local stressFrame
local stressN, stressFired, stressEl = 0, 0, 0

local function stressStop()
    if stressFrame then
        stressFrame:SetScript("OnUpdate", nil)
    end
end

local function stressTick(_, dt)
    stressEl = stressEl + (isNumber(dt) and dt or 0)
    while stressFired < stressN and stressEl >= stressFired * STRESS_TIME / stressN do
        stressFired = stressFired + 1
        local ok, err = pcall(fireTest, 1 + floor(random() * 15), false, nil)
        if not ok then
            ns:Log("stress error %s", tostring(err))
            stressStop()
            return
        end
    end
    if stressFired >= stressN then
        stressStop()
    end
end

local function startStress(arg)
    local n = floor(tonumber(arg) or STRESS_DEFAULT)
    n = max(1, min(STRESS_MAX, n))
    if not stressFrame then
        stressFrame = CreateFrame("Frame")
        Orbs.stressFrame = stressFrame
    end
    stressN, stressFired, stressEl = n, 0, 0
    stressFrame:SetScript("OnUpdate", stressTick)
    ns.Print(string.format("stress: %d test bursts over about %g s", n, STRESS_TIME))
end

-- what /xporbs test prints as style= for each Burst result
local TEST_USED = { ["pop+stream"] = "popstream/nameplate", streampop = "popstream/direct" }

-- /xporbs test [pct] [rested] [popstream|crossfade|stream] [nameplate|direct] [smooth|chaos|helix]
-- (any style alias works: streampop = Popstream (Direct), wide / mob = Popstream (Nameplate); nameplate / direct alone
-- mean Popstream with that pop; smooth / chaos / helix override the flight path for that burst; the old "frame" /
-- "plate" words are ignored)
-- /xporbs test stress [n]
-- quiet = true fires the burst without the chat report (the Test Kill buttons use it through ns.TestKill; the slash
-- handler passes a second argument of its own, so the flag is not a parameter of ns.commands.test).
local function runTest(arg, quiet)
    local first, count = string.match(arg or "", "^%s*(%S+)%s*(%S*)")
    if first == "stress" then
        startStress(count)
        return
    end
    settings() -- loads the db if it is not up yet
    local pct, rested, force, forceMode, path = 5, false, nil, nil, nil
    for tok in string.gmatch(arg or "", "%S+") do
        if tok == "rested" then
            rested = true
        elseif ns.STYLE_ALIAS[tok] then
            force = tok
        elseif ns.PATH_LABEL[tok] then
            path = tok
        elseif tok == "nameplate" or tok == "direct" then
            force, forceMode = force or "popstream", tok
        elseif tok ~= "frame" and tok ~= "plate" then
            local v = tonumber(tok)
            if v and v > 0 then
                pct = min(v, 1000)
            end
        end
    end
    Orbs.lastUnknown = nil
    local n, scale, nPurple, est, estW, mode, label = fireTest(pct, rested, force, forceMode, path)
    if quiet then
        return
    end
    local used = TEST_USED[mode] or mode
    if mode == "crossfade" then
        label = "estimated"
    end
    ns.Print(string.format("test: %g%% of a level -> %d orbs (%d purple), scale %.2f, est=%s w=%.2f pop=%s stream=%s"
        .. " style=%s", pct, n, nPurple, scale, est or "none", estW or 0, mode == "pop+stream" and "yes" or "no",
        label, used) .. (Orbs.lastUnknown and " unknown=" .. Orbs.lastUnknown or "")
        .. (path and " path=" .. path or ""))
end

function ns.commands.test(arg)
    runTest(arg, false)
end

-- The Test Kill buttons (Preview.lua, Options.lua): the same burst as /xporbs test, with no chat output.
function ns.TestKill(arg)
    runTest(arg, true)
end

-- /xporbs perf [reset]: addon memory, driver frame time, pool usage.
function ns.commands.perf(arg)
    if arg == "reset" then
        Orbs:PerfReset()
        ns.Print("perf counters reset")
        return
    end
    local mem = "n/a"
    if UpdateAddOnMemoryUsage and GetAddOnMemoryUsage then
        local okUpdate = pcall(UpdateAddOnMemoryUsage)
        local okUsage, kb = pcall(GetAddOnMemoryUsage, ADDON)
        if okUpdate and okUsage and isNumber(kb) then
            mem = string.format("%.1f KB", kb)
        end
    end
    local nLive, _, perfFrames, perfTotal, perfMax = Orbs:BenchProbe()
    local _, texInUse, texCreated, ceiling = Orbs:Info()
    local _, popsCreated, popFrameCap = Orbs:PopInfo()
    ns.Print("perf: memory " .. mem)
    if perfFrames == 0 and not debugprofilestop then
        ns.Print("perf: driver timing n/a")
    else
        ns.Print(string.format("perf: driver frames=%d avg=%.3f ms max=%.3f ms", perfFrames,
            perfFrames > 0 and perfTotal / perfFrames or 0, perfMax))
    end
    ns.Print(string.format("perf: textures created=%d in use=%d ceiling=%d", texCreated, texInUse, ceiling))
    ns.Print(string.format("perf: pop frames created=%d (cap %d)", popsCreated, popFrameCap))
    ns.Print(string.format("perf: live orbs=%d", nLive))
end

local function refreshPanel()
    if ns.Options and ns.Options.Refresh then
        ns.Options:Refresh()
    end
end

-- /xporbs style popstream [nameplate|direct] | crossfade | stream, plus the old names (Core STYLE_ALIAS): streampop =
-- Popstream (Direct), wide / mob = Popstream (Nameplate) with Wide on. /xporbs pop on|off = popstream|stream.
function ns.commands.style(arg)
    local word, subMode = string.match(arg or "", "^%s*(%S*)%s*(%S*)")
    if word == "nameplate" or word == "direct" then
        word, subMode = "popstream", word
    end
    if word ~= "" then
        local alias = ns.STYLE_ALIAS[word]
        if not alias
            or (subMode ~= "" and (alias[1] ~= "popstream" or (subMode ~= "nameplate" and subMode ~= "direct"))) then
            ns.Print("style: use popstream [nameplate|direct], crossfade or stream")
            return
        end
        ns.SetStyle(settings(), word)
        if subMode ~= "" then
            settings().popMode = subMode
        end
        refreshPanel()
    end
    ns.Print("kill style: " .. ns.StyleLabel(settings()))
end

-- /xporbs flightmode time|speed: debug switch between a fixed flight time and a flight speed (db.flightMode); not in
-- /xporbs help. No argument shows the current mode.
function ns.commands.flightmode(arg)
    local word = string.match(arg or "", "^%s*(%S*)")
    if word ~= "" then
        if word ~= "time" and word ~= "speed" then
            ns.Print("flightmode: use time or speed (now " .. tostring(settings().flightMode) .. ")")
            return
        end
        settings().flightMode = word
        refreshPanel()
    end
    ns.Print("flight mode: " .. tostring(settings().flightMode))
end

-- /xporbs path smooth|chaos|helix: how orbs fly (db.flightPath). No argument shows the current one.
function ns.commands.path(arg)
    local word = string.match(arg or "", "^%s*(%S*)")
    if word ~= "" then
        if not ns.PATH_LABEL[word] then
            ns.Print("path: use smooth, chaos or helix")
            return
        end
        settings().flightPath = word
        refreshPanel()
    end
    ns.Print("flight pathing: " .. (ns.PATH_LABEL[settings().flightPath] or "Smooth"))
end

-- /xporbs shape starlight|bubble|retro|crackle: how the orbs are drawn (db.orbShape). Size, quantity and opacity are
-- remembered per shape (ns.SetOrbShape). No argument shows the current one.
function ns.commands.shape(arg)
    local word = string.match(arg or "", "^%s*(%S*)")
    if word ~= "" then
        settings()
        if not ns.SetOrbShape(word) then
            ns.Print("shape: use starlight, bubble, retro or crackle")
            return
        end
        refreshPanel()
    end
    ns.Print("orb shape: " .. (ns.SHAPE_LABEL[settings().orbShape] or ns.SHAPE_LABEL.starlight))
end

-- /xporbs pulse on|off: the "Pulsing" tickbox, always Bubble's own look (shapeLook.bubble.pulse): its orbs gently swell
-- and shrink.
function ns.commands.pulse(arg)
    local word = string.match(arg or "", "%S+")
    settings()
    if word == "on" or word == "off" then
        ns.SetShapeLook("bubble", "pulse", word == "on") -- Bubble's own look, whichever shape is active
        refreshPanel()
    elseif word ~= nil then
        ns.Print("pulse: use on or off (now " .. (ns.GetShapeLook("bubble", "pulse") and "on" or "off") .. ")")
        return
    end
    ns.Print("pulsing: " .. (ns.GetShapeLook("bubble", "pulse") and "on" or "off")
        .. (settings().orbShape ~= "bubble" and " (Bubble only)" or ""))
end

local function spreadState()
    return settings().zoomSpread and "on" or "off"
end

-- /xporbs wide on|off: the "Zoom-scaled spread" tickbox (db.zoomSpread): located orbs' spawn spread scales with zoom.
function ns.commands.wide(arg)
    local word = string.match(arg or "", "%S+")
    if word == "on" or word == "off" then
        settings().zoomSpread = word == "on"
        refreshPanel()
    elseif word ~= nil then
        ns.Print("wide: use on or off (now " .. spreadState() .. ")")
        return
    end
    ns.Print("zoom-scaled spread: " .. spreadState())
end

-- /xporbs unknown off|wide: where the stream starts when the mob is not located (no Options control; "off" is kept
-- for future quest/exploration streams)
function ns.commands.unknown(arg)
    local word = string.match(arg or "", "%S+")
    if word ~= nil and UNKNOWN_LEVEL[word] == nil then
        ns.Print("unknown: use off or wide (now " .. tostring(settings().unknownOrigin) .. ")")
        return
    end
    if word ~= nil then
        settings().unknownOrigin = word
    end
    ns.Print("unknown origin: " .. tostring(settings().unknownOrigin))
end

function ns.commands.pop(arg)
    local word = string.match(arg or "", "%S+")
    if word == "on" then
        settings().style = "popstream"
        refreshPanel()
    elseif word == "off" then
        settings().style = "stream"
        refreshPanel()
    elseif word ~= nil then
        ns.Print("pop: use on or off")
        return
    end
    ns.Print("kill style: " .. ns.StyleLabel(settings()))
end

table.insert(ns.statusProviders, function()
    Target:GetDestination()
    local active, texInUse, texCreated, ceiling = Orbs:Info()
    local nPops, popsCreated, popFrameCap = Orbs:PopInfo()
    return string.format(
        "orbs: driver=%s, live textures=%d, pool=%d/%d, dest=%s, fallback=%s, style=%s, pops=%d (frames %d/%d)",
        active and "active" or "idle",
        texInUse,
        texCreated,
        ceiling,
        tostring(Target.lastName) .. (Target.lastSourceLabel and (" [" .. Target.lastSourceLabel .. "]") or ""),
        Target.lastOk and "no" or "yes",
        ns.RenderStyle(settings().style, settings().popMode),
        nPops,
        popsCreated,
        popFrameCap
    )
end)

table.insert(ns.statusProviders, function()
    return "kill style: " .. ns.StyleLabel(settings()) .. ", zoom-scaled spread: " .. spreadState()
end)

table.insert(ns.statusProviders, function()
    return "unknown origin: " .. tostring(settings().unknownOrigin)
end)

table.insert(ns.statusProviders, function()
    local config = settings()
    local size = config.orbShape == "retro" and (config.size .. " px") or tostring(config.size)
    local line = string.format("orb shape: %s (size %s, quantity %d%%, opacity %d%%)",
        ns.SHAPE_LABEL[config.orbShape] or ns.SHAPE_LABEL.starlight, size, config.density, config.opacity)
    if config.orbShape == "bubble" then
        line = line .. ", pulsing " .. (config.pulse and "on" or "off")
    end
    return line
end)
