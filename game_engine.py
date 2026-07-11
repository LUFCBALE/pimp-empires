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

BANK_LOCKOUT_MS = 10 * 60 * 1000
BANK_FEE_MS = 60 * 60 * 1000
BANK_FEE_PCT = 0.05

BRIBE_DURATION_MS = 5 * 60 * 1000
BRIBE_COOLDOWN_MS = 60 * 60 * 1000

BOT_COUNT = 19
BOT_TICK_MS = 5 * 60 * 1000  # bots take an action roughly every 5 real minutes
BOT_MAX_TURNS = 5000
BOT_MAX_TICKS_PER_CATCHUP = 60  # cap one catch-up burst at ~5 hours of simulated activity

HOE_RECRUIT_TURN_BLOCK = 10
HOE_RECRUIT_MIN = 1
HOE_RECRUIT_MAX = 3
THUG_RECRUIT_PER_TURN = 1

NIGHT_TURNS = 150
HOE_NIGHTLY_CAP = 2000

DAILY_BONUS_MS = 24 * 60 * 60 * 1000
DAILY_BONUS_AMOUNT = 1000

REALMONEY_COOLDOWN_MS = 12 * 60 * 60 * 1000
REALMONEY_TURNS = 500

DEALER_RESET_MS = 10 * 60 * 1000
DEALER_DAILY_CAP = 100
DEALER_RESALE_COOLDOWN_MS = 10 * 60 * 1000

STORE_ITEMS = {
    "girls": [
        {"id": "condoms", "name": "Safety Kits", "cost": 300},
    ],
    "thugs": [
        {"id": "cadillac", "name": "Cadillac", "cost": 15000},
    ],
    "weapons": [
        {"id": "pistol9mm", "name": "9mm Pistol", "cost": 800},
        {"id": "shotgun12gauge", "name": "12 Gauge Shotgun", "cost": 3500},
        {"id": "ak47", "name": "AK-47", "cost": 6000},
    ],
}

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

CITIES = [
    {"name": "London", "home": True},
    {"name": "Bristol"},
    {"name": "Birmingham"},
    {"name": "Manchester"},
    {"name": "Leeds"},
    {"name": "Liverpool"},
]
AWAY_CITIES = [c["name"] for c in CITIES if not c.get("home")]

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
WORK_LOCATION_HOE_RECRUIT_BASE_PER_10_TURNS = {
    "redlight": 4,
    "nightclub": 5,
    "pullup": 7,
}

# Hoes take this cut of every session's gross earnings as their pay - it's
# just gone, not credited to cash, bank or hoeCash anywhere.
HOE_WAGE_PCT = 0.10

HEIST_JOBS = {
    "shop": {"minThugs": 200, "turnCost": 10, "minCash": 800, "maxCash": 4000,
             "successChance": 0.60, "casualtyPct": (0.05, 0.15), "failCasualtyPct": (0.15, 0.35)},
    "jewellery": {"minThugs": 1000, "turnCost": 50, "minCash": 8000, "maxCash": 35000,
                  "successChance": 0.42, "casualtyPct": (0.10, 0.25), "failCasualtyPct": (0.30, 0.55)},
    "bank": {"minThugs": 5000, "turnCost": 150, "minCash": 60000, "maxCash": 250000,
             "successChance": 0.28, "casualtyPct": (0.20, 0.40), "failCasualtyPct": (0.45, 0.80)},
}
CASINO_JOB = {
    "thugsPerMember": 10000, "turnsPerMember": 100, "minCash": 500000, "maxCash": 2000000,
    "successChance": 0.35, "casualtyPct": (0.15, 0.30), "failCasualtyPct": (0.50, 0.90),
    "cooldownHours": 24,
}

FACTORY_COSTS = {
    "medical": 940000, "gun": 25000000, "car": 30000000, "drug": 14000000,
    "explosive": 32000000, "counterfeit": 23000000,
}

# Explicit per-factory sell/refund price (not a flat % of cost - each type
# has its own resale value now).
FACTORY_SELL_PRICES = {
    "medical": 170000, "gun": 14000000, "car": 13000000, "drug": 3000000,
    "explosive": 9000000, "counterfeit": 6000000,
}

# All factory output rates below are boosted 30% over their original values,
# since a single factory's produce was worth very little next to what it
# actually costs.
DRUG_FACTORY_RATE = 2079  # cocaine produced per factory per tick

MEDICAL_KIT_RATE = 130  # safety kits produced per factory per tick
EXPLOSIVE_BOMB_RATE = 65  # bombs produced per factory per tick
COUNTERFEIT_CASH_RATE = 48750  # cash printed per factory per tick

