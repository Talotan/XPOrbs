local ADDON, ns = ...

-- /xporbs lab: one-shot anchoring experiments on the current target's nameplate. Each technique runs in its own pcall,
-- prints one chat line and shows a coloured marker for DURATION seconds, then everything is hidden and un-anchored.
-- Frames are created lazily and reused. Nothing here ever measures a frame that is anchored to a plate.

local Lab = {}
ns.Lab = Lab

local ORB_TEX = "Interface\\AddOns\\XPOrbs\\media\\orb"
local WHITE = "Interface\\Buttons\\WHITE8X8"
local DURATION = 4
local SIZE = 24
local SMALL = 16 -- T3 reuses T2's colours at this size so the two are tellable apart

local RED, GREEN, YELLOW = { 1, 0.1, 0.1 }, { 0.1, 1, 0.1 }, { 1, 0.9, 0.1 }
local BLUE, PURPLE = { 0.2, 0.5, 1 }, { 0.8, 0.2, 1 }

local objs, order, groups, ready = {}, {}, {}, {}
local driver
local elapsed = 0
Lab.running = false

local function say(msg)
    ns.Print(msg)
end

-- Creates (once) and returns objs[key]. setup(obj) runs until it succeeds once, so a failed setup is retried
-- on the next run without creating a second object.
local function get(key, make, setup)
    local o = objs[key]
    if o == nil then
        o = make()
        objs[key] = o
        order[#order + 1] = key
    end
    if setup and not ready[key] then
        setup(o)
        ready[key] = true
    end
    return o
end

local function frame(key, kind, parent)
    return get(key, function()
        return CreateFrame(kind or "Frame", nil, parent or UIParent)
    end)
end

local function overlay()
    local o = frame("overlay")
    o:SetAllPoints(UIParent)
    o:SetFrameStrata("HIGH")
    o:EnableMouse(false)
    o:Show()
    return o
end

local function marker(key, parent, c, size)
    local t = get(key, function()
        return parent:CreateTexture(nil, "OVERLAY")
    end)
    t:SetTexture(ORB_TEX)
    t:SetBlendMode("ADD")
    t:SetVertexColor(c[1], c[2], c[3])
    t:SetSize(size, size)
    t:SetAlpha(1)
    t:ClearAllPoints()
    return t
end

local function setupBar(bar, orientation)
    bar:SetOrientation(orientation)
    bar:SetMinMaxValues(0, 1)
    bar:SetStatusBarTexture(WHITE)
    bar:SetStatusBarColor(0, 0, 0, 0)
    bar:SetValue(0)
end

-- The StatusBar chain from Orbs.lua on frame R; returns the horizontal bar's fill texture.
local function chain(key, R, value)
    local v = get(key .. "v", function()
        local f = CreateFrame("StatusBar", nil, R)
        setupBar(f, "VERTICAL")
        return f
    end)
    local m = frame(key .. "m", "Frame", R)
    local h = get(key .. "h", function()
        local f = CreateFrame("StatusBar", nil, R)
        setupBar(f, "HORIZONTAL")
        return f
    end)
    v:ClearAllPoints()
    v:SetAllPoints(R)
    m:ClearAllPoints()
    m:SetPoint("BOTTOMLEFT", R, "BOTTOMLEFT")
    m:SetPoint("TOPRIGHT", v:GetStatusBarTexture(), "TOPRIGHT")
    h:ClearAllPoints()
    h:SetAllPoints(m)
    v:SetValue(value)
    h:SetValue(value)
    v:Show()
    m:Show()
    h:Show()
    return h:GetStatusBarTexture()
end

local function newGroup(key, parent, setup)
    return get(key, function()
        local ag = parent:CreateAnimationGroup()
        groups[#groups + 1] = ag
        return ag
    end, setup)
end

-- T1: one anchor, marker on the plate.
local function t1(plate)
    local t = marker("t1", overlay(), RED, SIZE)
    t:SetPoint("CENTER", plate, "CENTER", 0, 0)
    t:Show()
end

-- T2 / T3: frame R spanning UIParent BOTTOMLEFT to the plate centre, each SetPoint pcalled on its own.
local function twoAnchor(plate, plateFirst, key, size)
    local R = frame(key .. "R", "Frame", UIParent)
    R:ClearAllPoints()
    local errs = {}
    local function toScreen()
        local ok, e = pcall(R.SetPoint, R, "BOTTOMLEFT", UIParent, "BOTTOMLEFT")
        if not ok then
            errs[#errs + 1] = "BOTTOMLEFT->UIParent: " .. tostring(e)
        end
    end
    local function toPlate()
        local ok, e = pcall(R.SetPoint, R, "TOPRIGHT", plate, "CENTER")
        if not ok then
            errs[#errs + 1] = "TOPRIGHT->plate: " .. tostring(e)
        end
    end
    if plateFirst then
        toPlate()
        toScreen()
    else
        toScreen()
        toPlate()
    end
    if #errs > 0 then
        error("SetPoint failed (" .. table.concat(errs, "; ") .. ")", 0)
    end
    R:Show()
    local o = overlay()
    local g = marker(key .. "g", o, GREEN, size)
    g:SetPoint("CENTER", R, "TOPRIGHT")
    g:Show()
    local fill = chain(key, R, 0.5)
    local y = marker(key .. "y", o, YELLOW, size)
    y:SetPoint("CENTER", fill, "TOPRIGHT")
    y:Show()
end

local function t2(plate)
    twoAnchor(plate, false, "t2", SIZE)
end

local function t3(plate)
    twoAnchor(plate, true, "t3", SMALL)
end

-- T4: scale animation on a frame at the XP bar; the blue marker is its child, anchored to the plate.
local function t4(plate)
    local dx, dy = ns.Target:GetDestination()
    local F = frame("t4F", "Frame", UIParent)
    F:ClearAllPoints()
    F:SetSize(2, 2)
    F:SetPoint("CENTER", UIParent, "BOTTOMLEFT", dx, dy)
    F:Show()
    local m = marker("t4m", F, BLUE, SIZE)
    m:SetPoint("CENTER", plate, "CENTER")
    m:Show()
    local ag = newGroup("t4ag", F, function(g)
        g:SetLooping("BOUNCE")
        local s = g:CreateAnimation("Scale")
        if s.SetScaleFrom then
            s:SetScaleFrom(1, 1)
            s:SetScaleTo(0.05, 0.05)
        elseif s.SetFromScale then
            s:SetFromScale(1, 1)
            s:SetToScale(0.05, 0.05)
        elseif s.SetScale then
            s:SetScale(0.05, 0.05)
        else
            error("Scale animation has no SetScaleFrom/SetFromScale/SetScale", 0)
        end
        s:SetOrigin("CENTER", 0, 0)
        s:SetDuration(1.0)
    end)
    ag:Play()
end

-- T5: translation animation on a plate-anchored frame (purple marker should bob 200 px below the mob).
local function t5(plate)
    local G = frame("t5G", "Frame", UIParent)
    G:ClearAllPoints()
    G:SetSize(2, 2)
    G:SetPoint("CENTER", plate, "CENTER")
    G:Show()
    local m = marker("t5m", G, PURPLE, SIZE)
    m:SetPoint("CENTER", G, "CENTER")
    m:Show()
    local ag = newGroup("t5ag", G, function(g)
        g:SetLooping("BOUNCE")
        local t = g:CreateAnimation("Translation")
        if not t.SetOffset then
            error("Translation animation has no SetOffset", 0)
        end
        t:SetOffset(0, -200)
        t:SetDuration(1.0)
    end)
    ag:Play()
end

local TECHNIQUES = {
    { 1, "single-anchor", t1 },
    { 2, "two-anchor", t2 },
    { 3, "two-anchor-plate-first", t3 },
    { 4, "scale-anim", t4 },
    { 5, "translate-anim", t5 },
}

-- Hides and un-anchors everything, stops every animation. Safe to call at any time.
local function cleanup()
    for i = 1, #groups do
        local ag = groups[i]
        pcall(ag.Stop, ag)
    end
    for i = 1, #order do
        local o = objs[order[i]]
        pcall(function()
            o:Hide()
            o:ClearAllPoints()
        end)
    end
    if driver then
        driver:SetScript("OnUpdate", nil)
    end
    Lab.running = false
end
Lab.Cleanup = cleanup

local function onUpdate(_, dt)
    elapsed = elapsed + dt
    if elapsed >= DURATION then
        cleanup()
    end
end

local function targetPlate()
    if not (C_NamePlate and C_NamePlate.GetNamePlateForUnit) then
        return nil, "C_NamePlate API unavailable"
    end
    local ok, p = pcall(C_NamePlate.GetNamePlateForUnit, "target")
    if not ok then
        return nil, "C_NamePlate error: " .. tostring(p)
    end
    if type(p) == "table" and (not issecretvalue or not issecretvalue(p)) then
        return p
    end
    return nil, "your target has no nameplate (target a mob with a visible nameplate)"
end

function ns.commands.lab()
    cleanup()
    local plate, why = targetPlate()
    if not plate then
        say("lab: " .. tostring(why))
        return
    end
    for i = 1, #TECHNIQUES do
        local n, name, fn = TECHNIQUES[i][1], TECHNIQUES[i][2], TECHNIQUES[i][3]
        local ok, err = pcall(fn, plate)
        local line = string.format("lab T%d %s: %s", n, name, ok and "ok" or ("ERR " .. tostring(err)))
        say(line)
        ns:Log("%s", line)
    end
    say("lab: watch for 4 s — red=mob, green=mob, yellow=halfway to corner, blue=slides mob↔bar, "
        .. "purple=bobs below mob")
    driver = driver or CreateFrame("Frame")
    Lab.driver = driver
    elapsed = 0
    Lab.running = true
    driver:SetScript("OnUpdate", onUpdate)
end
