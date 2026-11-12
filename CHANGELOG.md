# Changelog

## 0.2 (in progress)
- M1: pure logic modules: XPParse (real enUS XP-gain strings, rested/penalty/unnamed/quest variants), OrbMath (count, rested split, bezier, easing, fill edge, XP delta with level-up wrap), KillMatcher (death/chat/delta pairing, tiers, owed deltas). 68 new tests.
- Core: `ns.commands` and `ns.statusProviders` so modules register slash commands and status lines; `probe` default for M3.
- Placeholder Plates/Target/Orbs/Kills files in the toc so M2 and M3 can run in parallel.

## 0.1
- M0: scaffold, `.toc`, Core skeleton (defaults, DB init, debug log ring, `/xporbs` dispatcher), pytest + lupa harness.
