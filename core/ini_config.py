"""
The War In Rapture: BioShock 2 — INI Configuration Parser/Patcher
==================================================================
Parses and patches BioShock 2 Remastered INI configuration files
extracted from ConfigINI.IBF.

Key INI files:
  DamageSets.ini           - All weapon/plasmid damage stimuli sets
  DamageMultiplierSet.ini  - Per-region (headshot) damage multipliers
  LootTables_perobjectconfig.ini - Enemy loot drop tables + vending tables
  Difficulty_perobjectconfig.ini - Difficulty curve tables
  WeaponUpgrades.ini       - Weapon upgrade definitions
"""
import re
from collections import OrderedDict


# ─── INI Parser (preserves duplicate keys and formatting) ────────────────────

def parse_ini(text):
    """Parse INI text into [(section, key, value, raw_line), ...].
    Preserves ordering and duplicate keys (common in UE2 configs).
    """
    entries = []
    current_section = ''
    for line in text.split('\n'):
        line = line.rstrip('\r')  # normalize \r\n -> \n (avoids \r\r\n on write)
        stripped = line.strip()
        if not stripped or stripped.startswith(';') or stripped.startswith('#'):
            entries.append((current_section, None, None, line))
            continue
        if stripped.startswith('[') and stripped.endswith(']'):
            current_section = stripped[1:-1]
            entries.append((current_section, None, None, line))
            continue
        m = re.match(r'^(\w[\w\d]*)\s*=\s*(.*)', stripped)
        if m:
            key, value = m.group(1), m.group(2)
            entries.append((current_section, key, value, line))
        else:
            entries.append((current_section, None, None, line))
    return entries


def write_ini(entries):
    """Write entries back to INI text."""
    lines = []
    for section, key, value, raw_line in entries:
        if key is not None:
            lines.append('%s=%s' % (key, value))
        else:
            lines.append(raw_line)
    return '\n'.join(lines)


def get_section_entries(entries, section_name):
    """Get all entries for a given section."""
    return [(s, k, v, r) for s, k, v, r in entries if s == section_name and k is not None]


def set_value(entries, section, key, value):
    """Set the first occurrence of key in section to value. Returns True if found."""
    for i, (s, k, v, r) in enumerate(entries):
        if s == section and k == key:
            entries[i] = (s, k, str(value), r)
            return True
    return False


def get_value(entries, section, key):
    """Get the first value for key in section."""
    for s, k, v, r in entries:
        if s == section and k == key:
            return v
    return None


def add_entry(entries, section, key, value):
    """Add a new key=value after the last entry of the given section."""
    last_idx = -1
    for i, (s, k, v, r) in enumerate(entries):
        if s == section:
            last_idx = i
    if last_idx >= 0:
        entries.insert(last_idx + 1, (section, key, str(value), ''))
        return True
    return False


# ─── DamageSets.ini — Weapon/Plasmid Damage ─────────────────────────────────

# Friendly names for stimuli sets
WEAPON_STIMULI = OrderedDict([
    # Drill
    ('DrillSpin_StimuliSet',           'Drill (Spin)'),
    ('DrillSwing_StimuliSet',          'Drill (Swing)'),
    ('DrillDashStimuliSet',            'Drill (Dash)'),
    # Rivet Gun
    ('StandardRivet_StimuliSet',       'Rivet Gun (Standard)'),
    ('MagnumRivet_StimuliSet',         'Rivet Gun (Heavy)'),
    ('TrapRivet_DirectHit_StimuliSet', 'Rivet Gun (Trap Hit)'),
    ('TrapRivet_TrapSprung_StimuliSet','Rivet Gun (Trap Sprung)'),
    # Machine Gun
    ('MachineGunStandardBulletStimuliSet',       'Machine Gun (Standard)'),
    ('MachineGunArmorPiercingBulletStimuliSet',  'Machine Gun (Armor Piercing)'),
    ('MachineGunAntipersonnelBulletStimuliSet',  'Machine Gun (Antipersonnel)'),
    # Shotgun
    ('Buck00StimuliSet',               'Shotgun (00 Buck)'),
    ('PhosphorusExplosiveStimuliSet',  'Shotgun (Phosphorus)'),
    ('SolidSlugStimuliSet',            'Shotgun (Solid Slug)'),
    # Spear Gun
    ('StandardSpear_StimuliSet',       'Spear Gun (Standard)'),
    ('RocketSpear_StimuliSet',         'Spear Gun (Rocket)'),
    ('TrapSpear_StimuliSet',           'Spear Gun (Trap)'),
    # Grenade Launcher
    ('FragGrenadeStimuliSet',          'Launcher (Frag)'),
    ('ProxGrenadeStimuliSet',          'Launcher (Proximity)'),
    ('StickyProxStimuliSet',           'Launcher (Sticky Prox)'),
    ('HeatSeekingRPGStimuliSet',       'Launcher (Rocket)'),
    # Hack Tool
    ('DistanceHackingStimuliSet',      'Hack Tool'),
    # Camera / Research
    ('LaserGunLaserStimuliSet',        'Research Camera (Laser)'),
    ('LaserGunHeatStimuliSet',         'Research Camera (Heat)'),
    ('LaserGunBurstStimuliSet_Max',    'Research Camera (Burst Max)'),
    ('LaserGunBurstStimuliSet_Min',    'Research Camera (Burst Min)'),
    # Plasmids
    ('ElectroBoltBasicStimuliSet',     'Electro Bolt 1'),
    ('ElectroBoltChargedAdvancedStimuliSet', 'Electro Bolt 2'),
    ('ElectroBoltChargedMasterStimuliSet',   'Electro Bolt 3'),
    ('IncinerateStimuliSet',           'Incinerate 1'),
    ('IncinerateStimuliSet_Advanced',  'Incinerate 2'),
    ('IncinerateStimuliSet_Master',    'Incinerate 3'),
    ('TelekinesisThrowStimuliSet',     'Telekinesis (Throw)'),
    ('WinterBlastStimuliSet',          'Winter Blast 1'),
    ('WinterBlast2StimuliSet',         'Winter Blast 2'),
    ('WinterBlast3StimuliSet',         'Winter Blast 3'),
    ('CycloneTrapStimuliSet',          'Cyclone Trap'),
    ('InsectSwarmStimuliSet',          'Insect Swarm 1'),
    ('InsectSwarm2StimuliSet',         'Insect Swarm 2'),
    ('InsectSwarm3StimuliSet',         'Insect Swarm 3'),
    ('ScoutPlasmidStimuliSet',         'Scout'),
    # Security
    ('AutoTurretStimuliSet',           'Auto Turret'),
    ('BotLaserStimuliSet',             'Security Bot'),
    ('MasterBotLaserStimuliSet',       'Master Bot'),
])


