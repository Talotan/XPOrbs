local ADDON, ns = ...

-- Settings panel: a canvas category under Esc > Options > AddOns, built from plain CreateFrame controls. Every control
-- writes ns.db directly (changes apply to the next burst) and the panel re-reads ns.db whenever it is shown.

local Options = {}
ns.Options = Options

local floor = math.floor

local STYLES = { "popstream", "crossfade", "stream" }
local SLIDER_W = 220
local COL2 = 236 -- x of the second checkbox column
local RULE_W = 520

local refreshers = {}
local refreshing = false
Options.controls = {}

local function D()
    if not ns.db then
        ns:InitDB()
    end
    return ns.db
end

-- Re-read every control from ns.db (OnShow, reset, slash changes).
function Options:Refresh()
    if #refreshers == 0 then
        return
    end
    refreshing = true
    for i = 1, #refreshers do
        pcall(refreshers[i])
    end
    refreshing = false
end

local function text(parent, template, str, x, y, width)
    local fs = parent:CreateFontString(nil, "ARTWORK", template)
    fs:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    fs:SetJustifyH("LEFT")
    if width then
        fs:SetWidth(width)
    end
    fs:SetText(str)
    return fs
end

local function header(parent, str, y)
    text(parent, "GameFontNormal", str, 16, y)
    local rule = parent:CreateTexture(nil, "ARTWORK")
    rule:SetPoint("TOPLEFT", parent, "TOPLEFT", 16, y - 18)
    rule:SetSize(RULE_W, 1)
    rule:SetColorTexture(1, 1, 1, 0.15)
end

local function newCheck(parent, label, x, y)
    local cb = CreateFrame("CheckButton", nil, parent, "UICheckButtonTemplate")
    cb:SetSize(24, 24)
    cb:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    local fs = cb.Text or cb.text
    if not fs then
        fs = parent:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
        fs:SetPoint("LEFT", cb, "RIGHT", 4, 0)
    end
    fs:SetText(label)
    return cb
end

