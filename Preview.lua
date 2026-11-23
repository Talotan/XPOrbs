-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- "Test target": a small window docked to the right of the settings panel that shows a stand-in mob (Hogger for the
-- Alliance, Gamon for the Horde) and a fake nameplate above it. While the window is shown, "Test Kill" fires the
-- orbs FROM this stand-in: the fake plate is passed to Orbs:Burst as the nameplate anchor (so Popstream (Nameplate)
-- and Crossfade pop on it) and the model's body centre is the mob estimate, reported as located. Why: a Test Kill
-- otherwise starts from an unknown point, which makes Direct Stream and Popstream (Direct) use the wide "unknown
-- origin" spread and misrepresents the common case, where the mob is located and has a nameplate. The model dies when
-- Test is pressed and gets up again a few seconds later. The "Test Kill" button lives in a small frame under the
-- window. Dragging on the model turns it around its vertical axis. The window is ours, unnamed, built on first show;
-- every model call is pcall'd because the model API differs between clients (a missing method just means a blank or
-- static model). An OnUpdate exists only during the death sequence and, on the model, while the mouse button is held
-- for a drag.

local Preview = {}
ns.Preview = Preview

local WINDOW_W, WINDOW_H = 200, 260
local GAP = 4 -- px between the settings panel and the window
local PAD = 8
local TITLE_H = 22
local PLATE_W, PLATE_H = 128, 30
local HEALTH_H = 8

-- Stand-ins: Hogger (NPC 448, display id 108956) for the Alliance, Gamon (NPC 6466, display id 5205) for the Horde.
-- Both display ids are the "displayId" in the model viewer data on each NPC's Wowhead page (wowhead.com/npc=448 and
-- wowhead.com/npc=6466, the entries with "type":1 and the NPC id as "typeId"). Framing (facing in radians, camera
-- distance scale, vertical nudge) is per stand-in, tuned by eye in game; Gamon's values are a first guess (he is a
-- bigger model than Hogger).
local STAND_INS = {
    Alliance = { npcId = 448, displayId = 108956, name = "Hogger", facing = 0.6, camDistance = 1.15, z = -0.1 },
    Horde = { npcId = 6466, displayId = 5205, name = "Gamon", facing = 0.6, camDistance = 1.35, z = -0.1 },
}
local LOAD_WAIT = 1.0 -- seconds to wait for the first load method before trying the other one

-- The stand-in for the player's faction (Hogger when neutral, unknown or unreadable).
local function pickStandIn()
    local ok, faction = pcall(UnitFactionGroup, "player")
    return STAND_INS[ok and faction or "Alliance"] or STAND_INS.Alliance
end

-- Animation ids (AnimationData: 1 Death, 6 Dead, 26 Ready1H; wowdev.wiki/M2/AnimationList lists 25 ReadyUnarmed,
-- 26 Ready1H, 27 Ready2H). The base Stand (0) turns the head left and right in game, so the idle is Ready1H, a calm
-- weapon-ready pose. SetAnimation(anim, variation) is API_Model_SetAnimation on warcraft.wiki.gg. A model without
-- that animation makes the client fall back by itself, and the call is pcall'd. Death plays once and normally holds
-- on its last frame; at DEAD_AT the model is switched to Dead (the same final pose, which loops) in case it did not.
local ANIM_IDLE_READY_1H, ANIM_DEATH, ANIM_DEAD = 26, 1, 6

-- Death sequence (seconds since Test): the health bar drains, the pose is held, then the stand-in gets up.
local DRAIN_TIME = 0.5
local DEAD_AT = 1.3
local REVIVE_AT = 3.0

