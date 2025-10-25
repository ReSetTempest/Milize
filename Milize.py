
import discord
from discord.ext import commands, tasks
import asyncio, json, os, random, time, math
from typing import Dict, Any, List, Optional

# ---------------- CONFIG ----------------
BOT_TOKEN = "hidden so discord dosen't nuke it"
if not BOT_TOKEN:
    print("WARNING: DISCORD_TOKEN environment variable not set. Set it before running to avoid runtime error.")

COMMAND_PREFIX = "86!"
INTENTS = discord.Intents.default()
INTENTS.message_content = True

DATA_FILE = "data.json"
FILE_LOCK = asyncio.Lock()

# Cooldowns & windows (seconds)
MISSION_CD = 5 * 60
BOSS_CD = 15 * 60
EVENT_JOIN_WINDOW = 2 * 60
EVENT_PERSONAL_COOLDOWN = 10 * 60

# Rewards / balancing
BASE_MISSION_REWARD = 100
BASE_EXP = 25
SCRAPYARD_MULTIPLIER = 0.5

PAGE_SIZE = 6  # items shown per page in shop/scrapyard

# ---------------- BOT ----------------
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=INTENTS, help_command=None)

# ---------------- DATA IO ----------------
async def load_data() -> Dict[str, Any]:
    async with FILE_LOCK:
        if not os.path.exists(DATA_FILE):
            base = {"meta": {"next_event_id": 1}, "players": {}, "event": None}
            with open(DATA_FILE, "w") as f:
                json.dump(base, f, indent=2)
            return base
        with open(DATA_FILE, "r") as f:
            return json.load(f)

async def save_data(data: Dict[str, Any]):
    async with FILE_LOCK:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)

async def ensure_player(user: discord.User) -> Dict[str, Any]:
    data = await load_data()
    players = data.setdefault("players", {})
    uid = str(user.id)
    if uid not in players:
        players[uid] = {
            "id": user.id,
            "name": user.display_name,
            "level": 1,
            "exp": 0,
            "skill_points": 0,
            "stats": {"attack": 10, "defense": 8, "hp_max": 100},
            "hp": 100,
            "missions": 0,
            "wins": 0,
            "rank": "Private",
            "credits": 500,
            "inventory": {},  # item_id -> {data, count}
            "parts": [],      # equipped parts (list of dicts)
            "juggernaut": "XM2 Base Model",
            "companions": {}, # name -> comp dict
            "last_mission": 0.0,
            "last_boss": 0.0,
            "last_checkin": 0,
            "last_event_attack": 0.0,
            "boss_forced": False
        }
        await save_data(data)
    return players[uid]

async def ensure_player_obj_by_id(uid:int, create_if_missing:bool=False) -> Dict[str,Any]:
    data = await load_data()
    players = data.setdefault("players", {})
    sid = str(uid)
    if sid not in players and create_if_missing:
        players[sid] = {
            "id": uid, "name": str(uid), "level":1,"exp":0,"skill_points":0,
            "stats":{"attack":10,"defense":8,"hp_max":100},"hp":100,"missions":0,"wins":0,"rank":"Private","credits":500,
            "inventory":{},"parts":[],"juggernaut":"XM2 Base Model","companions":{},
            "last_mission":0.0,"last_boss":0.0,"last_checkin":0,"last_event_attack":0.0,"boss_forced":False
        }
        await save_data(data)
    return players.get(sid)

# ---------------- GAME DATA ----------------

