"""
The War In Rapture: BioShock 2 — Scripted Encounter Spawn Patcher
==================================================================
Binary-patches BioShock 2 Remastered .bsm map files to add extra spawns
to Kismet scripted encounters (one-time triggers like ambushes and story
events).

How scripted encounters work in BioShock 2:
  - Each level has Script objects containing Actions arrays.
  - ActionSpawnAI actions within those arrays each spawn one enemy of a
    specified AI type at a named spawn location when triggered.
  - These are ONE-TIME spawns — they fire once when the player enters
    a trigger zone or hits a story beat.

What this patcher does:
  1. Parses the BSM package to find all Script exports and their
     ActionSpawnAI child actions (via the parentScript property).
  2. Groups actions by parent Script label to identify encounters.
  3. Provides encounter analysis for the GUI.

BioShock 2 BSM specifics:
  - Package version 143 / licensee 59
  - Script serial header skip varies (auto-detected 50-74)
  - ActionSpawnAI serial starts with ACTION_HEADER (8 bytes)
  - Properties start at offset 8 in action serial
"""
import struct
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.bsm_parser import (
    read_compact_index, write_compact_index, read_name_ref,
    parse_properties, parse_package
)

# ActionSpawnAI header (all action objects start with this)
ACTION_HEADER = b'\x04\x00\x00\x00\x03\x00\x00\x00'

# AI type prefixes that indicate real enemy spawns (not FX, quest markers, etc.)
AI_SPAWN_PREFIXES = (
    'Spawned',
)

# Classes to exclude from encounter listing (story-critical, gatherer/protector)
EXCLUDE_SCRIPTS = {
    'LittleSisterFX_Script',
    'NAR_StartHarvestA', 'NAR_StartHarvestB', 'NAR_StartHarvestC',
    'NAR_StartHarvestD', 'NAR_StartHarvestE', 'NAR_StartHarvestF',
    'NAR_StartSaveA', 'NAR_StartSaveB', 'NAR_StartSaveC',
    'NAR_StartSaveD', 'NAR_StartSaveE', 'NAR_StartSaveF',
    # FX / narrative / atmospheric scripts (not real combat)
    'ElectricFidgetFX', 'BulletDecalGlassB', 'ForceShape',
    'ChangeYourDifficulty', 'SCRIPT_BigSisBreakOut_Anim',
    'A_Marker_SFX', 'GA_Gatherer_PickupIdle_Evil',
    'ShockPlayerPlasmidEquipped_VulnerabilityKnowledge_spec',
    'LancerFlashBurstWeapon', 'BouncingBallScript',
    'NAR_SC_StartGrace',
    # Big Sister one-time story encounters (multiplying spawns clones that
    # get stuck in geometry / ocean floor behind glass)
    'BigSisterAttack',
    'QuestLine_GetLockdownKey',
    'Moment_BigSisFutureScare',
    'Moment_SpawnBigSis',
}
# AI types excluded from encounter multiplication.
# Checked as both base_ai (split on '_')[0] AND full ai_type name.
EXCLUDE_AI_TYPES = {
    'SpawnedPlayerEscortedGatherer',
    'SpawnedGatherer',
    # Big Sister encounters — single boss spawns, clones get stuck in geometry
    'SpawnedBigSister',
    # Father Wales quest NPC — duplicating causes door-relock softlock in
    # Siren Alley / Pink Pearl (full-name match, not base_ai)
    'SpawnedHumanAggressorShotgun_RedLight_Pimp_Quest',
}

# Short names for AI types
AI_SHORT = {
    'SpawnedMeleeThug':              'Melee Thug',
    'SpawnedHumanAggressorPistol':   'Pistol Splicer',
    'SpawnedHumanAggressorSMG':      'SMG Splicer',
    'SpawnedHumanAggressorShotgun':  'Shotgun Splicer',
    'SpawnedCeilingCrawler':         'Ceiling Crawler',
    'SpawnedBouncer':                'Bouncer',
    'SpawnedRosie':                  'Rosie',
    'SpawnedBrute':                  'Brute',
    'SpawnedBigSister':              'Big Sister',
    'SpawnedRumbler':                'Rumbler',
    'SpawnedAlphaSeries':            'Alpha Series',
    'SpawnedMadDaddy':               'Alpha Daddy',
    'SpawnedLancer':                 'Lancer',
    'SpawnedAssassin':               'Houdini',
    'SpawnedMagicAssassin':          'Houdini',
    'SpawnedSPF':                    'Big Daddy (SPF)',
    'SpawnedScriptedAI':             'Scripted AI',
}