def read_damage_sets(entries):
    """Read all stimuli sets from DamageSets.ini entries.
    Returns {section_name: {'friendly': str, 'stimuli': [{'type': str, 'amount': float, ...}, ...]}}
    """
    result = OrderedDict()
    for section_name, friendly in WEAPON_STIMULI.items():
        stimuli = []
        for s, k, v, r in entries:
            if s == section_name and k == 'Stimulus':
                parsed = _parse_stimulus(v)
                if parsed:
                    stimuli.append(parsed)
        if stimuli:
            result[section_name] = {'friendly': friendly, 'stimuli': stimuli}
    return result


def _parse_stimulus(value):
    """Parse a Stimulus=(Type=...,Amount=...,Chance=...) value."""
    m = re.match(r'\((.+)\)', value.strip())
    if not m:
        return None
    inner = m.group(1)
    parts = {}
    for pair in re.findall(r'(\w+)\s*=\s*([^,\)]+)', inner):
        parts[pair[0]] = pair[1]
    return {
        'type': parts.get('Type', ''),
        'amount': float(parts.get('Amount', 0)),
        'chance': float(parts.get('Chance', 1.0)),
    }


def patch_stimulus_amount(entries, section, stimulus_type, new_amount):
    """Patch a specific stimulus amount in a stimuli set section."""
    count = 0
    for i, (s, k, v, r) in enumerate(entries):
        if s == section and k == 'Stimulus' and stimulus_type in v:
            new_v = re.sub(
                r'(Amount=)[0-9]+\.?[0-9]*',
                r'\g<1>%.1f' % new_amount, v)
            if new_v != v:
                entries[i] = (s, k, new_v, r)
                count += 1
    return count


# ─── LootTables — Enemy Loot ────────────────────────────────────────────────

# Friendly item names
LOOT_ITEMS = {
    'None': 'Nothing',
    "class'ShockDesignerClasses.MedHypo'": 'Med Hypo',
    "class'ShockDesignerClasses.BioAmmoHypo'": 'EVE Hypo',
    "class'ShockGame.Credits'": 'Credits',
    "class'ShockGame.Rivet_Ammo'": 'Rivets',
    "class'ShockGame.HeavyRivet_Ammo'": 'Heavy Rivets',
    "class'ShockGame.TrapRivet_Ammo'": 'Trap Rivets',
    "class'ShockGame.MachineGun_Ammo'": 'MG Rounds',
    "class'ShockGame.MachineGun_ArmorPiercing_Ammo'": 'MG AP Rounds',
    "class'ShockGame.MachineGun_Antipersonnel_Ammo'": 'MG Anti-P Rounds',
    "class'ShockGame.Shotgun_00Buck'": '00 Buck',
    "class'ShockGame.Shotgun_SolidSlug'": 'Solid Slug',
    "class'ShockGame.Shotgun_Phosphorus'": 'Phosphorus',
    "class'ShockGame.Spear_Ammo'": 'Spears',
    "class'ShockGame.RocketSpear_Ammo'": 'Rocket Spears',
    "class'ShockGame.TrapSpear_Ammo'": 'Trap Spears',
    "class'ShockGame.Frag_Grenade'": 'Frag Grenades',
    "class'ShockGame.ProximityMine'": 'Proximity Mines',
    "class'ShockGame.RPGAmmo'": 'RPG Rockets',
    "class'ShockGame.Drill_Ammo'": 'Drill Fuel',
    "class'ShockGame.HackDart_Ammo'": 'Hack Darts',
    "class'ShockGame.MiniTurretAmmo'": 'Mini Turret',
    "class'ShockGame.FirstAidKit'": 'First Aid Kit',
    "class'ShockGame.Chips'": 'Chips',
    "class'ShockGame.Creme_Filled_Cake'": 'Creme Cake',
    "class'ShockGame.Coffee'": 'Coffee',
    "class'ShockGame.Pep_Bar'": 'Pep Bar',
    "class'ShockGame.Beans'": 'Beans',
    "class'ShockGame.Bandages'": 'Bandages',
    "class'ShockGame.Vodka'": 'Vodka',
    "class'ShockGame.Wine'": 'Wine',
    "class'ShockGame.Whiskey'": 'Whiskey',
    "class'ShockGame.Cigarettes'": 'Cigarettes',
}

# Reverse lookup
LOOT_ITEMS_REV = {v: k for k, v in LOOT_ITEMS.items()}


def loot_item_friendly(item_class):
    """Get friendly name for an item class string."""
    return LOOT_ITEMS.get(item_class, item_class)


def read_loot_tables(entries):
    """Read enemy loot tables from LootTables entries.
    Returns {section: [{'item': str, 'chance': int, 'min_stack': int, 'max_stack': int}, ...]}
    """
    result = OrderedDict()
    current_section = None
    current_specs = []

    for s, k, v, r in entries:
        if k is None:
            continue
        if k == 'LootSpec':
            if s != current_section:
                if current_section and current_specs:
                    result[current_section] = current_specs
                current_section = s
                current_specs = []
            spec = _parse_loot_spec(v)
            if spec:
                current_specs.append(spec)

    if current_section and current_specs:
        result[current_section] = current_specs

    return result


