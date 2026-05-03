"""
Export Installer — The War In Rapture: BioShock 2 Remastered
=============================================================
Collects all patched game files produced by the mod manager and
packages them into a distributable installer folder + .exe.

After running "Apply Mod" in the mod manager, run this script.
A folder picker lets you choose where to export.  The output
contains:

    TheWarInRapture2/
        WarInRapture_Install.exe   (GUI installer)
        mod_files/                 (all patched game files)
        README.txt

Zip the TheWarInRapture2 folder and distribute.  Users run the exe.

Usage:
    python export_installer.py
"""

import os
import sys
import shutil
import json
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = SCRIPT_DIR / "settings.json"
PRISTINE_DIR = SCRIPT_DIR / "backups" / "pristine"
INSTALLER_GUI = SCRIPT_DIR / "installer_gui.py"

# ─── Game root detection ──────────────────────────────────────────────────────

def _get_game_root():
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r') as f:
                gr = json.load(f).get('game_root')
                if gr and Path(gr).exists():
                    return Path(gr)
        except Exception:
            pass
    default = Path(r"D:\SteamLibrary\steamapps\common\BioShock 2 Remastered")
    if default.exists():
        return default
    print("ERROR: Cannot find game root. Set game_root in settings.json")
    sys.exit(1)

# ─── File collection ──────────────────────────────────────────────────────────

def collect_files(game_root):
    """
    Identify all files modified/created by the mod.
    Returns a list of (src_path, relative_path) tuples.
    """
    files = []
    content_dir = game_root / "ContentBaked" / "pc"
    maps_dir = content_dir / "Maps"
    system_dir = content_dir / "System"
    scripts_dir = game_root / "Build" / "Final" / "BakedScripts" / "pc"

    # 1) BSM map files — only include ones that differ from pristine
    print("\n[1] Checking map files...")
    map_count = 0
    for bsm in sorted(maps_dir.glob("*.bsm")):
        pristine = PRISTINE_DIR / bsm.name
        if pristine.exists():
            # Compare file sizes first (fast check — patched maps are larger)
            if bsm.stat().st_size != pristine.stat().st_size:
                rel = Path("ContentBaked") / "pc" / "Maps" / bsm.name
                files.append((bsm, rel))
                map_count += 1
                print("  CHANGED: %s (%+d bytes)" % (
                    bsm.name,
                    bsm.stat().st_size - pristine.stat().st_size))
            else:
                # Same size — do byte comparison
                if bsm.read_bytes() != pristine.read_bytes():
                    rel = Path("ContentBaked") / "pc" / "Maps" / bsm.name
                    files.append((bsm, rel))
                    map_count += 1
                    print("  CHANGED: %s (same size, different content)" % bsm.name)
        else:
            # No pristine backup — new file, include it
            rel = Path("ContentBaked") / "pc" / "Maps" / bsm.name
            files.append((bsm, rel))
            map_count += 1
            print("  NEW: %s" % bsm.name)
    print("  Maps to include: %d" % map_count)

    # 2) Loose INI files in System/
    print("\n[2] Checking loose INI files...")
    # These are the INI files extracted from ConfigINI.IBF and written as loose
    # overrides.  We also include any new INI files (e.g. Weapon_Drill.ini).
    # Exclude stock files that exist in pristine and haven't changed.
    stock_inis = {'Default.ini', 'DefUser.ini'}  # these live in System/ but are stock
    ini_count = 0
    if system_dir.exists():
        for ini_f in sorted(system_dir.glob("*.ini")):
            if ini_f.name in stock_inis:
                # Check if modified vs pristine
                pristine = PRISTINE_DIR / ini_f.name
                if pristine.exists() and ini_f.read_bytes() == pristine.read_bytes():
                    continue  # unchanged stock file
            rel = Path("ContentBaked") / "pc" / "System" / ini_f.name
            files.append((ini_f, rel))
            ini_count += 1
            print("  %s (%d bytes)" % (ini_f.name, ini_f.stat().st_size))
    print("  INI files to include: %d" % ini_count)

    # 3) ShockGame.U (bytecode patches)
    print("\n[3] Checking ShockGame.U...")
    sg = scripts_dir / "ShockGame.U"
    sg_pristine = PRISTINE_DIR / "ShockGame.U"
    if sg.exists():
        if sg_pristine.exists() and sg.stat().st_size == sg_pristine.stat().st_size:
            if sg.read_bytes() == sg_pristine.read_bytes():
                print("  ShockGame.U: unchanged (skipping)")
            else:
                rel = Path("Build") / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
                files.append((sg, rel))
                print("  ShockGame.U: CHANGED (same size, different content)")
        else:
            rel = Path("Build") / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
            files.append((sg, rel))
            print("  ShockGame.U: CHANGED (%+d bytes)" % (
                sg.stat().st_size - (sg_pristine.stat().st_size if sg_pristine.exists() else 0)))

    # 4) DLCWeapons.U (ion laser — new file)
    dlc = scripts_dir / "DLCWeapons.U"
    if dlc.exists():
        rel = Path("Build") / "Final" / "BakedScripts" / "pc" / "DLCWeapons.U"
        files.append((dlc, rel))
        print("  DLCWeapons.U: %d bytes" % dlc.stat().st_size)

    # 5) Default.ini (Build/Final/ — ServerPackages, PerObjIniFile)
    print("\n[4] Checking Default.ini...")
    di = game_root / "Build" / "Final" / "Default.ini"
    di_pristine = PRISTINE_DIR / "Default.ini"
    if di.exists():
        if di_pristine.exists() and di.read_bytes() == di_pristine.read_bytes():
            print("  Default.ini: unchanged (skipping)")
        else:
            rel = Path("Build") / "Final" / "Default.ini"
            files.append((di, rel))
            print("  Default.ini: CHANGED")

    # 6) Localizedint.lbf (display names for weapons/plasmids/ammo)
    print("\n[5] Checking Localizedint.lbf...")
    content_dir = game_root / "ContentBaked" / "pc"
    lbf = content_dir / "Localizedint.lbf"
    lbf_pristine = PRISTINE_DIR / "Localizedint.lbf"
    if lbf.exists():
        if lbf_pristine.exists() and lbf.read_bytes() == lbf_pristine.read_bytes():
            print("  Localizedint.lbf: unchanged (skipping)")
        else:
            rel = Path("ContentBaked") / "pc" / "Localizedint.lbf"
            files.append((lbf, rel))
            print("  Localizedint.lbf: CHANGED (display names patched)")

    return files


