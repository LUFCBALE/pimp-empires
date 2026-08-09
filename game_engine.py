"""
Pimp Empires - server-side game engine.

Ported from the client-side JS in pimp-empires.html so the server is the
single source of truth for every calculation (anti-cheat). Every function
here takes the full player `state` dict (loaded from SQLite as JSON) and
mutates it in place, returning either nothing or a small result dict for
UI feedback (toast text, whether a raid happened, etc).

Known bugs in the original client code that are intentionally FIXED here
(not preserved) because they were flagged as bugs, not design intent:
  - `gunsOwned` was never initialized (NaN-prone) -> initialized to 0.
  - Black market sell/buy used dotted stockKeys like "guns.pistol9mm" as a
    flat dict key instead of drilling into state['guns']['pistol9mm'] ->
    fixed to address the nested dict correctly.
  - `ensureBots()` regenerated the ENTIRE bot roster (wiping progress) any
    time the bot count didn't match 19 -> fixed to only ever create bots
    once; existing bots are never wiped/replaced.
  - Only the second (later-declared) `fightBot()` in the original file was
    ever live, since JS function declarations overwrite earlier ones with
    the same name. Only that version is ported here.
  - Bots never got a `.gang` name assigned despite GANG_NAMES existing ->
    bots are now assigned a gang name.
"""

import math
import random
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGEN_AMOUNT = 40
REGEN_MS = 20 * 60 * 1000

FACTORY_MS = 30 * 60 * 1000

MARKET_MS = 60 * 60 * 1000
MARKET_MIN_MULT = 0.5
MARKET_MAX_MULT = 1.8
MARKET_HISTORY_CAP = 24

BRIBE_DURATION_MS = 5 * 60 * 1000
BRIBE_COOLDOWN_MS = 60 * 60 * 1000
BRIBE_COST_PER_HOE = 15

LAY_LOW_DURATION_MS = 15 * 60 * 1000
LAY_LOW_COOLDOWN_MS = 8 * 60 * 60 * 1000
LAY_LOW_COST_PCT = 0.10

BOT_COUNT = 19
# Bots now regen/act on the exact same cadence and cap as a human player -
# they used to tick 4x faster (every 5 min) with a bigger turn pool (5000
# vs a human's 3600), which let them massively outpace real players'
# net worth/hoes even though nobody was actively playing them.
BOT_TICK_MS = REGEN_MS  # same 20-real-minute cadence as human turn regen
BOT_MAX_TURNS = 3600  # same cap as a human's maxTurns
BOT_MAX_TICKS_PER_CATCHUP = 72  # cap one catch-up burst at ~24 hours of simulated activity (72 * 20min) - a quiet overnight stretch with no requests shouldn't permanently cost bots a chunk of growth

# Bumped ~50% (avg 2.0 -> 3.0 per 10 turns) to match the same recruitment
# boost given to human players - hoe_earnings (regen_bots) is keyed off hoe
# count separately from this, so it isn't affected by the change.
HOE_RECRUIT_TURN_BLOCK = 10
HOE_RECRUIT_MIN = 2
HOE_RECRUIT_MAX = 4
THUG_RECRUIT_PER_TURN = 1

NIGHT_TURNS = 150
HOE_NIGHTLY_CAP = 2000

DAILY_BONUS_MS = 24 * 60 * 60 * 1000
DAILY_BONUS_AMOUNT = 1000

REALMONEY_COOLDOWN_MS = 12 * 60 * 60 * 1000
REALMONEY_MOB_DOLLARS = 50

# Must match GAME_DURATION_MS in pimp-empires.html (the per-player "Game
# ends in" countdown shown there is cosmetic - this is the authoritative
# shared clock used to decide when to actually award Hall of Fame prizes).
GAME_DURATION_MS = 7 * 24 * 60 * 60 * 1000
# Season 1's shared reset moment (2026-07-14 11:30:26 UTC, the gameStartTime
# every human got from that reset) + GAME_DURATION_MS. Only used to backfill
# world["seasonEndAt"] the one time that key is missing - a future season
# reset should set world["seasonEndAt"] explicitly to a fresh value.
SEASON_1_END_MS = 1784633426073

# Hall of Fame categories awarded once, permanently, when the season ends -
# see maybe_award_season_end_prizes in app.py (needs every human's saved
# state, so it can't live here alongside the rest of world catchup).
HOF_CATEGORIES = [
    ("statsThugsKilled", "most_thugs_killed"),
    ("statsFactoriesDestroyed", "most_factories_destroyed"),
    ("statsMoneyStolen", "most_money_stolen"),
    ("hoes", "most_hoes"),
    ("statsCarsStolen", "most_cars_stolen"),
    ("lifetimeEarnings", "top_earner"),
]

# Mob Dollars is the single currency behind every "get more turns" path -
# earned free from achievements/referrals, or topped up via the free
# buy_mob_dollars_with_real_money grant below (gated by a cooldown, unlike
# spending, which is always instant). Never cashable/withdrawable.
MOB_DOLLARS_TURNS_PER_UNIT = 10
ACHIEVEMENT_MOB_DOLLARS_DIVISOR = 10
ACHIEVEMENT_MOB_DOLLARS_MIN = 5

DEALER_RESET_MS = 10 * 60 * 1000
DEALER_DAILY_CAP = 100
DEALER_RESALE_COOLDOWN_MS = 10 * 60 * 1000

BLACKMARKET_ITEMS = [
    {"key": "pistol9mm", "name": "9mm Pistols", "price": 240, "gun": "pistol9mm"},
    {"key": "shotgun12gauge", "name": "12 Gauge Shotguns", "price": 1050, "gun": "shotgun12gauge"},
    {"key": "ak47", "name": "AK-47s", "price": 1800, "gun": "ak47"},
    {"key": "meds", "name": "Safety Kits", "price": 15, "stock": "medsStock"},
    {"key": "thugs", "name": "Thugs", "price": 100, "stock": "thugs"},
    {"key": "cars", "name": "Cadillacs", "price": 9600, "stock": "cadillacs"},
    {"key": "m249", "name": "M249s", "price": 8000, "gun": "m249", "sellOnly": True},
    {"key": "trucks", "name": "Armored Trucks", "price": 18000, "stock": "armoredTrucks", "sellOnly": True},
]
BLACKMARKET_BY_KEY = {i["key"]: i for i in BLACKMARKET_ITEMS}

DOPE_DEALER_DRUGS = [
    {"id": "weed", "baseBuyPrice": 12, "baseSellPrice": 20},
    {"id": "xanax", "baseBuyPrice": 20, "baseSellPrice": 32},
    {"id": "lsd", "baseBuyPrice": 35, "baseSellPrice": 55},
    {"id": "ecstasy", "baseBuyPrice": 50, "baseSellPrice": 80},
    {"id": "mdma", "baseBuyPrice": 60, "baseSellPrice": 95},
    {"id": "coke", "baseBuyPrice": 110, "baseSellPrice": 170},
    {"id": "ketamine", "baseBuyPrice": 120, "baseSellPrice": 185},
    {"id": "meth", "baseBuyPrice": 160, "baseSellPrice": 245},
    {"id": "heroin", "baseBuyPrice": 220, "baseSellPrice": 340},
]
DOPE_DEALER_BY_ID = {d["id"]: d for d in DOPE_DEALER_DRUGS}

TRAVEL_COST_PER_THUG = 50
TRAVEL_BASE_FEE = 100

# Traveling isn't just a cash toll anymore - you need enough cars to
# physically move your whole crew. Each cadillac seats 4 thugs, each
# armored truck seats 6; total capacity must cover your headcount.
TRAVEL_THUGS_PER_CADILLAC = 4
TRAVEL_THUGS_PER_ARMORED_TRUCK = 6

CITIES = [
    {"name": "London"},
    {"name": "Bristol"},
    {"name": "Birmingham"},
    {"name": "Manchester"},
    {"name": "Leeds"},
    {"name": "Liverpool"},
    {"name": "Amsterdam"},
    {"name": "Dublin"},
]
CITY_NAMES = [c["name"] for c in CITIES]

# Bots are split across 4 shared crews (not one unique gang name each) -
# multiple bots belong to the same crew, distributed randomly.
GANG_NAMES = ["The Players Club", "Gang of London", "Mighty Ducks", "Mafia"]

BOSS_NICKNAMES = [
    "Big Tony", "Fat Sal", "Mad Mikey", "Slick Rick", "Diesel", "Knuckles",
    "Vinnie Two-Times", "Bishop", "Reno", "Preacher", "Junior", "Spider",
    "Tank", "Cassius", "Duke", "Prince", "Smooth Eddie", "King Cobra",
    "Lil Rome", "Ghostface Greg",
]

THUG_NICKNAMES = [
    "Bruno", "Tiny", "Chains", "Razor", "Snake", "Hammer", "Bones", "Wolf",
    "Ghost", "Ace", "Rocco", "Spike", "Bull", "Cutter", "Torque", "Reaper",
    "Mack", "Deuce", "Sledge", "Fang",
]

HOE_FIRST_NAMES = [
    "Crystal", "Roxy", "Angel", "Scarlett", "Destiny", "Cherry", "Diamond",
    "Bambi", "Foxxy", "Candy", "Sapphire", "Velvet", "Star", "Jade",
    "Cinnamon", "Coco", "Amber", "Ruby", "Storm", "Blaze",
]
HOE_LAST_NAMES = [
    "Diamond", "Storm", "Fox", "Devine", "Nights", "Sinclair", "Delight",
    "Valentine", "LaRue", "Knight", "Sterling", "Vixen", "Monroe", "Dupree",
    "Steele", "St. Claire", "Rain", "Lace", "Winters", "Fatale", "Sunrise",
    "Rush", "Vice", "Wilde", "Chevalier", "Diamonte", "Delacroix", "Rivers",
    "Le Fleur", "Blaze",
]

WORK_LOCATIONS = {
    "redlight": {"bustRisk": 1.5, "thugRecruitMult": 0.7},
    "nightclub": {"bustRisk": 0.7, "thugRecruitMult": 1.0},
    "pullup": {"bustRisk": 0.4, "thugRecruitMult": 1.1},
}

# Base earnings per 100 hoes per 10 turns worked, at 100% collective hoe
# happiness. Red Light pays the most per hoe but recruits the fewest new
# hoes; Pull Up is the inverse - low pay, high recruitment, low bust risk.
WORK_LOCATION_BASE_EARN_PER_100_HOES_PER_10_TURNS = {
    "redlight": 35000,
    "nightclub": 31500,
    "pullup": 28000,
}

# Flat % bonus added on top of the base earnings above, biggest at the
# riskiest location.
WORK_LOCATION_AREA_BONUS_PCT = {
    "redlight": 0.03,
    "nightclub": 0.02,
    "pullup": 0.01,
}

# New hoes recruited per 10 turns worked, at 100% collective hoe happiness -
# scales with the *aggregate* hoeMorale, not each hoe's individual happiness.
# Bumped ~50% across the board - purely a recruitment boost, completely
# decoupled from WORK_LOCATION_BASE_EARN_PER_100_HOES_PER_10_TURNS above, so
# more hoes doesn't mean more cash per work session.
WORK_LOCATION_HOE_RECRUIT_BASE_PER_10_TURNS = {
    "redlight": 6,
    "nightclub": 8,
    "pullup": 11,
}

# Hoes take this cut of every session's gross earnings as their pay - it's
# just gone, not credited to cash or hoeCash anywhere.
HOE_WAGE_PCT = 0.10

HEIST_JOBS = {
    "shop": {"minThugs": 200, "turnCost": 10, "minCash": 25000, "maxCash": 75000,
             "successChance": 0.60, "casualtyPct": (0.05, 0.15), "failCasualtyPct": (0.15, 0.35),
             "netWorthPct": {"min": 0.00005, "max": 0.00015}},
    "jewellery": {"minThugs": 1000, "turnCost": 50, "minCash": 150000, "maxCash": 400000,
                  "successChance": 0.42, "casualtyPct": (0.10, 0.25), "failCasualtyPct": (0.30, 0.55),
                  "netWorthPct": {"min": 0.0002, "max": 0.0006}},
    "bank": {"minThugs": 5000, "turnCost": 150, "minCash": 750000, "maxCash": 2500000,
             "successChance": 0.28, "casualtyPct": (0.20, 0.40), "failCasualtyPct": (0.45, 0.80),
             "netWorthPct": {"min": 0.0008, "max": 0.0025}},
}
HEIST_JOB_COOLDOWN_MS = 6 * 3600 * 1000
CASINO_JOB = {
    "thugsPerMember": 10000, "turnsPerMember": 100, "minCash": 5000000, "maxCash": 15000000,
    "successChance": 0.35, "casualtyPct": (0.15, 0.30), "failCasualtyPct": (0.50, 0.90),
    "cooldownHours": 24,
    # Scales off the WHOLE crew's combined net worth (player + every crew
    # member), not just the player's own - the biggest heist in the game
    # should actually reflect how loaded the crew pulling it off is.
    "netWorthPct": {"min": 0.0005, "max": 0.0015},
}

FACTORY_COSTS = {
    "medical": 500000, "gun": 10000000, "car": 25000000, "drug": 50000000,
    "explosive": 75000000, "counterfeit": 100000000, "gym": 2000000,
    "warehouse": 5000000,
}

# Explicit per-factory sell/refund price (not a flat % of cost - each type
# has its own resale value now).
FACTORY_SELL_PRICES = {
    "medical": 250000, "gun": 5000000, "car": 12500000, "drug": 25000000,
    "explosive": 37500000, "counterfeit": 50000000, "gym": 1000000,
    "warehouse": 2500000,
}

# Real Estate is a progression ladder, not a shopping list you can max out
# on day one - each rank-up unlocks exactly one new factory type, roughly in
# order of tier/cost. Matches the `RANKS` levels defined further down.
# Warehouse shares Rank 2 with Gym rather than pushing every later factory's
# rank up a notch.
FACTORY_UNLOCK_RANK = {
    "medical": 1, "gym": 2, "warehouse": 2, "gun": 3, "car": 4,
    "drug": 5, "explosive": 6, "counterfeit": 7,
}

# All factory output rates below are boosted 30% over their original values,
# since a single factory's produce was worth very little next to what it
# actually costs.
DRUG_FACTORY_RATE = 2525  # cocaine produced per factory per tick

MEDICAL_KIT_RATE = 133  # safety kits produced per factory per tick
EXPLOSIVE_BOMB_RATE = 65  # bombs produced per factory per tick
COUNTERFEIT_CASH_RATE = 1000000  # cash printed per factory per tick
GYM_THUG_RATE = 10  # thugs recruited per factory per tick

# Car factories split their output between cadillacs (high-volume, more
# cash, small morale bump) and armored trucks (low-volume, more net worth
# per unit, big morale bump). `carFactoryRatio` is a 0.0-1.0 slider: 1.0 is
# all-in on cadillacs (46 cadillacs + 4 trucks per factory per tick), 0.0 is
# all-in on trucks (3 cadillacs + 13 trucks per factory per tick), and
# everything between is a straight linear blend.
CAR_FACTORY_CADILLAC_AT_MAX = 16
CAR_FACTORY_CADILLAC_AT_MIN = 3
CAR_FACTORY_ARMORED_AT_MAX = 0
CAR_FACTORY_ARMORED_AT_MIN = 13


def car_factory_output_rates(ratio):
    """Return (cadillac_rate, armored_rate) per factory per tick for a given
    0.0 (all trucks) .. 1.0 (all cadillacs) ratio."""
    ratio = clamp(ratio, 0.0, 1.0)
    cadillac_rate = CAR_FACTORY_CADILLAC_AT_MIN + (CAR_FACTORY_CADILLAC_AT_MAX - CAR_FACTORY_CADILLAC_AT_MIN) * ratio
    armored_rate = CAR_FACTORY_ARMORED_AT_MIN + (CAR_FACTORY_ARMORED_AT_MAX - CAR_FACTORY_ARMORED_AT_MIN) * ratio
    return cadillac_rate, armored_rate


# Gun factories split output across all 4 weapon types. `gunFactoryRatio` is
# a 0.0-1.0 slider: 0.0 is "volume" (39 pistols, 26 shotguns, 13 AKs, 3
# M249s per factory per tick), 1.0 is "elite" (3 pistols, 7 shotguns, 13
# AKs, 4 M249s), everything between is a straight linear blend.
GUN_FACTORY_PISTOL_AT_VOLUME = 25
GUN_FACTORY_PISTOL_AT_ELITE = 3
GUN_FACTORY_SHOTGUN_AT_VOLUME = 15
GUN_FACTORY_SHOTGUN_AT_ELITE = 5
GUN_FACTORY_AK_AT_VOLUME = 8
GUN_FACTORY_AK_AT_ELITE = 10
GUN_FACTORY_M249_AT_VOLUME = 1
GUN_FACTORY_M249_AT_ELITE = 3


def gun_factory_output_rates(ratio):
    """Return (pistol_rate, shotgun_rate, ak_rate, m249_rate) per factory
    per tick for a given 0.0 (volume) .. 1.0 (elite) ratio."""
    ratio = clamp(ratio, 0.0, 1.0)
    pistol_rate = GUN_FACTORY_PISTOL_AT_VOLUME + (GUN_FACTORY_PISTOL_AT_ELITE - GUN_FACTORY_PISTOL_AT_VOLUME) * ratio
    shotgun_rate = GUN_FACTORY_SHOTGUN_AT_VOLUME + (GUN_FACTORY_SHOTGUN_AT_ELITE - GUN_FACTORY_SHOTGUN_AT_VOLUME) * ratio
    ak_rate = GUN_FACTORY_AK_AT_VOLUME + (GUN_FACTORY_AK_AT_ELITE - GUN_FACTORY_AK_AT_VOLUME) * ratio
    m249_rate = GUN_FACTORY_M249_AT_VOLUME + (GUN_FACTORY_M249_AT_ELITE - GUN_FACTORY_M249_AT_VOLUME) * ratio
    return pistol_rate, shotgun_rate, ak_rate, m249_rate


def now_ms():
    return int(time.time() * 1000)


def jround(x):
    """Mimic JS Math.round (round-half-up), safe for negative values too."""
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


class GameError(Exception):
    """Raised for any invalid/rejected action; message is shown to the user."""
    pass


# ---------------------------------------------------------------------------
# Default state / bootstrapping
# ---------------------------------------------------------------------------

def default_state(pimp_name="Big Boss"):
    now = now_ms()
    state = {
        "name": pimp_name,
        "bio": "",
        "gang": "",
        "cash": 500,
        "hoes": 1,
        "thugs": 0,
        "turns": 2000,
        "maxTurns": 3600,
        "lastRegen": now,
        "hoeMorale": 50,
        "thugMorale": 50,
        "workLocation": "redlight",
        "location": random.choice(CITY_NAMES),
        "gunsStock": 0,
        "gunsOwned": 0,
        "guns": {"pistol9mm": 0, "shotgun12gauge": 0, "ak47": 0, "m249": 0},
        "cadillacs": 0,
        "armoredTrucks": 0,
        "medsStock": 1,
        "lifetimeEarnings": 0,
        "xp": 0,
        "achievements": [],
        "mobDollars": 0,
        "referredBy": None,
        "referralRewardPaid": False,
        "statsThugsKilled": 0,
        "statsFactoriesDestroyed": 0,
        "statsMoneyStolen": 0,
        "statsCarsStolen": 0,
        "statsJobsSucceeded": 0,
        "statsTurnsWorked": 0,
        "lastAttackedBy": None,
        "counterfeitEarnings": 0,
        "counterfeitStock": 0,
        "factories": {"medical": 0, "gun": 0, "car": 0, "drug": 0, "explosive": 0, "counterfeit": 0, "gym": 0, "warehouse": 0},
        "carFactoryRatio": 1.0,
        "gunFactoryRatio": 0.0,
        "bombs": 0,
        "lastFactoryRun": now,
        "market": {item["key"]: {"mult": 1.0, "history": [1.0]} for item in BLACKMARKET_ITEMS},
        "lastMarketUpdate": now,
        "lastCasinoHeist": 0,
        "lastJobHeist": 0,
        "bribeActiveUntil": 0,
        "bribeCooldownUntil": 0,
        "layLowUntil": 0,
        "layLowCooldownUntil": 0,
        "crewMembers": [],
        "crewAttackBans": {},
        "crewEmblem": "",
        "crewLeaderUserId": None,
        "crewLeaderName": "",
        # Only the crew LEADER's copy of this is ever authoritative/shared -
        # same rule as crewMembers. See build_crew_roster (app.py) and
        # send_crew_chat_message below.
        "crewChat": [],
        "pendingCrewInvites": [],
        # theJob (The Job) is leader-authoritative too - see start_the_job.
        "theJob": None,
        "theJobCooldownUntil": 0,
        "thugsInHospital": 0,
        "thugsHospitalReadyAt": 0,
        "drugs": {d["id"]: 0 for d in DOPE_DEALER_DRUGS},
        "dealerPrices": {},
        "dealerBoughtToday": {},
        "drugBoughtAt": {},
        "drugsPaidPrice": {},
        "lastDealerPriceUpdate": now,
        "gameStartTime": now,
        "last24HourBonus": now,
        "lastRealMoneyPurchase": 0,
        "showWorkResults": False,
        "showTutorial": True,
        "messages": [],
        "log": [],
        "pimpNameLocked": True,
    }
    return state


