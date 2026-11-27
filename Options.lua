-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Settings panel shell (v0.13): a canvas category under Esc > Options > AddOns. Fixed title and footer, a scrolling
-- body with a label column and a control column (layout spec: docs/review-v012/review.md). Every control writes ns.db
-- directly (changes apply to the next burst) and the panel re-reads ns.db whenever it is shown or a slash command
-- changes it. This file holds the tab strip, the scroll frame, the footer and the registration; the rows live in
-- OptionsKit.lua (widgets), ColourPicker.lua, OptionsLook.lua and OptionsPages.lua (the tabs).

local Options = ns.Options
local kit = ns.OptionsKit
local settings, text, postRefresh = kit.settings, kit.text, kit.postRefresh
local HEADER_X, RULE_W, CONTENT_W = kit.HEADER_X, kit.RULE_W, kit.CONTENT_W

local POPUP = "XPORBS_RESET_ALL"
local CONTENT_H = 0 -- the tallest tab's height (|last y| + 16); newTabs sets it
Options.CONTENT_H = CONTENT_H

local function registerPopup()
    if type(StaticPopupDialogs) ~= "table" then
        return false
    end
    StaticPopupDialogs[POPUP] = {
        text = "Reset all XPOrbs settings, on every tab, to their defaults?",
        button1 = "Reset",
        button2 = "Cancel",
        OnAccept = function()
            pcall(ns.commands.reset)
        end,
        timeout = 0,
        whileDead = true,
        hideOnEscape = true,
        preferredIndex = 3,
    }
    return true
end

local function confirmReset()
    if StaticPopup_Show and type(StaticPopupDialogs) == "table" and StaticPopupDialogs[POPUP] then
        if pcall(StaticPopup_Show, POPUP) then
            return
        end
    end
    ns.Print("couldn't show the confirmation; use /xporbs reset instead")
end

local function newScroll(panel)
    for _, tpl in ipairs({ "ScrollFrameTemplate", "UIPanelScrollFrameTemplate" }) do
        local ok, sf = pcall(CreateFrame, "ScrollFrame", nil, panel, tpl)
        if ok and sf then
            return sf, tpl
        end
    end
    -- no template: a bare scroll frame with mouse-wheel scrolling and no bar
    local sf = CreateFrame("ScrollFrame", nil, panel)
    pcall(sf.EnableMouseWheel, sf, true)
    sf:SetScript("OnMouseWheel", function(self, delta)
        local cur, range = self:GetVerticalScroll() or 0, self:GetVerticalScrollRange() or 0
        self:SetVerticalScroll(math.max(0, math.min(range, cur - (delta or 0) * 40)))
    end)
    return sf, nil
end

-- ---------------------------------------------------------------- the tabs
-- One tab per section, most-used first. Each tab builds into its own child frame (the scroll frame shows one at a
-- time); the row helpers hang off `kit.child`, so building a tab just points it at that tab's frame.
-- Options.rows / controls / refreshers / resets stay global, so Refresh and the resets work on every tab. The Debug log
-- row closes the General tab after a 12 px gap.
local TAB_NAMES = { "General", "Sound", "Look", "Flight", "Arrival" }
-- the tab builders register themselves in kit.pages (OptionsLook.lua, OptionsPages.lua)
local TAB_TOP, TAB_H, TAB_GAP, TAB_PAD, TAB_MIN_W = 42, 28, 4, 28, 64
local SCROLL_TOP = TAB_TOP + TAB_H + 4
local TAB_START_Y = 8 -- every tab's first row
local GOLD_R, GOLD_G, GOLD_B = 1, 0.82, 0
local selectedTab = 1 -- remembered for the session only, not saved
local warned = false

-- True when a tab's content fits the visible height, so the scroll bar has nothing to do. An unknown (zero) height
-- counts as not fitting, so the bar is never hidden on a guess.
local function tabFits(contentH, viewH)
    return (viewH or 0) > 0 and contentH <= viewH
end
Options.TabFits = tabFits

local function warnOnce(err)
    if not warned and ns.db and ns.db.debug then
        warned = true
        ns.Print("options: tab template call failed: " .. tostring(err))
    end
end

local function callGuarded(fn, ...)
    if fn then
        local ok, err = pcall(fn, ...)
        if not ok then
            warnOnce(err)
        end
    end
end

-- Real template: normal = GameFontNormal, selected (disabled) = GameFontHighlight, so labels aren't the Small font.
local function applyTabFonts(btn)
    if btn.SetNormalFontObject and GameFontNormal then
        pcall(btn.SetNormalFontObject, btn, GameFontNormal)
    end
    if btn.SetDisabledFontObject and GameFontHighlight then
        pcall(btn.SetDisabledFontObject, btn, GameFontHighlight)
    end
