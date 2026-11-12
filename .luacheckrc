std = "lua51"
max_line_length = 120

globals = {
    "XPOrbsDB",
    "SLASH_XPORBS1",
    "SlashCmdList.XPORBS",
}

read_globals = {
    "C_NamePlate",
    "C_AddOns",
    "Settings",
    "CreateFrame",
    "UIParent",
    "GetTime",
    "UnitGUID",
    "UnitName",
    "UnitIsDead",
    "UnitHealth",
    "UnitCanAttack",
    "UnitExists",
    "UnitLevel",
    "UnitIsUnit",
    "UnitXP",
    "UnitXPMax",
    "GetXPExhaustion",
    "GetMaxPlayerLevel",
    "issecretvalue",
    "SlashCmdList",
    "DEFAULT_CHAT_FRAME",
    "GetMouseFoci",
    "GetMouseFocus",
    "GetCursorPosition",
    "MainStatusTrackingBarContainer",
    "StatusTrackingBarManager",
    "MainMenuExpBar",
    "COMBATLOG_XPGAIN_FIRSTPERSON",
    "COMBATLOG_XPGAIN_FIRSTPERSON_GROUP",
    "COMBATLOG_XPGAIN_FIRSTPERSON_RAID",
    "COMBATLOG_XPGAIN_EXHAUSTION1",
    "COMBATLOG_XPGAIN_EXHAUSTION1_GROUP",
    "COMBATLOG_XPGAIN_EXHAUSTION1_RAID",
    "COMBATLOG_XPGAIN_EXHAUSTION2",
    "COMBATLOG_XPGAIN_EXHAUSTION2_GROUP",
    "COMBATLOG_XPGAIN_EXHAUSTION2_RAID",
    "COMBATLOG_XPGAIN_EXHAUSTION3",
    "COMBATLOG_XPGAIN_EXHAUSTION3_GROUP",
    "COMBATLOG_XPGAIN_EXHAUSTION3_RAID",
    "COMBATLOG_XPGAIN_EXHAUSTION4",
    "COMBATLOG_XPGAIN_EXHAUSTION4_GROUP",
    "COMBATLOG_XPGAIN_EXHAUSTION4_RAID",
    "COMBATLOG_XPGAIN_EXHAUSTION5",
    "COMBATLOG_XPGAIN_EXHAUSTION5_GROUP",
    "COMBATLOG_XPGAIN_EXHAUSTION5_RAID",
    "_G",
}

exclude_files = { "tests/" }

-- Pure logic must not touch any WoW global.
files["logic/"] = { read_globals = {} }
