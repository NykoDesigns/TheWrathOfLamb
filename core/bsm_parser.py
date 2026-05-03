"""
The War In Rapture: BioShock 2 — Unreal Package Parser
========================================================
Reads BioShock 2 Remastered .bsm map files (Unreal Engine 2.5 "Vengeance
Engine" packages).  Handles the package header, name / import / export
tables, compact-index encoding, and UE1-style property serialisation.

BioShock 2 uses package version **143** with licensee **59** (BS1 was
142 / 56).  The binary layout is otherwise identical to BioShock 1:
  - Magic:   0x9E2A83C1
  - Names:   length-byte + UTF-16LE chars + 8-byte flags
  - Imports: compact_index fields + INT32 fields (same order as BS1)
  - Exports: compact_index fields + INT32 fields + UINT64 flags
  - Serial header skip for spawner actors is **65 bytes** (BS1 = 57).
"""
import struct
import sys

# =============================================================================
# COMPACT INDEX  (variable-length signed integer)
# =============================================================================
# Encoding:  b0[7]=sign, b0[6]=more, b0[5:0]=value(6 bits)
#            b1[7]=more, b1[6:0]=value(7 bits) shifted left 6 …
#            up to 5 bytes for 6+7+7+7+7 = 34 value bits.

def read_compact_index(data, pos):
    """Read a UE compact index from *data* at *pos*.  Returns (value, new_pos)."""
    b0 = data[pos]; pos += 1
    sign = b0 & 0x80
    more = b0 & 0x40
    val  = b0 & 0x3F
    if more:
        b1 = data[pos]; pos += 1
        val |= (b1 & 0x7F) << 6
        if b1 & 0x80:
            b2 = data[pos]; pos += 1
            val |= (b2 & 0x7F) << 13
            if b2 & 0x80:
                b3 = data[pos]; pos += 1
                val |= (b3 & 0x7F) << 20
                if b3 & 0x80:
                    b4 = data[pos]; pos += 1
                    val |= (b4 & 0x7F) << 27
    if sign:
        val = -val
    return val, pos


def write_compact_index(value):
    """Encode *value* as a compact index byte string."""
    sign = 0
    if value < 0:
        sign = 0x80
        value = -value
    if value < 0x40:
        return bytes([sign | value])
    result = bytearray()
    result.append(sign | 0x40 | (value & 0x3F))
    value >>= 6
    if value < 0x80:
        result.append(value)
        return bytes(result)
    result.append(0x80 | (value & 0x7F)); value >>= 7
    if value < 0x80:
        result.append(value)
        return bytes(result)
    result.append(0x80 | (value & 0x7F)); value >>= 7
    if value < 0x80:
        result.append(value)
        return bytes(result)
    result.append(0x80 | (value & 0x7F)); value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


# =============================================================================
# NAME REFERENCE  (compact_index + INT32 instance number)
# =============================================================================

def read_name_ref(data, pos):
    """Read a name reference: compact_index for name table index + INT32 instance number."""
    idx, pos = read_compact_index(data, pos)
    num = struct.unpack_from('<I', data, pos)[0]; pos += 4
    return idx, num, pos


# =============================================================================
# UE PROPERTY TYPES
# =============================================================================
PROP_TYPES = {
    0: 'None', 1: 'Byte', 2: 'Int', 3: 'Bool', 4: 'Float',
    5: 'Object', 6: 'Name', 7: 'String', 8: 'Class', 9: 'Array',
    10: 'Struct', 11: 'Vector', 12: 'Rotator', 13: 'Str',
    14: 'Map', 15: 'FixedArray',
}


def decode_packed_size(data, pos, size_bits):
    """Decode the property size from the 3-bit size class in the info byte."""
    if size_bits == 0: return 1, pos
    if size_bits == 1: return 2, pos
    if size_bits == 2: return 4, pos
    if size_bits == 3: return 12, pos
    if size_bits == 4: return 16, pos
    if size_bits == 5: return data[pos], pos + 1
    if size_bits == 6: return struct.unpack_from('<H', data, pos)[0], pos + 2
    if size_bits == 7: return struct.unpack_from('<I', data, pos)[0], pos + 4
    return 0, pos


# =============================================================================
# PROPERTY PARSER
# =============================================================================