SHOP_ITEMS_ORDER = [
 "reactive_armor","enhanced_thrusters","adv_targeting","legion_radar","plasma_cannon",
 "titan_chassis","energy_shield","thermal_reg","sensor_mk2","nano_gel","high_output_reactor",
 "smart_missile","stealth_coat","hydraulic_enh","ai_copilot","control_uplink","composite_layer",
 "emp_defense","ballistic_shield","cooling_mk3","nano_weave","quantum_proc","drone_bay",
 "maneuver_sys","boss_beacon"
]
SHOP_CATALOG: Dict[str, Dict[str, Any]] = {
    "reactive_armor": {"id":"reactive_armor","name":"Reactive Armor Plating","attack":0,"defense":6,"hp":40,"price":1200,"durability":100,"rarity":"rare"},
    "enhanced_thrusters": {"id":"enhanced_thrusters","name":"Enhanced Thrusters","attack":0,"defense":0,"hp":0,"price":1500,"durability":100,"rarity":"rare","speed":5},
    "adv_targeting": {"id":"adv_targeting","name":"Advanced Targeting System","attack":8,"defense":0,"hp":0,"price":2000,"durability":80,"rarity":"epic"},
    "legion_radar": {"id":"legion_radar","name":"Legion Radar Scanner","attack":0,"defense":3,"hp":0,"price":2500,"durability":90,"rarity":"rare"},
    "plasma_cannon": {"id":"plasma_cannon","name":"Plasma Cannon","attack":15,"defense":0,"hp":0,"price":3000,"durability":60,"rarity":"epic"},
    "titan_chassis": {"id":"titan_chassis","name":"Titan Alloy Chassis","attack":0,"defense":10,"hp":80,"price":3500,"durability":120,"rarity":"legendary"},
    "energy_shield": {"id":"energy_shield","name":"Energy Shield Core","attack":0,"defense":12,"hp":30,"price":4000,"durability":100,"rarity":"legendary"},
    "thermal_reg": {"id":"thermal_reg","name":"Thermal Regulator","attack":0,"defense":2,"hp":0,"price":1800,"durability":80,"rarity":"uncommon"},
    "sensor_mk2": {"id":"sensor_mk2","name":"Sensor Suite Mk-II","attack":3,"defense":1,"hp":0,"price":1200,"durability":70,"rarity":"uncommon"},
    "nano_gel": {"id":"nano_gel","name":"Nano Repair Gel","attack":0,"defense":0,"hp":20,"price":900,"durability":1,"rarity":"uncommon"},
    "high_output_reactor": {"id":"high_output_reactor","name":"High-Output Reactor","attack":0,"defense":0,"hp":0,"price":5000,"durability":200,"rarity":"legendary"},
    "smart_missile": {"id":"smart_missile","name":"Smart Missile Pod","attack":18,"defense":0,"hp":0,"price":3800,"durability":60,"rarity":"epic"},
    "stealth_coat": {"id":"stealth_coat","name":"Stealth Coating","attack":0,"defense":4,"hp":0,"price":2800,"durability":70,"rarity":"rare"},
    "hydraulic_enh": {"id":"hydraulic_enh","name":"Hydraulic Enhancer","attack":2,"defense":2,"hp":0,"price":2200,"durability":80,"rarity":"uncommon"},
    "ai_copilot": {"id":"ai_copilot","name":"AI Co-Pilot","attack":5,"defense":3,"hp":0,"price":4500,"durability":120,"rarity":"epic"},
    "control_uplink": {"id":"control_uplink","name":"Juggernaut Control Uplink","attack":3,"defense":0,"hp":0,"price":1500,"durability":90,"rarity":"uncommon"},
    "composite_layer": {"id":"composite_layer","name":"Composite Armor Layer","attack":0,"defense":5,"hp":25,"price":1700,"durability":90,"rarity":"rare"},
    "emp_defense": {"id":"emp_defense","name":"EMP Defense Module","attack":0,"defense":6,"hp":0,"price":2000,"durability":80,"rarity":"rare"},
    "ballistic_shield": {"id":"ballistic_shield","name":"Ballistic Shield Array","attack":0,"defense":8,"hp":30,"price":2100,"durability":90,"rarity":"rare"},
    "cooling_mk3": {"id":"cooling_mk3","name":"Cooling Vents Mk-III","attack":0,"defense":2,"hp":0,"price":1900,"durability":90,"rarity":"uncommon"},
    "nano_weave": {"id":"nano_weave","name":"Nano-Armor Weave","attack":0,"defense":7,"hp":20,"price":2300,"durability":100,"rarity":"rare"},
    "quantum_proc": {"id":"quantum_proc","name":"Quantum Processor","attack":4,"defense":2,"hp":0,"price":4700,"durability":120,"rarity":"legendary"},
    "drone_bay": {"id":"drone_bay","name":"Drone Support Bay","attack":8,"defense":2,"hp":0,"price":5200,"durability":150,"rarity":"legendary"},
    "maneuver_sys": {"id":"maneuver_sys","name":"Advanced Maneuver System","attack":0,"defense":3,"hp":0,"price":2600,"durability":100,"rarity":"rare"},
    "boss_beacon": {"id":"boss_beacon","name":"Boss Beacon","attack":0,"defense":0,"hp":0,"price":8000,"durability":1,"rarity":"legendary"}
}

