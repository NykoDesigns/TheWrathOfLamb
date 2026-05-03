"""
DLC Weapon Package Builder
===========================
Extracts Ion Laser weapon assets from Minerva_A.bsm and builds a standalone
DLCWeapons.U package that can be loaded as a ServerPackage in the main campaign.

Approach:
  - Copies Minerva_A's FULL name table (preserves FName references in serial data)
  - Builds a CLEAN minimal import table (9 entries) with proper package names
  - BSM v143 mangles import names — the original 937 imports are unusable
  - Remaps export + import references in serial data to new indices
  - IL_Mesh material section is rebuilt; property values use zero-padded patching
"""

import struct
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from core.bsm_parser import (
    read_compact_index, write_compact_index,
    parse_properties, read_name_ref,
)
from core.bsm_asset_analyzer import parse_package_deep

# ── Constants ────────────────────────────────────────────────────────────────

MAGIC       = 0x9E2A83C1
PKG_VERSION = 143
PKG_LICENSE = 59

# Minerva_A export indices (0-based) for the weapon dependency set
SRC_EXPORTS = {
    'PlayerLaserGun':  1189,
    'IL_Mesh':         25417,
    'Material_0':      27502,
    'Material_1':      27503,
    'Tex_SpecMap_0':   27469,
    'Tex_Normal_0':    27470,
    'Tex_Diffuse_0':   27471,
    'Tex_SpecMap_1':   27472,
    'Tex_Normal_1':    27473,
    'Tex_Diffuse_1':   27474,
}

# Ordered list for deterministic export table layout
EXPORT_ORDER = [
    'PlayerLaserGun',   # new idx 0, 1-based ref 1
    'IL_Mesh',          # new idx 1, 1-based ref 2
    'Material_0',       # new idx 2, 1-based ref 3
    'Material_1',       # new idx 3, 1-based ref 4
    'Tex_SpecMap_0',    # new idx 4, 1-based ref 5
    'Tex_Normal_0',     # new idx 5, 1-based ref 6
    'Tex_Diffuse_0',    # new idx 6, 1-based ref 7
    'Tex_SpecMap_1',    # new idx 7, 1-based ref 8
    'Tex_Normal_1',     # new idx 8, 1-based ref 9
    'Tex_Diffuse_1',    # new idx 9, 1-based ref 10
]


def _build_ref_map():
    """Build old_1based_ref → new_1based_ref mapping."""
    m = {}
    for new_idx, label in enumerate(EXPORT_ORDER):
        old_0based = SRC_EXPORTS[label]
        m[old_0based + 1] = new_idx + 1   # 1-based → 1-based
    return m


# ── Clean import table ──────────────────────────────────────────────────────

# Name indices in Minerva_A's name table for the classes/packages we need.
# These are verified to exist; BSM keeps real names alongside mangled ones.
NAME_IDX = {
    'Core':           21051,
    'Engine':         37219,
    'ShockGame':      37098,
    'Class':            456,
    'Package':        37216,
    'LaserGun_LaserAmmo': 1194,
    'LaserGun_BurstAmmo': 2702,
    'Texture':          356,
    'SkeletalMesh':   37137,
    'Shader':         18566,
    'LaserGun':         813,
}

# Clean import table — 11 entries with correct package/class names.
# The engine must be able to resolve every top-level package.
IMPORT_DEFS = [
    # idx  name            class_pkg   class_name  outer (0=top, neg=import 1-based)
    # 0    Core            Core        Package     0
    # 1    Engine          Core        Package     0
    # 2    ShockGame       Core        Package     0
    # 3    Core.Class      Core        Class       -1 (Core)
    # 4    Core.Package    Core        Class       -1 (Core)
    # 5    Engine.Texture  Core        Class       -2 (Engine)
    # 6    Engine.SkelMesh Core        Class       -2 (Engine)
    # 7    Engine.Shader   Core        Class       -2 (Engine)
    # 8    ShockGame.Laser Core        Class       -3 (ShockGame)
    ('Core',         'Core', 'Package',       0),
    ('Engine',       'Core', 'Package',       0),
    ('ShockGame',    'Core', 'Package',       0),
    ('Class',        'Core', 'Class',        -1),
    ('Package',      'Core', 'Class',        -1),
    ('Texture',      'Core', 'Class',        -2),
    ('SkeletalMesh', 'Core', 'Class',        -2),
    ('Shader',       'Core', 'Class',        -2),
    ('LaserGun',     'Core', 'Class',        -3),
    ('LaserGun_LaserAmmo', 'Core', 'Class', -3),   # 9 — DefaultAmmoSelection
    ('LaserGun_BurstAmmo', 'Core', 'Class', -3),   # 10 — burst ammo type
]

