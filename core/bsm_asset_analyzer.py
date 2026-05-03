"""
Deep BSM package analyzer for asset dependency tracing.

Used to identify all exports needed to transplant the Ion Laser weapon
from Minerva's Den DLC maps into the main campaign.
"""

import struct
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from core.bsm_parser import read_compact_index


def parse_package_deep(filepath):
    """Parse a BSM with full import/export detail for dependency tracing."""
    with open(filepath, 'rb') as f:
        data = f.read()

    magic = struct.unpack_from('<I', data, 0)[0]
    assert magic == 0x9E2A83C1, "Not an Unreal package"

    ver = struct.unpack_from('<H', data, 4)[0]
    lic = struct.unpack_from('<H', data, 6)[0]
    header_size = struct.unpack_from('<I', data, 8)[0]

    name_count   = struct.unpack_from('<I', data, 12)[0]
    name_offset  = struct.unpack_from('<I', data, 16)[0]
    export_count = struct.unpack_from('<I', data, 20)[0]
    export_offset = struct.unpack_from('<I', data, 24)[0]
    import_count = struct.unpack_from('<I', data, 28)[0]
    import_offset = struct.unpack_from('<I', data, 32)[0]

    # Parse name table
    pos = name_offset
    names = []
    name_offsets = []
    for i in range(name_count):
        name_offsets.append(pos)
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

    # Parse imports with FULL detail
    imports = []
    pos = import_offset
    for i in range(import_count):
        class_pkg_idx, pos = read_compact_index(data, pos)
        class_pkg_num = struct.unpack_from('<I', data, pos)[0]; pos += 4
        class_name_idx, pos = read_compact_index(data, pos)
        class_name_num = struct.unpack_from('<I', data, pos)[0]; pos += 4
        outer_idx = struct.unpack_from('<i', data, pos)[0]; pos += 4
        obj_name_idx, pos = read_compact_index(data, pos)
        obj_name_num = struct.unpack_from('<I', data, pos)[0]; pos += 4

        imports.append({
            'class_pkg_idx': class_pkg_idx,
            'class_name_idx': class_name_idx,
            'outer_idx': outer_idx,  # negative = import, positive = export
            'name_idx': obj_name_idx,
            'name_num': obj_name_num,
            'name': names[obj_name_idx] if 0 <= obj_name_idx < len(names) else '?',
            'class_pkg': names[class_pkg_idx] if 0 <= class_pkg_idx < len(names) else '?',
            'class_name': names[class_name_idx] if 0 <= class_name_idx < len(names) else '?',
        })

    # Parse exports with FULL detail
    exports = []
    pos = export_offset
    for i in range(export_count):
        exp_start = pos
        ci, pos = read_compact_index(data, pos)   # class index
        si, pos = read_compact_index(data, pos)   # super index
        oi = struct.unpack_from('<i', data, pos)[0]; pos += 4  # outer index
        bs_field1 = struct.unpack_from('<i', data, pos)[0]; pos += 4  # BioShock extra
        ni, pos = read_compact_index(data, pos)   # name index
        nn = struct.unpack_from('<I', data, pos)[0]; pos += 4  # name number
        flags = struct.unpack_from('<Q', data, pos)[0]; pos += 8  # flags
        sz, pos = read_compact_index(data, pos)   # serial size
        so = 0
        if sz > 0:
            so, pos = read_compact_index(data, pos)  # serial offset
        bs_field2 = struct.unpack_from('<i', data, pos)[0]; pos += 4  # BioShock extra

        name = names[ni] if 0 <= ni < len(names) else '?'

        # Resolve class name
        cls_name = 'Class'
        if ci > 0:
            ce = None  # will resolve after all exports parsed
        elif ci < 0:
            imp_idx = -ci - 1
            if 0 <= imp_idx < len(imports):
                cls_name = imports[imp_idx]['name']

        exports.append({
            'name': name, 'name_idx': ni, 'name_num': nn,
            'class_idx': ci, 'super_idx': si, 'outer_idx': oi,
            'flags': flags, 'size': sz, 'offset': so,
            'bs_field1': bs_field1, 'bs_field2': bs_field2,
            'cls_name': cls_name,
            '_entry_offset': exp_start,
        })

    # Second pass: resolve class names for exports referencing other exports
    for exp in exports:
        if exp['class_idx'] > 0:
            ci = exp['class_idx'] - 1
            if 0 <= ci < len(exports):
                exp['cls_name'] = exports[ci]['name']

    return {
        'data': data, 'names': names, 'imports': imports, 'exports': exports,
        'version': ver, 'licensee': lic, 'header_size': header_size,
        'name_count': name_count, 'name_offset': name_offset,
        'export_count': export_count, 'export_offset': export_offset,
        'import_count': import_count, 'import_offset': import_offset,
    }