SCRAP_ITEMS_ORDER = [
 "damaged_armor","old_thruster","cracked_barrel","rusty_shield","used_sensor","leaky_reactor","broken_servo",
 "worn_lens","scratched_panels","bent_gun_mount","overheated_circuit","salvaged_ammo","depleted_cell","corroded_frame",
 "worn_pistons","low_grade_plating","burned_cpu","jammed_rack","defective_actuator","flicker_hud","weak_battery",
 "cracked_glass","loose_bolts","unstable_cartridge","rust_fragment"
]
SCRAPYARD_CATALOG: Dict[str, Dict[str, Any]] = {
    "damaged_armor": {"id":"damaged_armor","name":"Damaged Armor Plate","attack":0,"defense":2,"hp":10,"price":200,"durability":20,"rarity":"common"},
    "old_thruster": {"id":"old_thruster","name":"Old Thruster","attack":0,"defense":0,"hp":0,"price":150,"durability":15,"rarity":"common"},
    "cracked_barrel": {"id":"cracked_barrel","name":"Cracked Cannon Barrel","attack":5,"defense":0,"hp":0,"price":300,"durability":20,"rarity":"common"},
    "rusty_shield": {"id":"rusty_shield","name":"Rusty Shield Generator","attack":0,"defense":1,"hp":0,"price":180,"durability":18,"rarity":"common"},
    "used_sensor": {"id":"used_sensor","name":"Used Sensor Array","attack":1,"defense":0,"hp":0,"price":250,"durability":25,"rarity":"common"},
    "leaky_reactor": {"id":"leaky_reactor","name":"Leaky Reactor Core","attack":0,"defense":0,"hp":0,"price":220,"durability":10,"rarity":"common"},
    "broken_servo": {"id":"broken_servo","name":"Broken Servo","attack":0,"defense":0,"hp":0,"price":100,"durability":10,"rarity":"common"},
    "worn_lens": {"id":"worn_lens","name":"Worn Targeting Lens","attack":2,"defense":0,"hp":0,"price":140,"durability":15,"rarity":"common"},
    "scratched_panels": {"id":"scratched_panels","name":"Scratched Armor Panels","attack":0,"defense":1,"hp":5,"price":130,"durability":18,"rarity":"common"},
    "bent_gun_mount": {"id":"bent_gun_mount","name":"Bent Gun Mount","attack":1,"defense":0,"hp":0,"price":120,"durability":12,"rarity":"common"},
    "overheated_circuit": {"id":"overheated_circuit","name":"Overheated Circuit","attack":0,"defense":0,"hp":0,"price":160,"durability":12,"rarity":"common"},
    "salvaged_ammo": {"id":"salvaged_ammo","name":"Salvaged Ammo Pack","attack":3,"defense":0,"hp":0,"price":240,"durability":25,"rarity":"common"},
    "depleted_cell": {"id":"depleted_cell","name":"Depleted Energy Cell","attack":0,"defense":0,"hp":0,"price":210,"durability":10,"rarity":"common"},
    "corroded_frame": {"id":"corroded_frame","name":"Corroded Frame Piece","attack":0,"defense":1,"hp":5,"price":200,"durability":20,"rarity":"common"},
    "worn_pistons": {"id":"worn_pistons","name":"Worn Leg Pistons","attack":0,"defense":0,"hp":0,"price":230,"durability":20,"rarity":"common"},
    "low_grade_plating": {"id":"low_grade_plating","name":"Low-Grade Plating","attack":0,"defense":1,"hp":5,"price":190,"durability":18,"rarity":"common"},
    "burned_cpu": {"id":"burned_cpu","name":"Burned Out CPU","attack":0,"defense":0,"hp":0,"price":150,"durability":10,"rarity":"common"},
    "jammed_rack": {"id":"jammed_rack","name":"Jammed Missile Rack","attack":4,"defense":0,"hp":0,"price":260,"durability":15,"rarity":"common"},
    "defective_actuator": {"id":"defective_actuator","name":"Defective Actuator","attack":0,"defense":0,"hp":0,"price":270,"durability":12,"rarity":"common"},
    "flicker_hud": {"id":"flicker_hud","name":"Flickering HUD Module","attack":1,"defense":0,"hp":0,"price":180,"durability":15,"rarity":"common"},
    "weak_battery": {"id":"weak_battery","name":"Weak Battery","attack":0,"defense":0,"hp":0,"price":130,"durability":8,"rarity":"common"},
    "cracked_glass": {"id":"cracked_glass","name":"Cracked Cockpit Glass","attack":0,"defense":0,"hp":0,"price":210,"durability":20,"rarity":"common"},
    "loose_bolts": {"id":"loose_bolts","name":"Loose Bolts Set","attack":0,"defense":0,"hp":0,"price":110,"durability":999,"rarity":"common"},
    "unstable_cartridge": {"id":"unstable_cartridge","name":"Unstable Plasma Cartridge","attack":6,"defense":0,"hp":0,"price":250,"durability":6,"rarity":"common"},
    "rust_fragment": {"id":"rust_fragment","name":"Rust Fragment Bundle","attack":0,"defense":0,"hp":0,"price":90,"durability":5,"rarity":"common"}
}

JUGGERNAUT_CONFIGS: Dict[str, Dict[str,int]] = {
    "XM2 Base Model":{"attack":0,"defense":0,"hp":0},
    "XM2 Assault Variant":{"attack":5,"defense":-1,"hp":-10},
    "XM2 Defender Class":{"attack":-2,"defense":6,"hp":20},
    "XM3 Sniper Unit":{"attack":8,"defense":-2,"hp":-15},
    "XM3 Heavy Armor":{"attack":-1,"defense":10,"hp":40},
    "XM3 Recon Scout":{"attack":2,"defense":0,"hp":-20},
    "XM4 Prototype":{"attack":4,"defense":3,"hp":10},
    "XM4 Vanguard":{"attack":6,"defense":2,"hp":5},
    "XM4 Commander":{"attack":7,"defense":4,"hp":10},
    "XM4 Nightshade":{"attack":5,"defense":0,"hp":-5},
    "XM5 Experimental Type":{"attack":10,"defense":-5,"hp":-30},
    "XM5 Long Range":{"attack":9,"defense":-1,"hp":-20},
    "XM5 Aegis Model":{"attack":-3,"defense":12,"hp":50},
    "XM6 Rapid Strike":{"attack":8,"defense":-2,"hp":-10},
    "XM6 Guardian":{"attack":1,"defense":8,"hp":30},
    "XM6 Ghost Unit":{"attack":6,"defense":1,"hp":-10},
    "XM7 Supreme Class":{"attack":12,"defense":10,"hp":80},
    "XM7 Shadow":{"attack":9,"defense":3,"hp":-10},
    "XM7 Paladin":{"attack":0,"defense":15,"hp":60},
    "XM7 Omega Variant":{"attack":15,"defense":5,"hp":40},
    "XM8 Prototype Delta":{"attack":11,"defense":4,"hp":20},
    "XM8 Legion Buster":{"attack":14,"defense":-3,"hp":-10},
    "XM8 Overdrive":{"attack":13,"defense":2,"hp":-5},
    "XM8 Eclipse":{"attack":10,"defense":6,"hp":10},
    "XM9 Sovereign":{"attack":18,"defense":12,"hp":120}
}

RARE_DROPS = [
    {"id":"legendary_blade","name":"Legendary Blade","attack":25,"defense":0,"hp":0,"rarity":"legendary"},
    {"id":"precision_module","name":"Precision Module","attack":15,"defense":5,"hp":0,"rarity":"rare"},
    {"id":"aegis_fragment","name":"Aegis Fragment","attack":0,"defense":12,"hp":30,"rarity":"epic"}
]

# ---------------- UTILITIES ----------------
def exp_to_next(level:int) -> int:
    return 100 + (level-1)*50

