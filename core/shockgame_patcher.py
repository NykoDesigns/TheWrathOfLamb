"""
The War In Rapture: BioShock 2 — ShockGame.U Binary Patcher
=============================================================
Patches compiled class defaults in ShockGame.U to enable cut content.

SummonProtector is a stub class that ships with ShockGame.U but has no
compiled Track or Level defaults.  Without Track = TRACK_Plasmid the
game's equip system never shows the plasmid in the Quick Select wheel.

This module inserts the missing default properties into the class
serial data by appending a new serial blob and updating the export
table entry.
"""

import struct
import shutil
from pathlib import Path

from core.bsm_parser import (
    parse_package,
    read_compact_index,
    write_compact_index,
)
from core.bsm_spawn_patcher import write_export_entry


# ── Property builders ──────────────────────────────────────────────────

def _byte_property(name_ci, value):
    """Encode a single ByteProperty (enum) default: name_ref + info + val."""
    buf = bytearray()
    buf += name_ci                      # compact-index name ref
    buf += struct.pack('<I', 0)         # name instance number
    buf += bytes([0x01])                # info byte: ByteProperty, 1 byte
    buf += bytes([value & 0xFF])
    return bytes(buf)


def _find_export_entry_in_table(tbl_data, target_idx, export_count):
    """Walk the raw export table bytes and return (start, end) offsets
    of the entry at *target_idx*."""
    pos = 0
    for ei in range(export_count):
        start = pos
        _ci, pos = read_compact_index(tbl_data, pos)  # class
        _ci, pos = read_compact_index(tbl_data, pos)  # super
        pos += 4                                        # outer
        pos += 4                                        # unknown1
        _ci, pos = read_compact_index(tbl_data, pos)  # name
        pos += 4                                        # name_num
        pos += 8                                        # flags UINT64
        sz, pos = read_compact_index(tbl_data, pos)    # size
        if sz > 0:
            _ci, pos = read_compact_index(tbl_data, pos)  # offset
        pos += 4                                        # unknown2

        if ei == target_idx:
            return start, pos
    return None, None


def _parse_export_entry_full(entry_bytes):
    """Parse a raw export entry and return a dict with ALL fields including
    flags and unknown BioShock fields."""
    pos = 0
    ci, pos = read_compact_index(entry_bytes, pos)
    si, pos = read_compact_index(entry_bytes, pos)
    oi = struct.unpack_from('<i', entry_bytes, pos)[0]; pos += 4
    u1 = struct.unpack_from('<I', entry_bytes, pos)[0]; pos += 4
    ni, pos = read_compact_index(entry_bytes, pos)
    nn = struct.unpack_from('<I', entry_bytes, pos)[0]; pos += 4
    flags = struct.unpack_from('<Q', entry_bytes, pos)[0]; pos += 8
    sz, pos = read_compact_index(entry_bytes, pos)
    so = 0
    if sz > 0:
        so, pos = read_compact_index(entry_bytes, pos)
    u2 = struct.unpack_from('<I', entry_bytes, pos)[0]; pos += 4
    return {
        'class_idx': ci, 'super_idx': si, 'outer_idx': oi,
        'unknown1': u1, 'name_idx': ni, 'name_num': nn,
        'flags': flags, 'size': sz, 'offset': so, 'unknown2': u2,
    }


# ── Main patch function ────────────────────────────────────────────────

def patch_summon_protector(shockgame_path, backup_dir=None):
    """Insert Track and Level defaults into SummonProtector in ShockGame.U.

    Parameters
    ----------
    shockgame_path : str
        Full path to ShockGame.U (will be modified in-place).
    backup_dir : str, optional
        Directory to store a pristine backup.  If None, no backup is made.

    Returns
    -------
    dict  with keys 'patched' (bool) and 'message' (str).
    """
    sg_path = Path(shockgame_path)
    if not sg_path.exists():
        return {'patched': False, 'message': 'ShockGame.U not found'}

    data = bytearray(sg_path.read_bytes())

    # ── Parse package ──────────────────────────────────────────────────
    pkg = parse_package(str(sg_path))
    names = pkg['names']
    exports = pkg['exports']

    # Locate the SummonProtector class export
    sp_name_idx = None
    for i, n in enumerate(names):
        if n == 'SummonProtector':
            sp_name_idx = i
            break
    if sp_name_idx is None:
        return {'patched': False, 'message': 'SummonProtector name not found'}

    sp_exp_idx = None
    for i, e in enumerate(exports):
        if e['name_idx'] == sp_name_idx and e['class_idx'] == 0:
            sp_exp_idx = i
            break
    if sp_exp_idx is None:
        return {'patched': False,
                'message': 'SummonProtector class export not found'}

    sp_exp = exports[sp_exp_idx]
    old_serial = bytes(data[sp_exp['offset']:sp_exp['offset'] + sp_exp['size']])

    # ── Locate name indices ────────────────────────────────────────────
    color_name_idx = track_name_idx = level_name_idx = None
    for i, n in enumerate(names):
        if n == 'Color':
            color_name_idx = i
        elif n == 'Track':
            track_name_idx = i
        elif n == 'Level':
            level_name_idx = i

    if track_name_idx is None or level_name_idx is None:
        return {'patched': False,
                'message': 'Track/Level names not in name table'}

    # Find the Color property in the serial to verify structure
    color_ci = write_compact_index(color_name_idx)
    color_marker = color_ci + struct.pack('<I', 0) + bytes([0x01])
    color_pos = old_serial.find(color_marker)
    if color_pos < 0:
        return {'patched': False,
                'message': 'Color property not found in serial'}

    # Check if Track is ALREADY present (avoid double-patching)
    track_ci = write_compact_index(track_name_idx)
    track_marker = track_ci + struct.pack('<I', 0) + bytes([0x01])
    if old_serial.find(track_marker) >= 0:
        return {'patched': False,
                'message': 'Track already present (already patched)'}

    # ── Build the new serial ───────────────────────────────────────────
    # Insert Track and Level properties before the None terminator.
    # Layout: [header...Color prop] [Track prop] [Level prop] [None]
    prop_end = color_pos + len(color_marker) + 1   # +1 for Color value byte
    none_bytes = old_serial[prop_end:]              # 00 00000000

    track_prop = _byte_property(track_ci, 1)        # TRACK_Plasmid = 1
    level_ci_bytes = write_compact_index(level_name_idx)
    level_prop = _byte_property(level_ci_bytes, 1)  # LEVEL_Basic = 1

    new_serial = bytearray()
    new_serial += old_serial[:prop_end]
    new_serial += track_prop
    new_serial += level_prop
    new_serial += none_bytes

    size_delta = len(new_serial) - len(old_serial)

    # ── Backup ─────────────────────────────────────────────────────────
    if backup_dir:
        bak = Path(backup_dir) / 'ShockGame.U'
        if not bak.exists():
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(sg_path), str(bak))

    # ── Build the patched file ─────────────────────────────────────────
    # Append the new serial at the end of serial data (before tables).
    # Then shift all three tables forward by the new serial's length.
    # Only the SP export entry needs a new offset/size; all other export
    # entries keep their original values (serial offsets didn't move).

    name_offset   = struct.unpack_from('<I', data, 16)[0]
    export_count  = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    # Tables are at: name → import → export (verified for ShockGame.U)
    first_table_off = min(name_offset, import_offset, export_offset)
    new_serial_offset = first_table_off   # place new serial right before tables

    # Build output: prefix + new serial + shifted tables
    output = bytearray(data[:first_table_off])
    output += bytes(new_serial)

    shift = len(new_serial)

    # Copy name table
    new_name_offset = len(output)
    output += data[name_offset:import_offset]

    # Copy import table
    new_import_offset = len(output)
    output += data[import_offset:export_offset]

    # Copy export table — surgically replace just the SP entry
    new_export_offset = len(output)
    exp_tbl = bytes(data[export_offset:])

    entry_start, entry_end = _find_export_entry_in_table(
        exp_tbl, sp_exp_idx, export_count)
    if entry_start is None:
        return {'patched': False,
                'message': 'Could not locate SP export entry in table'}

    # Parse the original entry to preserve all fields
    original_entry = _parse_export_entry_full(exp_tbl[entry_start:entry_end])
    original_entry['size'] = len(new_serial)
    original_entry['offset'] = new_serial_offset
    new_entry_bytes = write_export_entry(original_entry, data)

    output += exp_tbl[:entry_start]
    output += new_entry_bytes
    output += exp_tbl[entry_end:]

    # ── Patch header ───────────────────────────────────────────────────
    struct.pack_into('<I', output, 16, new_name_offset)
    struct.pack_into('<I', output, 24, new_export_offset)
    struct.pack_into('<I', output, 32, new_import_offset)

    # ── Write ──────────────────────────────────────────────────────────
    sg_path.write_bytes(bytes(output))

    return {
        'patched': True,
        'message': ('Inserted Track=TRACK_Plasmid + Level=LEVEL_Basic '
                    '(+%d bytes)' % size_delta),
    }


def _parse_func_header(serial):
    """Parse a UFunction serial header to locate ScriptSize and bytecode start.

    Returns (bc_start, ss_offset, scriptsize) where:
        bc_start    – byte offset in serial where bytecodes begin
        ss_offset   – byte offset of the ScriptSize INT32 in serial
        scriptsize  – current ScriptSize value
    """
    pos = 8   # skip fixed 8 bytes
    _, pos = read_compact_index(serial, pos)  # property list terminator CI
    pos += 4                                  # property list terminator instance
    _, pos = read_compact_index(serial, pos)  # Super CI
    _, pos = read_compact_index(serial, pos)  # Next CI
    _, pos = read_compact_index(serial, pos)  # ScriptText CI
    _, pos = read_compact_index(serial, pos)  # Children CI
    _, pos = read_compact_index(serial, pos)  # FriendlyName CI
    pos += 4                                  # FriendlyName instance
    pos += 4 + 4 + 1 + 4 + 2                 # fixed fields + Line + iNative
    ss_offset = pos
    ss = struct.unpack_from('<I', serial, pos)[0]
    pos += 4
    return pos, ss_offset, ss


