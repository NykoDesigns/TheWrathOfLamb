"""
The War In Rapture: BioShock 2 — IBF Archive Utilities
========================================================
Extracts and repacks the ConfigINI.IBF archive used by BioShock 2
Remastered to store all .ini configuration files.

BioShock 2 IBF format (differs from BioShock 1):
  For each file:
    BYTE          filename_wchar_length  (number of UTF-16LE chars incl. null)
    WCHAR[N]      filename in UTF-16LE
    COMPACT_INDEX content_wchar_length   (number of UTF-16LE chars incl. null)
    WCHAR[M]      content in UTF-16LE
  End of archive:
    BYTE 0x00     sentinel (filename_wchar_length == 0)

Key differences from BioShock 1:
  - Content length is encoded as a compact index (variable-length integer)
    rather than a fixed INT32.
  - Content length is measured in wchars (UTF-16LE code units), not bytes.
  - Both filenames and content are UTF-16LE encoded.
"""
import struct
import os
import shutil
import json
from pathlib import Path


# ─── Compact Index (same encoding as BSM packages) ──────────────────────────

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
IBF_PATH = GAME_ROOT / "ContentBaked" / "pc" / "ConfigINI.IBF"
IBF_BACKUP_PATH = IBF_PATH.with_suffix('.IBF.bak')
SYSTEM_DIR = GAME_ROOT / "ContentBaked" / "pc" / "System"
BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups" / "config"


# ─── Extract / Repack ────────────────────────────────────────────────────────

def extract_ibf(ibf_path=None):
    """Extract all INI files from a ConfigINI.IBF archive.

    Returns a dict  {filename: text_content, ...}
    """
    if ibf_path is None:
        ibf_path = IBF_PATH

    with open(ibf_path, 'rb') as f:
        data = f.read()

    pos = 0
    files = {}
    while pos < len(data):
        wchar_len = data[pos]; pos += 1
        if wchar_len == 0:
            break
        fname_raw = data[pos:pos + wchar_len * 2]; pos += wchar_len * 2
        filename = fname_raw.decode('utf-16-le').rstrip('\x00')

        content_wchars, pos = read_compact_index(data, pos)
        content_raw = data[pos:pos + content_wchars * 2]; pos += content_wchars * 2
        text = content_raw.decode('utf-16-le', errors='replace').rstrip('\x00')

        files[filename] = text

    return files


def repack_ibf(files, output_path=None):
    """Repack a dict of {filename: text_content} into IBF format.

    Writes the archive to *output_path* (default: IBF_PATH).
    """
    if output_path is None:
        output_path = IBF_PATH

    buf = bytearray()
    for filename, text in files.items():
        # Encode filename (add null terminator)
        fname_utf16 = (filename + '\x00').encode('utf-16-le')
        wchar_len = len(fname_utf16) // 2
        buf.append(wchar_len)
        buf += fname_utf16

        # Encode content (add null terminator)
        content_utf16 = (text + '\x00').encode('utf-16-le')
        content_wchars = len(content_utf16) // 2
        buf += write_compact_index(content_wchars)
        buf += content_utf16

    # Note: the original BioShock 2 IBF has no trailing sentinel byte;
    # the parser simply stops when it reaches the end of the file.

    with open(output_path, 'wb') as f:
        f.write(buf)

    return len(buf)


def backup_ibf():
    """Create a backup of the original IBF if one doesn't exist."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / "ConfigINI.IBF"
    if not backup_path.exists():
        shutil.copy2(str(IBF_PATH), str(backup_path))
        print("  Backed up IBF: %s" % backup_path)
    else:
        print("  IBF backup exists: %s" % backup_path)
    return backup_path


def restore_ibf():
    """Restore the original IBF from backup."""
    backup_path = BACKUP_DIR / "ConfigINI.IBF"
    if not backup_path.exists():
        print("  No IBF backup found at %s" % backup_path)
        return False
    shutil.copy2(str(backup_path), str(IBF_PATH))
    print("  Restored IBF: %s" % IBF_PATH)
    return True


def write_loose_ini(filename, text, system_dir=None):
    """Write an INI file as a loose file in the System directory.

    BioShock 2's engine loads loose .ini files from the System directory
    in preference to files inside ConfigINI.IBF.
    """
    if system_dir is None:
        system_dir = SYSTEM_DIR
    system_dir = Path(system_dir)
    system_dir.mkdir(parents=True, exist_ok=True)

    filepath = system_dir / filename
    with open(filepath, 'w', encoding='utf-16-le') as f:
        f.write('\ufeff')  # BOM
        f.write(text)
    return filepath


# ─── Convenience ─────────────────────────────────────────────────────────────

def get_ini(filename, ibf_files=None):
    """Get the text content of a specific INI file from the IBF."""
    if ibf_files is None:
        ibf_files = extract_ibf()
    return ibf_files.get(filename, None)


def list_ini_files(ibf_path=None):
    """List all INI filenames in the IBF archive."""
    files = extract_ibf(ibf_path)
    return sorted(files.keys())


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'list':
        names = list_ini_files()
        print("ConfigINI.IBF contains %d files:" % len(names))
        for n in names:
            print("  %s" % n)
    elif len(sys.argv) > 1 and sys.argv[1] == 'extract':
        files = extract_ibf()
        out_dir = Path(__file__).resolve().parent.parent / "extracted_ini"
        out_dir.mkdir(exist_ok=True)
        for fn, text in files.items():
            with open(out_dir / fn, 'w', encoding='utf-8') as f:
                f.write(text)
            print("  %s (%d chars)" % (fn, len(text)))
        print("\nExtracted %d files to %s" % (len(files), out_dir))
    elif len(sys.argv) > 1 and sys.argv[1] == 'roundtrip':
        # Verify extract→repack produces identical bytes
        with open(IBF_PATH, 'rb') as f:
            original = f.read()
        files = extract_ibf()
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ibf') as tmp:
            tmp_path = tmp.name
        repack_ibf(files, tmp_path)
        with open(tmp_path, 'rb') as f:
            repacked = f.read()
        os.unlink(tmp_path)
        if original == repacked:
            print("ROUNDTRIP OK: extract -> repack produces identical bytes")
        else:
            print("ROUNDTRIP MISMATCH: %d vs %d bytes" % (len(original), len(repacked)))
            # Find first diff
            for i in range(min(len(original), len(repacked))):
                if original[i] != repacked[i]:
                    print("  First diff at byte %d: orig=0x%02x repack=0x%02x" % (
                        i, original[i], repacked[i]))
                    break
    else:
        print("Usage: py ibf_utils.py [list|extract|roundtrip]")