# Old Minerva_A import indices → new DLCWeapons import 1-based negative refs
IMPORT_REMAP = {
    # old_imp_idx: new_negative_ref  (new_ref = -(new_0based + 1))
    20:  -6,    # Texture        → new imp[5]
    33:  -8,    # Shader         → new imp[7]
    114: -7,    # SkeletalMesh   → new imp[6]
    150: -9,    # LaserGun       → new imp[8]
    212: -10,   # LaserGun_LaserAmmo → new imp[9]
    252: -11,   # LaserGun_BurstAmmo → new imp[10]
}


# ── Serial data patching ────────────────────────────────────────────────────

def _patch_property_refs(serial, prop_start, names, exp_ref_map, imp_ref_map):
    """Patch Object property values in-place using zero-padded replacement.

    For each Object property whose value is a compact_index ref:
      - Positive (export ref): remap via exp_ref_map, or set to 0 (None).
      - Negative (import ref): remap via imp_ref_map, or set to 0 (None).

    Returns the patched serial (same length).
    """
    buf = bytearray(serial)
    data = bytes(serial)  # immutable copy for parsing
    serial_end = len(data)

    props = parse_properties(data, prop_start, names, serial_end)
    for p in props:
        name, prop_type, type_name, prop_size, arr_idx, value_data, tag_pos, value_pos, *_ = p
        if type_name != 'Object' or prop_size <= 0:
            continue
        old_ref, _ = read_compact_index(value_data, 0)
        if old_ref == 0:
            continue  # already null
        if old_ref > 0:
            # Export reference — remap
            new_ref = exp_ref_map.get(old_ref, 0)  # 0 = None for unmapped
        else:
            # Import reference — remap or null
            old_imp = -old_ref - 1
            new_ref = imp_ref_map.get(old_imp, 0)  # 0 = None for unmapped
        new_bytes = write_compact_index(new_ref)
        if len(new_bytes) > prop_size:
            raise ValueError(
                "Remapped ref %d->%d grows from %d to %d bytes (exceeds prop_size %d)"
                % (old_ref, new_ref, len(value_data), len(new_bytes), prop_size))
        # Write new ref + zero padding
        for i, b in enumerate(new_bytes):
            buf[value_pos + i] = b
        for i in range(len(new_bytes), prop_size):
            buf[value_pos + i] = 0
    return bytes(buf)


def _patch_mesh_material_refs(serial, ref_map):
    """Rebuild IL_Mesh material reference section.

    Material refs are at a known offset in the SkeletalMesh serial:
      offset 0x48: BYTE count
      offset 0x49: compact_index[] refs (variable length each)
    After the refs, the rest of the serial continues.

    We rebuild the section with remapped refs, which may change length.
    """
    mat_count_off = 0x48
    mat_count = serial[mat_count_off]

    # Find where old material refs end
    pos = mat_count_off + 1
    for _ in range(mat_count):
        _, pos = read_compact_index(serial, pos)
    old_refs_end = pos

    # Build new material ref bytes
    new_ref_bytes = bytearray()
    pos = mat_count_off + 1
    for _ in range(mat_count):
        old_ref, pos = read_compact_index(serial, pos)
        new_ref = ref_map.get(old_ref, old_ref)  # keep if not in map
        new_ref_bytes.extend(write_compact_index(new_ref))

    # Rebuild serial: header + count + new refs + rest
    result = bytearray()
    result.extend(serial[:mat_count_off + 1])   # up to and including count byte
    result.extend(new_ref_bytes)
    result.extend(serial[old_refs_end:])
    return bytes(result)


def _patch_class_header_superfield(serial, new_super_ref):
    """Patch the SuperField compact_index in a Class export's serial header.

    The class header is: [8 fixed bytes] [compact_index SuperField] [rest...]
    We replace SuperField with the new ref, zero-padded to same byte length.
    """
    buf = bytearray(serial)
    old_ci, old_end = read_compact_index(serial, 8)
    old_len = old_end - 8
    new_bytes = bytearray(write_compact_index(new_super_ref))
    # Zero-pad to match original length
    while len(new_bytes) < old_len:
        # Set continuation bit on last byte so far, then add 0x00
        new_bytes[-1] |= 0x40 if len(new_bytes) == 1 else 0x80
        new_bytes.append(0x00)
    if len(new_bytes) > old_len:
        raise ValueError("SuperField remap %d->%d grows from %d to %d bytes"
                         % (old_ci, new_super_ref, old_len, len(new_bytes)))
    for i, b in enumerate(new_bytes):
        buf[8 + i] = b
    return bytes(buf)