def patch_dual_drill(shockgame_path, backup_dir=None):
    """Patch Drill class to attach a second drill model on the left hand.

    Modifies OnEquippingFinished to call Hands.ApplyScriptedHandAttachment
    and OnUnEquippingStarted to call Hands.RemoveScriptedHandAttachment.

    Parameters
    ----------
    shockgame_path : str
        Full path to ShockGame.U (will be modified in-place).
    backup_dir : str, optional
        Directory to store a pristine backup.  If None, no backup is made.

    Returns
    -------
    dict  with keys 'patched' (bool) and 'message' (str).
    """
    sg_path = Path(shockgame_path)
    if not sg_path.exists():
        return {'patched': False, 'message': 'ShockGame.U not found'}

    data = bytearray(sg_path.read_bytes())
    pkg = parse_package(str(sg_path))
    names = pkg['names']
    exports = pkg['exports']

    # ── Locate name indices ───────────────────────────────────────────
    name_apply = name_remove = name_bone = None
    for i, n in enumerate(names):
        if n == 'ApplyScriptedGathererAttachment':
            name_apply = i
        elif n == 'RemoveScriptedGathererAttachment':
            name_remove = i
        elif n == 'Pistol':
            name_bone = i
    if None in (name_apply, name_remove, name_bone):
        return {'patched': False,
                'message': 'Required names not found in name table'}

    # ── Locate exports ────────────────────────────────────────────────
    # OnEquippingFinished (exp[14098]) and OnUnEquippingStarted (exp[14099])
    # in the Drill class.  Verify by checking the existing bytecodes.
    EXP_EQUIP = 14098
    EXP_UNEQUIP = 14099

    e_equip = exports[EXP_EQUIP]
    e_unequip = exports[EXP_UNEQUIP]

    if e_equip['name'] != 'OnEquippingFinished':
        return {'patched': False,
                'message': 'exp[14098] is not OnEquippingFinished'}
    if e_unequip['name'] != 'OnUnEquippingStarted':
        return {'patched': False,
                'message': 'exp[14099] is not OnUnEquippingStarted'}

    old_serial_eq = bytes(data[e_equip['offset']:
                               e_equip['offset'] + e_equip['size']])
    old_serial_uneq = bytes(data[e_unequip['offset']:
                                  e_unequip['offset'] + e_unequip['size']])

    # Parse headers to find bytecode boundaries
    bc_start_eq, ss_off_eq, ss_eq = _parse_func_header(old_serial_eq)
    bc_start_uneq, ss_off_uneq, ss_uneq = _parse_func_header(old_serial_uneq)

    FOOTER_SIZE = 7  # OperatorPrec(1) + FuncFlags(4) + RepOffset(2)
    old_bc_eq = old_serial_eq[bc_start_eq:-FOOTER_SIZE]
    old_bc_uneq = old_serial_uneq[bc_start_uneq:-FOOTER_SIZE]
    footer_eq = old_serial_eq[-FOOTER_SIZE:]
    footer_uneq = old_serial_uneq[-FOOTER_SIZE:]

    # ── Check for double-patch ────────────────────────────────────────
    apply_vfunc = (bytes([0x1b]) + write_compact_index(name_apply)
                   + struct.pack('<I', 0))
    if old_bc_eq.find(apply_vfunc) >= 0:
        return {'patched': False,
                'message': 'Dual drill already patched'}

    # ── Build new bytecodes ───────────────────────────────────────────
    # Compact indices for references
    ci_hands = write_compact_index(989)    # Hands property ref
    ci_dbac  = write_compact_index(9741)   # DrillBitAttachmentClass property ref
    ci_apply = write_compact_index(name_apply)
    ci_remove = write_compact_index(name_remove)
    ci_bone = write_compact_index(name_bone)

    # Hands.ApplyScriptedGathererAttachment(DrillBitAttachmentClass, 'Pistol')
    apply_call = bytes([0x19])                                  # EX_Context
    apply_call += bytes([0x01]) + ci_hands                      # InstanceVariable(Hands)
    apply_call += struct.pack('<H', 28)                         # wSkip = member memory size
    apply_call += bytes([0x00])                                 # bSize (void)
    apply_call += bytes([0x1b]) + ci_apply + struct.pack('<I', 0)  # VirtualFunction
    apply_call += bytes([0x01]) + ci_dbac                       # param1: DrillBitAttachmentClass
    apply_call += bytes([0x21]) + ci_bone + struct.pack('<I', 0)    # param2: NameConst('Pistol')
    apply_call += bytes([0x16])                                 # EndFunctionParms

    # Hands.RemoveScriptedGathererAttachment()
    remove_call = bytes([0x19])                                 # EX_Context
    remove_call += bytes([0x01]) + ci_hands                     # InstanceVariable(Hands)
    remove_call += struct.pack('<H', 10)                        # wSkip (verified from existing caller)
    remove_call += bytes([0x00])                                # bSize (void)
    remove_call += bytes([0x1b]) + ci_remove + struct.pack('<I', 0)  # VirtualFunction
    remove_call += bytes([0x16])                                # EndFunctionParms

    # Insert apply_call before Return (04 0b) in OnEquippingFinished
    new_bc_eq = old_bc_eq[:-2] + apply_call + old_bc_eq[-2:]
    # Insert remove_call at start of OnUnEquippingStarted
    new_bc_uneq = remove_call + old_bc_uneq

    # ── Build new serials ─────────────────────────────────────────────
    # ScriptSize = in-memory byte count.  64-bit engine: opcodes 1B,
    # CI refs (pointers) 8B, FName 8B, INT32 4B, UINT16 2B, BYTE 1B.
    # apply_call mem: Context(1)+InstVar(1)+CI(8)+U16(2)+B(1)
    #   +VirtFunc(1)+FName(8)+InstVar(1)+CI(8)+NameConst(1)+FName(8)+End(1)=41
    # remove_call mem: Context(1)+InstVar(1)+CI(8)+U16(2)+B(1)
    #   +VirtFunc(1)+FName(8)+End(1)=23
    APPLY_MEM  = 41
    REMOVE_MEM = 23
    new_ss_eq = ss_eq + APPLY_MEM
    new_ss_uneq = ss_uneq + REMOVE_MEM

    new_serial_eq = bytearray(old_serial_eq[:ss_off_eq])
    new_serial_eq += struct.pack('<I', new_ss_eq)
    new_serial_eq += new_bc_eq
    new_serial_eq += footer_eq

    new_serial_uneq = bytearray(old_serial_uneq[:ss_off_uneq])
    new_serial_uneq += struct.pack('<I', new_ss_uneq)
    new_serial_uneq += new_bc_uneq
    new_serial_uneq += footer_uneq

    # ── Backup ────────────────────────────────────────────────────────
    if backup_dir:
        bak = Path(backup_dir) / 'ShockGame.U'
        if not bak.exists():
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(sg_path), str(bak))

    # ── Rebuild file (same pattern as patch_summon_protector) ─────────
    name_offset   = struct.unpack_from('<I', data, 16)[0]
    export_count  = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    first_table_off = min(name_offset, import_offset, export_offset)

    # Place new serials right before tables
    output = bytearray(data[:first_table_off])
    new_offset_eq = len(output)
    output += bytes(new_serial_eq)
    new_offset_uneq = len(output)
    output += bytes(new_serial_uneq)

    shift = len(new_serial_eq) + len(new_serial_uneq)

    # Copy name table
    new_name_offset = len(output)
    output += data[name_offset:import_offset]

    # Copy import table
    new_import_offset = len(output)
    output += data[import_offset:export_offset]

    # Copy export table with patched entries
    new_export_offset = len(output)
    exp_tbl = bytes(data[export_offset:])

    # Patch both entries
    patches = [
        (EXP_EQUIP, len(new_serial_eq), new_offset_eq),
        (EXP_UNEQUIP, len(new_serial_uneq), new_offset_uneq),
    ]

    # Walk the export table and replace entries as needed
    tbl_out = bytearray()
    pos = 0
    for ei in range(export_count):
        start = pos
        _ci, pos = read_compact_index(exp_tbl, pos)
        _ci, pos = read_compact_index(exp_tbl, pos)
        pos += 4 + 4
        _ci, pos = read_compact_index(exp_tbl, pos)
        pos += 4 + 8
        sz, pos = read_compact_index(exp_tbl, pos)
        if sz > 0:
            _ci, pos = read_compact_index(exp_tbl, pos)
        pos += 4

        match = None
        for pidx, psize, poffset in patches:
            if ei == pidx:
                match = (psize, poffset)
                break

        if match:
            entry_data = _parse_export_entry_full(exp_tbl[start:pos])
            entry_data['size'] = match[0]
            entry_data['offset'] = match[1]
            tbl_out += write_export_entry(entry_data, data)
        else:
            tbl_out += exp_tbl[start:pos]

    output += bytes(tbl_out)

    # ── Patch header ──────────────────────────────────────────────────
    struct.pack_into('<I', output, 16, new_name_offset)
    struct.pack_into('<I', output, 24, new_export_offset)
    struct.pack_into('<I', output, 32, new_import_offset)

    # ── Write ─────────────────────────────────────────────────────────
    sg_path.write_bytes(bytes(output))

    return {
        'patched': True,
        'message': ('Dual drill: patched OnEquippingFinished (+%d bc) '
                    'and OnUnEquippingStarted (+%d bc)'
                    % (len(apply_call), len(remove_call))),
    }


# Emitter choices for the flame drill effect.
# key -> (ref_value, expected_name, description, source)
#   source='local'      : ref_value = 0-based export index in ShockGame.U
#   source='dlceffects'  : ref_value = class name in DLCEffects.U (import added dynamically)
FLAME_EMITTERS = {
    'flamethrower':  (776, 'FlameThrowerTestB',          'Flamethrower blast (intense)',      'local'),
    'trap_fire':     (774, 'RivetGun_Trap_Fire',         'Rivet trap fire (small, localized)','local'),
    'adam_trail':    (773, 'DaddySense_Trail',            'ADAM-sense trail (ethereal glow)',  'local'),
    'tesla_spark':   (393, 'Shotgun_Tesla_Spark',         'Tesla sparks (electrical)',         'local'),
    'incinerate':    (789, 'Incinerate_Player_',          'Incinerate plasmid (fireball)',     'local'),
    'cigarette':     (0,   'Cigarette_Glow',              'Cigarette glow (subtle ember)',     'dlceffects'),
    'idle_fire':     (0,   'PLSM_FIRE_idle_advanced',     'Idle fire glow (ambient)',          'dlceffects'),
}

# Names needed in ShockGame.U for DLCEffects imports
_DLCEFFECTS_IMPORT_NAMES = ['DLCEffects', 'Cigarette_Glow', 'PLSM_FIRE_idle_advanced']

# Default name flags for appended name entries
_DEFAULT_NAME_FLAGS = bytes([0x10, 0x00, 0x07, 0x00, 0x00, 0x00, 0x00, 0x00])


def _encode_name_entry(text):
    """Encode a name table entry: BYTE wchar_count + UTF-16LE + 8-byte flags."""
    encoded = (text + '\x00').encode('utf-16-le')
    wchar_len = len(text) + 1
    return bytes([wchar_len]) + encoded + _DEFAULT_NAME_FLAGS


def _write_import_entry_raw(cls_pkg_ni, cls_name_ni, outer_idx, obj_name_ni):
    """Build a raw import table entry."""
    buf = bytearray()
    buf.extend(write_compact_index(cls_pkg_ni))
    buf.extend(struct.pack('<I', 0))
    buf.extend(write_compact_index(cls_name_ni))
    buf.extend(struct.pack('<I', 0))
    buf.extend(struct.pack('<i', outer_idx))
    buf.extend(write_compact_index(obj_name_ni))
    buf.extend(struct.pack('<I', 0))
    return bytes(buf)