def compute_effective_stats(player:Dict[str,Any]) -> Dict[str,int]:
    attack = player["stats"]["attack"]
    defense = player["stats"]["defense"]
    hp_max = player["stats"]["hp_max"]
    for p in player.get("parts", []):
        attack += p.get("attack",0)
        defense += p.get("defense",0)
        hp_max += p.get("hp",0)
    cfg = JUGGERNAUT_CONFIGS.get(player.get("juggernaut","XM2 Base Model"), {})
    attack += cfg.get("attack",0)
    defense += cfg.get("defense",0)
    hp_max += cfg.get("hp",0)
    return {"attack": max(1,int(attack)), "defense": max(0,int(defense)), "hp_max": max(10,int(hp_max))}

async def add_item(player:Dict[str,Any], item:Dict[str,Any], count:int=1):
    inv = player.setdefault("inventory", {})
    iid = item["id"]
    if iid in inv:
        inv[iid]["count"] += count
    else:
        inv[iid] = {"data": item, "count": count}

# ---------------- MISSION / BOSS LOGIC ----------------
async def attempt_mission(player:Dict[str,Any], data:Dict[str,Any]) -> Dict[str,Any]:
    now = time.time()
    if now - player.get("last_mission",0) < MISSION_CD:
        return {"ok":False,"reason":"mission_cd","remaining": int(MISSION_CD - (now - player.get("last_mission",0)))}
    mission_num = player.get("missions",0) + 1
    boss_chance = 0.10
    if mission_num % 5 == 0:
        boss_chance = 0.80
    boss = False
    if player.get("boss_forced", False):
        boss = True
        player["boss_forced"] = False
    else:
        boss = random.random() < boss_chance
    level = player.get("level",1)
    difficulty = 10 + level * 2
    if boss:
        difficulty *= 3
    eff = compute_effective_stats(player)
    score = eff["attack"] * random.uniform(0.8,1.3) + eff["defense"] * random.uniform(0.5,1.0)
    success = score > difficulty
    reward_credits = BASE_MISSION_REWARD + level*10
    reward_exp = BASE_EXP + level*5
    if boss:
        reward_credits *= 3
        reward_exp *= 4
    for p in player.get("parts", []):
        wear = random.randint(1,8)
        p["durability"] = max(0, p.get("durability",0) - wear)
    player["missions"] = player.get("missions",0) + 1
    player["last_mission"] = now
    drop = None
    if success:
        player["wins"] = player.get("wins",0) + 1
        player["credits"] = player.get("credits",0) + int(reward_credits)
        player["exp"] = player.get("exp",0) + int(reward_exp)
        if boss and random.random() < 0.35:
            drop = random.choice(RARE_DROPS)
            await add_item(player, drop, 1)
        elif not boss and random.random() < 0.10:
            drop = random.choice(RARE_DROPS)
            await add_item(player, drop, 1)
    else:
        player["hp"] = max(0, player.get("hp", eff["hp_max"]) - random.randint(5,25))
        player["credits"] = max(0, player.get("credits",0) - int(reward_credits*0.2))
    leveled = False
    while player.get("exp",0) >= exp_to_next(player.get("level",1)):
        player["exp"] -= exp_to_next(player.get("level",1))
        player["level"] += 1
        player["skill_points"] += 2
        leveled = True
    lvl = player.get("level",1)
    if lvl >= 10:
        player["rank"] = "Captain"
    elif lvl >= 6:
        player["rank"] = "Sergeant"
    else:
        player["rank"] = "Private"
    return {"ok":True,"success":success,"boss":boss,"credits":int(reward_credits),"exp":int(reward_exp),"drop":drop,"leveled":leveled}

# ---------------- EVENT SYSTEM (GLOBAL) ----------------
async def start_event(data:Dict[str,Any], hp:int=5000, title:str="Event Legion Overlord") -> Dict[str,Any]:
    eid = data.setdefault("meta", {}).get("next_event_id",1)
    data["meta"]["next_event_id"] = eid + 1
    event = {
        "id": eid,
        "name": title,
        "hp": hp,
        "max_hp": hp,
        "started_at": time.time(),
        "join_deadline": time.time() + EVENT_JOIN_WINDOW,
        "attack_deadline": time.time() + EVENT_JOIN_WINDOW,
        "participants": {}, # uid -> {"joined_at":..., "attacked_at":...}
        "active": True
    }
    data["event"] = event
    await save_data(data)
    return event

async def join_event(user:discord.User) -> Dict[str,Any]:
    data = await load_data()
    event = data.get("event")
    now = time.time()
    if not event or not event.get("active"):
        return {"ok":False,"reason":"no_event"}
    if now > event.get("join_deadline",0):
        return {"ok":False,"reason":"join_closed"}
    uid = str(user.id)
    event.setdefault("participants", {})[uid] = {"joined_at": now, "attacked_at": 0.0}
    await save_data(data)
    return {"ok":True,"event":event}

