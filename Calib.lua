-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Zoom-anchor calibration: /xporbs calib opens a small panel and puts a marker on the targeted mob at the offset the
-- current settings give. Nudge it onto the body, save a point, repeat at another camera zoom, then Fit. The plate is
-- a restricted region, so the marker is a 1x1 frame whose ONLY anchor is the plate; nothing here measures the plate or
-- the marker. The OnUpdate exists only while the panel is open.

local Calib = {}
ns.Calib = Calib

local OrbMath = ns.OrbMath
local TICK = 0.1 -- marker re-anchor interval (10 Hz)
local STEP, STEP_BIG = 2, 10 -- nudge in px (shift = big)
local POINTS_MAX = 8
local MARKER_SIZE = 20
local CROSS = 15 -- crosshair arm length

local nudge, acc = 0, 0
local panel, marker, readout

local function db()
    if not ns.db then
        ns:InitDB()
    end
    return ns.db
end

-- The offset the current settings give at this zoom (no nudge), or nil.
local function baseOffset(z)
    local d = db()
    return z and OrbMath.ZoomOffset(z, d.zoomA, d.zoomB, d.zoomMin) or nil
end

local function fmt(v)
    return type(v) == "number" and string.format("%.1f", v) or "n/a"
end

local function refresh()
    local z = ns.Orbs.ReadZoom()
    local off = baseOffset(z)
    if readout then
        readout:SetText(string.format("zoom %s   offset %s px   points %d", fmt(z), off and fmt(off + nudge) or "n/a",
            #db().zoomPoints))
    end
    if not marker then
        return
    end
    local plate = nil
    if ns.Target and ns.Target.TargetPlate then
        local ok, p = pcall(ns.Target.TargetPlate, ns.Target)
        plate = ok and p or nil
    end
    if not (plate and off) then
        marker:Hide()
        return
    end
    local ok = pcall(function()
        marker:ClearAllPoints()
        marker:SetPoint("CENTER", plate, "BOTTOM", 0, -(off + nudge))
        marker:Show()
    end)
    if not ok then
        marker:Hide()
    end
end

local function bump(dir)
    local big = IsShiftKeyDown and IsShiftKeyDown()
    nudge = nudge + dir * (big and STEP_BIG or STEP)
    refresh()
end

-- Records { z, off } at the current zoom (off includes the nudge), drops the oldest beyond 8, resets the nudge.
function Calib.SavePoint()
    local z = ns.Orbs.ReadZoom()
    local base = baseOffset(z)
    if not base then
        ns.Print("camera zoom is unreadable, can't save a point")
        return false
    end
    local pts = db().zoomPoints
    pts[#pts + 1] = { z = z, off = base + nudge }
    while #pts > POINTS_MAX do
        table.remove(pts, 1)
    end
    nudge = 0
    ns.Print(string.format("saved point: zoom %s, offset %s px (%d saved)", fmt(z), fmt(pts[#pts].off), #pts))
    refresh()
    return true
end

-- Fits zoomA / zoomB to the saved points. Returns true when it saved a fit.
function Calib.Fit()
    local d = db()
    local a, b = OrbMath.FitZoom(d.zoomPoints, d.zoomMin)
    if not a then
        ns.Print("save points at two or more different zooms")
        return false
    end
    local ra, rb = ns.zoomRanges.zoomA, ns.zoomRanges.zoomB
    d.zoomA = math.max(ra[1], math.min(ra[2], a))
    d.zoomB = math.max(rb[1], math.min(rb[2], b))
    nudge = 0
    ns.Print(string.format("fit saved: a=%s b=%s (offset = a + b / zoom)", fmt(d.zoomA), fmt(d.zoomB)))
    refresh()
    return true
end

function Calib.Reset()
    local d, def = db(), ns.defaults
    d.zoomA, d.zoomB, d.zoomMin = def.zoomA, def.zoomB, def.zoomMin
    d.zoomPoints = {}
    nudge = 0
    ns.Print("zoom calibration reset to defaults")
    refresh()
end

local function onUpdate(_, dt)
    acc = acc + dt
    if acc >= TICK then
        acc = 0
        refresh()
    end
end

local function makeMarker()
    local f = CreateFrame("Frame", nil, UIParent)
    f:SetSize(1, 1)
    f:SetFrameStrata("HIGH")
    f:EnableMouse(false)
    f:Hide()
    local orb = f:CreateTexture(nil, "OVERLAY")
    orb:SetTexture(ns.Orbs.ORB_TEX)
    orb:SetVertexColor(1, 1, 0.85)
    orb:SetSize(MARKER_SIZE, MARKER_SIZE)
    orb:SetPoint("CENTER", f, "CENTER", 0, 0)
    -- a crosshair so the exact point stays readable over a bright body
    for i = 1, 2 do
        local line = f:CreateTexture(nil, "OVERLAY")
        line:SetColorTexture(1, 1, 1, 0.9)
        line:SetSize(i == 1 and CROSS or 1, i == 1 and 1 or CROSS)
        line:SetPoint("CENTER", f, "CENTER", 0, 0)
    end
    return f
end

local function button(parent, text, w, x, onClick)
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetSize(w, 22)
    b:SetPoint("BOTTOMLEFT", parent, "BOTTOMLEFT", x, 10)
    b:SetText(text)
    b:SetScript("OnClick", function()
        pcall(onClick)
    end)
    return b
end

local function makePanel()
    local f = CreateFrame("Frame", nil, UIParent)
    f:SetSize(400, 118)
    f:SetFrameStrata("DIALOG")
    f:SetPoint("TOP", UIParent, "TOP", 0, -80)
    f:SetClampedToScreen(true)
    f:SetMovable(true)
    f:EnableMouse(true)
    f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", f.StartMoving)
    f:SetScript("OnDragStop", f.StopMovingAndSizing)
    f:EnableMouseWheel(true)
    f:SetScript("OnMouseWheel", function(_, delta)
        bump(delta > 0 and 1 or -1)
    end)
    local bg = f:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints(f)
    bg:SetColorTexture(0, 0, 0, 0.8)
    local title = f:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    title:SetPoint("TOPLEFT", f, "TOPLEFT", 12, -10)
    title:SetText("XP Orbs calibration")
    readout = f:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    readout:SetPoint("TOPRIGHT", f, "TOPRIGHT", -12, -10)
    local hint = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    hint:SetPoint("TOPLEFT", f, "TOPLEFT", 12, -30)
    hint:SetWidth(376)
    hint:SetJustifyH("LEFT")
    hint:SetText("Target a mob, zoom the camera, nudge until the marker sits on its body, then Save point. "
        .. "Repeat at another zoom, then Fit.")
    button(f, "-", 26, 12, function()
        bump(-1)
    end)
    button(f, "+", 26, 44, function()
        bump(1)
    end)
    button(f, "Save point", 90, 76, Calib.SavePoint)
    button(f, "Fit", 50, 172, Calib.Fit)
    button(f, "Close", 60, 328, Calib.Close)
    f:SetScript("OnHide", function()
        f:SetScript("OnUpdate", nil)
        if marker then
            marker:Hide()
        end
    end)
    f:Hide()
    return f
end

function Calib.Open()
    if not panel then
        panel = makePanel()
        marker = makeMarker()
        Calib.panel, Calib.marker = panel, marker
    end
    nudge, acc = 0, 0
    panel:Show()
    panel:SetScript("OnUpdate", onUpdate)
    refresh()
end

function Calib.Close()
    if panel then
        panel:SetScript("OnUpdate", nil)
        panel:Hide()
    end
    if marker then
        marker:Hide()
    end
end

function Calib.IsOpen()
    return panel ~= nil and panel:IsShown() == true
end

-- ---------------------------------------------------------------- commands and status

local function zoomState()
    local d = db()
    local z = ns.Orbs.ReadZoom()
    local off = baseOffset(z)
    return string.format("zoom=%s a=%s b=%s zMin=%s camera=%s offset=%s points=%d", d.zoomAnchor and "on" or "off",
        fmt(d.zoomA), fmt(d.zoomB), fmt(d.zoomMin), fmt(z), fmt(off), #d.zoomPoints)
end

function ns.commands.zoomanchor(arg)
    local d = db()
    if arg == "on" then
        d.zoomAnchor = true
    elseif arg == "off" then
        d.zoomAnchor = false
    elseif arg ~= "" then
        ns.Print("usage: /xporbs zoomanchor on|off")
        return
    end
    ns.Print("anchor: " .. zoomState())
end

function ns.commands.calib(arg)
    if arg == "off" then
        Calib.Close()
    elseif arg == "reset" then
        Calib.Reset()
    elseif arg == "fit" then
        Calib.Fit()
    elseif arg == "save" then
        Calib.SavePoint()
    elseif arg == "" then
        Calib.Open()
    else
        ns.Print("usage: /xporbs calib [off|reset|fit|save]")
    end
end

table.insert(ns.statusProviders, function()
    return "anchor: " .. zoomState()
end)
