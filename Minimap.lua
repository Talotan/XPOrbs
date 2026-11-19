-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Minimap button (LibDataBroker + LibDBIcon, bundled in Libs/) and the Addon Compartment entry (declared in the .toc).
-- Every library call is wrapped in pcall: if a library is missing or errors, the button is simply unavailable and the
-- rest of the addon, including the compartment entry, keeps working.

local Btn = {}
ns.Minimap = Btn

local NAME = "XPOrbs"
local ICON = "Interface\\AddOns\\XPOrbs\\media\\icon"
local GREY = 0.7

local ldb, ldbi -- the libraries, when they loaded
local dataObject
local registered = false
Btn.err = nil

local function D()
    if not ns.db then
        ns:InitDB()
    end
    return ns.db
end

local function fail(msg)
    if Btn.err then
        return -- logged once
    end
    Btn.err = tostring(msg)
    ns:Log("MINIMAP_ERR %s", Btn.err)
end

local function stateText()
    return D().enabled and "orbs on" or "orbs off"
end

-- True when the Settings window is open on our own category (our canvas panel is only shown then).
local function optionsOpen()
    local panel = ns.Options and ns.Options.panel
    if not (panel and panel:IsShown() and SettingsPanel and SettingsPanel:IsShown()) then
        return false
    end
    return true
end

-- Closing the Settings window from addon code can be blocked (or taint the UIPanel manager) in combat, so don't try
-- then.
local function closeOptions()
    if InCombatLockdown and InCombatLockdown() then
        ns.Print("can't close the options in combat")
        return
    end
    if SettingsPanel and type(SettingsPanel.Close) == "function" and pcall(SettingsPanel.Close, SettingsPanel) then
        return
    end
    if HideUIPanel then
        pcall(HideUIPanel, SettingsPanel)
    end
end

-- Left-click (or anything but right-click): toggle the settings panel. Right-click: orbs on/off.
local function click(button)
    if button == "RightButton" then
        local db = D()
        db.enabled = not db.enabled
        ns.Print(stateText())
        local panel = ns.Options and ns.Options.panel
        if panel and panel:IsShown() then
            ns.Options:Refresh()
        end
    elseif optionsOpen() then
        closeOptions()
    else
        ns.commands.options()  -- also switches over when the window is open on another addon's category
    end
end

local function fillTooltip(tt)
    tt:SetText("XP Orbs", 1, 1, 1)
    tt:AddLine(stateText())
    tt:AddLine("Left-click: options", GREY, GREY, GREY)
    tt:AddLine("Right-click: turn orbs on/off", GREY, GREY, GREY)
end

-- Applies db.minimap.hide to the button (a no-op when LibDBIcon isn't registered).
local function applyVisibility()
    if not (registered and ldbi) then
        return
    end
    local hidden = D().minimap.hide
    local ok, err = pcall(hidden and ldbi.Hide or ldbi.Show, ldbi, NAME)
    if not ok then
        fail(err)
    end
end

-- Show or hide the button (saved in db.minimap.hide).
function Btn.SetShown(shown)
    D().minimap.hide = not shown
    applyVisibility()
end

-- After a settings reset: the saved table was emptied in place, so let LibDBIcon re-read position and visibility.
function Btn.Reapply()
    if registered and ldbi and ldbi.Refresh then
        local ok, err = pcall(ldbi.Refresh, ldbi, NAME, D().minimap)
        if not ok then
            fail(err)
        end
    end
    applyVisibility()
end

function ns.commands.minimap(arg)
    if arg == "on" or arg == "off" then
        Btn.SetShown(arg == "on")
        if ns.Options and ns.Options.panel and ns.Options.panel:IsShown() then
            ns.Options:Refresh()
        end
    elseif arg ~= "" then
        ns.Print("usage: /xporbs minimap on|off")
        return
    end
    local note = Btn.err and (" (button unavailable: " .. Btn.err .. ")") or ""
    ns.Print("minimap button " .. (D().minimap.hide and "hidden" or "shown") .. note)
end

local function register()
    local db = D()
    local ok, err = pcall(function()
        if type(LibStub) ~= "function" and type(LibStub) ~= "table" then
            error("LibStub is missing", 0)
        end
        ldb = LibStub("LibDataBroker-1.1", true)
        if not ldb then
            error("LibDataBroker-1.1 is missing", 0)
        end
        ldbi = LibStub("LibDBIcon-1.0", true)
        if not ldbi then
            error("LibDBIcon-1.0 is missing", 0)
        end
        dataObject = ldb:NewDataObject(NAME, {
            type = "launcher",
            icon = ICON,
            label = "XP Orbs",
            text = "XP Orbs",
            OnClick = function(_, button)
                click(button)
            end,
            OnTooltipShow = fillTooltip,
        })
        if not dataObject then
            error("LibDataBroker refused the data object", 0)
        end
        ldbi:Register(NAME, dataObject, db.minimap)
        registered = true
    end)
    if not ok then
        ldbi = nil
        fail(err)
    end
end

Btn.dataObject = function()
    return dataObject
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:SetScript("OnEvent", function(_, event, name)
    if event == "ADDON_LOADED" and name == ADDON then
        register()
    end
end)

-- Addon Compartment (the entry in the minimap's addon list), wired from the .toc. These need no library.
function XPOrbs_OnAddonCompartmentClick(_, buttonName)
    click(buttonName)
end

function XPOrbs_OnAddonCompartmentEnter(_, menuButtonFrame)
    GameTooltip:SetOwner(menuButtonFrame, "ANCHOR_LEFT")
    fillTooltip(GameTooltip)
    GameTooltip:Show()
end

function XPOrbs_OnAddonCompartmentLeave()
    GameTooltip:Hide()
end

table.insert(ns.statusProviders, function()
    if Btn.err then
        return "minimap button: unavailable (" .. Btn.err .. ")"
    end
    return "minimap button: " .. (D().minimap.hide and "hidden" or "shown")
end)