def short_ai(name):
    """Get short display name for an AI type."""
    # Try exact match first
    if name in AI_SHORT:
        return AI_SHORT[name]
    # Try prefix match (e.g. SpawnedMeleeThug_Ghetto_Lemming -> Melee Thug)
    for prefix, short in AI_SHORT.items():
        if name.startswith(prefix):
            return short
    # Strip 'Spawned' prefix
    if name.startswith('Spawned'):
        return name[7:]
    return name


def _is_clean_label(s):
    """Check if a label string is clean ASCII (not corrupted by name table encoding)."""
    try:
        return all(32 <= ord(c) < 127 for c in s) and len(s) > 0
    except (TypeError, UnicodeError):
        return False


def _get_script_label(data, exp, names):
    """Extract the Label property from a Script export's serial data."""
    s_serial = data[exp['offset']:exp['offset'] + exp['size']]
    for skip in range(50, 75):
        try:
            sprops = parse_properties(s_serial, skip, names, len(s_serial))
            for sp in sprops:
                if sp[0] == 'Label' and sp[2] == 'Name' and len(sp[5]) >= 5:
                    ni, _ = read_compact_index(sp[5], 0)
                    if 0 <= ni < len(names):
                        label = names[ni]
                        if _is_clean_label(label):
                            return label
        except Exception:
            continue
    return None


def get_map_encounter_info(filepath):
    """Analyze scripted encounters in a BSM file.

    Returns:
      encounters: {label: {'spawns': int, 'ai_types': [str, ...]}}
      ai_types: set of all AI type export names in the map
    """
    pkg = parse_package(filepath)
    names = pkg['names']
    exports = pkg['exports']

    with open(filepath, 'rb') as f:
        data = f.read()

    # Find AITypeToSpawn name index
    ai_type_ni = None
    for i, n in enumerate(names):
        if n == 'AITypeToSpawn':
            ai_type_ni = i
            break
    if ai_type_ni is None:
        return {}, set()

    # Find all ActionSpawnAI exports
    encounters = {}
    all_ai_types = set()

    for ei, e in enumerate(exports):
        if e['size'] < 20:
            continue
        serial = data[e['offset']:e['offset'] + e['size']]
        if len(serial) < 14 or serial[:8] != ACTION_HEADER:
            continue
        try:
            ni, _ = read_compact_index(serial, 8)
            if ni != ai_type_ni:
                continue
        except Exception:
            continue

        props = parse_properties(serial, 8, names, len(serial))
        ai_type = None
        script_label = None

        for prop in props:
            if prop[0] == 'AITypeToSpawn' and prop[2] == 'Object':
                ref, _ = read_compact_index(prop[5], 0)
                if ref > 0 and ref <= len(exports):
                    ai_type = exports[ref - 1]['name']
            elif prop[0] == 'parentScript' and prop[2] == 'Object':
                ref, _ = read_compact_index(prop[5], 0)
                if ref > 0 and ref <= len(exports):
                    script_label = _get_script_label(data, exports[ref - 1], names)

        # Filter: only real AI spawns with clean names
        if ai_type and any(ai_type.startswith(p) for p in AI_SPAWN_PREFIXES):
            if not _is_clean_label(ai_type):
                continue
            # Skip excluded
            if script_label in EXCLUDE_SCRIPTS:
                continue
            base_ai = ai_type.split('_')[0]
            if base_ai in EXCLUDE_AI_TYPES or ai_type in EXCLUDE_AI_TYPES:
                continue

            all_ai_types.add(ai_type)

            if script_label is None or not _is_clean_label(script_label):
                script_label = '(unknown)'
            if script_label not in encounters:
                encounters[script_label] = {'spawns': 0, 'ai_types': []}
            encounters[script_label]['spawns'] += 1
            encounters[script_label]['ai_types'].append(short_ai(ai_type))

    return encounters, all_ai_types


