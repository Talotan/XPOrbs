-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- The General, Sound, Flight and Arrival tabs (and the Debug log row that closes General), with their texts.

local kit = ns.OptionsKit
local Options = ns.Options
local settings, showTip, showTip2, hideTip = kit.settings, kit.showTip, kit.showTip2, kit.hideTip
local text, newRow, label, newRadio = kit.text, kit.newRow, kit.label, kit.newRadio
local enable, setDim = kit.enable, kit.setDim
local addReset, checkbox, slider, button = kit.addReset, kit.checkbox, kit.slider, kit.button
local radioClick, newDropdown, choiceRow, boxFrame = kit.radioClick, kit.newDropdown, kit.choiceRow, kit.boxFrame
local refreshers, postRefresh = kit.refreshers, kit.postRefresh
local LABEL_X, CTRL_X, DROPDOWN_SIZE, HILITE = kit.LABEL_X, kit.CTRL_X, kit.DROPDOWN_SIZE, kit.HILITE
local DIM, GREY = kit.DIM, kit.GREY
local BOX_X, BOX_LABEL_X, BOX_RESET_X, BOX_BOTTOM_PAD = kit.BOX_X, kit.BOX_LABEL_X, kit.BOX_RESET_X, kit.BOX_BOTTOM_PAD

-- Kill styles (schema 6): three archetypes; Popstream has a Nameplate / Direct sub-choice (db.popMode). Each line says
-- whether the style uses the nameplate, the estimated mob position or both, and whether it has a pop.
local STYLES = { "popstream", "crossfade", "stream" }
local STYLE_NAME = { popstream = "Popstream", crossfade = "Crossfade", stream = "Direct Stream" }
local STYLE_DESC = {
    popstream = "A pop of orbs at the mob, then a stream to the bar. Pick where it pops:",
    crossfade = "Pop on the nameplate (if shown); the orbs reappear just above the bar.",
    stream = "A plain stream from the estimated position. No pop, no nameplate needed.",
}
local POPMODES = { "nameplate", "direct" }
local POPMODE_NAME = { nameplate = "Nameplate", direct = "Direct" }
local POPMODE_DESC = {
    nameplate = "Pop on the nameplate (if shown), stream from the estimated position.",
    direct = "Pop and stream from the estimated position. No nameplate needed.",
}
local SPREAD_DESC = "Wider when zoomed in, tighter when zoomed out."
local SPREAD_TIP = "Applies to all three styles: the nameplate pop, the pop or stream start at the estimated position. "
    .. "At the default camera zoom nothing changes. A mob you didn't mouse over always starts over a wide area that "
    .. "scales with zoom, whatever this says."
local DESC_DIM = 0.55 -- dimmed descriptions stay readable (rows and controls use DIM)
local SHAPES = { "bar", "vertical", "round" }
local SHAPE_NAME = { bar = "Horizontal", vertical = "Vertical", round = "Circular" }
local SHAPE_SPACING = 100 -- px between the shape radios
local SHAPE_TIP = {
    bar = "Orbs land on the bar's fill edge. A vertical bar the addon recognises gets the vertical glow automatically.",
    vertical = "A bar that fills bottom to top.",
    round = "The centre of a round frame, such as a portrait.",
}
local QUEST_TIP = "Orbs for quest turn-ins and other XP that is not a kill or exploration."
local EXPLORE_TIP = "Orbs for the XP you get from discovering a new area."
local FLIGHT_PATH_DESC = {
    smooth = "A clean arc from the mob to your XP bar.",
    chaos = "Orbs dart and weave like fireflies on the way.",
    helix = "Orbs spiral around each other in pairs.",
}
local STATUS_TIP = "Opens your addon status in a window to copy into a bug report"
local MAX_TIP = "At max level, each kill sends a small burst of orbs to your portrait."
local SOUND_TIP = "Glass: a glassy tink. Coin: a soft coin clink. Swish: a soft brushed whoosh. "
    .. "Pixel: a retro chip-tune ding. "
    .. "One per arriving orb (up to six per burst). On by default."