def patch_flame_drill(shockgame_path, backup_dir=None, emitter_style='trap_fire'):
    """Patch Drill class to attach an emitter effect when equipped.

    Injects Hands.ApplyScriptedHandAttachment(class'<Emitter>', 'Drill')
    into OnEquippingFinished, and Hands.RemoveScriptedHandAttachment() into
    OnUnEquippingStarted.  The emitter persists while the drill is held.

    Uses EX_ObjectConst (0x20) to reference the emitter class directly.

    Parameters
    ----------
    shockgame_path : str
        Full path to ShockGame.U (will be modified in-place).
    backup_dir : str, optional
        Directory to store a pristine backup.
    emitter_style : str
        Key from FLAME_EMITTERS dict.  Default 'trap_fire'.

    Returns
    -------
    dict  with keys 'patched' (bool) and 'message' (str).
    """
    if emitter_style not in FLAME_EMITTERS:
        return {'patched': False,
                'message': 'Unknown emitter style: %s' % emitter_style}
    sg_path = Path(shockgame_path)
    if not sg_path.exists():
        return {'patched': False, 'message': 'ShockGame.U not found'}

    data = bytearray(sg_path.read_bytes())
    pkg = parse_package(str(sg_path))
    names = pkg['names']
    exports = pkg['exports']

    # ── Locate name indices ───────────────────────────────────────────
    name_apply = name_remove = name_bone = None
    for i, n in enumerate(names):
        if n == 'ApplyScriptedHandAttachment':
            name_apply = i
        elif n == 'RemoveScriptedHandAttachment':
            name_remove = i
        elif n == 'Drill':
            name_bone = i
    if None in (name_apply, name_remove, name_bone):
        return {'patched': False,
                'message': 'Required names not found in name table'}

    # ── Resolve emitter reference ──────────────────────────────────────
    ref_val, expected_name, emitter_desc, emitter_src = FLAME_EMITTERS[emitter_style]
    needs_dlceffects = (emitter_src == 'dlceffects')

    if not needs_dlceffects:
        # Local export: verify
        if exports[ref_val]['name'] != expected_name:
            return {'patched': False,
                    'message': 'exp[%d] is not %s' % (ref_val, expected_name)}

    # ── Locate target functions ────────────────────────────────────────
    EXP_EQUIP = 14098
    EXP_UNEQUIP = 14099

    e_equip = exports[EXP_EQUIP]
    e_unequip = exports[EXP_UNEQUIP]

    if e_equip['name'] != 'OnEquippingFinished':
        return {'patched': False,
                'message': 'exp[14098] is not OnEquippingFinished'}
    if e_unequip['name'] != 'OnUnEquippingStarted':
        return {'patched': False,
                'message': 'exp[14099] is not OnUnEquippingStarted'}

    old_serial_eq = bytes(data[e_equip['offset']:
                                e_equip['offset'] + e_equip['size']])
    old_serial_uneq = bytes(data[e_unequip['offset']:
                                   e_unequip['offset'] + e_unequip['size']])

    bc_start_eq, ss_off_eq, ss_eq = _parse_func_header(old_serial_eq)
    bc_start_uneq, ss_off_uneq, ss_uneq = _parse_func_header(old_serial_uneq)

    FOOTER_SIZE = 7
    old_bc_eq = old_serial_eq[bc_start_eq:-FOOTER_SIZE]
    old_bc_uneq = old_serial_uneq[bc_start_uneq:-FOOTER_SIZE]
    footer_eq = old_serial_eq[-FOOTER_SIZE:]
    footer_uneq = old_serial_uneq[-FOOTER_SIZE:]

    # ── Check for double-patch ────────────────────────────────────────
    apply_vfunc = (bytes([0x1b]) + write_compact_index(name_apply)
                   + struct.pack('<I', 0))
    if old_bc_eq.find(apply_vfunc) >= 0:
        return {'patched': False,
                'message': 'Flame drill already patched'}

    # Also check for dual drill patch (uses GathererAttachment)
    for i, n in enumerate(names):
        if n == 'ApplyScriptedGathererAttachment':
            gatherer_vfunc = (bytes([0x1b]) + write_compact_index(i)
                              + struct.pack('<I', 0))
            if old_bc_eq.find(gatherer_vfunc) >= 0:
                return {'patched': False,
                        'message': 'Dual drill already patched — conflicts '
                                   'with flame drill (same injection point)'}
            break

    # ── Build new bytecodes ───────────────────────────────────────────
    ci_hands  = write_compact_index(989)   # Hands property (InstanceVariable)
    ci_apply  = write_compact_index(name_apply)
    ci_remove = write_compact_index(name_remove)
    ci_bone   = write_compact_index(name_bone)
    if needs_dlceffects:
        # DLCEffects emitter: compute the import ref from current import count.
        # Imports will be appended: [DLCEffects pkg, Cigarette_Glow, PLSM_FIRE_idle]
        import_count_orig = struct.unpack_from('<I', data, 28)[0]
        dlc_class_names = [n for n in _DLCEFFECTS_IMPORT_NAMES if n != 'DLCEffects']
        class_import_offset = dlc_class_names.index(expected_name)
        # import[import_count_orig] = DLCEffects package
        # import[import_count_orig + 1 + class_import_offset] = the emitter class
        new_imp_idx = import_count_orig + 1 + class_import_offset  # 0-based
        ci_flame = write_compact_index(-(new_imp_idx + 1))  # 1-based negative ref
    else:
        ci_flame = write_compact_index(ref_val + 1)  # 1-based export ref

    # Hands.ApplyScriptedHandAttachment(class'<Emitter>', 'Drill')
    apply_call = bytes([0x19])                                    # EX_Context
    apply_call += bytes([0x01]) + ci_hands                        # InstanceVariable(Hands)
    apply_call += struct.pack('<H', 28)                           # wSkip = member memory size
    apply_call += bytes([0x00])                                   # bSize (void)
    apply_call += bytes([0x1b]) + ci_apply + struct.pack('<I', 0) # VirtualFunction(Apply)
    apply_call += bytes([0x20]) + ci_flame                        # ObjectConst(FlameThrowerTestB)
    apply_call += bytes([0x21]) + ci_bone + struct.pack('<I', 0)  # NameConst('Drill')
    apply_call += bytes([0x16])                                   # EndFunctionParms

    # Hands.RemoveScriptedHandAttachment()
    remove_call = bytes([0x19])                                     # EX_Context
    remove_call += bytes([0x01]) + ci_hands                         # InstanceVariable(Hands)
    remove_call += struct.pack('<H', 10)                            # wSkip
    remove_call += bytes([0x00])                                    # bSize (void)
    remove_call += bytes([0x1b]) + ci_remove + struct.pack('<I', 0) # VirtualFunction(Remove)
    remove_call += bytes([0x16])                                    # EndFunctionParms

    # Insert apply_call before Return (04 0b) in OnEquippingFinished
    new_bc_eq = old_bc_eq[:-2] + apply_call + old_bc_eq[-2:]
    # Insert remove_call at start of OnUnEquippingStarted
    new_bc_uneq = remove_call + old_bc_uneq

    # ── Build new serials ─────────────────────────────────────────────
    # Memory sizes (64-bit): ObjectConst = 1+8 = 9, same as InstanceVar.
    # apply_call mem: Context(1)+InstVar(1)+CI(8)+U16(2)+B(1)
    #   +VirtFunc(1)+FName(8)+ObjConst(1)+CI(8)+NameConst(1)+FName(8)+End(1)=41
    # remove_call mem: Context(1)+InstVar(1)+CI(8)+U16(2)+B(1)
    #   +VirtFunc(1)+FName(8)+End(1)=23
    APPLY_MEM  = 41
    REMOVE_MEM = 23
    new_ss_eq = ss_eq + APPLY_MEM
    new_ss_uneq = ss_uneq + REMOVE_MEM

    new_serial_eq = bytearray(old_serial_eq[:ss_off_eq])
    new_serial_eq += struct.pack('<I', new_ss_eq)
    new_serial_eq += new_bc_eq
    new_serial_eq += footer_eq

    new_serial_uneq = bytearray(old_serial_uneq[:ss_off_uneq])
    new_serial_uneq += struct.pack('<I', new_ss_uneq)
    new_serial_uneq += new_bc_uneq
    new_serial_uneq += footer_uneq

    # ── Backup ────────────────────────────────────────────────────────
    if backup_dir:
        bak = Path(backup_dir) / 'ShockGame.U'
        if not bak.exists():
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(sg_path), str(bak))

    # ── Rebuild file ───────────────────────────────────────────────────
    # NOTE: In ShockGame.U the name table overlaps with the import table
    # (the last ~24 "name" entries are read from import table bytes).
    # We must walk each table independently and copy them to separate,
    # non-overlapping regions in the output.

    name_offset_orig   = struct.unpack_from('<I', data, 16)[0]
    name_count_orig    = struct.unpack_from('<I', data, 12)[0]
    export_count       = struct.unpack_from('<I', data, 20)[0]
    export_offset_orig = struct.unpack_from('<I', data, 24)[0]
    import_count_orig  = struct.unpack_from('<I', data, 28)[0]
    import_offset_orig = struct.unpack_from('<I', data, 32)[0]

    first_table_off = min(name_offset_orig, import_offset_orig, export_offset_orig)

    output = bytearray(data[:first_table_off])
    new_offset_eq = len(output)
    output += bytes(new_serial_eq)
    new_offset_uneq = len(output)
    output += bytes(new_serial_uneq)

    # ── Walk and copy name table (entry by entry) ──────────────────────
    new_name_offset = len(output)
    pos = name_offset_orig
    for _ in range(name_count_orig):
        entry_start = pos
        l = data[pos]; pos += 1
        pos += (l * 2 + 8 if l else 8)
        output += data[entry_start:pos]
    new_name_count = name_count_orig

    # DLCEffects: append new name entries
    dlc_name_indices = {}
    if needs_dlceffects:
        existing_name_set = set(names)
        for nm in _DLCEFFECTS_IMPORT_NAMES:
            if nm in existing_name_set:
                dlc_name_indices[nm] = names.index(nm)
            else:
                dlc_name_indices[nm] = new_name_count
                output += _encode_name_entry(nm)
                new_name_count += 1

    # ── Walk and copy import table (entry by entry) ────────────────────
    new_import_offset = len(output)
    pos = import_offset_orig
    for _ in range(import_count_orig):
        entry_start = pos
        _, pos = read_compact_index(data, pos); pos += 4   # class_pkg + num
        _, pos = read_compact_index(data, pos); pos += 4   # class_name + num
        pos += 4                                            # outer_idx
        _, pos = read_compact_index(data, pos); pos += 4   # obj_name + num
        output += data[entry_start:pos]
    new_import_count = import_count_orig

    # DLCEffects: append new import entries
    if needs_dlceffects:
        NI_CORE = 9; NI_PACKAGE = 13174; NI_CLASS = 1042
        ni_dlcfx = dlc_name_indices['DLCEffects']
        dlcfx_imp_ref = -(new_import_count + 1)  # 1-based neg ref for the package
        output += _write_import_entry_raw(NI_CORE, NI_PACKAGE, 0, ni_dlcfx)
        new_import_count += 1
        for cls_name in [n for n in _DLCEFFECTS_IMPORT_NAMES if n != 'DLCEffects']:
            ni_cls = dlc_name_indices[cls_name]
            output += _write_import_entry_raw(NI_CORE, NI_CLASS, dlcfx_imp_ref, ni_cls)
            new_import_count += 1

    # ── Copy export table (from original) ──────────────────────────────
    new_export_offset = len(output)
    exp_tbl = bytes(data[export_offset_orig:])

    patches = [
        (EXP_EQUIP, len(new_serial_eq), new_offset_eq),
        (EXP_UNEQUIP, len(new_serial_uneq), new_offset_uneq),
    ]

    tbl_out = bytearray()
    pos = 0
    for ei in range(export_count):
        start = pos
        _ci, pos = read_compact_index(exp_tbl, pos)
        _ci, pos = read_compact_index(exp_tbl, pos)
        pos += 4 + 4
        _ci, pos = read_compact_index(exp_tbl, pos)
        pos += 4 + 8
        sz, pos = read_compact_index(exp_tbl, pos)
        if sz > 0:
            _ci, pos = read_compact_index(exp_tbl, pos)
        pos += 4

        match = None
        for pidx, psize, poffset in patches:
            if ei == pidx:
                match = (psize, poffset)
                break

        if match:
            entry_data = _parse_export_entry_full(exp_tbl[start:pos])
            entry_data['size'] = match[0]
            entry_data['offset'] = match[1]
            tbl_out += write_export_entry(entry_data, data)
        else:
            tbl_out += exp_tbl[start:pos]

    output += bytes(tbl_out)

    struct.pack_into('<I', output, 16, new_name_offset)
    struct.pack_into('<I', output, 24, new_export_offset)
    struct.pack_into('<I', output, 32, new_import_offset)
    if needs_dlceffects:
        struct.pack_into('<I', output, 12, new_name_count)
        struct.pack_into('<I', output, 28, new_import_count)
        # BS2 v143 header: GUID at 36 (16 bytes), gen_count at 52,
        # gen[0].export_count at 56, gen[0].name_count at 60
        struct.pack_into('<I', output, 60, new_name_count)

    sg_path.write_bytes(bytes(output))

    return {
        'patched': True,
        'message': ('Flame drill [%s]: patched OnEquippingFinished (+%d bc) '
                    'and OnUnEquippingStarted (+%d bc)'
                    % (emitter_desc, len(apply_call), len(remove_call))),
    }


