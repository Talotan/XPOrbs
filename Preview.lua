-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- "Test target": a small window docked to the right of the settings panel that shows a gnoll (Hogger) and a fake
-- nameplate above it. While the window is shown, "Test burst" fires the orbs FROM this stand-in: the fake plate is
-- passed to Orbs:Burst as the nameplate (so Popstream (Nameplate) and Crossfade pop on it) and the model's body centre
-- is the mob estimate, reported as located. Why: a Test burst otherwise starts from an unknown point, which makes
-- Direct Stream and Popstream (Direct) use the wide "unknown origin" spread and misrepresents the common case, where
-- the mob is located and has a nameplate. The model dies when Test is pressed and gets up again a few seconds later.
-- The window is ours, unnamed, built on first show; every model call is pcall'd because the model API differs between
-- clients (a missing method just means a blank or static model). An OnUpdate exists only during the death sequence.

local Preview = {}
ns.Preview = Preview

local WINDOW_W, WINDOW_H = 200, 260
local GAP = 4 -- px between the settings panel and the window
local PAD = 8
local TITLE_H = 22
local PLATE_W, PLATE_H = 128, 30
local HEALTH_H = 8

-- Hogger: NPC 448. SetCreature takes the NPC id and the client resolves its model, but it can stay blank when the
-- creature is not in the client's cache, so a display id is the fallback. UNCONFIRMED: no source reachable while this
-- was written confirmed Hogger's CreatureDisplayInfo id (wowhead and wago.tools could not be read, see the handoff).
-- Check it in game with `/xporbs` > Test target, and replace it (a wago.tools CreatureDisplayInfo or wowhead
-- npc=448 "View in 3D" lookup gives the right number). A wrong id just shows some other creature.
local HOGGER_NPC_ID = 448
local HOGGER_DISPLAY_ID = 384
local LOAD_WAIT = 1.0 -- seconds to wait for the model to load before falling back to the display id

-- Animation ids (AnimationData: 0 Stand, 1 Death, 6 Dead; TrinityCore wiki "AnimationData" table and WoWInterface
-- model-extraction thread; warcraft.wiki.gg lists the same ids). Death plays once and normally holds on its last
-- frame; at DEAD_AT the model is switched to Dead (the same final pose, which loops) in case it did not hold.
local ANIM_STAND, ANIM_DEATH, ANIM_DEAD = 0, 1, 6

-- Death sequence (seconds since Test): the health bar drains, the pose is held, then the gnoll gets up.
local DRAIN_TIME = 0.5
local DEAD_AT = 1.3
local REVIVE_AT = 3.0

-- 3/4 view framing, tuned by eye in game: facing in radians, camera distance scale, small vertical nudge.
local FACING = 0.6
local CAM_DISTANCE = 1.15
local MODEL_Z = -0.1

local BACKDROP = {
    bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
    edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
    tile = true,
    tileSize = 16,
    edgeSize = 16,
    insets = { left = 4, right = 4, top = 4, bottom = 4 },
}

local window, model, plate, healthFill
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

-- Camera and pose. Run after every (re)load: a model load resets them.
local function frameModel()
    try(model, "SetPortraitZoom", 0)
    try(model, "SetCamDistanceScale", CAM_DISTANCE)
    try(model, "SetFacing", FACING)
    try(model, "SetPosition", 0, 0, MODEL_Z)
    setAnimation(phase == "idle" and ANIM_STAND or ANIM_DEAD)
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
    try(model, "SetDisplayInfo", HOGGER_DISPLAY_ID)
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
    local ok = try(model, "SetCreature", HOGGER_NPC_ID)
    if not ok then
        try(model, "SetDisplayInfo", HOGGER_DISPLAY_ID)
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
    name:SetText("Hogger")
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
        setAnimation(ANIM_STAND)
    end
end

-- Test was pressed: the gnoll dies (restarts the sequence if it is already running).
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

local function buildWindow()
    local created, frame = pcall(CreateFrame, "Frame", nil, UIParent, "BackdropTemplate")
    if not (created and frame) then
        frame = CreateFrame("Frame", nil, UIParent)
    end
    window = frame
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
    Preview.window, Preview.model, Preview.plate = window, model, plate
    loadModel()
end

-- Options.panel OnShow (show = true) / OnHide (false). Idempotent.
function Preview:Sync(show)
    if show then
        if not window then
            local ok = pcall(buildWindow)
            if not ok then
                window = nil
                return
            end
        end
        dockWindow()
        window:Show()
        setHealth(1)
    elseif window then
        stopSequence()
        window:Hide()
        setAnimation(ANIM_STAND)
        setHealth(1)
    end
end

-- The stand-in for a Test burst: plate frame, and the model's body centre in UIParent coordinates. nil unless the
-- window is shown and its centre is readable (the caller then keeps the normal test origin).
function Preview:TestTarget()
    if not (window and window:IsShown() and plate) then
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
    return plate, centreX * ratio, centreY * ratio
end