# Car factories split their output between cadillacs (high-volume, more
# cash, small morale bump) and armored trucks (low-volume, more net worth
# per unit, big morale bump). `carFactoryRatio` is a 0.0-1.0 slider: 1.0 is
# all-in on cadillacs (46 cadillacs + 4 trucks per factory per tick), 0.0 is
# all-in on trucks (3 cadillacs + 13 trucks per factory per tick), and
# everything between is a straight linear blend.
CAR_FACTORY_CADILLAC_AT_MAX = 46
CAR_FACTORY_CADILLAC_AT_MIN = 3
CAR_FACTORY_ARMORED_AT_MAX = 4
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
GUN_FACTORY_PISTOL_AT_VOLUME = 39
GUN_FACTORY_PISTOL_AT_ELITE = 3
GUN_FACTORY_SHOTGUN_AT_VOLUME = 26
GUN_FACTORY_SHOTGUN_AT_ELITE = 7
GUN_FACTORY_AK_AT_VOLUME = 13
GUN_FACTORY_AK_AT_ELITE = 13
GUN_FACTORY_M249_AT_VOLUME = 3
GUN_FACTORY_M249_AT_ELITE = 4


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
        "gang": "",
        "cash": 500,
        "bank": 0,
        "hoes": 1,
        "thugs": 0,
        "turns": 2000,
        "maxTurns": 3600,
        "lastRegen": now,
        "hoeMorale": 50,
        "thugMorale": 50,
        "workLocation": "redlight",
        "location": random.choice(AWAY_CITIES),
        "gunsStock": 0,
        "gunsOwned": 0,
        "guns": {"pistol9mm": 0, "shotgun12gauge": 0, "ak47": 0, "m249": 0},
        "cadillacs": 0,
        "armoredTrucks": 0,
        "medsStock": 1,
        "factories": {"medical": 0, "gun": 0, "car": 0, "drug": 0, "explosive": 0, "counterfeit": 0},
        "carFactoryRatio": 1.0,
        "gunFactoryRatio": 0.0,
        "bombs": 0,
        "lastFactoryRun": now,
        "market": {item["key"]: {"mult": 1.0, "history": [1.0]} for item in BLACKMARKET_ITEMS},
        "lastMarketUpdate": now,
        "lastBankFeeUpdate": now,
        "bankLockedUntil": 0,
        "lastCasinoHeist": 0,
        "bribeActiveUntil": 0,
        "bribeCooldownUntil": 0,
        "hoeRoster": [],
        "nextHoeId": 0,
        "crewMembers": [],
        "crewAttackBans": {},
        "crewEmblem": "",
        "crewLeaderUserId": None,
        "crewLeaderName": "",
        "pendingCrewInvites": [],
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
    ensure_hoe_roster(state)
    return state


def add_log(state, msg, cls="info"):
    state["log"].append({"t": now_ms(), "msg": msg, "cls": cls})
    if len(state["log"]) > 60:
        state["log"] = state["log"][-60:]


# ---------------------------------------------------------------------------
# Hoe roster
# ---------------------------------------------------------------------------

def _random_hoe_name(state):
    for _ in range(20):
        name = f"{random.choice(HOE_FIRST_NAMES)} {random.choice(HOE_LAST_NAMES)}"
        if not any(h["name"] == name for h in state["hoeRoster"]):
            return name
    return f"{random.choice(HOE_FIRST_NAMES)} {random.choice(HOE_LAST_NAMES)}"


def create_hoe(state):
    state["nextHoeId"] += 1
    hoe = {
        "id": state["nextHoeId"],
        "name": _random_hoe_name(state),
        "happiness": jround(state["hoeMorale"]),
        "earned": 0,
        "turnsWorked": 0,
    }
    state["hoeRoster"].append(hoe)
    return hoe


def ensure_hoe_roster(state):
    target = state["hoes"]
    roster = state["hoeRoster"]
    while len(roster) < target:
        create_hoe(state)
    if len(roster) > target:
        state["hoeRoster"] = roster[:target] if target > 0 else []
    state["hoes"] = len(state["hoeRoster"])


def add_hoes(state, n):
    for _ in range(max(0, n)):
        create_hoe(state)
    state["hoes"] = len(state["hoeRoster"])


def distribute_earnings(state, total, turns_spent):
    """Earnings are driven by collective hoeMorale, not each hoe's individual
    happiness, so the payout is just split evenly across the roster - this
    is purely for each hoe's own "earned" display stat, not a real cash
    allocation."""
    roster = state["hoeRoster"]
    if not roster:
        return
    per_hoe = total / len(roster)
    for h in roster:
        h["turnsWorked"] += turns_spent
        h["earned"] += jround(per_hoe)


def recalc_morale(state):
    """Happiness/morale are pure supply ratios - meds:hoes and guns:thugs,
    both 1:1 for 100% - recalculated fresh from current stock every time
    this runs. No decay, no drift, no bonus from heists or purchases;
    just "do you have enough," reflected live. Call this any time hoes,
    thugs, medsStock, or guns change, and unconditionally at the end of
    apply_catchup so it's always accurate regardless of which action ran."""
    hoes = state.get("hoes", 0)
    state["hoeMorale"] = min(100, jround(100 * state.get("medsStock", 0) / hoes)) if hoes > 0 else 100
    for h in state.get("hoeRoster", []):
        h["happiness"] = state["hoeMorale"]

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
HOE_ATTRITION_MIN_CHANCE = 0.05  # chance an individual hoe walks, right at the 40% threshold
HOE_ATTRITION_MAX_CHANCE = 0.40  # chance at rock-bottom 0% happiness


def check_hoe_attrition(state):
    """Hoes are never lost to a raid/bust - the only way you lose them is
    letting happiness collapse. Below 40% happiness each hoe has a small,
    escalating chance of walking per work session; by 0% happiness a lot
    of them go. Checked per-individual against their own happiness, not the
    aggregate hoeMorale."""
    roster = state.get("hoeRoster", [])
    if not roster:
        return 0
    survivors = []
    left = 0
    for h in roster:
        happiness = h["happiness"]
        if happiness < HOE_ATTRITION_HAPPINESS_THRESHOLD:
            severity = 1 - (happiness / HOE_ATTRITION_HAPPINESS_THRESHOLD)
            leave_chance = HOE_ATTRITION_MIN_CHANCE + severity * (HOE_ATTRITION_MAX_CHANCE - HOE_ATTRITION_MIN_CHANCE)
            if random.random() < leave_chance:
                left += 1
                continue
        survivors.append(h)
    if left:
        state["hoeRoster"] = survivors
        state["hoes"] = len(survivors)
    return left