def patch_tk_upgrade(shockgame_path, backup_dir=None):
    """Upgrade TK1/TK2 to pick up living pawns (TK3 behaviour) in ShockGame.U.

    Inserts CanTKLivingPawns=True into the default properties of
    TelekinesisBasicAbility and TelekinesisAdvancedAbility.

    Parameters
    ----------
    shockgame_path : str
        Full path to ShockGame.U (will be modified in-place).
    backup_dir : str, optional
        Directory to store a pristine backup.

    Returns
    -------
    dict  with keys 'patched' (bool) and 'message' (str).
    """
    from core.bsm_parser import parse_properties

    sg_path = Path(shockgame_path)
    if not sg_path.exists():
        return {'patched': False, 'message': 'ShockGame.U not found'}

    data = bytearray(sg_path.read_bytes())
    pkg = parse_package(str(sg_path))
    names = pkg['names']
    exports = pkg['exports']

    # ── Locate name index for CanTKLivingPawns ─────────────────────────
    cantkpawn_ni = None
    for i, n in enumerate(names):
        if n == 'CanTKLivingPawns':
            cantkpawn_ni = i
            break
    if cantkpawn_ni is None:
        return {'patched': False, 'message': 'CanTKLivingPawns name not found'}

    cantk_ci = write_compact_index(cantkpawn_ni)
    # BoolProperty TRUE: info byte = type 3 | size_bits 5<<4 | array_flag 1<<7 = 0xD3
    # Followed by 1 byte size=0 (size_bits=5 → read 1 byte of prop_size)
    cantk_prop = cantk_ci + struct.pack('<I', 0) + bytes([0xD3, 0x00])

    # ── Identify target exports ────────────────────────────────────────
    target_names = ('TelekinesisBasicAbility', 'TelekinesisAdvancedAbility')
    target_exps = []
    for tname in target_names:
        for i, e in enumerate(exports):
            if e['name'] == tname and e['class_idx'] == 0:
                target_exps.append((i, e))
                break
        else:
            return {'patched': False,
                    'message': '%s class export not found' % tname}

    # ── Check for double-patch (CanTKLivingPawns already in serial) ────
    cantk_marker = cantk_ci + struct.pack('<I', 0)
    for idx, exp in target_exps:
        serial = data[exp['offset']:exp['offset'] + exp['size']]
        if serial.find(cantk_marker) >= 0:
            return {'patched': False,
                    'message': 'CanTKLivingPawns already in %s (patched)' % exp['name']}

    # ── Build new serials ──────────────────────────────────────────────
    PROP_START = 142  # verified offset where default properties begin
    new_serials = []
    for idx, exp in target_exps:
        serial = bytes(data[exp['offset']:exp['offset'] + exp['size']])
        try:
            props = parse_properties(serial, PROP_START, names, exp['size'])
        except Exception:
            return {'patched': False,
                    'message': 'Failed to parse properties of %s' % exp['name']}
        if not props:
            return {'patched': False,
                    'message': 'No properties found in %s' % exp['name']}

        # None terminator is right after the last property value data
        last = props[-1]
        none_off = last[7] + last[3]  # val_pos + prop_size
        if serial[none_off:none_off + 5] != b'\x00\x00\x00\x00\x00':
            return {'patched': False,
                    'message': 'None terminator not found at expected offset in %s' % exp['name']}

        # Insert CanTKLivingPawns before None terminator
        new_serial = bytearray(serial[:none_off])
        new_serial += cantk_prop
        new_serial += serial[none_off:]
        new_serials.append(bytes(new_serial))

    # ── Backup ─────────────────────────────────────────────────────────
    if backup_dir:
        bak = Path(backup_dir) / 'ShockGame.U'
        if not bak.exists():
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(sg_path), str(bak))

    # ── Append new serials and shift tables ────────────────────────────
    name_offset   = struct.unpack_from('<I', data, 16)[0]
    export_count  = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    first_table_off = min(name_offset, import_offset, export_offset)

    output = bytearray(data[:first_table_off])

    # Append each new serial and record its new offset
    new_offsets = []
    for ns in new_serials:
        new_offsets.append(len(output))
        output += ns

    # Copy name table
    new_name_offset = len(output)
    output += data[name_offset:import_offset]

    # Copy import table
    new_import_offset = len(output)
    output += data[import_offset:export_offset]

    # Copy export table — replace target entries with new offset/size
    new_export_offset = len(output)
    exp_tbl = bytes(data[export_offset:])

    # Build set of entries to replace
    replace_map = {}
    for j, (idx, exp) in enumerate(target_exps):
        replace_map[idx] = (new_offsets[j], len(new_serials[j]))

    # Walk export table and splice replacements
    pos = 0
    for ei in range(export_count):
        start = pos
        _ci, pos = read_compact_index(exp_tbl, pos)
        _ci, pos = read_compact_index(exp_tbl, pos)
        pos += 4 + 4
        _ci, pos = read_compact_index(exp_tbl, pos)
        pos += 4 + 8
        sz, pos = read_compact_index(exp_tbl, pos)
        if sz > 0:
            _ci, pos = read_compact_index(exp_tbl, pos)
        pos += 4

        if ei in replace_map:
            new_off, new_sz = replace_map[ei]
            orig = _parse_export_entry_full(exp_tbl[start:pos])
            orig['size'] = new_sz
            orig['offset'] = new_off
            new_entry = write_export_entry(orig, data)
            output += new_entry
        else:
            output += exp_tbl[start:pos]

    # ── Patch header ───────────────────────────────────────────────────
    struct.pack_into('<I', output, 16, new_name_offset)
    struct.pack_into('<I', output, 24, new_export_offset)
    struct.pack_into('<I', output, 32, new_import_offset)

    # ── Write ──────────────────────────────────────────────────────────
    sg_path.write_bytes(bytes(output))

    patched_names = [exp['name'] for _, exp in target_exps]
    delta = sum(len(ns) for ns in new_serials) - sum(e['size'] for _, e in target_exps)
    return {
        'patched': True,
        'message': 'Inserted CanTKLivingPawns=True into %s (+%d bytes)' % (
            ', '.join(patched_names), delta),
    }