-- Layout, measured from the window's top edge (px): the health bar's centre, the model area's centre, and where the
-- pop anchor sits between them. The pop forms on the mob's body in real use, close to the stream origin (the model
-- centre), not on the nameplate, so the invisible anchor is 60% of the way from the health bar down to the centre
-- (the brief said about 40%, but it also wants the pop closer to the stream origin than to the plate, which needs
-- more than half way; this is the number to nudge after looking in game).
local HEALTH_CENTRE_Y = TITLE_H + 4 + PLATE_H - HEALTH_H / 2
local MODEL_TOP_Y = TITLE_H + PLATE_H + 8
local MODEL_CENTRE_Y = (MODEL_TOP_Y + WINDOW_H - PAD) / 2
local ANCHOR_FRACTION = 0.6
local ANCHOR_Y = HEALTH_CENTRE_Y + ANCHOR_FRACTION * (MODEL_CENTRE_Y - HEALTH_CENTRE_Y)
-- The stream origin (what fireTest gets as the mob's position) sits this fraction of the way from the model centre up
-- to the pop anchor, so the stream starts a little higher than the model centre, nearer where the pop forms.
local ORIGIN_FRACTION = 0.5
local ORIGIN_RISE = ORIGIN_FRACTION * (MODEL_CENTRE_Y - ANCHOR_Y) -- px above the model centre (window scale)
local ANCHOR_SIZE = 1
local BUTTON_FRAME_W, BUTTON_FRAME_H = 120, 34
Preview.ANCHOR_SIZE = ANCHOR_SIZE
Preview.originRise = ORIGIN_RISE -- exposed for tests
Preview.anchorY = -ANCHOR_Y -- offset of the pop anchor's BOTTOM from the window's TOP (exposed for tests)

local BACKDROP = {
    bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
    edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
    tile = true,
    tileSize = 16,
    edgeSize = 16,
    insets = { left = 4, right = 4, top = 4, bottom = 4 },
}

local window, model, plate, healthFill, popAnchor, buttonFrame
local standIn = STAND_INS.Alliance
local modelLoaded = false
local loadCheckPending = false -- a C_Timer.After for the load fallback is in flight
local currentFacing = STAND_INS.Alliance.facing -- radians; the drag changes it and it is kept for the session
local dragStartX, dragStartFacing, dragScale = 0, 0, 1
local elapsed = 0
local phase = "idle" -- "idle" | "dying" | "dead"

Preview.deathTime = REVIVE_AT -- exposed for tests

-- Calls frame:method(...) under pcall when the method exists. Returns ok, results.
local function try(frame, method, ...)
    if not frame then
        return false
    end
    local fn = frame[method]
    if type(fn) ~= "function" then
        return false
    end
    return pcall(fn, frame, ...)
end

local function isNumber(v)
    return type(v) == "number" and (not issecretvalue or not issecretvalue(v)) and v == v
end

-- Same look as the setup window (Setup.lua keeps its helper private, so the table is repeated here).
local function addBackground(frame)
    local styled = frame.SetBackdrop and pcall(frame.SetBackdrop, frame, BACKDROP)
    if styled then
        pcall(frame.SetBackdropColor, frame, 0.07, 0.07, 0.10, 0.95)
        pcall(frame.SetBackdropBorderColor, frame, 0.6, 0.6, 0.7, 1)
    else
        local fill = frame:CreateTexture(nil, "BACKGROUND")
        fill:SetAllPoints(frame)
        fill:SetColorTexture(0.07, 0.07, 0.10, 0.95)
    end
end

-- ---------------------------------------------------------------- the model

local function setAnimation(id)
    if model then
        try(model, "SetAnimation", id, 0)
    end
end

-- The idle pose (see ANIM_IDLE_READY_1H).
local function setIdle()
    setAnimation(ANIM_IDLE_READY_1H)
end

-- Camera and pose. Run after every (re)load: a model load resets them.
local function frameModel()
    try(model, "SetPortraitZoom", 0)
    try(model, "SetCamDistanceScale", standIn.camDistance)
    try(model, "SetFacing", currentFacing)
    try(model, "SetPosition", 0, 0, standIn.z)
    if phase == "idle" then
        setIdle()
    else
        setAnimation(ANIM_DEAD)
    end
end

local function onModelLoaded()
    modelLoaded = true
    frameModel()
end

-- True when the model reports something loaded. GetModelFileID (Model, 8.1.0) returns the file id of the loaded model
-- and nothing (or 0) while it is blank; a client without it just relies on OnModelLoaded.
local function hasLoaded()
    if modelLoaded then
        return true
    end
    local ok, fileId = try(model, "GetModelFileID")
    return ok and isNumber(fileId) and fileId > 0
end

-- Load order: the display id first, SetCreature as the other option. SetDisplayInfo takes a CreatureDisplayInfo id
-- and needs no creature cache, while SetCreature(npcId) silently shows nothing when the NPC is not cached (seen in
-- game with Gamon). If the first call is missing or errors, the other runs at once; otherwise, after LOAD_WAIT, the
-- other runs unless OnModelLoaded fired or GetModelFileID reports a model. Each method runs at most once per load.
local function loadByDisplayId()
    return standIn.displayId ~= nil and try(model, "SetDisplayInfo", standIn.displayId)
end

local function loadByCreature()
    return (try(model, "SetCreature", standIn.npcId))
end

local function loadFallback()
    loadCheckPending = false
    if not model or hasLoaded() then
        return
    end
    loadByCreature()
    frameModel() -- the load event may not fire on every client; pose it anyway
end

local function createModel(parent)
    for _, kind in ipairs({ "PlayerModel", "CinematicModel", "DressUpModel" }) do
        local ok, frame = pcall(CreateFrame, kind, nil, parent)
        if ok and frame then
            return frame
        end
    end
    return nil
end

local function loadModel()
    if not model then
        return
    end
    modelLoaded = false
    try(model, "SetScript", "OnModelLoaded", onModelLoaded)
    if not loadByDisplayId() then
        loadByCreature() -- no display id or the call failed: the creature is the only way
        frameModel()
        return
    end
    frameModel()
    if C_Timer and C_Timer.After and not loadCheckPending then
        loadCheckPending = true
        pcall(C_Timer.After, LOAD_WAIT, loadFallback)
    end
end

-- ---------------------------------------------------------------- the fake nameplate

-- A real nameplate is only ever used as an anchor by the orbs (a 1x1 pop frame hangs off it with one point), and the
-- pop code reads IsVisible-like state nowhere else. This stand-in is an ordinary frame, so it also answers
-- GetCenter / GetEffectiveScale / IsVisible. Name and a red health bar are drawn on it.
local function buildPlate(parent)
    local frame = CreateFrame("Frame", nil, parent)
    frame:SetSize(PLATE_W, PLATE_H)
    frame:SetPoint("TOP", parent, "TOP", 0, -(TITLE_H + 4))
    local name = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    name:SetPoint("TOP", frame, "TOP", 0, 0)
    name:SetText(standIn.name)
    local back = frame:CreateTexture(nil, "BACKGROUND")
    back:SetPoint("BOTTOM", frame, "BOTTOM", 0, 0)
    back:SetSize(PLATE_W, HEALTH_H)
    back:SetColorTexture(0, 0, 0, 0.7)
    healthFill = frame:CreateTexture(nil, "ARTWORK")
    healthFill:SetPoint("BOTTOMLEFT", frame, "BOTTOMLEFT", 1, 1)
    healthFill:SetSize(PLATE_W - 2, HEALTH_H - 2)
    healthFill:SetColorTexture(0.80, 0.10, 0.10, 1)
    return frame
end

-- Health bar fill 0..1 (a texture width of 0 is invalid in the client, so keep a sliver and hide it at 0).
local function setHealth(fraction)
    if not healthFill then
        return
    end
    local width = (PLATE_W - 2) * fraction
    if width < 0.5 then
        healthFill:Hide()
    else
        healthFill:SetWidth(width)
        healthFill:Show()
    end
end

-- ---------------------------------------------------------------- drag to rotate

local DRAG_RADIANS_PER_PIXEL = 0.012

local function stopDrag()
    if model then
        model:SetScript("OnUpdate", nil)
    end
end

-- OnUpdate of the model while the mouse button is held. No allocation: plain calls, no varargs helpers.
local function onDragUpdate(frame)
    local okDown, down = pcall(IsMouseButtonDown, "LeftButton")
    if okDown and not down then
        stopDrag() -- released outside the frame (no OnMouseUp), or the window hid under the cursor
        return
    end
    local okCursor, cursorX = pcall(GetCursorPosition)
    if not (okCursor and isNumber(cursorX)) then
        return
    end
    currentFacing = dragStartFacing + (cursorX / dragScale - dragStartX) * DRAG_RADIANS_PER_PIXEL
    local setFacing = frame.SetFacing
    if setFacing then
        pcall(setFacing, frame, currentFacing)
    end
end

local function startDrag(frame, button)
    if button ~= nil and button ~= "LeftButton" then
        return
    end
    local okCursor, cursorX = pcall(GetCursorPosition)
    local okScale, scale = pcall(frame.GetEffectiveScale, frame)
    if not (okCursor and isNumber(cursorX)) then
        return
    end
    dragScale = okScale and isNumber(scale) and scale > 0 and scale or 1
    dragStartX, dragStartFacing = cursorX / dragScale, currentFacing
    frame:SetScript("OnUpdate", onDragUpdate)
end

-- ---------------------------------------------------------------- the death sequence

local function stopSequence()
    if window then
        window:SetScript("OnUpdate", nil)
    end
    phase = "idle"
    elapsed = 0
end

-- OnUpdate of the window, installed only while the sequence runs and removed by the last step.
local function onUpdate(_, dt)
    elapsed = elapsed + (isNumber(dt) and dt or 0)
    if elapsed < DRAIN_TIME then
        setHealth(1 - elapsed / DRAIN_TIME)
    elseif phase == "dying" then
        setHealth(0)
    end
    if phase == "dying" and elapsed >= DEAD_AT then
        phase = "dead"
        setAnimation(ANIM_DEAD)
    end
    if elapsed >= REVIVE_AT then
        stopSequence()
        setHealth(1)
        setIdle()
    end
end

-- Test was pressed: the stand-in dies (restarts the sequence if it is already running).
function Preview:PlayDeath()
    if not (window and window:IsShown()) then
        return
    end
    elapsed, phase = 0, "dying"
    setHealth(1)
    setAnimation(ANIM_DEATH)
    window:SetScript("OnUpdate", onUpdate)
end

-- ---------------------------------------------------------------- the window

local function dockWindow()
    window:ClearAllPoints()
    local panel = _G.SettingsPanel
    if panel then
        window:SetPoint("TOPLEFT", panel, "TOPRIGHT", GAP, 0)
    else
        window:SetPoint("CENTER", UIParent, "CENTER", 0, 0) -- no Settings panel on this client
    end
end

-- The "Test Kill" button, in its own small frame centred under the window (the same backdrop, narrower, 2 px gap).
-- It does what the old footer button did: the same orbs a kill would make, rested ones too when Rested tint is on.
local function buildButtonFrame(parent)
    local created, frame = pcall(CreateFrame, "Frame", nil, parent, "BackdropTemplate")
    if not (created and frame) then
        frame = CreateFrame("Frame", nil, parent)
    end
    buttonFrame = frame
    frame:SetSize(BUTTON_FRAME_W, BUTTON_FRAME_H)
    frame:SetPoint("TOP", parent, "BOTTOM", 0, -2)
    frame:EnableMouse(true)
    addBackground(frame)
    local button = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    button:SetSize(100, 22)
    button:SetPoint("CENTER", frame, "CENTER", 0, 0)
    button:SetText("Test Kill")
    button:SetScript("OnClick", function()
        pcall(ns.TestKill, ns.db and ns.db.restedTint and "5 rested" or "5")
    end)
    Preview.buttonFrame, Preview.testButton = frame, button
end

local function buildWindow()
    local created, frame = pcall(CreateFrame, "Frame", nil, UIParent, "BackdropTemplate")
    if not (created and frame) then
        frame = CreateFrame("Frame", nil, UIParent)
    end
    window = frame
    standIn = pickStandIn()
    currentFacing = standIn.facing
    frame:SetSize(WINDOW_W, WINDOW_H)
    -- MEDIUM, below the orbs overlay (HIGH): the stream and pops draw over the window and the settings panel
    frame:SetFrameStrata("MEDIUM")
    frame:EnableMouse(true)
    addBackground(frame)
    local title = frame:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    title:SetPoint("TOP", frame, "TOP", 0, -PAD - 2)
    title:SetText("Test target")
    plate = buildPlate(frame)
    model = createModel(frame)
    if model then
        try(model, "EnableMouse", true)
        model:SetScript("OnMouseDown", startDrag)
        model:SetScript("OnMouseUp", stopDrag)
        model:SetScript("OnHide", stopDrag)
        model:SetPoint("TOPLEFT", frame, "TOPLEFT", PAD, -(TITLE_H + PLATE_H + 8))
        model:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -PAD, PAD)
    end
    -- the pop anchor: an invisible 1x1 frame the burst hangs its pop from (placed by TestTarget)
    popAnchor = CreateFrame("Frame", nil, frame)
    popAnchor:SetSize(ANCHOR_SIZE, ANCHOR_SIZE)
    popAnchor:SetPoint("BOTTOM", frame, "TOP", 0, -ANCHOR_Y)
    Preview.window, Preview.model, Preview.plate, Preview.popAnchor = window, model, plate, popAnchor
    loadModel()
    buildButtonFrame(frame)
