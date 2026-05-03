"""
The War In Rapture: BioShock 2 — Repopulation Spawner Duplicator
=================================================================
Binary-patches BioShock 2 Remastered .bsm map files to duplicate the
placed AggressorSpawner, ProtectorSpawner, SecurityBotSpawner,
TurretSpawner and SecurityCameraSpawner actors that control the
repopulation and security systems.

How repopulation works in BioShock 2:
  - Each map contains placed AggressorSpawner actors at fixed positions.
  - The engine periodically respawns enemies at these points when the
    player is far enough away.
  - Each spawner = ONE spawn point.  There is no "count" property.
  - To increase enemy density, we must duplicate the spawner actors
    themselves within the BSM package's export table.

What this patcher does:
  1. Parses the BSM package (names, imports, exports) via bsm_parser.
  2. Identifies all AggressorSpawner, ProtectorSpawner,
     SecurityBotSpawner, TurretSpawner and SecurityCameraSpawner exports.
  3. For each spawner, creates (multiplier-1) cloned export entries
     with slightly offset positions to avoid stacking.
  4. Appends cloned serial data to the end of the file.
  5. Rewrites the package header with updated export count and offsets.

The multiplier creates (multiplier-1) duplicates per spawner:
    2x = 1 duplicate per spawner (doubles the spawner count)
    3x = 2 duplicates per spawner (triples the spawner count)

Position adjustments:
    After testing, edit bsm_spawn_adjustments.json to tweak positions
    of individual spawners that ended up in invalid locations.

BioShock 2 BSM differences vs BioShock 1:
  - Package version 143 / licensee 59 (BS1 = 142 / 56)
  - Spawner serial header skip = 65 bytes (BS1 = 57)
  - Otherwise binary layout is identical.
"""
import struct
import sys
import os
import json
import shutil
import math
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.bsm_parser import (
    read_compact_index, write_compact_index, read_name_ref,
    parse_properties, parse_package
)

# ─── Config ──────────────────────────────────────────────────────────────────
def _get_game_root():
    settings_file = Path(__file__).resolve().parent.parent / "settings.json"
    if settings_file.exists():
        try:
            with open(settings_file, 'r') as f:
                gr = json.load(f).get('game_root')
                if gr:
                    return Path(gr)
        except Exception:
            pass
    return Path(r"D:\SteamLibrary\steamapps\common\BioShock 2 Remastered")

GAME_ROOT = _get_game_root()
MAPS_DIR = GAME_ROOT / "ContentBaked" / "pc" / "Maps"
BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups" / "maps"
ADJUSTMENTS_FILE = Path(__file__).resolve().parent.parent / "bsm_spawn_adjustments.json"
REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"

SPAWNER_CLASSES = ['AggressorSpawner', 'ProtectorSpawner', 'SecurityCameraSpawner']
POSITION_OFFSET = 150.0   # units to offset duplicated spawners
MIN_Z_OFFSET = 0.0        # vertical offset (0 = same floor level)

# PlacedBooty subclasses that are NOT combat enemies (dead bodies, props, FX)
PLACED_EXCLUDE_PREFIXES = (
    'Dead', 'MedBot', 'FX_', 'AS_', 'RideScene', 'Eve', 'light',
)

# BioShock 2 maps have no language suffixes on .bsm filenames
SKIP_MAPS = ('Entry',)