def _parse_loot_spec(value):
    """Parse a LootSpec=(Chance=X, ItemClass=Y, ...) value."""
    m = re.match(r'\((.+)\)', value.strip())
    if not m:
        return None
    inner = m.group(1)

    chance = 0
    item = 'None'
    min_stack = 0
    max_stack = 0
    table_name = ''

    cm = re.search(r'Chance\s*=\s*(\d+)', inner)
    if cm:
        chance = int(cm.group(1))

    im = re.search(r"ItemClass\s*=\s*(class'[^']*'|None)", inner)
    if im:
        item = im.group(1)

    tm = re.search(r'TableName\s*=\s*(\w+)', inner)
    if tm:
        table_name = tm.group(1)

    sm = re.search(r'MinStackSize\s*=\s*(\d+)', inner)
    if sm:
        min_stack = int(sm.group(1))

    mx = re.search(r'MaxStackSize\s*=\s*(\d+)', inner)
    if mx:
        max_stack = int(mx.group(1))

    return {
        'item': item,
        'chance': chance,
        'min_stack': min_stack,
        'max_stack': max_stack,
        'table_name': table_name,
    }


def rebuild_loot_table(entries, section, specs):
    """Replace all LootSpec entries in a section with new specs."""
    # Remove existing LootSpec entries
    to_remove = []
    for i, (s, k, v, r) in enumerate(entries):
        if s == section and k == 'LootSpec':
            to_remove.append(i)
    for i in reversed(to_remove):
        entries.pop(i)

    # Find where to insert (after section header)
    insert_at = -1
    for i, (s, k, v, r) in enumerate(entries):
        if s == section:
            insert_at = i + 1
            break

    if insert_at < 0:
        return

    # Insert new specs
    for si, spec in enumerate(reversed(specs)):
        parts = ['Chance=%d' % spec['chance']]
        if spec.get('table_name'):
            parts.append('TableName=%s' % spec['table_name'])
        else:
            parts.append('ItemClass=%s' % spec['item'])
        if spec.get('min_stack', 0) > 0:
            parts.append('MinStackSize=%d' % spec['min_stack'])
        if spec.get('max_stack', 0) > 0:
            parts.append('MaxStackSize=%d' % spec['max_stack'])
        val = '(%s)' % ', '.join(parts)
        entries.insert(insert_at, (section, 'LootSpec', val, ''))


# ─── Vending Machine & Gatherer's Garden ────────────────────────────────────