def _null_class_header_import_at(serial, offset):
    """Zero out a compact_index import ref at a specific offset in the class header."""
    buf = bytearray(serial)
    _, end = read_compact_index(serial, offset)
    for i in range(offset, end):
        buf[i] = 0
    return bytes(buf)


# ── Name table writer ────────────────────────────────────────────────────────

def _write_name_table(pkg):
    """Serialize the full name table from source package.

    Format per entry:  BYTE length + UTF-16LE chars (length wchars incl NUL) + 8-byte flags
    """
    data = pkg['data']
    pos = pkg['name_offset']
    # We just copy the raw bytes from the source package for perfect fidelity
    end = pos
    for _ in range(pkg['name_count']):
        l = data[end]; end += 1
        if l == 0:
            end += 8
        else:
            end += l * 2 + 8  # l wchars (incl NUL) as UTF-16LE + 8 flags
    return data[pos:end]


def _write_import_table():
    """Build a clean minimal import table with 9 entries.

    Each entry:
      compact_index  class_pkg_name_idx
      INT32          class_pkg_name_num  (always 0)
      compact_index  class_name_name_idx
      INT32          class_name_name_num (always 0)
      INT32          outer_idx           (signed: neg=import, 0=none)
      compact_index  obj_name_idx
      INT32          obj_name_num        (always 0)
    """
    buf = bytearray()
    for obj_name, cls_pkg, cls_name, outer in IMPORT_DEFS:
        buf.extend(write_compact_index(NAME_IDX[cls_pkg]))
        buf.extend(struct.pack('<I', 0))
        buf.extend(write_compact_index(NAME_IDX[cls_name]))
        buf.extend(struct.pack('<I', 0))
        buf.extend(struct.pack('<i', outer))
        buf.extend(write_compact_index(NAME_IDX[obj_name]))
        buf.extend(struct.pack('<I', 0))
    return bytes(buf)


# ── Export table writer ──────────────────────────────────────────────────────

def _remap_export_class_super(exp):
    """Remap class_idx and super_idx from old Minerva_A imports to new clean imports."""
    class_idx = exp['class_idx']
    super_idx = exp['super_idx']
    # Remap negative (import) refs using IMPORT_REMAP
    if class_idx < 0:
        old_imp = -class_idx - 1
        class_idx = IMPORT_REMAP.get(old_imp, 0)
    if super_idx < 0:
        old_imp = -super_idx - 1
        super_idx = IMPORT_REMAP.get(old_imp, 0)
    return class_idx, super_idx


def _write_export_entry(exp, serial_size, serial_offset):
    """Write a single export table entry.

    Fields:
      compact_index  class_idx
      compact_index  super_idx
      INT32          outer_idx  (0 = top-level)
      INT32          bs_field1  (always 0)
      compact_index  name_idx
      INT32          name_num
      UINT64         flags
      compact_index  serial_size
      compact_index  serial_offset  (only if size > 0)
      INT32          bs_field2
    """
    class_idx, super_idx = _remap_export_class_super(exp)
    buf = bytearray()
    buf.extend(write_compact_index(class_idx))
    buf.extend(write_compact_index(super_idx))
    buf.extend(struct.pack('<i', 0))                  # outer = 0 (top-level)
    buf.extend(struct.pack('<i', 0))                  # bs_field1
    buf.extend(write_compact_index(exp['name_idx']))
    buf.extend(struct.pack('<I', exp['name_num']))
    buf.extend(struct.pack('<Q', exp['flags']))
    buf.extend(write_compact_index(serial_size))
    if serial_size > 0:
        buf.extend(write_compact_index(serial_offset))
    buf.extend(struct.pack('<i', exp['bs_field2']))
    return bytes(buf)


# ── Package builder ──────────────────────────────────────────────────────────