async def attack_event(user:discord.User) -> Dict[str,Any]:
    data = await load_data()
    event = data.get("event")
    now = time.time()
    if not event or not event.get("active"):
        return {"ok":False,"reason":"no_event"}
    if now > event.get("attack_deadline",0):
        return {"ok":False,"reason":"attack_window_closed"}
    uid = str(user.id)
    if uid not in event.get("participants", {}):
        return {"ok":False,"reason":"not_joined"}
    player = await ensure_player(user)
    if now - player.get("last_event_attack",0) < EVENT_PERSONAL_COOLDOWN:
        return {"ok":False,"reason":"personal_cd","remaining": int(EVENT_PERSONAL_COOLDOWN - (now - player.get("last_event_attack",0)))}
    eff = compute_effective_stats(player)
    damage = int(eff["attack"] * random.uniform(1.0,2.5))
    comp_dmg = 0
    for comp in player.get("companions", {}).values():
        comp_dmg += comp.get("attack",0) * 0.5
    damage += int(comp_dmg)
    event["hp"] = max(0, event["hp"] - damage)
    event["participants"].setdefault(uid, {})["attacked_at"] = now
    player["last_event_attack"] = now
    player["credits"] = player.get("credits",0) + int(damage * 0.3)
    await save_data(data)
    killed = event["hp"] <= 0
    drops = []
    if killed:
        for part_uid in list(event["participants"].keys()):
            pid = int(part_uid)
            p = await ensure_player_obj_by_id(pid, create_if_missing=True)
            p["credits"] = p.get("credits",0) + 500
            p["exp"] = p.get("exp",0) + 200
            if random.random() < 0.3:
                drop = random.choice(RARE_DROPS)
                await add_item(p, drop, 1)
                drops.append({"uid":part_uid,"drop":drop})
        event["active"] = False
        await save_data(data)
        return {"ok":True,"damage":damage,"killed":True,"drops":drops}
    await save_data(data)
    return {"ok":True,"damage":damage,"killed":False}

# ---------------- UI / VIEWS ----------------
class StoreView(discord.ui.View):
    def __init__(self, ctx:commands.Context, keys:List[str], catalog:Dict[str,Any], title:str):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.keys = keys
        self.catalog = catalog
        self.page = 0
        self.title = title

    def get_page_count(self) -> int:
        return max(1, math.ceil(len(self.keys) / PAGE_SIZE))

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title=self.title, color=0x224466)
        start = self.page * PAGE_SIZE
        for i in range(PAGE_SIZE):
            idx = start + i
            if idx >= len(self.keys):
                break
            key = self.keys[idx]
            item = self.catalog[key]
            price = item["price"]
            if self.catalog is SCRAPYARD_CATALOG:
                price = int(item["price"] * SCRAPYARD_MULTIPLIER)
            embed.add_field(name=f"{idx+1}. {item['name']}", value=f"Price: {price} — ATK {item.get('attack',0)} DEF {item.get('defense',0)} HP {item.get('hp',0)} Dur: {item.get('durability',0)} Rarity: {item.get('rarity','')}", inline=False)
        embed.set_footer(text=f"Page {self.page+1}/{self.get_page_count()} • Press Buy then reply with item number to purchase.")
        return embed

    async def interaction_check(self, interaction:discord.Interaction) -> bool:
        return interaction.user.id == self.ctx.author.id

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction:discord.Interaction, button:discord.ui.Button):
        self.page = max(0, self.page - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction:discord.Interaction, button:discord.ui.Button):
        self.page = min(self.get_page_count()-1, self.page + 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Buy", style=discord.ButtonStyle.success)
    async def buy(self, interaction:discord.Interaction, button:discord.ui.Button):
        await interaction.response.send_message("Reply in chat with the item number to buy (visible to you for 30s).", ephemeral=True)
        def check(m):
            return m.author.id == self.ctx.author.id and m.channel == self.ctx.channel
        try:
            msg = await bot.wait_for('message', check=check, timeout=30)
        except asyncio.TimeoutError:
            await interaction.followup.send("Timed out.", ephemeral=True)
            return
        try:
            idx = int(msg.content.strip()) - 1
        except:
            await interaction.followup.send("Invalid number.", ephemeral=True)
            return
        if idx < 0 or idx >= len(self.keys):
            await interaction.followup.send("Number out of range.", ephemeral=True)
            return
        key = self.keys[idx]
        item = self.catalog[key]
        price = item["price"] if self.catalog is SHOP_CATALOG else int(item["price"] * SCRAPYARD_MULTIPLIER)
        player = await ensure_player(self.ctx.author)
        if player.get("credits",0) < price:
            await interaction.followup.send(f"Insufficient credits (need {price}).", ephemeral=True)
            return
        player["credits"] -= price
        part_copy = dict(item)
        if self.catalog is SCRAPYARD_CATALOG:
            part_copy["durability"] = max(1, int(part_copy.get("durability",50) * 0.5))
        player.setdefault("parts", []).append(part_copy)
        data = await load_data()
        data["players"][str(self.ctx.author.id)] = player
        await save_data(data)
        await interaction.followup.send(f"Purchased and equipped {item['name']} for {price} credits.", ephemeral=True)
        await interaction.message.edit(embed=self.build_embed(), view=self)

class HangarView(discord.ui.View):
    def __init__(self, ctx:commands.Context, player:Dict[str,Any]):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.player = player

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title="Hangar — Repair Bay", color=0x446622)
        parts = self.player.get("parts", [])
        if not parts:
            embed.description = "No parts equipped."
            return embed
        for i,p in enumerate(parts):
            embed.add_field(name=f"[{i}] {p.get('name')}", value=f"Dur: {p.get('durability',0)} ATK {p.get('attack',0)} DEF {p.get('defense',0)} HP {p.get('hp',0)}", inline=False)
        embed.set_footer(text="Press Repair then reply with part index to repair (cost scales with damage).")
        return embed

    @discord.ui.button(label="Repair", style=discord.ButtonStyle.primary)
    async def repair(self, interaction:discord.Interaction, button:discord.ui.Button):
        await interaction.response.send_message("Reply in chat with the part index to repair (30s).", ephemeral=True)
        def check(m): return m.author.id == self.ctx.author.id and m.channel == self.ctx.channel
        try:
            msg = await bot.wait_for('message', check=check, timeout=30)
        except asyncio.TimeoutError:
            await interaction.followup.send("Timed out.", ephemeral=True)
            return
        try:
            idx = int(msg.content.strip())
        except:
            await interaction.followup.send("Invalid index.", ephemeral=True)
            return
        parts = self.player.get("parts", [])
        if idx < 0 or idx >= len(parts):
            await interaction.followup.send("Index out of range.", ephemeral=True)
            return
        part = parts[idx]
        missing = 100 - part.get("durability",0)
        cost = max(50, missing * 5)
        if self.player.get("credits",0) < cost:
            await interaction.followup.send(f"Not enough credits. Need {cost}.", ephemeral=True)
            return
        self.player["credits"] -= cost
        part["durability"] = 100
        data = await load_data()
        data["players"][str(self.ctx.author.id)] = self.player
        await save_data(data)
        await interaction.followup.send(f"Repaired {part.get('name')} for {cost} credits.", ephemeral=True)
        await interaction.message.edit(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction:discord.Interaction, button:discord.ui.Button):
        await interaction.message.delete()
        self.stop()