def _pick_output_directory():
    """Open a folder picker dialog and return the chosen path, or None."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        default_dir = str(SCRIPT_DIR / "installer_output")
        chosen = filedialog.askdirectory(
            title="Choose where to export the installer",
            initialdir=default_dir)
        root.destroy()
        if chosen:
            return Path(chosen)
    except Exception as e:
        print("  Could not open folder picker: %s" % e)
    return None


def build_installer(game_root, files, output_base):
    """Create the installer directory with mod files + compiled .exe."""
    output_dir = output_base / "TheWarInRapture2"

    if output_dir.exists():
        shutil.rmtree(str(output_dir))
    output_dir.mkdir(parents=True)

    mod_dir = output_dir / "mod_files"

    # Copy all collected files preserving relative structure
    print("\n[5] Copying %d files to installer..." % len(files))
    total_size = 0
    for src, rel in files:
        dst = mod_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        total_size += src.stat().st_size
        print("  -> %s" % rel)

    # Detect map names for readme
    map_names = [r.name for _, r in files
                 if str(r).startswith(str(Path("ContentBaked") / "pc" / "Maps"))]

    # ── Generate README ───────────────────────────────────────────────────
    readme = _generate_readme(len(files), total_size, map_names)
    with open(output_dir / "README.txt", 'w', newline='\r\n') as f:
        f.write(readme)

    # ── Copy logo to output ───────────────────────────────────────────────
    logo_src = SCRIPT_DIR / "installer_logo.png"
    if logo_src.exists():
        shutil.copy2(str(logo_src), str(output_dir / "installer_logo.png"))
        print("  Copied installer_logo.png")

    # ── Compile installer .exe via PyInstaller ────────────────────────────
    exe_built = False
    if INSTALLER_GUI.exists():
        print("\n[7] Building installer .exe with PyInstaller...")
        exe_built = _build_exe(output_dir, logo_src if logo_src.exists() else None)
    else:
        print("\n[6] WARNING: installer_gui.py not found — skipping .exe build")

    # ── Fallback: copy the Python script if exe build failed ──────────────
    if not exe_built:
        print("  Copying installer_gui.py as fallback...")
        shutil.copy2(str(INSTALLER_GUI), str(output_dir / "installer_gui.py"))
        # Also write a small launcher batch file
        bat = (
            '@echo off\n'
            'echo Launching War In Rapture installer...\n'
            'python "%~dp0installer_gui.py"\n'
            'if errorlevel 1 (\n'
            '    echo.\n'
            '    echo Python not found. Install Python 3.8+ from python.org\n'
            '    echo or use the .exe installer if available.\n'
            '    pause\n'
            ')\n'
        )
        with open(output_dir / "install.bat", 'w', newline='\r\n') as f:
            f.write(bat)

    print("\n" + "=" * 62)
    print("  INSTALLER EXPORTED SUCCESSFULLY")
    print("=" * 62)
    print("  Output:  %s" % output_dir)
    print("  Files:   %d" % len(files))
    print("  Size:    %.1f MB" % (total_size / 1024 / 1024))
    if exe_built:
        print("  Exe:     WarInRapture_Install.exe")
    else:
        print("  Exe:     NOT BUILT (Nuitka unavailable)")
        print("           install.bat + installer_gui.py included as fallback")
    print("\n  To distribute: zip the entire TheWarInRapture2 folder.")
    print("  Users run WarInRapture_Install.exe to install/uninstall.")


def _build_exe(output_dir, logo_path=None):
    """Compile installer_gui.py into a standalone .exe using Nuitka."""
    # Check if Nuitka is available
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'nuitka', '--version'],
            capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            print("  Nuitka not found. Install with: pip install nuitka")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("  Nuitka not found. Install with: pip install nuitka")
        return False

    exe_name = "WarInRapture_Install"
    build_tmp = SCRIPT_DIR / "_nuitka_build"
    if build_tmp.exists():
        shutil.rmtree(str(build_tmp))

    cmd = [
        sys.executable, '-m', 'nuitka',
        '--onefile',
        '--windows-console-mode=disable',
        '--output-dir=%s' % str(build_tmp),
        '--output-filename=%s.exe' % exe_name,
        '--enable-plugin=tk-inter',
        '--remove-output',
        '--assume-yes-for-download',
    ]
    if logo_path and logo_path.exists():
        cmd.append('--include-data-files=%s=installer_logo.png' % str(logo_path))
    cmd.append(str(INSTALLER_GUI))

    print("  Running Nuitka (this may take a few minutes)...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            # Nuitka places the exe in build_tmp
            built_exe = build_tmp / ("%s.exe" % exe_name)
            if not built_exe.exists():
                # Search for it
                for f in build_tmp.rglob("*.exe"):
                    if exe_name.lower() in f.name.lower():
                        built_exe = f
                        break
            if built_exe.exists():
                final_exe = output_dir / ("%s.exe" % exe_name)
                shutil.move(str(built_exe), str(final_exe))
                print("  Built: %s (%.1f MB)" % (
                    final_exe.name, final_exe.stat().st_size / 1024 / 1024))
                if build_tmp.exists():
                    shutil.rmtree(str(build_tmp), ignore_errors=True)
                return True
            else:
                print("  Nuitka ran but exe not found in output.")
        else:
            print("  Nuitka failed (exit code %d)" % result.returncode)
            if result.stderr:
                err_lines = result.stderr.strip().split('\n')
                for line in err_lines[-5:]:
                    print("    %s" % line)
    except subprocess.TimeoutExpired:
        print("  Nuitka timed out (600s).")
    except Exception as e:
        print("  Nuitka error: %s" % e)

    if build_tmp.exists():
        shutil.rmtree(str(build_tmp), ignore_errors=True)
    return False


def _generate_readme(file_count, total_size, map_names):
    lines = []
    lines.append('=' * 64)
    lines.append('  THE WAR IN RAPTURE')
    lines.append('  BioShock 2 Remastered — Game Modification')
    lines.append('=' * 64)
    lines.append('')
    lines.append('INSTALLATION')
    lines.append('------------')
    lines.append('  1. Run WarInRapture_Install.exe')
    lines.append('     (or install.bat if .exe is not available)')
    lines.append('  2. The installer will auto-detect your game directory')
    lines.append('     (or let you browse to it)')
    lines.append('  3. Click "Install Mod"')
    lines.append('  4. Original files are backed up to _WarInRapture_Backup/')
    lines.append('     inside your game folder')
    lines.append('  5. Launch BioShock 2 Remastered and start a NEW GAME')
    lines.append('     (or load from a level transition save point)')
    lines.append('')
    lines.append('UNINSTALLATION')
    lines.append('--------------')
    lines.append('  Run WarInRapture_Install.exe and click "Uninstall Mod".')
    lines.append('  Alternatively, verify game files through Steam:')
    lines.append('  Right-click BioShock 2 > Properties > Local Files > Verify')
    lines.append('')
    lines.append('IMPORTANT NOTES')
    lines.append('---------------')
    lines.append('  - Scripted encounter and spawn changes require starting a new')
    lines.append('    game or transitioning from a previous level. Loading a')
    lines.append('    mid-level save uses the saved game state.')
    lines.append('  - INI balance changes (damage, loot, difficulty) take effect')
    lines.append('    immediately on launch.')
    lines.append('  - Do NOT verify game files through Steam while the mod is')
    lines.append('    installed, or you will lose the changes.')
    lines.append('')
    lines.append('WHAT THIS MOD CHANGES')
    lines.append('---------------------')
    lines.append('  - Enemy spawner duplication in map files (more enemies)')
    lines.append('  - Scripted encounter additions (bigger ambushes)')
    lines.append('  - INI balance: damage, loot tables, difficulty scaling')
    lines.append('  - Weapon upgrades: ricochet, knockback, new ammo effects')
    lines.append('  - Plasmid enhancements: Electric Highlight, etc.')
    lines.append('  - Enemy health scaling')
    lines.append('  - Bytecode patches to ShockGame.U')
    lines.append('')
    lines.append('  Modified maps: %s' % ', '.join(
        n.replace('.bsm', '') for n in sorted(map_names)) if map_names else '  (none)')
    lines.append('  Total files: %d (%.1f MB)' % (file_count, total_size / 1024 / 1024))
    lines.append('')
    lines.append('=' * 64)
    lines.append('')
    return '\n'.join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 62)
    print("  THE WAR IN RAPTURE: BioShock 2 — Export Installer")
    print("=" * 62)

    game_root = _get_game_root()
    print("\n  Game root: %s" % game_root)
    print("  Pristine:  %s" % PRISTINE_DIR)

    if not PRISTINE_DIR.exists():
        print("\nERROR: Pristine backup directory not found.")
        print("       Run the mod manager and apply the mod first.")
        sys.exit(1)

    # Ask user where to export
    print("\n  Opening folder picker...")
    output_base = _pick_output_directory()
    if not output_base:
        # Fallback: use default location
        print("  No directory chosen. Using default: installer_output/")
        output_base = SCRIPT_DIR / "installer_output"

    print("  Output to: %s" % output_base)

    files = collect_files(game_root)

    if not files:
        print("\nNo modified files found. Apply the mod first, then run this.")
        sys.exit(1)

    build_installer(game_root, files, output_base)


if __name__ == '__main__':
    main()