def patch_hypnotize_reflect(shockgame_path, backup_dir=None):
    """Inject SetDamageReflection(true, 1.0) into Hypnotize projectile code.

    Patches ModifyDamageStimuli in BerserkProjectile, HypnotizeProjectile,
    and HypnotizeMasterProjectile so that every enemy hit by a Hypnotize
    projectile gets damage reflection enabled (Vampiric Thrall).

    Parameters
    ----------
    shockgame_path : str
        Full path to ShockGame.U (will be modified in-place).
    backup_dir : str, optional
        Directory to store a pristine backup.

    Returns
    -------
    dict  with keys 'patched' (bool) and 'message' (str).
    """
    sg_path = Path(shockgame_path)
    if not sg_path.exists():
        return {'patched': False, 'message': 'ShockGame.U not found'}

    data = bytearray(sg_path.read_bytes())
    pkg = parse_package(str(sg_path))
    names = pkg['names']
    exports = pkg['exports']

    # ── Locate SetDamageReflection name index ──────────────────────────
    set_reflect_ni = None
    for i, n in enumerate(names):
        if n == 'SetDamageReflection':
            set_reflect_ni = i
            break
    if set_reflect_ni is None:
        return {'patched': False,
                'message': 'SetDamageReflection name not found'}

    ci_set_reflect = write_compact_index(set_reflect_ni)

    # Double-patch marker: FinalFunction + FName(SetDamageReflection)
    patch_marker = bytes([0x1b]) + ci_set_reflect + struct.pack('<I', 0)

    # ── Identify the 3 ModifyDamageStimuli targets ─────────────────────
    # Each tuple: (func_export_0idx, parent_class_name)
    TARGETS = [
        ('BerserkProjectile',            'ModifyDamageStimuli'),
        ('HypnotizeProjectile',          'ModifyDamageStimuli'),
        ('HypnotizeMasterProjectile',    'ModifyDamageStimuli'),
    ]
    func_exps = []
    for cls_name, func_name in TARGETS:
        cls_idx = None
        for i, e in enumerate(exports):
            if e['name'] == cls_name and e['class_idx'] == 0:
                cls_idx = i
                break
        if cls_idx is None:
            return {'patched': False,
                    'message': '%s class not found' % cls_name}
        func_idx = None
        for i, e in enumerate(exports):
            if e['name'] == func_name and e['outer_idx'] == cls_idx + 1:
                func_idx = i
                break
        if func_idx is None:
            return {'patched': False,
                    'message': '%s.%s not found' % (cls_name, func_name)}
        func_exps.append((func_idx, exports[func_idx], cls_name))

    # ── Check for double-patch ─────────────────────────────────────────
    first_e = func_exps[0][1]
    first_serial = data[first_e['offset']:first_e['offset'] + first_e['size']]
    if first_serial.find(patch_marker) >= 0:
        return {'patched': False,
                'message': 'Hypnotize reflection already patched'}

    # ── Build injection bytecodes per function ─────────────────────────
    FOOTER_SIZE = 7
    SS_DELTA = 29  # memory-size of the injected expression

    new_serials = []
    for func_idx, func_e, cls_name in func_exps:
        serial = bytes(data[func_e['offset']:
                            func_e['offset'] + func_e['size']])
        bc_start, ss_off, old_ss = _parse_func_header(serial)
        bc = bytearray(serial[bc_start:-FOOTER_SIZE])
        footer = serial[-FOOTER_SIZE:]

        # Find AIDamagee local variable (child of this function)
        ai_ci = None
        for i, e2 in enumerate(exports):
            if e2['name'] == 'AIDamagee' and e2['outer_idx'] == func_idx + 1:
                ai_ci = write_compact_index(i + 1)
                break
        if ai_ci is None:
            return {'patched': False,
                    'message': 'AIDamagee not found in %s.ModifyDamageStimuli'
                               % cls_name}

        # Build: AIDamagee.SetDamageReflection(true, 1.0)
        inject = bytes([0x19])                                   # Context
        inject += bytes([0x00]) + ai_ci                          # LocalVar
        inject += struct.pack('<H', 16)                          # wSkip
        inject += bytes([0x00])                                  # bSize
        inject += bytes([0x1b]) + ci_set_reflect + struct.pack('<I', 0)
        inject += bytes([0x27])                                  # True
        inject += bytes([0x1e]) + struct.pack('<f', 1.0)         # 1.0
        inject += bytes([0x16])                                  # EndParms

        # Fix JumpIfNot targets that point at the Return (old_ss - 2)
        old_target = old_ss - 2
        new_target = old_target + SS_DELTA
        old_jmp = bytes([0x07]) + struct.pack('<H', old_target)
        new_jmp = bytes([0x07]) + struct.pack('<H', new_target)
        bc_fixed = bytes(bc).replace(old_jmp, new_jmp)
        bc_fixed = bytearray(bc_fixed)

        # Insert injection before Return Nothing (04 0b at end of bc)
        new_bc = bc_fixed[:-2] + inject + bc_fixed[-2:]
        new_ss = old_ss + SS_DELTA

        # Rebuild serial
        new_serial = bytearray(serial[:ss_off])
        new_serial += struct.pack('<I', new_ss)
        new_serial += new_bc
        new_serial += footer
        new_serials.append((func_idx, new_serial))

    # ── Backup ─────────────────────────────────────────────────────────
    if backup_dir:
        bak = Path(backup_dir) / 'ShockGame.U'
        if not bak.exists():
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(sg_path), str(bak))

    # ── Rebuild file (same multi-export pattern as patch_dual_drill) ───
    name_offset   = struct.unpack_from('<I', data, 16)[0]
    export_count  = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    first_table_off = min(name_offset, import_offset, export_offset)
    output = bytearray(data[:first_table_off])

    # Append new serials
    patches = []
    for func_idx, ns in new_serials:
        offset = len(output)
        output += bytes(ns)
        patches.append((func_idx, len(ns), offset))

    # Copy tables
    new_name_offset = len(output)
    output += data[name_offset:import_offset]
    new_import_offset = len(output)
    output += data[import_offset:export_offset]
    new_export_offset = len(output)
    exp_tbl = bytes(data[export_offset:])

    # Walk export table and patch modified entries
    tbl_out = bytearray()
    pos = 0
    for ei in range(export_count):
        start = pos
        _ci, pos = read_compact_index(exp_tbl, pos)
        _ci, pos = read_compact_index(exp_tbl, pos)
        pos += 4 + 4
        _ci, pos = read_compact_index(exp_tbl, pos)
        pos += 4 + 8
        sz, pos = read_compact_index(exp_tbl, pos)
        if sz > 0:
            _ci, pos = read_compact_index(exp_tbl, pos)
        pos += 4

        match = None
        for pidx, psize, poffset in patches:
            if ei == pidx:
                match = (psize, poffset)
                break

        if match:
            entry_data = _parse_export_entry_full(exp_tbl[start:pos])
            entry_data['size'] = match[0]
            entry_data['offset'] = match[1]
            tbl_out += write_export_entry(entry_data, data)
        else:
            tbl_out += exp_tbl[start:pos]

    output += bytes(tbl_out)

    # Patch header
    struct.pack_into('<I', output, 16, new_name_offset)
    struct.pack_into('<I', output, 24, new_export_offset)
    struct.pack_into('<I', output, 32, new_import_offset)

    sg_path.write_bytes(bytes(output))

    delta = sum(len(ns) for _, ns in new_serials) - sum(
        e['size'] for _, e, _ in func_exps)
    patched_cls = [c for _, _, c in func_exps]
    return {
        'patched': True,
        'message': 'Injected SetDamageReflection into %s (+%d bytes)' % (
            ', '.join(patched_cls), delta),
    }


def patch_tk_fire(shockgame_path, backup_dir=None):
    """Inject SetBurning + SetBurningTime into TK OnStartedHoldingActor.

    When the player picks up a living pawn via Telekinesis, the pawn is set
    on fire.  Uses DynamicCast(ShockPawn, Target) as the Context expression
    so non-pawn objects are silently skipped (Context handles NULL by skipping).

    Parameters
    ----------
    shockgame_path : str
        Full path to ShockGame.U (will be modified in-place).
    backup_dir : str, optional
        Directory to store a pristine backup.

    Returns
    -------
    dict  with keys 'patched' (bool) and 'message' (str).
    """
    sg_path = Path(shockgame_path)
    if not sg_path.exists():
        return {'patched': False, 'message': 'ShockGame.U not found'}

    data = bytearray(sg_path.read_bytes())
    pkg = parse_package(str(sg_path))
    names = pkg['names']
    exports = pkg['exports']

    # ── Locate name indices ────────────────────────────────────────────
    set_burning_ni = set_burning_time_ni = None
    for i, n in enumerate(names):
        if n == 'SetBurning':
            set_burning_ni = i
        elif n == 'SetBurningTime':
            set_burning_time_ni = i
    if set_burning_ni is None or set_burning_time_ni is None:
        return {'patched': False,
                'message': 'SetBurning/SetBurningTime names not found'}

    # ── Locate exports ─────────────────────────────────────────────────
    # TelekinesisAbility class
    tk_cls_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'TelekinesisAbility' and e['class_idx'] == 0:
            tk_cls_idx = i
            break
    if tk_cls_idx is None:
        return {'patched': False, 'message': 'TelekinesisAbility class not found'}

    # OnStartedHoldingActor function
    func_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'OnStartedHoldingActor' and e.get('outer_idx', 0) == tk_cls_idx + 1:
            func_idx = i
            break
    if func_idx is None:
        return {'patched': False,
                'message': 'OnStartedHoldingActor not found in TelekinesisAbility'}

    # ShockPawn class (for DynamicCast)
    shockpawn_cls_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'ShockPawn' and e['class_idx'] == 0:
            shockpawn_cls_idx = i
            break
    if shockpawn_cls_idx is None:
        return {'patched': False, 'message': 'ShockPawn class not found'}

    # Target and Player instance variables (children of TelekinesisAbility)
    target_exp_idx = player_exp_idx = None
    for i, e in enumerate(exports):
        if e.get('outer_idx', 0) == tk_cls_idx + 1:
            if e['name'] == 'Target':
                target_exp_idx = i
            elif e['name'] == 'Player':
                player_exp_idx = i
    if target_exp_idx is None or player_exp_idx is None:
        return {'patched': False,
                'message': 'Target/Player properties not found in TelekinesisAbility'}

    # ── Read function serial ───────────────────────────────────────────
    func_e = exports[func_idx]
    serial = bytes(data[func_e['offset']:func_e['offset'] + func_e['size']])
    bc_start, ss_off, old_ss = _parse_func_header(serial)

    FOOTER_SIZE = 7
    bc = bytearray(serial[bc_start:-FOOTER_SIZE])
    footer = serial[-FOOTER_SIZE:]

    # ── Check for double-patch ─────────────────────────────────────────
    ci_set_burning = write_compact_index(set_burning_ni)
    patch_marker = bytes([0x1b]) + ci_set_burning + struct.pack('<I', 0)
    if bc.find(patch_marker) >= 0:
        return {'patched': False,
                'message': 'TK fire already patched (SetBurning found)'}

    # ── Build injection bytecodes ──────────────────────────────────────
    ci_shockpawn = write_compact_index(shockpawn_cls_idx + 1)
    ci_target    = write_compact_index(target_exp_idx + 1)
    ci_player    = write_compact_index(player_exp_idx + 1)
    ci_sburn     = write_compact_index(set_burning_ni)
    ci_sbtime    = write_compact_index(set_burning_time_ni)

    # wSkip = memory size of member expression:
    #   VirtFunc(1)+FName(8) + FloatConst(1)+Float(4) + InstVar(1)+ptr(8) + End(1) = 24
    WSKIP = 24

    def _build_fire_call(func_name_ci, effectiveness):
        """Build Context(DynamicCast(ShockPawn, Target), func(eff, Player))"""
        call = bytes([0x19])                                     # Context
        call += bytes([0x2E]) + ci_shockpawn                     # DynamicCast(ShockPawn,
        call += bytes([0x01]) + ci_target                        #   InstanceVar(Target))
        call += struct.pack('<H', WSKIP)                         # wSkip
        call += bytes([0x00])                                    # bSize (void)
        call += bytes([0x1b]) + func_name_ci + struct.pack('<I', 0)  # VirtFunc
        call += bytes([0x1e]) + struct.pack('<f', effectiveness) # FloatConst
        call += bytes([0x01]) + ci_player                        # InstanceVar(Player)
        call += bytes([0x16])                                    # EndFunctionParms
        return call

    burn_call  = _build_fire_call(ci_sburn, 10.0)
    btime_call = _build_fire_call(ci_sbtime, 5.0)

    # Memory size per call:
    #   Context(1) + DynCast(1)+ptr(8) + InstVar(1)+ptr(8) + wSkip(2)+bSize(1) + member(24) = 46
    SS_DELTA = 46 * 2  # two calls

    # Insert before Return Nothing (04 0b) at end of bytecodes
    new_bc = bc[:-2] + burn_call + btime_call + bc[-2:]
    new_ss = old_ss + SS_DELTA

    # ── Rebuild serial ─────────────────────────────────────────────────
    new_serial = bytearray(serial[:ss_off])
    new_serial += struct.pack('<I', new_ss)
    new_serial += new_bc
    new_serial += footer

    # ── Backup ─────────────────────────────────────────────────────────
    if backup_dir:
        bak = Path(backup_dir) / 'ShockGame.U'
        if not bak.exists():
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(sg_path), str(bak))

    # ── Rebuild file ───────────────────────────────────────────────────
    name_offset   = struct.unpack_from('<I', data, 16)[0]
    export_count  = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    first_table_off = min(name_offset, import_offset, export_offset)
    output = bytearray(data[:first_table_off])

    new_serial_offset = len(output)
    output += bytes(new_serial)

    new_name_offset = len(output)
    output += data[name_offset:import_offset]
    new_import_offset = len(output)
    output += data[import_offset:export_offset]
    new_export_offset = len(output)
    exp_tbl = bytes(data[export_offset:])

    entry_start, entry_end = _find_export_entry_in_table(
        exp_tbl, func_idx, export_count)
    if entry_start is None:
        return {'patched': False,
                'message': 'Could not locate OnStartedHoldingActor in export table'}

    original_entry = _parse_export_entry_full(exp_tbl[entry_start:entry_end])
    original_entry['size'] = len(new_serial)
    original_entry['offset'] = new_serial_offset
    new_entry_bytes = write_export_entry(original_entry, data)

    output += exp_tbl[:entry_start]
    output += new_entry_bytes
    output += exp_tbl[entry_end:]

    struct.pack_into('<I', output, 16, new_name_offset)
    struct.pack_into('<I', output, 24, new_export_offset)
    struct.pack_into('<I', output, 32, new_import_offset)

    sg_path.write_bytes(bytes(output))

    delta = len(new_serial) - func_e['size']
    return {
        'patched': True,
        'message': 'Injected SetBurning+SetBurningTime into '
                   'OnStartedHoldingActor (+%d bytes)' % delta,
    }