class EventView(discord.ui.View):
    def __init__(self, ctx:commands.Context):
        super().__init__(timeout=EVENT_JOIN_WINDOW + 10)
        self.ctx = ctx

    @discord.ui.button(label="Join Event", style=discord.ButtonStyle.primary)
    async def join_btn(self, interaction:discord.Interaction, button:discord.ui.Button):
        res = await join_event(interaction.user)
        if not res.get("ok"):
            await interaction.response.send_message(f"Could not join: {res.get('reason')}", ephemeral=True)
            return
        await interaction.response.send_message("Joined event. Use 'Attack Event' to deal damage during the window.", ephemeral=True)

    @discord.ui.button(label="Attack Event", style=discord.ButtonStyle.danger)
    async def attack_btn(self, interaction:discord.Interaction, button:discord.ui.Button):
        res = await attack_event(interaction.user)
        if not res.get("ok"):
            await interaction.response.send_message(f"Could not attack: {res.get('reason')}", ephemeral=True)
            return
        if res.get("killed"):
            await interaction.response.send_message(f"You dealt {res['damage']} damage and killed the event boss. Rewards distributed.", ephemeral=True)
        else:
            await interaction.response.send_message(f"You dealt {res['damage']} damage to the event boss.", ephemeral=True)

# ---------------- COMMANDS ----------------
@bot.event
async def on_ready():
    print(f"Eighty-Six Bot online as {bot.user}")
    cleanup_tasks.start()

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="🧭 Project 86 — Command Guide", color=0x5865F2, description="Prefix: `86!`\nMilitary tone engaged. Use commands below to interact with the Spearhead systems.")
    embed.add_field(name="Player & Profile", value="`register` — create profile\n`status` — view your status\n`checkin` — daily check-in", inline=False)
    embed.add_field(name="Combat", value="`deploy` — undertake a mission\n`forceboss` — consume Boss Beacon to force a boss mission (if you have one)", inline=False)
    embed.add_field(name="Shops & Gear", value="`86!shop` — premium shop (buttons)\n`86!scrapyard` — cheap salvage (buttons)\n`86!hangar` — repairs (buttons)\n`86!buy <shop|scrap> <index>` — direct buy", inline=False)
    embed.add_field(name="Juggernauts & Companions", value="`86!juggernauts <page>` — list configs\n`86!selectjug <index>` — equip config\n`86!companion_add <name>` — add companion\n`86!companion_upgrade <name> <stat> <points>` — upgrade companion", inline=False)
    embed.add_field(name="Events", value="Admin: `86!startevent <hp> <title>`\nPlayers: `86!joinevent`, `86!attackevent`, `86!eventstatus`", inline=False)
    embed.add_field(name="Misc", value="`86!inventory` — list inventory\n`86!assign <stat> <points>` — spend skill points\n`86!about` — about the bot", inline=False)
    embed.set_footer(text="Spearhead Command — stay disciplined. Use commands responsibly.")
    await ctx.send(embed=embed)

@bot.command()
async def about(ctx):
    embed = discord.Embed(title="📖 About Project 86 Bot", description="A tactical RPG Discord bot themed after *Eighty-Six* (military, mecha, risk & sacrifice).", color=0x7289da)
    embed.add_field(name="Developer", value="Spearhead Initiative", inline=True)
    embed.add_field(name="Prefix", value=COMMAND_PREFIX, inline=True)
    embed.set_footer(text="Glory to the Republic — and to the Spearhead Squadron.")
    await ctx.send(embed=embed)

@bot.command()
async def register(ctx):
    player = await ensure_player(ctx.author)
    await ctx.send(f"Handler: Profile created for {player['name']} — Rank: {player['rank']}, Level: {player['level']}.")

@bot.command()
async def checkin(ctx):
    player = await ensure_player(ctx.author)
    now = int(time.time())
    last = int(player.get("last_checkin",0))
    day_now = now // 86400
    day_last = last // 86400
    if day_now == day_last:
        await ctx.send("You have already claimed today's ration allotment.")
        return
    player["credits"] = player.get("credits",0) + 200
    player["exp"] = player.get("exp",0) + 50
    player["last_checkin"] = now
    data = await load_data()
    data["players"][str(ctx.author.id)] = player
    await save_data(data)
    await ctx.send("Daily check-in received: +200 credits, +50 exp. Stay alive out there.")