# Friendly names for vending/garden item classes
VENDING_ITEM_NAMES = {
    # Ammo
    'ShockGame.Drill_Ammo':                     'Drill Fuel',
    'ShockGame.Rivet_Ammo':                     'Rivets',
    'ShockGame.Rivet_MagnumAmmo':               'Heavy Rivets',
    'ShockGame.Rivet_TrapAmmo':                 'Trap Rivets',
    'ShockGame.MachineGun_Bullet':              'Machine Gun Rounds',
    'ShockGame.MachineGun_ArmorPiercingBullet':  'Armor-Piercing Rounds',
    'ShockGame.MachineGun_AntiPersonnelBullet':  'Antipersonnel Rounds',
    'ShockGame.Shotgun_00Buck':                 '00 Buck',
    'ShockGame.Shotgun_PhosphorusBuck':         'Phosphorus Buck',
    'ShockGame.Shotgun_SolidSlug':              'Solid Slug',
    'ShockGame.Speargun_Spear':                 'Spears',
    'ShockGame.Speargun_TrapSpearAmmo':         'Trap Spears',
    'ShockGame.Speargun_RocketSpearAmmo':       'Rocket Spears',
    'ShockGame.GrenadeLauncher_FragGrenade':     'Frag Grenades',
    'ShockGame.GrenadeLauncher_StickyGrenade':   'Proximity Mines',
    'ShockGame.GrenadeLauncher_RPG':            'RPG Rockets',
    'ShockGame.Hacking_Ammo':                   'Hack Darts',
    'ShockGame.Hacking_AutoHackAmmo':           'Auto-Hack Darts',
    'ShockGame.Hacking_TurretAmmo':             'Mini Turret Ammo',
    # Consumables
    'ShockDesignerClasses.MedHypo':             'First Aid Kit',
    'ShockDesignerClasses.BioAmmoHypo':         'EVE Hypo',
    # Food / Drink
    'Pickups.ChipsPickupItem':                  'Chips',
    'Pickups.CoffeePickupItem':                 'Coffee',
    'Pickups.TwinkiePickupItem':                'Cream-Filled Cake',
    'Pickups.PowerbarPickupItem':               'Pep Bar',
    'Pickups.CannedBeansPickupItem':            'Canned Beans',
    'Pickups.CannedFruitPickupItem':            'Canned Fruit',
    'Pickups.PottedMeatPickupItem':             'Potted Meat',
    'Pickups.SardinesPickupItem':               'Sardines',
    'Pickups.SodaPickupItem':                   'Soda',
    'Pickups.FreshWaterPickupItem':             'Fresh Water',
    'Pickups.VitaminsPickupItem':               'Vitamins',
    'Pickups.AspirinPickupItem':                'Aspirin',
    'Pickups.DrHollcroftsCureAllPickupItem':     'Dr. Hollcroft\'s Cure-All',
    # Plasmids
    'Plasmids.ElectroBoltBasicPlasmid':         'Electro Bolt',
    'Plasmids.ElectroBoltAdvancedPlasmid':      'Electro Bolt 2',
    'Plasmids.ElectroBoltMasterPlasmid':        'Electro Bolt 3',
    'Plasmids.IncinerationBasicPlasmid':        'Incinerate!',
    'Plasmids.IncinerationAdvancedPlasmid':     'Incinerate! 2',
    'Plasmids.IncinerationMasterPlasmid':       'Incinerate! 3',
    'Plasmids.TelekinesisBasicPlasmid':         'Telekinesis',
    'Plasmids.TelekinesisAdvancedPlasmid':      'Telekinesis 2',
    'Plasmids.TelekinesisMasterPlasmid':        'Telekinesis 3',
    'Plasmids.WinterBlastBasicPlasmid':         'Winter Blast',
    'Plasmids.WinterBlastAdvancedPlasmid':      'Winter Blast 2',
    'Plasmids.WinterBlastMasterPlasmid':        'Winter Blast 3',
    'Plasmids.CycloneTrapBasicPlasmid':         'Cyclone Trap',
    'Plasmids.CycloneTrapAdvancedPlasmid':      'Cyclone Trap 2',
    'Plasmids.CycloneTrapMasterPlasmid':        'Cyclone Trap 3',
    'Plasmids.SwarmBasicPlasmid':               'Insect Swarm',
    'Plasmids.SwarmAdvancedPlasmid':            'Insect Swarm 2',
    'Plasmids.SwarmMasterPlasmid':              'Insect Swarm 3',
    'Plasmids.HypnotizeBasicPlasmid':           'Hypnotize',
    'Plasmids.HypnotizeAdvancedPlasmid':        'Hypnotize 2',
    'Plasmids.HypnotizeMasterPlasmid':          'Hypnotize 3',
    'Plasmids.SecurityCommandBasicPlasmid':     'Security Command',
    'Plasmids.SecurityCommandAdvancedPlasmid':  'Security Command 2',
    'Plasmids.SecurityCommandMasterPlasmid':    'Security Command 3',
    'Plasmids.DecoyBasicPlasmid':               'Decoy',
    'Plasmids.DecoyAdvancedPlasmid':            'Decoy 2',
    'Plasmids.DecoyMasterPlasmid':              'Decoy 3',
    'Plasmids.ScoutBasicPlasmid':               'Scout',
    'Plasmids.ScoutAdvancedPlasmid':            'Scout 2',
    'DLCPlasmids.BioGrenadeAdvancedPlasmid':    'Sonic Boom 2 (DLC)',
    'DLCPlasmids.BioGrenadeMasterPlasmid':      'Sonic Boom 3 (DLC)',
    'DLCPlasmids.DLCSecurityCommandAdvancedPlasmid': 'Security Command 2 (DLC)',
    'DLCPlasmids.DLCSecurityCommandMasterPlasmid':   'Security Command 3 (DLC)',
    # Upgrades
    'ShockGame.HealthUpgrade':                  'Health Upgrade',
    'ShockGame.BioAmmoUpgrade':                 'EVE Upgrade',
    'ShockGame.ActiveGeneticSlotUpgrade':       'Plasmid Slot Upgrade',
    'ShockGame.PhysicalGeneticSlotUpgrade':     'Tonic Slot Upgrade',
    # Tonics
    'Tonics.AlcoholEveBonus_Tonic':             'Booze Hound',
    'Tonics.AmmoSalvageIncrease_Tonic':         'Scrounger',
    'Tonics.ArmoredShell_Tonic':                'Armored Shell',
    'Tonics.Bloodlust_Tonic':                   'Bloodlust',
    'Tonics.BonusAutoHack_Tonic':               'Careful Hacker',
    'Tonics.ChargedFireBursts_Tonic':           'Fire Storm',
    'Tonics.ChargedIceBursts_Tonic':            'Ice Storm',
    'Tonics.ConsumableHealthBonus_Tonic':       'Extra Nutrition',
    'Tonics.DrillPowerX_Tonic':                 'Drill Power',
    'Tonics.ElectricFlesh_Tonic':               'Electric Flesh',
    'Tonics.ElementalLifeDrain_Tonic':          'Elemental Vampire',
    'Tonics.EveCarriedBonus_Tonic':             'EVE Expert',
    'Tonics.EveLink_Tonic':                     'EVE Link',
    'Tonics.EveSaver_Tonic':                    'EVE Saver',
    'Tonics.EveSaver2_Tonic':                   'EVE Saver 2',
    'Tonics.FrozenField_Tonic':                 'Frozen Field',
    'Tonics.HackersDelight_Tonic':              "Hacker's Delight",
    'Tonics.HackersDelight2_Tonic':             "Hacker's Delight 2",
    'Tonics.HackingLargeSuccess_Tonic':         'EZ-Hack',
    'Tonics.HackingNeedleSpeed_Tonic':          'Speedy Hacker',
    'Tonics.HackingNeedleSpeed2_Tonic':         'Speedy Hacker 2',
    'Tonics.HackingStageRemoval_Tonic':         'Short Circuit',
    'Tonics.Handyman_Tonic':                    'Handyman',
    'Tonics.HeadshotDamageBonus_Tonic':         'Headhunter',
    'Tonics.HealStationsGiveEve_Tonic':         'Fountain of Youth',
    'Tonics.KeenObserver_Tonic':                'Keen Observer',
    'Tonics.KeenObserver2_Tonic':               'Keen Observer 2',
    'Tonics.Lurker_Tonic':                      'Lurker',
    'Tonics.MachineBuster_Tonic':               'Machine Buster',
    'Tonics.MachineDamageIncrease_Tonic':       'Damage Research',
    'Tonics.MedicalExpert_Tonic':               'Medical Expert',
    'Tonics.QuickFeet_Tonic':                   'Sports Boost',
    'Tonics.Research3_Tonic':                   'Drill Specialist',
    'Tonics.ResearchBonusIncrease_Tonic':       'Prolific Inventor',
    'Tonics.Scrounger_Tonic':                   'Thrifty Hacker',
    'Tonics.SecurityDisabling_Tonic':           'Security Evasion',
    'Tonics.SecurityDisabling2_Tonic':          'Security Evasion 2',
    'Tonics.SecurityResponseSlow_Tonic':        'Alarm Expert',
    'Tonics.SharpenedDrill_Tonic':              'Drill Lurker',
    'Tonics.SharpenedDrill2_Tonic':             'Drill Lurker 2',
    'Tonics.ShortenAlarms_Tonic':               'Short Circuit 2',
    'Tonics.ShortenAlarms2_Tonic':              'Shorten Alarms 2',
    'Tonics.StaticDischarge_Tonic':             'Static Discharge',
    'Tonics.TurretHackHealth_Tonic':            'Hardy Machines',
    'Tonics.VendingExpert_Tonic':               'Vending Expert',
    'Tonics.VendingExpert2_Tonic':              'Vending Expert 2',
    'Tonics.WalkingInferno_Tonic':              'Walking Inferno',
    'Tonics.WaterHealthRestoration_Tonic':      'Aqua Inhaler',
    'Tonics.NaturalCamouflage_Tonic':           'Natural Camouflage',
    'DLCPlasmids.DaddyDash_Tonic':              'Proud Parent (DLC)',
    'DLCPlasmids.MasterProtector_Tonic':        'Master Protector (DLC)',
}