# Map display names
MAP_NAMES = {
    'Abyss':                   'Fontaine Futuristics',
    'Eden':                    'Inner Persephone',
    'Eden_CellBlock':          'Persephone - Cell Block',
    'Education':               'Ryan Amusements',
    'Gallery':                 'Dionysus Park',
    'GalleryCarousel':         'Dionysus Park - Carousel',
    'Ghetto':                  'Pauper\'s Drop',
    'GhettoMarket':            'Pauper\'s Drop - Market',
    'Gulag':                   'Outer Persephone',
    'Minerva_A':               'Minerva\'s Den - A',
    'Minerva_B':               'Minerva\'s Den - B',
    'Minerva_C':               'Minerva\'s Den - C',
    'Prelude-2':               'Adonis Luxury Resort',
    'PreludePool':             'Adonis - Pool',
    'Redlight':                'Siren Alley',
    'RedlightChurch':          'Siren Alley - Church',
    'WelcomeBack':             'Atlantic Express',
    'WelcomeBackMaintenance':  'Atlantic Express - Maintenance',
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def detect_header_skip(data, offset, size, names):
    """Auto-detect the header byte count before properties start.

    BioShock 2 spawners typically use skip=65 (BS1 used 57).
    """
    best_skip = 65
    best_score = 0
    KNOWN_PROPS = {'Tag', 'Location', 'Rotation', 'Label', 'Region', 'Level',
                   'SpawnZones', 'RepopulationPatrol', 'RepopulationAITypes',
                   'OwnerGroups', 'PhysicsVolume', 'CheckpointTypePadding',
                   'RepopulationGroupLabel', 'GroupLabel',
                   'bAggressorRepopulationEnabled', 'bProtectorRepopulationEnabled',
                   'SecurityBotType', 'ForScriptedSpawn', 'HackInfoName', 'Mesh'}
    for skip in range(50, 80):
        if skip >= size:
            continue
        try:
            props = parse_properties(data, offset + skip, names, offset + size)
            named = [p for p in props if p[0] != 'None' and p[1] != 0]
            score = sum(1 for p in named if p[0] in KNOWN_PROPS)
            if score > best_score:
                best_score = score
                best_skip = skip
        except Exception:
            continue
    return best_skip


def get_spawner_location(data, offset, size, names, skip):
    """Extract Location vector from a spawner's serial data."""
    props = parse_properties(data, offset + skip, names, offset + size)
    for p in props:
        if p[0] == 'Location' and p[2] == 'Struct' and p[3] == 12:
            vdata = p[5]
            x, y, z = struct.unpack_from('<fff', vdata, 0)
            return (x, y, z), p[7]
    return None, None


def get_spawner_info(data, offset, size, names, skip):
    """Extract key properties from a spawner for reporting."""
    props = parse_properties(data, offset + skip, names, offset + size)
    info = {}
    for p in props:
        if p[0] == 'None':
            break
        if p[0] == 'Location' and p[2] == 'Struct' and p[3] == 12:
            x, y, z = struct.unpack_from('<fff', p[5], 0)
            info['location'] = (x, y, z)
            info['location_value_pos'] = p[7]
        elif p[0] == 'Rotation' and p[2] == 'Struct' and p[3] == 12:
            pitch, yaw, roll = struct.unpack_from('<iii', p[5], 0)
            info['rotation'] = (pitch, yaw, roll)
        elif p[0] == 'RepopulationPatrol' and p[2] == 'Name' and len(p[5]) >= 5:
            ni, _, _ = read_name_ref(p[5], 0)
            info['patrol'] = names[ni] if 0 <= ni < len(names) else '?'
        elif p[0] == 'Tag' and p[2] == 'Name' and len(p[5]) >= 5:
            ni, _, _ = read_name_ref(p[5], 0)
            info['tag'] = names[ni] if 0 <= ni < len(names) else '?'
        elif p[0] == 'SpawnZones' and p[2] == 'Array':
            info['has_spawn_zones'] = True
        elif p[0] == 'RepopulationAITypes' and p[2] == 'Array':
            info['has_ai_types'] = True
    info['prop_count'] = len([p for p in props if p[0] != 'None' and p[1] != 0])
    return info


def offset_position(x, y, z, index, total):
    """Generate an offset position using radial distribution."""
    angle = (2 * math.pi * index) / total
    dx = POSITION_OFFSET * math.cos(angle)
    dy = POSITION_OFFSET * math.sin(angle)
    dz = MIN_Z_OFFSET
    return (x + dx, y + dy, z + dz)


def write_export_entry(exp, data):
    """Serialize a single export table entry to bytes."""
    buf = bytearray()
    buf += write_compact_index(exp['class_idx'])
    buf += write_compact_index(exp['super_idx'])
    buf += struct.pack('<i', exp['outer_idx'])
    buf += struct.pack('<I', exp.get('unknown1', 0))
    buf += write_compact_index(exp['name_idx'])
    buf += struct.pack('<I', exp['name_num'])
    buf += struct.pack('<Q', exp.get('flags', 0))
    buf += write_compact_index(exp['size'])
    if exp['size'] > 0:
        buf += write_compact_index(exp['offset'])
    buf += struct.pack('<I', exp.get('unknown2', 0))
    return bytes(buf)


# ─── Level Actor List ────────────────────────────────────────────────────────

# BioShock 2 Level serial layout:
#   [0:N]      header (variable length, typically 33-34 bytes)
#   [N:N+4]    INT32  actor_count
#   [N+4:N+8]  INT32  actor_count (duplicate / allocated capacity)
#   [N+8:...]  compact_index[actor_count]  actor references (1-based export idx)
#   [end_of_list:...]  rest of Level data (URL, BSP geometry, etc.)
#
# The header length varies because it contains a variable-length compact
# index field.  Use _find_actor_list_offset() to auto-detect.


def _find_actor_list_offset(serial, num_exports):
    """Auto-detect where the actor count INT32 pair starts in Level serial.

    Searches for two consecutive identical INT32 values that represent a
    reasonable actor count (100 .. num_exports*2), followed by compact-index
    references that are mostly valid export indices.

    Returns the byte offset of the first count INT32, or None.
    """
    limit = min(80, len(serial) - 8)
    for off in range(20, limit):
        c1 = struct.unpack_from('<I', serial, off)[0]
        c2 = struct.unpack_from('<I', serial, off + 4)[0]
        if c1 != c2 or c1 < 10 or c1 > num_exports * 2:
            continue
        # Validate by reading the first few refs
        pos = off + 8
        valid = 0
        sample = min(20, c1)
        ok = True
        for _ in range(sample):
            try:
                ref, pos = read_compact_index(serial, pos)
                if 0 < ref <= num_exports:
                    valid += 1
            except Exception:
                ok = False
                break
        if ok and valid >= sample * 0.6:
            return off
    return None


def parse_level_actors(pkg):
    """Parse the Level export's actor list.

    Returns (level_exp_idx, actor_refs, actor_set, count_offset) where
    actor_refs is the ordered list of compact-index references, actor_set
    is the set of 1-based export indices that are placed actors, and
    count_offset is the byte offset of the actor count in the Level serial.
    Returns (None, [], set(), 0) if the Level export cannot be found.
    """
    exports = pkg['full_exports']
    imports = pkg['imports']
    data    = pkg['data']

    # Locate Level class in import table
    level_imp_idx = None
    for ii, imp in enumerate(imports):
        if imp == 'Level':
            level_imp_idx = ii
            break
    if level_imp_idx is None:
        return None, [], set(), 0

    # Locate the single Level export
    level_exp_idx = None
    for ei, e in enumerate(exports):
        if e['class_idx'] == -(level_imp_idx + 1) and e['size'] > 50:
            level_exp_idx = ei
            break
    if level_exp_idx is None:
        return None, [], set(), 0

    e = exports[level_exp_idx]
    serial = data[e['offset']:e['offset'] + e['size']]

    count_off = _find_actor_list_offset(serial, len(exports))
    if count_off is None:
        return level_exp_idx, [], set(), 0

    count = struct.unpack_from('<I', serial, count_off)[0]
    pos = count_off + 8   # skip both INT32 count fields
    refs = []
    for _ in range(count):
        ref, pos = read_compact_index(serial, pos)
        refs.append(ref)

    actor_set = set(r for r in refs if r > 0)
    return level_exp_idx, refs, actor_set, count_off


def rebuild_level_serial(old_serial, new_actor_refs, count_offset):
    """Rebuild Level serial data with an expanded (or changed) actor list.

    Preserves the header and everything after the original actor list
    (URL, BSP geometry, etc.).  *count_offset* is the byte position of
    the first actor-count INT32 (as returned by parse_level_actors).
    """
    old_count = struct.unpack_from('<I', old_serial, count_offset)[0]
    # Walk past the old list to find where the post-list data starts
    pos = count_offset + 8   # skip both INT32 count fields
    for _ in range(old_count):
        _, pos = read_compact_index(old_serial, pos)
    old_list_end = pos

    # Encode new list
    encoded_refs = bytearray()
    for ref in new_actor_refs:
        encoded_refs += write_compact_index(ref)

    new_count = len(new_actor_refs)
    new_serial = bytearray()
    new_serial += old_serial[:count_offset]                 # header
    new_serial += struct.pack('<I', new_count)              # count1
    new_serial += struct.pack('<I', new_count)              # count2
    new_serial += encoded_refs                              # actor refs
    new_serial += old_serial[old_list_end:]                 # rest of data
    return bytes(new_serial)


# ─── Core Functions ──────────────────────────────────────────────────────────

def full_parse_package(filepath):
    """Extended parse that preserves raw bytes for round-trip writing."""
    with open(filepath, 'rb') as f:
        data = f.read()

    pkg = parse_package(filepath)

    # Parse header fields we need to update
    name_offset = struct.unpack_from('<I', data, 16)[0]
    export_count = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    # Parse export table fully (need raw fields for writing back)
    full_exports = []
    pos = export_offset
    for i in range(export_count):
        entry_start = pos
        ci, pos = read_compact_index(data, pos)
        si, pos = read_compact_index(data, pos)
        oi = struct.unpack_from('<i', data, pos)[0]; pos += 4
        u1 = struct.unpack_from('<I', data, pos)[0]; pos += 4
        ni, pos = read_compact_index(data, pos)
        nn = struct.unpack_from('<I', data, pos)[0]; pos += 4
        fl = struct.unpack_from('<Q', data, pos)[0]; pos += 8
        sz, pos = read_compact_index(data, pos)
        so = 0
        if sz > 0:
            so, pos = read_compact_index(data, pos)
        u2 = struct.unpack_from('<I', data, pos)[0]; pos += 4
        entry_end = pos

        nm = pkg['names'][ni] if 0 <= ni < len(pkg['names']) else '?'
        full_exports.append({
            'index': i,
            'name': nm, 'name_idx': ni, 'name_num': nn,
            'class_idx': ci, 'super_idx': si, 'outer_idx': oi,
            'unknown1': u1, 'flags': fl,
            'size': sz, 'offset': so,
            'unknown2': u2,
            'serial_data': data[so:so+sz] if sz > 0 else b'',
            'raw_entry': data[entry_start:entry_end],
        })

    # Store raw table bytes
    import_table_raw = data[import_offset:export_offset]
    name_table_raw = data[name_offset:import_offset]
    prefix_raw = data[:name_offset]

    pkg['full_exports'] = full_exports
    pkg['data'] = data
    pkg['import_table_raw'] = import_table_raw
    pkg['name_table_raw'] = name_table_raw
    pkg['prefix_raw'] = prefix_raw
    pkg['name_offset'] = name_offset
    pkg['export_count'] = export_count
    pkg['export_offset'] = export_offset
    pkg['import_offset'] = import_offset

    return pkg


def analyze_map(filepath, verbose=True):
    """Analyze a BSM map file and report spawner information.

    Only counts spawner exports that are registered in the Level's actor
    list (i.e. actually placed in the map).  Default-object and archetype
    exports that happen to share the same class are excluded.
    """
    map_name = os.path.basename(filepath)

    if verbose:
        print()
        print("=" * 70)
        display = MAP_NAMES.get(Path(filepath).stem, map_name)
        print("  ANALYZING: %s  (%s)" % (map_name, display))
        print("=" * 70)

    pkg = full_parse_package(filepath)
    names = pkg['names']
    data = pkg['data']
    exports = pkg['full_exports']
    imports = pkg['imports']

    # Parse the Level actor list so we only consider placed actors
    level_exp_idx, actor_refs, actor_set, count_offset = parse_level_actors(pkg)
    pkg['level_exp_idx'] = level_exp_idx
    pkg['actor_refs'] = actor_refs
    pkg['actor_set'] = actor_set
    pkg['level_count_offset'] = count_offset

    def cls_name(ci):
        if ci > 0:
            return exports[ci-1]['name'] if ci <= len(exports) else '?'
        if ci < 0:
            return imports[(-ci)-1] if (-ci) <= len(imports) else '?'
        return 'class'

    spawner_data = {}
    for target_class in SPAWNER_CLASSES:
        spawners = []
        for i, exp in enumerate(exports):
            cn = cls_name(exp['class_idx'])
            if cn == target_class and exp['size'] > 0:
                # Only include spawners that are in the Level actor list
                if actor_set and (i + 1) not in actor_set:
                    continue
                skip = detect_header_skip(data, exp['offset'], exp['size'], names)
                info = get_spawner_info(data, exp['offset'], exp['size'], names, skip)
                info['export_index'] = i
                info['name_num'] = exp['name_num']
                info['header_skip'] = skip
                info['size'] = exp['size']
                spawners.append(info)
        spawner_data[target_class] = spawners

    # ── Detect placed enemy actors (PlacedBooty / Booty / Brute hierarchy) ──
    placed_classes = []
    if actor_set:
        # Identify class exports that represent placed enemies by:
        #   1. Class name ends with 'Booty' (e.g. BreadwinnerBooty, ButtonsBooty)
        #   2. Class name contains 'Brute' (e.g. DinerExteriorBrute)
        #   3. Class extends 'PlacedBooty' directly
        placed_booty_classes = {}  # class_exp_idx -> class_name
        for i, exp in enumerate(exports):
            if exp['class_idx'] != 0:
                continue  # only CLASS exports have class_idx==0
            cn = exp['name']
            if not cn.isascii():
                continue

            si = exp['super_idx']
            super_name = ''
            if si > 0 and si <= len(exports):
                super_name = exports[si-1]['name']
            elif si < 0 and (-si) <= len(imports):
                super_name = imports[(-si)-1]

            is_enemy = (cn.endswith('Booty')
                        or 'Brute' in cn
                        or super_name == 'PlacedBooty')

            if not is_enemy:
                continue

            # Exclude non-combat classes (dead bodies, props, FX)
            if any(cn.startswith(p) for p in PLACED_EXCLUDE_PREFIXES):
                continue
            if cn.startswith('DeadBrute') or cn.startswith('Dead'):
                continue

            placed_booty_classes[i + 1] = cn  # 1-based class_idx

        # Find actor list members whose class is a placed enemy
        for class_idx, class_name in placed_booty_classes.items():
            placed = []
            for ref in actor_set:
                if ref < 1 or ref > len(exports):
                    continue
                e = exports[ref - 1]
                if e['class_idx'] == class_idx and e['size'] > 0:
                    skip = detect_header_skip(data, e['offset'], e['size'], names)
                    info = get_spawner_info(data, e['offset'], e['size'], names, skip)
                    info['export_index'] = ref - 1
                    info['name_num'] = e['name_num']
                    info['header_skip'] = skip
                    info['size'] = e['size']
                    placed.append(info)
            if placed:
                spawner_data[class_name] = placed
                placed_classes.append(class_name)

    pkg['placed_classes'] = placed_classes

    if verbose:
        for target_class, spawners in spawner_data.items():
            if target_class in SPAWNER_CLASSES:
                kind = ''
            else:
                kind = ' [Placed Enemy]'
            print()
            print("  %s: %d found%s" % (target_class, len(spawners), kind))
            print("  " + "-" * 66)
            print("  %-4s %-6s %-35s %-20s" % ("#", "Num", "Location (X, Y, Z)", "Patrol"))
            print("  " + "-" * 66)
            for j, sp in enumerate(spawners):
                loc = sp.get('location', (0, 0, 0))
                patrol = sp.get('patrol', '-')
                print("  %-4d %-6d (%-10.0f, %-10.0f, %-10.0f) %s" % (
                    j+1, sp['name_num'], loc[0], loc[1], loc[2], patrol))

        total = sum(len(s) for s in spawner_data.values())
        print()
        print("  TOTAL SPAWNERS + PLACED: %d" % total)

    return pkg, spawner_data


def analyze_ambush_sets(filepath, verbose=False):
    """
    Find all AmbushSet exports (gather defense wave spawners) in a BSM map.
    Returns a list of dicts: {export_idx, max_spawned, value_offset, skip}.
    """
    pkg = full_parse_package(filepath)
    names = pkg['names']
    exports = pkg['full_exports']
    data = pkg['data']

    # AmbushSets are identified by property signature, not class name
    # (class names are often garbled in BSM v143 packages)
    ambush_sets = []
    for i, e in enumerate(exports):
        if e['size'] < 50 or e['size'] > 2000:
            continue
        for skip in [55, 57, 58, 59, 60, 63, 65]:
            if skip >= e['size']:
                continue
            try:
                serial = data[e['offset']:e['offset'] + e['size']]
                props = parse_properties(serial, skip, names, e['size'])
                pnames = {p[0] for p in props}

                if 'MaxSpawned' in pnames and 'Weight' in pnames and 'DoNotMenace' in pnames:
                    ms_prop = next(p for p in props if p[0] == 'MaxSpawned')
                    if ms_prop[2] == 'Int' and len(ms_prop[5]) >= 4:
                        ms_val = struct.unpack_from('<i', ms_prop[5])[0]
                        abs_offset = e['offset'] + ms_prop[7]
                        ambush_sets.append({
                            'export_idx': i,
                            'max_spawned': ms_val,
                            'value_offset': abs_offset,
                            'skip': skip,
                        })
                        break
            except Exception:
                pass

    if verbose and ambush_sets:
        print()
        print("  AmbushSets (gather defense): %d found" % len(ambush_sets))
        non_zero = [a for a in ambush_sets if a['max_spawned'] > 0]
        print("    Non-zero MaxSpawned: %d  (values: %s)" % (
            len(non_zero),
            ', '.join(str(a['max_spawned']) for a in non_zero) if non_zero else 'none'))

    return ambush_sets


DEFAULT_MAX_SPAWNED = 2   # assumed class default when MaxSpawned == 0


def patch_ambush_sets(filepath, multiplier, dry_run=False):
    """
    Increase MaxSpawned on AmbushSet exports to intensify gather defense waves.

    Zero values (engine class default) are treated as DEFAULT_MAX_SPAWNED
    before applying the multiplier, so maps that never set an explicit count
    still get scaled.
    Returns count of patched sets.
    """
    if multiplier <= 1:
        return 0

    ambush_sets = analyze_ambush_sets(filepath, verbose=True)
    if not ambush_sets:
        return 0

    if dry_run:
        print("  [DRY RUN] Would patch %d AmbushSets (x%d)" % (len(ambush_sets), multiplier))
        return len(ambush_sets)

    with open(filepath, 'r+b') as f:
        for a in ambush_sets:
            old_val = a['max_spawned']
            base = old_val if old_val > 0 else DEFAULT_MAX_SPAWNED
            new_val = base * multiplier
            f.seek(a['value_offset'])
            f.write(struct.pack('<i', new_val))

    print("  Patched %d AmbushSets: MaxSpawned x%d" % (len(ambush_sets), multiplier))
    for a in ambush_sets:
        old_val = a['max_spawned']
        base = old_val if old_val > 0 else DEFAULT_MAX_SPAWNED
        print("    export #%-6d  %d -> %d%s" % (
            a['export_idx'] + 1, old_val, base * multiplier,
            ' (was zero, used default %d)' % DEFAULT_MAX_SPAWNED if old_val == 0 else ''))

    return len(ambush_sets)


def patch_map(filepath, multiplier, adjustments=None, dry_run=False):
    """
    Duplicate spawners in a BSM map file.
    Returns a report dict with details of all changes.
    """
    map_name = os.path.basename(filepath)
    pkg, spawner_data = analyze_map(filepath, verbose=True)

    names = pkg['names']
    data = pkg['data']
    exports = pkg['full_exports']
    imports = pkg['imports']

    duplicates_per_spawner = multiplier - 1
    if duplicates_per_spawner < 1:
        print("  Nothing to do (multiplier = 1)")
        return None

    # Collect all spawners + placed enemies to duplicate
    new_exports = []
    report_entries = []

    all_classes = list(SPAWNER_CLASSES) + pkg.get('placed_classes', [])

    for target_class in all_classes:
        spawners = spawner_data.get(target_class, [])
        if not spawners:
            continue

        # Find the maximum name_num for this class to generate unique numbers
        max_name_num = max(sp['name_num'] for sp in spawners)
        next_num = max_name_num + 1

        kind = ' [Placed Enemy]' if target_class not in SPAWNER_CLASSES else ''
        print()
        print("  DUPLICATING %s%s (x%d -> %d new)" % (
            target_class, kind, multiplier, len(spawners) * duplicates_per_spawner))
        print("  " + "-" * 66)

        for sp in spawners:
            exp = exports[sp['export_index']]
            loc = sp.get('location')

            if loc is None:
                print("  SKIP #%d: no location found" % sp['name_num'])
                continue

            for dup_idx in range(duplicates_per_spawner):
                # Calculate new position
                new_loc = offset_position(
                    loc[0], loc[1], loc[2],
                    dup_idx, duplicates_per_spawner
                )

                # Check for manual adjustments
                adj_key = "%s_%s_%d_dup%d" % (map_name, target_class, sp['name_num'], dup_idx)
                if adjustments and adj_key in adjustments:
                    adj = adjustments[adj_key]
                    new_loc = (
                        new_loc[0] + adj.get('dx', 0),
                        new_loc[1] + adj.get('dy', 0),
                        new_loc[2] + adj.get('dz', 0),
                    )

                # Create new serial data by copying original and patching Location
                new_serial = bytearray(exp['serial_data'])

                # Find and patch the Location in the serial data
                skip = sp['header_skip']
                props = parse_properties(new_serial, skip, names, len(new_serial))
                patched_loc = False
                for p in props:
                    if p[0] == 'Location' and p[2] == 'Struct' and p[3] == 12:
                        loc_offset = p[7]
                        struct.pack_into('<fff', new_serial, loc_offset,
                                        new_loc[0], new_loc[1], new_loc[2])
                        patched_loc = True
                        break

                if not patched_loc:
                    print("  WARN: Could not patch location for dup of #%d" % sp['name_num'])
                    continue

                # Build new export entry
                new_exp = {
                    'name': exp['name'],
                    'name_idx': exp['name_idx'],
                    'name_num': next_num,
                    'class_idx': exp['class_idx'],
                    'super_idx': exp['super_idx'],
                    'outer_idx': exp['outer_idx'],
                    'unknown1': exp['unknown1'],
                    'flags': exp['flags'],
                    'size': len(new_serial),
                    'offset': 0,  # will be set during write
                    'unknown2': exp['unknown2'],
                    'serial_data': bytes(new_serial),
                }

                new_exports.append(new_exp)

                report_entry = {
                    'map': map_name,
                    'class': target_class,
                    'source_num': sp['name_num'],
                    'new_num': next_num,
                    'adj_key': adj_key,
                    'source_loc': list(loc),
                    'new_loc': list(new_loc),
                    'offset_dist': POSITION_OFFSET,
                }
                report_entries.append(report_entry)

                print("  NEW #%-4d from #%-4d  (%10.0f, %10.0f, %10.0f) -> (%10.0f, %10.0f, %10.0f)" % (
                    next_num, sp['name_num'],
                    loc[0], loc[1], loc[2],
                    new_loc[0], new_loc[1], new_loc[2]))

                next_num += 1

    if not new_exports:
        print("\n  No spawners to add.")
        return None

    total_new = len(new_exports)
    total_orig = sum(len(s) for s in spawner_data.values())

    print()
    print("  " + "=" * 66)
    print("  SUMMARY: %d original + %d new = %d total spawners" % (
        total_orig, total_new, total_orig + total_new))
    print("  " + "=" * 66)

    if dry_run:
        print("\n  [DRY RUN - no files modified]")
        return {'entries': report_entries, 'new_count': total_new}

    # === WRITE PATCHED FILE ===
    print()
    print("  WRITING PATCHED FILE...")

    # Strategy:
    #   1. Copy everything up to name_table_offset (header + original serial data)
    #   2. Expand Level actor list IN-PLACE to register cloned spawners
    #   3. Shift export offsets that follow the insertion point
    #   4. Append new spawner serial data (recording offsets)
    #   5. Append name table (unchanged)
    #   6. Append import table (unchanged)
    #   7. Append export table (all entries re-encoded to reflect offsets)
    #   8. Patch header fields (counts, offsets, generation data)

    prefix = pkg['prefix_raw']      # header + all original serial data
    name_tbl = pkg['name_table_raw']
    imp_tbl = pkg['import_table_raw']

    # ── In-place expand Level actor list with new spawner refs ──
    level_exp_idx = pkg.get('level_exp_idx')
    actor_refs = pkg.get('actor_refs', [])
    count_offset = pkg.get('level_count_offset', 0)

    if level_exp_idx is not None and actor_refs and count_offset:
        level_exp = exports[level_exp_idx]
        level_off = level_exp['offset']    # absolute offset in file
        list_start = level_off + count_offset  # where count1 INT32 starts

        # Walk past old actor list to find end position
        old_count = struct.unpack_from('<I', data, list_start)[0]
        pos = list_start + 8  # skip both INT32 count fields
        for _ in range(old_count):
            _, pos = read_compact_index(data, pos)
        old_list_end = pos

        # Build new actor refs = original + new spawner export indices
        new_actor_refs = list(actor_refs)
        base_idx = len(exports) + 1  # 1-based index for first new export
        for i in range(len(new_exports)):
            new_actor_refs.append(base_idx + i)

        # Encode new actor list
        new_encoded = bytearray()
        for ref in new_actor_refs:
            new_encoded += write_compact_index(ref)
        new_count = len(new_actor_refs)
        new_list_bytes = struct.pack('<I', new_count) + struct.pack('<I', new_count) + bytes(new_encoded)

        old_list_size = old_list_end - list_start
        delta = len(new_list_bytes) - old_list_size

        # Splice into prefix: replace old actor list region with expanded one
        output = bytearray(prefix[:list_start]) + new_list_bytes + bytearray(prefix[old_list_end:])

        # Update Level export's size (serial grew by delta)
        exports[level_exp_idx]['size'] += delta

        # Shift offsets for all exports whose serial data starts at or after
        # the old list end (they moved right by delta bytes)
        for exp in exports:
            if exp['index'] != level_exp_idx and exp['offset'] >= old_list_end:
                exp['offset'] += delta

        print("  Level actor list: %d -> %d actors (+%d spawner clones, %+d bytes)" % (
            len(actor_refs), new_count, len(new_exports), delta))
    else:
        output = bytearray(prefix)
        if level_exp_idx is not None and actor_refs:
            print("  Level actor list: %d actors (no registration needed)" %
                  len(actor_refs))

    # Append new spawner serial data
    for new_exp in new_exports:
        new_exp['offset'] = len(output)
        output += new_exp['serial_data']

    # Pad to 4-byte alignment
    while len(output) % 4 != 0:
        output += b'\x00'

    # Record new table offsets
    new_name_offset = len(output)
    output += name_tbl

    new_import_offset = len(output)
    output += imp_tbl

    new_export_offset = len(output)

    # Write export table: ALL entries re-encoded to reflect offset/size changes
    for exp in exports:
        output += write_export_entry(exp, data)

    # Then new entries
    for new_exp in new_exports:
        output += write_export_entry(new_exp, data)

    new_export_count = len(exports) + len(new_exports)

    # Patch header
    struct.pack_into('<I', output, 16, new_name_offset)     # NameOffset
    struct.pack_into('<I', output, 20, new_export_count)     # ExportCount
    struct.pack_into('<I', output, 24, new_export_offset)    # ExportOffset
    struct.pack_into('<I', output, 32, new_import_offset)    # ImportOffset

    # Patch generations table (offset 56 = Gen[0].ExportCount)
    struct.pack_into('<I', output, 56, new_export_count)

    # Backup original
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / map_name
    if not backup_path.exists():
        shutil.copy2(filepath, backup_path)
        print("  Backed up: %s" % backup_path)
    else:
        print("  Backup exists: %s" % backup_path)

    # Write patched file
    with open(filepath, 'wb') as f:
        f.write(output)

    orig_size = len(data)
    new_size = len(output)
    print("  Written: %s" % filepath)
    print("  Size: %s -> %s (+%s bytes)" % (
        format(orig_size, ','), format(new_size, ','), format(new_size - orig_size, ',')))

    return {'entries': report_entries, 'new_count': total_new}


# ─── Main Commands ───────────────────────────────────────────────────────────

def find_bsm_files():
    """Find base .bsm map files (skip non-combat maps)."""
    files = []
    for f in sorted(MAPS_DIR.glob("*.bsm")):
        name = f.stem
        if any(name.startswith(skip) for skip in SKIP_MAPS):
            continue
        files.append(str(f))
    return files


def cmd_analyze():
    """Analyze all maps without making changes."""
    maps = find_bsm_files()
    print("Found %d base .bsm map files" % len(maps))

    grand_total = {}
    map_summary = []
    for f in maps:
        try:
            pkg, spawner_data = analyze_map(f, verbose=True)
            row = {'map': os.path.basename(f)}
            for cls, spawners in spawner_data.items():
                grand_total[cls] = grand_total.get(cls, 0) + len(spawners)
                row[cls] = len(spawners)
            map_summary.append(row)
        except Exception as e:
            print("  ERROR parsing %s: %s" % (os.path.basename(f), e))

    print()
    print("=" * 70)
    print("  MAP SUMMARY TABLE")
    print("=" * 70)
    print("  %-35s %12s %12s %12s %10s %10s %8s" % ("Map", "Aggressors", "Protectors", "SecBots", "Turrets", "Cameras", "Total"))
    print("  " + "-" * 105)
    for row in map_summary:
        ag = row.get('AggressorSpawner', 0)
        pr = row.get('ProtectorSpawner', 0)
        sb = row.get('SecurityBotSpawner', 0)
        tu = row.get('TurretSpawner', 0)
        ca = row.get('SecurityCameraSpawner', 0)
        print("  %-35s %12d %12d %12d %10d %10d %8d" % (row['map'], ag, pr, sb, tu, ca, ag + pr + sb + tu + ca))
    print("  " + "-" * 105)
    total_ag = grand_total.get('AggressorSpawner', 0)
    total_pr = grand_total.get('ProtectorSpawner', 0)
    total_sb = grand_total.get('SecurityBotSpawner', 0)
    total_tu = grand_total.get('TurretSpawner', 0)
    total_ca = grand_total.get('SecurityCameraSpawner', 0)
    print("  %-35s %12d %12d %12d %10d %10d %8d" % ("TOTAL", total_ag, total_pr, total_sb, total_tu, total_ca, total_ag + total_pr + total_sb + total_tu + total_ca))


def cmd_patch(multiplier):
    """Patch all maps with spawner duplicates."""
    maps = find_bsm_files()
    print("Found %d .bsm map files" % len(maps))
    print("Multiplier: x%d (%d duplicates per spawner)" % (multiplier, multiplier - 1))

    # Load adjustments if they exist
    adjustments = {}
    if ADJUSTMENTS_FILE.exists():
        with open(ADJUSTMENTS_FILE) as f:
            adjustments = json.load(f)
        print("Loaded %d position adjustments from %s" % (len(adjustments), ADJUSTMENTS_FILE))

    all_reports = []
    total_added = 0

    for filepath in maps:
        try:
            report = patch_map(filepath, multiplier, adjustments)
            if report:
                all_reports.extend(report['entries'])
                total_added += report['new_count']
        except Exception as e:
            print("\n  ERROR patching %s: %s" % (os.path.basename(filepath), e))
            import traceback
            traceback.print_exc()

    # Save report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / ("spawn_report_x%d_%s.json" % (
        multiplier, time.strftime("%Y%m%d_%H%M%S")))
    with open(report_path, 'w') as f:
        json.dump(all_reports, f, indent=2)

    # Save adjustment template
    if not ADJUSTMENTS_FILE.exists():
        adj_template = {}
        for entry in all_reports:
            adj_template[entry['adj_key']] = {"dx": 0, "dy": 0, "dz": 0}
        with open(ADJUSTMENTS_FILE, 'w') as f:
            json.dump(adj_template, f, indent=2)
        print("\nAdjustment template saved to: %s" % ADJUSTMENTS_FILE)

    # Final summary
    print()
    print("=" * 70)
    print("  PATCHING COMPLETE")
    print("=" * 70)
    print("  Maps patched: %d" % len(maps))
    print("  Total spawners added: %d" % total_added)
    print("  Report saved: %s" % report_path)
    print("  Backups at: %s" % BACKUP_DIR)
    print()
    print("  To adjust positions after testing:")
    print("    1. Edit %s" % ADJUSTMENTS_FILE)
    print("    2. Set dx/dy/dz offsets for any bad spawners")
    print("    3. Run: py bsm_spawn_patcher.py restore")
    print("    4. Run: py bsm_spawn_patcher.py %d" % multiplier)
    print()
    print("  To restore originals:")
    print("    py bsm_spawn_patcher.py restore")


