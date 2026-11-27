-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- The Look tab: the orb shape dropdown, the per-shape settings box, the trail, the colours and the orb cap.

local kit = ns.OptionsKit
local Options = ns.Options
local settings, lookDefault, writeValue, changed = kit.settings, kit.lookDefault, kit.writeValue, kit.changed
local hex, onOff = kit.hex, kit.onOff
local showTip, showTip2, hideTip = kit.showTip, kit.showTip2, kit.hideTip
local newRow, label, newCheck, newRadio = kit.newRow, kit.label, kit.newCheck, kit.newRadio
local enable, setDim = kit.enable, kit.setDim
local addReset, checkbox, slider, swatch = kit.addReset, kit.checkbox, kit.slider, kit.swatch
local choiceRow, boxFrame = kit.choiceRow, kit.boxFrame
local refreshers, postRefresh = kit.refreshers, kit.postRefresh
local LABEL_X, CTRL_X = kit.LABEL_X, kit.CTRL_X
local GREY = kit.GREY
local BOX_X, BOX_LABEL_X, BOX_RESET_X, BOX_BOTTOM_PAD = kit.BOX_X, kit.BOX_LABEL_X, kit.BOX_RESET_X, kit.BOX_BOTTOM_PAD

local SWATCH_OFF_ALPHA = 0.35

local ORB_SHAPE_DESC = {
    starlight = "Soft glowing orbs with a spinning sparkle.",
    retro = "Chunky pixel-art orbs that move in blocky steps.",
    bubble = "Smooth glossy orbs with a long soft tail; they can gently pulse.",
    crackle = "A bright core with lightning crackling round its edge.",
}
local PULSE_TIP = "Bubble orbs gently swell and shrink."
local CAP_TIP = "Lowering the cap can improve performance on less powerful computers."

-- The orb shape's own reset: back to the default shape (which swaps the look settings, like picking it does).
local SHAPE_RESET = {
    default = function()
        return ns.defaults.orbShape
    end,
    reset = function()
        ns.SetOrbShape(ns.defaults.orbShape)
    end,
}

-- The "Orb shape" dropdown (db.orbShape, /xporbs shape): applies to every kill style, so it never dims. Built by
-- choiceRow (OptionsKit.lua), like the Flight tab's dropdowns.
local SHAPE_DROPDOWN = {
    key = "orbShape", text = "Orb shape", order = ns.SHAPE_ORDER, labels = ns.SHAPE_LABEL,
    desc = ORB_SHAPE_DESC, field = "shapeDropdown", radioX = { 0, 90, 165, 235 },
    -- switching shape also swaps in that shape's own size, quantity and opacity (ns.SetOrbShape)
    set = function(kind)
        ns.SetOrbShape(kind)
    end,
    reset = SHAPE_RESET,
}

-- The Look tab's boxed group: the settings that belong to the current orb shape. Its height is fixed (two option rows
-- always, even when empty), so switching shape never moves what is below. Rows inside hang off the box frame.
local BOX_TOP_PAD = 28
local BOX_H = BOX_TOP_PAD + 32 * 3 + 28 * 2 + BOX_BOTTOM_PAD -- (bottom pad 8: the option slot sits 2 px lower)
local BOX_GAP = 10 -- under the box
local GROUP_GAP = 8 -- between the global groups (flight / colours / cap)
local BLEND_TIP = { -- the Overlap Type option (db.blend)
    natural = "Soft glowing edge: orbs blend into each other, brightening where they overlap.",
    solid = "A dark outline round opaque orbs that stack in front of each other; colours stay true on bright ground.",
}
local BLEND_NAME = { natural = "Glow", solid = "Solid" }
local STARLIGHT_NOTE = "No outline or extras: Starlight is always a soft glow with a spinning sparkle."
local PIXEL_TIP = "The size of each art pixel."
-- Which shapes each option applies to (Core.lua: Starlight has no outline, only Retro sparkles, only Bubble pulses,
-- only Crackle has a speed)
local OPTION_SHAPES = {
    blend = { retro = true, bubble = true, crackle = true },
    sparkle = { retro = true },
    pulse = { bubble = true },
    crackleSpeed = { crackle = true },
}
local OPTION_NAME = { blend = "Overlap Type", sparkle = "Sparkle", pulse = "Pulsing", crackleSpeed = "Crackle speed" }
local CRACKLE_SPEED_TIP = "How fast the lightning round each orb changes. 200% is twice as fast."

local function currentShape()
    return ns.CanonShape(settings().orbShape) or ns.defaults.orbShape
end

local function optionApplies(key)
    return OPTION_SHAPES[key][currentShape()] and true or false
end

local function optionValueText(key, v)
    if key == "blend" then
        return BLEND_NAME[v] or tostring(v)
    end
    return onOff(v)
end

local function showIf(frame, on)
    if on then
        frame:Show()
    else
        frame:Hide()
    end
end