local PLAY_X = 156 -- px right of CTRL_X: just past the 150 px voice dropdown
local PLAY_ATLAS = "voicechat-icon-speaker"
local PLAY_FALLBACK = "Interface\\Common\\VoiceChat-Speaker"
local PLAY_TIP = "Play a sample: a handful of orbs arriving"
local VOICES = { "glass", "coin", "swish", "pixel" }
local VOICE_NAME = { glass = "Glass", coin = "Coin", swish = "Swish", pixel = "Pixel" }
local RADIO_STEP = 64 -- radio fallback: px between the four voice radios (they fit between CTRL_X and the reset button)
local OFFSET_TIP = "Moves where orbs land and the glow appears (pixels)."
local PICK_HINT = "For a replaced XP bar, or to target your portrait (Circular)."

local function destinationText()
    local saved, Target = settings(), ns.Target
    pcall(Target.GetDestination, Target)
    local using, picked = Target.lastName, saved.targetFrame
    local pickedSource = Target.PickSource(picked)
    if pickedSource then
        if Target.lastSource == pickedSource.id then
            return pickedSource.label .. " (picked)"
        end
        return "Picked " .. pickedSource.label .. " is unavailable; using "
            .. (using or "the bottom-centre fallback")
    end
    if picked and Target.lastSourceViaPick then
        return picked .. " (picked; using " .. Target.lastSourceLabel .. ")"
    elseif Target.lastSourceLabel and not picked then
        return Target.lastSourceLabel .. " (auto)"
    elseif picked and using == picked then
        return picked .. " (picked)"
    elseif picked then
        return "Picked frame " .. picked .. " is unavailable; using " .. (using or "the bottom-centre fallback")
    end
    return using and (using .. " (auto)") or "none found, using the bottom-centre fallback"
end

