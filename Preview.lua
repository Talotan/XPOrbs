-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- "Test target": a small window docked to the right of the settings panel that shows a stand-in mob (Hogger for the
-- Alliance, Gamon for the Horde) and a fake nameplate above it. While the window is shown, "Test burst" fires the
-- orbs FROM this stand-in: the fake plate is passed to Orbs:Burst as the nameplate anchor (so Popstream (Nameplate)
-- and Crossfade pop on it) and the model's body centre is the mob estimate, reported as located. Why: a Test burst
-- otherwise starts from an unknown point, which makes Direct Stream and Popstream (Direct) use the wide "unknown
-- origin" spread and misrepresents the common case, where the mob is located and has a nameplate. The model dies when
-- Test is pressed and gets up again a few seconds later. The "Test burst" button lives in a small frame under the
-- window. The window is ours, unnamed, built on first show; every model call is pcall'd because the model API differs
-- between clients (a missing method just means a blank or static model). An OnUpdate exists only during the death
-- sequence.

local Preview = {}
ns.Preview = Preview

local WINDOW_W, WINDOW_H = 200, 260
local GAP = 4 -- px between the settings panel and the window
local PAD = 8
local TITLE_H = 22
local PLATE_W, PLATE_H = 128, 30
local HEALTH_H = 8

-- Stand-ins. SetCreature takes the NPC id and the client resolves its model. Hogger (NPC 448) can stay blank when
-- the creature is not in the client's cache, so he also has a display id as a fallback. UNCONFIRMED: no source
-- reachable confirmed Hogger's CreatureDisplayInfo id; a wrong id just shows some other creature. Gamon, the Hero of
-- Orgrimmar in Orgrimmar, is NPC 6466 (wowhead.com/npc=6466, checked when this was written); no display id is known
-- for him, so he has none. Framing (facing in radians, camera distance scale, vertical nudge) is per stand-in,
-- tuned by eye in game; Gamon's values are a first guess (he is a bigger model than Hogger).
local STAND_INS = {
    Alliance = { npcId = 448, displayId = 384, name = "Hogger", facing = 0.6, camDistance = 1.15, z = -0.1 },
    Horde = { npcId = 6466, name = "Gamon", facing = 0.6, camDistance = 1.35, z = -0.1 },
}
local LOAD_WAIT = 1.0 -- seconds to wait for the model to load before falling back to the display id

-- The stand-in for the player's faction (Hogger when neutral, unknown or unreadable).
local function pickStandIn()
    local ok, faction = pcall(UnitFactionGroup, "player")
    return STAND_INS[ok and faction or "Alliance"] or STAND_INS.Alliance
end

-- Animation ids (AnimationData: 0 Stand, 1 Death, 6 Dead; TrinityCore wiki "AnimationData" table and WoWInterface
-- model-extraction thread; warcraft.wiki.gg lists the same ids). SetAnimation(anim, variation) takes a variation
-- (API_Model_SetAnimation on warcraft.wiki.gg) and variation 0 is the base Stand, but in game the base Stand still
-- turns the head left and right. So the idle is held with Model:FreezeAnimation(anim, variation, frame)
-- (API_Model_FreezeAnimation, added 7.0.3) on frame 0 of Stand variation 0: a calm static pose. Both calls are
-- pcall'd; a client without FreezeAnimation just gets the plain Stand. Death plays once and normally holds on its last
-- frame; at DEAD_AT the model is switched to Dead (the same final pose, which loops) in case it did not hold.
local ANIM_STAND, ANIM_DEATH, ANIM_DEAD = 0, 1, 6

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
local ANCHOR_SIZE = 1
local BUTTON_FRAME_W, BUTTON_FRAME_H = 120, 34
Preview.ANCHOR_SIZE = ANCHOR_SIZE
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
local loadCheckPending = false -- a C_Timer.After for the display-id fallback is in flight
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

-- The calm idle: Stand variation 0, then held on its first frame so it never looks around (see ANIM_STAND).
local function setIdle()
    setAnimation(ANIM_STAND)
    if model then
        try(model, "FreezeAnimation", ANIM_STAND, 0, 0)
    end
end

-- Camera and pose. Run after every (re)load: a model load resets them.
local function frameModel()
    try(model, "SetPortraitZoom", 0)
    try(model, "SetCamDistanceScale", standIn.camDistance)
    try(model, "SetFacing", standIn.facing)
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

-- The creature did not load in LOAD_WAIT seconds (id not cached): try the display id instead.
local function loadFallback()
    loadCheckPending = false
    if modelLoaded or not model then
        return
    end
    if standIn.displayId then
        try(model, "SetDisplayInfo", standIn.displayId)
    end
    frameModel() -- the load event may not fire for a display id on every client; pose it anyway
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
    try(model, "SetScript", "OnModelLoaded", onModelLoaded)
    local ok = try(model, "SetCreature", standIn.npcId)
    if not ok then
        if standIn.displayId then
            try(model, "SetDisplayInfo", standIn.displayId)
        end
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

-- The "Test burst" button, in its own small frame centred under the window (the same backdrop, narrower, 2 px gap).
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
    button:SetText("Test burst")
    button:SetScript("OnClick", function()
        pcall(ns.commands.test, ns.db and ns.db.restedTint and "5 rested" or "5")
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
-- panel keeps its own footer Test burst button only when it is not).
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
        return true
    elseif window then
        stopSequence()
        window:Hide()
        setIdle()
        setHealth(1)
    end
    return false
end

-- The stand-in for a Test burst: the pop anchor frame (the burst's "plate") and the model's body centre in UIParent
-- coordinates. popOffsetY is the vertical offset (px, negative = down) the burst will add from the anchor's BOTTOM
-- to place its pop (the camera-zoom body offset, or the plate default); the anchor is moved by exactly that much
-- the other way, so the pop lands at ANCHOR_Y whatever the zoom-anchor setting is. nil unless the window is
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
    return popAnchor, centreX * ratio, centreY * ratio
end
