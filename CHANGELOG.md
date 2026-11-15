# Changelog

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