def add_log(state, msg, cls="info"):
    state["log"].append({"t": now_ms(), "msg": msg, "cls": cls})
    if len(state["log"]) > 60:
        state["log"] = state["log"][-60:]


def add_hoes(state, n):
    state["hoes"] = max(0, state.get("hoes", 0) + n)


def recalc_morale(state):
    """Happiness/morale are pure supply ratios - meds:hoes and guns:thugs,
    both 1:1 for 100% - recalculated fresh from current stock every time
    this runs. No decay, no drift, no bonus from heists or purchases;
    just "do you have enough," reflected live. Call this any time hoes,
    thugs, medsStock, or guns change, and unconditionally at the end of
    apply_catchup so it's always accurate regardless of which action ran."""
    hoes = state.get("hoes", 0)
    state["hoeMorale"] = min(100, jround(100 * state.get("medsStock", 0) / hoes)) if hoes > 0 else 100

    thugs = state.get("thugs", 0)
    if thugs > 0:
        total_guns = sum(state.get("guns", {}).values())
        state["thugMorale"] = min(100, jround(100 * total_guns / thugs))
    else:
        state["thugMorale"] = 100


def check_thug_attrition(state):
    if state["thugMorale"] <= 0 and state["thugs"] > 0:
        loss = max(1, math.ceil(state["thugs"] * 0.05))
        state["thugs"] = max(0, state["thugs"] - loss)


HOE_ATTRITION_HAPPINESS_THRESHOLD = 40
HOE_ATTRITION_MIN_CHANCE = 0.05  # chance a hoe walks, right at the 40% threshold
HOE_ATTRITION_MAX_CHANCE = 0.40  # chance at rock-bottom 0% happiness


def check_hoe_attrition(state):
    """Hoes are never lost to a raid/bust - the only way you lose them is
    letting happiness collapse. Below 40% happiness there's a small,
    escalating chance any given hoe walks per work session; by 0% happiness
    a lot of them go. Applied as an expected fraction of the roster against
    the aggregate hoeMorale, not tracked per-individual."""
    hoes = state.get("hoes", 0)
    happiness = state.get("hoeMorale", 100)
    if hoes <= 0 or happiness >= HOE_ATTRITION_HAPPINESS_THRESHOLD:
        return 0
    severity = 1 - (happiness / HOE_ATTRITION_HAPPINESS_THRESHOLD)
    leave_chance = HOE_ATTRITION_MIN_CHANCE + severity * (HOE_ATTRITION_MAX_CHANCE - HOE_ATTRITION_MIN_CHANCE)
    left = min(hoes, jround(hoes * leave_chance))
    if left:
        state["hoes"] -= left
    return left


# ---------------------------------------------------------------------------
# XP / Rank
# ---------------------------------------------------------------------------

# (level, name, xp required to reach it)
RANKS = [
    (1, "Junkie", 0),
    (2, "Street Rat", 1000),
    (3, "Foot Soldier", 3000),
    (4, "Associate", 10000),
    (5, "Gang Member", 25000),
    (6, "Gang Leader", 60000),
    (7, "Mob Boss", 120000),
    (8, "Underboss", 250000),
    (9, "Consigliere", 450000),
    (10, "Capo", 750000),
    (11, "Boss of Bosses", 1150000),
    (12, "Kingpin", 1750000),
    (13, "THE DON", 2500000),
]

XP_PER_TURN_SPENT = 1
ATTACK_XP_LOSS = 20
ATTACK_XP_WIN_BONUS = 30
BOMB_XP = 30
SELL_XP_PER_POUND = 0.0005  # 1 XP per £2,000 of produce sold


def add_xp(state, amount):
    if amount <= 0:
        return
    state["xp"] = state.get("xp", 0) + jround(amount)


def rank_info(xp):
    """Rank is always derived fresh from total xp, never stored separately -
    same "recompute, don't drift" approach as recalc_morale, so it can never
    go stale or desync from the xp total."""
    current = RANKS[0]
    next_rank = None
    for i, r in enumerate(RANKS):
        if xp >= r[2]:
            current = r
            next_rank = RANKS[i + 1] if i + 1 < len(RANKS) else None
        else:
            break
    return {
        "level": current[0],
        "name": current[1],
        "xp": xp,
        "xpIntoLevel": xp - current[2],
        "xpForLevel": (next_rank[2] - current[2]) if next_rank else 0,
        "nextLevel": next_rank[0] if next_rank else None,
        "nextName": next_rank[1] if next_rank else None,
        "xpToNext": (next_rank[2] - xp) if next_rank else 0,
    }


# Rank-up rewards: crossing into a new rank pays out a one-time cash prize
# on top of any XP from achievements, culminating in a big payout for
# reaching THE DON. Tracked in state["rankRewardsClaimed"] rather than
# recomputed fresh like rank itself, since a reward must never be paid out
# twice - even a big XP jump that skips straight past several ranks at once
# (a heist, an admin credit) still pays every rank crossed, one by one.
RANK_UP_CASH_REWARDS = {
    2: 5_000,
    3: 25_000,
    4: 100_000,
    5: 500_000,
    6: 2_000_000,
    7: 10_000_000,
    8: 30_000_000,
    9: 60_000_000,
    10: 100_000_000,
    11: 200_000_000,
    12: 400_000_000,
    13: 1_000_000_000,
}

# Referral rewards: paid via a shareable "?ref=<userId>" signup link. The new
# player gets a small welcome bonus instantly; the friend who invited them
# only gets paid once the new player actually sticks around long enough to
# reach Street Rat, not just for signing up - cheap friction against someone
# farming free Mob Dollars with throwaway accounts. See maybe_pay_referral_reward
# in app.py, which needs the referrer's own saved state so it can't live here.
REFERRAL_MILESTONE_XP = RANKS[1][2]  # 1000 XP = rank 2, "Street Rat"
REFERRAL_REWARD_MOB_DOLLARS = 50
REFERRAL_WELCOME_BONUS_MOB_DOLLARS = 10

# New-player catch-up: everyone shares one season clock (world["seasonEndAt"]),
# so someone who signs up mid-season would otherwise start from the exact same
# scratch line as day-one players with far less time to close the gap. Grant a
# one-time bonus that scales with how much of the season has already elapsed -
# nothing at hour one, a full grant near the end. Deliberately modest (tiny next
# to what a genuinely active player accumulates by then) so it helps a late
# joiner get going without being worth farming via throwaway accounts.
NEW_PLAYER_CATCHUP_MIN_ELAPSED_FRAC = 0.05
NEW_PLAYER_CATCHUP_CASH = 8000
NEW_PLAYER_CATCHUP_TURNS = 2000
NEW_PLAYER_CATCHUP_THUGS = 6
NEW_PLAYER_CATCHUP_HOES = 2
NEW_PLAYER_CATCHUP_MOB_DOLLARS = 15


def apply_new_player_catchup(state, world):
    """One-time late-join bonus on top of default_state, sized by how far
    into the shared season clock the account was created. Returns the grant
    dict (for logging/telemetry) or None if no bonus applied."""
    season_end = world.get("seasonEndAt")
    if not season_end:
        return None
    elapsed = now_ms() - (season_end - GAME_DURATION_MS)
    frac = max(0.0, min(1.0, elapsed / GAME_DURATION_MS))
    if frac < NEW_PLAYER_CATCHUP_MIN_ELAPSED_FRAC:
        return None

    cash = jround(NEW_PLAYER_CATCHUP_CASH * frac)
    turns = jround(NEW_PLAYER_CATCHUP_TURNS * frac)
    thugs = jround(NEW_PLAYER_CATCHUP_THUGS * frac)
    hoes = jround(NEW_PLAYER_CATCHUP_HOES * frac)
    mob_dollars = jround(NEW_PLAYER_CATCHUP_MOB_DOLLARS * frac)
    if cash <= 0 and turns <= 0 and thugs <= 0 and hoes <= 0 and mob_dollars <= 0:
        return None

    state["cash"] += cash
    state["turns"] = min(state["maxTurns"], state["turns"] + turns)
    state["thugs"] += thugs
    state["hoes"] += hoes
    state["mobDollars"] = state.get("mobDollars", 0) + mob_dollars
    add_log(
        state,
        f"🎁 Late-start bonus: +£{cash}, +{turns} turns, +{thugs} thugs, "
        f"+{hoes} hoes, +{mob_dollars} Mob Dollars - to help you catch up!",
        "good",
    )
    return {"cash": cash, "turns": turns, "thugs": thugs, "hoes": hoes, "mobDollars": mob_dollars}


def check_rank_rewards(state):
    """Called unconditionally from apply_catchup, same 'recompute, don't
    drift' entry point as check_milestone_achievements - safe to call on
    every load since already-claimed rewards are skipped."""
    rank = rank_info(state.get("xp", 0))
    claimed = state.setdefault("rankRewardsClaimed", [])
    for level, reward in RANK_UP_CASH_REWARDS.items():
        if rank["level"] >= level and level not in claimed:
            claimed.append(level)
            state["cash"] += reward
            rank_name = RANKS[level - 1][1]
            add_log(state, f"🎖️ Ranked up to {rank_name}! Bonus: £{reward}.", "good")


# ---------------------------------------------------------------------------
# Achievements
# ---------------------------------------------------------------------------

# GUN_TYPE_NAMES isn't defined yet at this point in the file, so this list
# is spelled out explicitly rather than referencing it.
ALL_GUN_TYPES = ("pistol9mm", "shotgun12gauge", "ak47", "m249")

ACHIEVEMENTS = [
    {"id": "first_blood", "name": "First Blood", "emoji": "🔰", "desc": "Win your first attack", "xp": 100},
    {"id": "demolition_man", "name": "Demolition Man", "emoji": "💣", "desc": "Complete your first bombing run", "xp": 100},
    {"id": "pulled_a_job", "name": "Pulled a Job", "emoji": "🕶️", "desc": "Win your first heist", "xp": 100},
    {"id": "high_roller", "name": "High Roller", "emoji": "🎰", "desc": "Win your first Casino Heist", "xp": 250},
    {"id": "real_estate_mogul", "name": "Real Estate Mogul", "emoji": "🏭", "desc": "Own your first factory", "xp": 100},
    {"id": "armed_to_the_teeth", "name": "Armed to the Teeth", "emoji": "🔫", "desc": "Own at least one of every gun type", "xp": 150},
    {"id": "crew_cut", "name": "Crew Cut", "emoji": "🤝", "desc": "Join or form a crew", "xp": 50},
    {"id": "gang_leader_rank", "name": "Gang Leader", "emoji": "👑", "desc": "Reach rank 6 (Gang Leader)", "xp": 300},
    {"id": "millionaire", "name": "Millionaire", "emoji": "💰", "desc": "Hit £1,000,000 net worth", "xp": 300},
    {"id": "tycoon", "name": "Tycoon", "emoji": "🏦", "desc": "Hit £100,000,000 net worth", "xp": 750},
    {"id": "the_don", "name": "THE DON", "emoji": "😈", "desc": "Reach max rank", "xp": 1000},
    {"id": "top_of_the_charts", "name": "Top of the Charts", "emoji": "🥇", "desc": "Reach #1 on the global leaderboard", "xp": 500},
    {"id": "top_ten", "name": "Top Ten", "emoji": "🥈", "desc": "Reach the top 10 on the global leaderboard", "xp": 200},
    {"id": "most_thugs_killed", "name": "Body Count King", "emoji": "💀", "desc": "Hold the #1 spot for Most Thugs Killed", "xp": 400},
    {"id": "most_money_stolen", "name": "Grand Larcenist", "emoji": "💸", "desc": "Hold the #1 spot for Most Money Stolen", "xp": 400},
    {"id": "most_factories_destroyed", "name": "Wrecking Ball", "emoji": "🧨", "desc": "Hold the #1 spot for Most Factories Destroyed", "xp": 400},
    {"id": "most_hoes", "name": "Easy Money", "emoji": "👠", "desc": "Hold the #1 spot for Most Hoes", "xp": 400},
    {"id": "most_cars_stolen", "name": "Chop Shop King", "emoji": "🚗", "desc": "Hold the #1 spot for Most Cars Stolen", "xp": 400},
    {"id": "top_earner", "name": "Top Earner", "emoji": "📈", "desc": "Hold the #1 spot for All Time Earnings", "xp": 400},
]
ACHIEVEMENTS_BY_ID = {a["id"]: a for a in ACHIEVEMENTS}