# ---------------------------------------------------------------------------
# Bots
# ---------------------------------------------------------------------------

# Each bot plays with a distinct style instead of one flat growth curve:
#   hustler  - invests hard in hoes, banks cash fastest
#   enforcer - invests hard in thugs, more muscle than money
#   mogul    - saves aggressively and plows cash into buying factories
#   shark    - preys on other bots in the same city, skimming their hoeCash
BOT_ARCHETYPES = {
    "hustler": {"hoeGrowth": 1.4, "thugGrowth": 0.7, "cashRate": 1.0, "raidChance": 0.0, "reinvestRate": 0.20},
    "enforcer": {"hoeGrowth": 0.7, "thugGrowth": 1.5, "cashRate": 1.0, "raidChance": 0.05, "reinvestRate": 0.15},
    "mogul": {"hoeGrowth": 1.0, "thugGrowth": 0.9, "cashRate": 1.4, "raidChance": 0.0, "reinvestRate": 0.35},
    "shark": {"hoeGrowth": 0.9, "thugGrowth": 1.1, "cashRate": 0.9, "raidChance": 0.25, "reinvestRate": 0.10},
}
BOT_FACTORY_TYPES = ("medical", "gun", "car", "explosive", "counterfeit")

# Bots keep this much hoeCash on hand as walking-around money - anything
# above it gets plowed into guns/cars each tick (see bot_reinvest_hoecash)
# instead of just piling up as a raid target.
BOT_HOECASH_REINVEST_FLOOR = 15000
BOT_REINVEST_GUN_PRICES = {"pistol9mm": 240, "shotgun12gauge": 1050, "ak47": 1800, "m249": 8000}
BOT_REINVEST_CAR_PRICE = 9600


def make_bot(bot_id, used_bosses, gang):
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
        "city": random.choice(AWAY_CITIES),
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
            "explosive": 0,
            "counterfeit": 0,
        },
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
    if not world.get("bots"):
        used_bosses = set()
        crew_assignments = even_crew_assignments(BOT_COUNT)
        world["bots"] = [make_bot(i + 1, used_bosses, crew_assignments[i]) for i in range(BOT_COUNT)]
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


def ensure_bot_crew_emblems(world):
    """Each of the 4 street crews gets a random emblem, assigned once.
    First come, first served: no two crews (bot or player) share one."""
    if world.get("botCrewEmblems"):
        return
    available = random.sample(CREW_EMBLEMS, len(GANG_NAMES))
    world["botCrewEmblems"] = dict(zip(GANG_NAMES, available))


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
    )


def produce_sell_value(guns, cadillacs, armored_trucks, meds_stock, coke):
    """Sell value of everything factories actually produce - guns, cars/
    trucks, safety kits and cocaine, all at their real dealer/black-market
    sell prices. Bombs (explosive factory output) and counterfeit's raw
    cash aren't sellable inventory, so those factory types only contribute
    via factory_sell_value above."""
    guns_value = sum(
        (guns or {}).get(gun_key, 0) * price
        for gun_key, price in BOT_REINVEST_GUN_PRICES.items()
    )
    vehicles_value = (cadillacs or 0) * BOT_REINVEST_CAR_PRICE + (armored_trucks or 0) * BOT_TRUCK_SELL_PRICE
    meds_value = (meds_stock or 0) * BLACKMARKET_BY_KEY["meds"]["price"]
    coke_value = (coke or 0) * DOPE_DEALER_BY_ID["coke"]["baseSellPrice"]
    return guns_value + vehicles_value + meds_value + coke_value