local function checkbox(parent, key, label, x, y)
    local cb = newCheck(parent, label, x, y)
    cb:SetScript("OnClick", function(self)
        D()[key] = self:GetChecked() and true or false
    end)
    refreshers[#refreshers + 1] = function()
        cb:SetChecked(D()[key] and true or false)
    end
    Options.controls[key] = cb
end

local function newSlider(parent)
    local ok, s = pcall(CreateFrame, "Slider", nil, parent, "OptionsSliderTemplate")
    if ok and s then
        -- the template's own title and min/max captions are replaced by our label and value text
        for _, k in ipairs({ "Text", "Low", "High" }) do
            if s[k] and s[k].Hide then
                s[k]:Hide()
            end
        end
        return s
    end
    s = CreateFrame("Slider", nil, parent)
    s:SetOrientation("HORIZONTAL")
    s:SetThumbTexture("Interface\\Buttons\\UI-SliderBar-Button-Horizontal")
    local bg = s:CreateTexture(nil, "BACKGROUND")
    bg:SetColorTexture(0, 0, 0, 0.5)
    bg:SetPoint("LEFT", s, "LEFT", 0, 0)
    bg:SetPoint("RIGHT", s, "RIGHT", 0, 0)
    bg:SetHeight(6)
    return s
end

local function slider(parent, key, label, minV, maxV, step, fmt, y)
    text(parent, "GameFontHighlight", label, 16, y)
    local s = newSlider(parent)
    s:SetPoint("TOPLEFT", parent, "TOPLEFT", 20, y - 20)
    s:SetSize(SLIDER_W, 16)
    s:SetMinMaxValues(minV, maxV)
    s:SetValueStep(step)
    if s.SetObeyStepOnDrag then
        s:SetObeyStepOnDrag(true)
    end
    local val = text(parent, "GameFontNormal", "", 20 + SLIDER_W + 14, y - 19)
    local function snap(v)
        v = minV + floor((v - minV) / step + 0.5) * step
        v = tonumber(string.format("%.4f", v)) -- no float dust (0.15000000000000002)
        return math.max(minV, math.min(maxV, v))
    end
    s:SetScript("OnValueChanged", function(_, v)
        if type(v) ~= "number" then
            return
        end
        v = snap(v)
        val:SetText(string.format(fmt, v))
        if not refreshing then
            D()[key] = v
        end
    end)
    refreshers[#refreshers + 1] = function()
        local v = D()[key]
        if type(v) ~= "number" then
            return
        end
        s:SetValue(v)
        val:SetText(string.format(fmt, snap(v)))
    end
    Options.controls[key] = s
end

local function swatch(parent, key, label, x, y)
    local b = CreateFrame("Button", nil, parent)
    b:SetSize(22, 22)
    b:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    local border = b:CreateTexture(nil, "BACKGROUND")
    border:SetAllPoints(b)
    border:SetColorTexture(0.75, 0.75, 0.75, 1)
    local fill = b:CreateTexture(nil, "ARTWORK")
    fill:SetPoint("TOPLEFT", b, "TOPLEFT", 2, -2)
    fill:SetPoint("BOTTOMRIGHT", b, "BOTTOMRIGHT", -2, 2)
    local cap = text(parent, "GameFontHighlight", label, x + 30, y - 4)
    local function paint()
        local c = D()[key]
        if type(c) == "table" then
            fill:SetColorTexture(c[1] or 1, c[2] or 1, c[3] or 1, 1)
        end
    end
    b:SetScript("OnClick", function()
        if not ColorPickerFrame or not ColorPickerFrame.SetupColorPickerAndShow then
            return
        end
        local c = D()[key]
        local prev = { c[1], c[2], c[3] }
        ColorPickerFrame:SetupColorPickerAndShow({
            r = prev[1],
            g = prev[2],
            b = prev[3],
            hasOpacity = false,
            swatchFunc = function()
                local r, g, bl = ColorPickerFrame:GetColorRGB()
                D()[key] = { r, g, bl }
                paint()
            end,
            cancelFunc = function()
                D()[key] = { prev[1], prev[2], prev[3] }
                paint()
            end,
        })
    end)
    if not (ColorPickerFrame and ColorPickerFrame.SetupColorPickerAndShow) then
        b:Hide()
        cap:Hide()
    end
    refreshers[#refreshers + 1] = paint
    Options.controls[key] = b
end

local function button(parent, label, x, y, w, onClick)
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetSize(w, 24)
    b:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    b:SetText(label)
    b:SetScript("OnClick", function()
        pcall(onClick)
    end)
    return b
end

local function destinationText()
    local d, T = D(), ns.Target
    pcall(T.GetDestination, T)
    local using, picked = T.lastName, d.targetFrame
    if picked and using == picked then
        return "XP bar frame: " .. picked .. " (picked)"
    elseif picked then
        return "Picked frame " .. picked .. " is unavailable; using " .. (using or "the bottom-centre fallback")
    end
    return "XP bar frame: " .. (using and (using .. " (auto)") or "none found, using the bottom-centre fallback")
end

local function build()
    local panel = CreateFrame("Frame")
    Options.panel = panel
    text(panel, "GameFontNormalLarge", "XPOrbs", 16, -16)

    local y = -48
    header(panel, "General", y)
    y = y - 26
    checkbox(panel, "enabled", "Enabled", 16, y)
    checkbox(panel, "restedTint", "Rested tint", COL2, y)
    y = y - 26
    checkbox(panel, "trail", "Trail", 16, y)
    checkbox(panel, "questBursts", "Quest bursts", COL2, y)
    y = y - 26
    checkbox(panel, "showAtMax", "Show at max level", 16, y)
    checkbox(panel, "debug", "Debug log", COL2, y)

    y = y - 38
    header(panel, "Look", y)
    y = y - 26
    slider(panel, "density", "Orb multiplier", 25, 400, 25, "%d%%", y)
    y = y - 40
    slider(panel, "cap", "Max orbs per burst", 5, 80, 1, "%d", y)
    y = y - 40
    slider(panel, "size", "Orb size", 8, 32, 1, "%d", y)
    y = y - 40
    slider(panel, "flightTime", "Flight time", 0.4, 1.5, 0.05, "%.2f s", y)
    y = y - 42
    swatch(panel, "color", "Orb colour", 16, y)
    swatch(panel, "restedColor", "Rested colour", COL2, y)

    y = y - 38
    header(panel, "Style", y)
    y = y - 26
    local radios = {}
    for i, st in ipairs(STYLES) do
        local cb = newCheck(panel, st, 16 + (i - 1) * 140, y)
        cb:SetScript("OnClick", function()
            D().style = st
            Options:Refresh()
        end)
        radios[st] = cb
        Options.controls["style_" .. st] = cb
    end
    refreshers[#refreshers + 1] = function()
        local cur = D().style
        for _, st in ipairs(STYLES) do
            radios[st]:SetChecked(cur == st)
        end
    end
    y = y - 28
    local hint = text(panel, "GameFontHighlightSmall", "popstream: a burst at the corpse, then a stream to the bar. "
        .. "crossfade: orbs bloom at the corpse, then fly to the bar. stream: a plain stream from the target frame.",
        20, y, RULE_W - 8)
    hint:SetWordWrap(true)

    y = y - 44
    header(panel, "XP bar", y)
    y = y - 26
    local dest = text(panel, "GameFontHighlight", "", 16, y, RULE_W)
    refreshers[#refreshers + 1] = function()
        dest:SetText(destinationText())
    end
    y = y - 28
    button(panel, "Pick XP bar frame", 16, y, 150, function()
        ns.commands.pick("")
    end)
    button(panel, "Test burst", 176, y, 110, function()
        ns.commands.test("5")
    end)
    button(panel, "Reset", 296, y, 90, function()
        ns.commands.reset()
    end)

    panel:SetScript("OnShow", function()
        Options:Refresh()
    end)
    return panel
end

if Settings and Settings.RegisterCanvasLayoutCategory and Settings.RegisterAddOnCategory then
    local ok, err = pcall(function()
        local panel = build()
        Options.category = Settings.RegisterCanvasLayoutCategory(panel, "XPOrbs")
        Settings.RegisterAddOnCategory(Options.category)
    end)
    if not ok then
        Options.category, Options.err = nil, tostring(err)
    end
end

function ns.commands.options()
    if not Options.category then
        ns.Print("options: the settings panel isn't available ("
            .. (Options.err or "no Settings API on this client") .. "); use /xporbs commands instead")
        return
    end
    local ok = pcall(function()
        Settings.OpenToCategory(Options.category:GetID())
    end)
    if not ok then
        ns.Print("options: couldn't open the settings panel; try Esc > Options > AddOns > XPOrbs")
    end
end

table.insert(ns.statusProviders, function()
    if Options.category then
        return "options panel: registered"
    end
    return "options panel: unavailable (" .. (Options.err or "no Settings API") .. ")"
end)
