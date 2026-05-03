"""
DLC Effects Package Builder
============================
Extracts fire/flame emitter classes from Abyss.bsm and builds a standalone
DLCEffects.U package that can be loaded as a ServerPackage.

Approach:
  - Copies Abyss.bsm's FULL name table (preserves FName references in serial data)
  - Appends extra names needed for the clean import table
  - Builds a CLEAN minimal import table
  - Remaps super/child references in class serial data
  - Child SpriteEmitter serial data is copied verbatim (name refs preserved)
"""

import struct
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from core.bsm_parser import read_compact_index, write_compact_index
from core.bsm_asset_analyzer import parse_package_deep

# ── Constants ────────────────────────────────────────────────────────────────

MAGIC       = 0x9E2A83C1
PKG_VERSION = 143
PKG_LICENSE = 59
HEADER_SIZE = 68

# Default name flags for appended names
DEFAULT_NAME_FLAGS = bytes([0x10, 0x00, 0x07, 0x00, 0x00, 0x00, 0x00, 0x00])


# ── Emitter definitions ──────────────────────────────────────────────────────

# Each emitter to transplant: (export_idx, [child_export_indices])
EMITTER_DEFS = {
    'Cigarette_Glow': {
        'class_idx':    1034,
        'children':     [88929],
        'child_ref_offsets': [0x93],   # offsets in class serial where child refs appear
    },
    'PLSM_FIRE_idle_advanced': {
        'class_idx':    523,
        'children':     [84890, 84891, 84892, 84893, 84894, 84895],
        'child_ref_offsets': [0x94, 0x97, 0x9A, 0x9D, 0xA0, 0xA3],
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _encode_name(text):
    """Encode a name entry: BYTE len + UTF-16LE + 8-byte flags."""
    encoded = (text + '\x00').encode('utf-16-le')
    wchar_len = len(text) + 1  # including NUL
    return bytes([wchar_len]) + encoded + DEFAULT_NAME_FLAGS


def _pad_ci(value, target_len):
    """Encode a compact index with zero-padding to target byte length."""
    raw = bytearray(write_compact_index(value))
    if len(raw) == target_len:
        return bytes(raw)
    if len(raw) > target_len:
        raise ValueError("CI(%d) needs %d bytes, target is %d" % (value, len(raw), target_len))
    # Add continuation bits and zero bytes
    while len(raw) < target_len:
        if len(raw) == 1:
            raw[0] |= 0x40  # set continuation bit on first byte
        else:
            raw[-1] |= 0x80  # set continuation bit on subsequent bytes
        raw.append(0x00)
    return bytes(raw)


def _write_export_entry(class_idx, super_idx, outer_idx, name_idx, name_num,
                        flags, serial_size, serial_offset, bs_field1=0, bs_field2=1):
    """Write a single export table entry."""
    buf = bytearray()
    buf.extend(write_compact_index(class_idx))
    buf.extend(write_compact_index(super_idx))
    buf.extend(struct.pack('<i', outer_idx))
    buf.extend(struct.pack('<i', bs_field1))
    buf.extend(write_compact_index(name_idx))
    buf.extend(struct.pack('<I', name_num))
    buf.extend(struct.pack('<Q', flags))
    buf.extend(write_compact_index(serial_size))
    if serial_size > 0:
        buf.extend(write_compact_index(serial_offset))
    buf.extend(struct.pack('<i', bs_field2))
    return bytes(buf)


def _write_import_entry(cls_pkg_name_idx, cls_name_idx, outer_idx, obj_name_idx):
    """Write a single import table entry."""
    buf = bytearray()
    buf.extend(write_compact_index(cls_pkg_name_idx))
    buf.extend(struct.pack('<I', 0))  # class_pkg_name_num
    buf.extend(write_compact_index(cls_name_idx))
    buf.extend(struct.pack('<I', 0))  # class_name_num
    buf.extend(struct.pack('<i', outer_idx))
    buf.extend(write_compact_index(obj_name_idx))
    buf.extend(struct.pack('<I', 0))  # obj_name_num
    return bytes(buf)


# ── Package builder ──────────────────────────────────────────────────────────

def build_dlc_effects_package(abyss_path, output_path):
    """Build DLCEffects.U from Abyss.bsm.

    Returns dict mapping emitter name -> new 1-based export reference.
    """
    print("  Parsing Abyss.bsm...")
    pkg = parse_package_deep(abyss_path)
    data = pkg['data']
    names = pkg['names']
    exports = pkg['exports']

    # ── Phase 1: Build name table ─────────────────────────────────────
    # Copy raw name table from Abyss
    name_offset_src = struct.unpack_from('<I', data, 16)[0]
    name_count_src = struct.unpack_from('<I', data, 12)[0]
    pos = name_offset_src
    for _ in range(name_count_src):
        l = data[pos]; pos += 1
        pos += (l * 2 if l else 0) + 8
    raw_name_table = data[name_offset_src:pos]

    # Append extra names needed for imports
    extra_names = ['Engine', 'Package', 'SpriteEmitter', 'DLCEffects']
    extra_name_indices = {}
    cur_name_idx = name_count_src
    extra_bytes = bytearray()
    for en in extra_names:
        # Check if already in Abyss name table
        found = False
        for i, n in enumerate(names):
            if n == en:
                extra_name_indices[en] = i
                found = True
                break
        if not found:
            extra_name_indices[en] = cur_name_idx
            extra_bytes.extend(_encode_name(en))
            cur_name_idx += 1

    total_name_count = cur_name_idx
    name_table_bytes = raw_name_table + bytes(extra_bytes)

    # Name indices for import table
    NI_CORE    = None
    NI_ENGINE  = extra_name_indices.get('Engine')
    NI_CLASS   = None
    NI_PACKAGE = extra_name_indices.get('Package')
    NI_EMITTER = None
    NI_SPRITE  = extra_name_indices.get('SpriteEmitter')
    NI_DLCFX   = extra_name_indices.get('DLCEffects')

    # Find Core, Class, Emitter in Abyss names
    for i, n in enumerate(names):
        if n == 'Core':     NI_CORE = i
        elif n == 'Class':  NI_CLASS = i
        elif n == 'Emitter': NI_EMITTER = i

    assert all(v is not None for v in [NI_CORE, NI_ENGINE, NI_CLASS, NI_PACKAGE,
                                        NI_EMITTER, NI_SPRITE, NI_DLCFX]), \
        "Missing required name indices"

    print("  Name table: %d entries (%d from Abyss + %d added)" %
          (total_name_count, name_count_src, total_name_count - name_count_src))

    # ── Phase 2: Build clean import table ─────────────────────────────
    # imp[0]: Core       (Package)
    # imp[1]: Engine     (Package)
    # imp[2]: DLCEffects (Package) - self-reference for outer
    # imp[3]: Class      (outer=Core)
    # imp[4]: Emitter    (outer=Engine)
    # imp[5]: SpriteEmitter (outer=Engine)
    import_entries = []
    import_entries.append(_write_import_entry(NI_CORE,   NI_PACKAGE, 0,  NI_CORE))     # 0: Core
    import_entries.append(_write_import_entry(NI_CORE,   NI_PACKAGE, 0,  NI_ENGINE))    # 1: Engine
    import_entries.append(_write_import_entry(NI_CORE,   NI_PACKAGE, 0,  NI_DLCFX))     # 2: DLCEffects
    import_entries.append(_write_import_entry(NI_CORE,   NI_CLASS,  -1,  NI_CLASS))      # 3: Core.Class
    import_entries.append(_write_import_entry(NI_CORE,   NI_CLASS,  -2,  NI_EMITTER))    # 4: Engine.Emitter
    import_entries.append(_write_import_entry(NI_CORE,   NI_CLASS,  -2,  NI_SPRITE))     # 5: Engine.SpriteEmitter

    import_table_bytes = b''.join(import_entries)
    num_imports = len(import_entries)

    # New import refs (1-based negative):
    NEW_EMITTER_REF  = -5   # imp[4]
    NEW_SPRITE_REF   = -6   # imp[5]

    # ── Phase 3: Prepare serial data ──────────────────────────────────
    # Build export list: [class1, child1a, child1b, ..., class2, child2a, ...]
    export_list = []  # (name_idx, class_idx, super_idx, outer_1based, flags, bs_field2, serial)
    export_ref_map = {}  # old_abyss_1based -> new_1based

    new_idx = 0  # 0-based
    for ename, edef in EMITTER_DEFS.items():
        cls_exp = exports[edef['class_idx']]
        cls_serial = bytearray(data[cls_exp['offset']:cls_exp['offset'] + cls_exp['size']])

        # The class's new 1-based ref
        cls_new_1based = new_idx + 1
        export_ref_map[edef['class_idx'] + 1] = cls_new_1based

        # Remap super CI at offset 8 (from Abyss Emitter import → new Emitter import)
        old_super_ci_end = 8
        _, old_super_ci_end = read_compact_index(bytes(cls_serial), 8)
        old_super_len = old_super_ci_end - 8
        new_super_bytes = _pad_ci(NEW_EMITTER_REF, old_super_len)
        for i, b in enumerate(new_super_bytes):
            cls_serial[8 + i] = b

        # Map children
        child_new_refs = []
        for ci, child_idx in enumerate(edef['children']):
            child_exp = exports[child_idx]
            child_new_1based = new_idx + 2 + ci  # class is first, then children
            export_ref_map[child_idx + 1] = child_new_1based
            child_new_refs.append(child_new_1based)

        # Remap child export refs in class serial
        for ci, (child_old_idx, ref_offset) in enumerate(
                zip(edef['children'], edef['child_ref_offsets'])):
            old_ref_1based = child_old_idx + 1
            old_ref_bytes = write_compact_index(old_ref_1based)
            old_ref_len = len(old_ref_bytes)
            new_ref = child_new_refs[ci]
            new_ref_bytes = _pad_ci(new_ref, old_ref_len)
            for i, b in enumerate(new_ref_bytes):
                cls_serial[ref_offset + i] = b

        # Add class export
        export_list.append({
            'name_idx': cls_exp['name_idx'],
            'class_idx': 0,  # Class
            'super_idx': NEW_EMITTER_REF,
            'outer_idx': 0,  # top-level
            'flags': cls_exp['flags'],
            'bs_field2': cls_exp['bs_field2'],
            'serial': bytes(cls_serial),
        })
        new_idx += 1

        # Add child exports
        for child_idx in edef['children']:
            child_exp = exports[child_idx]
            child_serial = data[child_exp['offset']:child_exp['offset'] + child_exp['size']]
            export_list.append({
                'name_idx': child_exp['name_idx'],
                'class_idx': NEW_SPRITE_REF,
                'super_idx': 0,
                'outer_idx': cls_new_1based,  # parent class
                'flags': child_exp['flags'],
                'bs_field2': child_exp['bs_field2'],
                'serial': child_serial,
            })
            new_idx += 1

    num_exports = len(export_list)
    print("  Exports: %d" % num_exports)

    # ── Phase 4: Calculate layout and build export table ──────────────
    name_file_offset = HEADER_SIZE
    import_file_offset = name_file_offset + len(name_table_bytes)
    export_file_offset = import_file_offset + len(import_table_bytes)

    # First pass: measure export table size with placeholder offsets
    placeholder_entries = []
    for exp_info in export_list:
        entry = _write_export_entry(
            exp_info['class_idx'], exp_info['super_idx'], exp_info['outer_idx'],
            exp_info['name_idx'], 0, exp_info['flags'],
            len(exp_info['serial']), 0xFFFFFF, 0, exp_info['bs_field2'])
        placeholder_entries.append(entry)
    export_table_size = sum(len(e) for e in placeholder_entries)

    serial_start = export_file_offset + export_table_size

    # Second pass: real offsets
    real_entries = []
    cur_offset = serial_start
    for exp_info in export_list:
        entry = _write_export_entry(
            exp_info['class_idx'], exp_info['super_idx'], exp_info['outer_idx'],
            exp_info['name_idx'], 0, exp_info['flags'],
            len(exp_info['serial']), cur_offset, 0, exp_info['bs_field2'])
        real_entries.append(entry)
        cur_offset += len(exp_info['serial'])

    # Check if table size changed
    real_table_size = sum(len(e) for e in real_entries)
    if real_table_size != export_table_size:
        serial_start = export_file_offset + real_table_size
        real_entries = []
        cur_offset = serial_start
        for exp_info in export_list:
            entry = _write_export_entry(
                exp_info['class_idx'], exp_info['super_idx'], exp_info['outer_idx'],
                exp_info['name_idx'], 0, exp_info['flags'],
                len(exp_info['serial']), cur_offset, 0, exp_info['bs_field2'])
            real_entries.append(entry)
            cur_offset += len(exp_info['serial'])

    # ── Phase 5: Assemble the file ────────────────────────────────────
    out = bytearray()

    # Header
    out.extend(struct.pack('<I', MAGIC))
    out.extend(struct.pack('<H', PKG_VERSION))
    out.extend(struct.pack('<H', PKG_LICENSE))
    out.extend(struct.pack('<I', HEADER_SIZE))
    out.extend(struct.pack('<I', total_name_count))
    out.extend(struct.pack('<I', name_file_offset))
    out.extend(struct.pack('<I', num_exports))
    out.extend(struct.pack('<I', export_file_offset))
    out.extend(struct.pack('<I', num_imports))
    out.extend(struct.pack('<I', import_file_offset))
    out.extend(struct.pack('<I', 0))        # heritage_count
    out.extend(b'\x00' * 16)                # GUID
    out.extend(struct.pack('<I', 1))         # generation_count
    out.extend(struct.pack('<I', num_exports))
    out.extend(struct.pack('<I', total_name_count))
    assert len(out) == HEADER_SIZE

    # Name table
    out.extend(name_table_bytes)
    # Import table
    out.extend(import_table_bytes)
    # Export table
    for entry in real_entries:
        out.extend(entry)
    # Serial data
    for exp_info in export_list:
        out.extend(exp_info['serial'])

    # Write
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(out)

    total_size = len(out)
    serial_total = sum(len(e['serial']) for e in export_list)
    print("  Package written: %d bytes (%.1f KB)" % (total_size, total_size / 1024))
    print("    Name table:   %d entries, %d bytes" % (total_name_count, len(name_table_bytes)))
    print("    Import table: %d entries, %d bytes" % (num_imports, len(import_table_bytes)))
    print("    Export table: %d entries, %d bytes" % (num_exports, sum(len(e) for e in real_entries)))
    print("    Serial data:  %d bytes" % serial_total)

    # Return mapping: emitter_name -> new_1based_ref
    result = {}
    idx = 0
    for ename, edef in EMITTER_DEFS.items():
        result[ename] = idx + 1  # 1-based
        idx += 1 + len(edef['children'])
    return result


def verify_dlc_effects(filepath):
    """Quick verification that the built package is parseable."""
    print("  Verifying %s..." % filepath)
    pkg = parse_package_deep(filepath)
    print("    Names: %d, Imports: %d, Exports: %d" % (
        len(pkg['names']), len(pkg['imports']), len(pkg['exports'])))
    for i, exp in enumerate(pkg['exports']):
        name = exp.get('name', '?')
        end = exp['offset'] + exp['size']
        in_bounds = end <= len(pkg['data'])
        print("    [%d] %-35s class=%d super=%d outer=%d size=%d %s" % (
            i, name[:35], exp['class_idx'], exp['super_idx'], exp['outer_idx'],
            exp['size'], 'OK' if in_bounds else '*** OUT OF BOUNDS'))
    return True


if __name__ == '__main__':
    ABYSS  = r'D:\SteamLibrary\steamapps\common\BioShock 2 Remastered\ContentBaked\pc\Maps\Abyss.bsm'
    OUTPUT = r'D:\SteamLibrary\steamapps\common\BioShock 2 Remastered\Build\Final\BakedScripts\pc\DLCEffects.U'

    print("Building DLCEffects.U package...")
    refs = build_dlc_effects_package(ABYSS, OUTPUT)
    print("\nExport refs: %s\n" % refs)
    verify_dlc_effects(OUTPUT)