# ─── Patching Helpers ─────────────────────────────────────────────────────────

def patch_spawned_ai_label(serial, names, new_name_num):
    """Patch the SpawnedAILabel name_number in an action's serial data.
    Each clone needs a unique SpawnedAILabel so the engine doesn't skip it."""
    props = parse_properties(serial, 8, names, len(serial))
    for p in props:
        if p[0] == 'SpawnedAILabel' and p[2] == 'Name':
            val_pos = p[7]
            ni, after_ni = read_compact_index(serial, val_pos)
            patched = bytearray(serial)
            struct.pack_into('<I', patched, after_ni, new_name_num)
            old_nn = struct.unpack_from('<I', serial, after_ni)[0]
            label_name = names[ni] if 0 <= ni < len(names) else '?'
            return bytes(patched), '%s_%d' % (label_name, old_nn)
    return serial, None


def parse_script_actions(serial, names):
    """Parse a Script's properties to find the Actions array data.
    Tries skip values 50-74 for BS2's variable header skip."""
    for skip in range(50, 75):
        try:
            props = parse_properties(serial, skip, names, len(serial))
            for p in props:
                if p[0] == 'Actions' and p[2] == 'Array':
                    arr_data = p[5]
                    pos = 0
                    count, pos = read_compact_index(arr_data, pos)
                    refs = []
                    for _ in range(count):
                        ref, pos = read_compact_index(arr_data, pos)
                        refs.append(ref)
                    return {
                        'tag_offset': p[6],
                        'value_offset': p[7],
                        'value_end': p[7] + p[3],
                        'data_size': p[3],
                        'refs': refs,
                        'raw': arr_data,
                        'skip': skip,
                    }
        except Exception:
            continue
    return None


def encode_actions_array(refs):
    """Encode an Actions array as bytes: count + compact_index refs."""
    result = bytearray()
    result.extend(write_compact_index(len(refs)))
    for ref in refs:
        result.extend(write_compact_index(ref))
    return bytes(result)


def encode_size_field(size, old_info_byte):
    """Encode the property size field, returning (new_info_byte, size_bytes)."""
    type_bits = old_info_byte & 0x0F
    array_bit = old_info_byte & 0x80

    if size <= 0:
        return (array_bit | type_bits), b''
    elif size == 1:
        return (array_bit | (0 << 4) | type_bits), b''
    elif size == 2:
        return (array_bit | (1 << 4) | type_bits), b''
    elif size == 4:
        return (array_bit | (2 << 4) | type_bits), b''
    elif size == 12:
        return (array_bit | (3 << 4) | type_bits), b''
    elif size == 16:
        return (array_bit | (4 << 4) | type_bits), b''
    elif size <= 255:
        return (array_bit | (5 << 4) | type_bits), struct.pack('B', size)
    elif size <= 65535:
        return (array_bit | (6 << 4) | type_bits), struct.pack('<H', size)
    else:
        return (array_bit | (7 << 4) | type_bits), struct.pack('<I', size)


def rebuild_script_serial(old_serial, actions_info, new_refs, names):
    """Rebuild a Script's serial data with an expanded Actions array."""
    skip = actions_info['skip']
    new_array_data = encode_actions_array(new_refs)
    new_size = len(new_array_data)

    props = parse_properties(old_serial, skip, names, len(old_serial))
    for p in props:
        if p[0] != 'Actions' or p[2] != 'Array':
            continue

        tag_pos = p[6]
        value_pos = p[7]
        old_data_size = p[3]
        value_end = value_pos + old_data_size

        ni, pos2 = read_compact_index(old_serial, tag_pos)
        pos2 += 4  # skip name_number INT32
        info_byte_pos = pos2
        old_info = old_serial[info_byte_pos]

        new_info, new_size_bytes = encode_size_field(new_size, old_info)
        old_size_enum = (old_info >> 4) & 0x07

        if old_size_enum == 5:
            old_size_field_len = 1
        elif old_size_enum == 6:
            old_size_field_len = 2
        elif old_size_enum == 7:
            old_size_field_len = 4
        else:
            old_size_field_len = 0

        new_serial = bytearray()
        new_serial.extend(old_serial[:info_byte_pos])
        new_serial.append(new_info)
        new_serial.extend(new_size_bytes)
        new_serial.extend(new_array_data)
        new_serial.extend(old_serial[value_end:])

        return bytes(new_serial)

    return old_serial