end

local function flatColour(btn, hover)
    local fs = btn.xpLabel
    if btn.xpSelected then
        fs:SetTextColor(GOLD_R, GOLD_G, GOLD_B)
    elseif hover then
        fs:SetTextColor(1, 1, 1)
    else
        fs:SetTextColor(0.70, 0.70, 0.70)
    end
end

local function setTabLook(btn, on)
    btn.xpSelected = on
    if Options.tabTemplate == "flat" then
        flatColour(btn, false)
        if on then
            btn.xpBar:Show()
            btn.xpFill:Show()
        else
            btn.xpBar:Hide()
            btn.xpFill:Hide()
        end
    else
        callGuarded(on and PanelTemplates_SelectTab or PanelTemplates_DeselectTab, btn)
        applyTabFonts(btn)
    end
end

-- The rule under the strip is the tabs' baseline: two segments, left of the selected tab and right of it, so the
-- selected tab breaks through it.
local function placeBaseline(btn)
    local panel, base = Options.panel, Options.tabBase
    local l, r = Options.tabRuleL, Options.tabRuleR
    local left, right = btn.xpX, btn.xpX + btn.xpW
    l:ClearAllPoints()
    l:SetPoint("TOPLEFT", panel, "TOPLEFT", HEADER_X, -base)
    l:SetSize(math.max(0, left - HEADER_X), 1)
    r:ClearAllPoints()
    r:SetPoint("TOPLEFT", panel, "TOPLEFT", right, -base)
    r:SetSize(math.max(0, HEADER_X + RULE_W - right), 1)
end

-- Hides the scroll bar when the selected tab fits (the Settings canvas size isn't known at build time, so this also
-- runs on show and on size changes).
function Options:UpdateScrollBar()
    local scroll = self.scroll
    local bar = scroll and scroll.ScrollBar
    if not bar then
        return
    end
    local fits = tabFits(self.tabHeights[TAB_NAMES[selectedTab]] or 0, scroll:GetHeight())
    pcall(fits and bar.Hide or bar.Show, bar)
end

function Options:SelectTab(which)
    local idx = which
    if type(which) == "string" then
        idx = nil
        for i, name in ipairs(TAB_NAMES) do
            if name == which then
                idx = i
            end
        end
    end
    if not idx or not TAB_NAMES[idx] then
        return false
    end
    selectedTab = idx
    for i, name in ipairs(TAB_NAMES) do
        local c = self.tabChildren[name]
        if i == idx then
            c:Show()
        else
            c:Hide()
        end
        setTabLook(self.tabs[i], i == idx)
    end
    placeBaseline(self.tabs[idx])
    local c = self.tabChildren[TAB_NAMES[idx]]
    self.child = c
    self.scroll:SetScrollChild(c)
    self.scroll:SetVerticalScroll(0)
    self:UpdateScrollBar()
    return true
end

