# Embedded libraries

XP Orbs embeds these libraries unmodified for its minimap button. They are not covered by the addon's
GPL-3.0-or-later licence; each keeps its own terms. LibStub loads only the newest copy of each library across
all installed addons, so these copies are used only when no other addon ships a newer one.

| Library | Version | Author | Licence | Source |
|---|---|---|---|---|
| LibStub | minor 2 | WowAce community | Public Domain | https://www.curseforge.com/wow/addons/libstub |
| CallbackHandler-1.0 | minor 8 | Nevcairiel and the Ace3 team | BSD 3-clause | https://www.curseforge.com/wow/addons/callbackhandler |
| LibDataBroker-1.1 | minor 4 | tekkub | No explicit licence (see below) | https://github.com/tekkub/libdatabroker-1-1 |
| LibDBIcon-1.0 | minor 57 | funkydude | Ace3-style BSD (no standalone redistribution) | https://www.curseforge.com/wow/addons/libdbicon-1-0 |

**LibDataBroker-1.1** has no licence file or header, and its CurseForge page shows the default "All Rights
Reserved". It was written to be embedded by other addons (its README and the "Addons using LDB" wiki list say so)
and has been embedded unmodified by thousands of addons since 2008. It is included here on that basis, credited to
tekkub. If the author or a rights holder objects, open an issue and it will be removed.

To update: copy the newer `.lua` file over the old one, update the version column above, and run the tests.