@bot.command()
async def status(ctx, member:discord.Member=None):
    who = member or ctx.author
    player = await ensure_player(who)
    eff = compute_effective_stats(player)
    embed = discord.Embed(title=f"{player['name']} — Status Report", color=0x2b547e)
    embed.add_field(name="Rank", value=player.get("rank"))
    embed.add_field(name="Level", value=str(player.get("level")))
    embed.add_field(name="HP", value=f"{player.get('hp')}/{eff.get('hp_max')}")
    embed.add_field(name="Attack", value=str(eff.get("attack")))
    embed.add_field(name="Defense", value=str(eff.get("defense")))
    embed.add_field(name="Juggernaut", value=player.get("juggernaut"))
    embed.add_field(name="Skill Points", value=str(player.get("skill_points",0)))
    embed.add_field(name="Credits", value=str(player.get("credits",0)))
    embed.add_field(name="Missions/Wins", value=f"{player.get('missions',0)}/{player.get('wins',0)}")
    await ctx.send(embed=embed)

@bot.command()
async def shop(ctx):
    keys = SHOP_ITEMS_ORDER
    view = StoreView(ctx, keys, SHOP_CATALOG, title="🛒 Spearhead Arsenal — Tactical Upgrades")
    embed = view.build_embed()
    await ctx.send(embed=embed, view=view)

@bot.command()
async def scrapyard(ctx):
    keys = SCRAP_ITEMS_ORDER
    view = StoreView(ctx, keys, SCRAPYARD_CATALOG, title="⚙️ Spearhead Scrapyard — Salvage & Parts")
    embed = view.build_embed()
    await ctx.send(embed=embed, view=view)

@bot.command()
async def hangar(ctx):
    player = await ensure_player(ctx.author)
    view = HangarView(ctx, player)
    embed = view.build_embed()
    await ctx.send(embed=embed, view=view)