def build_dlc_weapons_package(minerva_path, output_path):
    """Build DLCWeapons.U from Minerva_A.bsm.

    Returns the number of exports written (should be 10).
    """
    print("  Parsing Minerva_A.bsm...")
    pkg = parse_package_deep(minerva_path)
    data = pkg['data']
    names = pkg['names']
    exp_ref_map = _build_ref_map()
    imp_ref_map = IMPORT_REMAP  # old_imp_idx → new negative ref

    # ── Prepare serial data for each export ──────────────────────────────
    serial_blobs = []
    for label in EXPORT_ORDER:
        src_idx = SRC_EXPORTS[label]
        exp = pkg['exports'][src_idx]
        serial = data[exp['offset']:exp['offset'] + exp['size']]

        if label == 'PlayerLaserGun':
            # Patch class header: SuperField at offset 8 (LaserGun import)
            serial = _patch_class_header_superfield(serial, -9)  # new imp[8]
            # Null out header import at offset 55 (unresolvable in clean table)
            serial = _null_class_header_import_at(serial, 55)
            # Patch default property Object refs (start at serial offset 152)
            serial = _patch_property_refs(serial, 152, names, exp_ref_map, imp_ref_map)

        elif label == 'IL_Mesh':
            # Rebuild material reference section
            serial = _patch_mesh_material_refs(serial, exp_ref_map)

        elif label.startswith('Material_'):
            # Patch texture Object refs (properties start at serial offset 8)
            serial = _patch_property_refs(serial, 8, names, exp_ref_map, imp_ref_map)

        # Textures: copy verbatim (self-contained mip data)
        serial_blobs.append(serial)

    # ── Write the package ────────────────────────────────────────────────
    print("  Writing %s..." % output_path)

    # Phase 1: serialize name table (raw copy) + clean import table
    name_table_bytes = _write_name_table(pkg)
    import_table_bytes = _write_import_table()

    # Phase 2: calculate layout
    header_size = 36 + 4 + 4 + 16  # standard header + heritage + guid + generations
    # Actually let's just use a fixed header approach
    #   0..3   magic
    #   4..5   version
    #   6..7   licensee
    #   8..11  header_size (= offset of first data after header block)
    #  12..15  name_count
    #  16..19  name_offset
    #  20..23  export_count
    #  24..27  export_offset
    #  28..31  import_count
    #  32..35  import_offset
    #  36..39  heritage_count (0)
    #  40..55  GUID (16 bytes, zeroed)
    #  56..59  generation_count (1)
    #  60..63  gen export_count
    #  64..67  gen name_count
    HEADER_SIZE = 68

    name_offset = HEADER_SIZE
    name_end = name_offset + len(name_table_bytes)

    import_offset = name_end
    import_end = import_offset + len(import_table_bytes)

    # We need to know export table size to compute serial offsets.
    # First pass: build export entries with placeholder offsets to measure size.
    export_entries_placeholder = []
    for label in EXPORT_ORDER:
        src_idx = SRC_EXPORTS[label]
        exp = pkg['exports'][src_idx]
        entry = _write_export_entry(exp, len(serial_blobs[EXPORT_ORDER.index(label)]), 0xFFFFFF)
        export_entries_placeholder.append(entry)
    export_table_size = sum(len(e) for e in export_entries_placeholder)

    export_offset = import_end
    serial_data_start = export_offset + export_table_size

    # Second pass: compute real serial offsets and rebuild export entries
    export_entries = []
    cur_serial_offset = serial_data_start
    for i, label in enumerate(EXPORT_ORDER):
        src_idx = SRC_EXPORTS[label]
        exp = pkg['exports'][src_idx]
        blob = serial_blobs[i]
        entry = _write_export_entry(exp, len(blob), cur_serial_offset)
        # If entry size differs from placeholder, offsets shift — iterate
        export_entries.append(entry)
        cur_serial_offset += len(blob)

    # Verify export table size didn't change (it can if compact_index sizes differ
    # between placeholder offset and real offset)
    real_export_size = sum(len(e) for e in export_entries)
    if real_export_size != export_table_size:
        # Re-calculate with real sizes
        serial_data_start = export_offset + real_export_size
        export_entries = []
        cur_serial_offset = serial_data_start
        for i, label in enumerate(EXPORT_ORDER):
            src_idx = SRC_EXPORTS[label]
            exp = pkg['exports'][src_idx]
            blob = serial_blobs[i]
            entry = _write_export_entry(exp, len(blob), cur_serial_offset)
            export_entries.append(entry)
            cur_serial_offset += len(blob)

    # ── Assemble the file ────────────────────────────────────────────────
    out = bytearray()

    # Header
    out.extend(struct.pack('<I', MAGIC))
    out.extend(struct.pack('<H', PKG_VERSION))
    out.extend(struct.pack('<H', PKG_LICENSE))
    out.extend(struct.pack('<I', HEADER_SIZE))         # header_size
    out.extend(struct.pack('<I', pkg['name_count']))   # name_count
    out.extend(struct.pack('<I', name_offset))         # name_offset
    out.extend(struct.pack('<I', len(EXPORT_ORDER)))   # export_count
    out.extend(struct.pack('<I', export_offset))       # export_offset
    out.extend(struct.pack('<I', len(IMPORT_DEFS)))    # import_count
    out.extend(struct.pack('<I', import_offset))       # import_offset
    out.extend(struct.pack('<I', 0))                   # heritage_count
    out.extend(b'\x00' * 16)                           # GUID
    out.extend(struct.pack('<I', 1))                   # generation_count
    out.extend(struct.pack('<I', len(EXPORT_ORDER)))   # gen[0].export_count
    out.extend(struct.pack('<I', pkg['name_count']))   # gen[0].name_count
    assert len(out) == HEADER_SIZE, "Header size mismatch: %d != %d" % (len(out), HEADER_SIZE)

    # Name table
    out.extend(name_table_bytes)

    # Import table
    out.extend(import_table_bytes)

    # Export table
    for entry in export_entries:
        out.extend(entry)

    # Serial data
    for blob in serial_blobs:
        out.extend(blob)

    # Write file
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(out)

    total_size = len(out)
    serial_total = sum(len(b) for b in serial_blobs)
    print("  Package written: %d bytes (%.1f KB)" % (total_size, total_size / 1024))
    print("    Name table:   %d entries, %d bytes" % (pkg['name_count'], len(name_table_bytes)))
    print("    Import table: %d entries, %d bytes" % (len(IMPORT_DEFS), len(import_table_bytes)))
    print("    Export table: %d entries, %d bytes" % (len(EXPORT_ORDER), sum(len(e) for e in export_entries)))
    print("    Serial data:  %d bytes" % serial_total)

    return len(EXPORT_ORDER)


