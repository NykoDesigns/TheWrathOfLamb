"""
The War In Rapture: BioShock 2 Remastered — GUI Installer
==========================================================
Standalone tkinter installer/uninstaller.  Compiled to .exe by
export_installer.py via PyInstaller.  Expects a 'mod_files/' sibling
directory containing all patched game files.

Features:
  - Auto-detect game via Steam registry + common paths
  - Browse button for manual selection
  - Progress bar during install/uninstall
  - Automatic backup of original files
  - Install log written to disk
  - Verification pass after install
"""

import os
import sys
import shutil
import threading
import time
import ctypes
import winreg
from pathlib import Path
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ── Constants ────────────────────────────────────────────────────────────────

APP_TITLE = "The War In Rapture — BioShock 2 Remastered"
VERSION = "2.0"
BACKUP_FOLDER = "_WarInRapture_Backup"
GAME_EXE = r"Build\Final\Bioshock2HD.exe"
IBF_REL = r"ContentBaked\pc\ConfigINI.IBF"
LBF_REL = r"ContentBaked\pc\Localizedint.lbf"
LOGO_FILENAME = "installer_logo.png"

KNOWN_LOOSE_INIS = [
    'Animation.ini', 'AutoTest.ini',
    'BGSounds.ini', 'BGSounds2D.ini', 'BGSounds3D.ini',
    'Bindings_perobjectconfig.ini', 'BotFlyingMotionParameters.ini',
    'DamageMultiplierSet.ini', 'DamageSets.ini',
    'Difficulty_perobjectconfig.ini', 'Gui_perobjectconfig.ini',
    'Inventory.ini', 'LootTables_perobjectconfig.ini',
    'Manual_perobjectconfig.ini', 'NewHacking_perobjectconfig.ini',
    'Physics.ini', 'Plasmids.ini', 'Plasmids_perobjectconfig.ini',
    'Quests_perobjectconfig.ini', 'Research_perobjectconfig.ini',
    'ResourceLimits.ini', 'SoundEffectChains.ini', 'SoundMixStates.ini',
    'Speech_perobjectconfig.ini', 'startup.ini', 'Version.ini',
    'WeaponUpgrades.ini', 'Weapon_Drill.ini',
]

# ── Utility ──────────────────────────────────────────────────────────────────