end

-- Options.panel OnShow (show = true) / OnHide (false). Idempotent. Returns true when the window is up (the options
-- panel keeps its own footer Test Kill button only when it is not).
function Preview:Sync(show)
    if show then
        if not window then
            local ok = pcall(buildWindow)
            if not ok then
                window = nil
                return false
            end
        end
        dockWindow()
        window:Show()
        setHealth(1)
        setIdle() -- the model's animation can be lost while hidden
        return true
    elseif window then
        stopSequence()
        stopDrag()
        window:Hide()
        setIdle()
        setHealth(1)
    end
    return false
end

-- The stand-in for a Test Kill: the pop anchor frame (the burst's "plate") and the stream origin (the model centre
-- raised by ORIGIN_RISE) in UIParent coordinates. popOffsetY is the vertical offset (px, negative = down) the burst
-- will add from the anchor's BOTTOM to
-- place its pop (the camera-zoom body offset, or the plate default); the anchor is moved by exactly that much the other
-- way, so the pop lands at ANCHOR_Y whatever the zoom-anchor setting is. nil unless the window is
-- shown and its centre is readable (the caller then keeps the normal test origin).
function Preview:TestTarget(popOffsetY)
    if not (window and window:IsShown() and popAnchor) then
        return nil
    end
    local anchor = model or window
    local ok, centreX, centreY = pcall(anchor.GetCenter, anchor)
    if not (ok and isNumber(centreX) and isNumber(centreY)) then
        return nil
    end
    local okScale, scale = pcall(anchor.GetEffectiveScale, anchor)
    local okParent, parentScale = pcall(UIParent.GetEffectiveScale, UIParent)
    local ratio = 1
    if okScale and okParent and isNumber(scale) and isNumber(parentScale) and parentScale > 0 then
        ratio = scale / parentScale
    end
    popAnchor:ClearAllPoints()
    popAnchor:SetPoint("BOTTOM", window, "TOP", 0, -ANCHOR_Y - (isNumber(popOffsetY) and popOffsetY or 0))
    return popAnchor, centreX * ratio, (centreY + ORIGIN_RISE) * ratio
end