local function labelWidth(panel, name)
    local fs = Options.measure
    if not fs then
        fs = panel:CreateFontString(nil, "ARTWORK", "GameFontNormal")
        fs:Hide()
        Options.measure = fs
    end
    fs:SetText(name)
    local ok, w = pcall(fs.GetStringWidth, fs)
    return (ok and tonumber(w) and w > 0) and w or (#name * 7)
end

local function newFlatTab(panel, name)
    local btn = CreateFrame("Button", nil, panel)
    btn.xpFill = btn:CreateTexture(nil, "BACKGROUND")
    btn.xpFill:SetAllPoints(btn)
    btn.xpFill:SetColorTexture(1, 1, 1, 0.04)
    btn.xpBar = btn:CreateTexture(nil, "ARTWORK")
    btn.xpBar:SetPoint("BOTTOMLEFT", btn, "BOTTOMLEFT", 0, 0)
    btn.xpBar:SetPoint("BOTTOMRIGHT", btn, "BOTTOMRIGHT", 0, 0)
    btn.xpBar:SetHeight(2)
    btn.xpBar:SetColorTexture(GOLD_R, GOLD_G, GOLD_B, 1)
    btn.xpLabel = btn:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    btn.xpLabel:SetPoint("CENTER", btn, "CENTER", 0, 0)
    btn.xpLabel:SetText(name)
    btn.text = name
    if btn.SetFontString then
        pcall(btn.SetFontString, btn, btn.xpLabel)
    end
    btn:SetScript("OnEnter", function(self)
        flatColour(self, true)
    end)
    btn:SetScript("OnLeave", function(self)
        flatColour(self, false)
    end)
    return btn
end

local function newTabButton(panel, i, prev)
    local name = TAB_NAMES[i]
    local w = math.max(TAB_MIN_W, math.floor(labelWidth(panel, name) + 0.5) + TAB_PAD)
    local btn
    if Options.tabTemplate ~= "flat" then
        local ok, b = pcall(CreateFrame, "Button", nil, panel, "PanelTopTabButtonTemplate")
        if ok and b then
            btn, Options.tabTemplate = b, "PanelTopTabButtonTemplate"
        else
            Options.tabTemplate = "flat"
        end
    end
    if Options.tabTemplate == "flat" then
        btn = newFlatTab(panel, name)
        btn:SetSize(w, TAB_H)
    else
        btn:SetText(name)
        applyTabFonts(btn)
        callGuarded(PanelTemplates_TabResize, btn, 0, w) -- the template keeps its own height
        btn:SetWidth(w)
    end
    btn.xpName, btn.xpW = name, w
    if prev then
        btn:SetPoint("TOPLEFT", prev, "TOPRIGHT", TAB_GAP, 0)
        btn.xpX = prev.xpX + prev.xpW + TAB_GAP
    else
        btn:SetPoint("TOPLEFT", panel, "TOPLEFT", HEADER_X, -TAB_TOP)
        btn.xpX = HEADER_X
    end
    btn:SetScript("OnClick", function()
        Options:SelectTab(i)
    end)
    return btn
end

-- Builds the tab strip, the baseline rule, the scroll frame under them and one child per tab.
local function newTabs(panel)
    Options.tabTemplate, Options.tabs, Options.tabChildren, Options.tabHeights = nil, {}, {}, {}
    Options.tabTop = TAB_TOP
    for i = 1, #TAB_NAMES do
        Options.tabs[i] = newTabButton(panel, i, Options.tabs[i - 1])
    end
    -- the baseline is the strip's bottom edge: the template's own height when it reports one, else TAB_H
    local h = Options.tabs[1]:GetHeight()
    Options.tabHeight = (h and h > 0) and h or TAB_H
    Options.tabBase = TAB_TOP + Options.tabHeight
    SCROLL_TOP = math.max(TAB_TOP + TAB_H + 4, Options.tabBase + 4)
    Options.tabRuleL = panel:CreateTexture(nil, "ARTWORK")
    Options.tabRuleR = panel:CreateTexture(nil, "ARTWORK")
    Options.tabRuleL:SetColorTexture(1, 1, 1, 0.15)
    Options.tabRuleR:SetColorTexture(1, 1, 1, 0.15)
    Options.topRule = Options.tabRuleL

    local scroll, tpl = newScroll(panel)
    Options.scroll, Options.scrollTemplate, Options.scrollTop = scroll, tpl, SCROLL_TOP
    scroll:SetPoint("TOPLEFT", panel, "TOPLEFT", 0, -SCROLL_TOP)
    scroll:SetPoint("BOTTOMRIGHT", panel, "BOTTOMRIGHT", -28, 44)
    local maxH = 0
    for _, name in ipairs(TAB_NAMES) do
        kit.child = CreateFrame("Frame", nil, scroll)
        local ch = kit.pages[name](TAB_START_Y) + 16 -- |last y| + 16
        kit.child:SetSize(CONTENT_W, ch)
        kit.child:Hide()
        Options.tabChildren[name], Options.tabHeights[name] = kit.child, ch
        maxH = math.max(maxH, ch)
    end
    -- the tallest tab (the scroll range follows the selected tab's own height)
    CONTENT_H = maxH
    Options.CONTENT_H = CONTENT_H
    Options:SelectTab(selectedTab)
    scroll:SetScript("OnSizeChanged", function()
        Options:UpdateScrollBar()
    end)
    return scroll
end

-- ---------------------------------------------------------------- the panel

local function build()
    local panel = CreateFrame("Frame")
    Options.panel = panel
    text(panel, "GameFontNormalLarge", "XP Orbs", 16, -16)

    Options.rightX = HEADER_X + RULE_W -- the right edge of the rules and the footer button
    newTabs(panel)
    Options.footerY = 44 -- the footer rule's px above the panel's bottom
    -- the orb preview window (ShapePreview.lua) follows every change made here
    postRefresh[#postRefresh + 1] = function()
        if ns.ShapePreview then
            ns.ShapePreview:Sync()
        end
    end

    -- fixed footer
    local rule = panel:CreateTexture(nil, "ARTWORK")
    rule:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", HEADER_X, 44)
    rule:SetSize(RULE_W, 1)
    Options.footerRule = rule
    rule:SetColorTexture(1, 1, 1, 0.15)
    local resetAll = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    resetAll:SetSize(160, 22)
    resetAll:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", HEADER_X + RULE_W - 160, 11)
    resetAll:SetText("Reset all to default")
    resetAll:SetScript("OnClick", confirmReset)
    Options.resetAll = resetAll
    registerPopup()

    -- The Test Kill button lives under the "Test target" window (Preview.lua). Only when that window can't be built
    -- does the panel get its own footer button, made on first need, so testing still works.
    local function ensureFooterTest(needed)
        if needed and not Options.footerTest then
            local test = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
            test:SetSize(110, 22)
            test:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", 16, 11)
            test:SetText("Test Kill")
            test:SetScript("OnClick", function()
                -- the same orbs a kill would make: rested ones too when Rested tint is on
                pcall(ns.TestKill, settings().restedTint and "5 rested" or "5")
            end)
            Options.footerTest = test
        end
        if Options.footerTest then
            if needed then
                Options.footerTest:Show()
            else
                Options.footerTest:Hide()
            end
        end
    end
    panel:SetScript("OnShow", function()
        Options:Refresh()
        Options:UpdateScrollBar()
        -- the orb preview window (ShapePreview.lua) goes up first: the "Test target" window docks under it
        if ns.ShapePreview then
            pcall(ns.ShapePreview.Sync, ns.ShapePreview, true)
        end
        -- the "Test target" stand-in window follows this panel (Preview.lua); never let it break the panel
        local okSync, windowUp = false, false
        if ns.Preview then
            okSync, windowUp = pcall(ns.Preview.Sync, ns.Preview, true)
        end
        ensureFooterTest(not (okSync and windowUp))
    end)
    panel:SetScript("OnHide", function()
        if ns.Preview then
            pcall(ns.Preview.Sync, ns.Preview, false)
        end
        if ns.ShapePreview then
            -- hides it; its OnUpdate runs only while the panel shows
            pcall(ns.ShapePreview.Sync, ns.ShapePreview, false)
        end
    end)
    return panel
end

Options.POPUP = POPUP

if Settings and Settings.RegisterCanvasLayoutCategory and Settings.RegisterAddOnCategory then
    local ok, err = pcall(function()
        local panel = build()
        Options.category = Settings.RegisterCanvasLayoutCategory(panel, "XP Orbs")
        Settings.RegisterAddOnCategory(Options.category)
    end)
    if not ok then
        Options.category, Options.err = nil, tostring(err)
    end
end

local openWhenCombatEnds = false -- a click in combat is waiting for PLAYER_REGEN_ENABLED
local combatFrame -- built on first use; PLAYER_REGEN_ENABLED is registered only while waiting

local function openNow()
    local id = Options.category:GetID()
    local ok
    -- Blizzard's Settings.OpenToCategory runs gamepad focus code on the addon's call path (blocked-action errors on
    -- Forever); C_SettingsUtil.OpenSettingsPanel through securecallfunction avoids that.
    if type(securecallfunction) == "function" and C_SettingsUtil
        and type(C_SettingsUtil.OpenSettingsPanel) == "function" then
        ok = pcall(securecallfunction, C_SettingsUtil.OpenSettingsPanel, id)
    else
        ok = pcall(Settings.OpenToCategory, id)
    end
    if not ok then
        ns.Print("options: couldn't open the settings panel; try Esc > Options > AddOns > XP Orbs")
    end
end

local function onCombatFrameEvent(self, event)
    if event ~= "PLAYER_REGEN_ENABLED" then
        return
    end
    pcall(self.UnregisterEvent, self, "PLAYER_REGEN_ENABLED")
    if openWhenCombatEnds then
        openWhenCombatEnds = false
        openNow()
    end
end

function ns.commands.options()
    if not Options.category then
        ns.Print("options: the settings panel isn't available ("
            .. (Options.err or "no Settings API on this client") .. "); use /xporbs commands instead")
        return
    end
    if InCombatLockdown and InCombatLockdown() then
        if not openWhenCombatEnds then
            openWhenCombatEnds = true
            combatFrame = combatFrame or CreateFrame("Frame")
            combatFrame:SetScript("OnEvent", onCombatFrameEvent)
            pcall(combatFrame.RegisterEvent, combatFrame, "PLAYER_REGEN_ENABLED")
        end
        ns.Print("options will open after combat")
        return
    end
    openNow()
end

table.insert(ns.statusProviders, function()
    if Options.category then
        return "options panel: registered"
    end
    return "options panel: unavailable (" .. (Options.err or "no Settings API") .. ")"
end)