# Master list of all vending machine items: (ItemClass, PickupClass, StackSize, CostAdjustment)
VENDING_MASTER = [
    ('ShockDesignerClasses.MedHypo',              'Pickups.MedHypo_Pickup',           1,  1),
    ('ShockDesignerClasses.BioAmmoHypo',          'Pickups.EveHypo_Pickup',           1,  1),
    ('ShockGame.Drill_Ammo',                      'Pickups.DrillAmmo_Pickup',         50, 1),
    ('ShockGame.Rivet_Ammo',                      'Pickups.StandardRivet_Pickup',     12, 1),
    ('ShockGame.Rivet_MagnumAmmo',                'Pickups.HighPowerRivet_Pickup',    6,  1),
    ('ShockGame.Rivet_TrapAmmo',                  'Pickups.TrapRivet_Pickup',         6,  1),
    ('ShockGame.Shotgun_00Buck',                  'Pickups.00Buck_Pickup',            4,  1),
    ('ShockGame.Shotgun_PhosphorusBuck',          'Pickups.PhosphorusBuck_Pickup',    4,  1),
    ('ShockGame.Shotgun_SolidSlug',               'Pickups.SolidSlug_Pickup',         4,  1),
    ('ShockGame.MachineGun_Bullet',               'Pickups.SMG40Cal_Pickup',          40, 1),
    ('ShockGame.MachineGun_ArmorPiercingBullet',  'Pickups.SMGArmorPiercing_Pickup',  20, 1),
    ('ShockGame.MachineGun_AntiPersonnelBullet',  'Pickups.SMGAntiPersonnel_Pickup',  20, 1),
    ('ShockGame.Speargun_Spear',                  'Pickups.StandardSpear_Pickup',     5,  1),
    ('ShockGame.Speargun_TrapSpearAmmo',          'Pickups.TrapSpear_Pickup',         4,  1),
    ('ShockGame.Speargun_RocketSpearAmmo',        'Pickups.RocketSpear_Pickup',       2,  1),
    ('ShockGame.GrenadeLauncher_FragGrenade',      'Pickups.FragGrenade_Pickup',       2,  1),
    ('ShockGame.GrenadeLauncher_StickyGrenade',    'Pickups.StickyGrenade_Pickup',     1,  1),
    ('ShockGame.GrenadeLauncher_RPG',              'Pickups.RPG_Pickup',               1,  1),
    ('ShockGame.Hacking_Ammo',                     'Pickups.HackAmmo_Pickup',          1,  1),
    ('ShockGame.Hacking_AutoHackAmmo',             'Pickups.AutoHackAmmo_Pickup',      1,  1),
    ('ShockGame.Hacking_TurretAmmo',               'Pickups.TurretAmmo_Pickup',        1,  1),
    ('Pickups.ChipsPickupItem',                    'Pickups.ChipsPickupItem',          1,  1),
    ('Pickups.CoffeePickupItem',                   'Pickups.CoffeePickupItem',         1,  1),
    ('Pickups.TwinkiePickupItem',                  'Pickups.TwinkiePickupItem',        1,  1),
    ('Pickups.PowerbarPickupItem',                 'Pickups.PowerbarPickupItem',       1,  1),
]

