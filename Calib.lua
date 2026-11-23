-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Zoom-anchor calibration: /xporbs calib opens a small panel and puts a marker on the targeted mob at the offset the
-- current settings give. Nudge it onto the body, save a point, repeat at other camera zooms (each save refits). The
-- plate is a restricted region, so the marker is a 1x1 frame whose ONLY anchor is the plate; nothing here measures
-- the plate or the marker. The OnUpdate exists only while the panel is open.

local Calib = {}
ns.Calib = Calib

local OrbMath = ns.OrbMath
local TICK = 0.1 -- marker re-anchor interval (10 Hz)
local STEP, STEP_BIG = 2, 10 -- nudge in px (shift = big)
local POINTS_MAX = ns.ZOOM_POINTS_MAX
local MARKER_SIZE = 20
local ARM_FROM, ARM_TO = 6, 18 -- reticle arms run from here to here (px from the centre)

local nudge, acc = 0, 0 -- the user's nudge (px) and the OnUpdate time accumulator
local panel, marker, readout, fitBtn

local function settings()
    if not ns.db then
        ns:InitDB()
    end
    return ns.db
end

-- The offset the current settings give at this zoom (no nudge), or nil.
local function baseOffset(zoom)
    local saved = settings()
    return zoom and OrbMath.ZoomOffset(zoom, saved.zoomA, saved.zoomB, saved.zoomMin) or nil
end

local function fmt(v)
    return type(v) == "number" and string.format("%.1f", v) or "n/a"
end

local function refresh()
    local zoom = ns.Orbs.ReadZoom()
    local off = baseOffset(zoom)
    local plate = nil
    if ns.Target and ns.Target.TargetPlate then
        local ok, p = pcall(ns.Target.TargetPlate, ns.Target)
        plate = ok and p or nil
    end
    local numPoints = #settings().zoomPoints
    if readout then
        readout:SetText(string.format("zoom %s   %s   points %d", fmt(zoom),
            plate and ("offset " .. (off and fmt(off + nudge) or "n/a") .. " px")
                or "target a mob with its nameplate showing", numPoints))
    end
    if fitBtn then
        local setEnabled = numPoints >= 2 and fitBtn.Enable or fitBtn.Disable
        if setEnabled then
            setEnabled(fitBtn)
        end
    end
    if not marker then
        return
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

-- Move the marker one step (shift = the big step). dir -1 = up, 1 = down.
local function bump(dir)
    local big = IsShiftKeyDown and IsShiftKeyDown()
    nudge = nudge + dir * (big and STEP_BIG or STEP)
    refresh()
end

local function clampZoom(key, v)
    local r = ns.zoomRanges[key]
    return math.max(r[1], math.min(r[2], v))
end