def patch_tk_freeze(shockgame_path, backup_dir=None):
    """Inject SetFrozen into TK OnStartedHoldingActor.

    When the player picks up a living pawn via Telekinesis, the pawn is
    frozen.  Uses DynamicCast(ShockPawn, Target) as the Context expression
    so non-pawn objects are silently skipped (Context handles NULL by skipping).

    Can coexist with patch_tk_fire — each checks its own marker.

    Parameters
    ----------
    shockgame_path : str
        Full path to ShockGame.U (will be modified in-place).
    backup_dir : str, optional
        Directory to store a pristine backup.

    Returns
    -------
    dict  with keys 'patched' (bool) and 'message' (str).
    """
    sg_path = Path(shockgame_path)
    if not sg_path.exists():
        return {'patched': False, 'message': 'ShockGame.U not found'}

    data = bytearray(sg_path.read_bytes())
    pkg = parse_package(str(sg_path))
    names = pkg['names']
    exports = pkg['exports']

    # ── Locate name index ──────────────────────────────────────────────
    set_frozen_ni = None
    for i, n in enumerate(names):
        if n == 'SetFrozen':
            set_frozen_ni = i
            break
    if set_frozen_ni is None:
        return {'patched': False, 'message': 'SetFrozen name not found'}

    # ── Locate exports ─────────────────────────────────────────────────
    tk_cls_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'TelekinesisAbility' and e['class_idx'] == 0:
            tk_cls_idx = i
            break
    if tk_cls_idx is None:
        return {'patched': False, 'message': 'TelekinesisAbility class not found'}

    func_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'OnStartedHoldingActor' and e.get('outer_idx', 0) == tk_cls_idx + 1:
            func_idx = i
            break
    if func_idx is None:
        return {'patched': False,
                'message': 'OnStartedHoldingActor not found in TelekinesisAbility'}

    shockpawn_cls_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'ShockPawn' and e['class_idx'] == 0:
            shockpawn_cls_idx = i
            break
    if shockpawn_cls_idx is None:
        return {'patched': False, 'message': 'ShockPawn class not found'}

    target_exp_idx = player_exp_idx = None
    for i, e in enumerate(exports):
        if e.get('outer_idx', 0) == tk_cls_idx + 1:
            if e['name'] == 'Target':
                target_exp_idx = i
            elif e['name'] == 'Player':
                player_exp_idx = i
    if target_exp_idx is None or player_exp_idx is None:
        return {'patched': False,
                'message': 'Target/Player properties not found in TelekinesisAbility'}

    # ── Read function serial ───────────────────────────────────────────
    func_e = exports[func_idx]
    serial = bytes(data[func_e['offset']:func_e['offset'] + func_e['size']])
    bc_start, ss_off, old_ss = _parse_func_header(serial)

    FOOTER_SIZE = 7
    bc = bytearray(serial[bc_start:-FOOTER_SIZE])
    footer = serial[-FOOTER_SIZE:]

    # ── Check for double-patch ─────────────────────────────────────────
    ci_set_frozen = write_compact_index(set_frozen_ni)
    patch_marker = bytes([0x1b]) + ci_set_frozen + struct.pack('<I', 0)
    if bc.find(patch_marker) >= 0:
        return {'patched': False,
                'message': 'TK freeze already patched (SetFrozen found)'}

    # ── Build injection bytecodes ──────────────────────────────────────
    ci_shockpawn = write_compact_index(shockpawn_cls_idx + 1)
    ci_target    = write_compact_index(target_exp_idx + 1)
    ci_player    = write_compact_index(player_exp_idx + 1)

    # wSkip = memory size of member expression:
    #   VirtFunc(1)+FName(8) + FloatConst(1)+Float(4) + InstVar(1)+ptr(8) + End(1) = 24
    WSKIP = 24

    # Build Context(DynamicCast(ShockPawn, Target), SetFrozen(eff, Player))
    call = bytes([0x19])                                         # Context
    call += bytes([0x2E]) + ci_shockpawn                         # DynamicCast(ShockPawn,
    call += bytes([0x01]) + ci_target                            #   InstanceVar(Target))
    call += struct.pack('<H', WSKIP)                             # wSkip
    call += bytes([0x00])                                        # bSize (void)
    call += bytes([0x1b]) + ci_set_frozen + struct.pack('<I', 0) # VirtFunc(SetFrozen)
    call += bytes([0x1e]) + struct.pack('<f', 10.0)              # FloatConst(10.0)
    call += bytes([0x01]) + ci_player                            # InstanceVar(Player)
    call += bytes([0x16])                                        # EndFunctionParms

    # Memory size:
    #   Context(1) + DynCast(1)+ptr(8) + InstVar(1)+ptr(8) + wSkip(2)+bSize(1) + member(24) = 46
    SS_DELTA = 46  # single call

    # Insert before Return Nothing (04 0b) at end of bytecodes
    new_bc = bc[:-2] + call + bc[-2:]
    new_ss = old_ss + SS_DELTA

    # ── Rebuild serial ─────────────────────────────────────────────────
    new_serial = bytearray(serial[:ss_off])
    new_serial += struct.pack('<I', new_ss)
    new_serial += new_bc
    new_serial += footer

    # ── Backup ─────────────────────────────────────────────────────────
    if backup_dir:
        bak = Path(backup_dir) / 'ShockGame.U'
        if not bak.exists():
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(sg_path), str(bak))

    # ── Rebuild file ───────────────────────────────────────────────────
    name_offset   = struct.unpack_from('<I', data, 16)[0]
    export_count  = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    first_table_off = min(name_offset, import_offset, export_offset)
    output = bytearray(data[:first_table_off])

    new_serial_offset = len(output)
    output += bytes(new_serial)

    new_name_offset = len(output)
    output += data[name_offset:import_offset]
    new_import_offset = len(output)
    output += data[import_offset:export_offset]
    new_export_offset = len(output)
    exp_tbl = bytes(data[export_offset:])

    entry_start, entry_end = _find_export_entry_in_table(
        exp_tbl, func_idx, export_count)
    if entry_start is None:
        return {'patched': False,
                'message': 'Could not locate OnStartedHoldingActor in export table'}

    original_entry = _parse_export_entry_full(exp_tbl[entry_start:entry_end])
    original_entry['size'] = len(new_serial)
    original_entry['offset'] = new_serial_offset
    new_entry_bytes = write_export_entry(original_entry, data)

    output += exp_tbl[:entry_start]
    output += new_entry_bytes
    output += exp_tbl[entry_end:]

    struct.pack_into('<I', output, 16, new_name_offset)
    struct.pack_into('<I', output, 24, new_export_offset)
    struct.pack_into('<I', output, 32, new_import_offset)

    sg_path.write_bytes(bytes(output))

    delta = len(new_serial) - func_e['size']
    return {
        'patched': True,
        'message': 'Injected SetFrozen into '
                   'OnStartedHoldingActor (+%d bytes)' % delta,
    }