# Master list of all Gatherer's Garden items
GROWTH_MASTER = [
    # Plasmids (Basic)
    ('Plasmids.ElectroBoltBasicPlasmid',         'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.IncinerationBasicPlasmid',        'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.TelekinesisBasicPlasmid',         'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.WinterBlastBasicPlasmid',         'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.CycloneTrapBasicPlasmid',         'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.SwarmBasicPlasmid',               'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.HypnotizeBasicPlasmid',           'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.SecurityCommandBasicPlasmid',     'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.DecoyBasicPlasmid',               'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.ScoutBasicPlasmid',               'Pickups.MedHypo_Pickup', 1, 1),
    # Plasmids (Advanced)
    ('Plasmids.ElectroBoltAdvancedPlasmid',      'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.IncinerationAdvancedPlasmid',     'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.TelekinesisAdvancedPlasmid',      'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.WinterBlastAdvancedPlasmid',      'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.CycloneTrapAdvancedPlasmid',      'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.SwarmAdvancedPlasmid',            'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.HypnotizeAdvancedPlasmid',        'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.SecurityCommandAdvancedPlasmid',  'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.DecoyAdvancedPlasmid',            'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.ScoutAdvancedPlasmid',            'Pickups.MedHypo_Pickup', 1, 1),
    # Plasmids (Master)
    ('Plasmids.ElectroBoltMasterPlasmid',        'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.IncinerationMasterPlasmid',       'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.TelekinesisMasterPlasmid',        'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.WinterBlastMasterPlasmid',        'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.CycloneTrapMasterPlasmid',        'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.SwarmMasterPlasmid',              'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.HypnotizeMasterPlasmid',          'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.SecurityCommandMasterPlasmid',    'Pickups.MedHypo_Pickup', 1, 1),
    ('Plasmids.DecoyMasterPlasmid',              'Pickups.MedHypo_Pickup', 1, 1),
    # DLC Plasmids
    ('DLCPlasmids.BioGrenadeAdvancedPlasmid',    'Pickups.MedHypo_Pickup', 1, 1),
    ('DLCPlasmids.BioGrenadeMasterPlasmid',      'Pickups.MedHypo_Pickup', 1, 1),
    ('DLCPlasmids.DLCSecurityCommandAdvancedPlasmid', 'Pickups.MedHypo_Pickup', 1, 1),
    ('DLCPlasmids.DLCSecurityCommandMasterPlasmid',   'Pickups.MedHypo_Pickup', 1, 1),
    # Upgrades
    ('ShockGame.HealthUpgrade',                  'Pickups.MedHypo_Pickup', 1, 1),
    ('ShockGame.BioAmmoUpgrade',                 'Pickups.MedHypo_Pickup', 1, 1),
    ('ShockGame.ActiveGeneticSlotUpgrade',       'Pickups.MedHypo_Pickup', 1, 1),
    ('ShockGame.PhysicalGeneticSlotUpgrade',     'Pickups.MedHypo_Pickup', 1, 1),
    # Tonics
    ('Tonics.AlcoholEveBonus_Tonic',             'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.AmmoSalvageIncrease_Tonic',         'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.ArmoredShell_Tonic',                'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.Bloodlust_Tonic',                   'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.BonusAutoHack_Tonic',               'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.ChargedFireBursts_Tonic',           'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.ChargedIceBursts_Tonic',            'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.ConsumableHealthBonus_Tonic',       'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.DrillPowerX_Tonic',                 'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.ElectricFlesh_Tonic',               'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.ElementalLifeDrain_Tonic',          'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.EveCarriedBonus_Tonic',             'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.EveLink_Tonic',                     'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.EveSaver_Tonic',                    'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.EveSaver2_Tonic',                   'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.FrozenField_Tonic',                 'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.HackersDelight_Tonic',              'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.HackersDelight2_Tonic',             'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.HackingLargeSuccess_Tonic',         'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.HackingNeedleSpeed_Tonic',          'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.HackingNeedleSpeed2_Tonic',         'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.HackingStageRemoval_Tonic',         'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.Handyman_Tonic',                    'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.HeadshotDamageBonus_Tonic',         'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.HealStationsGiveEve_Tonic',         'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.KeenObserver_Tonic',                'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.KeenObserver2_Tonic',               'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.Lurker_Tonic',                      'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.MachineBuster_Tonic',               'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.MachineDamageIncrease_Tonic',       'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.MedicalExpert_Tonic',               'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.NaturalCamouflage_Tonic',           'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.QuickFeet_Tonic',                   'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.Research3_Tonic',                   'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.ResearchBonusIncrease_Tonic',       'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.Scrounger_Tonic',                   'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.SecurityDisabling_Tonic',           'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.SecurityDisabling2_Tonic',          'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.SecurityResponseSlow_Tonic',        'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.SharpenedDrill_Tonic',              'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.SharpenedDrill2_Tonic',             'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.ShortenAlarms_Tonic',               'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.ShortenAlarms2_Tonic',              'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.StaticDischarge_Tonic',             'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.TurretHackHealth_Tonic',            'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.VendingExpert_Tonic',               'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.VendingExpert2_Tonic',              'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.WalkingInferno_Tonic',              'Pickups.MedHypo_Pickup', 1, 1),
    ('Tonics.WaterHealthRestoration_Tonic',      'Pickups.MedHypo_Pickup', 1, 1),
    ('DLCPlasmids.DaddyDash_Tonic',              'Pickups.MedHypo_Pickup', 1, 1),
    ('DLCPlasmids.MasterProtector_Tonic',        'Pickups.MedHypo_Pickup', 1, 1),
]

# Level labels for vending section grouping
VENDING_LEVEL_MAP = OrderedDict([
    ('Ryan Amusements',    'Education'),
    ('Pauper\'s Drop',     'Ghetto'),
    ('Siren Alley',        'Redlight'),
    ('Dionysus Park',      'Gallery'),
    ('Fontaine Futuristics', 'Abyss'),
    ('Persephone',         'Gulag'),
    ('Inner Persephone',   'Eden'),
    ('Adonis Baths',       'WelcomeBack'),
    ('Atlantic Express',   'Prelude'),
    ('Outer Persephone',   'Redlight2'),
])

GROWTH_LEVEL_MAP = OrderedDict([
    ('Atlantic Express',   'Prelude'),
    ('Adonis Baths',       'WelcomeBack'),
    ('Ryan Amusements',    'Education'),
    ('Pauper\'s Drop',     'Ghetto'),
    ('Siren Alley',        'Redlight'),
    ('Dionysus Park',      'Gallery'),
    ('Fontaine Futuristics', 'Abyss'),
    ('Persephone',         'Gulag'),
    ('Inner Persephone',   'Eden'),
    ('Minerva\'s Den 1',   'MinervaA'),
    ('Minerva\'s Den 2',   'MinervaB'),
    ('Minerva\'s Den 3',   'MinervaC'),
    ('Outer Persephone',   'Redlight2'),
])


def _vending_friendly(item_class):
    """Get friendly name for a vending item class."""
    if item_class in VENDING_ITEM_NAMES:
        return VENDING_ITEM_NAMES[item_class]
    short = item_class.split('.')[-1]
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', short)
    name = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', name)
    return name.replace('_', ' ')


