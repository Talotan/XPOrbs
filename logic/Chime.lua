-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Pure logic: decides which of the six chime notes (if any) to play as an orb arrives. Notes climb one step per
-- played note (a pentatonic arpeggio), stay on the top note once they get there, and start again from the bottom after
-- a quiet moment. At most one note per `gap` seconds and `perBurst` notes per burst. Touches no WoW globals and
-- allocates nothing per call once a burst's counter exists (counters are cleared with Done).

local Chime = {}
ns.Chime = Chime
Chime.__index = Chime

local NOTES = 6

-- cfg = { now = fn, gap = min seconds between notes (0.07), perBurst = notes per burst (6), reset = quiet seconds
-- before the arpeggio restarts (0.5) }
function Chime.New(cfg)
    cfg = cfg or {}
    local self = setmetatable({}, Chime)
    self.now = cfg.now
    self.gap = cfg.gap or 0.07
    self.perBurst = cfg.perBurst or 6
    self.reset = cfg.reset or 0.5
    self.lastAt = nil -- time of the last note played
    self.step = 0 -- index of the last note played (0 = none)
    self.counts = {} -- burstKey -> notes played for it so far
    return self
end

-- An orb of burst `burstKey` arrived. Returns the note index 1..6 to play, or nil for silence.
function Chime:Arrive(burstKey)
    if burstKey == nil then
        return nil
    end
    local t = self.now()
    local counts = self.counts
    local played = counts[burstKey] or 0
    if played >= self.perBurst then
        return nil
    end
    local last = self.lastAt
    if last ~= nil and t - last < self.gap then
        return nil
    end
    if last == nil or t - last >= self.reset then
        self.step = 1
    elseif self.step < NOTES then
        self.step = self.step + 1
    end
    self.lastAt = t
    counts[burstKey] = played + 1
    return self.step
end

-- The burst has finished (all its orbs arrived or were freed): forget its counter.
function Chime:Done(burstKey)
    self.counts[burstKey] = nil
end

-- How many bursts have a counter (for tests).
function Chime:Open()
    local n = 0
    for _ in pairs(self.counts) do
        n = n + 1
    end
    return n
end