def patch_decoy_fire(shockgame_path, backup_dir=None):
    """Inject SetBurning + SetBurningTime into DecoyHumanAbility.UseAbility.

    The decoy spawns on fire, causing BioShock 2's fire propagation system
    to ignite nearby enemies.  Injection is placed after the existing
    SetDamageReflection / SetOwnerHealing calls, before super.UseAbility.

    Parameters
    ----------
    shockgame_path : str
        Full path to ShockGame.U (will be modified in-place).
    backup_dir : str, optional
        Directory to store a pristine backup.

    Returns
    -------
    dict  with keys 'patched' (bool) and 'message' (str).
    """
    sg_path = Path(shockgame_path)
    if not sg_path.exists():
        return {'patched': False, 'message': 'ShockGame.U not found'}

    data = bytearray(sg_path.read_bytes())
    pkg = parse_package(str(sg_path))
    names = pkg['names']
    exports = pkg['exports']

    # ── Locate name indices ────────────────────────────────────────────
    set_burning_ni = set_burning_time_ni = None
    for i, n in enumerate(names):
        if n == 'SetBurning':
            set_burning_ni = i
        elif n == 'SetBurningTime':
            set_burning_time_ni = i
    if set_burning_ni is None or set_burning_time_ni is None:
        return {'patched': False,
                'message': 'SetBurning/SetBurningTime names not found'}

    # ── Locate exports ─────────────────────────────────────────────────
    decoy_cls_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'DecoyHumanAbility' and e['class_idx'] == 0:
            decoy_cls_idx = i
            break
    if decoy_cls_idx is None:
        return {'patched': False, 'message': 'DecoyHumanAbility class not found'}

    func_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'UseAbility' and e.get('outer_idx', 0) == decoy_cls_idx + 1:
            func_idx = i
            break
    if func_idx is None:
        return {'patched': False,
                'message': 'UseAbility not found in DecoyHumanAbility'}

    # NewDecoyHuman and Instigator local variables (children of UseAbility)
    ndh_exp_idx = instigator_exp_idx = None
    for i, e in enumerate(exports):
        if e.get('outer_idx', 0) == func_idx + 1:
            if e['name'] == 'NewDecoyHuman':
                ndh_exp_idx = i
            elif e['name'] == 'Instigator':
                instigator_exp_idx = i
    if ndh_exp_idx is None or instigator_exp_idx is None:
        return {'patched': False,
                'message': 'NewDecoyHuman/Instigator locals not found in UseAbility'}

    # ── Read function serial ───────────────────────────────────────────
    func_e = exports[func_idx]
    serial = bytes(data[func_e['offset']:func_e['offset'] + func_e['size']])
    bc_start, ss_off, old_ss = _parse_func_header(serial)

    FOOTER_SIZE = 7
    bc = bytearray(serial[bc_start:-FOOTER_SIZE])
    footer = serial[-FOOTER_SIZE:]

    # ── Check for double-patch ─────────────────────────────────────────
    ci_set_burning = write_compact_index(set_burning_ni)
    patch_marker = bytes([0x1b]) + ci_set_burning + struct.pack('<I', 0)
    if bc.find(patch_marker) >= 0:
        return {'patched': False,
                'message': 'Decoy fire already patched (SetBurning found)'}

    # ── Build injection bytecodes ──────────────────────────────────────
    ci_ndh        = write_compact_index(ndh_exp_idx + 1)
    ci_instigator = write_compact_index(instigator_exp_idx + 1)
    ci_sburn      = write_compact_index(set_burning_ni)
    ci_sbtime     = write_compact_index(set_burning_time_ni)

    # wSkip = memory size of member expression:
    #   VirtFunc(1)+FName(8) + FloatConst(1)+Float(4) + LocalVar(1)+ptr(8) + End(1) = 24
    WSKIP = 24

    def _build_decoy_call(func_name_ci, effectiveness):
        """Build Context(LocalVar(NewDecoyHuman), func(eff, Instigator))"""
        call = bytes([0x19])                                     # Context
        call += bytes([0x00]) + ci_ndh                           # LocalVar(NewDecoyHuman)
        call += struct.pack('<H', WSKIP)                         # wSkip
        call += bytes([0x00])                                    # bSize (void)
        call += bytes([0x1b]) + func_name_ci + struct.pack('<I', 0)  # VirtFunc
        call += bytes([0x1e]) + struct.pack('<f', effectiveness) # FloatConst
        call += bytes([0x00]) + ci_instigator                    # LocalVar(Instigator)
        call += bytes([0x16])                                    # EndFunctionParms
        return call

    burn_call  = _build_decoy_call(ci_sburn, 99999.0)
    btime_call = _build_decoy_call(ci_sbtime, 99999.0)

    # Memory size per call:
    #   Context(1) + LocalVar(1)+ptr(8) + wSkip(2)+bSize(1) + member(24) = 37
    SS_DELTA = 37 * 2  # two calls

    # Insert before Return Nothing (04 0b) at end of bytecodes
    new_bc = bc[:-2] + burn_call + btime_call + bc[-2:]
    new_ss = old_ss + SS_DELTA

    # ── Rebuild serial ─────────────────────────────────────────────────
    new_serial = bytearray(serial[:ss_off])
    new_serial += struct.pack('<I', new_ss)
    new_serial += new_bc
    new_serial += footer

    # ── Backup ─────────────────────────────────────────────────────────
    if backup_dir:
        bak = Path(backup_dir) / 'ShockGame.U'
        if not bak.exists():
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(sg_path), str(bak))

    # ── Rebuild file ───────────────────────────────────────────────────
    name_offset   = struct.unpack_from('<I', data, 16)[0]
    export_count  = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    first_table_off = min(name_offset, import_offset, export_offset)
    output = bytearray(data[:first_table_off])

    new_serial_offset = len(output)
    output += bytes(new_serial)

    new_name_offset = len(output)
    output += data[name_offset:import_offset]
    new_import_offset = len(output)
    output += data[import_offset:export_offset]
    new_export_offset = len(output)
    exp_tbl = bytes(data[export_offset:])

    entry_start, entry_end = _find_export_entry_in_table(
        exp_tbl, func_idx, export_count)
    if entry_start is None:
        return {'patched': False,
                'message': 'Could not locate UseAbility in export table'}

    original_entry = _parse_export_entry_full(exp_tbl[entry_start:entry_end])
    original_entry['size'] = len(new_serial)
    original_entry['offset'] = new_serial_offset
    new_entry_bytes = write_export_entry(original_entry, data)

    output += exp_tbl[:entry_start]
    output += new_entry_bytes
    output += exp_tbl[entry_end:]

    struct.pack_into('<I', output, 16, new_name_offset)
    struct.pack_into('<I', output, 24, new_export_offset)
    struct.pack_into('<I', output, 32, new_import_offset)

    sg_path.write_bytes(bytes(output))

    delta = len(new_serial) - func_e['size']
    return {
        'patched': True,
        'message': 'Injected SetBurning+SetBurningTime into '
                   'DecoyHumanAbility.UseAbility (+%d bytes)' % delta,
    }


def patch_decoy_cyclone(shockgame_path, backup_dir=None):
    """Inject Spawn(SpringBoardTrapMarkerBasic) into DecoyHumanAbility.UseAbility.

    Spawns a Cyclone Trap at the decoy's position when deployed.
    Uses native Spawn (opcode 0x61 0x16) through Context(Instigator).

    Must run AFTER patch_decoy_fire (reads already-patched bytecodes).

    Parameters
    ----------
    shockgame_path : str
        Full path to ShockGame.U (will be modified in-place).
    backup_dir : str, optional
        Directory to store a pristine backup.

    Returns
    -------
    dict  with keys 'patched' (bool) and 'message' (str).
    """
    sg_path = Path(shockgame_path)
    if not sg_path.exists():
        return {'patched': False, 'message': 'ShockGame.U not found'}

    data = bytearray(sg_path.read_bytes())
    pkg = parse_package(str(sg_path))
    names = pkg['names']
    exports = pkg['exports']

    # ── Locate exports ─────────────────────────────────────────────────
    dh_cls_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'DecoyHumanAbility' and e['class_idx'] == 0:
            dh_cls_idx = i
            break
    if dh_cls_idx is None:
        return {'patched': False, 'message': 'DecoyHumanAbility class not found'}

    func_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'UseAbility' and e.get('outer_idx', 0) == dh_cls_idx + 1:
            func_idx = i
            break
    if func_idx is None:
        return {'patched': False,
                'message': 'UseAbility not found in DecoyHumanAbility'}

    # SpringBoardTrapMarkerBasic class (the cyclone trap marker)
    trap_cls_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'SpringBoardTrapMarkerBasic' and e['class_idx'] == 0:
            trap_cls_idx = i
            break
    if trap_cls_idx is None:
        return {'patched': False,
                'message': 'SpringBoardTrapMarkerBasic class not found'}

    # Instigator local var (parameter of UseAbility)
    instigator_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'Instigator' and e.get('outer_idx', 0) == func_idx + 1:
            instigator_idx = i
            break
    if instigator_idx is None:
        return {'patched': False, 'message': 'Instigator not found in UseAbility'}

    # DecoyPosition local var
    decoy_pos_idx = None
    for i, e in enumerate(exports):
        if e['name'] == 'DecoyPosition' and e.get('outer_idx', 0) == func_idx + 1:
            decoy_pos_idx = i
            break
    if decoy_pos_idx is None:
        return {'patched': False, 'message': 'DecoyPosition not found in UseAbility'}

    # ── Read function serial ───────────────────────────────────────────
    func_e = exports[func_idx]
    serial = bytes(data[func_e['offset']:func_e['offset'] + func_e['size']])
    bc_start, ss_off, old_ss = _parse_func_header(serial)

    FOOTER_SIZE = 7
    bc = bytearray(serial[bc_start:-FOOTER_SIZE])
    footer = serial[-FOOTER_SIZE:]

    # ── Check for double-patch ─────────────────────────────────────────
    ci_trap = write_compact_index(trap_cls_idx + 1)
    # Marker: MetaCast(SpringBoardTrapMarkerBasic) = 0x20 + CI
    patch_marker = bytes([0x20]) + ci_trap
    if bc.find(patch_marker) >= 0:
        return {'patched': False,
                'message': 'Cyclone trap already patched (SpringBoardTrapMarkerBasic found)'}

    # ── Build injection bytecodes ──────────────────────────────────────
    ci_instigator = write_compact_index(instigator_idx + 1)
    ci_decoy_pos  = write_compact_index(decoy_pos_idx + 1)

    # Member expression: Spawn(class, None, <default>, DecoyPosition)
    member = bytes([0x61, 0x16])                          # Native Spawn (278)
    member += bytes([0x20]) + ci_trap                     # MetaCast(SBTMarkerBasic)
    member += bytes([0x2A])                               # NoObject (SpawnOwner=None)
    member += bytes([0x0B])                               # Nothing (SpawnTag=default)
    member += bytes([0x00]) + ci_decoy_pos                # LocalVar(DecoyPosition)
    member += bytes([0x16])                               # EndFunctionParms

    WSKIP = len(member)  # wSkip = archive bytes of member expression

    call = bytes([0x19])                                  # Context
    call += bytes([0x00]) + ci_instigator                 # LocalVar(Instigator)
    call += struct.pack('<H', WSKIP)                      # wSkip
    call += bytes([0x04])                                 # bSize = 4 (Actor return)
    call += member

    # Memory (ScriptSize) delta:
    #   Context(1) + LocalVar(1)+ptr(8) + wSkip(2) + bSize(1)
    #   + NativeSpawn(2) + MetaCast(1)+ptr(8) + NoObject(1) + Nothing(1)
    #   + LocalVar(1)+ptr(8) + EndFuncParms(1) = 36
    SS_DELTA = 36

    # Insert before Return Nothing (04 0b) at end of bytecodes
    new_bc = bc[:-2] + call + bc[-2:]
    new_ss = old_ss + SS_DELTA

    # ── Rebuild serial ─────────────────────────────────────────────────
    new_serial = bytearray(serial[:ss_off])
    new_serial += struct.pack('<I', new_ss)
    new_serial += new_bc
    new_serial += footer

    # ── Backup ─────────────────────────────────────────────────────────
    if backup_dir:
        bak = Path(backup_dir) / 'ShockGame.U'
        if not bak.exists():
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(sg_path), str(bak))

    # ── Rebuild file ───────────────────────────────────────────────────
    name_offset   = struct.unpack_from('<I', data, 16)[0]
    export_count  = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    first_table_off = min(name_offset, import_offset, export_offset)
    output = bytearray(data[:first_table_off])

    new_serial_offset = len(output)
    output += bytes(new_serial)

    new_name_offset = len(output)
    output += data[name_offset:import_offset]
    new_import_offset = len(output)
    output += data[import_offset:export_offset]
    new_export_offset = len(output)
    exp_tbl = bytes(data[export_offset:])

    entry_start, entry_end = _find_export_entry_in_table(
        exp_tbl, func_idx, export_count)
    if entry_start is None:
        return {'patched': False,
                'message': 'Could not locate UseAbility in export table'}

    original_entry = _parse_export_entry_full(exp_tbl[entry_start:entry_end])
    original_entry['size'] = len(new_serial)
    original_entry['offset'] = new_serial_offset
    new_entry_bytes = write_export_entry(original_entry, data)

    output += exp_tbl[:entry_start]
    output += new_entry_bytes
    output += exp_tbl[entry_end:]

    struct.pack_into('<I', output, 16, new_name_offset)
    struct.pack_into('<I', output, 24, new_export_offset)
    struct.pack_into('<I', output, 32, new_import_offset)

    sg_path.write_bytes(bytes(output))

    delta = len(new_serial) - func_e['size']
    return {
        'patched': True,
        'message': 'Injected Spawn(SpringBoardTrapMarkerBasic) into '
                   'DecoyHumanAbility.UseAbility (+%d bytes)' % delta,
    }


