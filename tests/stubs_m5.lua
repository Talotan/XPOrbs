-- M5 stub extensions: Settings, option-panel widgets (sliders, check buttons, font strings), ColorPickerFrame,
-- GLOBAL_MOUSE_DOWN picking helpers. Load AFTER stubs_m2.lua and BEFORE the addon files (Options.lua registers at
-- load). Called as a chunk with (ns).
local ns = ...
local stub = ns.stub
local fm = getmetatable(UIParent).__index

stub.settings = { registered = {}, added = {}, opened = {} }
Settings = {
    RegisterCanvasLayoutCategory = function(frame, name)
        local cat = { frame = frame, name = name, id = 100 + #stub.settings.registered }
        function cat.GetID()
            return cat.id
        end
        stub.settings.registered[#stub.settings.registered + 1] = cat
        return cat
    end,
    RegisterAddOnCategory = function(cat)
        stub.settings.added[#stub.settings.added + 1] = cat
    end,
    OpenToCategory = function(id)
        stub.settings.opened[#stub.settings.opened + 1] = id
    end,
}

ColorPickerFrame = {
    SetupColorPickerAndShow = function(self, info)
        self.info = info
        self.r, self.g, self.b = info.r, info.g, info.b
    end,
    GetColorRGB = function(self)
        return self.r, self.g, self.b
    end,
}

-- names / parents (the v0.9 wrapper only keeps the parent)
local baseCreate = CreateFrame
function CreateFrame(kind, name, parent, template)
    local f = baseCreate(kind, name, parent)
    f.name, f.template = name, template
    if parent ~= nil then
        f.createdParent = parent
    end
    if kind == "CheckButton" then
        f.checked = false
    end
    return f
end
function fm:GetName()
    return self.name
end
function fm:GetParent()
    return self.createdParent or self.parentFrame
end

-- no-op recorders for the cosmetic calls the panel makes
for _, name in ipairs({
    "SetJustifyH", "SetWordWrap", "SetColorTexture", "SetFontObject", "SetOrientation", "SetThumbTexture",
    "SetObeyStepOnDrag",
}) do
    fm[name] = function(self, ...)
        self.calls = self.calls or {}
        self.calls[name] = { ... }
    end
end
function fm:CreateFontString()
    local fs = CreateFrame("FontString")
    fs.parentFrame = self
    return fs
end
function fm:SetText(t)
    self.text = t
end
function fm:GetText()
    return self.text
end
function fm:SetChecked(b)
    self.checked = b and true or false
end
function fm:GetChecked()
    return self.checked
end

-- sliders: clamp, snap to the step, fire OnValueChanged(self, value, userInput) only when the value changed
function fm:SetMinMaxValues(a, b)
    self.minV, self.maxV = a, b
end
function fm:SetValueStep(s)
    self.step = s
end
function fm:SetValue(v)
    if self.minV then
        v = math.max(self.minV, math.min(self.maxV, v))
    end
    if self.step and self.step > 0 then
        v = (self.minV or 0) + math.floor((v - (self.minV or 0)) / self.step + 0.5) * self.step
    end
    if v ~= self.value then
        self.value = v
        local fn = self.scripts.OnValueChanged
        if fn then
            fn(self, v, false)
        end
    end
end
function fm:GetValue()
    return self.value or 0
end

-- what a user does: drag a slider, click a check button / button
function stub.slide(f, v)
    f:SetValue(v)
end
function stub.click(f)
    if f.kind == "CheckButton" then
        f.checked = not f.checked
    end
    local fn = f.scripts.OnClick
    if fn then
        fn(f, "LeftButton", false)
    end
end

-- picking
stub.focus = nil
function GetMouseFoci()
    return { stub.focus }
end
function stub.mouseDown(button)
    ns.fire("GLOBAL_MOUSE_DOWN", button)
end
function stub.namedFrame(name, parent)
    local f = CreateFrame("Frame", name, parent)
    _G[name] = f
    return f
end