@bot.command()
async def inventory(ctx):
    player = await ensure_player(ctx.author)
    inv = player.get("inventory", {})
    if not inv:
        await ctx.send("Inventory secure: none stored.")
        return
    embed = discord.Embed(title=f"{player['name']} — Inventory", color=0x444444)
    for k,v in inv.items():
        data = v.get("data")
        embed.add_field(name=data.get("name",k), value=f"Count: {v.get('count',0)} • Rarity: {data.get('rarity','')}", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def deploy(ctx):
    player = await ensure_player(ctx.author)
    data = await load_data()
    now = time.time()
    if now - player.get("last_mission",0) < MISSION_CD:
        remain = int(MISSION_CD - (now - player.get("last_mission",0)))
        await ctx.send(f"Mission Prep: cooldown active. Wait {remain} seconds before next deployment.")
        return
    res = await attempt_mission(player, data)
    data["players"][str(ctx.author.id)] = player
    await save_data(data)
    if not res.get("ok"):
        await ctx.send("Mission failed to initiate.")
        return
    title = "⚠️ Boss Mission" if res["boss"] else "Mission Report"
    color = 0xff4400 if res["boss"] else 0x00aa66
    desc = ("**SUCCESS** — " if res["success"] else "**FAILED** — ") + ("Mission concluded." if not res["boss"] else "Boss engagement concluded.")
    details = ""
    if res["success"]:
        details += f" Credits +{res['credits']}, EXP +{res['exp']}.\n"
        if res.get("drop"):
            details += f"**Drop Collected**: {res['drop']['name']} ({res['drop']['rarity']})\n"
    else:
        details += "You sustained damage and/or lost resources.\n"
    if res.get("leveled"):
        details += "Promotion achieved. Spend skill points with `86!assign <stat> <points>`.\n"
    embed = discord.Embed(title=title, description=desc, color=color)
    if details:
        embed.add_field(name="Outcome Details", value=details, inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def assign(ctx, stat:str=None, points:int=None):
    player = await ensure_player(ctx.author)
    if stat is None or points is None:
        await ctx.send("Usage: `86!assign <attack|defense|hp_max> <points>`")
        return
    if points <= 0 or player.get("skill_points",0) < points:
        await ctx.send("Insufficient skill points.")
        return
    if stat not in ("attack","defense","hp_max"):
        await ctx.send("Invalid stat. Choose attack, defense or hp_max.")
        return
    if stat == "hp_max":
        player["stats"]["hp_max"] += points * 5
    else:
        player["stats"][stat] += points
    player["skill_points"] -= points
    data = await load_data()
    data["players"][str(ctx.author.id)] = player
    await save_data(data)
    await ctx.send(f"Assigned {points} point(s) to {stat}. Tactical performance updated.")

@bot.command()
async def juggernauts(ctx, page:int=1):
    keys = list(JUGGERNAUT_CONFIGS.keys())
    per = 6
    page = max(1,page)
    start = (page-1)*per
    embed = discord.Embed(title="Juggernaut Configurations — Select with `86!selectjug <index>`", color=0x223344)
    for i in range(per):
        idx = start + i
        if idx >= len(keys):
            break
        name = keys[idx]
        cfg = JUGGERNAUT_CONFIGS[name]
        embed.add_field(name=f"{idx+1}. {name}", value=f"ATK {cfg['attack']} • DEF {cfg['defense']} • HP {cfg['hp']}", inline=False)
    embed.set_footer(text=f"Page {page} • Use index from full list (see the numbering).")
    await ctx.send(embed=embed)

@bot.command()
async def selectjug(ctx, index:int):
    keys = list(JUGGERNAUT_CONFIGS.keys())
    if index < 1 or index > len(keys):
        await ctx.send("Invalid juggernaut index.")
        return
    name = keys[index-1]
    player = await ensure_player(ctx.author)
    player["juggernaut"] = name
    data = await load_data()
    data["players"][str(ctx.author.id)] = player
    await save_data(data)
    await ctx.send(f"Juggernaut configured: {name}. Handler acknowledges.")

@bot.command()
@commands.has_permissions(administrator=True)
async def startevent(ctx, hp:int=5000, *, title:str="Event Legion Overlord"):
    data = await load_data()
    event = await start_event(data, hp=hp, title=title)
    embed = discord.Embed(title=f"🚨 Event Launched — {event['name']}", description=f"HP: {event['hp']} • Join window: {EVENT_JOIN_WINDOW}s", color=0xaa0000)
    view = EventView(ctx)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def joinevent(ctx):
    res = await join_event(ctx.author)
    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "no_event":
            await ctx.send("No active event at present.")
        elif reason == "join_closed":
            await ctx.send("Event joining window closed.")
        else:
            await ctx.send("Could not join event.")
        return
    await ctx.send("You have been registered for the event. Prepare to attack with `86!attackevent` or press Attack on the event view.")

@bot.command()
async def attackevent(ctx):
    res = await attack_event(ctx.author)
    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "no_event":
            await ctx.send("No active event.")
        elif reason == "attack_window_closed":
            await ctx.send("Event attack window closed.")
        elif reason == "not_joined":
            await ctx.send("You didn't join the event. Use `86!joinevent` first.")
        elif reason == "personal_cd":
            await ctx.send(f"Personal cooldown active. Wait {res.get('remaining',0)}s.")
        else:
            await ctx.send("Could not attack event.")
        return
    if res.get("killed"):
        await ctx.send(f"You dealt {res['damage']} and destroyed the event boss. Rewards distributed.")
    else:
        await ctx.send(f"You dealt {res['damage']} damage to the event boss.")

@bot.command()
async def eventstatus(ctx):
    data = await load_data()
    event = data.get("event")
    if not event or not event.get("active"):
        await ctx.send("No active event.")
        return
    remain = max(0, int(event.get("attack_deadline",0) - time.time()))
    await ctx.send(f"Event {event['name']}: HP {event['hp']}/{event['max_hp']} — Attack window: {remain}s")

@bot.command()
async def forceboss(ctx):
    player = await ensure_player(ctx.author)
    inv = player.setdefault("inventory", {})
    if "boss_beacon" in inv and inv["boss_beacon"].get("count",0) > 0:
        inv["boss_beacon"]["count"] -= 1
        if inv["boss_beacon"]["count"] <= 0:
            del inv["boss_beacon"]
        player["boss_forced"] = True
        data = await load_data()
        data["players"][str(ctx.author.id)] = player
        await save_data(data)
        await ctx.send("Boss Beacon activated. Next deployment will be a boss.")
    else:
        await ctx.send("No Boss Beacon in inventory.")

@bot.command()
async def companion_add(ctx, name:str):
    player = await ensure_player(ctx.author)
    if not name:
        await ctx.send("Usage: 86!companion_add <name>")
        return
    comps = player.setdefault("companions", {})
    if name in comps:
        await ctx.send("Companion name already exists.")
        return
    comps[name] = {"level":1,"attack":5,"defense":2,"hp":50,"skill_points":0}
    data = await load_data()
    data["players"][str(ctx.author.id)] = player
    await save_data(data)
    await ctx.send(f"Companion {name} enlisted and assigned to your unit.")

@bot.command()
async def companion_upgrade(ctx, name:str, stat:str, points:int):
    player = await ensure_player(ctx.author)
    comps = player.get("companions", {})
    comp = comps.get(name)
    if not comp:
        await ctx.send("Companion not found.")
        return
    if comp.get("skill_points",0) < points:
        await ctx.send("Companion lacks skill points.")
        return
    if stat not in ("attack","defense","hp"):
        await ctx.send("Invalid stat.")
        return
    if stat == "hp":
        comp["hp"] += points * 5
    else:
        comp[stat] += points
    comp["skill_points"] -= points
    data = await load_data()
    data["players"][str(ctx.author.id)] = player
    await save_data(data)
    await ctx.send(f"Companion {name} enhanced: +{points} {stat}.")

@bot.command()
async def buy(ctx, source:str, index:int):
    source = source.lower()
    player = await ensure_player(ctx.author)
    if source == "shop":
        keys = SHOP_ITEMS_ORDER
        catalog = SHOP_CATALOG
    elif source in ("scrap","scrapyard"):
        keys = SCRAP_ITEMS_ORDER
        catalog = SCRAPYARD_CATALOG
    else:
        await ctx.send("Source must be 'shop' or 'scrapyard'.")
        return
    if index < 1 or index > len(keys):
        await ctx.send("Index out of range.")
        return
    key = keys[index-1]
    item = catalog[key]
    price = item["price"] if catalog is SHOP_CATALOG else int(item["price"] * SCRAPYARD_MULTIPLIER)
    if player.get("credits",0) < price:
        await ctx.send(f"Not enough credits — need {price}.")
        return
    player["credits"] -= price
    part_copy = dict(item)
    if catalog is SCRAPYARD_CATALOG:
        part_copy["durability"] = max(1, int(part_copy.get("durability",50) * 0.5))
    player.setdefault("parts", []).append(part_copy)
    data = await load_data()
    data["players"][str(ctx.author.id)] = player
    await save_data(data)
    await ctx.send(f"Equipped {item['name']} — paid {price} credits.")

# ----- cleanup loop -----
@tasks.loop(minutes=10)
async def cleanup_tasks():
    data = await load_data()
    changed = False
    for p in data.get("players", {}).values():
        parts = p.get("parts", [])
        new_parts = [pp for pp in parts if pp.get("durability",100) > 0]
        if len(new_parts) != len(parts):
            p["parts"] = new_parts
            changed = True
    if changed:
        await save_data(data)

# ---------------- RUN ----------------
if __name__ == "__main__":
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({"meta":{"next_event_id":1},"players":{},"event":None}, f, indent=2)
    # Run bot (token must be set in DISCORD_TOKEN)
    bot.run(BOT_TOKEN)