-- The "Sound" row under the chime checkbox: a modern dropdown (newDropdown) with arrows,
-- or one radio per voice when this client has no such template. Picking a voice plays one sample note,
-- even with the chime off, so the player can audition them before turning the chime on. The row stays enabled.
local function soundVoiceRow(y)
    local row = newRow(y, 28)
    Options.rows.soundVoice = row
    label(row, "Voice", LABEL_X + 24)
    local function pick(v)
        settings().soundVoice = v
        if ns.Orbs and ns.Orbs.PreviewSound then
            pcall(ns.Orbs.PreviewSound, ns.Orbs, v)
        end
        Options:Refresh()
    end
    local dropdown = newDropdown(row, function(_, root)
        for _, v in ipairs(VOICES) do
            root:CreateRadio(VOICE_NAME[v], function()
                return settings().soundVoice == v
            end, function()
                pick(v)
            end)
        end
    end)
    local playX = dropdown and dropdown.xpHost and DROPDOWN_SIZE.PLAY_X or PLAY_X
    if dropdown then
        Options.soundDropdown = dropdown
        Options.controls.soundVoice = dropdown
        refreshers[#refreshers + 1] = function()
            if dropdown.GenerateMenu then
                dropdown:GenerateMenu()
            end
        end
    else
        Options.soundDropdown = nil
        local radioBtns = {}
        playX = #VOICES * RADIO_STEP + 4 -- the sample button sits after the last radio
        for i, v in ipairs(VOICES) do
            local radio = newRadio(row, CTRL_X + (i - 1) * RADIO_STEP, VOICE_NAME[v])
            radio:SetScript("OnClick", function()
                pick(v)
            end)
            radioBtns[i] = radio
            Options.controls["soundVoice_" .. v] = radio
        end
        refreshers[#refreshers + 1] = function()
            for i, v in ipairs(VOICES) do
                radioBtns[i]:SetChecked(settings().soundVoice == v)
            end
        end
    end
    -- Play button right of the voice control: a sample of about six orbs arriving, through the real chime path. Dimmed
    -- and disabled with the chime off (the voice and volume stay usable so they can still be auditioned).
    local play = CreateFrame("Button", nil, row)
    play:SetSize(22, 22)
    play:SetPoint("LEFT", row, "LEFT", CTRL_X + playX, 0)
    local playTex = play:CreateTexture(nil, "ARTWORK")
    playTex:SetAllPoints(play)
    local okPlayAtlas = false
    if C_Texture and C_Texture.GetAtlasInfo then
        local okInfo, info = pcall(C_Texture.GetAtlasInfo, PLAY_ATLAS)
        if okInfo and info then
            okPlayAtlas = pcall(playTex.SetAtlas, playTex, PLAY_ATLAS)
        end
    end
    if not okPlayAtlas then
        playTex:SetTexture(PLAY_FALLBACK)
    end
    pcall(play.SetHighlightTexture, play, HILITE, "ADD")
    play:SetScript("OnClick", function()
        if ns.Orbs and ns.Orbs.PlayChimeSample then
            pcall(ns.Orbs.PlayChimeSample, ns.Orbs)
        end
    end)
    play:SetScript("OnEnter", function(self)
        showTip(self, PLAY_TIP)
    end)
    play:SetScript("OnLeave", hideTip)
    Options.controls.chimeSample = play
    postRefresh[#postRefresh + 1] = function()
        local on = settings().sound == true
        play:SetAlpha(on and 1 or DIM)
        enable(play, on)
    end
    addReset(row, "soundVoice", { "soundVoice" }, function()
        return VOICE_NAME[ns.defaults.soundVoice] or tostring(ns.defaults.soundVoice)
    end)
end

-- The sample played while dragging the Chime volume slider: one note at the new volume, at most one per
-- VOLUME_SAMPLE_GAP seconds so a drag across the whole bar isn't a machine gun.
local VOLUME_SAMPLE_GAP = 0.15
local lastVolumeSample = -math.huge
local function previewVolume()
    local now = GetTime and GetTime() or 0
    if now - lastVolumeSample < VOLUME_SAMPLE_GAP then
        return
    end
    lastVolumeSample = now
    if ns.Orbs and ns.Orbs.PreviewSound then
        pcall(ns.Orbs.PreviewSound, ns.Orbs, settings().soundVoice)
    end
end

-- ---------------------------------------------------------------- the sections
-- Each builder draws one tab's rows starting at y (8, the top of its own child frame) and returns the y after them.
-- Splitting them keeps every function well under Lua 5.1's 60-upvalue limit.

local function buildGeneral(y)
    for _, c in ipairs({
        { "enabled", "Enabled" },
        { "showAtMax", "Orbs at max level", { tip = MAX_TIP } },
        { "questBursts", "Quest bursts", { tip = QUEST_TIP } },
        { "exploreBursts", "Exploration bursts", { tip = EXPLORE_TIP } },
    }) do
        checkbox(y, c[1], c[2], c[3])
        y = y + 28
    end
    checkbox(y, "minimap", "Show minimap button", {
        get = function()
            return not settings().minimap.hide
        end,
        set = function(v)
            if ns.Minimap then
                ns.Minimap.SetShown(v)
            else
                settings().minimap.hide = not v
            end
        end,
    })
    return y + 28
end

-- The "Flight pathing" (db.flightPath, /xporbs path) and "Orb shape" (db.orbShape, /xporbs shape) dropdowns: both apply
-- to every kill style, so they never dim. Built like the Sound voice dropdown. Each option explains itself in its own
-- menu tooltip and the button's tooltip explains the current one, so no description takes page space. Radios replace
-- the dropdown on a client without the template. "Smooth (default)" inside the dropdown menu only; everywhere else
-- (button text, tooltips, radios) the plain name.
local FLIGHT_DROPDOWN = {
    key = "flightPath", text = "Flight pathing", order = ns.PATH_ORDER, labels = ns.PATH_LABEL,
    desc = FLIGHT_PATH_DESC, field = "flightDropdown", radioX = { 0, 140, 230 }, -- px right of CTRL_X (the first
    -- label is the long one)
}
-- The "Speed type" dropdown (db.flightMode): whether the Flight tab's one slider row is a speed or a time.
local SPEED_TYPE_DROPDOWN = {
    key = "flightMode", text = "Speed type", order = { "speed", "time" },
    labels = { speed = "Constant speed", time = "Relative speed" },
    desc = {
        speed = "Orbs always move at the same speed, wherever they start.",
        time = "Orbs from different locations move at different speeds so they always arrive after a set time.",
    },
    field = "speedTypeDropdown", radioX = { 0, 130 },
}

-- The "Orb layer" dropdown (db.orbStrata): the frame strata orbs and the flash draw in. A pick moves the live frames at
-- once (Orbs.ApplyStrata), and so does the row's reset.
local STRATA_LOW_NOTE = "The game menu and popups then draw over the orbs. Orbs from Test Kill may pass behind the "
    .. "preview windows."
local ORB_LAYER_DROPDOWN = {
    key = "orbStrata", text = "Orb layer", order = ns.STRATA_ORDER, labels = ns.STRATA_LABEL,
    desc = {
        BACKGROUND = "Behind most of the interface. " .. STRATA_LOW_NOTE,
        LOW = "Behind most windows. " .. STRATA_LOW_NOTE,
        MEDIUM = "Level with ordinary interface frames. " .. STRATA_LOW_NOTE,
        HIGH = "Above ordinary windows, below dialogs. " .. STRATA_LOW_NOTE,
        DIALOG = "Level with dialogs and the preview windows. " .. STRATA_LOW_NOTE,
        FULLSCREEN = "Above most windows, below the game menu and popups. " .. STRATA_LOW_NOTE,
        FULLSCREEN_DIALOG = "Above almost everything, including the game menu and other addons' windows.",
    },
    -- the radios are only drawn when no dropdown template exists (a tight fit)
    field = "orbStrataDropdown", radioX = { 0, 90, 140, 200, 250, 310, 400 },
    set = function(kind)
        settings().orbStrata = kind
        ns.Orbs.ApplyStrata()
    end,
    reset = {
        default = function(key)
            return ns.defaults[key]
        end,
        reset = function(key)
            settings()[key] = ns.defaults[key]
            ns.Orbs.ApplyStrata()
        end,
    },
}

local function flightStyleRow(y)
    return choiceRow(FLIGHT_DROPDOWN, y)
end

-- Flight: the Flight pathing dropdown, the Speed type dropdown and its one slider row (Flight speed or Flight time,
-- both at the same y; the one matching db.flightMode is shown, /xporbs flightmode switches it too), then the Kill style
-- group: three radios (row 24 + its description) indented 16 px under the header, Popstream's two sub-radios indented
-- under it at a tighter 42 px pitch with a wider gap after the group (dimmed unless Popstream is picked; clicking one
-- also picks Popstream), then the Zoom-scaled spread checkbox and its description (back on the label column).
local KILL_PAD = 10 -- above the first radio inside the kill style box (the box has no caption row)
local function buildFlight(y)
    y = flightStyleRow(y)
    y = choiceRow(SPEED_TYPE_DROPDOWN, y)
    slider(y, "flightSpeed", "Flight speed", "%d%%", "%")
    slider(y, "flightTime", "Flight time", "%.2f s", " s")
    postRefresh[#postRefresh + 1] = function()
        local speed = settings().flightMode ~= "time"
        local show, hide = Options.rows.flightSpeed, Options.rows.flightTime
        if not speed then
            show, hide = hide, show
        end
        show:Show()
        hide:Hide()
    end
    y = y + 32 + 4 -- a little air before the next group
    -- the three kill styles are their own group: a label so they don't read as options of the dropdown above
    text(kit.child, "GameFontHighlight", "Kill style", LABEL_X, -y)
    Options.killStyleLabelY = y
    y = y + 22
    -- their settings sit in a box like the Look tab's (no caption: the header above is its title); rows hang off it
    local KILL_ROWS_H = 278 -- the radios, sub-radios, descriptions and the spread row
    local boxY = y
    local box = boxFrame(boxY, KILL_PAD + KILL_ROWS_H + BOX_BOTTOM_PAD)
    Options.killBox = box
    kit.rowParent = box
    y = y + KILL_PAD
    local function boxText(str, x, ty, width)
        return text(box, "GameFontHighlight", str, x - BOX_X, -(ty - boxY), width)
    end
    local radios, subs = {}, {}
    local function tipOn(w, title, body)
        w:SetScript("OnEnter", function(self)
            showTip2(self, title, body)
        end)
        w:SetScript("OnLeave", hideTip)
    end
    local function styleRadio(styleKey, rowY)
        local row = newRow(rowY, 24)
        local radio = newRadio(row, BOX_LABEL_X, STYLE_NAME[styleKey])
        radio:SetScript("OnClick", function()
            radioClick("style", styleKey)
        end)
        radios[styleKey] = radio
        Options.controls["style_" .. styleKey] = radio
        Options.rows["style_" .. styleKey] = row
        local desc = boxText(STYLE_DESC[styleKey], BOX_LABEL_X + 24, rowY + 24, 474)
        desc:SetTextColor(GREY, GREY, GREY)
        Options.descs[styleKey] = desc
        return row
    end
    local prow = styleRadio("popstream", y)
    addReset(prow, "style", { "style", "popMode" }, function()
        return ns.StyleLabel(ns.defaults)
    end, nil, BOX_RESET_X)
    for i, pm in ipairs(POPMODES) do
        local ry = y + i * 42
        local row = newRow(ry, 24)
        local radio = newRadio(row, BOX_LABEL_X + 24, POPMODE_NAME[pm])
        radio:SetScript("OnClick", function()
            settings().style = "popstream" -- a sub-choice only means something under Popstream
            radioClick("popMode", pm)
        end)
        subs[pm] = radio
        Options.controls["popMode_" .. pm] = radio
        Options.rows["popMode_" .. pm] = row
        local desc = boxText(POPMODE_DESC[pm], BOX_LABEL_X + 48, ry + 24, 450)
        desc:SetTextColor(GREY, GREY, GREY)
        Options.descs[pm] = desc
    end
    styleRadio("crossfade", y + 136)
    styleRadio("stream", y + 182)
    refreshers[#refreshers + 1] = function()
        local saved = settings()
        for _, st in ipairs(STYLES) do
            radios[st]:SetChecked(saved.style == st)
        end
        for _, pm in ipairs(POPMODES) do
            subs[pm]:SetChecked(saved.popMode == pm)
        end
    end
    -- Zoom-scaled spread (db.zoomSpread, /xporbs wide): applies to every style, so it never dims. The unknown-position
    -- oval (db.unknownOrigin) is separate and has no control here.
    y = y + 236
    local _, scb = checkbox(y, "zoomSpread", "Zoom-scaled spread", { labelX = BOX_LABEL_X, resetX = BOX_RESET_X })
    tipOn(scb, "Zoom-scaled spread", SPREAD_TIP)
    local spreadDescText = boxText(SPREAD_DESC, BOX_LABEL_X, y + 28, 474)
    spreadDescText:SetWordWrap(true)
    spreadDescText:SetTextColor(GREY, GREY, GREY)
    Options.descs.zoomSpread = spreadDescText
    postRefresh[#postRefresh + 1] = function()
        local on = settings().style == "popstream"
        for _, pm in ipairs(POPMODES) do
            -- dimmed but still clickable: picking one also picks Popstream
            Options.rows["popMode_" .. pm]:SetAlpha(on and 1 or DIM)
            Options.descs[pm]:SetAlpha(on and 1 or DESC_DIM)
        end
    end
    kit.rowParent = nil
    return boxY + KILL_PAD + KILL_ROWS_H + BOX_BOTTOM_PAD
end

-- "Landing point" (db.targetAnchor): an Auto radio (the fill edge on a bar, the centre of a round frame) and, right of
-- it, a 3 x 3 grid of small radios laid out like the points they name (corners, edges, centre). The grid sits on a
-- little bar (an outline and a part-filled purple rect through the radio centres) so it reads as the XP bar frame. One
-- reset for the row. It stays live whatever the other settings say: the portrait that max-level bursts aim at is
-- automatic, not a setting.
local AIM_ROW_H = 62 -- three grid rows of 20 px, with a pixel or so of air
local AIM_GRID_X = 100 -- px right of CTRL_X: past the "Auto" radio and its caption
local AIM_COL, AIM_LINE = 50, 20 -- px between grid columns and between grid lines
local AIM_TIP = "Auto: the XP fill edge on a bar, the centre of a round frame."
local AIM_BAR_FILL = 0.58 -- the part of the little bar drawn filled
local AIM_BAR_RGB = { 0.447, 0.196, 0.518 } -- the XP bar purple, #723284
local function aimBar(row, left, top, w, h)
    local function rect(r, g, b, a, x1, y1, x2, y2)
        local tex = row:CreateTexture(nil, "BACKGROUND")
        tex:SetPoint("TOPLEFT", row, "TOPLEFT", x1, y1)
        tex:SetPoint("BOTTOMRIGHT", row, "TOPLEFT", x2, y2)
        tex:SetColorTexture(r, g, b, a)
        return tex
    end
    rect(AIM_BAR_RGB[1], AIM_BAR_RGB[2], AIM_BAR_RGB[3], 0.55, left, top, left + w * AIM_BAR_FILL, top - h)
    -- the 1 px outline, white at 30%: four thin rects (they are textures, so they never take the mouse)
    rect(1, 1, 1, 0.30, left, top, left + w, top - 1)
    rect(1, 1, 1, 0.30, left, top - h + 1, left + w, top - h)
    rect(1, 1, 1, 0.30, left, top, left + 1, top - h)
    rect(1, 1, 1, 0.30, left + w - 1, top, left + w, top - h)
end
local function buildAimRow(y)
    local row = newRow(y, AIM_ROW_H)
    Options.rows.targetAnchor = row
    label(row, "Landing point", LABEL_X)
    -- the radio centres: a radio is 20 px, placed at x - 2, -1 - line * AIM_LINE, so its centre is at x + 8, -11 - line
    local gridX = CTRL_X + AIM_GRID_X
    aimBar(row, gridX + 8, -11, 2 * AIM_COL, 2 * AIM_LINE)
    local radios = {}
    local function addRadio(value, x, rowIndex, caption, tip)
        local radio = newRadio(row, x, caption)
        if rowIndex then
            -- a grid cell: no caption, so no hit area past the radio itself, and placed on its own line of the row
            radio:ClearAllPoints()
            radio:SetPoint("TOPLEFT", row, "TOPLEFT", x - 2, -1 - rowIndex * AIM_LINE)
            pcall(radio.SetHitRectInsets, radio, 0, 0, 0, 0)
        end
        radio:SetScript("OnClick", function()
            radioClick("targetAnchor", value)
        end)
        radio:SetScript("OnEnter", function(self)
            showTip(self, tip)
        end)
        radio:SetScript("OnLeave", hideTip)
        radios[value] = radio
        Options.controls["targetAnchor_" .. value] = radio
    end
    addRadio("fill", CTRL_X, nil, "Auto", AIM_TIP)
    for i, point in ipairs(ns.AIM_POINTS) do
        addRadio(point, gridX + ((i - 1) % 3) * AIM_COL, math.floor((i - 1) / 3), "",
            ns.AIM_LABEL[point] .. " of the XP bar frame")
    end
    refreshers[#refreshers + 1] = function()
        local current = settings().targetAnchor
        for value, radio in pairs(radios) do
            radio:SetChecked(current == value)
        end
    end
    addReset(row, "targetAnchor", { "targetAnchor" }, function()
        return "Auto"
    end)
    return y + AIM_ROW_H + 6
end

-- Arrival: where the orbs land. The XP bar row (what was found, plus the picker) comes first, then the target frame's
-- shape and offsets and the glow. The shape and offsets stay live with Show glow off; only the intensity dims.
local function buildArrival(y)
    local destRow = newRow(y, 36)
    Options.rows.targetFrame = destRow
    label(destRow, "XP bar frame", LABEL_X)
    local dest = destRow:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    dest:SetPoint("LEFT", destRow, "LEFT", CTRL_X, 0)
    dest:SetWidth(280)
    dest:SetJustifyH("LEFT")
    dest:SetWordWrap(true)
    refreshers[#refreshers + 1] = function()
        dest:SetText(destinationText())
    end
    addReset(destRow, "targetFrame", { "targetFrame" }, function()
        return "auto-detect"
    end)
    y = y + 36
    local pickRow = newRow(y, 30)
    button(pickRow, "Pick XP bar frame", CTRL_X, 150, function()
        ns.commands.pick("")
    end)
    local pickHintText = text(kit.child, "GameFontHighlight", PICK_HINT, LABEL_X, -(y + 34), 520)
    pickHintText:SetWordWrap(true)
    pickHintText:SetTextColor(GREY, GREY, GREY)
    Options.pickHint = pickHintText
    y = y + 34 + 8 + 22 -- one hint line, then the gap between groups

    local shapeRow = newRow(y, 24)
    Options.rows.glowShape = shapeRow
    label(shapeRow, "Target frame shape", LABEL_X)
    local shapeBtns = {}
    for i, sh in ipairs(SHAPES) do
        local x = CTRL_X + (i - 1) * SHAPE_SPACING
        local radio = newRadio(shapeRow, x, SHAPE_NAME[sh])
        radio:SetScript("OnClick", function()
            radioClick("glowShape", sh)
        end)
        radio:SetScript("OnEnter", function(self)
            showTip2(self, SHAPE_NAME[sh], SHAPE_TIP[sh])
        end)
        radio:SetScript("OnLeave", hideTip)
        shapeBtns[#shapeBtns + 1] = radio
        Options.controls["glowShape_" .. sh] = radio
    end
    refreshers[#refreshers + 1] = function()
        local cur = settings().glowShape
        for i, sh in ipairs(SHAPES) do
            shapeBtns[i]:SetChecked(cur == sh)
        end
    end
    addReset(shapeRow, "glowShape", { "glowShape" }, function()
        return SHAPE_NAME[ns.defaults.glowShape] or tostring(ns.defaults.glowShape)
    end)
    y = buildAimRow(y + 32)
    slider(y, "glowOffsetX", "Target offset X", "%d px", " px")
    y = y + 32
    slider(y, "glowOffsetY", "Target offset Y", "%d px", " px")
    for _, key in ipairs({ "glowOffsetX", "glowOffsetY" }) do
        local offsetSlider = Options.controls[key]
        offsetSlider:SetScript("OnEnter", function(self)
            showTip(self, OFFSET_TIP)
        end)
        offsetSlider:SetScript("OnLeave", hideTip)
    end
    y = y + 36
    checkbox(y, "glow", "Show glow")
    y = y + 28
    slider(y, "glowIntensity", "Glow intensity", "%d%%", "%")
    postRefresh[#postRefresh + 1] = function()
        setDim(Options.rows.glowIntensity, { Options.controls.glowIntensity }, settings().glow ~= false)
    end
    return choiceRow(ORB_LAYER_DROPDOWN, y + 40) -- a group gap above it
end

local function buildSound(y)
    checkbox(y, "sound", "Chime when orbs arrive", { tip = SOUND_TIP })
    y = y + 28
    soundVoiceRow(y)
    y = y + 28
    slider(y, "soundVolume", "Chime volume", "%d%%", "%", previewVolume)
    -- dimmed with the chime off but left enabled (no controls passed), so a volume can still be auditioned and set
    postRefresh[#postRefresh + 1] = function()
        setDim(Options.rows.soundVolume, {}, settings().sound == true)
    end
    return y + 32
end

-- The Debug log row, then the Copy status button on a row of its own: both are for bug reports.
local function buildDebug(y)
    checkbox(y, "debug", "Debug log")
    local row = newRow(y + 30, 26)
    label(row, "Bug report", LABEL_X)
    Options.rows.copyStatus = row
    local copyStatus = button(row, "Copy status", CTRL_X, 110, function()
        ns.StatusWindow:Show()
    end)
    copyStatus:SetScript("OnEnter", function(self)
        showTip(self, STATUS_TIP)
    end)
    copyStatus:SetScript("OnLeave", hideTip)
    Options.controls.copyStatus = copyStatus
    return y + 58
end

-- The Debug log row closes the General tab after a 12 px gap.
kit.pages.General = function(y)
    return buildDebug(buildGeneral(y) + 12)
end
kit.pages.Sound = buildSound
kit.pages.Flight = buildFlight
kit.pages.Arrival = buildArrival