def parse_properties(data, start, names, serial_end):
    """Parse UE1-style properties from raw serial data.

    Returns a list of tuples:
        (name, prop_type_int, type_name, prop_size, array_index,
         value_data, tag_pos, value_pos, bool_value, struct_name)
    """
    props = []
    pos = start
    while pos < serial_end:
        tag_pos = pos
        name_idx, name_num, pos = read_name_ref(data, pos)
        if name_idx == 0:
            break
        if name_idx < 0 or name_idx >= len(names):
            break
        name = names[name_idx]
        if name_num > 0:
            name = '%s_%d' % (name, name_num)

        # Read info byte
        if pos >= len(data):
            break
        info = data[pos]; pos += 1

        prop_type  = info & 0x0F
        size_bits  = (info >> 4) & 0x07
        array_flag = (info >> 7) & 1

        type_name = PROP_TYPES.get(prop_type, 'Unknown(%d)' % prop_type)

        # For StructProperty, read struct name
        struct_name = None
        if prop_type == 10:  # Struct
            sn_idx, sn_num, pos = read_name_ref(data, pos)
            struct_name = names[sn_idx] if 0 <= sn_idx < len(names) else '?'

        # Decode size
        prop_size, pos = decode_packed_size(data, pos, size_bits)

        # Handle bool and array index
        array_index = 0
        bool_value = None
        if prop_type == 3:  # Bool
            bool_value = bool(array_flag)
        elif array_flag:
            # Read variable-length array index
            b = data[pos]; pos += 1
            if (b & 0x80) == 0:
                array_index = b
            elif (b & 0xC0) == 0x80:
                c = data[pos]; pos += 1
                array_index = ((b & 0x7F) << 8) + c
            else:
                c = data[pos]; pos += 1
                d = data[pos]; pos += 1
                e = data[pos]; pos += 1
                array_index = ((b & 0x3F) << 24) + (c << 16) + (d << 8) + e

        value_pos = pos
        value_data = data[pos:pos + prop_size] if prop_size > 0 else b''

        props.append((name, prop_type, type_name, prop_size, array_index,
                       value_data, tag_pos, value_pos, bool_value, struct_name))
        pos += prop_size

    return props


# =============================================================================
# PACKAGE PARSER
# =============================================================================

def parse_package(filepath):
    """Parse a BioShock 2 Unreal package (.bsm) file.

    Returns a dict with keys:
        data, names, imports, exports, version, licensee
    Each export is a dict with:
        name, name_num, class_idx, super_idx, outer_idx,
        size, offset, name_idx
    """
    with open(filepath, 'rb') as f:
        data = f.read()

    magic = struct.unpack_from('<I', data, 0)[0]
    assert magic == 0x9E2A83C1, "Not an Unreal package"

    ver = struct.unpack_from('<H', data, 4)[0]
    lic = struct.unpack_from('<H', data, 6)[0]

    name_count   = struct.unpack_from('<I', data, 12)[0]
    name_offset  = struct.unpack_from('<I', data, 16)[0]
    export_count = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_count = struct.unpack_from('<I', data, 28)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    # Parse name table
    pos = name_offset
    names = []
    for i in range(name_count):
        if pos >= len(data):
            break
        l = data[pos]; pos += 1
        if l == 0:
            pos += 8
            names.append('')
            continue
        name = data[pos:pos + l * 2 - 2].decode('utf-16-le', errors='replace')
        pos += l * 2 + 8
        names.append(name)

    # Parse imports
    imports = []
    pos = import_offset
    for i in range(import_count):
        cp, pos = read_compact_index(data, pos); pos += 4
        cn, pos = read_compact_index(data, pos); pos += 4
        oi = struct.unpack_from('<i', data, pos)[0]; pos += 4
        on, pos = read_compact_index(data, pos); pos += 4
        on_nm = names[on] if 0 <= on < len(names) else '?'
        imports.append(on_nm)

    # Parse exports
    exports = []
    pos = export_offset
    for i in range(export_count):
        ci, pos = read_compact_index(data, pos)
        si, pos = read_compact_index(data, pos)
        oi = struct.unpack_from('<i', data, pos)[0]; pos += 4
        pos += 4  # unknown BioShock field
        ni, pos = read_compact_index(data, pos)
        nn = struct.unpack_from('<I', data, pos)[0]; pos += 4
        pos += 8  # flags UINT64
        sz, pos = read_compact_index(data, pos)
        so = 0
        if sz > 0:
            so, pos = read_compact_index(data, pos)
        pos += 4  # unknown BioShock field
        nm = names[ni] if 0 <= ni < len(names) else '?'
        exports.append({
            'name': nm, 'name_num': nn, 'class_idx': ci, 'super_idx': si,
            'outer_idx': oi, 'size': sz, 'offset': so, 'name_idx': ni
        })

    return {
        'data': data, 'names': names, 'imports': imports, 'exports': exports,
        'version': ver, 'licensee': lic
    }


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: py bsm_parser.py <file.bsm>")
        sys.exit(1)

    pkg = parse_package(sys.argv[1])
    print("Version: %d, Licensee: %d" % (pkg['version'], pkg['licensee']))
    print("Names: %d, Exports: %d, Imports: %d" % (
        len(pkg['names']), len(pkg['exports']), len(pkg['imports'])))
