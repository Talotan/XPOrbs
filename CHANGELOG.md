# Changelog

## 1.1.0 (2026-11-18)

- Orbs now match the XP bar's colours: purple normally, blue when rested. Saved colours that were still the old
  defaults update automatically; colours you changed are kept.
- The default flight time is now 1 s (it was 0.75 s, and a saved 0.75 s updates too).
- "Kill orbs at max level" now sends a small burst of orbs to your portrait when you kill something you were fighting.
- New optional chime as orbs arrive (off by default), with two sounds, glass (the default) and coin: pick one in
  the options panel or with `/xporbs sound glass|coin`. Both are quiet and wobble a little in pitch.
- Big pulls now show orbs for every kill: the orb pool holds two full bursts, and a crowded burst drops its trails or
  draws fewer orbs instead of leaving the later kills with none.
- Fixed the rare pop that appeared on the wrong mob, and the doubled orbs after XP was briefly unreadable.
- The gain that takes you to max level now shows its orbs.
- Level-ups are now read from the XP bar itself, so they no longer depend on event order.
- Damaged or hand-edited saved settings are repaired when the game loads them, and a failing frame can no longer
  leave orbs stuck on screen.
- The frame picker no longer picks nameplates.
- `/xporbs pick` now works on XP bars that ignore the mouse (such as EnhanceQoL's), and `/xporbs pick <FrameName>`
  sets one by name. EnhanceQoL's XP bar is also detected automatically, and orbs land on the bar's actual fill point,
  whichever way it fills.
- New `/xporbs perf` (memory and frame time) and `/xporbs test stress [n]` for checking performance.
- Now also on Wago.

## 1.0.1 (2026-11-15)

- The addon now shows as "XP Orbs" in the AddOns list and the options panel. The folder, `/xporbs` and saved settings
  are unchanged.
- First release on CurseForge.

## 1.0.0 (2026-11-15)

First public release, for WoW Forever (Interface 16001).

- XP gains send a burst of orbs to your XP bar. The number of orbs scales with the share of the level the gain gave.
- Kills start the burst at the mob: a short pop on its nameplate, then a stream from where the mob was on screen.
  Quest and other non-kill XP start a little above the centre of the screen.
- Rested XP is shown in a second colour.
- Three kill styles: `popstream` (default), `crossfade` and `stream`.
- An options panel (Esc > Options > AddOns > XPOrbs) covers orb quantity, maximum orbs, size, flight time, colour or
  class colour, rested colour, landing offset, the arrival glow and its intensity, and the kill style.
- `/xporbs pick` lets you click any frame as the destination, for UIs that replace the default XP bar.
- `/xporbs status`, `/xporbs test` and an optional debug log help with bug reports. The log never records mob names or
  GUIDs.