def _make_vending_line(item_cls, pickup_cls, stack, cost, unhacked=True, hacked=True,
                      supply_size=None):
    """Build a VendingLootSpec line.
    supply_size: required for Growth (Gatherer's Garden) entries — omit for vending.
    """
    base = (
        "(ItemClass=class'%s',"
        "PickupClass=class'%s',"
        "StackSize=%d,CostAdjustment=%s,"
        "DisplayWhenUnHacked=%s,DisplayWhenHacked=%s"
        % (item_cls, pickup_cls, stack, cost,
           'True' if unhacked else 'False',
           'True' if hacked else 'False'))
    if supply_size is not None:
        base += ',SupplySize=%d' % supply_size
    return base + ')'


def read_vending_data(entries):
    """Read all vending machine and Gatherer's Garden data.

    Returns {
        'vending_sections': OrderedDict of {sec_name: [spec, ...]},
        'growth_sections': OrderedDict of {sec_name: [spec, ...]},
        'circus_sections': OrderedDict of {sec_name: [spec, ...]},
        'vending_items': unique items across vending (collapsed list),
        'growth_items': unique items across growth (collapsed list),
    }
    Each spec: {item, pickup, friendly, cost, stack, unhacked, hacked, entry_idx}
    """
    item_re = re.compile(r"ItemClass=class'([^']+)'")
    pickup_re = re.compile(r"PickupClass=class'([^']+)'")
    cost_re = re.compile(r'CostAdjustment=([\d.]+)')
    stack_re = re.compile(r'StackSize=(\d+)')

    vending = OrderedDict()
    growth = OrderedDict()
    circus = OrderedDict()

    for idx, (sec, key, val, raw) in enumerate(entries):
        if key != 'VendingLootSpec' or not val:
            continue
        im = item_re.search(val)
        pm = pickup_re.search(val)
        cm = cost_re.search(val)
        sm = stack_re.search(val)
        if not im:
            continue

        spec = {
            'item': im.group(1),
            'pickup': pm.group(1) if pm else 'Pickups.MedHypo_Pickup',
            'friendly': _vending_friendly(im.group(1)),
            'cost': float(cm.group(1)) if cm else 1.0,
            'stack': int(sm.group(1)) if sm else 1,
            'unhacked': 'DisplayWhenUnHacked=True' in val,
            'hacked': 'DisplayWhenHacked=True' in val,
            'entry_idx': idx,
        }

        sl = sec.lower()
        if 'test' in sl:
            continue
        if 'growth' in sl:
            growth.setdefault(sec, []).append(spec)
        elif 'circus' in sl or 'ammo' in sl:
            circus.setdefault(sec, []).append(spec)
        elif 'vending' in sl:
            vending.setdefault(sec, []).append(spec)

    # Build collapsed unique-item lists (lowest cost wins for duplicates)
    def collapse(sections):
        best = OrderedDict()
        for sec, specs in sections.items():
            for sp in specs:
                key = sp['item']
                if key not in best or sp['cost'] < best[key]['cost']:
                    best[key] = dict(sp)
        return list(best.values())

    return {
        'vending_sections': vending,
        'growth_sections': growth,
        'circus_sections': circus,
        'vending_items': collapse(dict(list(vending.items()) + list(circus.items()))),
        'growth_items': collapse(growth),
    }


def patch_vending_unlock_all(entries, unlock_vending=True, unlock_growth=True):
    """Unlock all items in every vending machine and/or Gatherer's Garden.

    1. Sets DisplayWhenUnHacked=True and DisplayWhenHacked=True on all entries.
    2. For duplicate items in the same section, keeps only one (lowest cost).
    3. Injects missing items from the master list into every section.

    Returns (vending_added, growth_added) count of new entries injected.
    """
    item_re = re.compile(r"ItemClass=class'([^']+)'")

    # Pass 1: unlock all display flags (vending/circus/ammo only — not Growth,
    # because the Garden has no hack state and flipping these breaks rendering)
    for i, (sec, key, val, raw) in enumerate(entries):
        if key != 'VendingLootSpec' or not val:
            continue
        if 'Growth' in sec:
            continue
        changed = False
        if 'DisplayWhenUnHacked=False' in val:
            val = val.replace('DisplayWhenUnHacked=False', 'DisplayWhenUnHacked=True')
            changed = True
        if 'DisplayWhenHacked=False' in val:
            val = val.replace('DisplayWhenHacked=False', 'DisplayWhenHacked=True')
            changed = True
        if changed:
            entries[i] = (sec, key, val, '%s=%s' % (key, val))

    # Pass 2: deduplicate per section — keep lowest cost entry, blank others
    from collections import defaultdict
    cost_re = re.compile(r'CostAdjustment=([\d.]+)')
    groups = defaultdict(list)
    for idx, (sec, key, val, raw) in enumerate(entries):
        if key != 'VendingLootSpec' or not val:
            continue
        im = item_re.search(val)
        cm = cost_re.search(val)
        if im and cm:
            groups[(sec, im.group(1))].append((idx, float(cm.group(1))))

    removed = 0
    for key, variants in groups.items():
        if len(variants) <= 1:
            continue
        variants.sort(key=lambda x: x[1])
        for idx, cost in variants[1:]:
            entries[idx] = (entries[idx][0], None, None, '')
            removed += 1

    # Pass 3: inject missing items
    # Build set of existing items per section
    existing = defaultdict(set)
    section_last_idx = {}
    for idx, (sec, key, val, raw) in enumerate(entries):
        if sec:
            section_last_idx[sec] = idx
        if key == 'VendingLootSpec' and val:
            im = item_re.search(val)
            if im:
                existing[sec].add(im.group(1))

    v_added = 0
    g_added = 0

    if unlock_vending:
        vending_secs = [sec for sec in section_last_idx
                        if ('Vending' in sec or 'Circus' in sec
                            or 'Ammo' in sec)
                        and 'Test' not in sec]
        for sec in vending_secs:
            insert_at = section_last_idx[sec] + 1
            for item_cls, pickup_cls, stack, cost in VENDING_MASTER:
                if item_cls not in existing[sec]:
                    line = _make_vending_line(item_cls, pickup_cls, stack, cost)
                    entries.insert(insert_at,
                                   (sec, 'VendingLootSpec', line,
                                    'VendingLootSpec=%s' % line))
                    existing[sec].add(item_cls)
                    # Update indices after insertion
                    for s2 in section_last_idx:
                        if section_last_idx[s2] >= insert_at:
                            section_last_idx[s2] += 1
                    insert_at += 1
                    v_added += 1

    if unlock_growth:
        # DLC items only valid in Minerva's Den levels; research-only tonics
        # also only appear in Minerva/Test sections in stock.
        _DLC_ONLY_ITEMS = {
            'DLCPlasmids.BioGrenadeAdvancedPlasmid',
            'DLCPlasmids.BioGrenadeMasterPlasmid',
            'DLCPlasmids.DLCSecurityCommandAdvancedPlasmid',
            'DLCPlasmids.DLCSecurityCommandMasterPlasmid',
            'DLCPlasmids.DaddyDash_Tonic',
            'DLCPlasmids.MasterProtector_Tonic',
            'Tonics.AmmoSalvageIncrease_Tonic',
            'Tonics.Bloodlust_Tonic',
            'Tonics.ElementalLifeDrain_Tonic',
            'Tonics.MachineDamageIncrease_Tonic',
            'Tonics.NaturalCamouflage_Tonic',
            'Tonics.Scrounger_Tonic',
            'Tonics.WaterHealthRestoration_Tonic',
        }
        growth_secs = [sec for sec in section_last_idx
                       if 'Growth' in sec and 'Test' not in sec]
        for sec in growth_secs:
            is_minerva = 'Minerva' in sec
            insert_at = section_last_idx[sec] + 1
            for item_cls, pickup_cls, stack, cost in GROWTH_MASTER:
                if item_cls not in existing[sec]:
                    if not is_minerva and item_cls in _DLC_ONLY_ITEMS:
                        continue
                    line = _make_vending_line(item_cls, pickup_cls, stack, cost,
                                              supply_size=1)
                    entries.insert(insert_at,
                                   (sec, 'VendingLootSpec', line,
                                    'VendingLootSpec=%s' % line))
                    existing[sec].add(item_cls)
                    for s2 in section_last_idx:
                        if section_last_idx[s2] >= insert_at:
                            section_last_idx[s2] += 1
                    insert_at += 1
                    g_added += 1

    return v_added, g_added