def bot_net_worth(bot):
    """Net worth is what everything would actually sell for right now -
    factories at their sell/refund price, plus produce (guns, cars/trucks,
    meds) at market sell price. Bots don't have drug factories, so no
    cocaine term here."""
    f = bot.get("factories", {})
    return (
        factory_sell_value(f)
        + produce_sell_value(bot.get("guns"), bot.get("cadillacs"), bot.get("armoredTrucks"), None, None)
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
    elif attacker_gun_score == 0 and defender_gun_score > 0:
        won = False
    else:
        attacker_mult = 1 + attacker_gun_score / max(1, attacker["thugs"])
        defender_mult = 1 + defender_gun_score / max(1, defender["thugs"])
        attacker_power = attacker["thugs"] * attacker_mult * (0.85 + random.random() * 0.3)
        defender_power = defender["thugs"] * defender_mult * (0.85 + random.random() * 0.3)
        won = attacker_power >= defender_power

    if won:
        cash_cut = 0.15 + random.random() * 0.2
        cash_won = jround(defender["hoeCash"] * cash_cut)
        defender["hoeCash"] = max(0, defender["hoeCash"] - cash_won)
        attacker["hoeCash"] += cash_won

        thugs_wiped = defender["thugs"]
        hospital_pct = ATTACK_HOSPITAL_PCT_MIN + random.random() * (ATTACK_HOSPITAL_PCT_MAX - ATTACK_HOSPITAL_PCT_MIN)
        thugs_hospitalized = jround(thugs_wiped * hospital_pct)
        defender["thugs"] = 0
        defender["thugsInHospital"] = defender.get("thugsInHospital", 0) + thugs_hospitalized
        defender["thugsHospitalReadyAt"] = now + ATTACK_HOSPITAL_RECOVERY_MS

        your_thugs_lost_pct = 0.85 + random.random() * 0.08
        your_thugs_lost = min(attacker["thugs"], jround(thugs_wiped * your_thugs_lost_pct))
        attacker["thugs"] = max(0, attacker["thugs"] - your_thugs_lost)
    else:
        thugs_lost_pct = 0.1 + random.random() * 0.15
        thugs_lost = jround(attacker["thugs"] * thugs_lost_pct)
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


# Bots keep this much cash on hand as walking-around money; the rest gets
# plowed into new factories every tick (see bot_reinvest_cash).
CASH_REINVEST_FLOOR = 20000


def bot_reinvest_cash(b, arch):
    """Net worth is purely factory-based now, so a bot that just stockpiles
    cash never climbs the leaderboard no matter how much it earns. Every bot
    plows its surplus cash (above CASH_REINVEST_FLOOR) into new factories
    every tick, buying as many as the surplus allows - moguls reinvest most
    aggressively, sharks least, using the same reinvestRate already used for
    hoeCash."""
    surplus = b["cash"] - CASH_REINVEST_FLOOR
    if surplus <= 0:
        return
    spend = jround(surplus * arch["reinvestRate"])
    affordable = [ft for ft in BOT_FACTORY_TYPES if FACTORY_COSTS[ft] <= spend]
    while affordable:
        choice = random.choice(affordable)
        cost = FACTORY_COSTS[choice]
        spend -= cost
        b["cash"] -= cost
        b["factories"][choice] = b["factories"].get(choice, 0) + 1
        affordable = [ft for ft in BOT_FACTORY_TYPES if FACTORY_COSTS[ft] <= spend]


BOT_TRUCK_SELL_PRICE = 18000


def bot_sell_surplus_produce(b):
    """Bots sell off produce they don't need. Guns beyond one-per-thug are
    dead stock (gun_score caps combat power there anyway), so the excess -
    worst weapons first, keeping the best for actual combat - gets sold for
    cash. Cadillacs and armored trucks don't count toward net worth or
    combat at all any more, so the whole fleet gets liquidated every tick.
    Proceeds land in `cash` and get plowed into more factories next via
    bot_reinvest_cash."""
    guns = b.get("guns", {})
    surplus = sum(guns.values()) - b.get("thugs", 0)
    for gun_key in ("pistol9mm", "shotgun12gauge", "ak47", "m249"):
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
    if cadillacs > 0:
        b["cash"] = b.get("cash", 0) + cadillacs * BOT_REINVEST_CAR_PRICE
        b["cadillacs"] = 0

    trucks = b.get("armoredTrucks", 0)
    if trucks > 0:
        b["cash"] = b.get("cash", 0) + trucks * BOT_TRUCK_SELL_PRICE
        b["armoredTrucks"] = 0


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
            b["cash"] += jround(hoe_earnings * 0.2 * arch["cashRate"])

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
            # recovery) - but never against their own crew. Every archetype
            # has a baseline chance; sharks (and enforcers, a bit) run hotter.
            attack_chance = max(BOT_BASE_ATTACK_CHANCE, arch["raidChance"])
            if random.random() < attack_chance:
                targets = [ob for ob in world["bots"] if ob["id"] != b["id"] and ob["city"] == b["city"] and ob["gang"] != b["gang"]]
                if targets:
                    bot_attack_bot(b, random.choice(targets), now)

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


GLOBAL_ATTACK_LOG_MAX = 50


def log_attack(world, attacker_name, attacker_gang, attacker_emblem, defender_name, defender_gang, defender_emblem):
    """Global, world-shared feed of every real attack (any player hitting
    any bot or player) - visible to everyone, unlike the private per-player
    log. Bot-vs-bot skirmishes don't get logged here, only ones a real
    player actually launched."""
    log = world.setdefault("globalAttackLog", [])
    log.append({
        "t": now_ms(),
        "attacker": attacker_name, "attackerGang": attacker_gang or "", "attackerEmblem": attacker_emblem or "",
        "defender": defender_name, "defenderGang": defender_gang or "", "defenderEmblem": defender_emblem or "",
    })
    if len(log) > GLOBAL_ATTACK_LOG_MAX:
        world["globalAttackLog"] = log[-GLOBAL_ATTACK_LOG_MAX:]


# Caps repeat hits on the same target so one player can't farm another
# (or an alt) over and over in a short window. Keyed per-attacker-per-target
# inside the attacker's own state, so it never affects anyone else's ability
# to attack that same target.
ATTACK_RATE_LIMIT_COUNT = 10
ATTACK_RATE_LIMIT_WINDOW_MS = 15 * 60 * 1000


def check_attack_rate_limit(state, target_id, target_name=None):
    now = now_ms()
    history = state.setdefault("attackHistory", {})
    key = str(target_id)
    recent = [t for t in history.get(key, []) if now - t < ATTACK_RATE_LIMIT_WINDOW_MS]
    if len(recent) >= ATTACK_RATE_LIMIT_COUNT:
        wait_min = math.ceil((ATTACK_RATE_LIMIT_WINDOW_MS - (now - min(recent))) / 60000)
        who = target_name or "this target"
        raise GameError(f"You've hit {who} too many times recently — try again in {wait_min} min")
    recent.append(now)
    history[key] = recent


def fight_bot(state, bot_id, world):
    if state["location"] == "London":
        raise GameError("You can't attack anyone at home turf")
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
        # An unarmed crew loses outright, no matter how many thugs they field
        won = True
    elif your_gun_score == 0 and their_gun_score > 0:
        won = False
    else:
        # Both armed (or both unarmed) - guns still add to your effective
        # power per thug, on top of the usual thug-count/morale comparison
        your_gun_mult = 1 + your_gun_score / max(1, state["thugs"])
        their_gun_mult = 1 + their_gun_score / max(1, bot["thugs"])
        your_power = state["thugs"] * your_gun_mult * thug_morale_mult(state) * (0.85 + random.random() * 0.3)
        their_power = bot["thugs"] * their_gun_mult * (0.85 + random.random() * 0.3)
        won = your_power >= their_power

    if won:
        hoe_cash_cut = 0.2 + random.random() * 0.25
        cash_won = jround(bot["hoeCash"] * hoe_cash_cut)
        bot["hoeCash"] = max(0, bot["hoeCash"] - cash_won)
        state["cash"] += cash_won

        # A win wipes the defender's whole crew - most are dead/scattered
        # for good, but a chunk just got hospitalized and walks back in
        # after ATTACK_HOSPITAL_RECOVERY_MS.
        thugs_wiped = bot["thugs"]
        hospital_pct = ATTACK_HOSPITAL_PCT_MIN + random.random() * (ATTACK_HOSPITAL_PCT_MAX - ATTACK_HOSPITAL_PCT_MIN)
        thugs_hospitalized = jround(thugs_wiped * hospital_pct)
        bot["thugs"] = 0
        bot["thugsInHospital"] = bot.get("thugsInHospital", 0) + thugs_hospitalized
        bot["thugsHospitalReadyAt"] = now + ATTACK_HOSPITAL_RECOVERY_MS

        # Winning isn't free - they get shots off before going down. Your
        # losses scale off how big THEIR crew was (~89% of it), not yours -
        # attacking a bigger crew costs you more, even in a win.
        your_thugs_lost_pct = 0.85 + random.random() * 0.08
        your_thugs_lost = min(state["thugs"], jround(thugs_wiped * your_thugs_lost_pct))
        state["thugs"] = max(0, state["thugs"] - your_thugs_lost)

        add_log(state, f"You hit {bot['boss']} of \"{bot['gang']}\" for £{cash_won} and wiped out {thugs_wiped} thugs ({thugs_hospitalized} hospitalized, the rest gone for good). Their crew fired back before going down, killing {your_thugs_lost} of your thugs.", "good")
        recalc_morale(state)
        return {"won": True, "cashWon": cash_won, "thugsWiped": thugs_wiped, "thugsHospitalized": thugs_hospitalized, "yourThugsLost": your_thugs_lost, "boss": bot["boss"], "gang": bot["gang"]}
    else:
        thugs_lost_pct = 0.1 + random.random() * 0.15
        cash_lost_amt = jround(state["cash"] * (0.05 + random.random() * 0.1))
        thugs_lost = jround(state["thugs"] * thugs_lost_pct)
        state["thugs"] = max(0, state["thugs"] - thugs_lost)
        state["cash"] = max(0, state["cash"] - cash_lost_amt)
        add_log(state, f"Attacked by {bot['boss']} of \"{bot['gang']}\" — they took £{cash_lost_amt} and {thugs_lost} thugs.", "bad")
        recalc_morale(state)
        return {"won": False, "cashLost": cash_lost_amt, "thugsLost": thugs_lost, "boss": bot["boss"], "gang": bot["gang"]}


# Deliberately steep - one explosive factory produces ~50 bombs per 30-min
# tick, so these costs are meant to take multiple ticks of pure stockpiling
# to afford even a single hit, not let one bombing run wipe out a bot's
# whole factory portfolio in one sitting. "drug" only ever shows up on real
# player targets - bots never build drug factories.
BOMB_COST_BY_FACTORY = {"medical": 30, "gun": 75, "car": 120, "drug": 135, "explosive": 150, "counterfeit": 450}


def bomb_bot(state, bot_id, factory_type, world):
    """Blind by holdings, not by type: you pick which kind of factory to
    hit (medical/gun/car/etc) without ever being shown how many of anything
    they actually own. Whichever type you choose, every factory of that type
    gets wiped in one strike - cost is however many they turn out to have,
    times that type's per-unit tier cost."""
    if factory_type not in BOMB_COST_BY_FACTORY:
        raise GameError("Invalid factory type")
    bot = next((b for b in world["bots"] if b["id"] == bot_id), None)
    if not bot:
        raise GameError("Target not found")
    if bot["thugs"] > 0:
        raise GameError("Target still has thugs guarding it")
    owned = bot["factories"].get(factory_type, 0)
    if owned <= 0:
        raise GameError(f"They have no {factory_type} factories")
    cost = BOMB_COST_BY_FACTORY[factory_type] * owned
    if state["bombs"] < cost:
        raise GameError(f"Need {cost} bombs to wipe out their {factory_type} factories")
    state["bombs"] -= cost
    bot["factories"][factory_type] = 0
    add_log(state, f"You spent {cost} bombs wiping out every {factory_type} factory {bot['boss']} owned.", "good")
    return {"boss": bot["boss"], "target": factory_type, "bombsSpent": cost}


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
    its unprotected, raidable pot and `cash` is what funds factories - for a
    human, that's `cash` (raidable) and `bank` (protected) respectively."""
    return {
        "id": HUMAN_ID_OFFSET + user_id,
        "isHuman": True,
        "userId": user_id,
        "boss": pimp_name,
        "gang": s.get("gang") or "",
        "archetype": "human",
        "city": s.get("location", "London"),
        "thugs": s.get("thugs", 0),
        "thugNames": [],
        "hoes": s.get("hoes", 0),
        "hoeNames": [],
        "cash": s.get("bank", 0),
        "hoeCash": s.get("cash", 0),
        "thugMorale": s.get("thugMorale", 50),
        "hoeMorale": s.get("hoeMorale", 50),
        "guns": s.get("guns", {}),
        "cadillacs": s.get("cadillacs", 0),
        "armoredTrucks": s.get("armoredTrucks", 0),
        "factories": s.get("factories", {}),
        "thugsInHospital": s.get("thugsInHospital", 0),
        "thugsHospitalReadyAt": s.get("thugsHospitalReadyAt", 0),
    }


def fight_human(state, defender, world, defender_target_id=None):
    """Attack another real player. Mirrors fight_bot exactly, but the
    raidable pot is the defender's liquid `cash` (their `bank` stays
    protected, same as a bot's `cash` staying untouched while `hoeCash`
    gets raided)."""
    if state["location"] == "London":
        raise GameError("You can't attack anyone at home turf")
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

    if won:
        cash_cut = 0.2 + random.random() * 0.25
        cash_won = jround(defender["cash"] * cash_cut)
        defender["cash"] = max(0, defender["cash"] - cash_won)
        state["cash"] += cash_won

        thugs_wiped = defender["thugs"]
        hospital_pct = ATTACK_HOSPITAL_PCT_MIN + random.random() * (ATTACK_HOSPITAL_PCT_MAX - ATTACK_HOSPITAL_PCT_MIN)
        thugs_hospitalized = jround(thugs_wiped * hospital_pct)
        defender["thugs"] = 0
        defender["thugsInHospital"] = defender.get("thugsInHospital", 0) + thugs_hospitalized
        defender["thugsHospitalReadyAt"] = now + ATTACK_HOSPITAL_RECOVERY_MS

        your_thugs_lost_pct = 0.85 + random.random() * 0.08
        your_thugs_lost = min(state["thugs"], jround(thugs_wiped * your_thugs_lost_pct))
        state["thugs"] = max(0, state["thugs"] - your_thugs_lost)

        add_log(state, f"You hit {defender['name']} for £{cash_won} and wiped out {thugs_wiped} thugs ({thugs_hospitalized} hospitalized, the rest gone for good). They fired back before going down, killing {your_thugs_lost} of your thugs.", "good")
        add_log(defender, f"{state['name']} hit you for £{cash_won} and wiped out {thugs_wiped} of your thugs ({thugs_hospitalized} hospitalized).", "bad")
        recalc_morale(state)
        recalc_morale(defender)
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
        return {"won": False, "cashLost": cash_lost_amt, "thugsLost": thugs_lost, "boss": defender["name"], "gang": defender.get("gang", "")}


def bomb_human(state, defender, factory_type):
    """Same type-targeted strike as bomb_bot, for a real player."""
    if factory_type not in BOMB_COST_BY_FACTORY:
        raise GameError("Invalid factory type")
    if defender["thugs"] > 0:
        raise GameError("Target still has thugs guarding it")
    owned = defender["factories"].get(factory_type, 0)
    if owned <= 0:
        raise GameError(f"They have no {factory_type} factories")
    cost = BOMB_COST_BY_FACTORY[factory_type] * owned
    if state["bombs"] < cost:
        raise GameError(f"Need {cost} bombs to wipe out their {factory_type} factories")
    state["bombs"] -= cost
    defender["factories"][factory_type] = 0

    # Blow up someone's explosive factories and their whole bomb stockpile
    # goes with it - there's nowhere else those bombs were being kept.
    bombs_destroyed = 0
    if factory_type == "explosive":
        bombs_destroyed = defender.get("bombs", 0)
        defender["bombs"] = 0

    add_log(state, f"You spent {cost} bombs wiping out every {factory_type} factory {defender['name']} owned"
                   + (f", destroying their {bombs_destroyed} stockpiled bombs with it" if bombs_destroyed else "") + ".", "good")
    add_log(defender, f"{state['name']} wiped out all of your {factory_type} factories with a bombing run"
                       + (f", taking your {bombs_destroyed} stockpiled bombs with it" if bombs_destroyed else "") + ".", "bad")
    return {"boss": defender["name"], "target": factory_type, "bombsSpent": cost, "bombsDestroyed": bombs_destroyed}


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
        "boss": defender["name"], "gang": defender.get("gang", ""), "city": defender.get("location", ""),
        "cost": cost, "netWorth": nw,
        "cash": defender["cash"], "bank": defender["bank"],
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
    """Net worth is what everything would actually sell for right now -
    factories at their sell/refund price, plus produce (guns, cars/trucks,
    meds, cocaine) at market sell price. Cash, workforce (thugs/hoes) and
    bombs still don't count at all."""
    f = state["factories"]
    return (
        factory_sell_value(f)
        + produce_sell_value(
            state.get("guns"), state.get("cadillacs"), state.get("armoredTrucks"),
            state.get("medsStock"), (state.get("drugs") or {}).get("coke"),
        )
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
    cost = jround(state["hoes"] * 15)
    if state["cash"] < cost:
        raise GameError("Not enough cash")
    state["cash"] -= cost
    state["bribeActiveUntil"] = now + BRIBE_DURATION_MS
    state["bribeCooldownUntil"] = now + BRIBE_COOLDOWN_MS
    add_log(state, f"Paid £{cost} to keep the cops off your back for 5 minutes.", "good")
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

    distribute_earnings(state, cash_gain, turns)
    state["cash"] += cash_gain
    add_hoes(state, hoes_gain)
    state["thugs"] += thugs_gain
    state["thugs"] = max(0, state["thugs"] - thugs_lost)

    if state["gunsStock"] > 0:
        state["gunsStock"] -= 1

    recalc_morale(state)

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
# Banking
# ---------------------------------------------------------------------------

def bank_cash(state, amt):
    now = now_ms()
    if now < state["bankLockedUntil"]:
        raise GameError("Bank is locked right now")
    amt = min(amt, state["cash"])
    if amt <= 0:
        raise GameError("Nothing to deposit")
    fee = jround(amt * 0.05)
    deposited = amt - fee
    state["cash"] -= amt
    state["bank"] += deposited
    return {"deposited": deposited, "fee": fee}


def withdraw_cash(state, amt):
    amt = min(amt, state["bank"])
    if amt <= 0:
        raise GameError("Nothing to withdraw")
    fee = jround(amt * 0.10)
    received = amt - fee
    state["bank"] -= amt
    state["cash"] += received
    return {"received": received, "fee": fee}


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
    return {"qty": qty, "price": price, "payout": payout}


def sell_all_cocaine(state):
    """Sell the entire cocaine stash to the current city's dealer (safe, guaranteed)."""
    qty = state["drugs"].get("coke", 0)
    if qty < 1:
        raise GameError("No cocaine to sell")
    result = sell_drugs(state, "coke", qty)
    add_log(state, f"Sold all {qty} cocaine to the dealer for £{result['totalEarnings']}.", "good")
    return {"qty": qty, "price": result["price"], "payout": result["totalEarnings"]}


COCAINE_OVERSEAS_SUCCESS_CHANCE = 0.65  # 35% bust chance at customs
COCAINE_OVERSEAS_PREMIUM = 1.30


def sell_cocaine_overseas(state):
    """High risk / high reward: ship the whole cocaine stash overseas. 70%
    chance of selling at dealer price + 30%; 30% chance customs catches the
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
        return {"success": True, "qty": qty, "price": jround(overseas_price), "payout": payout}
    else:
        add_log(state, f"Customs busted your overseas shipment of {qty} cocaine. Total loss — got nothing.", "bad")
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
    return {"qty": qty, "price": price, "payout": payout}


def run_factories(state, ticks):
    if ticks < 1:
        return
    f = state["factories"]
    any_factories = any(f.get(k, 0) > 0 for k in ("medical", "gun", "car", "drug", "explosive", "counterfeit"))
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
        state["cash"] += counterfeit_cash


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

    state["turns"] -= job["turnCost"]
    won = random.random() < (job["successChance"] + (state["thugMorale"] / 100) * 0.08)

    if won:
        cash_won = jround(job["minCash"] + random.random() * (job["maxCash"] - job["minCash"]))
        lo, hi = job["casualtyPct"]
        pct = lo + random.random() * (hi - lo)
        thugs_lost = max(0, jround(state["thugs"] * pct))
        state["cash"] += cash_won
        state["thugs"] = max(0, state["thugs"] - thugs_lost)
        add_log(state, f"{job_id.title()} heist scored £{cash_won}! Lost {thugs_lost} thugs.", "good")
        recalc_morale(state)
        return {"won": True, "cashWon": cash_won, "thugsLost": thugs_lost}
    else:
        lo, hi = job["failCasualtyPct"]
        pct = lo + random.random() * (hi - lo)
        thugs_lost = max(1, jround(state["thugs"] * pct))
        state["thugs"] = max(0, state["thugs"] - thugs_lost)
        add_log(state, f"{job_id.title()} heist failed! Lost {thugs_lost} thugs.", "bad")
        recalc_morale(state)
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
        total_cash = jround(job["minCash"] + random.random() * (job["maxCash"] - job["minCash"]))
        player_share = jround(total_cash * 0.60)
        crew_share_per_member = jround(total_cash * 0.40 / crew_size)
        state["cash"] += player_share
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
        return {"won": True, "playerShare": player_share, "thugsLost": thugs_lost}
    else:
        lo, hi = job["failCasualtyPct"]
        pct = lo + random.random() * (hi - lo)
        thugs_lost = max(crew_size, jround(thugs_needed * pct))
        state["thugs"] = max(0, state["thugs"] + thugs_needed - thugs_lost)
        add_log(state, "Casino heist failed badly.", "bad")
        recalc_morale(state)
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
    state["drugBoughtAt"][f"{city}_{drug_id}"] = now_ms()
    state["drugsPaidPrice"][drug_id] = price
    return {"totalCost": total_cost, "price": price}


def sell_drugs(state, drug_id, qty):
    have = state["drugs"].get(drug_id, 0)
    if qty < 1 or qty > have:
        raise GameError("Not enough to sell")
    city = state["location"]
    bought_at = state["drugBoughtAt"].get(f"{city}_{drug_id}", 0)
    if bought_at > 0 and (now_ms() - bought_at) < DEALER_RESALE_COOLDOWN_MS:
        raise GameError("Prices haven't moved yet - wait a bit")
    price = get_dealer_price(state, city, drug_id, True)
    total_earnings = price * qty
    state["drugs"][drug_id] -= qty
    state["cash"] += total_earnings
    return {"totalEarnings": total_earnings, "price": price}


# ---------------------------------------------------------------------------
# Store / black market
# ---------------------------------------------------------------------------

def _find_store_item(group, item_id):
    for item in STORE_ITEMS.get(group, []):
        if item["id"] == item_id:
            return item
    return None


def buy_store_item(state, group, item_id, qty):
    item = _find_store_item(group, item_id)
    if not item:
        raise GameError("Invalid item")
    afford = state["cash"] // item["cost"]
    qty = max(0, min(qty, afford))
    if qty < 1:
        raise GameError("Can't afford that")

    total_cost = qty * item["cost"]
    state["cash"] -= total_cost

    if group == "girls" and item_id == "condoms":
        state["medsStock"] += qty
    elif group == "thugs" and item_id == "cadillac":
        state["cadillacs"] += qty
    elif group == "weapons":
        state["guns"][item_id] = state["guns"].get(item_id, 0) + qty
        state["gunsOwned"] = state.get("gunsOwned", 0) + qty
    else:
        raise GameError("Invalid item")

    recalc_morale(state)
    return {"totalCost": total_cost}


def _market_current_price(state, item):
    if item["key"] == "thugs":
        return 90
    mult = state["market"].get(item["key"], {"mult": 1.0})["mult"]
    return max(1, jround(item["price"] * min(mult, 1.0)))


def thug_buy_price(state):
    """Thugs get pricier the bigger your hoe roster gets - a quadratic
    curve fitted to hit exactly £100 at 0 hoes, £300 at 500 hoes, and
    £1,000 at 1,000 hoes, then keeps climbing the same way beyond that."""
    hoes = state["hoes"]
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


CREW_EMBLEMS = ["🐍", "🦂", "🐺", "💀", "🔥", "👑", "🗡️", "🦅", "🐉", "⚡", "🎩", "♠️"]


def set_crew_emblem(state, emblem, world):
    if state.get("crewLeaderUserId"):
        raise GameError("Only the crew leader can set the emblem")
    if emblem not in CREW_EMBLEMS:
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


def buy_turns_with_real_money(state):
    now = now_ms()
    if now < state["lastRealMoneyPurchase"] + REALMONEY_COOLDOWN_MS:
        raise GameError("On cooldown")
    state["turns"] = min(state["maxTurns"], state["turns"] + REALMONEY_TURNS)
    state["lastRealMoneyPurchase"] = now
    add_log(state, f"Purchased {REALMONEY_TURNS} turns.", "good")


def travel_cost(state, city):
    if city.get("home"):
        return 0
    return max(TRAVEL_BASE_FEE, jround(TRAVEL_COST_PER_THUG * state["thugs"]))


def travel_to(state, city_name):
    city = next((c for c in CITIES if c["name"] == city_name), None)
    if not city:
        raise GameError("Unknown city")
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


def tick_bank_fee(state, now):
    ticks = (now - state["lastBankFeeUpdate"]) // BANK_FEE_MS
    if ticks >= 1:
        if state["bank"] > 0:
            state["bank"] = jround(state["bank"] * ((1 - BANK_FEE_PCT) ** int(ticks)))
        state["lastBankFeeUpdate"] += int(ticks) * BANK_FEE_MS


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
    if "drug" not in state["factories"]:
        state["factories"]["drug"] = 0
    if "thugsInHospital" not in state:
        state["thugsInHospital"] = 0
    if "thugsHospitalReadyAt" not in state:
        state["thugsHospitalReadyAt"] = 0
    if "pendingCrewInvites" not in state:
        state["pendingCrewInvites"] = []
    ensure_hoe_roster(state)
    tick_regen(state, now)
    tick_factories(state, now)
    tick_market(state, now)
    tick_bank_fee(state, now)
    process_human_hospital(state, now)
    check_dealer_reset(state, now)
    check_daily_bonus(state, now)
    recalc_morale(state)
    return state


def apply_world_catchup(world):
    """Run every time-based system forward to `now` for the shared world
    (bots). Call this once per request, independent of which player is
    making it."""
    now = now_ms()
    ensure_bots(world)
    if "globalAttackLog" not in world:
        world["globalAttackLog"] = []
    # One-time migration: bots created before the 4-crew system had unique
    # per-bot gang names. Reassign everyone into the new shared crews
    # without touching any other bot progress.
    if world["bots"] and world["bots"][0].get("gang") not in GANG_NAMES:
        crew_assignments = even_crew_assignments(len(world["bots"]))
        for b, gang in zip(world["bots"], crew_assignments):
            b["gang"] = gang
    regen_bots(world, now)
    process_bot_hospitals(world, now)
    return world
