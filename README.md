# XPOrbs

Blue orbs fly from a killed mob to your XP bar, with the orb count proportional to the XP gained.
Target client: Blizzard WoW Forever (Interface 16001).

Status: M0 scaffold only (slash command skeleton, saved variables). See `docs/ROADMAP.md`.

## Install (dev)
Junction this folder into `_forever_\Interface\AddOns\XPOrbs` (not yet created).

## Commands
`/xporbs help | debug on|off | status | test [pct] | pick | reset | options`
(`test`, `pick`, `reset`, `options` are stubs until later milestones.)

## Dev
`uv run pytest -q` runs the Lua 5.1 test harness (lupa).