-- Records { z, off } at the current zoom (off includes the nudge), drops the oldest beyond 8, then refits at once so
-- the curve passes through where the marker was put (otherwise the marker snaps back and saving looks like a no-op).
function Calib.SavePoint()
    local zoom = ns.Orbs.ReadZoom()
    local base = baseOffset(zoom)
    if not base then
        ns.Print("camera zoom is unreadable, can't save a point")
        return false
    end
    local saved = settings()
    local points = saved.zoomPoints
    local off = base + nudge
    points[#points + 1] = { z = zoom, off = off }
    while #points > POINTS_MAX do
        table.remove(points, 1)
    end
    ns.Print(string.format("saved point: zoom %s, offset %s px (%d saved)", fmt(zoom), fmt(off), #points))
    local fitA, fitB = OrbMath.FitZoom(points, saved.zoomMin)
    if fitA then
        saved.zoomA, saved.zoomB = clampZoom("zoomA", fitA), clampZoom("zoomB", fitB)
        ns.Print(string.format("curve refit: a=%s b=%s (offset = a + b / zoom)", fmt(saved.zoomA), fmt(saved.zoomB)))
    else
        -- one usable point (or all at one zoom): keep the slope, slide the curve through the point
        saved.zoomA = clampZoom("zoomA", off - saved.zoomB / math.max(zoom, saved.zoomMin))
    end
    nudge = 0
    refresh()
    return true
end

-- Refits zoomA / zoomB to all saved points. Returns true when it saved a fit.
function Calib.Fit()
    local saved = settings()
    local fitA, fitB = OrbMath.FitZoom(saved.zoomPoints, saved.zoomMin)
    if not fitA then
        ns.Print("save points at two or more different zooms")
        return false
    end
    saved.zoomA, saved.zoomB = clampZoom("zoomA", fitA), clampZoom("zoomB", fitB)
    nudge = 0
    ns.Print(string.format("fit saved: a=%s b=%s (offset = a + b / zoom)", fmt(saved.zoomA), fmt(saved.zoomB)))
    refresh()
    return true
end

function Calib.Reset()
    local saved, defaults = settings(), ns.defaults
    saved.zoomA, saved.zoomB, saved.zoomMin = defaults.zoomA, defaults.zoomB, defaults.zoomMin
    saved.zoomPoints = {}
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
    -- the orb is only a hint (dimmed over a black underlay); the exact point is the gapped reticle outside it
    local under = f:CreateTexture(nil, "ARTWORK")
    under:SetTexture(ns.Orbs.ORB_TEX)
    under:SetVertexColor(0, 0, 0)
    under:SetAlpha(0.4)
    under:SetSize(26, 26)
    under:SetPoint("CENTER", f, "CENTER", 0, 0)
    local orb = f:CreateTexture(nil, "OVERLAY")
    orb:SetTexture(ns.Orbs.ORB_TEX)
    orb:SetVertexColor(1, 1, 0.85)
    orb:SetAlpha(0.6)
    orb:SetSize(MARKER_SIZE, MARKER_SIZE)
    orb:SetPoint("CENTER", f, "CENTER", 0, 0)
    local armMid, armLen = (ARM_FROM + ARM_TO) / 2, ARM_TO - ARM_FROM
    f.arms = {}
    for i = 1, 4 do
        -- arms 1/2 sit right/left of centre, 3/4 above/below
        local dx = (i == 1 and armMid) or (i == 2 and -armMid) or 0
        local dy = (i == 3 and armMid) or (i == 4 and -armMid) or 0
        local horizontal = i <= 2
        for pass = 1, 2 do -- black (4 px, under) then white (2 px)
            local line = f:CreateTexture(nil, "OVERLAY", nil, pass == 1 and 1 or 2)
            if pass == 1 then
                line:SetColorTexture(0, 0, 0, 0.6)
            else
                line:SetColorTexture(1, 1, 1, 0.95)
                f.arms[#f.arms + 1] = line
            end
            local w = pass == 1 and 4 or 2 -- line thickness
            local length = armLen + (pass == 1 and 2 or 0)
            line:SetSize(horizontal and length or w, horizontal and w or length)
            line:SetPoint("CENTER", f, "CENTER", dx, dy)
        end
    end
    return f
end

local function tip(btn, text)
    btn:SetScript("OnEnter", function(self)
        pcall(function()
            GameTooltip:SetOwner(self, "ANCHOR_BOTTOM")
            GameTooltip:SetText(text)
            GameTooltip:Show()
        end)
    end)
    btn:SetScript("OnLeave", function()
        pcall(function()
            GameTooltip:Hide()
        end)
    end)
end

local function button(parent, text, w, x, onClick)
    local btn = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    btn:SetSize(w, 22)
    btn:SetPoint("BOTTOMLEFT", parent, "BOTTOMLEFT", x, 10)
    btn:SetText(text)
    btn:SetScript("OnClick", function()
        pcall(onClick)
    end)
    return btn
end

local function makePanel()
    local f = CreateFrame("Frame", nil, UIParent, BackdropTemplateMixin and "BackdropTemplate" or nil)
    f:SetSize(400, 124)
    f:SetFrameStrata("DIALOG")
    f:SetPoint("TOP", UIParent, "TOP", 0, -80)
    f:SetClampedToScreen(true)
    f:SetMovable(true)
    f:EnableMouse(true)
    f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", f.StartMoving)
    f:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
    end)
    f:EnableMouseWheel(true)
    f:SetScript("OnMouseWheel", function(_, delta)
        bump(delta > 0 and -1 or 1) -- wheel up moves the marker up (the marker sits at -(offset + nudge))
    end)
    local bg = f:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints(f)
    bg:SetColorTexture(0, 0, 0, 0.8)
    if f.SetBackdrop then
        pcall(f.SetBackdrop, f, { edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", edgeSize = 12 })
        if f.SetBackdropBorderColor then
            pcall(f.SetBackdropBorderColor, f, 0.8, 0.8, 0.8, 0.8)
        end
    end
    local title = f:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    title:SetPoint("TOPLEFT", f, "TOPLEFT", 12, -10)
    title:SetText("XP Orbs Calibration")
    readout = f:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    readout:SetPoint("TOPLEFT", f, "TOPLEFT", 180, -10)
    readout:SetJustifyH("LEFT")
    local hint = f:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    hint:SetPoint("TOPLEFT", f, "TOPLEFT", 12, -30)
    hint:SetWidth(376)
    hint:SetJustifyH("LEFT")
    hint:SetText("Nudge the marker onto the target's body (mouse wheel; Shift = 10 px), then Save point. "
        .. "Repeat at a few zooms; the curve updates as you save.")
    tip(button(f, "Down", 44, 12, function()
        bump(1)
    end), "Shift-click: 10 px")
    tip(button(f, "Up", 44, 60, function()
        bump(-1)
    end), "Shift-click: 10 px")
    button(f, "Save point", 90, 120, Calib.SavePoint)
    fitBtn = button(f, "Fit", 50, 216, Calib.Fit)
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
    local saved = settings()
    local zoom = ns.Orbs.ReadZoom()
    local off = baseOffset(zoom)
    return string.format("zoom=%s a=%s b=%s zMin=%s camera=%s offset=%s points=%d",
        saved.zoomAnchor and "on" or "off", fmt(saved.zoomA), fmt(saved.zoomB), fmt(saved.zoomMin), fmt(zoom),
        fmt(off), #saved.zoomPoints)
end

function ns.commands.zoomanchor(arg)
    local saved = settings()
    if arg == "on" then
        saved.zoomAnchor = true
    elseif arg == "off" then
        saved.zoomAnchor = false
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