# ─── Main Patching Function ──────────────────────────────────────────────────

def patch_map_encounters(filepath, script_multipliers, dry_run=False):
    """Patch a BSM file to multiply scripted encounter spawns.

    Args:
        filepath: path to the .bsm file (should be pristine or freshly restored)
        script_multipliers: dict {script_label: multiplier_int} for encounters to boost
        dry_run: if True, don't write anything

    Returns:
        dict with 'new_count' or None if nothing to do
    """
    from core.bsm_spawn_patcher import full_parse_package, write_export_entry

    pkg = full_parse_package(filepath)
    exports = pkg['full_exports']
    names = pkg['names']
    data = pkg['data']
    map_name = os.path.basename(filepath)

    # Find ActionSpawnAI name index
    ai_type_ni = None
    for i, n in enumerate(names):
        if n == 'AITypeToSpawn':
            ai_type_ni = i
            break
    if ai_type_ni is None:
        return None

    # Find all ActionSpawnAI actions and their parent Scripts
    spawn_actions = []  # (export_index, ai_type, script_label, script_exp_idx)
    for ei, e in enumerate(exports):
        if e['size'] < 20:
            continue
        serial = e['serial_data']
        if len(serial) < 14 or serial[:8] != ACTION_HEADER:
            continue
        try:
            ni, _ = read_compact_index(serial, 8)
            if ni != ai_type_ni:
                continue
        except Exception:
            continue

        props = parse_properties(serial, 8, names, len(serial))
        ai_type = None
        script_exp_idx = None
        script_label = None

        for prop in props:
            if prop[0] == 'AITypeToSpawn' and prop[2] == 'Object':
                ref, _ = read_compact_index(prop[5], 0)
                if ref > 0 and ref <= len(exports):
                    ai_type = exports[ref - 1]['name']
            elif prop[0] == 'parentScript' and prop[2] == 'Object':
                ref, _ = read_compact_index(prop[5], 0)
                if ref > 0 and ref <= len(exports):
                    script_exp_idx = ref - 1
                    script_label = _get_script_label(data, exports[ref - 1], names)

        if ai_type and any(ai_type.startswith(p) for p in AI_SPAWN_PREFIXES):
            if not _is_clean_label(ai_type):
                continue
            if script_label in EXCLUDE_SCRIPTS:
                continue
            base_ai = ai_type.split('_')[0]
            if base_ai in EXCLUDE_AI_TYPES or ai_type in EXCLUDE_AI_TYPES:
                continue
            if script_label is None or not _is_clean_label(script_label):
                script_label = '(unknown)'
            spawn_actions.append({
                'exp_idx': ei,
                'ai_type': ai_type,
                'script_label': script_label,
                'script_exp_idx': script_exp_idx,
                'name_num': e['name_num'],
            })

    if not spawn_actions:
        return None

    # Build set of eligible action export indices
    eligible_set = set(sa['exp_idx'] for sa in spawn_actions)

    # Determine next available name_num for action clones
    # Use the ActionSpawnAI class_idx to find the max
    spawn_class_idx = exports[spawn_actions[0]['exp_idx']]['class_idx']
    max_name_num = 0
    for exp in exports:
        if exp['class_idx'] == spawn_class_idx:
            max_name_num = max(max_name_num, exp['name_num'])
    next_num = max_name_num + 1

    new_exports = []
    modified_serials = {}  # script_exp_idx -> new_serial
    total_new = 0

    # Walk all Script exports, find those with eligible spawn actions
    for si, script_exp in enumerate(exports):
        if script_exp['name'] != 'Script' or script_exp['size'] < 60:
            continue

        old_serial = script_exp['serial_data']
        actions_info = parse_script_actions(old_serial, names)
        if actions_info is None or not actions_info['refs']:
            continue

        # Get script label for this Script
        label = _get_script_label(data, script_exp, names)
        if label is None or not _is_clean_label(label):
            label = '(unknown)'

        # Check if any ref in Actions is an eligible spawn action
        spawn_refs = []
        for ref in actions_info['refs']:
            exp_idx = ref - 1
            if exp_idx in eligible_set:
                spawn_refs.append((ref, exp_idx))

        if not spawn_refs:
            continue

        # Get multiplier for this encounter
        mult = script_multipliers.get(label, 1)
        if mult <= 1:
            continue

        dups_per_action = mult - 1
        new_refs_for_script = []

        for src_ref, src_exp_idx in spawn_refs:
            src_exp = exports[src_exp_idx]
            src_serial = src_exp['serial_data']

            for dup_idx in range(dups_per_action):
                new_serial = bytearray(src_serial)

                # Patch SpawnedAILabel to unique name_number
                patched, old_label = patch_spawned_ai_label(
                    bytes(new_serial), names, next_num)
                new_serial = bytearray(patched)

                new_exp = {
                    'name': src_exp['name'],
                    'name_idx': src_exp['name_idx'],
                    'name_num': next_num,
                    'class_idx': src_exp['class_idx'],
                    'super_idx': src_exp['super_idx'],
                    'outer_idx': src_exp['outer_idx'],
                    'unknown1': src_exp.get('unknown1', 0),
                    'flags': src_exp.get('flags', 0),
                    'size': len(new_serial),
                    'offset': 0,
                    'unknown2': src_exp.get('unknown2', 0),
                    'serial_data': bytes(new_serial),
                }

                new_exports.append(new_exp)
                new_ref = len(exports) + len(new_exports)
                new_refs_for_script.append(new_ref)

                next_num += 1
                total_new += 1

        # Rebuild this Script's serial with expanded Actions
        all_refs = list(actions_info['refs']) + new_refs_for_script
        new_script_serial = rebuild_script_serial(old_serial, actions_info, all_refs, names)
        modified_serials[si] = new_script_serial

    if not new_exports:
        return None

    if dry_run:
        return {'new_count': total_new}

    # ─── Write patched BSM ────────────────────────────────────────────
    output = bytearray(pkg['prefix_raw'])

    # Append modified Script serials
    for si_idx, new_serial in modified_serials.items():
        exports[si_idx]['offset'] = len(output)
        exports[si_idx]['size'] = len(new_serial)
        exports[si_idx]['serial_data'] = new_serial
        exports[si_idx]['raw_entry'] = write_export_entry(exports[si_idx], data)
        output += new_serial

    # Append new action serial data
    for ne in new_exports:
        ne['offset'] = len(output)
        output += ne['serial_data']

    # Pad to 4-byte alignment
    while len(output) % 4 != 0:
        output += b'\x00'

    # Append tables
    new_name_offset = len(output)
    output += pkg['name_table_raw']

    new_import_offset = len(output)
    output += pkg['import_table_raw']

    new_export_offset = len(output)

    # Write export table
    for exp in exports:
        output += exp['raw_entry']
    for ne in new_exports:
        output += write_export_entry(ne, data)

    new_export_count = len(exports) + len(new_exports)

    # Patch header
    struct.pack_into('<I', output, 16, new_name_offset)
    struct.pack_into('<I', output, 20, new_export_count)
    struct.pack_into('<I', output, 24, new_export_offset)
    struct.pack_into('<I', output, 32, new_import_offset)
    struct.pack_into('<I', output, 56, new_export_count)  # Gen[0].ExportCount

    # Write patched file
    with open(filepath, 'wb') as f:
        f.write(output)

    return {'new_count': total_new}