-- A reset for options that depend on the shape: a key the shape does not use counts as already at its default.
local function optionResetSpec()
    return {
        default = function(key)
            if optionApplies(key) then
                return lookDefault(key)
            end
            return settings()[key]
        end,
        reset = function(key)
            if optionApplies(key) then
                ns.SetLook(key, lookDefault(key))
            end
        end,
    }
end

local function optionDescribe(keys)
    return function()
        local parts = {}
        for _, key in ipairs(keys) do
            if optionApplies(key) then
                parts[#parts + 1] = OPTION_NAME[key] .. " " .. optionValueText(key, lookDefault(key)):lower()
            end
        end
        return #parts > 0 and table.concat(parts, ", ") or "nothing to reset"
    end
end

-- Option row A: "Overlap Type" with the Glow / Solid radios (Starlight: a grey note instead, centred across both rows).
local function blendRow(y)
    local row = newRow(y, 28)
    Options.rows.blend = row
    local note = label(row, STARLIGHT_NOTE, BOX_LABEL_X)
    note:SetTextColor(GREY, GREY, GREY)
    note:ClearAllPoints()
    note:SetPoint("LEFT", row, "LEFT", BOX_LABEL_X, -14)
    local blendLabel = label(row, OPTION_NAME.blend, BOX_LABEL_X)
    local radios = {}
    for i, kind in ipairs({ "natural", "solid" }) do
        local radio = newRadio(row, CTRL_X + (i - 1) * 100, BLEND_NAME[kind])
        radio:SetScript("OnClick", function()
            writeValue("blend", kind)
            Options:Refresh()
        end)
        radio:SetScript("OnEnter", function(self)
            showTip2(self, BLEND_NAME[kind], BLEND_TIP[kind])
        end)
        radio:SetScript("OnLeave", hideTip)
        radios[kind] = radio
        Options.controls["blend_" .. kind] = radio
    end
    refreshers[#refreshers + 1] = function()
        local blend = settings().blend
        for kind, radio in pairs(radios) do
            radio:SetChecked(blend == kind)
        end
    end
    postRefresh[#postRefresh + 1] = function()
        local on = optionApplies("blend")
        showIf(note, currentShape() == "starlight")
        showIf(blendLabel, on)
        for _, radio in pairs(radios) do
            showIf(radio, on)
            showIf(radio.xpLabel, on)
        end
    end
    addReset(row, "blend", { "blend" }, optionDescribe({ "blend" }), optionResetSpec(), BOX_RESET_X)
end

-- Option row B: the shape's extra, a standard checkbox row (Sparkle on Retro, Pulsing on Bubble); Crackle's speed
-- slider sits in the same slot (see buildShapeBox); empty on Starlight.
local function extraRow(y)
    local row = newRow(y, 28)
    Options.rows.shapeExtra, Options.rows.sparkle, Options.rows.pulse = row, row, row
    local ticks = {}
    for _, key in ipairs({ "sparkle", "pulse" }) do
        local caption = label(row, OPTION_NAME[key], BOX_LABEL_X)
        local cb = newCheck(row, CTRL_X - 3)
        cb:SetScript("OnClick", function(self)
            writeValue(key, self:GetChecked() and true or false)
            changed()
        end)
        if key == "pulse" then
            cb:SetScript("OnEnter", function(self)
                showTip(self, PULSE_TIP)
            end)
            cb:SetScript("OnLeave", hideTip)
        end
        ticks[key] = { cb, caption }
        Options.controls[key] = cb
    end
    refreshers[#refreshers + 1] = function()
        for key, pair in pairs(ticks) do
            pair[1]:SetChecked(settings()[key] and true or false)
        end
    end
    postRefresh[#postRefresh + 1] = function()
        for key, pair in pairs(ticks) do
            showIf(pair[1], optionApplies(key))
            showIf(pair[2], optionApplies(key))
        end
    end
    -- one reset button for whichever extra the shape has
    addReset(row, "shapeExtra", { "sparkle", "pulse" }, optionDescribe({ "sparkle", "pulse" }), optionResetSpec(),
        BOX_RESET_X)
    Options.resets.sparkle, Options.resets.pulse = Options.resets.shapeExtra, Options.resets.shapeExtra
end

local function sizeRange()
    return ns.ShapeRange(currentShape(), "size")
end

local function isRetro()
    return currentShape() == "retro"
end

-- Draws the box and fills it with size, quantity, opacity and the two option rows. Returns the y under it.
local function buildShapeBox(y)
    local box = boxFrame(y, BOX_H)
    Options.shapeBox = box
    local caption = box:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    caption:SetPoint("TOPLEFT", box, "TOPLEFT", BOX_LABEL_X - BOX_X, -8)
    caption:SetJustifyH("LEFT")
    caption:SetTextColor(GREY, GREY, GREY)
    Options.shapeBoxCaption = caption
    postRefresh[#postRefresh + 1] = function()
        caption:SetText(ns.SHAPE_LABEL[currentShape()] .. " settings")
    end

    kit.rowParent = box
    local ry = y + BOX_TOP_PAD
    slider(ry, "size", "Orb size", function()
        return isRetro() and "%d px" or "%d"
    end, function()
        return isRetro() and " px" or ""
    end, nil, {
        range = sizeRange,
        labelX = BOX_LABEL_X,
        resetX = BOX_RESET_X,
        label = function()
            return isRetro() and "Pixel size" or "Orb size"
        end,
        tip = function()
            return isRetro() and PIXEL_TIP or nil
        end,
        hint = function()
            return isRetro() and PIXEL_TIP or nil
        end,
    })
    slider(ry + 32, "density", "Orb quantity multiplier", "%d%%", "%", nil,
        { labelX = BOX_LABEL_X, resetX = BOX_RESET_X })
    slider(ry + 64, "opacity", "Orb opacity", "%d%%", "%", nil, { labelX = BOX_LABEL_X, resetX = BOX_RESET_X })
    blendRow(ry + 96)
    extraRow(ry + 126)
    -- Crackle's slider takes the extra row's slot: its 32 px row sits 2 px higher so the centre lines match
    slider(ry + 124, "crackleSpeed", OPTION_NAME.crackleSpeed, "%d%%", "%", nil,
        { labelX = BOX_LABEL_X, resetX = BOX_RESET_X, tip = CRACKLE_SPEED_TIP })
    postRefresh[#postRefresh + 1] = function()
        showIf(Options.rows.crackleSpeed, optionApplies("crackleSpeed"))
    end
    kit.rowParent = nil
    return y + BOX_H + BOX_GAP
end

local function buildLook(y)
    y = choiceRow(SHAPE_DROPDOWN, y)
    y = buildShapeBox(y)
    checkbox(y, "trail", "Trail")
    y = y + 28
    slider(y, "trailOpacity", "Trail opacity", "%d%%", "%", nil, { labelX = LABEL_X + 16 })
    postRefresh[#postRefresh + 1] = function()
        setDim(Options.rows.trailOpacity, { Options.controls.trailOpacity }, settings().trail)
    end
    y = y + 32 + GROUP_GAP

    -- Orb colour: swatch + "Class colour" checkbox; one reset button resets both
    local colourRow = newRow(y, 28)
    Options.rows.color = colourRow
    local colourLabel = label(colourRow, "Orb colour", LABEL_X)
    local swatchBtn = swatch(colourRow, "color", CTRL_X)
    local classColourCheck = newCheck(colourRow, 297)
    label(colourRow, "Class colour", 297 + 24 + 2)
    classColourCheck:SetScript("OnClick", function(self)
        settings().classColor = self:GetChecked() and true or false
        changed()
    end)
    refreshers[#refreshers + 1] = function()
        classColourCheck:SetChecked(settings().classColor and true or false)
    end
    Options.controls.classColor = classColourCheck
    addReset(colourRow, "color", { "color", "classColor" }, function()
        return hex(ns.defaults.color) .. ", class colour " .. onOff(ns.defaults.classColor)
    end)
    postRefresh[#postRefresh + 1] = function()
        local on = not settings().classColor
        enable(swatchBtn, on)
        swatchBtn:SetAlpha(on and 1 or SWATCH_OFF_ALPHA)
    end
    if not swatchBtn:IsShown() then
        colourLabel:Hide() -- no colour picker on this client: the colour can't be edited, class colour still works
    end

    -- Rested orb colour: the tickbox (db.restedTint) and its swatch (db.restedColor) in one row; the swatch sits under
    -- the Class colour tickbox above and dims while the tickbox is off. One reset button resets both.
    y = y + 30
    local restedRow = newRow(y, 28)
    Options.rows.restedTint, Options.rows.restedColor = restedRow, restedRow
    local restedLabel = label(restedRow, "Rested orb colour", LABEL_X)
    local restedCheck = newCheck(restedRow, CTRL_X - 3)
    restedCheck:SetScript("OnClick", function(self)
        settings().restedTint = self:GetChecked() and true or false
        changed()
    end)
    refreshers[#refreshers + 1] = function()
        restedCheck:SetChecked(settings().restedTint and true or false)
    end
    Options.controls.restedTint = restedCheck
    local restedSwatch = swatch(restedRow, "restedColor", 298)
    addReset(restedRow, "restedTint", { "restedTint", "restedColor" }, function()
        return onOff(ns.defaults.restedTint) .. ", " .. hex(ns.defaults.restedColor)
    end)
    if not restedSwatch:IsShown() then
        restedLabel:SetText("Rested tint") -- no colour picker on this client: only the tickbox is left
    end
    postRefresh[#postRefresh + 1] = function()
        local on = settings().restedTint and true or false
        enable(restedSwatch, on)
        restedSwatch:SetAlpha(on and 1 or SWATCH_OFF_ALPHA)
    end
    y = y + 28 + GROUP_GAP
    slider(y, "cap", "Max orbs per burst", "%d", "", nil, { tip = CAP_TIP })
    return y + 32
end

kit.pages.Look = buildLook
