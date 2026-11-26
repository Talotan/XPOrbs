-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Pure logic: decides which of the six chime notes (if any) to play as an orb arrives. Each played note is a random
-- one of the six that differs from the previous note, so the pitch wobbles instead of climbing. At most one note per
-- `gap` seconds and `perBurst` notes per burst. Touches no WoW globals and allocates nothing per call once a burst's
-- counter exists (counters are cleared with Done).

local Chime = {}
ns.Chime = Chime
Chime.__index = Chime

local NOTES = 6

local function defaultRand(n)
    return math.random(n)
end

-- cfg = { now = fn, rand = fn(n) -> integer 1..n (default math.random), gap = min seconds between notes (0.07),
-- perBurst = notes per burst (6) }
function Chime.New(cfg)
    cfg = cfg or {}
    local self = setmetatable({}, Chime)
    self.now = cfg.now
    self.rand = cfg.rand or defaultRand
    self.gap = cfg.gap or 0.07
    self.perBurst = cfg.perBurst or 6
    self.lastAt = nil -- time of the last note played
    self.last = 0 -- index of the last note played (0 = none)
    self.counts = {} -- burstKey -> notes played for it so far
    return self
end

-- An orb of burst `burstKey` arrived. Returns the note index 1..6 to play, or nil for silence.
function Chime:Arrive(burstKey)
    if burstKey == nil then
        return nil
    end
    local now = self.now()
    local counts = self.counts
    local played = counts[burstKey] or 0
    if played >= self.perBurst then
        return nil
    end
    local lastTime = self.lastAt
    if lastTime ~= nil and now - lastTime < self.gap then
        return nil
    end
    local previousNote = self.last
    local note
    if previousNote == 0 then
        note = self.rand(NOTES)
        if note ~= note or note < 1 or note > NOTES then
            note = 1
        end
    else
        -- pick among the other five notes: draw 1..5 and skip over the previous one
        note = self.rand(NOTES - 1)
        if note ~= note or note < 1 or note > NOTES - 1 then
            note = 1
        end
        if note >= previousNote then
            note = note + 1
        end
    end
    note = note - note % 1 -- whole number even if the source returned a fraction
    self.lastAt = now
    self.last = note
    counts[burstKey] = played + 1
    return note
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