# ── Verification ─────────────────────────────────────────────────────────────

def verify_package(filepath):
    """Quick verification that the built package is parseable."""
    print("  Verifying %s..." % filepath)
    pkg = parse_package_deep(filepath)
    print("    Names: %d, Imports: %d, Exports: %d" % (
        len(pkg['names']), len(pkg['imports']), len(pkg['exports'])))

    for i, exp in enumerate(pkg['exports']):
        print("    [%d] %-25s class_idx=%d super=%d size=%d offset=%d" % (
            i, exp['name'][:25], exp['class_idx'], exp['super_idx'],
            exp['size'], exp['offset']))
        # Verify serial data is within file bounds
        if exp['size'] > 0:
            end = exp['offset'] + exp['size']
            if end > len(pkg['data']):
                print("      *** ERROR: serial extends beyond file (ends at %d, file is %d)" %
                      (end, len(pkg['data'])))
            else:
                print("      serial OK (%d bytes at 0x%x)" % (exp['size'], exp['offset']))

    # Check PlayerLaserGun properties
    if len(pkg['exports']) > 0:
        exp = pkg['exports'][0]
        serial = pkg['data'][exp['offset']:exp['offset'] + exp['size']]
        props = parse_properties(serial, 152, pkg['names'], exp['size'])
        print("    PlayerLaserGun: %d default properties parsed" % len(props))
        for p in props:
            name, prop_type, type_name, prop_size, arr_idx, val, *_ = p
            if type_name == 'Object' and val:
                ref, _ = read_compact_index(val, 0)
                if ref > 0 and ref <= len(pkg['exports']):
                    target = pkg['exports'][ref - 1]
                    print("      %-35s → exp[%d] %s (%d bytes)" % (
                        name[:35], ref - 1, target['name'][:25], target['size']))
                elif ref < 0:
                    imp_idx = -ref - 1
                    imp_name = pkg['imports'][imp_idx] if imp_idx < len(pkg['imports']) else '?'
                    if isinstance(imp_name, dict):
                        imp_name = imp_name.get('name', '?')
                    print("      %-35s → imp[%d] %s" % (
                        name[:35], imp_idx, str(imp_name)[:25]))
                elif ref == 0:
                    print("      %-35s → None" % name[:35])

    return True


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    MINERVA = r'D:\SteamLibrary\steamapps\common\BioShock 2 Remastered\ContentBaked\pc\Maps\Minerva_A.bsm'
    OUTPUT  = r'D:\SteamLibrary\steamapps\common\BioShock 2 Remastered\Build\Final\BakedScripts\pc\DLCWeapons.U'

    if len(sys.argv) > 1:
        MINERVA = sys.argv[1]
    if len(sys.argv) > 2:
        OUTPUT = sys.argv[2]

    print("Building DLCWeapons.U package...")
    n = build_dlc_weapons_package(MINERVA, OUTPUT)
    print("\nDone — %d exports written.\n" % n)

    verify_package(OUTPUT)