def resolve_ref(pkg, idx):
    """Resolve a reference index to a name string.
    idx > 0  → export (1-based)
    idx < 0  → import (1-based negative)
    idx == 0 → None
    """
    if idx == 0:
        return None
    if idx > 0:
        e = pkg['exports'][idx - 1]
        return 'exp:%s' % e['name']
    else:
        i = pkg['imports'][-idx - 1]
        return 'imp:%s' % i['name']


def get_full_path(pkg, idx):
    """Get the full dotted path for an export or import."""
    parts = []
    seen = set()
    while idx != 0 and idx not in seen:
        seen.add(idx)
        if idx > 0:
            e = pkg['exports'][idx - 1]
            parts.append(e['name'])
            idx = e['outer_idx']
        elif idx < 0:
            i = pkg['imports'][-idx - 1]
            parts.append(i['name'])
            idx = i['outer_idx']
    parts.reverse()
    return '.'.join(parts)


def find_exports_by_name(pkg, pattern):
    """Find exports whose name contains pattern (case-insensitive)."""
    pat = pattern.lower()
    results = []
    for i, exp in enumerate(pkg['exports']):
        if pat in exp['name'].lower():
            results.append((i, exp))
    return results


def trace_serial_refs(pkg, export_idx):
    """Scan an export's serial data for compact-index references.
    Returns list of potential object references found in the serial data.
    This is heuristic — not all compact indices are object refs."""
    exp = pkg['exports'][export_idx]
    if exp['size'] <= 0:
        return []
    data = pkg['data']
    serial = data[exp['offset']:exp['offset'] + exp['size']]
    # We can't reliably parse arbitrary serial data, but we can note the size
    return {'size': exp['size'], 'offset': exp['offset']}


if __name__ == '__main__':
    import sys as _sys
    if len(_sys.argv) < 2:
        print("Usage: bsm_asset_analyzer.py <file.bsm> [search_pattern]")
        _sys.exit(1)

    filepath = _sys.argv[1]
    pattern = _sys.argv[2] if len(_sys.argv) > 2 else 'LaserGun'

    print("Parsing %s..." % filepath)
    pkg = parse_package_deep(filepath)
    print("  Names: %d, Imports: %d, Exports: %d" % (
        len(pkg['names']), len(pkg['imports']), len(pkg['exports'])))

    # Find matching exports
    matches = find_exports_by_name(pkg, pattern)
    print("\nExports matching '%s': %d" % (pattern, len(matches)))
    for idx, exp in matches:
        path = get_full_path(pkg, idx + 1)
        cls = exp['cls_name']
        outer = resolve_ref(pkg, exp['outer_idx'])
        print("  [%4d] %-50s class=%-25s size=%6d  outer=%s" % (
            idx, path, cls, exp['size'], outer or 'None'))

    # Find matching imports
    print("\nImports matching '%s':" % pattern)
    pat = pattern.lower()
    for i, imp in enumerate(pkg['imports']):
        if pat in imp['name'].lower():
            path = get_full_path(pkg, -(i + 1))
            print("  [%4d] %-50s class=%s.%s  outer=%s" % (
                i, path, imp['class_pkg'], imp['class_name'],
                resolve_ref(pkg, imp['outer_idx']) or 'None'))