def patch_decoy_reflect(shockgame_path, backup_dir=None):
    """Enable damage reflection on Decoy 1 (DecoyBasicAbility) in ShockGame.U.

    Inserts ShouldReflectDamage=True into the default properties of
    DecoyBasicAbility so all decoy versions reflect damage like Decoy 2+.

    Parameters
    ----------
    shockgame_path : str
        Full path to ShockGame.U (will be modified in-place).
    backup_dir : str, optional
        Directory to store a pristine backup.

    Returns
    -------
    dict  with keys 'patched' (bool) and 'message' (str).
    """
    from core.bsm_parser import parse_properties

    sg_path = Path(shockgame_path)
    if not sg_path.exists():
        return {'patched': False, 'message': 'ShockGame.U not found'}

    data = bytearray(sg_path.read_bytes())
    pkg = parse_package(str(sg_path))
    names = pkg['names']
    exports = pkg['exports']

    # ── Locate name index for ShouldReflectDamage ──────────────────────
    reflect_ni = None
    for i, n in enumerate(names):
        if n == 'ShouldReflectDamage':
            reflect_ni = i
            break
    if reflect_ni is None:
        return {'patched': False, 'message': 'ShouldReflectDamage name not found'}

    reflect_ci = write_compact_index(reflect_ni)
    # BoolProperty TRUE: info=0xD3 (type 3, size_bits 5, array_flag 1), size=0
    reflect_prop = reflect_ci + struct.pack('<I', 0) + bytes([0xD3, 0x00])

    # ── Identify target export ─────────────────────────────────────────
    target_idx = None
    target_exp = None
    for i, e in enumerate(exports):
        if e['name'] == 'DecoyBasicAbility' and e['class_idx'] == 0:
            target_idx = i
            target_exp = e
            break
    if target_exp is None:
        return {'patched': False,
                'message': 'DecoyBasicAbility class export not found'}

    # ── Check for double-patch ─────────────────────────────────────────
    serial = data[target_exp['offset']:target_exp['offset'] + target_exp['size']]
    reflect_marker = reflect_ci + struct.pack('<I', 0)
    if serial.find(reflect_marker) >= 0:
        return {'patched': False,
                'message': 'ShouldReflectDamage already in DecoyBasicAbility (patched)'}

    # ── Build new serial ───────────────────────────────────────────────
    PROP_START = 142
    try:
        props = parse_properties(serial, PROP_START, names, target_exp['size'])
    except Exception:
        return {'patched': False,
                'message': 'Failed to parse properties of DecoyBasicAbility'}
    if not props:
        return {'patched': False,
                'message': 'No properties found in DecoyBasicAbility'}

    last = props[-1]
    none_off = last[7] + last[3]
    if serial[none_off:none_off + 5] != b'\x00\x00\x00\x00\x00':
        return {'patched': False,
                'message': 'None terminator not found at expected offset'}

    new_serial = bytearray(serial[:none_off])
    new_serial += reflect_prop
    new_serial += serial[none_off:]

    # ── Backup ─────────────────────────────────────────────────────────
    if backup_dir:
        bak = Path(backup_dir) / 'ShockGame.U'
        if not bak.exists():
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(sg_path), str(bak))

    # ── Append new serial and shift tables ─────────────────────────────
    name_offset   = struct.unpack_from('<I', data, 16)[0]
    export_count  = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    first_table_off = min(name_offset, import_offset, export_offset)
    output = bytearray(data[:first_table_off])

    new_serial_offset = len(output)
    output += bytes(new_serial)

    new_name_offset = len(output)
    output += data[name_offset:import_offset]

    new_import_offset = len(output)
    output += data[import_offset:export_offset]

    new_export_offset = len(output)
    exp_tbl = bytes(data[export_offset:])

    entry_start, entry_end = _find_export_entry_in_table(
        exp_tbl, target_idx, export_count)
    if entry_start is None:
        return {'patched': False,
                'message': 'Could not locate DecoyBasicAbility entry in export table'}

    original_entry = _parse_export_entry_full(exp_tbl[entry_start:entry_end])
    original_entry['size'] = len(new_serial)
    original_entry['offset'] = new_serial_offset
    new_entry_bytes = write_export_entry(original_entry, data)

    output += exp_tbl[:entry_start]
    output += new_entry_bytes
    output += exp_tbl[entry_end:]

    struct.pack_into('<I', output, 16, new_name_offset)
    struct.pack_into('<I', output, 24, new_export_offset)
    struct.pack_into('<I', output, 32, new_import_offset)

    sg_path.write_bytes(bytes(output))

    delta = len(new_serial) - target_exp['size']
    return {
        'patched': True,
        'message': 'Inserted ShouldReflectDamage=True into DecoyBasicAbility (+%d bytes)' % delta,
    }


def patch_ricochet(shockgame_path, backup_dir=None):
    """Patch TraceAmmo.GetNumberOfRicochets to return 1 (always ricochet).

    This gives ricochet to ALL trace-based weapons (Rivet Gun, Shotgun,
    etc.) that don't already override GetNumberOfRicochets.  Machine Gun
    bullets are unaffected because they have their own conditional override
    that still checks the Power to the People upgrade.

    Parameters
    ----------
    shockgame_path : str
        Full path to ShockGame.U (will be modified in-place).
    backup_dir : str, optional
        Directory to store a pristine backup.

    Returns
    -------
    dict  with keys 'patched' (bool) and 'message' (str).
    """
    sg_path = Path(shockgame_path)
    if not sg_path.exists():
        return {'patched': False, 'message': 'ShockGame.U not found'}

    data = bytearray(sg_path.read_bytes())
    pkg = parse_package(str(sg_path))
    exports = pkg['exports']

    # ── Locate TraceAmmo.GetNumberOfRicochets (exp[3447]) ──────────
    EXP_IDX = 3447
    e = exports[EXP_IDX]
    if e['name'] != 'GetNumberOfRicochets':
        return {'patched': False,
                'message': 'exp[3447] is not GetNumberOfRicochets'}
    outer = exports[e['outer_idx'] - 1]
    if outer['name'] != 'TraceAmmo':
        return {'patched': False,
                'message': 'exp[3447] outer is not TraceAmmo'}

    old_serial = bytes(data[e['offset']:e['offset'] + e['size']])

    # Parse header to find bytecode boundaries
    bc_start, ss_off, ss = _parse_func_header(old_serial)
    FOOTER_SIZE = 7
    old_bc = old_serial[bc_start:-FOOTER_SIZE]
    footer = old_serial[-FOOTER_SIZE:]

    # Verify original bytecode: Return InstanceVariable(X) Return Nothing
    # 04 01 XX XX 04 0b
    if len(old_bc) < 4 or old_bc[0] != 0x04 or old_bc[1] != 0x01:
        # Check for double-patch: IntOne = 0x27
        if len(old_bc) >= 2 and old_bc[1] == 0x27:
            return {'patched': False,
                    'message': 'Ricochet already patched'}
        return {'patched': False,
                'message': 'Unexpected bytecode in GetNumberOfRicochets'}

    # ── Build new bytecode ─────────────────────────────────────────
    # Replace: Return InstanceVariable(ref) Return Nothing
    #    With: Return IntOne              Return Nothing
    # IntOne opcode = 0x27 (produces integer value 1, 1 byte in archive + memory)
    new_bc = bytes([0x04, 0x27, 0x04, 0x0b])

    # ScriptSize = in-memory byte sizes:
    #   Return(1) + IntOne(1) + Return(1) + Nothing(1) = 4
    new_ss = 4

    # ── Build new serial ───────────────────────────────────────────
    new_serial = bytearray(old_serial[:ss_off])
    new_serial += struct.pack('<I', new_ss)
    new_serial += new_bc
    new_serial += footer

    # ── Backup ─────────────────────────────────────────────────────
    if backup_dir:
        bak = Path(backup_dir) / 'ShockGame.U'
        if not bak.exists():
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(sg_path), str(bak))

    # ── Rebuild file (append + shift tables) ───────────────────────
    name_offset   = struct.unpack_from('<I', data, 16)[0]
    export_count  = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    first_table_off = min(name_offset, import_offset, export_offset)

    output = bytearray(data[:first_table_off])
    new_serial_offset = len(output)
    output += bytes(new_serial)

    new_name_offset = len(output)
    output += data[name_offset:import_offset]
    new_import_offset = len(output)
    output += data[import_offset:export_offset]
    new_export_offset = len(output)

    exp_tbl = bytes(data[export_offset:])

    entry_start, entry_end = _find_export_entry_in_table(
        exp_tbl, EXP_IDX, export_count)
    if entry_start is None:
        return {'patched': False,
                'message': 'Could not locate GetNumberOfRicochets in export table'}

    original_entry = _parse_export_entry_full(exp_tbl[entry_start:entry_end])
    original_entry['size'] = len(new_serial)
    original_entry['offset'] = new_serial_offset
    new_entry_bytes = write_export_entry(original_entry, data)

    output += exp_tbl[:entry_start]
    output += new_entry_bytes
    output += exp_tbl[entry_end:]

    struct.pack_into('<I', output, 16, new_name_offset)
    struct.pack_into('<I', output, 24, new_export_offset)
    struct.pack_into('<I', output, 32, new_import_offset)

    sg_path.write_bytes(bytes(output))

    return {
        'patched': True,
        'message': ('Ricochet: TraceAmmo.GetNumberOfRicochets now returns 1 '
                    '(-%d bytes serial, affects Rivet/Shotgun/Laser)'
                    % (len(old_serial) - len(new_serial))),
    }


def restore_shockgame(shockgame_path, backup_dir):
    """Restore ShockGame.U from pristine backup if it exists."""
    bak = Path(backup_dir) / 'ShockGame.U'
    if bak.exists():
        shutil.copy2(str(bak), shockgame_path)
        return True
    return False