def award_achievement(state, achievement_id):
    """Awards an achievement once, ever - re-awarding is a safe no-op, so
    every call site can just call this unconditionally whenever the
    triggering event happens rather than tracking "have I checked this
    already" itself. Returns the achievement dict if newly earned, else
    None (used by callers that want to log/notify on a fresh unlock)."""
    earned = state.setdefault("achievements", [])
    if achievement_id in earned:
        return None
    ach = ACHIEVEMENTS_BY_ID.get(achievement_id)
    if not ach:
        return None
    earned.append(achievement_id)
    add_xp(state, ach["xp"])
    mob_dollars_reward = max(ACHIEVEMENT_MOB_DOLLARS_MIN, ach["xp"] // ACHIEVEMENT_MOB_DOLLARS_DIVISOR)
    state["mobDollars"] = state.get("mobDollars", 0) + mob_dollars_reward
    add_log(state, f"🏆 Achievement unlocked: {ach['emoji']} {ach['name']} (+{ach['xp']} XP, +{mob_dollars_reward} 🪙 Mob Dollars)", "good")
    return ach


def check_milestone_achievements(state):
    """Achievements derivable purely from the player's own state - called
    unconditionally from apply_catchup so they're picked up on every load
    without needing a hook at every mutation site, same "recompute, don't
    drift" approach as recalc_morale/rank_info. Leaderboard-position
    achievements (top_of_the_charts/top_ten) need visibility into every
    other player's net worth, which isn't available here - those are
    checked separately in app.py's attach_world_view."""
    if sum(state.get("factories", {}).values()) > 0:
        award_achievement(state, "real_estate_mogul")

    guns = state.get("guns", {})
    if all(guns.get(g, 0) > 0 for g in ALL_GUN_TYPES):
        award_achievement(state, "armed_to_the_teeth")

    if state.get("gang"):
        award_achievement(state, "crew_cut")

    rank = rank_info(state.get("xp", 0))
    if rank["level"] >= 6:
        award_achievement(state, "gang_leader_rank")
    if rank["level"] >= 13:
        award_achievement(state, "the_don")

    nw = total_net_worth(state)
    if nw >= 1_000_000:
        award_achievement(state, "millionaire")
    if nw >= 100_000_000:
        award_achievement(state, "tycoon")


# ---------------------------------------------------------------------------
# Bots
# ---------------------------------------------------------------------------

# Each bot plays with a distinct style instead of one flat growth curve:
#   hustler  - invests hard in hoes, banks cash fastest
#   enforcer - invests hard in thugs, more muscle than money
#   mogul    - saves aggressively and plows cash into buying factories
#   shark    - preys on other bots in the same city, skimming their hoeCash
# reinvestRate controls what fraction of surplus cash gets banked toward the
# next factory purchase each tick (see bot_reinvest_cash). Doubled across the
# board from the original 0.10-0.35 range: with a single random factory type
# as the savings target (costs range £940k-32M) and only a small per-tick
# slice of surplus actually going toward it, bots were routinely still
# sitting on a half-finished factorySavings pot with zero (or just one)
# factories to show for a full day of play, while active human players
# racked up 5-10x that net worth in the same stretch. At 2x, an unlucky
# expensive first target (car/gun at £25-30M) still clears within about
# half a day instead of potentially the whole day.
BOT_ARCHETYPES = {
    "hustler": {"hoeGrowth": 1.4, "thugGrowth": 0.7, "cashRate": 1.0, "raidChance": 0.0, "reinvestRate": 0.40},
    "enforcer": {"hoeGrowth": 0.7, "thugGrowth": 1.5, "cashRate": 1.0, "raidChance": 0.05, "reinvestRate": 0.30},
    "mogul": {"hoeGrowth": 1.0, "thugGrowth": 0.9, "cashRate": 1.4, "raidChance": 0.0, "reinvestRate": 0.70},
    "shark": {"hoeGrowth": 0.9, "thugGrowth": 1.1, "cashRate": 0.9, "raidChance": 0.25, "reinvestRate": 0.20},
}
# Bots buy every factory type except explosive (bombs) - a deliberate call
# to keep bots out of the bomb-production business.
BOT_FACTORY_TYPES = ("medical", "gun", "car", "drug", "counterfeit", "gym", "warehouse")

# Bots keep this much hoeCash on hand as walking-around money - anything
# above it gets plowed into guns/cars each tick (see bot_reinvest_hoecash)
# instead of just piling up as a raid target.
BOT_HOECASH_REINVEST_FLOOR = 15000
BOT_REINVEST_GUN_PRICES = {"pistol9mm": 240, "shotgun12gauge": 1050, "ak47": 1800, "m249": 8000}
BOT_REINVEST_CAR_PRICE = 9600
# Bots have no dealer/drug-selling loop to plug real coke output into, so a
# drug factory just pays out cash directly each tick like counterfeit does -
# calibrated to roughly the same cost:payout ratio as counterfeit (~0.21%
# of factory cost per tick) so it's neither a dead purchase nor a strictly
# better one.
BOT_DRUG_CASH_RATE = 29750
# Bots liquidate most of what a car factory makes for cash, but hold onto a
# slice of the fleet instead of selling 100% every tick - otherwise "Steal
# Cars" against a bot always finds nothing to steal.
BOT_CAR_KEEP_PCT = 0.25


def make_bot(bot_id, used_bosses, gang, city):
    boss = next((b for b in BOSS_NICKNAMES if b not in used_bosses), None) or random.choice(BOSS_NICKNAMES)
    used_bosses.add(boss)

    thugs = 20 + random.randint(0, 79)
    hoes = 4 + random.randint(0, 19)
    thug_names = random.sample(THUG_NICKNAMES, min(4, len(THUG_NICKNAMES)))
    hoe_names = [f"{random.choice(HOE_FIRST_NAMES)} {random.choice(HOE_LAST_NAMES)}" for _ in range(min(4, hoes))]

    # 20% of crews are caught totally unarmed - a real liability in a fight,
    # no matter how many thugs they've got. The rest are armed to varying
    # degrees, split randomly across gun types.
    if random.random() < 0.2:
        guns = {"pistol9mm": 0, "shotgun12gauge": 0, "ak47": 0, "m249": 0}
    else:
        armed_count = int(thugs * random.uniform(0.1, 0.5))
        pistols = random.randint(0, armed_count)
        remaining = armed_count - pistols
        shotguns = random.randint(0, remaining)
        remaining -= shotguns
        aks = random.randint(0, remaining)
        remaining -= aks
        guns = {"pistol9mm": pistols, "shotgun12gauge": shotguns, "ak47": aks, "m249": remaining}

    return {
        "id": bot_id,
        "boss": boss,
        "gang": gang,
        "archetype": random.choice(list(BOT_ARCHETYPES.keys())),
        "city": city,
        "thugs": thugs,
        "thugNames": thug_names,
        "cash": 4000 + random.randint(0, 15999),
        "hoes": hoes,
        "hoeNames": hoe_names,
        "hoeCash": 3000 + random.randint(0, 11999),
        "turns": BOT_MAX_TURNS,
        "maxTurns": BOT_MAX_TURNS,
        "thugMorale": 50,
        "hoeMorale": 50,
        "guns": guns,
        "cadillacs": 0,
        "armoredTrucks": 0,
        "factories": {
            # Bots start with no factories - moguls earn theirs over time by
            # actually playing (see regen_bots), so factory ownership on the
            # leaderboard reflects real progress, not a creation-time lottery.
            "medical": 0,
            "gun": 0,
            "car": 0,
            "drug": 0,
            "explosive": 0,
            "counterfeit": 0,
            "gym": 0,
            "warehouse": 0,
        },
        "factorySavings": 0,
        "nextFactoryTarget": random.choice(BOT_FACTORY_TYPES),
        "lastRegen": now_ms(),
    }


def even_crew_assignments(count):
    """Deal `count` bots out across the 4 crews as evenly as possible (e.g.
    19 -> 5/5/5/4), shuffled so it's not always the same crew that's short
    a member. No crew ever exceeds the 5-member cap used for real crews."""
    base, extra = divmod(count, len(GANG_NAMES))
    sizes = [base + 1 if i < extra else base for i in range(len(GANG_NAMES))]
    gangs_shuffled = GANG_NAMES[:]
    random.shuffle(gangs_shuffled)  # so it's not always the same crew that ends up short
    assignments = []
    for gang, size in zip(gangs_shuffled, sizes):
        assignments.extend([gang] * size)
    random.shuffle(assignments)
    return assignments


def ensure_bots(world):
    """Only ever creates the initial roster once. Never wipes existing bots.
    `world` is the single shared world dict ({"bots": [...], "botCrewEmblems":
    {...}}) - bots are global, not per-player, so every human player competes
    against and can see the exact same roster."""
    ensure_bot_crew_cities(world)
    if not world.get("bots"):
        used_bosses = set()
        crew_assignments = even_crew_assignments(BOT_COUNT)
        world["bots"] = [
            make_bot(i + 1, used_bosses, crew_assignments[i], world["botCrewCities"][crew_assignments[i]])
            for i in range(BOT_COUNT)
        ]
    ensure_bot_crew_emblems(world)
    for b in world["bots"]:
        if "guns" not in b:
            b["guns"] = {"pistol9mm": 0, "shotgun12gauge": 0, "ak47": 0, "m249": 0}
        if "cadillacs" not in b:
            b["cadillacs"] = 0
        if "armoredTrucks" not in b:
            b["armoredTrucks"] = 0
        if "counterfeit" not in b.get("factories", {}):
            b.setdefault("factories", {})["counterfeit"] = 0
        if "gym" not in b.get("factories", {}):
            b.setdefault("factories", {})["gym"] = 0
        if "drug" not in b.get("factories", {}):
            b.setdefault("factories", {})["drug"] = 0
        if "warehouse" not in b.get("factories", {}):
            b.setdefault("factories", {})["warehouse"] = 0
        if "factorySavings" not in b:
            b["factorySavings"] = 0
        if b.get("nextFactoryTarget") not in BOT_FACTORY_TYPES:
            b["nextFactoryTarget"] = random.choice(BOT_FACTORY_TYPES)


def ensure_bot_crew_emblems(world):
    """Each of the 4 street crews gets a random emblem image, assigned
    once. First come, first served: no two crews (bot or player) share
    one. Also re-rolls if the stored set is still the old emoji style
    (from before real emblem images existed) or references an id that no
    longer exists in the image catalog."""
    current = world.get("botCrewEmblems")
    stale = not current or any(e not in CREW_EMBLEM_IMAGES for e in current.values())
    if not stale:
        return
    available = random.sample(list(CREW_EMBLEM_IMAGES.keys()), len(GANG_NAMES))
    world["botCrewEmblems"] = dict(zip(GANG_NAMES, available))


def ensure_bot_crew_cities(world):
    """Each of the 4 street crews lives in one shared city, assigned once -
    gang-mates actually crew up in person instead of being scattered
    randomly across the map despite supposedly running together."""
    if world.get("botCrewCities"):
        return
    cities = random.sample(CITY_NAMES, len(GANG_NAMES))
    world["botCrewCities"] = dict(zip(GANG_NAMES, cities))


def bots_in_city(world, city_name):
    return [b for b in world["bots"] if b["city"] == city_name]


def factory_sell_value(factories):
    f = factories
    return (
        f.get("medical", 0) * FACTORY_SELL_PRICES["medical"]
        + f.get("gun", 0) * FACTORY_SELL_PRICES["gun"]
        + f.get("car", 0) * FACTORY_SELL_PRICES["car"]
        + f.get("drug", 0) * FACTORY_SELL_PRICES["drug"]
        + f.get("explosive", 0) * FACTORY_SELL_PRICES["explosive"]
        + f.get("counterfeit", 0) * FACTORY_SELL_PRICES["counterfeit"]
        + f.get("gym", 0) * FACTORY_SELL_PRICES["gym"]
        + f.get("warehouse", 0) * FACTORY_SELL_PRICES["warehouse"]
    )


# Warehouses don't produce anything - they're storage for produce (drugs,
# cars, guns) that would otherwise sit out in the open. Without any, everyone
# still gets a small base allowance; each warehouse raises the ceiling on all
# three categories at once. Whatever sits above the current cap is
# "unprotected" - it isn't lost on its own, but a successful bombing run on
# the matching production factory (drug/gun/car) takes it out along with the
# factories. Produce that's within capacity is safe permanently - bombing the
# warehouses themselves only removes future capacity, never touches stash
# that's already protected. See bomb_bot/bomb_human.
WAREHOUSE_BASE_CAPACITY = 5000
WAREHOUSE_CAPACITY_PER_UNIT = 20000


def warehouse_capacity(entity):
    return WAREHOUSE_BASE_CAPACITY + entity.get("factories", {}).get("warehouse", 0) * WAREHOUSE_CAPACITY_PER_UNIT


def _total_drugs(entity):
    return sum(entity.get("drugs", {}).values())


def _total_guns(entity):
    return sum(entity.get("guns", {}).values())


def _total_cars(entity):
    return entity.get("cadillacs", 0) + entity.get("armoredTrucks", 0)


def _reduce_drugs_by(entity, amount):
    remaining = amount
    for k in list(entity.get("drugs", {}).keys()):
        if remaining <= 0:
            break
        cut = min(entity["drugs"][k], remaining)
        entity["drugs"][k] -= cut
        remaining -= cut


def _reduce_guns_by(entity, amount):
    remaining = amount
    for k in list(entity.get("guns", {}).keys()):
        if remaining <= 0:
            break
        cut = min(entity["guns"][k], remaining)
        entity["guns"][k] -= cut
        remaining -= cut


def _reduce_cars_by(entity, amount):
    remaining = amount
    cut = min(entity.get("armoredTrucks", 0), remaining)
    entity["armoredTrucks"] = entity.get("armoredTrucks", 0) - cut
    remaining -= cut
    if remaining > 0:
        cut2 = min(entity.get("cadillacs", 0), remaining)
        entity["cadillacs"] = entity.get("cadillacs", 0) - cut2


def exposed_cars_of_type(entity, car_type):
    """How many of this specific car type currently sit outside warehouse
    protection and are actually stealable/bombable. Warehouse capacity is
    one shared cap across cadillacs+armoredTrucks combined (see
    warehouse_capacity/_total_cars), so if the combined total is within
    capacity, NOTHING of either type is exposed - matches the removal
    order _reduce_cars_by already uses (armored trucks counted as exposed
    before cadillacs)."""
    cap = warehouse_capacity(entity)
    exposed_total = max(0, _total_cars(entity) - cap)
    trucks = entity.get("armoredTrucks", 0)
    if car_type == "armoredTruck":
        return min(trucks, exposed_total)
    return max(0, exposed_total - trucks)


def expose_unprotected_produce(entity, factory_type):
    """Called after a successful bombing hit on drug/gun/car factories -
    whatever stash of that produce sits above current warehouse capacity
    was sitting out unprotected right next to the factories and goes with
    them. Anything within capacity (i.e. actually in a warehouse) is safe."""
    cap = warehouse_capacity(entity)
    if factory_type == "drug":
        over = _total_drugs(entity) - cap
        if over > 0:
            _reduce_drugs_by(entity, over)
    elif factory_type == "gun":
        over = _total_guns(entity) - cap
        if over > 0:
            _reduce_guns_by(entity, over)
    elif factory_type == "car":
        over = _total_cars(entity) - cap
        if over > 0:
            _reduce_cars_by(entity, over)


THUG_NET_WORTH_VALUE = 500


def bot_net_worth(bot):
    """Net worth is what your factories would actually sell for right now,
    plus each thug's muscle value. Produce sitting in storage (guns,
    cars/trucks, meds, coke) doesn't count - it's inventory, not assets."""
    f = bot.get("factories", {})
    return (
        factory_sell_value(f)
        + bot.get("thugs", 0) * THUG_NET_WORTH_VALUE
    )


def gun_score(guns, thug_count):
    """Weighted firepower score: pistol=1, shotgun=2, AK=3, M249=4 point(s)
    each - but capped at one gun per thug, since a gun needs a body to carry
    it. The best weapons in the stash get handed out first (M249s, then AKs,
    then shotguns, then pistols); anything past `thug_count` just sits
    unused in storage and contributes nothing."""
    remaining = max(0, thug_count)
    score = 0
    for weight, count in (
        (4, guns.get("m249", 0)),
        (3, guns.get("ak47", 0)),
        (2, guns.get("shotgun12gauge", 0)),
        (1, guns.get("pistol9mm", 0)),
    ):
        used = min(remaining, count)
        score += used * weight
        remaining -= used
        if remaining <= 0:
            break
    return score


BOT_BASE_ATTACK_CHANCE = 0.08


def bot_attack_bot(attacker, defender, now):
    """One bot attacks another bot (never their own crew - that's filtered
    by the caller). Mirrors the player's fight_bot rules: an unarmed side
    auto-loses regardless of thug count, otherwise thugs+guns decide it. A
    win wipes the defender's thugs (partial hospital recovery) and skims
    their hoeCash; a loss costs the attacker some thugs."""
    attacker_gun_score = gun_score(attacker.get("guns", {}), attacker["thugs"])
    defender_gun_score = gun_score(defender.get("guns", {}), defender["thugs"])

    if defender_gun_score == 0 and attacker_gun_score > 0:
        won = True
        attacker_base_power = max(1, attacker["thugs"])
        defender_base_power = 0
    elif attacker_gun_score == 0 and defender_gun_score > 0:
        won = False
        attacker_base_power = 0
        defender_base_power = max(1, defender["thugs"])
    else:
        attacker_mult = 1 + attacker_gun_score / max(1, attacker["thugs"])
        defender_mult = 1 + defender_gun_score / max(1, defender["thugs"])
        attacker_base_power = attacker["thugs"] * attacker_mult
        defender_base_power = defender["thugs"] * defender_mult
        attacker_power = attacker_base_power * (0.85 + random.random() * 0.3)
        defender_power = defender_base_power * (0.85 + random.random() * 0.3)
        won = attacker_power >= defender_power

    power_ratio = defender_base_power / max(1, attacker_base_power)

    if won:
        cash_cut = 0.05 + random.random() * 0.10
        cash_won = jround(defender["hoeCash"] * cash_cut)
        defender["hoeCash"] = max(0, defender["hoeCash"] - cash_won)
        attacker["hoeCash"] += cash_won

        inv_ratio = attacker_base_power / max(1, defender_base_power)
        defender_loss_pct = 0.10 * min(2.5, inv_ratio)
        thugs_wiped = jround(defender["thugs"] * defender_loss_pct)
        
        hospital_pct = ATTACK_HOSPITAL_PCT_MIN + random.random() * (ATTACK_HOSPITAL_PCT_MAX - ATTACK_HOSPITAL_PCT_MIN)
        thugs_hospitalized = jround(thugs_wiped * hospital_pct)
        defender["thugs"] = max(0, defender["thugs"] - thugs_wiped)
        defender["thugsInHospital"] = defender.get("thugsInHospital", 0) + thugs_hospitalized
        defender["thugsHospitalReadyAt"] = now + ATTACK_HOSPITAL_RECOVERY_MS

        attacker_loss_pct = 0.05 * min(1.0, power_ratio)
        your_thugs_lost = jround(attacker["thugs"] * attacker_loss_pct)
        attacker["thugs"] = max(0, attacker["thugs"] - your_thugs_lost)
    else:
        cash_cut = 0.05 + random.random() * 0.10
        cash_lost_amt = jround(attacker["hoeCash"] * cash_cut)
        attacker["hoeCash"] = max(0, attacker["hoeCash"] - cash_lost_amt)
        defender["hoeCash"] += cash_lost_amt

        inv_ratio = defender_base_power / max(1, attacker_base_power)
        attacker_loss_pct = 0.10 * min(2.5, inv_ratio)
        thugs_lost = jround(attacker["thugs"] * attacker_loss_pct)
        attacker["thugs"] = max(0, attacker["thugs"] - thugs_lost)


def run_bot_factories(b, ticks):
    """Mirrors run_factories() for the player: factories a bot actually owns
    turn into real output each tick instead of just padding net worth as an
    inert purchase. Uses the same per-factory rate curves as the player's
    factories (gun_factory_output_rates/car_factory_output_rates) at their
    default ratios, since bots have no ratio slider to tune."""
    f = b.get("factories", {})
    if f.get("gun", 0) > 0:
        pistol_rate, shotgun_rate, ak_rate, m249_rate = gun_factory_output_rates(0.0)
        b["guns"]["pistol9mm"] = b["guns"].get("pistol9mm", 0) + jround(f["gun"] * pistol_rate * ticks)
        b["guns"]["shotgun12gauge"] = b["guns"].get("shotgun12gauge", 0) + jround(f["gun"] * shotgun_rate * ticks)
        b["guns"]["ak47"] = b["guns"].get("ak47", 0) + jround(f["gun"] * ak_rate * ticks)
        b["guns"]["m249"] = b["guns"].get("m249", 0) + jround(f["gun"] * m249_rate * ticks)
    if f.get("car", 0) > 0:
        cadillac_rate, armored_rate = car_factory_output_rates(1.0)
        b["cadillacs"] = b.get("cadillacs", 0) + jround(f["car"] * cadillac_rate * ticks)
        b["armoredTrucks"] = b.get("armoredTrucks", 0) + jround(f["car"] * armored_rate * ticks)
    if f.get("medical", 0) > 0:
        morale_gain = min(100 - b["hoeMorale"], f["medical"] * 2 * ticks)
        b["hoeMorale"] = min(100, b["hoeMorale"] + morale_gain)
    if f.get("counterfeit", 0) > 0:
        b["cash"] += f["counterfeit"] * COUNTERFEIT_CASH_RATE * ticks
    if f.get("gym", 0) > 0:
        b["thugs"] = b.get("thugs", 0) + jround(f["gym"] * GYM_THUG_RATE * ticks)
    if f.get("drug", 0) > 0:
        b["cash"] += f["drug"] * BOT_DRUG_CASH_RATE * ticks


# Bots keep this much cash on hand as walking-around money; the rest gets
# plowed into new factories every tick (see bot_reinvest_cash).
CASH_REINVEST_FLOOR = 20000

# Factories cost £940k-32M (FACTORY_COSTS) but a bot's "cash" pool only ever
# gets this slice of each tick's hoe earnings (the rest goes to hoeCash,
# their raidable spending money) - at the old 0.2 rate bots took most of a
# full day to afford their very first factory, leaving them looking totally
# stagnant next to human players who can rush factories in hours. 1.0 gets
# the first factory bought within 2-4 hours instead, without touching
# hoeCash or thug/hoe growth (those already track human pace reasonably).
BOT_CASH_EARN_RATE = 1.0


def bot_reinvest_cash(b, arch):
    """Net worth is purely factory-based now, so a bot that just stockpiles
    cash never climbs the leaderboard no matter how much it earns. Every
    tick, a slice of surplus cash (above CASH_REINVEST_FLOOR) gets moved out
    of spendable cash and into a running factorySavings pot instead of being
    spent immediately - moguls funnel in the biggest slice, sharks the
    smallest, same reinvestRate already used for hoeCash. Each bot is
    saving toward one randomly chosen factory type (nextFactoryTarget) at a
    time; once savings cover that type's cost, it buys it and rolls a new
    target. Saving up (rather than always grabbing whatever's cheapest
    affordable right now) is what actually lets bots end up owning the
    £10-32M factory types instead of only ever Medical at £940k."""
    surplus = b["cash"] - CASH_REINVEST_FLOOR
    if surplus > 0:
        deposit = jround(surplus * arch["reinvestRate"])
        b["cash"] -= deposit
        b["factorySavings"] = b.get("factorySavings", 0) + deposit

    if b.get("nextFactoryTarget") not in BOT_FACTORY_TYPES:
        b["nextFactoryTarget"] = random.choice(BOT_FACTORY_TYPES)

    cost = FACTORY_COSTS[b["nextFactoryTarget"]]
    while b.get("factorySavings", 0) >= cost:
        b["factorySavings"] -= cost
        b["factories"][b["nextFactoryTarget"]] = b["factories"].get(b["nextFactoryTarget"], 0) + 1
        b["nextFactoryTarget"] = random.choice(BOT_FACTORY_TYPES)
        cost = FACTORY_COSTS[b["nextFactoryTarget"]]


BOT_TRUCK_SELL_PRICE = 18000


def bot_sell_surplus_produce(b):
    """Bots sell off produce they don't need. Guns beyond one-per-thug are
    dead stock (gun_score caps combat power there anyway), so the excess -
    worst weapons first, keeping the best for actual combat - gets sold for
    cash; AK-47s are never sold off, so a bot's stockpile only ever grows.
    Cadillacs and armored trucks don't count toward net worth or combat at
    all any more, so most of the fleet gets liquidated every tick, but a
    BOT_CAR_KEEP_PCT slice stays on hand - otherwise stealing cars from a
    bot would always come up empty. Proceeds land in `cash` and get plowed
    into more factories next via bot_reinvest_cash."""
    guns = b.get("guns", {})
    surplus = sum(guns.values()) - b.get("thugs", 0)
    for gun_key in ("pistol9mm", "shotgun12gauge", "m249"):
        if surplus <= 0:
            break
        have = guns.get(gun_key, 0)
        sell_qty = min(have, surplus)
        if sell_qty <= 0:
            continue
        guns[gun_key] = have - sell_qty
        b["cash"] = b.get("cash", 0) + sell_qty * BOT_REINVEST_GUN_PRICES[gun_key]
        surplus -= sell_qty

    cadillacs = b.get("cadillacs", 0)
    sell_cadillacs = jround(cadillacs * (1 - BOT_CAR_KEEP_PCT))
    if sell_cadillacs > 0:
        b["cash"] = b.get("cash", 0) + sell_cadillacs * BOT_REINVEST_CAR_PRICE
        b["cadillacs"] = cadillacs - sell_cadillacs

    trucks = b.get("armoredTrucks", 0)
    sell_trucks = jround(trucks * (1 - BOT_CAR_KEEP_PCT))
    if sell_trucks > 0:
        b["cash"] = b.get("cash", 0) + sell_trucks * BOT_TRUCK_SELL_PRICE
        b["armoredTrucks"] = trucks - sell_trucks


def bot_reinvest_hoecash(b, arch):
    """Bots don't just let hoeCash pile up as an easy raid target - anything
    above BOT_HOECASH_REINVEST_FLOOR gets regularly converted into guns or
    cadillacs (real assets that count toward net worth and, for guns, actual
    combat strength) at the same rate the archetype already reinvests cash
    into factories."""
    excess = b["hoeCash"] - BOT_HOECASH_REINVEST_FLOOR
    if excess <= 0:
        return
    spend = jround(excess * arch["reinvestRate"])
    if spend < 500:
        return
    b["hoeCash"] -= spend
    if random.random() < 0.5:
        gun_key = random.choice(list(BOT_REINVEST_GUN_PRICES.keys()))
        price = BOT_REINVEST_GUN_PRICES[gun_key]
        qty = spend // price
        b["guns"][gun_key] = b["guns"].get(gun_key, 0) + qty
        leftover = spend - qty * price
    else:
        qty = spend // BOT_REINVEST_CAR_PRICE
        b["cadillacs"] = b.get("cadillacs", 0) + qty
        leftover = spend - qty * BOT_REINVEST_CAR_PRICE
    b["hoeCash"] += leftover  # can't buy a fractional unit, give the remainder back


def regen_bots(world, now):
    for b in world["bots"]:
        if "archetype" not in b:
            b["archetype"] = random.choice(list(BOT_ARCHETYPES.keys()))
        arch = BOT_ARCHETYPES[b["archetype"]]

        last = b.get("lastRegen", now)
        ticks = (now - last) // BOT_TICK_MS
        if ticks < 1:
            continue
        b["maxTurns"] = BOT_MAX_TURNS

        # Cap one catch-up burst at a few hours of simulated activity - same
        # idea as turns capping at maxTurns - and fast-forward the clock
        # past the rest rather than letting a backlog build up.
        ticks = min(int(ticks), BOT_MAX_TICKS_PER_CATCHUP)
        b["lastRegen"] = now

        # Earnings are based on the hoe count at the START of this burst,
        # not the live count. Otherwise hoes growing mid-burst feeds back
        # into that same burst's own earnings, turning what should be
        # linear growth over N ticks into quadratic - a bot away for a day
        # would otherwise come back with an absurd 8-figure bankroll.
        hoes_for_earnings = b["hoes"]

        for _ in range(ticks):
            b["turns"] = min(b["maxTurns"], b["turns"] + REGEN_AMOUNT)
            turns_to_spend = min(b["turns"], 60 + random.randint(0, 89))
            if turns_to_spend < 10:
                continue
            b["turns"] -= turns_to_spend

            hoe_earnings = hoes_for_earnings * HOE_NIGHTLY_CAP * (b["hoeMorale"] / 100) * (turns_to_spend / NIGHT_TURNS)
            b["hoeCash"] += jround(hoe_earnings * 1.5)
            b["cash"] += jround(hoe_earnings * BOT_CASH_EARN_RATE * arch["cashRate"])

            hoes_per_turn = ((HOE_RECRUIT_MIN + HOE_RECRUIT_MAX) / 2) / HOE_RECRUIT_TURN_BLOCK
            b["hoes"] += max(0, jround(hoes_per_turn * turns_to_spend * (1.0 + random.random() * 0.8) * arch["hoeGrowth"]))
            b["thugs"] = max(5, b["thugs"] + jround(THUG_RECRUIT_PER_TURN * turns_to_spend * (0.8 + random.random()) * arch["thugGrowth"]))
            b["thugMorale"] = clamp(b["thugMorale"] + (random.random() - 0.5) * 10, 0, 100)
            b["hoeMorale"] = clamp(b["hoeMorale"] + (random.random() - 0.5) * 8, 0, 100)

            # Factories a bot already owns actually produce now (guns/cars).
            run_bot_factories(b, 1)

            # Produce beyond what's needed for combat gets sold off, and the
            # resulting (plus existing) cash surplus gets plowed into more
            # factories every tick - net worth is purely factory-based now,
            # so a bot that just stockpiles cash or unused guns/cars never
            # climbs the leaderboard.
            bot_sell_surplus_produce(b)
            bot_reinvest_cash(b, arch)

            # Surplus hoeCash gets plowed into guns/cars instead of just
            # sitting there as an easy raid target.
            bot_reinvest_hoecash(b, arch)

            # Bots throw down on each other too, same rules as a player
            # attack (guns decide it, wins wipe thugs with hospital
            # recovery) - but never against their own crew, and never
            # against a human player (targets only ever come from
            # world["bots"], which holds no human accounts). Not restricted
            # to the same city: each of the 4 crews lives in one fixed
            # shared city (ensure_bot_crew_cities), so a same-city
            # requirement here would mean two different-gang bots could
            # never actually be in the same place at once - rival gang wars
            # instead of a literal turf requirement. Every archetype has a
            # baseline chance; sharks (and enforcers, a bit) run hotter.
            attack_chance = max(BOT_BASE_ATTACK_CHANCE, arch["raidChance"])
            if random.random() < attack_chance:
                targets = [ob for ob in world["bots"] if ob["id"] != b["id"] and ob["gang"] != b["gang"]]
                if targets:
                    defender = random.choice(targets)
                    bot_attack_bot(b, defender, now)
                    log_attack(
                        world,
                        b["boss"], b.get("gang", ""), world.get("botCrewEmblems", {}).get(b.get("gang", ""), ""),
                        defender["boss"], defender.get("gang", ""), world.get("botCrewEmblems", {}).get(defender.get("gang", ""), ""),
                    )

            if random.random() < 0.12:
                loss_pct = 0.1 + random.random() * 0.2
                b["hoeCash"] = max(0, jround(b["hoeCash"] * (1 - loss_pct)))


def thug_morale_mult(state):
    return 0.5 + state["thugMorale"] / 100


ATTACK_HOSPITAL_RECOVERY_MS = 2 * 60 * 1000  # 2 minutes
ATTACK_HOSPITAL_PCT_MIN = 0.4
ATTACK_HOSPITAL_PCT_MAX = 0.6


def process_bot_hospitals(world, now):
    """Thugs wiped out in a lost attack come back out of hospital after
    ATTACK_HOSPITAL_RECOVERY_MS."""
    for b in world["bots"]:
        ready_at = b.get("thugsHospitalReadyAt", 0)
        if ready_at and now >= ready_at:
            b["thugs"] += b.get("thugsInHospital", 0)
            b["thugsInHospital"] = 0
            b["thugsHospitalReadyAt"] = 0


def process_human_hospital(state, now):
    """Same recovery mechanic as process_bot_hospitals, but for a real
    player's own state - called every time that player's state is loaded."""
    ready_at = state.get("thugsHospitalReadyAt", 0)
    if ready_at and now >= ready_at:
        state["thugs"] += state.get("thugsInHospital", 0)
        state["thugsInHospital"] = 0
        state["thugsHospitalReadyAt"] = 0


GLOBAL_ATTACK_LOG_MAX = 150  # bot-vs-bot wars fire often enough now to churn a smaller cap within hours


def log_attack(world, attacker_name, attacker_gang, attacker_emblem, defender_name, defender_gang, defender_emblem):
    """Global, world-shared feed of every attack - a player hitting any bot
    or player, or a bot hitting a rival bot - visible to everyone, unlike
    the private per-player log."""
    log = world.setdefault("globalAttackLog", [])
    log.append({
        "t": now_ms(),
        "attacker": attacker_name, "attackerGang": attacker_gang or "", "attackerEmblem": attacker_emblem or "",
        "defender": defender_name, "defenderGang": defender_gang or "", "defenderEmblem": defender_emblem or "",
    })
    if len(log) > GLOBAL_ATTACK_LOG_MAX:
        world["globalAttackLog"] = log[-GLOBAL_ATTACK_LOG_MAX:]


GLOBAL_CHAT_MAX_LENGTH = 300
GLOBAL_CHAT_HISTORY_CAP = 150


def send_global_chat_message(world, sender_user_id, sender_name, text):
    """Every real player shares this one feed, world-shared same as
    globalAttackLog - unlike crew chat there's no leader indirection, it
    lives directly on the world state everyone already reads from."""
    text = (text or "").strip()
    if not text:
        raise GameError("Message can't be empty")
    if len(text) > GLOBAL_CHAT_MAX_LENGTH:
        raise GameError(f"Message can't be more than {GLOBAL_CHAT_MAX_LENGTH} characters")
    chat = world.setdefault("globalChat", [])
    chat.append({
        "userId": sender_user_id,
        "name": sender_name,
        "text": text,
        "timestamp": now_ms(),
    })
    if len(chat) > GLOBAL_CHAT_HISTORY_CAP:
        world["globalChat"] = chat[-GLOBAL_CHAT_HISTORY_CAP:]
    return {"sent": True}


# Caps repeat hits on the same target so one player can't farm another
# (or an alt) over and over in a short window. Keyed per-attacker-per-target
# inside the attacker's own state, so it never affects anyone else's ability
# to attack that same target.
ATTACK_RATE_LIMIT_COUNT = 10
ATTACK_RATE_LIMIT_WINDOW_MS = 15 * 60 * 1000

# Short spam-click guard: your first hit on a target is instant, but every
# hit after that on the SAME target needs this long to have passed since
# your last hit on them specifically. Doesn't touch attacking anyone else
# in between.
ATTACK_REPEAT_COOLDOWN_MS = 7 * 1000


def check_attack_rate_limit(state, target_id, target_name=None):
    now = now_ms()
    history = state.setdefault("attackHistory", {})
    key = str(target_id)
    recent = [t for t in history.get(key, []) if now - t < ATTACK_RATE_LIMIT_WINDOW_MS]
    who = target_name or "this target"
    if recent and now - recent[-1] < ATTACK_REPEAT_COOLDOWN_MS:
        wait_sec = math.ceil((ATTACK_REPEAT_COOLDOWN_MS - (now - recent[-1])) / 1000)
        raise GameError(f"Hold up — you can hit {who} again in {wait_sec}s")
    if len(recent) >= ATTACK_RATE_LIMIT_COUNT:
        wait_min = math.ceil((ATTACK_RATE_LIMIT_WINDOW_MS - (now - min(recent))) / 60000)
        raise GameError(f"You've hit {who} too many times recently — try again in {wait_min} min")
    recent.append(now)
    history[key] = recent


def fight_bot(state, bot_id, world):
    if state["turns"] < 30:
        raise GameError("Not enough turns (need 30)")
    bot = next((b for b in world["bots"] if b["id"] == bot_id and b["city"] == state["location"]), None)
    if not bot:
        raise GameError("Target not found in this city")

    ban_until = state.get("crewAttackBans", {}).get(str(bot["id"]), 0)
    now = now_ms()
    if now < ban_until:
        mins_left = math.ceil((ban_until - now) / 60000)
        raise GameError(f"You can't attack {bot['boss']} for another {mins_left} min (you just dropped them from your crew)")

    check_attack_rate_limit(state, bot["id"], bot["boss"])

    state["turns"] -= 30
    log_attack(
        world,
        state["name"], state.get("gang", ""), state.get("crewEmblem", ""),
        bot["boss"], bot.get("gang", ""), world.get("botCrewEmblems", {}).get(bot.get("gang", ""), ""),
    )

    your_gun_score = gun_score(state.get("guns", {}), state["thugs"])
    their_gun_score = gun_score(bot.get("guns", {}), bot["thugs"])

    if their_gun_score == 0 and your_gun_score > 0:
        won = True
        your_base_power = max(1, state["thugs"])
        their_base_power = 0
    elif your_gun_score == 0 and their_gun_score > 0:
        won = False
        your_base_power = 0
        their_base_power = max(1, bot["thugs"])
    else:
        your_gun_mult = 1 + your_gun_score / max(1, state["thugs"])
        their_gun_mult = 1 + their_gun_score / max(1, bot["thugs"])
        your_base_power = state["thugs"] * your_gun_mult * thug_morale_mult(state)
        their_base_power = bot["thugs"] * their_gun_mult
        your_power = your_base_power * (0.85 + random.random() * 0.3)
        their_power = their_base_power * (0.85 + random.random() * 0.3)
        won = your_power >= their_power

    power_ratio = their_base_power / max(1, your_base_power)

    if won:
        cash_cut = 0.05 + random.random() * 0.10
        cash_won = jround(bot["hoeCash"] * cash_cut)
        bot["hoeCash"] = max(0, bot["hoeCash"] - cash_won)
        state["cash"] += cash_won
        state["lifetimeEarnings"] = state.get("lifetimeEarnings", 0) + cash_won

        inv_ratio = your_base_power / max(1, their_base_power)
        defender_loss_pct = 0.10 * min(2.5, inv_ratio)
        thugs_wiped = jround(bot["thugs"] * defender_loss_pct)
        
        hospital_pct = ATTACK_HOSPITAL_PCT_MIN + random.random() * (ATTACK_HOSPITAL_PCT_MAX - ATTACK_HOSPITAL_PCT_MIN)
        thugs_hospitalized = jround(thugs_wiped * hospital_pct)
        bot["thugs"] = max(0, bot["thugs"] - thugs_wiped)
        bot["thugsInHospital"] = bot.get("thugsInHospital", 0) + thugs_hospitalized
        bot["thugsHospitalReadyAt"] = now + ATTACK_HOSPITAL_RECOVERY_MS

        attacker_loss_pct = 0.05 * min(1.0, power_ratio)
        your_thugs_lost = jround(state["thugs"] * attacker_loss_pct)
        state["thugs"] = max(0, state["thugs"] - your_thugs_lost)
        
        state["statsThugsKilled"] = state.get("statsThugsKilled", 0) + thugs_wiped
        state["statsMoneyStolen"] = state.get("statsMoneyStolen", 0) + cash_won

        add_log(state, f"You hit {bot['boss']} of \"{bot['gang']}\" for £{cash_won} and wiped out {thugs_wiped} thugs ({thugs_hospitalized} hospitalized, the rest gone for good). Their crew fired back before going down, killing {your_thugs_lost} of your thugs.", "good")
        recalc_morale(state)
        add_xp(state, 30 * XP_PER_TURN_SPENT + ATTACK_XP_LOSS + ATTACK_XP_WIN_BONUS)
        award_achievement(state, "first_blood")
        return {"won": True, "cashWon": cash_won, "thugsWiped": thugs_wiped, "thugsHospitalized": thugs_hospitalized, "yourThugsLost": your_thugs_lost, "boss": bot["boss"], "gang": bot["gang"]}
    else:
        cash_cut = 0.05 + random.random() * 0.10
        cash_lost_amt = jround(state["cash"] * cash_cut)
        state["cash"] = max(0, state["cash"] - cash_lost_amt)
        
        inv_ratio = their_base_power / max(1, your_base_power)
        attacker_loss_pct = 0.10 * min(2.5, inv_ratio)
        thugs_lost = jround(state["thugs"] * attacker_loss_pct)
        state["thugs"] = max(0, state["thugs"] - thugs_lost)
        
        add_log(state, f"Attacked by {bot['boss']} of \"{bot['gang']}\" — they took £{cash_lost_amt} and {thugs_lost} thugs.", "bad")
        recalc_morale(state)
        add_xp(state, 30 * XP_PER_TURN_SPENT + ATTACK_XP_LOSS)
        return {"won": False, "cashLost": cash_lost_amt, "thugsLost": thugs_lost, "boss": bot["boss"], "gang": bot["gang"]}


# Bomb costs scale perfectly linearly with the factory's cash cost.
# 1 bomb = $10,000 of damage. This means an Explosive factory (65 bombs/tick)
# takes 115 ticks to destroy $75,000,000 of enemy net worth, perfectly matching
# the cash ROI of the rest of the factory economy.
BOMB_COST_BY_FACTORY = {"medical": 50, "gym": 200, "warehouse": 500, "gun": 1000, "car": 2500, "drug": 5000, "explosive": 7500, "counterfeit": 10000}
BOMB_TURN_COST = 20

# Stealing cars needs bodies on the ground to drive them out, not bombs -
# every car you want to take costs this many of your own thugs' worth of
# "capacity" (not consumed, just required), same blind-by-holdings shape as
# bombing: pick a car type without knowing how many the target actually
# owns, and sending your thugs in always costs turns even if they own none.
STEAL_CARS_THUGS_PER_CAR = 4
STEAL_CARS_TURN_COST = 20
STEAL_CARS_XP = 30
CAR_TYPE_FIELD = {"cadillac": "cadillacs", "armoredTruck": "armoredTrucks"}
CAR_TYPE_LABELS = {"cadillac": "Cadillac", "armoredTruck": "Armored Truck"}


def bomb_bot(state, bot_id, factory_type, world, qty=None):
    """Blind by holdings, not by type: you pick which kind of factory to
    hit (medical/gun/car/etc) without ever being shown how many of anything
    they actually own. By default you throw your whole bomb stockpile at
    it - that buys you as many kills of that factory type as it can
    afford, capped at however many they actually own. Pass `qty` to cap
    how many you're willing to spend bombs on instead of going all-in -
    still capped by what you can afford and what they actually own.
    Doesn't need to be enough to wipe them out entirely; any bomb is
    better than none. Sending your thugs in always costs turns, whether
    or not the target actually has any of that factory type - otherwise
    there'd be no reason to ever pay an Informer first."""
    if factory_type not in BOMB_COST_BY_FACTORY:
        raise GameError("Invalid factory type")
    bot = next((b for b in world["bots"] if b["id"] == bot_id), None)
    if not bot:
        raise GameError("Target not found")
    if bot["thugs"] > 0:
        raise GameError("Target still has thugs guarding it")
    per_unit = BOMB_COST_BY_FACTORY[factory_type]
    if state["bombs"] < per_unit:
        raise GameError(f"Need at least {per_unit} bombs to hit their {factory_type} factories")
    if state["turns"] < BOMB_TURN_COST:
        raise GameError(f"Not enough turns (need {BOMB_TURN_COST})")
    if qty is not None and qty <= 0:
        raise GameError("Enter how many factories to hit")

    owned = bot["factories"].get(factory_type, 0)
    destroyed = min(owned, state["bombs"] // per_unit)
    if qty is not None:
        destroyed = min(destroyed, qty)

    state["turns"] -= BOMB_TURN_COST
    cost = destroyed * per_unit
    state["bombs"] -= cost
    add_xp(state, BOMB_XP)

    if destroyed <= 0:
        add_log(state, f"Your thugs went in and hit 0 of {bot['boss']}'s {factory_type} factories — they don't have any.", "bad")
        return {"boss": bot["boss"], "target": factory_type, "bombsSpent": 0, "destroyed": 0, "wipedOut": False, "networthDestroyed": 0}

    bot["factories"][factory_type] -= destroyed
    wiped_out = bot["factories"][factory_type] <= 0
    state["statsFactoriesDestroyed"] = state.get("statsFactoriesDestroyed", 0) + destroyed
    if factory_type in ("drug", "gun", "car"):
        expose_unprotected_produce(bot, factory_type)
    # Never reveal how many the target has left after a partial hit - that's
    # exactly what the Informer exists to sell. "Wiped out" is fine to show
    # since a follow-up bomb run on an empty target would say so anyway.
    add_log(state, f"You spent {cost} bombs destroying {destroyed} of {bot['boss']}'s {factory_type} factories"
                   + (" (all of them)" if wiped_out else "") + ".", "good")
    award_achievement(state, "demolition_man")
    networth_destroyed = destroyed * FACTORY_SELL_PRICES[factory_type]
    return {"boss": bot["boss"], "target": factory_type, "bombsSpent": cost, "destroyed": destroyed, "wipedOut": wiped_out, "networthDestroyed": networth_destroyed}


# ---------------------------------------------------------------------------
# Human vs human (real players sharing the same world can attack each other,
# same rules as attacking a bot)
# ---------------------------------------------------------------------------

HUMAN_ID_OFFSET = 1_000_000


def human_as_bot(user_id, pimp_name, s):
    """Shapes a real player's state into the same dict shape the client
    already renders for bots, so every bot-oriented UI (Attacks page, city
    listings, Leaderboard) works for real player targets with no changes.
    Field mapping mirrors a bot's cash/hoeCash split: a bot's `hoeCash` is
    its unprotected, raidable pot and `cash` is what funds factories - a
    human has no protected pot at all anymore (the Bank was removed, so
    every raid targets their entire cash), hence `cash` is fixed at 0 here.

    City is blanked out entirely while laying low (see lay_low) - other
    players still see this human on the leaderboard with their real net
    worth, they just can't tell which city to travel to in order to find
    them. The real fight_human location check still uses the player's
    actual s['location'], so a lucky coincidental encounter can still
    result in a fight - laying low hides you from being tracked down, it
    doesn't make you unattackable."""
    return {
        "id": HUMAN_ID_OFFSET + user_id,
        "isHuman": True,
        "userId": user_id,
        "boss": pimp_name,
        "gang": s.get("gang") or "",
        "archetype": "human",
        "city": "" if is_laying_low(s) else s.get("location", "London"),
        "thugs": s.get("thugs", 0),
        "thugNames": [],
        "hoes": s.get("hoes", 0),
        "hoeNames": [],
        "cash": 0,
        "hoeCash": s.get("cash", 0),
        "thugMorale": s.get("thugMorale", 50),
        "hoeMorale": s.get("hoeMorale", 50),
        "guns": s.get("guns", {}),
        "cadillacs": s.get("cadillacs", 0),
        "armoredTrucks": s.get("armoredTrucks", 0),
        "factories": s.get("factories", {}),
        "rankLevel": rank_info(s.get("xp", 0))["level"],
        "thugsInHospital": s.get("thugsInHospital", 0),
        "thugsHospitalReadyAt": s.get("thugsHospitalReadyAt", 0),
        "statsThugsKilled": s.get("statsThugsKilled", 0),
        "statsFactoriesDestroyed": s.get("statsFactoriesDestroyed", 0),
        "statsMoneyStolen": s.get("statsMoneyStolen", 0),
        "statsCarsStolen": s.get("statsCarsStolen", 0),
        "statsJobsSucceeded": s.get("statsJobsSucceeded", 0),
        "statsTurnsWorked": s.get("statsTurnsWorked", 0),
        "lifetimeEarnings": s.get("lifetimeEarnings", 0),
    }


def fight_human(state, defender, world, defender_target_id=None):
    """Attack another real player. Raids the defender's `cash` directly -
    there's no protected pot for a human at all (no Bank), so this always
    raids their entire liquid cash, unlike a bot where `hoeCash` is raided
    but `cash` stays untouched."""
    if state["turns"] < 30:
        raise GameError("Not enough turns (need 30)")
    if defender["location"] != state["location"]:
        raise GameError("Target not found in this city")

    if defender_target_id is not None:
        check_attack_rate_limit(state, defender_target_id, defender["name"])

    now = now_ms()
    state["turns"] -= 30
    log_attack(
        world,
        state["name"], state.get("gang", ""), state.get("crewEmblem", ""),
        defender["name"], defender.get("gang", ""), defender.get("crewEmblem", ""),
    )
    your_gun_score = gun_score(state.get("guns", {}), state["thugs"])
    their_gun_score = gun_score(defender.get("guns", {}), defender["thugs"])

    if their_gun_score == 0 and your_gun_score > 0:
        won = True
    elif your_gun_score == 0 and their_gun_score > 0:
        won = False
    else:
        your_gun_mult = 1 + your_gun_score / max(1, state["thugs"])
        their_gun_mult = 1 + their_gun_score / max(1, defender["thugs"])
        your_power = state["thugs"] * your_gun_mult * thug_morale_mult(state) * (0.85 + random.random() * 0.3)
        their_power = defender["thugs"] * their_gun_mult * (0.85 + random.random() * 0.3)
        won = your_power >= their_power

    defender["lastAttackedBy"] = {"name": state["name"], "t": now, "won": won}

    if won:
        cash_cut = 0.2 + random.random() * 0.25
        cash_won = jround(defender["cash"] * cash_cut)
        defender["cash"] = max(0, defender["cash"] - cash_won)
        state["cash"] += cash_won
        state["lifetimeEarnings"] = state.get("lifetimeEarnings", 0) + cash_won

        thugs_wiped = defender["thugs"]
        hospital_pct = ATTACK_HOSPITAL_PCT_MIN + random.random() * (ATTACK_HOSPITAL_PCT_MAX - ATTACK_HOSPITAL_PCT_MIN)
        thugs_hospitalized = jround(thugs_wiped * hospital_pct)
        defender["thugs"] = 0
        defender["thugsInHospital"] = defender.get("thugsInHospital", 0) + thugs_hospitalized
        defender["thugsHospitalReadyAt"] = now + ATTACK_HOSPITAL_RECOVERY_MS

        your_thugs_lost_pct = 0.85 + random.random() * 0.08
        your_thugs_lost = min(state["thugs"], jround(thugs_wiped * your_thugs_lost_pct))
        state["thugs"] = max(0, state["thugs"] - your_thugs_lost)
        state["statsThugsKilled"] = state.get("statsThugsKilled", 0) + thugs_wiped
        state["statsMoneyStolen"] = state.get("statsMoneyStolen", 0) + cash_won

        # Home invasion record - biggest single hit ever landed on a real
        # player's crew, tracked world-wide so it survives whoever holds it.
        records = world.setdefault("records", {})
        best = records.get("biggestHomeInvasion")
        if not best or thugs_wiped > best.get("thugsKilled", 0):
            records["biggestHomeInvasion"] = {
                "attacker": state["name"], "defender": defender["name"],
                "thugsKilled": thugs_wiped, "cashWon": cash_won, "t": now,
            }

        add_log(state, f"You hit {defender['name']} for £{cash_won} and wiped out {thugs_wiped} thugs ({thugs_hospitalized} hospitalized, the rest gone for good). They fired back before going down, killing {your_thugs_lost} of your thugs.", "good")
        add_log(defender, f"{state['name']} hit you for £{cash_won} and wiped out {thugs_wiped} of your thugs ({thugs_hospitalized} hospitalized).", "bad")
        recalc_morale(state)
        recalc_morale(defender)
        add_xp(state, 30 * XP_PER_TURN_SPENT + ATTACK_XP_LOSS + ATTACK_XP_WIN_BONUS)
        award_achievement(state, "first_blood")
        return {"won": True, "cashWon": cash_won, "thugsWiped": thugs_wiped, "thugsHospitalized": thugs_hospitalized, "yourThugsLost": your_thugs_lost, "boss": defender["name"], "gang": defender.get("gang", "")}
    else:
        thugs_lost_pct = 0.1 + random.random() * 0.15
        cash_lost_amt = jround(state["cash"] * (0.05 + random.random() * 0.1))
        thugs_lost = jround(state["thugs"] * thugs_lost_pct)
        state["thugs"] = max(0, state["thugs"] - thugs_lost)
        state["cash"] = max(0, state["cash"] - cash_lost_amt)
        add_log(state, f"Attacked {defender['name']} and lost — they took £{cash_lost_amt} and {thugs_lost} of your thugs.", "bad")
        add_log(defender, f"{state['name']} tried to hit you and failed.", "good")
        recalc_morale(state)
        add_xp(state, 30 * XP_PER_TURN_SPENT + ATTACK_XP_LOSS)
        return {"won": False, "cashLost": cash_lost_amt, "thugsLost": thugs_lost, "boss": defender["name"], "gang": defender.get("gang", "")}


def bomb_human(state, defender, factory_type, qty=None):
    """Same partial-strike logic as bomb_bot, for a real player: by default
    your bomb stockpile buys as many kills of that factory type as it can
    afford, capped at however many they actually own. Pass `qty` to cap
    how many you're willing to spend bombs on instead of going all-in.
    Sending your thugs in always costs turns, whether or not the target
    actually has any of that factory type."""
    if factory_type not in BOMB_COST_BY_FACTORY:
        raise GameError("Invalid factory type")
    if defender["thugs"] > 0:
        raise GameError("Target still has thugs guarding it")
    per_unit = BOMB_COST_BY_FACTORY[factory_type]
    if state["bombs"] < per_unit:
        raise GameError(f"Need at least {per_unit} bombs to hit their {factory_type} factories")
    if state["turns"] < BOMB_TURN_COST:
        raise GameError(f"Not enough turns (need {BOMB_TURN_COST})")
    if qty is not None and qty <= 0:
        raise GameError("Enter how many factories to hit")

    owned = defender["factories"].get(factory_type, 0)
    destroyed = min(owned, state["bombs"] // per_unit)
    if qty is not None:
        destroyed = min(destroyed, qty)

    state["turns"] -= BOMB_TURN_COST
    cost = destroyed * per_unit
    state["bombs"] -= cost
    add_xp(state, BOMB_XP)

    if destroyed <= 0:
        add_log(state, f"Your thugs went in and hit 0 of {defender['name']}'s {factory_type} factories — they don't have any.", "bad")
        return {"boss": defender["name"], "target": factory_type, "bombsSpent": 0, "destroyed": 0, "wipedOut": False, "bombsDestroyed": 0, "networthDestroyed": 0}

    defender["factories"][factory_type] -= destroyed
    wiped_out = defender["factories"][factory_type] <= 0
    state["statsFactoriesDestroyed"] = state.get("statsFactoriesDestroyed", 0) + destroyed
    if factory_type in ("drug", "gun", "car"):
        expose_unprotected_produce(defender, factory_type)

    # Blow up someone's explosive factories and a matching share of their
    # bomb stockpile goes with it - there's nowhere else those bombs were
    # being kept. Only lost if you actually wipe them all out.
    bombs_destroyed = 0
    if factory_type == "explosive" and wiped_out:
        bombs_destroyed = defender.get("bombs", 0)
        defender["bombs"] = 0

    # Never reveal how many the target has left after a partial hit to the
    # attacker - that's exactly what the Informer exists to sell. The
    # defender's own log below is unaffected, since it's their own factories.
    add_log(state, f"You spent {cost} bombs destroying {destroyed} of {defender['name']}'s {factory_type} factories"
                   + (" (all of them)" if wiped_out else "")
                   + (f", destroying their {bombs_destroyed} stockpiled bombs with it" if bombs_destroyed else "") + ".", "good")
    add_log(defender, f"{state['name']} destroyed {destroyed} of your {factory_type} factories with a bombing run"
                       + (" (wiped out entirely)" if wiped_out else f" ({defender['factories'][factory_type]} left standing)")
                       + (f", taking your {bombs_destroyed} stockpiled bombs with it" if bombs_destroyed else "") + ".", "bad")
    award_achievement(state, "demolition_man")
    networth_destroyed = destroyed * FACTORY_SELL_PRICES[factory_type]
    return {"boss": defender["name"], "target": factory_type, "bombsSpent": cost, "destroyed": destroyed, "wipedOut": wiped_out, "bombsDestroyed": bombs_destroyed, "networthDestroyed": networth_destroyed}


def steal_cars_from_bot(state, bot_id, car_type, world, qty=None):
    """Blind by holdings, not by type: pick Cadillac or Armored Truck
    without ever being shown how many the target actually owns. Stolen
    cars land straight in your own garage. Capped by both what they
    actually own and how many you can haul out - STEAL_CARS_THUGS_PER_CAR
    thugs per car, required but not spent, since it's muscle to drive them
    away, not a resource that gets consumed. Sending your thugs in always
    costs turns, whether or not the target has any of that car type."""
    if car_type not in CAR_TYPE_FIELD:
        raise GameError("Invalid car type")
    bot = next((b for b in world["bots"] if b["id"] == bot_id), None)
    if not bot:
        raise GameError("Target not found")
    if bot["thugs"] > 0:
        raise GameError("Target still has thugs guarding their garage")
    if state["turns"] < STEAL_CARS_TURN_COST:
        raise GameError(f"Not enough turns (need {STEAL_CARS_TURN_COST})")
    if state["thugs"] < STEAL_CARS_THUGS_PER_CAR:
        raise GameError(f"Need at least {STEAL_CARS_THUGS_PER_CAR} thugs to steal any cars")
    if qty is not None and qty <= 0:
        raise GameError("Enter how many cars to steal")

    field = CAR_TYPE_FIELD[car_type]
    label = CAR_TYPE_LABELS[car_type]
    owned = exposed_cars_of_type(bot, car_type)
    capacity = state["thugs"] // STEAL_CARS_THUGS_PER_CAR
    stolen = min(owned, capacity)
    if qty is not None:
        stolen = min(stolen, qty)

    state["turns"] -= STEAL_CARS_TURN_COST
    add_xp(state, STEAL_CARS_XP)

    if stolen <= 0:
        add_log(state, f"Your thugs raided {bot['boss']}'s garage but found 0 {label}s to take.", "bad")
        return {"boss": bot["boss"], "target": car_type, "stolen": 0, "wipedOut": False}

    bot[field] -= stolen
    state[field] = state.get(field, 0) + stolen
    state["statsCarsStolen"] = state.get("statsCarsStolen", 0) + stolen
    wiped_out = bot[field] <= 0
    add_log(state, f"Your thugs stole {stolen} {label}s from {bot['boss']}'s garage"
                   + (" (all of them)" if wiped_out else f" ({bot[field]} left)") + ".", "good")
    return {"boss": bot["boss"], "target": car_type, "stolen": stolen, "wipedOut": wiped_out}


def steal_cars_from_human(state, defender, car_type, qty=None):
    """Same partial-haul logic as steal_cars_from_bot, for a real player."""
    if car_type not in CAR_TYPE_FIELD:
        raise GameError("Invalid car type")
    if defender["thugs"] > 0:
        raise GameError("Target still has thugs guarding their garage")
    if state["turns"] < STEAL_CARS_TURN_COST:
        raise GameError(f"Not enough turns (need {STEAL_CARS_TURN_COST})")
    if state["thugs"] < STEAL_CARS_THUGS_PER_CAR:
        raise GameError(f"Need at least {STEAL_CARS_THUGS_PER_CAR} thugs to steal any cars")
    if qty is not None and qty <= 0:
        raise GameError("Enter how many cars to steal")

    field = CAR_TYPE_FIELD[car_type]
    label = CAR_TYPE_LABELS[car_type]
    owned = exposed_cars_of_type(defender, car_type)
    capacity = state["thugs"] // STEAL_CARS_THUGS_PER_CAR
    stolen = min(owned, capacity)
    if qty is not None:
        stolen = min(stolen, qty)

    state["turns"] -= STEAL_CARS_TURN_COST
    add_xp(state, STEAL_CARS_XP)

    if stolen <= 0:
        add_log(state, f"Your thugs raided {defender['name']}'s garage but found 0 {label}s to take.", "bad")
        return {"boss": defender["name"], "target": car_type, "stolen": 0, "wipedOut": False}

    defender[field] -= stolen
    state[field] = state.get(field, 0) + stolen
    state["statsCarsStolen"] = state.get("statsCarsStolen", 0) + stolen
    wiped_out = defender[field] <= 0
    add_log(state, f"Your thugs stole {stolen} {label}s from {defender['name']}'s garage"
                   + (" (all of them)" if wiped_out else f" ({defender[field]} left)") + ".", "good")
    add_log(defender, f"{state['name']} raided your garage and stole {stolen} of your {label}s"
                       + (" (all of them)" if wiped_out else f" ({defender[field]} left)") + ".", "bad")
    return {"boss": defender["name"], "target": car_type, "stolen": stolen, "wipedOut": wiped_out}


# ---------------------------------------------------------------------------
# Bounties (world-shared: any real player can put their own cash on
# someone's head - bot or human - and whoever is the first to wipe that
# target's thugs to zero collects the lot, stacked across every bounty
# posted on that same target)
# ---------------------------------------------------------------------------

BOUNTY_MIN_AMOUNT = 1


def place_bounty(state, world, target_id, target_name, amount, poster_id, poster_name):
    """Escrows `amount` out of the poster's own cash the moment it's
    posted - it's gone whether or not anyone ever claims it, same as a
    real bounty. Multiple bounties can stack on one target; whoever
    actually lands the kill collects every bounty on that head at once."""
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        raise GameError("Invalid target")
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise GameError("Invalid bounty amount")
    if amount < BOUNTY_MIN_AMOUNT:
        raise GameError(f"Bounty must be at least £{BOUNTY_MIN_AMOUNT}")
    if state["cash"] < amount:
        raise GameError("Not enough cash to post that bounty")
    if target_id == HUMAN_ID_OFFSET + poster_id:
        raise GameError("You can't put a bounty on your own head")

    state["cash"] -= amount
    bounties = world.setdefault("bounties", [])
    next_id = world.get("nextBountyId", 1)
    world["nextBountyId"] = next_id + 1
    bounty = {
        "id": next_id, "targetId": target_id, "targetName": target_name,
        "posterId": poster_id, "posterName": poster_name,
        "amount": amount, "postedAt": now_ms(),
    }
    bounties.append(bounty)
    add_log(state, f"Put a £{amount} bounty on {target_name}'s head.", "info")
    return bounty


def cancel_bounty(state, world, bounty_id, poster_id):
    """Refunds the poster in full. Only the original poster can pull it."""
    try:
        bounty_id = int(bounty_id)
    except (TypeError, ValueError):
        raise GameError("Invalid bounty")
    bounties = world.setdefault("bounties", [])
    bounty = next((b for b in bounties if b["id"] == bounty_id), None)
    if not bounty:
        raise GameError("Bounty not found (maybe it was already claimed)")
    if bounty["posterId"] != poster_id:
        raise GameError("That's not your bounty to cancel")
    bounties.remove(bounty)
    state["cash"] += bounty["amount"]
    add_log(state, f"Pulled your £{bounty['amount']} bounty on {bounty['targetName']} — refunded.", "info")
    return bounty


BOT_BOUNTY_INTERVAL_MS = 3 * 60 * 60 * 1000  # every 3 hours, a bot puts a bounty on a top player
BOT_BOUNTY_TOP_N = 5  # picked from the 5 wealthiest real players
BOT_BOUNTY_PCT = (0.005, 0.02)  # 0.5-2% of the target's net worth


def maybe_bot_places_bounty(world, humans):
    """Every few hours, a random bot puts a bounty on one of the wealthiest
    real players, funded out of that bot's own cash (same escrow rule as a
    player-placed bounty) - keeps the top of the leaderboard from feeling
    too safe. `humans` is a list of (user_id, pimp_name, state) tuples for
    every registered player - app.py owns the DB query, this owns the
    selection/mutation. Cheap on every other request: the interval check
    short-circuits before doing anything else.

    posterId is deliberately None, not the bot's own id - bot ids and real
    user ids share the same small integer space, so reusing a bot's raw id
    here could let a human whose userId happens to match cancel a bounty
    they never posted. None can never equal a real user's id, so
    cancel_bounty always correctly refuses to let anyone pull these."""
    now = now_ms()
    if now - world.get("lastBotBounty", 0) < BOT_BOUNTY_INTERVAL_MS:
        return None
    world["lastBotBounty"] = now

    ranked = sorted(
        ((uid, name, total_net_worth(s)) for uid, name, s in humans),
        key=lambda h: h[2], reverse=True,
    )
    ranked = [h for h in ranked if h[2] > 0][:BOT_BOUNTY_TOP_N]
    if not ranked:
        return None

    candidates = [b for b in world.get("bots", []) if b.get("cash", 0) >= BOUNTY_MIN_AMOUNT]
    if not candidates:
        return None
    bot = random.choice(candidates)
    target_id, target_name, target_nw = random.choice(ranked)

    lo, hi = BOT_BOUNTY_PCT
    amount = jround(target_nw * (lo + random.random() * (hi - lo)))
    amount = min(amount, bot["cash"])
    if amount < BOUNTY_MIN_AMOUNT:
        return None

    bot["cash"] -= amount
    bounties = world.setdefault("bounties", [])
    next_id = world.get("nextBountyId", 1)
    world["nextBountyId"] = next_id + 1
    bounty = {
        "id": next_id, "targetId": HUMAN_ID_OFFSET + target_id, "targetName": target_name,
        "posterId": None, "posterName": bot["boss"],
        "amount": amount, "postedAt": now,
    }
    bounties.append(bounty)

    chat = world.setdefault("globalChat", [])
    chat.append({
        "userId": None, "name": "📰 Street Word",
        "text": f"{bot['boss']} just slapped a £{amount} bounty on {target_name}'s head!",
        "timestamp": now,
    })
    if len(chat) > GLOBAL_CHAT_HISTORY_CAP:
        world["globalChat"] = chat[-GLOBAL_CHAT_HISTORY_CAP:]

    return bounty


def claim_bounties(world, target_id, blocked_poster_ids=None):
    """Called right after a successful attack wipes a target's thugs to
    zero. Every bounty posted on that target's head pays out at once to
    the winner - except any posted by one of the WINNER's own crew-mates,
    which would otherwise be a free way to pass cash to a teammate (post a
    bounty, have your crew-mate collect the kill). Those stay in the
    world's bounty list untouched, still collectable later by anyone who
    actually isn't in the poster's crew."""
    blocked_poster_ids = blocked_poster_ids or set()
    bounties = world.setdefault("bounties", [])
    matching = [b for b in bounties if b["targetId"] == target_id]
    if not matching:
        return []
    collectable = [b for b in matching if b["posterId"] not in blocked_poster_ids]
    blocked = [b for b in matching if b["posterId"] in blocked_poster_ids]
    world["bounties"] = [b for b in bounties if b["targetId"] != target_id] + blocked
    return collectable


# ---------------------------------------------------------------------------
# Informer (pay cash for a full stat readout on any bot or real player)
# ---------------------------------------------------------------------------

INFORMER_COST_PCT = 0.12


def informer_report_bot(state, bot_id, world):
    bot = next((b for b in world["bots"] if b["id"] == bot_id), None)
    if not bot:
        raise GameError("Target not found")
    nw = bot_net_worth(bot)
    cost = max(1, jround(nw * INFORMER_COST_PCT))
    if state["cash"] < cost:
        raise GameError(f"Need £{cost} to buy intel on them")
    state["cash"] -= cost
    add_log(state, f"Paid an informer £{cost} for the lowdown on {bot['boss']}.", "info")
    return {
        "boss": bot["boss"], "gang": bot.get("gang", ""), "city": bot.get("city", ""),
        "cost": cost, "netWorth": nw,
        "cash": bot["cash"], "hoeCash": bot["hoeCash"],
        "thugs": bot["thugs"], "hoes": bot["hoes"],
        "guns": dict(bot.get("guns", {})),
        "cadillacs": bot.get("cadillacs", 0), "armoredTrucks": bot.get("armoredTrucks", 0),
        "factories": dict(bot.get("factories", {})),
    }


def informer_report_human(state, defender):
    nw = total_net_worth(defender)
    cost = max(1, jround(nw * INFORMER_COST_PCT))
    if state["cash"] < cost:
        raise GameError(f"Need £{cost} to buy intel on them")
    state["cash"] -= cost
    add_log(state, f"Paid an informer £{cost} for the lowdown on {defender['name']}.", "info")
    return {
        "boss": defender["name"], "gang": defender.get("gang", ""),
        "city": "" if is_laying_low(defender) else defender.get("location", ""),
        "cost": cost, "netWorth": nw,
        "cash": defender["cash"],
        "thugs": defender["thugs"], "hoes": defender["hoes"],
        "guns": dict(defender.get("guns", {})),
        "cadillacs": defender.get("cadillacs", 0), "armoredTrucks": defender.get("armoredTrucks", 0),
        "factories": dict(defender.get("factories", {})),
        "bombs": defender.get("bombs", 0),
    }


# ---------------------------------------------------------------------------
# Net worth / rank
# ---------------------------------------------------------------------------

def calc_net_worth(state):
    """Net worth is what your factories would actually sell for right now,
    plus each thug's muscle value. Produce sitting in storage (guns, cars/
    trucks, meds, cocaine) doesn't count - it's inventory, not assets. Cash,
    hoes and bombs still don't count at all either."""
    f = state["factories"]
    return (
        factory_sell_value(f)
        + state.get("thugs", 0) * THUG_NET_WORTH_VALUE
    )


def total_net_worth(state):
    return calc_net_worth(state)


def leaderboard(state, world):
    player_nw = total_net_worth(state)
    rows = [{
        "id": "player",
        "name": state["name"],
        "city": state["location"],
        "hoes": state["hoes"],
        "thugs": state["thugs"],
        "cars": state["cadillacs"],
        "netWorth": player_nw,
        "isPlayer": True,
    }]
    for b in world["bots"]:
        rows.append({
            "id": b["id"],
            "name": b["boss"],
            "gang": b["gang"],
            "city": b["city"],
            "hoes": b["hoes"],
            "thugs": b["thugs"],
            "cars": 0,
            "netWorth": bot_net_worth(b),
            "isPlayer": False,
        })
    rows.sort(key=lambda r: r["netWorth"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Bribery
# ---------------------------------------------------------------------------

def is_bribed(state):
    return now_ms() < state["bribeActiveUntil"]


def bribe_cops(state):
    now = now_ms()
    if is_bribed(state):
        raise GameError("Already bribed")
    if now < state["bribeCooldownUntil"]:
        raise GameError("Bribe on cooldown")
    cost = jround(state["hoes"] * BRIBE_COST_PER_HOE)
    if state["cash"] < cost:
        raise GameError("Not enough cash")
    state["cash"] -= cost
    state["bribeActiveUntil"] = now + BRIBE_DURATION_MS
    state["bribeCooldownUntil"] = now + BRIBE_COOLDOWN_MS
    add_log(state, f"Paid £{cost} to keep the cops off your back for 5 minutes.", "good")
    return {"cost": cost}


def is_laying_low(state):
    return now_ms() < state.get("layLowUntil", 0)


def lay_low(state):
    """Goes off the radar for 15 minutes - other players still see you on
    the leaderboard (net worth intact), but your city shows blank and you
    never show as online, so nobody can tell where to find you to attack.
    Doesn't stop you doing anything yourself, including attacking - see
    human_as_bot for the hidden-city part and build_human_targets (app.py)
    for the hidden-online part. Priced as a % of your OWN net worth since
    it's a genuine end-game advantage, not a flat fee."""
    now = now_ms()
    if is_laying_low(state):
        raise GameError("Already lying low")
    if now < state.get("layLowCooldownUntil", 0):
        wait_min = math.ceil((state["layLowCooldownUntil"] - now) / 60000)
        raise GameError(f"Lay Low is on cooldown — try again in {wait_min} min")
    cost = max(1, jround(total_net_worth(state) * LAY_LOW_COST_PCT))
    if state["cash"] < cost:
        raise GameError(f"Need £{cost} to lay low")
    state["cash"] -= cost
    state["layLowUntil"] = now + LAY_LOW_DURATION_MS
    state["layLowCooldownUntil"] = now + LAY_LOW_COOLDOWN_MS
    add_log(state, f"Paid £{cost} to go off the radar for 15 minutes.", "good")
    return {"cost": cost}


# ---------------------------------------------------------------------------
# Work the block
# ---------------------------------------------------------------------------

def _work_loc_key(state):
    loc = state.get("workLocation")
    return loc if loc in WORK_LOCATION_BASE_EARN_PER_100_HOES_PER_10_TURNS else "redlight"


def hoe_earning_potential(state, turns):
    """Gross earnings (before the hoe wage cut) based on hoe count and
    *collective* hoeMorale, not each hoe's individual happiness."""
    loc_key = _work_loc_key(state)
    base_rate = WORK_LOCATION_BASE_EARN_PER_100_HOES_PER_10_TURNS[loc_key]
    happiness_frac = state["hoeMorale"] / 100
    gross = base_rate * (state["hoes"] / 100) * happiness_frac * (turns / 10)
    return gross * (1 + WORK_LOCATION_AREA_BONUS_PCT[loc_key])


def projected_yield(state, turns):
    loc_key = _work_loc_key(state)
    gross = hoe_earning_potential(state, turns)
    happiness_frac = state["hoeMorale"] / 100
    hoe_recruit_base = WORK_LOCATION_HOE_RECRUIT_BASE_PER_10_TURNS[loc_key]
    return {
        "cash": jround(gross * (1 - HOE_WAGE_PCT)),
        "hoeWage": jround(gross * HOE_WAGE_PCT),
        "hoes": jround(hoe_recruit_base * (turns / 10) * happiness_frac),
        "thugs": jround(turns),
    }


def work_block(state, requested_turns):
    turns = min(150, requested_turns, state["turns"])
    if turns < 1:
        raise GameError("Not enough turns")

    state["turns"] -= turns
    state["statsTurnsWorked"] = state.get("statsTurnsWorked", 0) + turns
    check_thug_attrition(state)
    hoes_lost = check_hoe_attrition(state)

    loc_key = _work_loc_key(state)
    loc = WORK_LOCATIONS[loc_key]

    variance = 0.8 + random.random() * 0.4
    gross = jround(hoe_earning_potential(state, turns) * variance)
    hoe_wage = jround(gross * HOE_WAGE_PCT)
    cash_gain = gross - hoe_wage  # hoe_wage is dead money - never credited anywhere

    happiness_frac = state["hoeMorale"] / 100
    hoe_recruit_base = WORK_LOCATION_HOE_RECRUIT_BASE_PER_10_TURNS[loc_key]
    hoes_gain = max(0, jround(hoe_recruit_base * (turns / 10) * happiness_frac))

    thugs_gain = max(0, jround(1 * turns * loc["thugRecruitMult"]))

    bust_chance = 0 if state["thugMorale"] >= 100 else 0.15 * loc["bustRisk"]
    busted = (not is_bribed(state)) and random.random() < bust_chance

    thugs_lost = 0
    cash_lost = 0
    if busted:
        cash_lost_pct = 0.25 + random.random() * 0.25
        cash_lost = jround(state["cash"] * cash_lost_pct)
        state["cash"] = max(0, state["cash"] - cash_lost)
        cash_gain = jround(cash_gain * 0.35)
        hoes_gain = jround(hoes_gain * 0.3)
        thugs_lost = jround(thugs_gain * 0.7)
        thugs_gain = jround(thugs_gain * 0.3)

    state["cash"] += cash_gain
    state["lifetimeEarnings"] = state.get("lifetimeEarnings", 0) + cash_gain
    add_hoes(state, hoes_gain)
    state["thugs"] += thugs_gain
    state["thugs"] = max(0, state["thugs"] - thugs_lost)

    if state["gunsStock"] > 0:
        state["gunsStock"] -= 1

    recalc_morale(state)
    add_xp(state, turns * XP_PER_TURN_SPENT)

    result = {
        "turnsSpent": turns,
        "cashGain": cash_gain,
        "hoeWage": hoe_wage,
        "hoesGain": hoes_gain,
        "thugsGain": thugs_gain,
        "busted": busted,
        "cashLost": cash_lost,
        "hoesLost": hoes_lost,
        "thugsLost": thugs_lost,
    }
    if busted:
        add_log(state, f"Raided! Lost £{cash_lost}.", "bad")
    else:
        add_log(state, f"Worked {turns} turns: +£{cash_gain} (paid hoes £{hoe_wage}), +{hoes_gain} hoes, +{thugs_gain} thugs.", "good")
    if hoes_lost:
        add_log(state, f"{hoes_lost} hoe{'s' if hoes_lost != 1 else ''} walked out on you - morale was too low.", "bad")
    return result


def set_work_location(state, loc):
    if loc not in WORK_LOCATIONS:
        raise GameError("Invalid location")
    state["workLocation"] = loc


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def buy_factory(state, ftype, qty=1):
    if ftype not in FACTORY_COSTS:
        raise GameError("Invalid factory type")
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise GameError("Invalid quantity")
    if qty < 1:
        raise GameError("Invalid quantity")
    required_rank = FACTORY_UNLOCK_RANK[ftype]
    current_rank = rank_info(state.get("xp", 0))["level"]
    if current_rank < required_rank:
        rank_name = RANKS[required_rank - 1][1]
        raise GameError(f"Unlocks at Rank {required_rank} ({rank_name}) - you're Rank {current_rank}")
    cost = FACTORY_COSTS[ftype] * qty
    if state["cash"] < cost:
        raise GameError("Not enough cash")
    state["cash"] -= cost
    state["factories"][ftype] += qty
    add_log(state, f"Bought {qty} new {ftype} factor{'y' if qty == 1 else 'ies'} for £{cost}.", "good")
    return {"type": ftype, "qty": qty, "cost": cost}


def sell_factory(state, ftype, qty=1):
    if ftype not in FACTORY_COSTS:
        raise GameError("Invalid factory type")
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise GameError("Invalid quantity")
    owned = state["factories"].get(ftype, 0)
    if qty < 1 or qty > owned:
        raise GameError(f"You only have {owned} {ftype} factories")
    payout = jround(FACTORY_SELL_PRICES[ftype] * qty)
    state["factories"][ftype] -= qty
    state["cash"] += payout
    add_log(state, f"Sold {qty} {ftype} factor{'y' if qty == 1 else 'ies'} for £{payout}.", "good")
    return {"type": ftype, "qty": qty, "payout": payout}


def set_car_factory_ratio(state, ratio_pct):
    try:
        ratio_pct = float(ratio_pct)
    except (TypeError, ValueError):
        raise GameError("Invalid ratio")
    if ratio_pct < 0 or ratio_pct > 100:
        raise GameError("Ratio must be between 0 and 100")
    state["carFactoryRatio"] = ratio_pct / 100.0
    add_log(state, "Adjusted car factory production mix.", "info")


def set_gun_factory_ratio(state, ratio_pct):
    try:
        ratio_pct = float(ratio_pct)
    except (TypeError, ValueError):
        raise GameError("Invalid ratio")
    if ratio_pct < 0 or ratio_pct > 100:
        raise GameError("Ratio must be between 0 and 100")
    state["gunFactoryRatio"] = ratio_pct / 100.0
    add_log(state, "Adjusted gun factory production mix.", "info")


def sell_all_cadillacs(state):
    qty = state.get("cadillacs", 0)
    if qty < 1:
        raise GameError("No cadillacs to sell")
    item = BLACKMARKET_BY_KEY["cars"]
    price = _market_current_price(state, item)
    payout = jround(qty * price)
    state["cadillacs"] = 0
    state["cash"] += payout
    add_log(state, f"Sold all {qty} cadillacs to the dealer for £{payout}.", "good")
    add_xp(state, payout * SELL_XP_PER_POUND)
    return {"qty": qty, "price": price, "payout": payout}


def sell_all_meds(state):
    qty = state.get("medsStock", 0)
    if qty < 1:
        raise GameError("No safety kits to sell")
    item = BLACKMARKET_BY_KEY["meds"]
    price = _market_current_price(state, item)
    payout = jround(qty * price)
    state["medsStock"] = 0
    state["cash"] += payout
    add_log(state, f"Sold all {qty} safety kits to the dealer for £{payout}.", "good")
    add_xp(state, payout * SELL_XP_PER_POUND)
    return {"qty": qty, "price": price, "payout": payout}


def sell_all_cocaine(state):
    """Sell the entire cocaine stash to the current city's dealer (safe, guaranteed)."""
    qty = state["drugs"].get("coke", 0)
    if qty < 1:
        raise GameError("No cocaine to sell")
    result = sell_drugs(state, "coke", qty)
    add_log(state, f"Sold all {qty} cocaine to the dealer for £{result['totalEarnings']}.", "good")
    return {"qty": qty, "price": result["price"], "payout": result["totalEarnings"]}


COCAINE_OVERSEAS_SUCCESS_CHANCE = 0.72  # 28% bust chance at customs
COCAINE_OVERSEAS_PREMIUM = 1.35

FAKE_MONEY_OVERSEAS_SUCCESS_CHANCE = 0.50  # 50% bust chance
FAKE_MONEY_OVERSEAS_PREMIUM = 1.9

def sell_cocaine_overseas(state):
    """High risk / high reward: ship the whole cocaine stash overseas. 72%
    chance of selling at dealer price + 35%; 28% chance customs catches the
    shipment and you lose everything for nothing."""
    qty = state["drugs"].get("coke", 0)
    if qty < 1:
        raise GameError("No cocaine to sell")
    city = state["location"]
    base_price = get_dealer_price(state, city, "coke", True)
    overseas_price = base_price * COCAINE_OVERSEAS_PREMIUM
    state["drugs"]["coke"] = 0

    if random.random() < COCAINE_OVERSEAS_SUCCESS_CHANCE:
        payout = jround(qty * overseas_price)
        state["cash"] += payout
        add_log(state, f"Shipped {qty} cocaine overseas and cleared customs clean! Made £{payout}.", "good")
        add_xp(state, payout * SELL_XP_PER_POUND)
        return {"success": True, "qty": qty, "price": jround(overseas_price), "payout": payout}
    else:
        add_log(state, f"Customs busted your overseas shipment of {qty} cocaine. Total loss — got nothing.", "bad")
        return {"success": False, "qty": qty, "payout": 0}


def wash_fake_money(state):
    qty = state.get("fakeMoney", 0)
    if qty < 1:
        raise GameError("No fake money to wash")
    
    payout = qty
    state["fakeMoney"] = 0
    state["cash"] += payout
    state["lifetimeEarnings"] = state.get("lifetimeEarnings", 0) + payout
    state["counterfeitEarnings"] = state.get("counterfeitEarnings", 0) + payout
    
    add_log(state, f"Washed £{qty} of fake money locally for a clean £{payout}.", "good")
    add_xp(state, payout * SELL_XP_PER_POUND)
    return {"success": True, "qty": qty, "payout": payout}


def wash_fake_money_overseas(state):
    qty = state.get("fakeMoney", 0)
    if qty < 1:
        raise GameError("No fake money to wash")
    
    state["fakeMoney"] = 0
    
    if random.random() < FAKE_MONEY_OVERSEAS_SUCCESS_CHANCE:
        payout = jround(qty * FAKE_MONEY_OVERSEAS_PREMIUM)
        state["cash"] += payout
        state["lifetimeEarnings"] = state.get("lifetimeEarnings", 0) + payout
        state["counterfeitEarnings"] = state.get("counterfeitEarnings", 0) + payout
        
        add_log(state, f"Laundered £{qty} of fake money through offshore accounts! Cleared £{payout}.", "good")
        add_xp(state, payout * SELL_XP_PER_POUND)
        return {"success": True, "qty": qty, "payout": payout}
    else:
        add_log(state, f"The FBI seized your offshore transfer of £{qty} in fake money. Total loss.", "bad")
        return {"success": False, "qty": qty, "payout": 0}


def sell_all_armored_trucks(state):
    qty = state.get("armoredTrucks", 0)
    if qty < 1:
        raise GameError("No armored trucks to sell")
    item = BLACKMARKET_BY_KEY["trucks"]
    price = _market_current_price(state, item)
    payout = jround(qty * price)
    state["armoredTrucks"] = 0
    state["cash"] += payout
    add_log(state, f"Sold all {qty} armored trucks to the dealer for £{payout}.", "good")
    add_xp(state, payout * SELL_XP_PER_POUND)
    return {"qty": qty, "price": price, "payout": payout}


GUN_TYPE_NAMES = {
    "pistol9mm": "9mm pistols",
    "shotgun12gauge": "shotguns",
    "ak47": "AK-47s",
    "m249": "M249s",
}


def sell_all_guns(state, gun_type):
    if gun_type not in GUN_TYPE_NAMES:
        raise GameError("Invalid gun type")
    qty = state["guns"].get(gun_type, 0)
    if qty < 1:
        raise GameError(f"No {GUN_TYPE_NAMES[gun_type]} to sell")
    item = BLACKMARKET_BY_KEY[gun_type]
    price = _market_current_price(state, item)
    payout = jround(qty * price)
    state["guns"][gun_type] = 0
    state["cash"] += payout
    add_log(state, f"Sold all {qty} {GUN_TYPE_NAMES[gun_type]} to the dealer for £{payout}.", "good")
    add_xp(state, payout * SELL_XP_PER_POUND)
    return {"qty": qty, "price": price, "payout": payout}


def run_factories(state, ticks):
    if ticks < 1:
        return
    f = state["factories"]
    any_factories = any(f.get(k, 0) > 0 for k in ("medical", "gun", "car", "drug", "explosive", "counterfeit", "gym"))
    if not any_factories:
        return

    kits = jround(f["medical"] * MEDICAL_KIT_RATE * ticks)
    pistol_rate, shotgun_rate, ak_rate, m249_rate = gun_factory_output_rates(state.get("gunFactoryRatio", 0.0))
    pistol_units = jround(f["gun"] * pistol_rate * ticks)
    shotgun_units = jround(f["gun"] * shotgun_rate * ticks)
    ak_units = jround(f["gun"] * ak_rate * ticks)
    m249_units = jround(f["gun"] * m249_rate * ticks)
    gun_units_total = pistol_units + shotgun_units + ak_units + m249_units
    cadillac_rate, armored_rate = car_factory_output_rates(state.get("carFactoryRatio", 1.0))
    cadillac_units = jround(f["car"] * cadillac_rate * ticks)
    armored_units = jround(f["car"] * armored_rate * ticks)
    coke = jround(f.get("drug", 0) * DRUG_FACTORY_RATE * ticks)
    bombs = jround(f["explosive"] * EXPLOSIVE_BOMB_RATE * ticks)
    counterfeit_cash = jround(f["counterfeit"] * COUNTERFEIT_CASH_RATE * ticks)
    gym_thugs = jround(f.get("gym", 0) * GYM_THUG_RATE * ticks)

    if kits > 0:
        state["medsStock"] += kits
    if gun_units_total > 0:
        state["guns"]["pistol9mm"] += pistol_units
        state["guns"]["shotgun12gauge"] += shotgun_units
        state["guns"]["ak47"] += ak_units
        state["guns"]["m249"] += m249_units
        state["gunsOwned"] += gun_units_total
        state["gunsStock"] = max(state["gunsStock"], 5)
    if cadillac_units > 0 or armored_units > 0:
        state["cadillacs"] += cadillac_units
        state["armoredTrucks"] += armored_units
    if coke > 0:
        state["drugs"]["coke"] = state["drugs"].get("coke", 0) + coke
    if bombs > 0:
        state["bombs"] += bombs
    if counterfeit_cash > 0:
        state["fakeMoney"] = state.get("fakeMoney", 0) + counterfeit_cash
    if gym_thugs > 0:
        state["thugs"] = state.get("thugs", 0) + gym_thugs


# ---------------------------------------------------------------------------
# Heists
# ---------------------------------------------------------------------------

def run_heist(state, job_id):
    job = HEIST_JOBS.get(job_id)
    if not job:
        raise GameError("Invalid heist")
    if state["thugs"] < job["minThugs"]:
        raise GameError(f"Need at least {job['minThugs']} thugs")
    if state["turns"] < job["turnCost"]:
        raise GameError("Not enough turns")
    now = now_ms()
    if now - state["lastJobHeist"] < HEIST_JOB_COOLDOWN_MS:
        wait_min = math.ceil((HEIST_JOB_COOLDOWN_MS - (now - state["lastJobHeist"])) / 60000)
        raise GameError(f"Pull a Job is on cooldown — try again in {wait_min} min")
    state["lastJobHeist"] = now

    state["turns"] -= job["turnCost"]
    won = random.random() < (job["successChance"] + (state["thugMorale"] / 100) * 0.08)

    if won:
        flat_cash = jround(job["minCash"] + random.random() * (job["maxCash"] - job["minCash"]))
        nw_lo, nw_hi = job["netWorthPct"]["min"], job["netWorthPct"]["max"]
        scaled_cash = jround(total_net_worth(state) * (nw_lo + random.random() * (nw_hi - nw_lo)))
        cash_won = max(flat_cash, scaled_cash)
        lo, hi = job["casualtyPct"]
        pct = lo + random.random() * (hi - lo)
        thugs_lost = max(0, jround(state["thugs"] * pct))
        state["cash"] += cash_won
        state["lifetimeEarnings"] = state.get("lifetimeEarnings", 0) + cash_won
        state["statsMoneyStolen"] = state.get("statsMoneyStolen", 0) + cash_won
        state["statsJobsSucceeded"] = state.get("statsJobsSucceeded", 0) + 1
        state["thugs"] = max(0, state["thugs"] - thugs_lost)
        add_log(state, f"{job_id.title()} heist scored £{cash_won}! Lost {thugs_lost} thugs.", "good")
        recalc_morale(state)
        add_xp(state, job["turnCost"] * XP_PER_TURN_SPENT + jround(cash_won * SELL_XP_PER_POUND))
        award_achievement(state, "pulled_a_job")
        return {"won": True, "cashWon": cash_won, "thugsLost": thugs_lost}
    else:
        lo, hi = job["failCasualtyPct"]
        pct = lo + random.random() * (hi - lo)
        thugs_lost = max(1, jround(state["thugs"] * pct))
        state["thugs"] = max(0, state["thugs"] - thugs_lost)
        add_log(state, f"{job_id.title()} heist failed! Lost {thugs_lost} thugs.", "bad")
        recalc_morale(state)
        add_xp(state, job["turnCost"] * XP_PER_TURN_SPENT)
        return {"won": False, "thugsLost": thugs_lost}


def run_casino_heist(state, world):
    crew_size = len(state["crewMembers"])
    if crew_size < 1:
        raise GameError("Need a crew to hit the casino")
    job = CASINO_JOB
    thugs_needed = crew_size * job["thugsPerMember"]
    turns_needed = crew_size * job["turnsPerMember"]
    if state["thugs"] < thugs_needed:
        raise GameError(f"Need at least {thugs_needed} thugs")
    if state["turns"] < turns_needed:
        raise GameError("Not enough turns")
    now = now_ms()
    if now - state["lastCasinoHeist"] < job["cooldownHours"] * 3600 * 1000:
        raise GameError("Casino heist on cooldown")

    state["turns"] -= turns_needed
    state["thugs"] -= thugs_needed
    state["lastCasinoHeist"] = now

    won = random.random() < (0.35 + (state["thugMorale"] / 100) * 0.10)

    if won:
        flat_cash = jround(job["minCash"] + random.random() * (job["maxCash"] - job["minCash"]))
        crew_bots = [next((b for b in world["bots"] if b["id"] == m["botId"]), None) for m in state["crewMembers"]]
        crew_net_worth = total_net_worth(state) + sum(bot_net_worth(b) for b in crew_bots if b)
        nw_lo, nw_hi = job["netWorthPct"]
        scaled_cash = jround(crew_net_worth * (nw_lo + random.random() * (nw_hi - nw_lo)))
        total_cash = max(flat_cash, scaled_cash)
        player_share = jround(total_cash * 0.60)
        crew_share_per_member = jround(total_cash * 0.40 / crew_size)
        state["cash"] += player_share
        state["lifetimeEarnings"] = state.get("lifetimeEarnings", 0) + player_share
        state["statsMoneyStolen"] = state.get("statsMoneyStolen", 0) + player_share
        state["statsJobsSucceeded"] = state.get("statsJobsSucceeded", 0) + 1
        lo, hi = job["casualtyPct"]
        pct = lo + random.random() * (hi - lo)
        thugs_lost = jround(thugs_needed * pct)
        state["thugs"] = max(0, state["thugs"] + thugs_needed - thugs_lost)
        for member in state["crewMembers"]:
            bot = next((b for b in world["bots"] if b["id"] == member["botId"]), None)
            if bot:
                bot["cash"] += crew_share_per_member
        add_log(state, f"Casino heist scored £{player_share} for you!", "good")
        recalc_morale(state)
        add_xp(state, turns_needed * XP_PER_TURN_SPENT + jround(player_share * SELL_XP_PER_POUND))
        award_achievement(state, "high_roller")
        return {"won": True, "playerShare": player_share, "thugsLost": thugs_lost}
    else:
        lo, hi = job["failCasualtyPct"]
        pct = lo + random.random() * (hi - lo)
        thugs_lost = max(crew_size, jround(thugs_needed * pct))
        state["thugs"] = max(0, state["thugs"] + thugs_needed - thugs_lost)
        add_log(state, "Casino heist failed badly.", "bad")
        recalc_morale(state)
        add_xp(state, turns_needed * XP_PER_TURN_SPENT)
        return {"won": False, "thugsLost": thugs_lost}



# ---------------------------------------------------------------------------
# Drugs
# ---------------------------------------------------------------------------

def get_dealer_price(state, city, drug_id, is_sell):
    key = f"{city}_{drug_id}"
    entry = state["dealerPrices"].get(key)
    if not entry:
        drug = DOPE_DEALER_BY_ID[drug_id]
        variance = 0.80 + random.random() * 0.4
        entry = {
            "buy": jround(drug["baseBuyPrice"] * variance),
            "sell": jround(drug["baseSellPrice"] * variance),
        }
        state["dealerPrices"][key] = entry
    return entry["sell"] if is_sell else entry["buy"]


def check_dealer_reset(state, now):
    if now - state["lastDealerPriceUpdate"] >= DEALER_RESET_MS:
        state["dealerPrices"] = {}
        state["dealerBoughtToday"] = {}
        state["lastDealerPriceUpdate"] = now


def buy_drugs(state, drug_id, qty):
    if drug_id not in DOPE_DEALER_BY_ID or qty < 1:
        raise GameError("Invalid purchase")
    city = state["location"]
    bought_key = f"{city}_{drug_id}_bought"
    already_bought = state["dealerBoughtToday"].get(bought_key, 0)
    if already_bought + qty > DEALER_DAILY_CAP:
        raise GameError("Dealer is out of stock for now")
    price = get_dealer_price(state, city, drug_id, False)
    total_cost = price * qty
    if state["cash"] < total_cost:
        raise GameError("Not enough cash")
    state["cash"] -= total_cost
    state["drugs"][drug_id] = state["drugs"].get(drug_id, 0) + qty
    state["dealerBoughtToday"][bought_key] = already_bought + qty
    # Keyed by drug only, not city - the stash itself isn't location-bound,
    # so a city-scoped key here would let you buy in one city and instantly
    # flip for guaranteed profit in another where the cooldown never fired.
    state["drugBoughtAt"][drug_id] = now_ms()
    state["drugsPaidPrice"][drug_id] = price
    return {"totalCost": total_cost, "price": price}


def sell_drugs(state, drug_id, qty):
    have = state["drugs"].get(drug_id, 0)
    if qty < 1 or qty > have:
        raise GameError("Not enough to sell")
    city = state["location"]
    bought_at = state["drugBoughtAt"].get(drug_id, 0)
    if bought_at > 0 and (now_ms() - bought_at) < DEALER_RESALE_COOLDOWN_MS:
        raise GameError("Prices haven't moved yet - wait a bit")
    price = get_dealer_price(state, city, drug_id, True)
    total_earnings = price * qty
    state["drugs"][drug_id] -= qty
    state["cash"] += total_earnings
    add_xp(state, total_earnings * SELL_XP_PER_POUND)
    return {"totalEarnings": total_earnings, "price": price}


# ---------------------------------------------------------------------------
# Black market
# ---------------------------------------------------------------------------

def _market_current_price(state, item):
    if item["key"] == "thugs":
        return 90
    mult = state["market"].get(item["key"], {"mult": 1.0})["mult"]
    # Capped below 1.0 (not at 1.0) so a buy-then-sell round trip on the same
    # item always nets a real cash loss, never a wash - otherwise, whenever
    # the market multiplier drifts above 1.0 (which happens often), buying
    # and immediately reselling costs nothing net while still paying out the
    # sell-side XP every time: free, unlimited XP/rank/Mob Dollar farming.
    return max(1, jround(item["price"] * min(mult, 0.9)))


def thug_buy_price(state):
    """Thugs get pricier the bigger your hoe roster gets - a quadratic
    curve fitted to hit exactly £100 at 0 hoes, £300 at 500 hoes, and
    £1,000 at 1,000 hoes - then it caps there. Past 1,000 hoes the price
    stays flat at £1,000 instead of continuing to climb."""
    hoes = min(state["hoes"], 1000)
    price = (hoes * (hoes - 100)) / 1000 + 100
    return max(100, jround(price))


def buy_black_market_item(state, key, qty):
    item = BLACKMARKET_BY_KEY.get(key)
    if not item or item.get("sellOnly"):
        raise GameError("Item not for sale")
    if qty < 1:
        raise GameError("Invalid quantity")
    price = thug_buy_price(state) if key == "thugs" else item["price"]
    total_cost = qty * price
    if state["cash"] < total_cost:
        raise GameError("Not enough cash")
    state["cash"] -= total_cost
    if "gun" in item:
        state["guns"][item["gun"]] += qty
    elif item["stock"] == "medsStock":
        state["medsStock"] += qty
    elif item["stock"] == "thugs":
        state["thugs"] += qty
    elif item["stock"] == "cadillacs":
        state["cadillacs"] += qty
    recalc_morale(state)
    return {"totalCost": total_cost, "price": price}


def sell_black_market(state, key, qty):
    item = BLACKMARKET_BY_KEY.get(key)
    if not item:
        raise GameError("Invalid item")
    if qty < 1:
        raise GameError("Invalid quantity")

    if "gun" in item:
        have = state["guns"].get(item["gun"], 0)
    elif item["stock"] == "armoredTrucks":
        have = state["armoredTrucks"]
    else:
        have = state.get(item["stock"], 0)

    if qty > have:
        raise GameError("You don't have that many to sell")

    price = _market_current_price(state, item)
    payout = qty * price

    if "gun" in item:
        state["guns"][item["gun"]] -= qty
    elif item["stock"] == "armoredTrucks":
        state["armoredTrucks"] -= qty
    else:
        state[item["stock"]] -= qty

    state["cash"] += payout
    recalc_morale(state)
    add_xp(state, payout * SELL_XP_PER_POUND)
    return {"payout": payout, "price": price}


def _step_market_item(state, key):
    m = state["market"][key]
    drift = 0.85 + random.random() * 0.3
    m["mult"] = clamp(m["mult"] * drift, MARKET_MIN_MULT, MARKET_MAX_MULT)
    m["history"].append(m["mult"])
    if len(m["history"]) > MARKET_HISTORY_CAP:
        m["history"] = m["history"][-MARKET_HISTORY_CAP:]


def tick_market(state, now):
    ticks = (now - state["lastMarketUpdate"]) // MARKET_MS
    if ticks < 1:
        return
    steps = min(int(ticks), MARKET_HISTORY_CAP)
    for _ in range(steps):
        for item in BLACKMARKET_ITEMS:
            _step_market_item(state, item["key"])
    state["lastMarketUpdate"] += int(ticks) * MARKET_MS


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

BIO_MAX_LENGTH = 200


def save_bio(state, bio):
    bio = (bio or "").strip()
    if len(bio) > BIO_MAX_LENGTH:
        raise GameError(f"Bio can't be more than {BIO_MAX_LENGTH} characters")
    state["bio"] = bio


# ---------------------------------------------------------------------------
# Crew
# ---------------------------------------------------------------------------

def save_crew_name(state, name):
    if state.get("crewLeaderUserId"):
        raise GameError("You're already a member of a crew — only its leader can rename it")
    name = (name or "").strip()
    if not name:
        raise GameError("Crew name required")
    if name in GANG_NAMES:
        raise GameError(f'"{name}" is already a street crew — pick a different name')
    state["gang"] = name


# Legacy emoji emblems - no longer offered (looked like garbage next to
# the real image emblems below), kept only so any value already stored in
# an old save still resolves to *something* instead of rendering blank.
CREW_EMBLEMS = ["🐍", "🦂", "🐺", "💀", "🔥", "👑", "🗡️", "🦅", "🐉", "⚡", "🎩", "♠️"]
# Image-based emblems - id -> filename under crew_emblems/. Populated as
# real image assets get added (processed the same way as achievement
# badges: cropped/transparent-background PNGs supplied by the admin, not
# an open player upload).
CREW_EMBLEM_IMAGES = {
    "the_pride": "crew_emblems/the_pride.gif",
    "the_forge": "crew_emblems/the_forge.gif",
    "the_serpents_fang": "crew_emblems/the_serpents_fang.gif",
    "the_royal_dead": "crew_emblems/the_royal_dead.gif",
    "the_stormbringers": "crew_emblems/the_stormbringers.gif",
    "the_stormbringers_2": "crew_emblems/the_stormbringers_2.gif",
    "the_watchers": "crew_emblems/the_watchers.gif",
    "the_nightfall_crew": "crew_emblems/the_nightfall_crew.gif",
    "the_ironclad": "crew_emblems/the_ironclad.gif",
    "the_reborn": "crew_emblems/the_reborn.gif",
    "the_riptide": "crew_emblems/the_riptide.gif",
    "the_contagion": "crew_emblems/the_contagion.gif",
    "the_pathfinders": "crew_emblems/the_pathfinders.gif",
    "the_maulers": "crew_emblems/the_maulers.gif",
    "the_breakers": "crew_emblems/the_breakers.gif",
    "the_stargazers": "crew_emblems/the_stargazers.gif",
    "the_wyverns": "crew_emblems/the_wyverns.gif",
    "the_rustlers": "crew_emblems/the_rustlers.gif",
    "the_metropolitans": "crew_emblems/the_metropolitans.gif",
    "the_chroniclers": "crew_emblems/the_chroniclers.gif",
    "the_lone_wolves": "crew_emblems/the_lone_wolves.gif",
    "the_squad": "crew_emblems/the_squad.webp",
    "the_crescent": "crew_emblems/the_crescent.webp",
    "the_crossfire": "crew_emblems/the_crossfire.webp",
    "the_open_hand": "crew_emblems/the_open_hand.gif",
    "the_shadow_circle": "crew_emblems/the_shadow_circle.webp",
    "the_ok_hand": "crew_emblems/the_ok_hand.gif",
    "the_balance": "crew_emblems/the_balance.gif",
    "the_rage": "crew_emblems/the_rage.webp",
    "the_quick_escape": "crew_emblems/the_quick_escape.webp",
    "the_gold_balance": "crew_emblems/the_gold_balance.gif",
    "the_neon_dancer": "crew_emblems/the_neon_dancer.webp",
    "the_statement": "crew_emblems/the_statement.webp",
    "the_criminal": "crew_emblems/the_criminal.webp",
    "the_pointed_gun": "crew_emblems/the_pointed_gun.webp",
    "the_shadow_gunman": "crew_emblems/the_shadow_gunman.webp",
    "the_mac10": "crew_emblems/the_mac10.webp",
    "the_anime_cube": "crew_emblems/the_anime_cube.webp",
    "the_siren": "crew_emblems/the_siren.webp",
    "the_run_and_gun": "crew_emblems/the_run_and_gun.webp",
    "the_partners_in_crime": "crew_emblems/the_partners_in_crime.webp",
}


def set_crew_emblem(state, emblem, world):
    if state.get("crewLeaderUserId"):
        raise GameError("Only the crew leader can set the emblem")
    if emblem not in CREW_EMBLEM_IMAGES:
        raise GameError("Invalid emblem")
    taken_by = next((crew for crew, e in world.get("botCrewEmblems", {}).items() if e == emblem), None)
    if taken_by:
        raise GameError(f"That emblem is already taken by {taken_by}")
    state["crewEmblem"] = emblem


CREW_ATTACK_BAN_MS = 60 * 60 * 1000  # 1 hour


def invite_to_crew(state, bot_id, world):
    if not state["gang"]:
        raise GameError("Set a crew name first")
    if state.get("crewLeaderUserId"):
        raise GameError("Only the crew leader can invite new members")
    if len(state["crewMembers"]) >= 5:
        raise GameError("Crew is full (max 5)")
    if any(m["botId"] == bot_id for m in state["crewMembers"]):
        raise GameError("Already in your crew")
    bot = next((b for b in world["bots"] if b["id"] == bot_id), None)
    if not bot:
        raise GameError("Target not found")
    state["crewMembers"].append({"botId": bot_id, "boss": bot["boss"], "gang": bot["gang"]})


def send_crew_invite_to_human(state, inviter_user_id, defender_state, defender_user_id):
    """Unlike recruiting a bot (instant, no say in it), a real player has to
    accept before they actually join - this drops a pending invite on their
    side for them to respond to, AND surfaces the same invite as an
    actionable message in their DM thread with the inviter (not just a
    separate panel on the Crew page)."""
    if not state["gang"]:
        raise GameError("Set a crew name first")
    if state.get("crewLeaderUserId"):
        raise GameError("Only the crew leader can invite new members")
    if len(state["crewMembers"]) >= 5:
        raise GameError("Crew is full (max 5)")
    target_id = HUMAN_ID_OFFSET + defender_user_id
    if any(m["botId"] == target_id for m in state["crewMembers"]):
        raise GameError("Already in your crew")
    pending = defender_state.setdefault("pendingCrewInvites", [])
    if any(inv["fromUserId"] == inviter_user_id for inv in pending):
        raise GameError("You already have a pending invite out to them")
    pending.append({
        "fromUserId": inviter_user_id,
        "fromName": state["name"],
        "fromGang": state["gang"],
        "sentAt": now_ms(),
    })
    add_log(state, f"Sent a crew invite to {defender_state['name']}.", "info")
    add_log(defender_state, f"{state['name']} invited you to join \"{state['gang']}\".", "info")

    now = now_ms()
    inviter_human_id = HUMAN_ID_OFFSET + inviter_user_id
    defender_state.setdefault("messages", []).append({
        "from": inviter_human_id, "to": "player",
        "text": f'Invited you to join "{state["gang"]}"',
        "timestamp": now, "read": False,
        "kind": "crewInvite", "fromUserId": inviter_user_id, "gang": state["gang"],
    })
    state["messages"].append({
        "from": "player", "to": target_id,
        "text": f'Invited {defender_state["name"]} to join "{state["gang"]}"',
        "timestamp": now, "read": True,
        "kind": "crewInvite",
    })
    return {"sentTo": defender_state["name"]}


def _resolve_crew_invite_messages(state, from_id_field, match_id, status):
    for m in state.get("messages", []):
        if m.get("kind") == "crewInvite" and m.get(from_id_field) == match_id and not m.get("status"):
            m["status"] = status
            m["read"] = True


def decline_crew_invite(state, my_user_id, inviter_state, from_user_id):
    pending = state.get("pendingCrewInvites", [])
    if not any(inv["fromUserId"] == from_user_id for inv in pending):
        raise GameError("No such invite")
    state["pendingCrewInvites"] = [inv for inv in pending if inv["fromUserId"] != from_user_id]
    _resolve_crew_invite_messages(state, "from", HUMAN_ID_OFFSET + from_user_id, "declined")
    _resolve_crew_invite_messages(inviter_state, "to", HUMAN_ID_OFFSET + my_user_id, "declined")


def accept_crew_invite(state, my_user_id, inviter_state, from_user_id):
    pending = state.get("pendingCrewInvites", [])
    invite = next((inv for inv in pending if inv["fromUserId"] == from_user_id), None)
    if not invite:
        raise GameError("No such invite")
    # Whatever happens below, this invite is spent - never leave a stale one
    # a player can click on again.
    state["pendingCrewInvites"] = [inv for inv in pending if inv["fromUserId"] != from_user_id]
    if state.get("gang"):
        raise GameError("You're already in a crew — leave it before joining another")
    if len(inviter_state["crewMembers"]) >= 5:
        raise GameError("That crew is now full")
    my_human_id = HUMAN_ID_OFFSET + my_user_id
    if any(m["botId"] == my_human_id for m in inviter_state["crewMembers"]):
        raise GameError("Already in that crew")
    inviter_state["crewMembers"].append({"botId": my_human_id, "boss": state["name"], "gang": state.get("gang", "")})
    # Mirror the crew name/leader onto the joining member's own state too -
    # otherwise their own gang tag, leaderboard row, and Crew page never
    # reflect that they actually joined anything.
    state["gang"] = invite["fromGang"]
    state["crewLeaderUserId"] = from_user_id
    state["crewLeaderName"] = invite["fromName"]
    add_log(state, f"You joined {invite['fromName']}'s crew \"{invite['fromGang']}\".", "good")
    add_log(inviter_state, f"{state['name']} joined your crew.", "good")
    _resolve_crew_invite_messages(state, "from", HUMAN_ID_OFFSET + from_user_id, "accepted")
    _resolve_crew_invite_messages(inviter_state, "to", my_human_id, "accepted")
    return {"gang": invite["fromGang"]}


THE_JOB_ROLES = ["don", "gunman", "driver", "bomber"]
THE_JOB_ROLE_LABELS = {"don": "The Don", "gunman": "Gunman", "driver": "Driver", "bomber": "Bomber"}
# The Don pays cash to plan it; the other three donate straight out of their
# own stockpile instead of paying cash - guns/cars/bombs are all slow to
# accumulate, so this is a real contribution, not just a shopping trip.
THE_JOB_DON_COST = 250_000_000
THE_JOB_GUN_DONATION = 10_000
THE_JOB_CAR_DONATION = 300
THE_JOB_BOMB_DONATION = 500
THE_JOB_PRIZE_MIN_M = 1_000  # whole millions, so the rolled prize is a clean number
THE_JOB_PRIZE_MAX_M = 10_000
THE_JOB_SUCCESS_CHANCE = 0.70
THE_JOB_COOLDOWN_MS = 24 * 60 * 60 * 1000
# Once the last role fills, the job isn't instant - it takes this long to
# actually go down, same wait for everyone regardless of who triggers the
# check (see maybe_resolve_the_job).
THE_JOB_EXECUTION_DELAY_MS = 2 * 60 * 1000
# "The Don" is both the role name and the top rank's name on purpose - only
# a player who's actually reached rank 13 can plan the job, which is what
# stops this from being doable "at the start of the game."
THE_JOB_DON_RANK_REQUIRED = 13

GUN_TYPES = ("pistol9mm", "shotgun12gauge", "ak47", "m249")


def _total_guns(state):
    return sum(state.get("guns", {}).values())


def _take_guns(state, amount):
    remaining = amount
    for gun_type in GUN_TYPES:
        have = state["guns"].get(gun_type, 0)
        take = min(have, remaining)
        state["guns"][gun_type] -= take
        remaining -= take
        if remaining <= 0:
            break


def start_the_job(leader_state, starter_user_id, starter_name):
    """Any crew member can post The Job - it doesn't have to be the crew
    leader. Rolls a random £1bn-£10bn prize up front (so everyone can see
    the stakes before buying into a role) and opens all 4 roles for anyone
    in the crew to claim. See claim_job_role for how roles fill and
    maybe_resolve_the_job for how it eventually pays out."""
    if leader_state.get("theJob"):
        raise GameError("The Job is already in motion for your crew")
    now = now_ms()
    cooldown = leader_state.get("theJobCooldownUntil", 0)
    if now < cooldown:
        wait_hours = math.ceil((cooldown - now) / (60 * 60 * 1000))
        raise GameError(f"Your crew just pulled a job - try again in {wait_hours}h")
    prize = random.randint(THE_JOB_PRIZE_MIN_M, THE_JOB_PRIZE_MAX_M) * 1_000_000
    job = {
        "startedByUserId": starter_user_id,
        "startedByName": starter_name,
        "prize": prize,
        "createdAt": now,
        "executesAt": None,
        "splits": {role: 25 for role in THE_JOB_ROLES},
        "roles": {role: {"userId": None, "name": None} for role in THE_JOB_ROLES},
    }
    leader_state["theJob"] = job
    add_log(leader_state, f"{starter_name} is planning a £{prize:,} job. The crew needs a Don, Gunman, Driver, and Bomber.", "good")
    return job


def set_job_split(leader_state, requester_user_id, splits):
    """Only whoever currently holds the Don role can set the payout split -
    matches "the Don is the planner" from how this was designed. Can be
    changed any time before the job resolves."""
    job = leader_state.get("theJob")
    if not job:
        raise GameError("No job in progress")
    if job["roles"]["don"].get("userId") != requester_user_id:
        raise GameError("Only the Don can set the split")
    if set(splits.keys()) != set(THE_JOB_ROLES):
        raise GameError("Split must cover all 4 roles")
    try:
        clean = {role: int(splits[role]) for role in THE_JOB_ROLES}
    except (TypeError, ValueError):
        raise GameError("Split percentages must be whole numbers")
    if any(v < 0 for v in clean.values()) or sum(clean.values()) != 100:
        raise GameError("Split percentages must be 0 or more and add up to 100")
    job["splits"] = clean
    return job


def claim_job_role(leader_state, role, claimant_state, claimant_user_id, claimant_name):
    """Fills one of the 4 open roles - always personally, no hiring outside
    help. The Don pays cash to plan it; Gunman/Driver/Bomber each donate a
    stockpile of guns/cars/bombs straight out of their own supply. Once the
    last role fills, the job doesn't fire immediately - it goes into motion
    and resolves itself after THE_JOB_EXECUTION_DELAY_MS (see
    maybe_resolve_the_job)."""
    job = leader_state.get("theJob")
    if not job:
        raise GameError("No job in progress")
    if job.get("executesAt"):
        raise GameError("The Job is already underway")
    if role not in THE_JOB_ROLES:
        raise GameError("Invalid role")
    role_data = job["roles"][role]
    if role_data.get("userId") is not None:
        raise GameError(f"{THE_JOB_ROLE_LABELS[role]} is already filled")
    if any(r.get("userId") == claimant_user_id for r in job["roles"].values()):
        raise GameError("You already have a role in this job")

    if role == "don":
        if rank_info(claimant_state.get("xp", 0))["level"] < THE_JOB_DON_RANK_REQUIRED:
            raise GameError("Only a player ranked THE DON can plan the job")
        if claimant_state["cash"] < THE_JOB_DON_COST:
            raise GameError(f"Need £{THE_JOB_DON_COST:,} to plan the job")
        claimant_state["cash"] -= THE_JOB_DON_COST
        add_log(claimant_state, f"Paid £{THE_JOB_DON_COST:,} to plan The Job as the Don.", "good")
    elif role == "gunman":
        if _total_guns(claimant_state) < THE_JOB_GUN_DONATION:
            raise GameError(f"Need {THE_JOB_GUN_DONATION:,} guns (any type) to arm the crew")
        _take_guns(claimant_state, THE_JOB_GUN_DONATION)
        add_log(claimant_state, f"Donated {THE_JOB_GUN_DONATION:,} guns to The Job.", "good")
    elif role == "driver":
        if claimant_state.get("cadillacs", 0) < THE_JOB_CAR_DONATION:
            raise GameError(f"Need {THE_JOB_CAR_DONATION:,} cars to be the getaway driver")
        claimant_state["cadillacs"] -= THE_JOB_CAR_DONATION
        add_log(claimant_state, f"Donated {THE_JOB_CAR_DONATION:,} cars to The Job.", "good")
    else:  # bomber
        if claimant_state.get("bombs", 0) < THE_JOB_BOMB_DONATION:
            raise GameError(f"Need {THE_JOB_BOMB_DONATION:,} bombs to breach the vault")
        claimant_state["bombs"] -= THE_JOB_BOMB_DONATION
        add_log(claimant_state, f"Donated {THE_JOB_BOMB_DONATION:,} bombs to The Job.", "good")

    role_data["userId"] = claimant_user_id
    role_data["name"] = claimant_name

    if all(r.get("userId") is not None for r in job["roles"].values()):
        job["executesAt"] = now_ms() + THE_JOB_EXECUTION_DELAY_MS
        add_log(leader_state, "All 4 roles filled - The Job is underway. Results in a couple of minutes.", "good")
        return {"complete": False, "job": job, "executing": True}
    return {"complete": False, "job": job, "executing": False}


def maybe_resolve_the_job(leader_state):
    """Checked opportunistically on every request (see attach_world_view in
    app.py) rather than tied to any single action - the job resolves itself
    once its execution delay has passed, whichever crew member happens to
    trigger the check. Returns the resolution dict if it just resolved,
    else None. Doesn't itself credit payouts - the caller is responsible
    for crediting each recipient's own saved state, since a job's
    participants are rarely all the same account."""
    job = leader_state.get("theJob")
    if not job or not job.get("executesAt") or now_ms() < job["executesAt"]:
        return None

    success = random.random() < THE_JOB_SUCCESS_CHANCE
    payouts = {}
    if success:
        for role, data in job["roles"].items():
            user_id = data.get("userId")
            if user_id is None:
                continue
            amount = jround(job["prize"] * job["splits"].get(role, 0) / 100)
            if amount > 0:
                payouts[user_id] = payouts.get(user_id, 0) + amount

    leader_state["theJob"] = None
    leader_state["theJobCooldownUntil"] = now_ms() + THE_JOB_COOLDOWN_MS
    if success:
        add_log(leader_state, f"The Job came off clean - £{job['prize']:,} split between the crew.", "good")
    else:
        add_log(leader_state, "The Job went sideways. Everyone's buy-in is gone.", "bad")

    return {"complete": True, "success": success, "prize": job["prize"], "payouts": payouts, "roles": job["roles"]}


def credit_the_job_payout(state, amount):
    state["cash"] = state.get("cash", 0) + amount
    add_log(state, f"Your cut of The Job: £{amount:,}.", "good")


def remove_from_crew(state, bot_id, member_state=None):
    member = next((m for m in state["crewMembers"] if m["botId"] == bot_id), None)
    state["crewMembers"] = [m for m in state["crewMembers"] if m["botId"] != bot_id]
    if member:
        # Only the bot who just got dropped is protected from you for an
        # hour - nobody else in their crew is covered by this.
        state.setdefault("crewAttackBans", {})[str(bot_id)] = now_ms() + CREW_ATTACK_BAN_MS
        # Free the removed member's own state too, or they'd be stuck
        # permanently unable to create/join any crew ever again.
        if member_state is not None:
            member_state["gang"] = ""
            member_state["crewLeaderUserId"] = None
            member_state["crewLeaderName"] = ""


# ---------------------------------------------------------------------------
# DMs (canned replies from bots; real delivery for human-to-human)
# ---------------------------------------------------------------------------

CANNED_BOT_REPLIES = [
    "Stay out of my territory.",
    "Ha! You wish you had my numbers.",
    "We'll settle this in the streets.",
    "Not interested in talking business with you.",
    "Careful who you threaten, kid.",
    "My crew's watching you already.",
    "Come back when you're worth my time.",
    "Nice try. Not happening.",
]


def send_dm(state, to_id, text, world, defender_state=None, sender_user_id=None):
    """Sends a DM. Bot targets get an instant canned reply, appended to the
    sender's own log only (cosmetic, one-sided). A real human target instead
    gets the message delivered into their own message log (via
    `defender_state`, loaded/saved by the caller) so they actually receive
    it and can reply - no auto-reply, since a person answers for themselves."""
    text = (text or "").strip()
    if not text:
        raise GameError("Message can't be empty")
    now = now_ms()
    state["messages"].append({"from": "player", "to": to_id, "text": text, "timestamp": now, "read": True})

    if defender_state is not None:
        sender_id = HUMAN_ID_OFFSET + sender_user_id
        defender_state.setdefault("messages", []).append({
            "from": sender_id, "to": "player", "text": text, "timestamp": now, "read": False,
        })
        return {"reply": None}

    bot = next((b for b in world["bots"] if b["id"] == to_id), None)
    reply = None
    if bot:
        reply = random.choice(CANNED_BOT_REPLIES)
        state["messages"].append({"from": to_id, "to": "player", "text": reply, "timestamp": now + 1000, "read": False})
    return {"reply": reply}


def mark_dm_read(state, from_id):
    for m in state.get("messages", []):
        if m.get("from") == from_id and m.get("to") == "player":
            m["read"] = True


CREW_CHAT_MAX_LENGTH = 300
CREW_CHAT_HISTORY_CAP = 100


def send_crew_chat_message(leader_state, sender_user_id, sender_name, text):
    """Appends to the crew LEADER's own crewChat log - the one shared,
    authoritative copy every member reads from (same pattern as
    crewMembers/crewEmblem). The caller (app.py) is responsible for
    resolving `leader_state` to the actual leader's state - this function
    doesn't care whether the sender IS the leader or just a member."""
    text = (text or "").strip()
    if not text:
        raise GameError("Message can't be empty")
    if len(text) > CREW_CHAT_MAX_LENGTH:
        raise GameError(f"Message can't be more than {CREW_CHAT_MAX_LENGTH} characters")
    chat = leader_state.setdefault("crewChat", [])
    chat.append({
        "userId": sender_user_id,
        "name": sender_name,
        "text": text,
        "timestamp": now_ms(),
    })
    del chat[:-CREW_CHAT_HISTORY_CAP]
    return {"sent": True}


# ---------------------------------------------------------------------------
# Settings / misc
# ---------------------------------------------------------------------------

def save_pimp_name(state, name):
    if state.get("pimpNameLocked"):
        raise GameError("Pimp name is locked and cannot be changed")
    name = (name or "").strip()
    if not name:
        raise GameError("Name required")
    state["name"] = name


def set_tutorial_visibility(state, enabled):
    state["showTutorial"] = bool(enabled)


def buy_mob_dollars_with_real_money(state):
    now = now_ms()
    if now < state["lastRealMoneyPurchase"] + REALMONEY_COOLDOWN_MS:
        raise GameError("On cooldown")
    state["mobDollars"] = state.get("mobDollars", 0) + REALMONEY_MOB_DOLLARS
    state["lastRealMoneyPurchase"] = now
    add_log(state, f"Purchased {REALMONEY_MOB_DOLLARS} \U0001fa99 Mob Dollars.", "good")


def spend_mob_dollars_on_turns(state, amount):
    """Mob Dollars is a prize currency (won from achievements, referrals, or
    bought with real money above) - it can only ever be spent in-game, never
    withdrawn or cashed out. Spending is always instant, no cooldown."""
    amount = int(amount)
    if amount <= 0:
        raise GameError("Invalid amount")
    have = state.get("mobDollars", 0)
    if have < amount:
        raise GameError("Not enough Mob Dollars")
    room = state["maxTurns"] - state["turns"]
    if room <= 0:
        raise GameError("Turns already full")
    turns_gained = min(amount * MOB_DOLLARS_TURNS_PER_UNIT, room)
    state["mobDollars"] = have - amount
    state["turns"] += turns_gained
    add_log(state, f"Spent {amount} 🪙 Mob Dollars for {turns_gained} turns.", "good")


def travel_cost(state, city):
    return max(TRAVEL_BASE_FEE, jround(TRAVEL_COST_PER_THUG * state["thugs"]))


def travel_capacity(state):
    return (state.get("cadillacs", 0) * TRAVEL_THUGS_PER_CADILLAC
            + state.get("armoredTrucks", 0) * TRAVEL_THUGS_PER_ARMORED_TRUCK)


def travel_to(state, city_name):
    city = next((c for c in CITIES if c["name"] == city_name), None)
    if not city:
        raise GameError("Unknown city")
    if travel_capacity(state) < state["thugs"]:
        raise GameError("Not enough cars to move your crew - buy more cadillacs or armored trucks")
    cost = travel_cost(state, city)
    if state["cash"] < cost:
        raise GameError("Not enough cash to travel there")
    state["cash"] -= cost
    state["location"] = city_name
    return {"cost": cost}


# ---------------------------------------------------------------------------
# Timers / catch-up (called at the top of every request after loading state)
# ---------------------------------------------------------------------------

def tick_regen(state, now):
    if state["turns"] < state["maxTurns"]:
        ticks = (now - state["lastRegen"]) // REGEN_MS
        if ticks > 0:
            gained = min(int(ticks) * REGEN_AMOUNT, state["maxTurns"] - state["turns"])
            state["turns"] += gained
            state["lastRegen"] += int(ticks) * REGEN_MS
    else:
        state["lastRegen"] = now


def tick_factories(state, now):
    ticks = (now - state["lastFactoryRun"]) // FACTORY_MS
    if ticks >= 1:
        run_factories(state, int(ticks))
        state["lastFactoryRun"] += int(ticks) * FACTORY_MS


def check_daily_bonus(state, now):
    if now - state["last24HourBonus"] >= DAILY_BONUS_MS:
        state["turns"] = min(state["maxTurns"], state["turns"] + DAILY_BONUS_AMOUNT)
        state["last24HourBonus"] = now
        add_log(state, "Daily bonus: +1000 turns!", "good")


def apply_catchup(state):
    """Run every time-based system forward to `now` for one player's own
    state. Call this right after loading a player's row from the DB and
    before handling any action. Bots live in the shared world now - see
    apply_world_catchup - so nothing bot-related happens here."""
    now = now_ms()
    if "carFactoryRatio" not in state:
        old_mode = state.pop("carFactoryMode", "cadillac")
        state["carFactoryRatio"] = 1.0 if old_mode == "cadillac" else 0.0
    if "gunFactoryRatio" not in state:
        state["gunFactoryRatio"] = 0.0
    if "crewAttackBans" not in state:
        state["crewAttackBans"] = {}
    if "crewEmblem" not in state:
        state["crewEmblem"] = ""
    if "crewChat" not in state:
        state["crewChat"] = []
    if "layLowUntil" not in state:
        state["layLowUntil"] = 0
    if "layLowCooldownUntil" not in state:
        state["layLowCooldownUntil"] = 0
    if "drug" not in state["factories"]:
        state["factories"]["drug"] = 0
    if "gym" not in state["factories"]:
        state["factories"]["gym"] = 0
    if "warehouse" not in state["factories"]:
        state["factories"]["warehouse"] = 0
    if "thugsInHospital" not in state:
        state["thugsInHospital"] = 0
    if "thugsHospitalReadyAt" not in state:
        state["thugsHospitalReadyAt"] = 0
    if "pendingCrewInvites" not in state:
        state["pendingCrewInvites"] = []
    if "xp" not in state:
        state["xp"] = 0
    if "achievements" not in state:
        state["achievements"] = []
    if "mobDollars" not in state:
        state["mobDollars"] = 0
    if "referredBy" not in state:
        state["referredBy"] = None
    if "referralRewardPaid" not in state:
        state["referralRewardPaid"] = False
    if "statsThugsKilled" not in state:
        state["statsThugsKilled"] = 0
    if "statsFactoriesDestroyed" not in state:
        state["statsFactoriesDestroyed"] = 0
    if "statsMoneyStolen" not in state:
        state["statsMoneyStolen"] = 0
    if "statsCarsStolen" not in state:
        state["statsCarsStolen"] = 0
    if "statsJobsSucceeded" not in state:
        state["statsJobsSucceeded"] = 0
    if "statsTurnsWorked" not in state:
        state["statsTurnsWorked"] = 0
    if "lastJobHeist" not in state:
        state["lastJobHeist"] = 0
    if "theJob" not in state:
        state["theJob"] = None
    if "theJobCooldownUntil" not in state:
        state["theJobCooldownUntil"] = 0
    if "counterfeitStock" not in state:
        state["counterfeitStock"] = 0
    state.pop("hoeRoster", None)
    state.pop("nextHoeId", None)
    # Bank feature removed - fold any balance still sitting in it back into
    # cash so nobody's money just vanishes, then drop the now-unused fields.
    if "bank" in state:
        state["cash"] = state.get("cash", 0) + state.pop("bank")
    state.pop("lastBankFeeUpdate", None)
    state.pop("bankLockedUntil", None)
    tick_regen(state, now)
    tick_factories(state, now)
    tick_market(state, now)
    process_human_hospital(state, now)
    check_dealer_reset(state, now)
    check_daily_bonus(state, now)
    recalc_morale(state)
    check_milestone_achievements(state)
    check_rank_rewards(state)
    return state


def apply_world_catchup(world):
    """Run every time-based system forward to `now` for the shared world
    (bots). Call this once per request, independent of which player is
    making it."""
    now = now_ms()
    ensure_bots(world)
    if "globalAttackLog" not in world:
        world["globalAttackLog"] = []
    if "globalChat" not in world:
        world["globalChat"] = []
    if "records" not in world:
        world["records"] = {}
    if "seasonEndAt" not in world:
        # SEASON_1_END_MS was only correct immediately after the original
        # 2026-07-14 reset - once that date passes, backfilling to it again
        # (e.g. after a later world wipe) would hand every player an
        # already-expired countdown. Backfill to a fresh "now + duration"
        # season instead; SEASON_1_END_MS is kept only as a historical record.
        world["seasonEndAt"] = now + GAME_DURATION_MS
    if "seasonPrizesAwarded" not in world:
        world["seasonPrizesAwarded"] = False
    # One-time migration: bots created before the 4-crew system had unique
    # per-bot gang names. Reassign everyone into the new shared crews
    # without touching any other bot progress.
    if world["bots"] and world["bots"][0].get("gang") not in GANG_NAMES:
        crew_assignments = even_crew_assignments(len(world["bots"]))
        for b, gang in zip(world["bots"], crew_assignments):
            b["gang"] = gang
    # Bots used to spawn in a random city independent of their crew. Keep
    # every bot snapped to its crew's shared city so gang-mates actually
    # live together - cheap to re-check every request, and self-heals any
    # bot left over from before this existed.
    for b in world["bots"]:
        crew_city = world["botCrewCities"].get(b["gang"])
        if crew_city and b["city"] != crew_city:
            b["city"] = crew_city
    regen_bots(world, now)
    process_bot_hospitals(world, now)
    return world
