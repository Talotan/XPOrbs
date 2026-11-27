-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Arrival chime (ns.Sound): the chime object and its file paths, the note played when an orb lands, the options
-- panel's sample and preview, /xporbs sound and the session-wide "sound is dead" switch. Orbs.lua (loaded next) caches
-- Sound.Arrive and Sound.Done as locals for the driver and re-exposes the public methods (Orbs.chime,
-- Orbs:PlayChimeSample, Orbs:PreviewSound, Orbs:SoundDisabled).

local Sound = {}
ns.Sound = Sound

local random = math.random

local function settings()
    if not ns.db then
        ns:InitDB()
    end
    return ns.db
end

local function readable(v)
    return not issecretvalue or not issecretvalue(v)
end

local function isNumber(v)
    return type(v) == "number" and readable(v)
end

local function refreshPanel()
    if ns.Options and ns.Options.Refresh then
        ns.Options:Refresh()
    end
end

-- Every chime file, built once so nothing is concatenated while orbs fly: CHIME_PATHS[voice][volume][note]. The game
-- has no per-sound volume, so each volume level (ns.ranges.soundVolume, percent) is its own pre-rendered folder, made
-- by tools/make_sounds.py.
local CHIME_NOTES = 6
local CHIME_PATHS = { glass = {}, coin = {}, swish = {}, pixel = {} }
do
    local range = ns.ranges.soundVolume
    local lowest, highest, step = range[1], range[2], range[3]
    for voice, byVolume in pairs(CHIME_PATHS) do
        for volume = lowest, highest, step do
            local notePaths = {}
            for note = 1, CHIME_NOTES do
                notePaths[note] = "Interface\\AddOns\\XPOrbs\\media\\chime\\" .. volume .. "\\" .. voice
                    .. note .. ".ogg"
            end
            byVolume[volume] = notePaths
        end
    end
end
-- the six paths for a voice at the saved volume (a saved value that is off the grid falls back to the default level)
local function chimeNotePaths(voice)
    local byVolume = CHIME_PATHS[voice] or CHIME_PATHS.glass
    return byVolume[ns.db.soundVolume] or byVolume[ns.defaults.soundVolume]
end

local chime = ns.Chime.New({ now = GetTime, gap = 0.07, perBurst = 6 })
local soundDead = false -- the first sound failure switches the chime off for the session
Sound.chime = chime -- exposed for tests (Orbs.chime)

