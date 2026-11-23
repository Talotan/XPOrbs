-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Pure logic: remembers the GUIDs of the units the player has been fighting, for a few seconds. At max level the game
-- pays no XP, so a death only earns orbs when the dead unit was one of these. GUIDs are opaque strings: never logged,
-- only compared. Touches no WoW globals.

local Engaged = {}
ns.Engaged = Engaged
Engaged.__index = Engaged

-- cfg = { now = fn, window = seconds a mark stays valid (10), cap = most GUIDs kept (40) }
function Engaged.New(cfg)
    cfg = cfg or {}
    local self = setmetatable({}, Engaged)
    self.now = cfg.now
    self.window = cfg.window or 10
    self.cap = cfg.cap or 40
    self.seen = {} -- guid -> time of the last mark
    self.n = 0
    return self
end

-- Drops every mark older than the window.
function Engaged:Prune()
    local now, window = self.now(), self.window
    for guid, markedAt in pairs(self.seen) do
        if now - markedAt > window then
            self.seen[guid] = nil
            self.n = self.n - 1
        end
    end
end

local function evictOldest(self)
    local oldestGuid, oldestMarkedAt
    for guid, markedAt in pairs(self.seen) do
        if oldestMarkedAt == nil or markedAt < oldestMarkedAt then
            oldestGuid, oldestMarkedAt = guid, markedAt
        end
    end
    if oldestGuid ~= nil then
        self.seen[oldestGuid] = nil
        self.n = self.n - 1
    end
end

-- Marks a GUID as engaged now. Anything that is not a string is ignored.
function Engaged:Mark(guid)
    if type(guid) ~= "string" then
        return
    end
    if self.seen[guid] == nil then
        self:Prune()
        while self.n >= self.cap do
            evictOldest(self)
        end
        self.n = self.n + 1
    end
    self.seen[guid] = self.now()
end

-- True when the GUID was marked within the window.
function Engaged:IsEngaged(guid)
    if type(guid) ~= "string" then
        return false
    end
    local markedAt = self.seen[guid]
    if markedAt == nil then
        return false
    end
    if self.now() - markedAt > self.window then
        self.seen[guid] = nil
        self.n = self.n - 1
        return false
    end
    return true
end

-- How many GUIDs are held (after pruning expired ones).
function Engaged:Count()
    self:Prune()
    return self.n
end