def patch_vending_costs(entries, multiplier, table_type='all'):
    """Multiply CostAdjustment on all VendingLootSpec entries.

    table_type: 'vending', 'growth', or 'all'
    Returns number of entries patched.
    """
    cost_re = re.compile(r'(CostAdjustment=)([\d.]+)')
    count = 0
    for i, (sec, key, val, raw) in enumerate(entries):
        if key != 'VendingLootSpec' or not val:
            continue
        sl = sec.lower()
        if 'test' in sl:
            continue
        is_growth = 'growth' in sl
        is_vending = 'vending' in sl or 'circus' in sl or 'ammo' in sl
        if table_type == 'vending' and not is_vending:
            continue
        if table_type == 'growth' and not is_growth:
            continue
        m = cost_re.search(val)
        if m:
            old = float(m.group(2))
            new = round(old * multiplier, 4)
            new_val = val[:m.start(2)] + str(new) + val[m.end(2):]
            entries[i] = (sec, key, new_val, '%s=%s' % (key, new_val))
            count += 1
    return count


def patch_vending_item_cost(entries, item_class, new_cost, table_type='all'):
    """Set CostAdjustment for a specific item across all matching sections.

    table_type: 'vending', 'growth', or 'all'
    Returns number of entries patched.
    """
    item_pat = "class'%s'" % item_class
    cost_re = re.compile(r'(CostAdjustment=)([\d.]+)')
    count = 0
    for i, (sec, key, val, raw) in enumerate(entries):
        if key != 'VendingLootSpec' or not val:
            continue
        if item_pat not in val:
            continue
        sl = sec.lower()
        if 'test' in sl:
            continue
        is_growth = 'growth' in sl
        is_vending = 'vending' in sl or 'circus' in sl or 'ammo' in sl
        if table_type == 'vending' and not is_vending:
            continue
        if table_type == 'growth' and not is_growth:
            continue
        m = cost_re.search(val)
        if m:
            new_val = val[:m.start(2)] + str(new_cost) + val[m.end(2):]
            entries[i] = (sec, key, new_val, '%s=%s' % (key, new_val))
            count += 1
    return count


# ─── Enemy loot grouping ────────────────────────────────────────────────────

ENEMY_LOOT_GROUPS = OrderedDict([
    ('Splicer (Pistol)',    ['HumanAggressorPistol_A', 'HumanAggressorPistol_B', 'HumanAggressorPistol_C']),
    ('Splicer (SMG)',       ['HumanAggressorSMG_A', 'HumanAggressorSMG_B', 'HumanAggressorSMG_C']),
    ('Splicer (Shotgun)',   ['HumanAggressorShotgun_A', 'HumanAggressorShotgun_B', 'HumanAggressorShotgun_C']),
    ('Ceiling Crawler',     ['CeilingCrawler_A', 'CeilingCrawler_B', 'CeilingCrawler_C']),
    ('Brute',               ['Brute_A', 'Brute_B', 'Brute_C']),
    ('Bouncer',             ['Bouncer_A', 'Bouncer_B', 'Bouncer_C']),
    ('Rosie',               ['Rosie_A', 'Rosie_B', 'Rosie_C']),
])


# ─── Load all configs from IBF ──────────────────────────────────────────────

def load_all_configs(ibf_path):
    """Extract IBF and parse all INI files into {filename: entries} dict."""
    from core.ibf_utils import extract_ibf
    raw_files = extract_ibf(ibf_path)
    configs = {}
    for name, text in raw_files.items():
        configs[name] = parse_ini(text)
    return configs, raw_files