def cmd_restore():
    """Restore all original map files from backup with verification."""
    import hashlib

    print()
    print("=" * 70)
    print("  RESTORING ORIGINAL MAP FILES")
    print("=" * 70)

    if not BACKUP_DIR.exists() or not any(BACKUP_DIR.glob("*.bsm")):
        print()
        print("  No backups found at %s" % BACKUP_DIR)
        print("  Nothing to restore.")
        return

    restored = 0
    failed = 0

    for backup in sorted(BACKUP_DIR.glob("*.bsm")):
        dest = MAPS_DIR / backup.name

        # Get backup hash before copy
        with open(backup, 'rb') as f:
            backup_hash = hashlib.md5(f.read()).hexdigest()

        # Copy
        shutil.copy2(str(backup), str(dest))

        # Verify destination matches backup
        with open(dest, 'rb') as f:
            dest_hash = hashlib.md5(f.read()).hexdigest()

        if backup_hash == dest_hash:
            size = os.path.getsize(dest)
            print("  OK  %-35s (%s bytes, md5:%s)" % (
                backup.name, format(size, ','), backup_hash[:12]))
            restored += 1
        else:
            print("  FAIL %-35s (hash mismatch!)" % backup.name)
            failed += 1

    print()
    print("  " + "-" * 66)
    if failed == 0:
        print("  RESTORE SUCCESSFUL: %d map(s) restored and verified." % restored)
    else:
        print("  RESTORE COMPLETED WITH ERRORS: %d OK, %d FAILED" % (restored, failed))

    if ADJUSTMENTS_FILE.exists():
        print()
        print("  NOTE: %s still exists." % ADJUSTMENTS_FILE.name)
        print("        Keeping your adjustments for next patch run.")
        print("        Delete it manually to regenerate a fresh template.")


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 70)
    print("  BioShock 2 Remastered - BSM Spawner Duplicator")
    print("=" * 70)

    if len(sys.argv) < 2:
        multiplier = 2
    elif sys.argv[1] == 'restore':
        cmd_restore()
        return
    elif sys.argv[1] == 'analyze':
        cmd_analyze()
        return
    else:
        try:
            multiplier = int(sys.argv[1])
            if multiplier < 1 or multiplier > 10:
                print("ERROR: Multiplier must be 1-10")
                sys.exit(1)
        except ValueError:
            print("Usage: py bsm_spawn_patcher.py [2|3|analyze|restore]")
            sys.exit(1)

    cmd_patch(multiplier)


if __name__ == '__main__':
    main()