-- An orb arrived: asks the chime for a note and plays it. The first failure (an error, or the client saying the file
-- won't play) logs SOUND_ERR once and silences the chime for the session. Allocates nothing.
local function playChime(burstKey)
    local note = chime:Arrive(burstKey)
    if not note then
        return
    end
    local ok, willPlay = pcall(PlaySoundFile, chimeNotePaths(ns.db.soundVoice)[note], "SFX")
    if not ok or willPlay == false then
        soundDead = true
        ns:Log("SOUND_ERR %s", ok and "the client won't play the file" or string.sub(tostring(willPlay), 1, 120))
    end
end

-- Chime sample (the options panel's play button): the chime of a burst of SAMPLE_COUNT orbs arriving, through
-- playChime so the note progression and the per-note gap match real arrivals. A real burst's orbs land at slightly
-- different times, so each press draws fresh arrival times (seconds after the press) into one reused scratch table:
-- the first note at 0, the rest spread at random inside SAMPLE_SPAN, sorted, and never closer than SAMPLE_MIN_GAP
-- (the chime's own 70 ms rate limit, logic/Chime.lua, plus about one frame: notes play on frame ticks, so two notes
-- drawn just over 70 ms apart could land on frames under it and one would be dropped). The room beyond the
-- minimum gaps is SAMPLE_SPAN - (SAMPLE_COUNT - 1) * SAMPLE_MIN_GAP; sorted random draws share it out unevenly.
-- One short-lived OnUpdate that removes itself after the last note; a new press restarts it.
local SAMPLE_COUNT = 6
local SAMPLE_SPAN = 0.50
local SAMPLE_MIN_GAP = 0.085
local SAMPLE_OFFSETS = {}
for index = 1, SAMPLE_COUNT do
    SAMPLE_OFFSETS[index] = 0
end
Sound.sampleOffsets = SAMPLE_OFFSETS -- exposed for tests (Orbs.sampleOffsets)

-- Fills SAMPLE_OFFSETS in place: insertion-sorted random shares of the spare time, plus the minimum gaps.
local function drawSampleOffsets()
    local spare = SAMPLE_SPAN - (SAMPLE_COUNT - 1) * SAMPLE_MIN_GAP
    SAMPLE_OFFSETS[1] = 0
    for index = 2, SAMPLE_COUNT do
        local share = random() * spare
        local slot = index
        while slot > 2 and SAMPLE_OFFSETS[slot - 1] > share do
            SAMPLE_OFFSETS[slot] = SAMPLE_OFFSETS[slot - 1]
            slot = slot - 1
        end
        SAMPLE_OFFSETS[slot] = share
    end
    for index = 2, SAMPLE_COUNT do
        SAMPLE_OFFSETS[index] = SAMPLE_OFFSETS[index] + (index - 1) * SAMPLE_MIN_GAP
    end
end
local SAMPLE_KEY = "chime-sample" -- its own burst key, so it never eats a real burst's six-note allowance
local sampleFrame
local sampleNext, sampleElapsed = 1, 0

local function sampleStop()
    if sampleFrame then
        sampleFrame:SetScript("OnUpdate", nil)
    end
    chime:Done(SAMPLE_KEY)
    sampleNext = #SAMPLE_OFFSETS + 1
end

local function sampleTick(_, dt)
    sampleElapsed = sampleElapsed + (isNumber(dt) and dt or 0)
    while sampleNext <= #SAMPLE_OFFSETS and sampleElapsed >= SAMPLE_OFFSETS[sampleNext] do
        sampleNext = sampleNext + 1
        if ns.db.sound and not soundDead then
            playChime(SAMPLE_KEY)
        end
    end
    if sampleNext > #SAMPLE_OFFSETS then
        sampleStop()
    end
end

-- Starts (or restarts) the sample. Returns false when the chime is off or switched off for the session.
function Sound.PlayChimeSample()
    if not settings().sound or soundDead then
        return false
    end
    if not sampleFrame then
        sampleFrame = CreateFrame("Frame")
        Sound.sampleFrame = sampleFrame -- Orbs.sampleFrame (tests) follows it
    end
    chime:Done(SAMPLE_KEY)
    drawSampleOffsets()
    sampleNext, sampleElapsed = 1, 0
    sampleFrame:SetScript("OnUpdate", sampleTick)
    return true
end

-- Plays one random note of a voice at the saved volume so the options panel and /xporbs sound can preview it (even with
-- the chime off). One pcall, no state.
function Sound.PreviewSound(voice)
    if CHIME_PATHS[voice] and PlaySoundFile then
        pcall(PlaySoundFile, chimeNotePaths(voice)[random(CHIME_NOTES)], "SFX")
    end
end

-- /xporbs sound on|off|glass|coin|swish|pixel|volume N: the arrival chime. Turning it on also clears a SOUND_ERR
-- shutdown, so it can be retried. A voice name picks the sound (and turns the chime on). volume N sets the volume in
-- percent (snapped to the options slider's steps) and plays a sample note if the chime is on.
function ns.commands.sound(arg)
    local word, rest = string.match(arg or "", "^%s*(%S*)%s*(.-)%s*$")
    if word == "on" or CHIME_PATHS[word] then
        settings().sound = true
        if word ~= "on" then
            settings().soundVoice = word
        end
        soundDead = false
        refreshPanel()
    elseif word == "off" then
        settings().sound = false
        refreshPanel()
    elseif word == "volume" then
        local range = ns.ranges.soundVolume
        local percent = ns.OrbMath.Snap(ns.OrbMath.ParseNumber(rest), range[1], range[2], range[3])
        if not percent then
            ns.Print(string.format("sound: volume needs a number, %d to %d (percent)", range[1], range[2]))
            return
        end
        settings().soundVolume = percent
        refreshPanel()
        if settings().sound and not soundDead then
            Sound.PreviewSound(settings().soundVoice)
        end
    elseif word ~= "" then
        ns.Print("sound: use on, off, glass, coin, swish, pixel or volume N")
        return
    end
    local note = soundDead and " (switched off this session: the client wouldn't play the file)" or ""
    ns.Print(string.format("chime: %s, %s, volume %d%%%s", settings().sound and "on" or "off",
        tostring(settings().soundVoice),
        tonumber(settings().soundVolume) or ns.defaults.soundVolume, note))
end

-- true once a sound failure has switched the chime off for this session
function Sound.Disabled()
    return soundDead
end

-- An orb arrived (the driver's call): plays the next chime note unless the chime is off or dead. Allocates nothing.
function Sound.Arrive(burstKey)
    if ns.db.sound and not soundDead then
        playChime(burstKey)
    end
end

-- A burst's last orb is gone (or the sample ended): the chime forgets its note count.
function Sound.Done(burstKey)
    chime:Done(burstKey)
end
