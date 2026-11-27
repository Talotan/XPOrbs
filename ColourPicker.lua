-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- The colour swatch and the hue-keeping workaround for the game's colour picker (exported as kit.swatch).

local kit = ns.OptionsKit
local Options = ns.Options
local settings, changed, refreshers = kit.settings, kit.changed, kit.refreshers

-- Black has no hue, so a picker that round-trips through RGB snaps its wheel to the centre when the value slider hits 0
-- (and brings back grey). The ColorSelect widget keeps HSV: the last hue and saturation (value above HS_MIN_V) is
-- remembered per colour key in db.colorHS and pushed back whenever the picker loses it. All of it is optional: with no
-- HSV API nothing here does anything.
local HS_MIN_V = 0.02
local HS_EPS = 0.002
local pickerSyncing = false -- SetColorHSV may fire OnColorSelect -> swatchFunc again: ignore that echo

local function colorSelect()
    local content = ColorPickerFrame and ColorPickerFrame.Content
    local colourPicker = content and content.ColorPicker
    if type(colourPicker) == "table" and colourPicker.GetColorHSV and colourPicker.SetColorHSV then
        return colourPicker
    end
end

local function readHSV(colourPicker)
    local ok, h, s, v = pcall(colourPicker.GetColorHSV, colourPicker)
    if ok and type(h) == "number" and type(s) == "number" and type(v) == "number" then
        return h, s, v
    end
end

local function pushHSV(colourPicker, h, s, v)
    pickerSyncing = true
    pcall(colourPicker.SetColorHSV, colourPicker, h, s, v)
    pickerSyncing = false
end

local function rememberHS(key, h, s)
    local db = settings()
    if type(db.colorHS) ~= "table" then
        db.colorHS = {}
    end
    db.colorHS[key] = { h, s }
end

local function savedHS(key)
    local pair = type(settings().colorHS) == "table" and settings().colorHS[key]
    if type(pair) == "table" and type(pair[1]) == "number" and type(pair[2]) == "number" then
        return pair
    end
end

-- Called from the picker's swatchFunc with what the widget holds now.
local function keepHue(key)
    local colourPicker = colorSelect()
    if not colourPicker or pickerSyncing then
        return
    end
    local h, s, v = readHSV(colourPicker)
    if not h then
        return
    end
    if v > HS_MIN_V then
        rememberHS(key, h, s)
        return
    end
    local saved = savedHS(key)
    if saved and (math.abs(h - saved[1]) > HS_EPS or math.abs(s - saved[2]) > HS_EPS) then
        pushHSV(colourPicker, saved[1], saved[2], v)
    end
end

-- Right after the picker opens on a colour: remember its hue, or (opened on black) show the remembered one.
local function openHue(key, red, green, blue)
    local colourPicker = colorSelect()
    if not colourPicker then
        return
    end
    local value = math.max(red or 0, green or 0, blue or 0)
    if value <= HS_MIN_V then
        local saved = savedHS(key)
        if saved then
            pushHSV(colourPicker, saved[1], saved[2], value)
        end
        return
    end
    local h, s, v = readHSV(colourPicker)
    if h and v > HS_MIN_V then
        rememberHS(key, h, s)
    end
end

-- A colour swatch at x in the row. Returns the swatch button (hidden when there is no colour picker).
local function swatch(row, key, x)
    local swatchBtn = CreateFrame("Button", nil, row)
    swatchBtn:SetSize(22, 22)
    swatchBtn:SetPoint("LEFT", row, "LEFT", x, 0)
    local border = swatchBtn:CreateTexture(nil, "BACKGROUND")
    border:SetAllPoints(swatchBtn)
    border:SetColorTexture(0.75, 0.75, 0.75, 1)
    local fill = swatchBtn:CreateTexture(nil, "ARTWORK")
    fill:SetPoint("TOPLEFT", swatchBtn, "TOPLEFT", 2, -2)
    fill:SetPoint("BOTTOMRIGHT", swatchBtn, "BOTTOMRIGHT", -2, 2)
    local function paint()
        local colour = settings()[key]
        if type(colour) == "table" then
            fill:SetColorTexture(colour[1] or 1, colour[2] or 1, colour[3] or 1, 1)
        end
    end
    swatchBtn:SetScript("OnClick", function()
        if swatchBtn.IsEnabled and not swatchBtn:IsEnabled() then
            return
        end
        if not ColorPickerFrame or not ColorPickerFrame.SetupColorPickerAndShow then
            return
        end
        local colour = settings()[key]
        local prev = { colour[1], colour[2], colour[3] }
        ColorPickerFrame:SetupColorPickerAndShow({
            r = prev[1],
            g = prev[2],
            b = prev[3],
            hasOpacity = false,
            swatchFunc = function()
                if pickerSyncing then
                    return
                end
                local r, g, blue = ColorPickerFrame:GetColorRGB()
                settings()[key] = { r, g, blue }
                paint()
                changed()
                keepHue(key)
            end,
            cancelFunc = function()
                settings()[key] = { prev[1], prev[2], prev[3] }
                paint()
                changed()
            end,
        })
        openHue(key, prev[1], prev[2], prev[3])
    end)
    if not (ColorPickerFrame and ColorPickerFrame.SetupColorPickerAndShow) then
        swatchBtn:Hide()
    end
    refreshers[#refreshers + 1] = paint
    Options.controls[key] = swatchBtn
    return swatchBtn
end

kit.swatch = swatch