def get_script_dir():
    """Return the directory containing this script / frozen exe."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(os.path.dirname(os.path.abspath(__file__)))


def _get_bundled_path(filename):
    """Resolve a bundled data file — works for both frozen .exe and dev."""
    # PyInstaller --add-data extracts to sys._MEIPASS
    if getattr(sys, '_MEIPASS', None):
        p = Path(sys._MEIPASS) / filename
        if p.exists():
            return p
    # Fallback: next to the exe / script
    p = get_script_dir() / filename
    if p.exists():
        return p
    return None


def detect_game_directory():
    """Try to find the BioShock 2 Remastered install directory."""
    # Method 1: Steam registry — libraryfolders
    try:
        steam_path = _read_steam_path()
        if steam_path:
            game = _search_steam_libraries(steam_path)
            if game:
                return str(game)
    except Exception:
        pass

    # Method 2: Common paths
    common = [
        r"C:\Program Files (x86)\Steam\steamapps\common\BioShock 2 Remastered",
        r"C:\Program Files\Steam\steamapps\common\BioShock 2 Remastered",
        r"D:\SteamLibrary\steamapps\common\BioShock 2 Remastered",
        r"E:\SteamLibrary\steamapps\common\BioShock 2 Remastered",
        r"F:\SteamLibrary\steamapps\common\BioShock 2 Remastered",
        r"G:\SteamLibrary\steamapps\common\BioShock 2 Remastered",
        r"X:\SteamLibrary\steamapps\common\BioShock 2 Remastered",
    ]
    for p in common:
        if (Path(p) / GAME_EXE).exists():
            return p
    return ""


def _read_steam_path():
    """Read Steam install path from the Windows registry."""
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for subkey in (r"SOFTWARE\Valve\Steam",
                       r"SOFTWARE\WOW6432Node\Valve\Steam"):
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, "InstallPath")
                    if val and Path(val).exists():
                        return Path(val)
            except OSError:
                continue
    return None


def _search_steam_libraries(steam_path):
    """Parse libraryfolders.vdf to find all Steam library paths,
    then look for BioShock 2 Remastered in each."""
    vdf = steam_path / "steamapps" / "libraryfolders.vdf"
    lib_paths = [steam_path]
    if vdf.exists():
        try:
            text = vdf.read_text(encoding='utf-8', errors='replace')
            import re
            for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                p = Path(m.group(1).replace('\\\\', '\\'))
                if p.exists():
                    lib_paths.append(p)
        except Exception:
            pass
    for lib in lib_paths:
        candidate = lib / "steamapps" / "common" / "BioShock 2 Remastered"
        if (candidate / GAME_EXE).exists():
            return candidate
    return None


def validate_game_dir(path_str):
    """Return True if the path looks like a valid game directory."""
    if not path_str:
        return False
    p = Path(path_str)
    return (p / GAME_EXE).exists()


# ── Installer GUI ────────────────────────────────────────────────────────────

class InstallerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("620x700")
        self.root.resizable(False, False)
        self.root.configure(bg='#1a1a2e')

        self.script_dir = get_script_dir()
        self.mod_dir = self.script_dir / "mod_files"
        self.working = False
        self.log_lines = []

        # Try to set DPI awareness
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self._setup_styles()
        self._build_ui()

        # Auto-detect game on startup
        detected = detect_game_directory()
        if detected:
            self.path_var.set(detected)
            self._log("Auto-detected game at:\n  %s" % detected)
        else:
            self._log("Could not auto-detect game directory.\n"
                      "Use Browse to locate your BioShock 2 Remastered folder.")

        # Verify mod_files exists
        if not self.mod_dir.exists():
            self._log("\nWARNING: 'mod_files' folder not found next to this installer.\n"
                      "Make sure the entire folder structure is extracted from the zip.")

    # ── Styles ───────────────────────────────────────────────────────────

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        BG = '#1a1a2e'
        BG2 = '#16213e'
        BG3 = '#0f3460'
        FG = '#e2e2e2'
        ACCENT = '#e94560'
        GREEN = '#4ecca3'

        style.configure('.', background=BG, foreground=FG)
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=FG,
                        font=('Segoe UI', 10))
        style.configure('Title.TLabel', background=BG, foreground='#e94560',
                        font=('Segoe UI', 16, 'bold'))
        style.configure('Sub.TLabel', background=BG, foreground='#7f8fa6',
                        font=('Segoe UI', 9))
        style.configure('TButton', font=('Segoe UI', 10, 'bold'),
                        padding=(16, 8))
        style.configure('Install.TButton', background=GREEN, foreground='#111')
        style.configure('Uninstall.TButton', background=ACCENT, foreground='#111')
        style.configure('Browse.TButton', padding=(8, 4))
        style.configure('TEntry', fieldbackground=BG2, foreground=FG,
                        insertcolor=FG)

        style.configure("green.Horizontal.TProgressbar",
                        troughcolor=BG2, background=GREEN)

    # ── UI ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {'padx': 16, 'pady': 4}
        BG = '#1a1a2e'

        # Logo / Title
        self._logo_image = None  # prevent GC
        logo_path = _get_bundled_path(LOGO_FILENAME)
        if logo_path:
            try:
                self._logo_image = tk.PhotoImage(file=str(logo_path))
                tk.Label(self.root, image=self._logo_image, bg=BG,
                         borderwidth=0).pack(pady=(10, 0))
                ttk.Label(self.root,
                          text="Mod Installer v%s" % VERSION,
                          style='Sub.TLabel').pack(pady=(0, 8))
            except Exception:
                self._logo_image = None

        if self._logo_image is None:
            ttk.Label(self.root, text="THE WAR IN RAPTURE",
                      style='Title.TLabel').pack(pady=(18, 0))
            ttk.Label(self.root,
                      text="BioShock 2 Remastered \u2014 Mod Installer v%s" % VERSION,
                      style='Sub.TLabel').pack(pady=(0, 12))

        ttk.Separator(self.root).pack(fill='x', padx=16)

        # Game directory
        dir_frame = ttk.Frame(self.root)
        dir_frame.pack(fill='x', padx=16, pady=(10, 4))

        ttk.Label(dir_frame, text="Game Directory:").pack(anchor='w')

        path_frame = ttk.Frame(dir_frame)
        path_frame.pack(fill='x', pady=(4, 0))

        self.path_var = tk.StringVar()
        self.path_entry = ttk.Entry(path_frame, textvariable=self.path_var,
                                    font=('Segoe UI', 9))
        self.path_entry.pack(side='left', fill='x', expand=True, padx=(0, 6))

        ttk.Button(path_frame, text="Browse...", style='Browse.TButton',
                   command=self._browse).pack(side='right')

        # Buttons
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill='x', padx=16, pady=(12, 4))

        self.install_btn = ttk.Button(btn_frame, text="  Install Mod  ",
                                      style='Install.TButton',
                                      command=self._do_install)
        self.install_btn.pack(side='left', padx=(0, 8))

        self.uninstall_btn = ttk.Button(btn_frame, text="  Uninstall Mod  ",
                                        style='Uninstall.TButton',
                                        command=self._do_uninstall)
        self.uninstall_btn.pack(side='left', padx=(0, 8))

        # Progress
        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Progressbar(self.root, variable=self.progress_var,
                                        maximum=100,
                                        style="green.Horizontal.TProgressbar")
        self.progress.pack(fill='x', padx=16, pady=(8, 4))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var,
                  style='Sub.TLabel').pack(anchor='w', padx=16)

        # Log area
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill='both', expand=True, padx=16, pady=(6, 16))

        self.log_text = tk.Text(log_frame, wrap='word', height=10,
                                bg='#0d1117', fg='#c9d1d9',
                                insertbackground='#c9d1d9',
                                font=('Consolas', 9), relief='flat',
                                state='disabled', borderwidth=0)
        scrollbar = ttk.Scrollbar(log_frame, orient='vertical',
                                  command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Tag for colored text
        self.log_text.tag_configure('ok', foreground='#4ecca3')
        self.log_text.tag_configure('warn', foreground='#ffa502')
        self.log_text.tag_configure('err', foreground='#e94560')

    # ── Actions ──────────────────────────────────────────────────────────

    def _browse(self):
        d = filedialog.askdirectory(title="Select BioShock 2 Remastered folder")
        if d:
            self.path_var.set(d)

    def _set_buttons(self, enabled):
        state = 'normal' if enabled else 'disabled'
        self.install_btn.configure(state=state)
        self.uninstall_btn.configure(state=state)

    def _log(self, msg, tag=None):
        self.log_text.configure(state='normal')
        self.log_text.insert('end', msg + '\n', tag or '')
        self.log_text.see('end')
        self.log_text.configure(state='disabled')
        self.log_lines.append(msg)

    def _do_install(self):
        if self.working:
            return
        game_dir = self.path_var.get().strip()
        if not validate_game_dir(game_dir):
            messagebox.showerror("Invalid Path",
                                 "Could not find Bioshock2HD.exe in that directory.\n\n"
                                 "Please select the folder containing Build\\ and ContentBaked\\.")
            return
        if not self.mod_dir.exists():
            messagebox.showerror("Missing Files",
                                 "'mod_files' folder not found next to the installer.\n"
                                 "Extract the full zip before running.")
            return
        self.working = True
        self._set_buttons(False)
        self.progress_var.set(0)
        t = threading.Thread(target=self._install_worker, args=(game_dir,), daemon=True)
        t.start()

    def _do_uninstall(self):
        if self.working:
            return
        game_dir = self.path_var.get().strip()
        if not validate_game_dir(game_dir):
            messagebox.showerror("Invalid Path",
                                 "Could not find Bioshock2HD.exe in that directory.")
            return
        backup_dir = Path(game_dir) / BACKUP_FOLDER
        if not backup_dir.exists():
            messagebox.showerror("No Backup",
                                 "No backup folder found at:\n%s\n\n"
                                 "You can verify game files through Steam instead:\n"
                                 "Right-click BioShock 2 > Properties > Local Files > Verify"
                                 % backup_dir)
            return
        if not messagebox.askyesno("Confirm Uninstall",
                                   "This will restore all original game files from backup.\n\n"
                                   "Continue?"):
            return
        self.working = True
        self._set_buttons(False)
        self.progress_var.set(0)
        t = threading.Thread(target=self._uninstall_worker, args=(game_dir,), daemon=True)
        t.start()

    # ── Install worker ───────────────────────────────────────────────────

    def _install_worker(self, game_dir):
        game = Path(game_dir)
        backup = game / BACKUP_FOLDER
        log_path = self.script_dir / ("install_log_%s.txt" % datetime.now().strftime('%Y%m%d_%H%M%S'))

        try:
            # Enumerate mod files
            mod_files = []
            for root_d, dirs, files in os.walk(str(self.mod_dir)):
                for fn in files:
                    full = Path(root_d) / fn
                    rel = full.relative_to(self.mod_dir)
                    mod_files.append((full, rel))

            total = len(mod_files) + 3  # +3 for backup, IBF rename, verify
            done = 0

            def tick(msg=None):
                nonlocal done
                done += 1
                pct = min(100, done * 100 // total)
                self.root.after(0, lambda: self.progress_var.set(pct))
                if msg:
                    self.root.after(0, lambda m=msg: self.status_var.set(m))

            # ── Step 1: Backup originals ─────────────────────────────
            self.root.after(0, lambda: self._log("\n[1/4] Backing up original files...", 'ok'))
            self.root.after(0, lambda: self.status_var.set("Backing up..."))
            backup.mkdir(parents=True, exist_ok=True)
            backed_up = 0

            for src, rel in mod_files:
                orig = game / rel
                bak_dst = backup / rel
                if orig.exists() and not bak_dst.exists():
                    bak_dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(orig), str(bak_dst))
                    backed_up += 1

            # Backup ConfigINI.IBF
            ibf = game / IBF_REL
            ibf_bak = backup / IBF_REL
            if ibf.exists() and not ibf_bak.exists():
                ibf_bak.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(ibf), str(ibf_bak))
                backed_up += 1

            # Backup Localizedint.lbf (display names for weapons/plasmids)
            lbf = game / LBF_REL
            lbf_bak = backup / LBF_REL
            if lbf.exists() and not lbf_bak.exists():
                lbf_bak.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(lbf), str(lbf_bak))
                backed_up += 1

            self.root.after(0, lambda: self._log("  Backed up %d files." % backed_up))
            tick("Backup complete")

            # ── Step 2: Copy mod files ───────────────────────────────
            self.root.after(0, lambda: self._log("\n[2/4] Installing mod files...", 'ok'))
            copied = 0
            for src, rel in mod_files:
                dst = game / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                copied += 1
                tick("Copying: %s" % rel.name)

            self.root.after(0, lambda: self._log("  Copied %d files." % copied))

            # ── Step 3: Rename ConfigINI.IBF ─────────────────────────
            self.root.after(0, lambda: self._log("\n[3/4] Disabling ConfigINI.IBF...", 'ok'))
            if ibf.exists():
                ibf_bak_game = ibf.with_suffix('.IBF.bak')
                try:
                    ibf.rename(ibf_bak_game)
                    self.root.after(0, lambda: self._log("  Renamed to ConfigINI.IBF.bak"))
                except OSError as e:
                    self.root.after(0, lambda: self._log("  WARNING: Could not rename IBF: %s" % e, 'warn'))
            else:
                self.root.after(0, lambda: self._log("  Already renamed or not present."))
            tick("IBF handled")

            # ── Step 4: Verify ───────────────────────────────────────
            self.root.after(0, lambda: self._log("\n[4/4] Verifying installation...", 'ok'))
            missing = []
            for src, rel in mod_files:
                dst = game / rel
                if not dst.exists():
                    missing.append(str(rel))
                elif dst.stat().st_size != src.stat().st_size:
                    missing.append(str(rel) + " (size mismatch)")

            if missing:
                self.root.after(0, lambda: self._log(
                    "  WARNING: %d files could not be verified:" % len(missing), 'warn'))
                for m in missing[:10]:
                    self.root.after(0, lambda m=m: self._log("    - %s" % m, 'warn'))
            else:
                self.root.after(0, lambda: self._log(
                    "  All %d files verified successfully." % len(mod_files), 'ok'))
            tick("Done")

            # ── Write log ────────────────────────────────────────────
            try:
                with open(log_path, 'w') as f:
                    f.write("War In Rapture Install Log — %s\n" % datetime.now().isoformat())
                    f.write("Game: %s\n" % game_dir)
                    f.write("Files: %d\n\n" % len(mod_files))
                    for line in self.log_lines:
                        f.write(line + '\n')
            except Exception:
                pass

            self.root.after(0, lambda: self.progress_var.set(100))
            self.root.after(0, lambda: self.status_var.set("Installation complete!"))
            self.root.after(0, lambda: self._log(
                "\n========================================\n"
                "  INSTALLED SUCCESSFULLY!\n"
                "========================================\n"
                "  Launch BioShock 2 Remastered and start\n"
                "  a new game (or load from a level\n"
                "  transition save) to see changes.\n"
                "========================================", 'ok'))

        except Exception as e:
            self.root.after(0, lambda: self._log("\nERROR: %s" % e, 'err'))
            self.root.after(0, lambda: self.status_var.set("Installation failed!"))
        finally:
            self.working = False
            self.root.after(0, lambda: self._set_buttons(True))

    # ── Uninstall worker ─────────────────────────────────────────────────

    def _uninstall_worker(self, game_dir):
        game = Path(game_dir)
        backup = game / BACKUP_FOLDER

        try:
            # Count files to restore
            restore_files = []
            for root_d, dirs, files in os.walk(str(backup)):
                for fn in files:
                    full = Path(root_d) / fn
                    rel = full.relative_to(backup)
                    restore_files.append((full, rel))

            total = len(restore_files) + 4
            done = 0

            def tick(msg=None):
                nonlocal done
                done += 1
                pct = min(100, done * 100 // total)
                self.root.after(0, lambda: self.progress_var.set(pct))
                if msg:
                    self.root.after(0, lambda m=msg: self.status_var.set(m))

            # ── Step 1: Restore from backup ──────────────────────────
            self.root.after(0, lambda: self._log("\n[1/3] Restoring original files...", 'ok'))
            restored = 0
            for src, rel in restore_files:
                dst = game / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                restored += 1
                tick("Restoring: %s" % rel.name)

            self.root.after(0, lambda: self._log("  Restored %d files." % restored))

            # ── Step 2: Restore ConfigINI.IBF ────────────────────────
            self.root.after(0, lambda: self._log("\n[2/4] Restoring ConfigINI.IBF...", 'ok'))
            ibf_bak = game / (IBF_REL + ".bak")
            ibf_orig = game / IBF_REL
            if ibf_bak.exists():
                if ibf_orig.exists():
                    ibf_orig.unlink()
                ibf_bak.rename(ibf_orig)
                self.root.after(0, lambda: self._log("  Restored from .bak"))
            else:
                self.root.after(0, lambda: self._log("  No .bak found (already restored or never renamed)."))
            tick("IBF restored")

            # ── Step 3: Restore Localizedint.lbf ─────────────────────
            self.root.after(0, lambda: self._log("\n[3/4] Restoring Localizedint.lbf...", 'ok'))
            lbf_bak = backup / LBF_REL
            lbf_orig = game / LBF_REL
            if lbf_bak.exists():
                shutil.copy2(str(lbf_bak), str(lbf_orig))
                self.root.after(0, lambda: self._log("  Restored display names from backup"))
            else:
                self.root.after(0, lambda: self._log("  No LBF backup found (skipping)."))
            tick("LBF restored")

            # ── Step 4: Remove mod-only files + loose INIs ───────────
            self.root.after(0, lambda: self._log("\n[4/4] Cleaning up mod-only files...", 'ok'))
            removed = 0

            # DLCWeapons.U — only remove if it wasn't backed up (mod-added)
            dlc = game / "Build" / "Final" / "BakedScripts" / "pc" / "DLCWeapons.U"
            dlc_bak = backup / "Build" / "Final" / "BakedScripts" / "pc" / "DLCWeapons.U"
            if dlc.exists() and not dlc_bak.exists():
                dlc.unlink()
                removed += 1

            # Weapon_Drill.ini — only remove if mod-added
            wd = game / "ContentBaked" / "pc" / "System" / "Weapon_Drill.ini"
            wd_bak = backup / "ContentBaked" / "pc" / "System" / "Weapon_Drill.ini"
            if wd.exists() and not wd_bak.exists():
                wd.unlink()
                removed += 1

            # Remove loose INI overrides
            sys_dir = game / "ContentBaked" / "pc" / "System"
            for ini in KNOWN_LOOSE_INIS:
                ini_f = sys_dir / ini
                if ini_f.exists():
                    ini_f.unlink()
                    removed += 1

            self.root.after(0, lambda: self._log("  Removed %d mod files." % removed))
            tick("Cleanup done")

            self.root.after(0, lambda: self.progress_var.set(100))
            self.root.after(0, lambda: self.status_var.set("Uninstall complete!"))
            self.root.after(0, lambda: self._log(
                "\n========================================\n"
                "  UNINSTALLED SUCCESSFULLY!\n"
                "========================================\n"
                "  Your game files have been restored.\n"
                "  Tip: Verify files via Steam for safety:\n"
                "  Right-click > Properties > Verify\n"
                "========================================", 'ok'))

        except Exception as e:
            self.root.after(0, lambda: self._log("\nERROR: %s" % e, 'err'))
            self.root.after(0, lambda: self.status_var.set("Uninstall failed!"))
        finally:
            self.working = False
            self.root.after(0, lambda: self._set_buttons(True))


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    root.withdraw()

    # Center on screen
    root.update_idletasks()
    w, h = 620, 700
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry('%dx%d+%d+%d' % (w, h, x, y))

    app = InstallerApp(root)
    root.deiconify()
    root.mainloop()


if __name__ == '__main__':
    main()
