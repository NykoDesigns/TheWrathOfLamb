"""
The War In Rapture: BioShock 2 — Mod Manager / Trainer
=======================================================
Main launcher for The War In Rapture BioShock 2 mod.
Provides a graphical UI for:

  Tab 1 - Repopulation: Spawner duplication (Aggressors, Big Daddies,
                         Security Bots) per-level multiplier.
  Tab 2 - Damage:       Weapon and plasmid damage values via DamageSets.ini.
  Tab 3 - Loot:         Enemy loot drop tables per enemy type.
  Tab 4 - Difficulty:   Difficulty curve scaling.

The mod works by:
  1. Backing up pristine game files on first run.
  2. Restoring pristine files before each apply (clean slate).
  3. Patching INI files (extracted from ConfigINI.IBF) for game balance.
  4. Binary-patching BSM map files to duplicate spawner actors.
"""

import tkinter as tk
from tkinter import ttk
import threading
import queue
import sys
import os
import shutil
import json
import logging
import platform
import datetime
from pathlib import Path

BIOMOD_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BIOMOD_DIR))

# ─── Settings / Paths ────────────────────────────────────────────────────────
SETTINGS_FILE = BIOMOD_DIR / "settings.json"
DEFAULT_GAME_ROOT = Path(r"D:\SteamLibrary\steamapps\common\BioShock 2 Remastered")

_GAME_SEARCH_PATHS = [
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\BioShock 2 Remastered"),
    Path(r"C:\Program Files\Steam\steamapps\common\BioShock 2 Remastered"),
    Path(r"D:\SteamLibrary\steamapps\common\BioShock 2 Remastered"),
    Path(r"E:\SteamLibrary\steamapps\common\BioShock 2 Remastered"),
    Path(r"F:\SteamLibrary\steamapps\common\BioShock 2 Remastered"),
    Path(r"G:\SteamLibrary\steamapps\common\BioShock 2 Remastered"),
    Path(r"X:\SteamLibrary\steamapps\common\BioShock 2 Remastered"),
    Path(r"C:\Program Files (x86)\GOG Galaxy\Games\BioShock 2 Remastered"),
    Path(r"C:\GOG Games\BioShock 2 Remastered"),
    Path(r"D:\GOG Games\BioShock 2 Remastered"),
    Path(r"C:\Program Files\Epic Games\BioShock2Remastered"),
    Path(r"D:\Epic Games\BioShock2Remastered"),
]

def _load_settings():
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

def _detect_game_root():
    settings = _load_settings()
    saved = settings.get('game_root')
    if saved and Path(saved).exists() and (Path(saved) / 'ContentBaked' / 'pc' / 'Maps').exists():
        return Path(saved)
    for p in _GAME_SEARCH_PATHS:
        if p.exists() and (p / 'ContentBaked' / 'pc' / 'Maps').exists():
            settings['game_root'] = str(p)
            _save_settings(settings)
            return p
    return DEFAULT_GAME_ROOT

GAME_ROOT = _detect_game_root()
CONTENT_DIR = GAME_ROOT / "ContentBaked" / "pc"
MAPS_DIR = CONTENT_DIR / "Maps"
PRISTINE_DIR = BIOMOD_DIR / "backups" / "pristine"
LOG_DIR = BIOMOD_DIR / "logs"

def _update_game_root(new_root):
    global GAME_ROOT, CONTENT_DIR, MAPS_DIR
    GAME_ROOT = Path(new_root)
    CONTENT_DIR = GAME_ROOT / "ContentBaked" / "pc"
    MAPS_DIR = CONTENT_DIR / "Maps"
    settings = _load_settings()
    settings['game_root'] = str(GAME_ROOT)
    _save_settings(settings)

SKIP_MAPS = ('Entry',)

MAP_NAMES = {
    'Abyss':               'Fontaine Futuristics',
    'Eden':                'Inner Persephone',
    'Eden_CellBlock':      'Persephone - Cell Block',
    'Education':           'Ryan Amusements',
    'Gallery':             'Dionysus Park',
    'GalleryCarousel':     'Dionysus Park - Carousel',
    'Ghetto':              "Pauper's Drop",
    'GhettoMarket':        "Pauper's Drop - Market",
    'Gulag':               'Outer Persephone',
    'Minerva_A':           "Minerva's Den - A",
    'Minerva_B':           "Minerva's Den - B",
    'Minerva_C':           "Minerva's Den - C",
    'Prelude-2':           'Adonis Luxury Resort',
    'PreludePool':         'Adonis - Pool',
    'Redlight':            'Siren Alley',
    'RedlightChurch':      'Siren Alley - Church',
    'WelcomeBack':         'Atlantic Express',
    'WelcomeBackMaintenance': 'Atlantic Express - Maintenance',
}


def find_map_files():
    files = []
    if not MAPS_DIR.exists():
        return files
    for f in sorted(MAPS_DIR.glob("*.bsm")):
        name = f.stem
        if any(name.startswith(s) for s in SKIP_MAPS):
            continue
        # Skip language suffixes
        if any(name.endswith(sfx) for sfx in ('_chn', '_deu', '_esp', '_fra',
                                                '_ita', '_jpn', '_kor', '_int')):
            continue
        files.append(f)
    return files


class StdoutRedirector:
    def __init__(self, msg_queue):
        self.queue = msg_queue
    def write(self, text):
        if text:
            self.queue.put(text)
    def flush(self):
        pass


# ─── Scrollable Frame helper ────────────────────────────────────────────────

def make_scrollable(parent):
    canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0, bg='#1e1e2e')
    scrollbar = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
    inner = ttk.Frame(canvas)
    inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.create_window((0, 0), window=inner, anchor='nw')
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side='left', fill='both', expand=True)
    scrollbar.pack(side='right', fill='y')

    def _on_mousewheel(event):
        try:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except tk.TclError:
            pass
    canvas.bind_all('<MouseWheel>', _on_mousewheel, add='+')
    canvas.bind('<Destroy>', lambda e: canvas.unbind_all('<MouseWheel>'), add='+')
    return canvas, inner


# ─── Main UI ─────────────────────────────────────────────────────────────────

class SpawnModManager:
    def __init__(self, root):
        self.root = root
        self.root.title("The War In Rapture \u2014 BioShock 2 Remastered Mod Manager")
        self.root.geometry("1050x900")
        self.root.minsize(900, 700)

        self.msg_queue = queue.Queue()
        self.working = False
        self.map_files = find_map_files()

        # Data populated by background analysis
        self.map_data = {}       # stem -> {spawner_counts}

        # Repopulation spawner multipliers
        self.spawner_vars = {}   # stem -> IntVar

        # INI config data (loaded in background)
        self.ini_configs = None
        self.ini_raw_files = None

        # Damage data
        self.damage_data = {}    # section -> {friendly, stimuli_vars}

        # Loot data
        self._loot_tables = {}
        self._loot_vars = {}

        # Encounter data
        self.encounter_data = {}   # stem -> {label: {spawns, ai_types}}
        self.encounter_mults = {}  # stem -> {label: IntVar}
        self.selected_map = None

        # Enemy health multipliers
        self.enemy_health_vars = {}  # set_name -> DoubleVar

        # Extras checkboxes
        self.extras_vars = {}      # key -> BooleanVar

        # File logger (opened during apply/restore)
        self._file_logger = None
        self._log_path = None

        self._build_ui()
        self._ensure_backups()
        self._poll_queue()
        self._start_analysis()

    # ══════════════════════════════════════════════════════════════════════
    # UI CONSTRUCTION
    # ══════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        BG       = '#1e1e2e'
        BG2      = '#252536'
        BG3      = '#2e2e42'
        FG       = '#cdd6f4'
        FG_DIM   = '#7f849c'
        FG_HEAD  = '#89b4fa'
        FG_TITLE = '#cba6f7'
        BORDER   = '#45475a'
        SELECT   = '#45475a'
        ACCENT   = '#89b4fa'
        ACCENT_FG= '#1e1e2e'
        TAB_BG   = '#313244'
        TAB_SEL  = '#45475a'

        self.root.configure(bg=BG)

        style = ttk.Style()
        style.theme_use('clam')

        style.configure('.', background=BG, foreground=FG, bordercolor=BORDER,
                        font=('Segoe UI', 9))
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=FG)
        style.configure('TLabelframe', background=BG, foreground=FG,
                        bordercolor=BORDER)
        style.configure('TLabelframe.Label', background=BG, foreground=FG_HEAD,
                        font=('Segoe UI', 10, 'bold'))
        style.configure('TNotebook', background=BG, bordercolor=BORDER)
        style.configure('TNotebook.Tab', background=TAB_BG, foreground=FG_DIM,
                        padding=[12, 4], font=('Segoe UI', 9))
        style.map('TNotebook.Tab',
                  background=[('selected', TAB_SEL)],
                  foreground=[('selected', FG)])
        style.configure('TButton', background=ACCENT, foreground=ACCENT_FG,
                        bordercolor=BORDER, focuscolor=ACCENT,
                        font=('Segoe UI', 9, 'bold'), padding=[8, 3])
        style.map('TButton',
                  background=[('active', '#a6d0fb'), ('disabled', '#45475a')],
                  foreground=[('disabled', '#585b70')])
        style.configure('TEntry', fieldbackground=BG3, foreground=FG,
                        insertcolor=FG, bordercolor=BORDER)
        style.configure('TSpinbox', fieldbackground=BG3, foreground=FG,
                        arrowcolor=FG_DIM, bordercolor=BORDER)
        style.configure('TCombobox', fieldbackground=BG3, foreground=FG,
                        arrowcolor=FG_DIM, bordercolor=BORDER)
        style.map('TCombobox', fieldbackground=[('readonly', BG3)])
        style.configure('TScrollbar', background=BG2, troughcolor=BG,
                        bordercolor=BORDER, arrowcolor=FG_DIM)
        style.configure('TSeparator', background=BORDER)
        style.configure('TCheckbutton', background=BG, foreground=FG)
        style.configure('Extras.TCheckbutton', background=BG, foreground=FG,
                        font=('Segoe UI', 9, 'bold'))

        self.root.option_add('*TCombobox*Listbox.background', BG3)
        self.root.option_add('*TCombobox*Listbox.foreground', FG)
        self.root.option_add('*TCombobox*Listbox.selectBackground', SELECT)
        self.root.option_add('*TCombobox*Listbox.selectForeground', FG)

        style.configure('Title.TLabel', font=('Segoe UI', 14, 'bold'),
                        foreground=FG_TITLE, background=BG)
        style.configure('Section.TLabelframe.Label', font=('Segoe UI', 10, 'bold'),
                        foreground=FG_HEAD, background=BG)
        style.configure('Header.TLabel', font=('Segoe UI', 9, 'bold'),
                        foreground=FG_HEAD, background=BG)
        style.configure('Small.TLabel', font=('Segoe UI', 8),
                        foreground=FG_DIM, background=BG)
        style.configure('MapName.TLabel', font=('Segoe UI', 11, 'bold'),
                        foreground=FG_TITLE, background=BG)
        style.configure('WeaponName.TLabel', font=('Segoe UI', 10, 'bold'),
                        foreground=FG_HEAD, background=BG)

        self._colors = {
            'bg': BG, 'bg2': BG2, 'bg3': BG3, 'fg': FG, 'fg_dim': FG_DIM,
            'accent': ACCENT, 'border': BORDER, 'select': SELECT,
        }

        main = ttk.Frame(self.root, padding=10)
        main.pack(fill='both', expand=True)

        # Title
        ttk.Label(main, text="The War In Rapture \u2014 BioShock 2 Remastered",
                  style='Title.TLabel').pack(pady=(0, 6))

        # Notebook (tabs)
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill='both', expand=True, pady=(0, 6))

        self._build_encounters_tab()
        self._build_repopulation_tab()
        self._build_damage_tab()
        self._build_loot_tab()
        self._build_difficulty_tab()
        self._build_vending_tab()
        self._build_enemy_health_tab()
        self._build_extras_tab()

        # Buttons + Status
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill='x', pady=(0, 4))

        self.apply_btn = ttk.Button(btn_frame, text="  Apply Mod  ",
                                    command=self._apply_mod)
        self.apply_btn.pack(side='left', padx=(0, 8))

        self.restore_btn = ttk.Button(btn_frame, text="  Restore All  ",
                                      command=self._restore_all)
        self.restore_btn.pack(side='left', padx=(0, 8))

        ttk.Button(btn_frame, text="  Game Dir  ",
                   command=self._change_game_dir).pack(side='left', padx=(0, 8))

        ttk.Separator(btn_frame, orient='vertical').pack(side='left', fill='y',
                                                          padx=(0, 8), pady=2)
        ttk.Button(btn_frame, text="  Save Preset  ",
                   command=self._save_preset).pack(side='left', padx=(0, 4))
        ttk.Button(btn_frame, text="  Load Preset  ",
                   command=self._load_preset).pack(side='left', padx=(0, 4))

        ttk.Separator(btn_frame, orient='vertical').pack(side='left', fill='y',
                                                          padx=(4, 8), pady=2)
        self.export_btn = ttk.Button(btn_frame, text="  Export Installer  ",
                                     command=self._export_installer)
        self.export_btn.pack(side='left', padx=(0, 4))

        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(btn_frame, textvariable=self.status_var,
                                      foreground='#a6e3a1', font=('Segoe UI', 10))
        self.status_label.pack(side='right')

        # Game path label
        self.game_path_var = tk.StringVar(value=str(GAME_ROOT))
        ttk.Label(main, textvariable=self.game_path_var,
                  foreground='#6c7086', font=('Consolas', 8)).pack(anchor='w')

        # Log
        log_lf = ttk.LabelFrame(main, text="  Log  ", padding=4)
        log_lf.pack(fill='x')

        self.log_text = tk.Text(log_lf, height=7, state='disabled',
                                font=('Consolas', 9), wrap='word',
                                bg='#11111b', fg='#a6adc8',
                                insertbackground='#cdd6f4',
                                selectbackground='#45475a',
                                borderwidth=0, highlightthickness=0)
        log_scroll = ttk.Scrollbar(log_lf, orient='vertical', command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side='left', fill='both', expand=True)
        log_scroll.pack(side='right', fill='y')

    # ── TAB 0: Encounters ──────────────────────────────────────────────

    def _build_encounters_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text='  Encounters  ')

        ttk.Label(tab, text=(
            "Scripted encounter spawns \u2014 one-time enemies triggered by entering "
            "areas or story events.  Use the multiplier to duplicate existing spawns.  "
            "Requires a fresh level load (new game or level transition)."),
            foreground='#7f849c', wraplength=900).pack(anchor='w', pady=(0, 6))

        # Global encounter multiplier
        gm = ttk.LabelFrame(tab, text="  Global Encounter Multiplier  ",
                             style='Section.TLabelframe', padding=6)
        gm.pack(fill='x', pady=(0, 6))

        gm_inner = ttk.Frame(gm)
        gm_inner.pack(fill='x')

        self.all_encounter_var = tk.IntVar(value=1)
        ttk.Label(gm_inner, text="All Encounters:").pack(side='left')
        ttk.Spinbox(gm_inner, from_=1, to=10, width=4,
                    textvariable=self.all_encounter_var).pack(side='left', padx=4)
        ttk.Label(gm_inner, text="x").pack(side='left')
        ttk.Button(gm_inner, text="  Apply to All  ",
                   command=self._set_all_encounters).pack(side='left', padx=(8, 0))
        ttk.Label(gm_inner, text="(sets every level and encounter to this value)",
                  foreground='#6c7086', font=('Segoe UI', 8)).pack(side='left', padx=8)

        # Split: level list (left) + detail (right)
        split = ttk.Frame(tab)
        split.pack(fill='both', expand=True)

        # Left: Level listbox
        left = ttk.LabelFrame(split, text="  Levels  ", padding=4)
        left.pack(side='left', fill='y', padx=(0, 6))

        self.enc_level_listbox = tk.Listbox(
            left, width=28, font=('Segoe UI', 9),
            bg='#11111b', fg='#cdd6f4', selectbackground='#45475a',
            selectforeground='#cdd6f4', highlightthickness=0,
            borderwidth=0, exportselection=False)
        self.enc_level_listbox.pack(fill='both', expand=True)
        self.enc_level_listbox.bind('<<ListboxSelect>>', self._on_enc_level_select)

        # Right: Encounter detail
        right = ttk.LabelFrame(split, text="  Level Details  ", padding=4)
        right.pack(side='left', fill='both', expand=True)

        self.enc_detail_frame = ttk.Frame(right)
        self.enc_detail_frame.pack(fill='both', expand=True)
        self.enc_detail_placeholder = ttk.Label(
            self.enc_detail_frame,
            text="Select a level to view encounters.",
            foreground='#6c7086', font=('Segoe UI', 10))
        self.enc_detail_placeholder.pack(expand=True)

    def _populate_encounters_tab(self):
        """Populate the level listbox with maps that have encounters."""
        self.enc_level_listbox.delete(0, tk.END)
        # Use the current global multiplier so late-populating maps
        # inherit any value the user already set via 'Apply to All'
        try:
            global_val = self.all_encounter_var.get()
        except Exception:
            global_val = 1
        for f in self.map_files:
            stem = f.stem
            enc = self.encounter_data.get(stem, {})
            if not enc:
                continue
            # Pre-create IntVars for every encounter so Apply-to-All works
            if stem not in self.encounter_mults:
                self.encounter_mults[stem] = {}
            for label in enc:
                if label not in self.encounter_mults[stem]:
                    self.encounter_mults[stem][label] = tk.IntVar(value=global_val)
            display = MAP_NAMES.get(stem, stem)
            n = sum(e['spawns'] for e in enc.values())
            self.enc_level_listbox.insert(tk.END, "%s (%d)" % (display, n))

    def _on_enc_level_select(self, event=None):
        sel = self.enc_level_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        # Map idx back to stem
        counter = 0
        for f in self.map_files:
            stem = f.stem
            enc = self.encounter_data.get(stem, {})
            if not enc:
                continue
            if counter == idx:
                self.selected_map = stem
                self._refresh_enc_detail()
                return
            counter += 1

    def _refresh_enc_detail(self):
        """Rebuild the encounter detail panel for the selected map."""
        for w in self.enc_detail_frame.winfo_children():
            w.destroy()

        stem = self.selected_map
        if not stem or stem not in self.encounter_data:
            ttk.Label(self.enc_detail_frame, text="No encounters.",
                      foreground='#6c7086').pack()
            return

        enc = self.encounter_data[stem]
        display = MAP_NAMES.get(stem, stem)

        # Header
        top = ttk.Frame(self.enc_detail_frame)
        top.pack(fill='x', pady=(0, 6))
        ttk.Label(top, text=display, style='MapName.TLabel').pack(side='left')

        # Level-wide multiplier
        self._level_enc_var = tk.IntVar(value=1)
        ttk.Label(top, text="   Level Multiplier:").pack(side='left', padx=(16, 0))
        ttk.Spinbox(top, from_=1, to=10, width=4,
                    textvariable=self._level_enc_var).pack(side='left', padx=4)
        ttk.Label(top, text="x").pack(side='left')
        ttk.Button(top, text=" Apply to Level ",
                   command=lambda: self._set_level_encounters(stem)).pack(side='left', padx=4)

        # Scrollable encounter list
        canvas, inner = make_scrollable(self.enc_detail_frame)

        # Headers
        ttk.Label(inner, text="Encounter", style='Header.TLabel', width=30).grid(
            row=0, column=0, sticky='w', padx=(2, 8))
        ttk.Label(inner, text="Original Spawns", style='Header.TLabel').grid(
            row=0, column=1, sticky='w', padx=4)
        ttk.Label(inner, text="Mult", style='Header.TLabel', width=6).grid(
            row=0, column=2, sticky='w', padx=4)
        ttk.Separator(inner, orient='horizontal').grid(
            row=1, column=0, columnspan=3, sticky='ew', pady=2)

        if stem not in self.encounter_mults:
            self.encounter_mults[stem] = {}

        try:
            global_val = self.all_encounter_var.get()
        except Exception:
            global_val = 1

        r = 2
        for label, info in sorted(enc.items()):
            if label not in self.encounter_mults[stem]:
                self.encounter_mults[stem][label] = tk.IntVar(value=global_val)

            # Truncate long labels
            disp_label = label[:40] + '...' if len(label) > 40 else label
            ttk.Label(inner, text=disp_label, font=('Segoe UI', 9, 'bold')).grid(
                row=r, column=0, sticky='w', padx=(2, 8), pady=2)

            # Show spawn count and AI types
            ai_summary = ', '.join(sorted(set(info['ai_types'])))
            spawn_text = "%d: %s" % (info['spawns'], ai_summary)
            ttk.Label(inner, text=spawn_text, foreground='#7f849c',
                      font=('Segoe UI', 8), wraplength=300).grid(
                row=r, column=1, sticky='w', padx=4, pady=2)

            ttk.Spinbox(inner, from_=1, to=10, width=4,
                        textvariable=self.encounter_mults[stem][label]).grid(
                row=r, column=2, sticky='w', padx=4, pady=2)
            r += 1

    def _set_all_encounters(self):
        v = self.all_encounter_var.get()
        for stem, mults in self.encounter_mults.items():
            for label, var in mults.items():
                var.set(v)

    def _set_level_encounters(self, stem):
        v = self._level_enc_var.get()
        if stem in self.encounter_mults:
            for label, var in self.encounter_mults[stem].items():
                var.set(v)

    # ── TAB 1: Repopulation ──────────────────────────────────────────────

    def _build_repopulation_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text='  Repopulation  ')

        ttk.Label(tab, text=(
            "Repopulation spawners are fixed points in each level where enemies "
            "continuously respawn after being killed, as long as the player is far "
            "enough away.  Each spawner = one spawn point.  The multiplier duplicates "
            "these physical points to increase the number of enemies that can respawn.\n\n"
            "Aggressors: Splicers   |   "
            "Protectors: Big Daddies (Bouncers, Rosies)   |   "
            "Placed: Pre-positioned enemies (Brutes, etc.)"),
            foreground='#7f849c', wraplength=900).pack(anchor='w', pady=(0, 6))

        # Set-all control
        sp = ttk.LabelFrame(tab, text="  Spawner Duplication  ",
                            style='Section.TLabelframe', padding=6)
        sp.pack(fill='both', expand=True, pady=(0, 6))
        ttk.Label(sp, text="Per-level multiplier for repopulation spawner actors.  "
                  "Set to 1 for vanilla spawn density.",
                  foreground='#7f849c', wraplength=800).pack(anchor='w', pady=(0, 4))

        sa_frame = ttk.Frame(sp)
        sa_frame.pack(fill='x', pady=(0, 6))
        self.all_spawner_var = tk.IntVar(value=1)
        ttk.Label(sa_frame, text="All Levels:", font=('Segoe UI', 9, 'bold')).pack(side='left')
        ttk.Spinbox(sa_frame, from_=1, to=10, width=4,
                    textvariable=self.all_spawner_var).pack(side='left', padx=4)
        ttk.Label(sa_frame, text="x").pack(side='left')
        ttk.Button(sa_frame, text="  Set All  ", width=8,
                   command=self._set_all_spawners).pack(side='left', padx=(8, 0))

        # Per-level spawner list (scrollable)
        canvas, inner = make_scrollable(sp)
        self._repop_inner = inner

        ttk.Label(inner, text="Level", style='Header.TLabel', width=28).grid(
            row=0, column=0, sticky='w', padx=(2, 8))
        ttk.Label(inner, text="Aggressors", style='Header.TLabel', width=10).grid(
            row=0, column=1, sticky='w', padx=4)
        ttk.Label(inner, text="Protectors", style='Header.TLabel', width=10).grid(
            row=0, column=2, sticky='w', padx=4)
        ttk.Label(inner, text="Placed", style='Header.TLabel', width=10).grid(
            row=0, column=3, sticky='w', padx=4)
        ttk.Label(inner, text="Multiplier", style='Header.TLabel', width=8).grid(
            row=0, column=4, sticky='w', padx=4)
        ttk.Separator(inner, orient='horizontal').grid(
            row=1, column=0, columnspan=5, sticky='ew', pady=2)

        self._repop_rows_start = 2

        # Initialize vars for all maps
        for f in self.map_files:
            stem = f.stem
            self.spawner_vars[stem] = tk.IntVar(value=1)

        # ── Gather Defense section ──
        gd = ttk.LabelFrame(tab, text="  Gather Defense  ",
                            style='Section.TLabelframe', padding=6)
        gd.pack(fill='x', pady=(0, 6))
        ttk.Label(gd, text=(
            "When defending a Little Sister during ADAM gathering, waves of "
            "enemies attack.  This multiplier increases the maximum number of "
            "enemies each wave can spawn concurrently.  Set to 1 for vanilla."),
            foreground='#7f849c', wraplength=800).pack(anchor='w', pady=(0, 4))

        gd_frame = ttk.Frame(gd)
        gd_frame.pack(fill='x')
        self.gather_defense_var = tk.IntVar(value=1)
        ttk.Label(gd_frame, text="Wave Intensity:",
                  font=('Segoe UI', 9, 'bold')).pack(side='left')
        ttk.Spinbox(gd_frame, from_=1, to=10, width=4,
                    textvariable=self.gather_defense_var).pack(side='left', padx=4)
        ttk.Label(gd_frame, text="x").pack(side='left')

    def _populate_repop_rows(self):
        inner = self._repop_inner
        r = self._repop_rows_start
        for f in self.map_files:
            stem = f.stem
            display = MAP_NAMES.get(stem, stem)
            data = self.map_data.get(stem, {})
            counts = data.get('spawner_counts', {})
            ag = counts.get('AggressorSpawner', 0)
            pr = counts.get('ProtectorSpawner', 0)
            # Sum placed enemy counts (any class not in SPAWNER_CLASSES)
            from core.bsm_spawn_patcher import SPAWNER_CLASSES
            pl = sum(v for k, v in counts.items() if k not in SPAWNER_CLASSES)

            if ag + pr + pl == 0:
                continue  # Skip maps with no spawners

            ttk.Label(inner, text=display, font=('Segoe UI', 9)).grid(
                row=r, column=0, sticky='w', padx=(2, 8), pady=2)
            ttk.Label(inner, text=str(ag)).grid(row=r, column=1, sticky='w', padx=4)
            ttk.Label(inner, text=str(pr)).grid(row=r, column=2, sticky='w', padx=4)
            ttk.Label(inner, text=str(pl)).grid(row=r, column=3, sticky='w', padx=4)
            ttk.Spinbox(inner, from_=1, to=10, width=4,
                        textvariable=self.spawner_vars[stem]).grid(
                row=r, column=4, sticky='w', padx=4, pady=2)
            r += 1

    # ── TAB 2: Damage ────────────────────────────────────────────────────

    def _build_damage_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text='  Damage  ')

        ttk.Label(tab, text=(
            "Adjust weapon and plasmid damage values.  These come from DamageSets.ini "
            "stimuli sets.  Each weapon/plasmid can have multiple stimulus types "
            "(e.g. piercing, explosive, electric).  The primary damage amount is "
            "shown for each."),
            foreground='#7f849c', wraplength=900).pack(anchor='w', pady=(0, 6))

        self.damage_inner_frame = ttk.Frame(tab)
        self.damage_inner_frame.pack(fill='both', expand=True)

        self.damage_placeholder = ttk.Label(self.damage_inner_frame,
            text="Loading damage data...", foreground='#6c7086', font=('Segoe UI', 10))
        self.damage_placeholder.pack(expand=True)

    def _populate_damage_tab(self):
        for w in self.damage_inner_frame.winfo_children():
            w.destroy()

        if not self.ini_configs or 'DamageSets.ini' not in self.ini_configs:
            ttk.Label(self.damage_inner_frame,
                      text="DamageSets.ini not found", foreground='#f38ba8').pack()
            return

        from core.ini_config import read_damage_sets
        dsets = read_damage_sets(self.ini_configs['DamageSets.ini'])

        canvas, inner = make_scrollable(self.damage_inner_frame)

        # Group by category
        categories = [
            ('Drill',           [s for s in dsets if 'Drill' in s]),
            ('Rivet Gun',       [s for s in dsets if 'Rivet' in s]),
            ('Machine Gun',     [s for s in dsets if 'MachineGun' in s]),
            ('Shotgun',         [s for s in dsets if any(k in s for k in ['Buck', 'Phosphorus', 'SolidSlug'])]),
            ('Spear Gun',       [s for s in dsets if 'Spear' in s and 'Laser' not in s]),
            ('Grenade Launcher',[s for s in dsets if any(k in s for k in ['Grenade', 'Prox', 'Sticky', 'RPG'])]),
            ('Research Camera', [s for s in dsets if 'LaserGun' in s]),
            ('Hack Tool',       [s for s in dsets if 'Hacking' in s]),
            ('Electro Bolt',    [s for s in dsets if 'ElectroBolt' in s]),
            ('Incinerate',      [s for s in dsets if 'Incinerate' in s]),
            ('Winter Blast',    [s for s in dsets if 'WinterBlast' in s]),
            ('Telekinesis',     [s for s in dsets if 'Telekinesis' in s]),
            ('Cyclone Trap',    [s for s in dsets if 'Cyclone' in s]),
            ('Insect Swarm',    [s for s in dsets if 'InsectSwarm' in s]),
            ('Scout',           [s for s in dsets if 'Scout' in s]),
            ('Security',        [s for s in dsets if any(k in s for k in ['AutoTurret', 'BotLaser', 'MasterBot'])]),
        ]

        row = 0
        for cat_name, sections in categories:
            if not sections:
                continue

            ttk.Label(inner, text=cat_name, style='WeaponName.TLabel').grid(
                row=row, column=0, columnspan=4, sticky='w', pady=(10, 2))
            row += 1

            ttk.Label(inner, text="Variant", style='Header.TLabel').grid(
                row=row, column=0, sticky='w', padx=(10, 8))
            ttk.Label(inner, text="Stimulus Type", style='Header.TLabel').grid(
                row=row, column=1, sticky='w', padx=4)
            ttk.Label(inner, text="Amount", style='Header.TLabel').grid(
                row=row, column=2, sticky='w', padx=4)
            ttk.Separator(inner, orient='horizontal').grid(
                row=row + 1, column=0, columnspan=4, sticky='ew', pady=2)
            row += 2

            for sec_name in sections:
                info = dsets[sec_name]
                friendly = info['friendly']

                for si, stim in enumerate(info['stimuli']):
                    label = friendly if si == 0 else ''
                    ttk.Label(inner, text=label, font=('Segoe UI', 9, 'bold') if si == 0 else ('Segoe UI', 9)).grid(
                        row=row, column=0, sticky='w', padx=(10, 8), pady=1)

                    stim_short = stim['type'].replace('STIMULUS_', '')
                    ttk.Label(inner, text=stim_short, foreground='#7f849c',
                              font=('Segoe UI', 8)).grid(
                        row=row, column=1, sticky='w', padx=4, pady=1)

                    amt_var = tk.StringVar(value=str(stim['amount']))
                    ttk.Entry(inner, textvariable=amt_var, width=7,
                              font=('Segoe UI', 9)).grid(
                        row=row, column=2, padx=4, pady=1)

                    # Store for apply
                    key = (sec_name, si)
                    self.damage_data[key] = {
                        'section': sec_name,
                        'stim_idx': si,
                        'type': stim['type'],
                        'amount': amt_var,
                        'orig_amount': stim['amount'],
                    }
                    row += 1

    # ── TAB 3: Loot ──────────────────────────────────────────────────────

    def _build_loot_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text='  Loot  ')

        ttk.Label(tab, text=(
            "Adjust enemy loot drop rates and stack sizes.  Each enemy type has "
            "multiple loot tiers (A, B, C) with different drop tables."),
            foreground='#7f849c', wraplength=900).pack(anchor='w', pady=(0, 6))

        self.loot_inner_frame = ttk.Frame(tab)
        self.loot_inner_frame.pack(fill='both', expand=True)

        self.loot_placeholder = ttk.Label(self.loot_inner_frame,
            text="Loading loot data...", foreground='#6c7086', font=('Segoe UI', 10))
        self.loot_placeholder.pack(expand=True)

    def _populate_loot_tab(self):
        for w in self.loot_inner_frame.winfo_children():
            w.destroy()

        if not self.ini_configs or 'LootTables_perobjectconfig.ini' not in self.ini_configs:
            ttk.Label(self.loot_inner_frame,
                      text="LootTables_perobjectconfig.ini not found",
                      foreground='#f38ba8').pack()
            return

        from core.ini_config import read_loot_tables, ENEMY_LOOT_GROUPS, loot_item_friendly

        all_loot = read_loot_tables(self.ini_configs['LootTables_perobjectconfig.ini'])

        # Group selector
        top = ttk.Frame(self.loot_inner_frame)
        top.pack(fill='x', pady=(0, 6))

        ttk.Label(top, text="Enemy Type:", font=('Segoe UI', 9, 'bold')).pack(side='left')
        self.loot_group_var = tk.StringVar()
        group_names = list(ENEMY_LOOT_GROUPS.keys())
        if group_names:
            self.loot_group_var.set(group_names[0])
        group_combo = ttk.Combobox(top, textvariable=self.loot_group_var,
                                   values=group_names, state='readonly', width=30)
        group_combo.pack(side='left', padx=6)
        group_combo.bind('<<ComboboxSelected>>',
                         lambda e: self._refresh_loot_detail())

        # Chance multiplier shortcut
        ttk.Label(top, text="  Drop Chance Scale:", font=('Segoe UI', 8)).pack(side='left')
        self.loot_scale_var = tk.StringVar(value="1.0")
        ttk.Entry(top, textvariable=self.loot_scale_var, width=5).pack(side='left', padx=2)
        ttk.Button(top, text="Scale All", command=self._scale_loot).pack(side='left', padx=4)

        # Detail frame
        self.loot_detail = ttk.Frame(self.loot_inner_frame)
        self.loot_detail.pack(fill='both', expand=True)

        self._all_loot = all_loot
        if group_names:
            self._refresh_loot_detail()

    def _refresh_loot_detail(self):
        for w in self.loot_detail.winfo_children():
            w.destroy()

        from core.ini_config import ENEMY_LOOT_GROUPS, loot_item_friendly, LOOT_ITEMS

        group_name = self.loot_group_var.get()
        sections = ENEMY_LOOT_GROUPS.get(group_name, [])
        if not sections:
            ttk.Label(self.loot_detail, text="No loot tables for this group.",
                      foreground='#6c7086').pack()
            return

        item_choices = sorted(set(LOOT_ITEMS.values()))
        canvas, inner = make_scrollable(self.loot_detail)

        row = 0
        self._loot_vars[group_name] = {}

        for sec_name in sections:
            specs = self._all_loot.get(sec_name, [])
            if not specs:
                continue

            # Tier label (e.g. "Pistol Splicer - Tier A")
            tier_label = sec_name.rsplit('_', 1)[-1] if '_' in sec_name else sec_name
            ttk.Label(inner, text="%s (Tier %s)" % (sec_name, tier_label),
                      font=('Segoe UI', 9, 'bold')).grid(
                row=row, column=0, columnspan=5, sticky='w', pady=(8, 2))
            row += 1

            # Headers
            for c, h in enumerate(['Item', 'Chance%', 'Min', 'Max']):
                ttk.Label(inner, text=h, style='Header.TLabel').grid(
                    row=row, column=c, sticky='w', padx=(10 if c == 0 else 4, 4))
            row += 1

            table_vars = []
            for spec in specs:
                if spec.get('table_name'):
                    friendly = 'Table: %s' % spec['table_name']
                else:
                    friendly = loot_item_friendly(spec['item'])

                item_var = tk.StringVar(value=friendly)
                ttk.Combobox(inner, textvariable=item_var, values=item_choices,
                             width=18, font=('Segoe UI', 8)).grid(
                    row=row, column=0, sticky='w', padx=(10, 4), pady=1)

                chance_var = tk.StringVar(value=str(spec['chance']))
                ttk.Entry(inner, textvariable=chance_var, width=5,
                          font=('Segoe UI', 9)).grid(row=row, column=1, padx=4, pady=1)

                min_var = tk.StringVar(value=str(spec['min_stack']))
                ttk.Entry(inner, textvariable=min_var, width=4,
                          font=('Segoe UI', 9)).grid(row=row, column=2, padx=4, pady=1)

                max_var = tk.StringVar(value=str(spec['max_stack']))
                ttk.Entry(inner, textvariable=max_var, width=4,
                          font=('Segoe UI', 9)).grid(row=row, column=3, padx=4, pady=1)

                table_vars.append({
                    'item': item_var, 'chance': chance_var,
                    'min': min_var, 'max': max_var,
                    'table_name': spec.get('table_name', ''),
                    'orig_item': spec['item'],
                })
                row += 1

            self._loot_vars[group_name][sec_name] = table_vars

    def _scale_loot(self):
        try:
            scale = float(self.loot_scale_var.get())
        except ValueError:
            return
        group_name = self.loot_group_var.get()
        if group_name not in self._loot_vars:
            return
        for sec_name, table_vars in self._loot_vars[group_name].items():
            for sv in table_vars:
                if sv['item'].get() in ('Nothing', 'None', '') or sv.get('table_name'):
                    continue
                try:
                    old = int(sv['chance'].get())
                    new = min(100, max(1, int(old * scale)))
                    sv['chance'].set(str(new))
                except ValueError:
                    pass

    # ── TAB 4: Difficulty ────────────────────────────────────────────────

    def _build_difficulty_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text='  Difficulty  ')

        ttk.Label(tab, text=(
            "Difficulty scaling controls how the game's adaptive difficulty adjusts "
            "loot drops, enemy damage, and resource availability based on player "
            "performance.  The Damage Multiplier Set controls headshot and per-region "
            "damage bonuses."),
            foreground='#7f849c', wraplength=900).pack(anchor='w', pady=(0, 6))

        # Damage multiplier section
        dm_frame = ttk.LabelFrame(tab, text="  Damage Region Multipliers  ",
                                   style='Section.TLabelframe', padding=6)
        dm_frame.pack(fill='both', expand=True, pady=(0, 6))

        self.dm_inner_frame = ttk.Frame(dm_frame)
        self.dm_inner_frame.pack(fill='both', expand=True)

        self.dm_placeholder = ttk.Label(self.dm_inner_frame,
            text="Loading difficulty data...", foreground='#6c7086', font=('Segoe UI', 10))
        self.dm_placeholder.pack(expand=True)

        self.dm_data = {}

    def _populate_difficulty_tab(self):
        for w in self.dm_inner_frame.winfo_children():
            w.destroy()

        if not self.ini_configs or 'DamageMultiplierSet.ini' not in self.ini_configs:
            ttk.Label(self.dm_inner_frame,
                      text="DamageMultiplierSet.ini not found",
                      foreground='#f38ba8').pack()
            return

        entries = self.ini_configs['DamageMultiplierSet.ini']

        # Parse all Multipliers entries grouped by section
        import re
        sections = {}
        for s, k, v, r in entries:
            if k == 'Multipliers':
                if s not in sections:
                    sections[s] = []
                m = re.match(r'\((.+)\)', v.strip())
                if m:
                    inner = m.group(1)
                    region = ''
                    stimuli = ''
                    mult = 1.0
                    rm = re.search(r'DamageRegion\s*=\s*(\w+)', inner)
                    if rm:
                        region = rm.group(1).replace('REGION_', '')
                    sm = re.search(r'StimuliSetName\s*=\s*(\w+)', inner)
                    if sm:
                        stimuli = sm.group(1)
                    mm = re.search(r'Multiplier\s*=\s*([0-9.]+)', inner)
                    if mm:
                        mult = float(mm.group(1))
                    sections[s].append({
                        'region': region, 'stimuli': stimuli,
                        'multiplier': mult, 'raw': v
                    })

        canvas, inner = make_scrollable(self.dm_inner_frame)

        row = 0
        for sec_name, mults in sections.items():
            ttk.Label(inner, text=sec_name, style='WeaponName.TLabel').grid(
                row=row, column=0, columnspan=4, sticky='w', pady=(10, 2))
            row += 1

            ttk.Label(inner, text="Region", style='Header.TLabel').grid(
                row=row, column=0, sticky='w', padx=(10, 8))
            ttk.Label(inner, text="Stimuli Set", style='Header.TLabel').grid(
                row=row, column=1, sticky='w', padx=4)
            ttk.Label(inner, text="Multiplier", style='Header.TLabel').grid(
                row=row, column=2, sticky='w', padx=4)
            ttk.Separator(inner, orient='horizontal').grid(
                row=row + 1, column=0, columnspan=4, sticky='ew', pady=2)
            row += 2

            for mi, mdata in enumerate(mults):
                from core.ini_config import WEAPON_STIMULI
                stim_friendly = WEAPON_STIMULI.get(mdata['stimuli'], mdata['stimuli'])

                ttk.Label(inner, text=mdata['region']).grid(
                    row=row, column=0, sticky='w', padx=(10, 8), pady=1)
                ttk.Label(inner, text=stim_friendly, foreground='#7f849c',
                          font=('Segoe UI', 8)).grid(
                    row=row, column=1, sticky='w', padx=4, pady=1)

                mult_var = tk.StringVar(value=str(mdata['multiplier']))
                ttk.Entry(inner, textvariable=mult_var, width=6,
                          font=('Segoe UI', 9)).grid(
                    row=row, column=2, padx=4, pady=1)

                key = (sec_name, mi)
                self.dm_data[key] = {
                    'section': sec_name,
                    'idx': mi,
                    'multiplier': mult_var,
                    'orig_mult': mdata['multiplier'],
                    'raw': mdata['raw'],
                }
                row += 1

    # ── TAB 5: Vending ────────────────────────────────────────────────────

    def _build_vending_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text='  Vending  ')

        ttk.Label(tab, text=(
            "Manage vending machines (Circus of Values / El Ammo Bandito) and "
            "Gatherer's Garden inventory.  'Unlock All' makes every possible "
            "item available at every machine.  Per-item costs are applied "
            "globally across all sections."),
            foreground='#7f849c', wraplength=900).pack(anchor='w', pady=(0, 6))

        self.vending_inner_frame = ttk.Frame(tab)
        self.vending_inner_frame.pack(fill='both', expand=True)

        self.vending_placeholder = ttk.Label(self.vending_inner_frame,
            text="Loading vending data...", foreground='#6c7086',
            font=('Segoe UI', 10))
        self.vending_placeholder.pack(expand=True)

        self.unlock_vending_var = tk.BooleanVar(value=False)
        self.unlock_garden_var = tk.BooleanVar(value=False)
        self.vending_mult_var = tk.DoubleVar(value=1.0)
        self.garden_mult_var = tk.DoubleVar(value=1.0)
        self.vending_cost_vars = {}   # {item_class: StringVar}
        self.garden_cost_vars = {}    # {item_class: StringVar}

    def _populate_vending_tab(self):
        for w in self.vending_inner_frame.winfo_children():
            w.destroy()

        if not self.ini_configs or 'LootTables_perobjectconfig.ini' not in self.ini_configs:
            ttk.Label(self.vending_inner_frame,
                      text="LootTables_perobjectconfig.ini not found",
                      foreground='#f38ba8').pack()
            return

        from core.ini_config import read_vending_data, VENDING_ITEM_NAMES

        self.vending_data = read_vending_data(
            self.ini_configs['LootTables_perobjectconfig.ini'])

        canvas, inner = make_scrollable(self.vending_inner_frame)

        row = 0

        # ── Controls row ────────────────────────────────────────────────
        ctrl = ttk.Frame(inner)
        ctrl.grid(row=row, column=0, columnspan=4, sticky='ew', pady=(0, 8))
        row += 1

        ttk.Checkbutton(ctrl, text="Unlock All Vending Items",
                         variable=self.unlock_vending_var).pack(
            side='left', padx=(0, 20))
        ttk.Checkbutton(ctrl, text="Unlock All Garden Items",
                         variable=self.unlock_garden_var).pack(
            side='left', padx=(0, 30))

        ttk.Label(ctrl, text="Vending Price x").pack(side='left')
        ttk.Spinbox(ctrl, from_=0.1, to=10.0, increment=0.1, width=5,
                    textvariable=self.vending_mult_var,
                    font=('Segoe UI', 9)).pack(side='left', padx=(0, 20))

        ttk.Label(ctrl, text="Garden Price x").pack(side='left')
        ttk.Spinbox(ctrl, from_=0.1, to=10.0, increment=0.1, width=5,
                    textvariable=self.garden_mult_var,
                    font=('Segoe UI', 9)).pack(side='left')

        ttk.Separator(inner, orient='horizontal').grid(
            row=row, column=0, columnspan=4, sticky='ew', pady=4)
        row += 1

        # ── Vending machine items ───────────────────────────────────────
        ttk.Label(inner, text="Vending Machines",
                  style='WeaponName.TLabel').grid(
            row=row, column=0, columnspan=4, sticky='w', pady=(6, 2))
        row += 1

        ttk.Label(inner, text="Item", style='Header.TLabel').grid(
            row=row, column=0, sticky='w', padx=(10, 8))
        ttk.Label(inner, text="Stack", style='Header.TLabel').grid(
            row=row, column=1, sticky='w', padx=4)
        ttk.Label(inner, text="Cost", style='Header.TLabel').grid(
            row=row, column=2, sticky='w', padx=4)
        ttk.Separator(inner, orient='horizontal').grid(
            row=row + 1, column=0, columnspan=4, sticky='ew', pady=2)
        row += 2

        # Deduplicate by item class — show one row per unique item
        seen = set()
        for sp in self.vending_data['vending_items']:
            ic = sp['item']
            if ic in seen:
                continue
            seen.add(ic)
            friendly = VENDING_ITEM_NAMES.get(ic, sp['friendly'])

            ttk.Label(inner, text=friendly).grid(
                row=row, column=0, sticky='w', padx=(10, 8), pady=1)
            ttk.Label(inner, text=str(sp['stack']),
                      foreground='#7f849c').grid(
                row=row, column=1, sticky='w', padx=4, pady=1)

            cost_var = tk.StringVar(value='%.4g' % sp['cost'])
            ttk.Entry(inner, textvariable=cost_var, width=7,
                      font=('Segoe UI', 9)).grid(
                row=row, column=2, padx=4, pady=1)
            self.vending_cost_vars[ic] = cost_var
            row += 1

        ttk.Separator(inner, orient='horizontal').grid(
            row=row, column=0, columnspan=4, sticky='ew', pady=6)
        row += 1

        # ── Gatherer's Garden items ─────────────────────────────────────
        ttk.Label(inner, text="Gatherer's Garden",
                  style='WeaponName.TLabel').grid(
            row=row, column=0, columnspan=4, sticky='w', pady=(6, 2))
        row += 1

        # Sub-group: Plasmids, Upgrades, Tonics
        groups = [
            ('Plasmids', lambda ic: 'Plasmid' in ic and 'Tonic' not in ic),
            ('Upgrades', lambda ic: 'Upgrade' in ic),
            ('Gene Tonics', lambda ic: 'Tonic' in ic),
        ]

        ttk.Label(inner, text="Item", style='Header.TLabel').grid(
            row=row, column=0, sticky='w', padx=(10, 8))
        ttk.Label(inner, text="Cost", style='Header.TLabel').grid(
            row=row, column=2, sticky='w', padx=4)
        ttk.Separator(inner, orient='horizontal').grid(
            row=row + 1, column=0, columnspan=4, sticky='ew', pady=2)
        row += 2

        seen_g = set()
        for grp_name, grp_filter in groups:
            ttk.Label(inner, text=grp_name, foreground='#cba6f7',
                      font=('Segoe UI', 9, 'bold')).grid(
                row=row, column=0, columnspan=4, sticky='w',
                padx=(6, 0), pady=(6, 1))
            row += 1

            for sp in self.vending_data['growth_items']:
                ic = sp['item']
                if ic in seen_g or not grp_filter(ic):
                    continue
                seen_g.add(ic)
                friendly = VENDING_ITEM_NAMES.get(ic, sp['friendly'])

                ttk.Label(inner, text=friendly).grid(
                    row=row, column=0, sticky='w', padx=(16, 8), pady=1)

                cost_var = tk.StringVar(value='%.4g' % sp['cost'])
                ttk.Entry(inner, textvariable=cost_var, width=7,
                          font=('Segoe UI', 9)).grid(
                    row=row, column=2, padx=4, pady=1)
                self.garden_cost_vars[ic] = cost_var
                row += 1

    # ── TAB 6: Enemy Health ──────────────────────────────────────────────

    # (friendly_name, resistance_set, ai_damage_stim_types)
    # Multiplier > 1 = tankier (less damage taken), < 1 = squishier
    ENEMY_HEALTH_SETS = [
        ('Splicers (Easy)',       'HumanAggressorResistanceSetEasy'),
        ('Splicers (Normal)',     'HumanAggressorResistanceSet'),
        ('Splicers (Hard)',       'HumanAggressorHardResistanceSet'),
        ('Brutes',                'BruteResistanceSet'),
        ('Fire Brutes',           'FireBruteResistanceSet'),
        ('Bouncers',              'BouncerResistanceSet'),
        ('Elite Bouncers',        'EliteBouncerResistanceSet'),
        ('Rosies',                'RosieResistanceSet'),
        ('Elite Rosies',          'EliteRosieResistanceSet'),
        ('Lancers',               'LancerResistanceSet'),
        ('Big Sisters',           'BigSisterResistanceSet'),
        ('Security Bots',         'SecurityBotResistanceSet'),
        ('Turrets',               'TurretResistanceSet'),
    ]

    def _build_enemy_health_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text='  Enemy Health  ')

        ttk.Label(tab, text=(
            "Adjust enemy health by scaling damage resistance.  A multiplier of "
            "2.0 means enemies take half damage (2\u00d7 effective health).  A "
            "value of 0.5 means enemies take double damage (half health).  "
            "Default is 1.0 for all types."),
            foreground='#7f849c', wraplength=900).pack(anchor='w', pady=(0, 6))

        self.ehealth_inner = ttk.Frame(tab)
        self.ehealth_inner.pack(fill='both', expand=True)

        self.ehealth_placeholder = ttk.Label(self.ehealth_inner,
            text="Loading health data...", foreground='#6c7086',
            font=('Segoe UI', 10))
        self.ehealth_placeholder.pack(expand=True)

    def _populate_enemy_health_tab(self):
        for w in self.ehealth_inner.winfo_children():
            w.destroy()

        canvas, inner = make_scrollable(self.ehealth_inner)

        ttk.Label(inner, text="Enemy Type", style='Header.TLabel').grid(
            row=0, column=0, sticky='w', padx=(10, 20))
        ttk.Label(inner, text="Health Multiplier", style='Header.TLabel').grid(
            row=0, column=1, sticky='w', padx=4)
        ttk.Separator(inner, orient='horizontal').grid(
            row=1, column=0, columnspan=3, sticky='ew', pady=2)

        row = 2
        for friendly, set_name in self.ENEMY_HEALTH_SETS:
            ttk.Label(inner, text=friendly, font=('Segoe UI', 9, 'bold')).grid(
                row=row, column=0, sticky='w', padx=(10, 20), pady=2)

            var = tk.DoubleVar(value=1.0)
            self.enemy_health_vars[set_name] = var

            spin = ttk.Spinbox(inner, from_=0.1, to=10.0, increment=0.1,
                               textvariable=var, width=6,
                               font=('Segoe UI', 9))
            spin.grid(row=row, column=1, padx=4, pady=2)

            ttk.Label(inner, text='\u00d7', foreground='#7f849c').grid(
                row=row, column=2, sticky='w')
            row += 1

    # ── TAB 7: Extras ─────────────────────────────────────────────────────

    # Each extra tweak is defined as:
    #   key: unique ID
    #   label: display name
    #   desc: tooltip/description
    #   section: DamageSets.ini section to modify
    #   add_stimuli: list of (Type, Amount, Chance) to append
    #   category: grouping in the UI
    EXTRAS_DEFS = [
        # ── Experimental ──
        {
            'key': 'raise_resource_limits',
            'label': 'Raise Engine Resource Limits',
            'desc': (
                'Raises memory pool limits in ResourceLimits.ini for stability '
                'with more enemies.  Stock pools are tuned for console-era enemy '
                'counts — multiplied spawns exhaust SkeletalMesh (enemy models), '
                'Animation, Havok (ragdoll physics), Emitters (fire/particles), '
                'Projectors, DynamicBuffer, and Audio pools.  This raises all of '
                'them and increases TotalMemory from 3000 to 3800 MB.  Safe on '
                'any PC with 8+ GB RAM (game is 32-bit LAA, 4 GB max).'
            ),
            'section': None,
            'add_stimuli': [],
            'category': 'Experimental',
            'ini_patches': {
                'file': 'ResourceLimits.ini',
                'key_values': {
                    'TotalMemory':   '3800',
                    'SkeletalMesh':  '200',
                    'Animation':     '250',
                    'Havok':         '250',
                    'Emitters':      '200',
                    'Projectors':    '200',
                    'DynamicBuffer': '200',
                    'Audio':         '300',
                },
            },
        },
        # ── Berserker Drill ──
        {
            'key': 'dual_drill',
            'label': 'Berserker Drill (Dual Drill Power)',
            'desc': (
                'Overhauls the drill into a devastating dual-drill berserker '
                'weapon.  Triples spin damage (15\u219250), massively boosts '
                'melee swing (40\u2192100), doubles dash impact, widens the '
                'reflector shield arc, halves fuel cost, and increases movement '
                'speed while drilling.  Creates a Weapon_Drill.ini config '
                'override and patches DamageSets + DamageMultipliers.  '
                'Pure INI changes \u2014 fully reversible.'
            ),
            'section': None,
            'add_stimuli': [],
            'category': 'Experimental',
        },
        # ── Flame Drill ──
        {
            'key': 'flame_drill',
            'label': 'Flame Drill (Fire Visual Effect)',
            'desc': (
                'Attaches a persistent fire emitter to the drill while '
                'equipped.  Uses the FlameThrower particle effect on the '
                'Drill bone via bytecode injection into OnEquippingFinished.  '
                'Patches ShockGame.U \u2014 restored on next apply.'
            ),
            'section': None,
            'add_stimuli': [],
            'category': 'Experimental',
        },
        # ══════════════════════════════════════════════════════════════
        # WEAPONS — Ammo element / behaviour overhauls
        # ══════════════════════════════════════════════════════════════
        # ── Drill ──
        {
            'key': 'hellfire_drill',
            'label': 'Hellfire Drill',
            'desc': (
                'The drill ignites enemies on fire with both the melee swing '
                'and spinning attacks.  Renamed to Hellfire Drill.'
            ),
            'sections': ['DrillSpin_StimuliSet', 'DrillSwing_StimuliSet'],
            'add_stimuli': [
                ('STIMULUS_Heat', 20.0, 1.0),
                ('STIMULUS_AIHeat', 15.0, 1.0),
                ('STIMULUS_Burning', 10.0, 1.0),
                ('STIMULUS_BurningTime', 5.0, 1.0),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('Drill', 'FriendlyName', 'Hellfire Drill'),
                ],
            },
            'lbf_patches': [
                ('Manual_perobjectconfig.int', 'Drill', 'FriendlyName', 'Hellfire Drill'),
            ],
            'category': 'Weapons',
        },
        # ── Rivet Gun: Standard ──
        {
            'key': 'ice_rivets',
            'label': 'Ice Rivets (Standard Rivet)',
            'desc': (
                'Standard rivets freeze enemies on hit.  '
                'Renamed to Ice Rivets.'
            ),
            'sections': ['StandardRivet_StimuliSet'],
            'add_stimuli': [
                ('STIMULUS_Frozen', 5.0, 1.0),
                ('STIMULUS_AICold', 0.0, 1.0),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('StandardRivet', 'FriendlyName', 'Ice Rivets'),
                ],
            },
            'lbf_patches': [
                ('ShockGame.int', 'Rivet_Ammo', 'FriendlyName', 'Ice Rivets'),
                ('Manual_perobjectconfig.int', 'StandardRivet', 'FriendlyName', 'Ice Rivets'),
            ],
            'category': 'Weapons',
        },
        # ── Rivet Gun: Heavy ──
        {
            'key': 'rage_rivets',
            'label': 'Rage Rivets (Heavy Rivet)',
            'desc': (
                'Heavy rivets enrage enemies and send them flying backwards '
                'on impact.  Renamed to Rage Rivets.'
            ),
            'sections': ['MagnumRivet_StimuliSet'],
            'add_stimuli': [
                ('STIMULUS_Berserk', 20.0, 1.0),
                ('STIMULUS_SpringBoardTrap', 1.0, 1.0),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('MagnumRivet', 'FriendlyName', 'Rage Rivets'),
                ],
            },
            'lbf_patches': [
                ('ShockGame.int', 'Rivet_MagnumAmmo', 'FriendlyName', 'Rage Rivets'),
                ('Manual_perobjectconfig.int', 'MagnumRivet', 'FriendlyName', 'Rage Rivets'),
            ],
            'category': 'Weapons',
        },
        # ── Machine Gun: Standard ──
        {
            'key': 'static_rounds',
            'label': 'Static Rounds (MG Standard)',
            'desc': (
                'Standard machine gun rounds shock enemies and apply the '
                'electric stun effect.  Renamed to Static Rounds.'
            ),
            'sections': ['MachineGunStandardBulletStimuliSet'],
            'add_stimuli': [
                ('STIMULUS_Shocked', 2.5, 1.0),
                ('STIMULUS_Electric', 5.0, 1.0),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('MachineGunBullet', 'FriendlyName', 'Static Rounds'),
                ],
            },
            'lbf_patches': [
                ('ShockGame.int', 'MachineGun_Bullet', 'FriendlyName', 'Static Rounds'),
                ('Manual_perobjectconfig.int', 'MachineGunBullet', 'FriendlyName', 'Static Rounds'),
            ],
            'category': 'Weapons',
        },
        # ── Machine Gun: Anti-Personnel ──
        {
            'key': 'shredder_rounds',
            'label': 'Shredder Rounds (MG Anti-Personnel)',
            'desc': (
                'Anti-personnel rounds cause enemies to bleed like the '
                'Insect Swarm plasmid.  Increased damage against splicers.  '
                'Renamed to Shredder Rounds.'
            ),
            'sections': ['MachineGunAntipersonnelBulletStimuliSet'],
            'add_stimuli': [
                ('STIMULUS_Bleeding', 15.0, 1.0),
                ('STIMULUS_Diseased', 1.0, 0.5),
                ('STIMULUS_AIAntiPersonnel', 10.0, 1.0),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('MachineGunAntiPersonnelBullet', 'FriendlyName',
                     'Shredder Rounds'),
                ],
            },
            'lbf_patches': [
                ('ShockGame.int', 'MachineGun_AntiPersonnelBullet',
                 'FriendlyName', 'Shredder Rounds'),
                ('Manual_perobjectconfig.int', 'MachineGunAntiPersonnelBullet',
                 'FriendlyName', 'Shredder Rounds'),
            ],
            'category': 'Weapons',
        },
        # ── Shotgun: 00 Buck ──
        {
            'key': 'heavy_shells',
            'label': 'Explosive Shells (Shotgun 00 Buck)',
            'desc': (
                '00 Buck shells explode on impact with enemies or surfaces, '
                'dealing area explosive damage similar to frag grenades.  '
                'Renamed to Explosive Shells.'
            ),
            'sections': ['Buck00StimuliSet'],
            'add_stimuli': [
                ('STIMULUS_AIExplosive', 100.0, 1.0),
                ('STIMULUS_Explosive', 30.0, 1.0),
            ],
            'ds_overrides': {
                'DamageType': 'Explosive',
                'DamageStrength': 'Heavy',
                'MomentumScale': '10.0f',
                'DeathReaction': 'InstantRagdoll',
            },
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('00Buck', 'FriendlyName', 'Explosive Shells'),
                ],
            },
            'lbf_patches': [
                ('ShockGame.int', 'Shotgun_00Buck', 'FriendlyName', 'Explosive Shells'),
                ('Manual_perobjectconfig.int', '00Buck', 'FriendlyName', 'Explosive Shells'),
            ],
            'category': 'Weapons',
        },
        # ── Shotgun: Solid Slug ──
        {
            'key': 'explosive_shot',
            'label': 'Explosive Shot (Shotgun Solid Slug)',
            'desc': (
                'Solid Slug shots detonate enemies with an explosion on '
                'impact, similar to frag grenades.  '
                'Renamed to Explosive Shot.'
            ),
            'sections': ['SolidSlugStimuliSet'],
            'add_stimuli': [
                ('STIMULUS_AIExplosive', 100.0, 1.0),
                ('STIMULUS_Explosive', 30.0, 1.0),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('SolidSlug', 'FriendlyName', 'Explosive Shot'),
                ],
            },
            'lbf_patches': [
                ('ShockGame.int', 'Shotgun_SolidSlug', 'FriendlyName', 'Explosive Shot'),
                ('Manual_perobjectconfig.int', 'SolidSlug', 'FriendlyName', 'Explosive Shot'),
            ],
            'category': 'Weapons',
        },
        # ── Plasmids ──
        {
            'key': 'hades_grasp',
            'label': 'Hades Grasp (Telekinesis)',
            'desc': (
                'Upgrades all Telekinesis levels to pick up living enemies '
                '(TK3 ability).  Picked-up enemies are set on fire immediately; '
                'thrown enemies/objects also ignite targets on impact.  '
                'All versions renamed to Hades Grasp.  '
                'Patches ShockGame.U \u2014 restored on next apply.'
            ),
            'sections': ['TelekinesisManipulationStimuliSet'],
            'add_stimuli': [
                ('STIMULUS_Heat', 20.0, 1.0),
                ('STIMULUS_AIHeat', 15.0, 1.0),
                ('STIMULUS_Burning', 10.0, 1.0),
                ('STIMULUS_BurningTime', 5.0, 1.0),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('TelekinesisBasicPlasmid', 'FriendlyName', 'Hades Grasp'),
                    ('TelekinesisAdvancedPlasmid', 'FriendlyName', 'Hades Grasp'),
                    ('TelekinesisMasterPlasmid', 'FriendlyName', 'Hades Grasp'),
                ],
            },
            'lbf_patches': [
                ('ShockGame.int', 'TelekinesisAbility', 'FriendlyName', 'Hades Grasp'),
                ('Manual_perobjectconfig.int', 'TelekinesisBasicPlasmid', 'FriendlyName', 'Hades Grasp'),
                ('Manual_perobjectconfig.int', 'TelekinesisAdvancedPlasmid', 'FriendlyName', 'Hades Grasp'),
                ('Manual_perobjectconfig.int', 'TelekinesisMasterPlasmid', 'FriendlyName', 'Hades Grasp'),
            ],
            'category': 'Plasmids',
        },
        {
            'key': 'winters_embrace',
            'label': "Winter's Embrace (Telekinesis)",
            'desc': (
                'Upgrades all Telekinesis levels to pick up living enemies '
                '(TK3 ability).  Picked-up enemies are frozen immediately; '
                'thrown enemies/objects apply freeze on impact.  '
                "All versions renamed to Winter's Embrace.  "
                'Patches ShockGame.U \u2014 restored on next apply.'
            ),
            'sections': ['TelekinesisManipulationStimuliSet'],
            'add_stimuli': [
                ('STIMULUS_Frozen', 5.0, 1.0),
                ('STIMULUS_AICold', 25.0, 1.0),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('TelekinesisBasicPlasmid', 'FriendlyName', "Winter's Embrace"),
                    ('TelekinesisAdvancedPlasmid', 'FriendlyName', "Winter's Embrace"),
                    ('TelekinesisMasterPlasmid', 'FriendlyName', "Winter's Embrace"),
                ],
            },
            'lbf_patches': [
                ('ShockGame.int', 'TelekinesisAbility', 'FriendlyName', "Winter's Embrace"),
                ('Manual_perobjectconfig.int', 'TelekinesisBasicPlasmid', 'FriendlyName', "Winter's Embrace"),
                ('Manual_perobjectconfig.int', 'TelekinesisAdvancedPlasmid', 'FriendlyName', "Winter's Embrace"),
                ('Manual_perobjectconfig.int', 'TelekinesisMasterPlasmid', 'FriendlyName', "Winter's Embrace"),
            ],
            'category': 'Plasmids',
        },
        {
            'key': 'hellfire_decoy',
            'label': 'Hell Fire Decoy (Decoy)',
            'desc': (
                'All decoy versions now reflect 100%% of incoming damage '
                'back to attackers.  A Cyclone Trap spawns at the decoy '
                'position, launching approaching enemies into the air '
                'and igniting them with fire damage.  '
                'All versions renamed to Hell Fire Decoy.  '
                'Patches ShockGame.U \u2014 restored on next apply.'
            ),
            'sections': ['SpringBoardTrapStimuliSet'],
            'add_stimuli': [
                ('STIMULUS_Heat', 20.0, 1.0),
                ('STIMULUS_Burning', 10.0, 1.0),
                ('STIMULUS_BurningTime', 5.0, 1.0),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('DecoyBasicPlasmid', 'FriendlyName', 'Hell Fire Decoy'),
                    ('DecoyAdvancedPlasmid', 'FriendlyName', 'Hell Fire Decoy'),
                    ('DecoyMasterPlasmid', 'FriendlyName', 'Hell Fire Decoy'),
                ],
            },
            'lbf_patches': [
                ('ShockGame.int', 'DecoyHumanAbility', 'FriendlyName', 'Hell Fire Decoy'),
                ('Manual_perobjectconfig.int', 'DecoyBasicPlasmid', 'FriendlyName', 'Hell Fire Decoy'),
                ('Manual_perobjectconfig.int', 'DecoyAdvancedPlasmid', 'FriendlyName', 'Hell Fire Decoy'),
                ('Manual_perobjectconfig.int', 'DecoyMasterPlasmid', 'FriendlyName', 'Hell Fire Decoy'),
            ],
            'category': 'Plasmids',
        },
        {
            'key': 'vampiric_thrall',
            'label': 'Vampiric Thrall (Hypnotize)',
            'desc': (
                'Hypnotized enemies now reflect 100%% of incoming damage '
                'back at attackers.  All versions renamed to Vampiric Thrall.  '
                'Patches ShockGame.U \u2014 restored on next apply.'
            ),
            'section': None,
            'add_stimuli': [],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('HypnotizeBasicPlasmid', 'FriendlyName', 'Vampiric Thrall'),
                    ('HypnotizeAdvancedPlasmid', 'FriendlyName', 'Vampiric Thrall'),
                    ('HypnotizeMasterPlasmid', 'FriendlyName', 'Vampiric Thrall'),
                ],
            },
            'lbf_patches': [
                ('ShockGame.int', 'BerserkRageAbility', 'FriendlyName', 'Vampiric Thrall'),
                ('Manual_perobjectconfig.int', 'HypnotizeBasicPlasmid', 'FriendlyName', 'Vampiric Thrall'),
                ('Manual_perobjectconfig.int', 'HypnotizeAdvancedPlasmid', 'FriendlyName', 'Vampiric Thrall'),
                ('Manual_perobjectconfig.int', 'HypnotizeMasterPlasmid', 'FriendlyName', 'Vampiric Thrall'),
            ],
            'category': 'Plasmids',
        },
        {
            'key': 'frej_swarm',
            'label': 'Frej Swarm (Insect Swarm)',
            'desc': (
                'Insect Swarm now freezes enemies on contact.  '
                'All versions renamed to Frej Swarm.'
            ),
            'sections': ['InsectSwarmStimuliSet'],
            'add_stimuli': [
                ('STIMULUS_Frozen', 5.0, 1.0),
                ('STIMULUS_AICold', 0.0, 1.0),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('SwarmBasicPlasmid', 'FriendlyName', 'Frej Swarm'),
                    ('SwarmAdvancedPlasmid', 'FriendlyName', 'Frej Swarm'),
                    ('SwarmMasterPlasmid', 'FriendlyName', 'Frej Swarm'),
                ],
            },
            'lbf_patches': [
                ('ShockGame.int', 'InsectSwarmAbility', 'FriendlyName', 'Frej Swarm'),
                ('Manual_perobjectconfig.int', 'SwarmBasicPlasmid', 'FriendlyName', 'Frej Swarm'),
                ('Manual_perobjectconfig.int', 'SwarmAdvancedPlasmid', 'FriendlyName', 'Frej Swarm'),
                ('Manual_perobjectconfig.int', 'SwarmMasterPlasmid', 'FriendlyName', 'Frej Swarm'),
            ],
            'category': 'Plasmids',
        },
        {
            'key': 'electric_highlight',
            'label': 'Electric Highlight (Electro Bolt)',
            'desc': (
                'Combines Electro Bolt with Security Command.  '
                'Enemies hit by any level of Electro Bolt are also '
                'tagged for Rapture security — cameras and turrets '
                'will attack them.  All versions renamed to Electric '
                'Highlight.'
            ),
            'sections': [
                'ElectricBoltStimuliSet',
                'ElectricBoltTwoStimuliSet',
                'ElectricBoltThreeStimuliSet',
            ],
            'add_stimuli': [
                ('STIMULUS_SecurityBeacon', 1.0, 1.0),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('ElectroboltBasicPlasmid', 'FriendlyName',
                     'Electric Highlight'),
                    ('ElectroboltAdvancedPlasmid', 'FriendlyName',
                     'Electric Highlight 2'),
                    ('ElectroboltMasterPlasmid', 'FriendlyName',
                     'Electric Highlight 3'),
                ],
            },
            'lbf_patches': [],
            'category': 'Plasmids',
        },
        # ══════════════════════════════════════════════════════════════
        #  SECURITY
        # ══════════════════════════════════════════════════════════════
        {
            'key': 'security_fire_ammo',
            'label': 'Ignition Ammo (Security Bots & Turrets)',
            'desc': (
                'Security bots and turrets fire incendiary rounds that '
                'ignite targets on hit.  Applies to all security bot '
                'difficulty tiers and SMG turrets.'
            ),
            'sections': [
                'SecurityBotEasyStimuliSet',
                'SecurityBotStimuliSet',
                'SecurityBotHardStimuliSet',
                'MaxSecurityBotStimuliSet',
                'SecurityBotSumMasStimuliSet',
                'SMGTurretMinigunEasyStimuliSet',
                'SMGTurretMinigunStimuliSet',
                'SMGTurretMinigunHardStimuliSet',
                'SPFTurretMinigunStimuliSet',
                'AutoTurretStimuliSet',
            ],
            'add_stimuli': [
                ('STIMULUS_Heat', 10.0, 1.0),
                ('STIMULUS_AIHeat', 5.0, 1.0),
                ('STIMULUS_Burning', 5.0, 1.0),
                ('STIMULUS_BurningTime', 3.0, 1.0),
            ],
            'section_patches': None,
            'lbf_patches': [],
            'category': 'Security',
        },
        # ══════════════════════════════════════════════════════════════
        #  WEAPON UPGRADES
        # ══════════════════════════════════════════════════════════════
        {
            'key': 'ricochet_enhancement',
            'label': 'Ricochet Enhancement (Rivet / Shotgun)',
            'desc': (
                'Bullets from the Rivet Gun and Shotgun ricochet once '
                'off solid surfaces, just like the Machine Gun\'s third '
                'upgrade.  Machine Gun bullets are unaffected (they '
                'still require the Power to the People upgrade).  '
                'Patches ShockGame.U bytecode.'
            ),
            'sections': [],
            'add_stimuli': [],
            'section_patches': None,
            'lbf_patches': [],
            'category': 'Weapon Upgrades',
        },
        {
            'key': 'drill_knockback',
            'label': 'Drill Knockback',
            'desc': (
                'The Drill spin attack now launches enemies back on hit, '
                'similar to the Shotgun Solid Slug.  Greatly increases '
                'the momentum of each spin hit.'
            ),
            'sections': ['DrillSpin_StimuliSet'],
            'add_stimuli': [
                ('STIMULUS_SpringBoardTrap', 1.0, 1.0),
            ],
            'ds_overrides': {
                'MomentumScale': '4.0f',
            },
            'section_patches': None,
            'lbf_patches': [],
            'category': 'Weapon Upgrades',
        },
        {
            'key': 'enrage_rounds',
            'label': 'Enrage Rounds (Machine Gun)',
            'desc': (
                'Renames Armor-Piercing Rounds to Enrage Rounds.  '
                'On hit, enemies become enraged and attack other enemies.  '
                'Retains the original anti-armor damage bonus.'
            ),
            'sections': ['MachineGunArmorPiercingBulletStimuliSet'],
            'add_stimuli': [
                ('STIMULUS_Berserk', 20.0, 1.0),
                ('STIMULUS_LatentBerserk', 1.0, 1.0),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('MachineGunArmorPiercingBullet', 'FriendlyName',
                     'Enrage Rounds'),
                ],
            },
            'lbf_patches': [],
            'category': 'Weapon Upgrades',
        },
        {
            'key': 'disease_buck',
            'label': 'Disease Buck (Shotgun)',
            'desc': (
                'Renames 00 Buck to Disease Buck.  Shotgun pellets now '
                'inflict a disease effect that deals damage over time, '
                'similar to shredder ammo.'
            ),
            'sections': ['Buck00StimuliSet'],
            'add_stimuli': [
                ('STIMULUS_Bleeding', 15.0, 1.0),
                ('STIMULUS_Diseased', 1.0, 0.5),
            ],
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('00Buck', 'FriendlyName', 'Disease Buck'),
                ],
            },
            'lbf_patches': [
                ('ShockGame.int', 'Shotgun_00Buck', 'FriendlyName', 'Disease Buck'),
                ('Manual_perobjectconfig.int', '00Buck', 'FriendlyName', 'Disease Buck'),
            ],
            'category': 'Weapon Upgrades',
        },
        {
            'key': 'weighted_spear',
            'label': 'Weighted Spear (Speargun)',
            'desc': (
                'Renames the standard Spear to Weighted Spear.  On hit, '
                'enemies are knocked back with heavy force, similar to '
                'the Shotgun Solid Slug.'
            ),
            'sections': ['StandardSpear_StimuliSet'],
            'add_stimuli': [
                ('STIMULUS_SpringBoardTrap', 1.0, 1.0),
            ],
            'ds_overrides': {
                'MomentumScale': '4.0f',
            },
            'section_patches': {
                'file': 'Manual_perobjectconfig.ini',
                'patches': [
                    ('StandardSpear', 'FriendlyName', 'Weighted Spear'),
                ],
            },
            'lbf_patches': [],
            'category': 'Weapon Upgrades',
        },
        {
            'key': 'static_rounds_fix',
            'label': 'Static Rounds Fix (Shotgun Tesla)',
            'desc': (
                'Fixes the Shotgun Tesla upgrade static rounds so they '
                'properly deal electric damage, stun enemies, and '
                'electrocute water.  The base game has AIElectric set '
                'to 0 — this corrects it.'
            ),
            'sections': ['TeslaUpgradeStimuliSet'],
            'add_stimuli': [
                ('STIMULUS_Electric', 30.0, 1.0),
            ],
            'stimulus_patches': [
                ('TeslaUpgradeStimuliSet', 'STIMULUS_AIElectric', 30.0),
            ],
            'section_patches': None,
            'lbf_patches': [],
            'category': 'Weapon Upgrades',
        },
    ]

    # ── Restored Cut Content ──
    # Each entry defines a cut plasmid/ability that has compiled code and assets
    # already in the game files but was never made available to the player.
    # Restoring adds the item to Gatherer's Garden vending machines and creates
    # the required GUI and Manual entries in the INI files.
    RESTORED_CONTENT_DEFS = [
        {
            'key': 'summon_protector',
            'label': 'Summon Protector (Cut Plasmid)',
            'desc': (
                'Restores the cut Summon Protector plasmid — summon a Big Daddy '
                'to fight alongside you. Ability code, animations, VFX and '
                'damage sets all exist in the game files.  Adds it to every '
                "Gatherer's Garden in the campaign."
            ),
            # SummonProtector is a TOPLEVEL class in ShockGame.U (not inside the
            # Plasmids sub-package), so the reference must use ShockGame.
            'vending_class': "class'ShockGame.SummonProtector'",
            'vending_sections': [
                'Education_Growth', 'Ghetto_Growth', 'Redlight_Growth',
                'Gallery_Growth', 'Abyss_Growth', 'Gulag_Growth',
            ],
            'gui_section': 'SummonProtector',
            'gui_entries': {
                'Filename': '..\\FlashMovies\\PlasmidTrainingContainer.swf',
                'DefaultPosition': '(X=0,Y=0)',
                'BackgroundAlpha': '0.0',
                'InputContextName': 'PauseUIActive',
                'BackgroundMovie': '"..\\BinkMovies\\Summon.bik"',
                'BackgroundMovieBufferSize': '0',
                'BackgroundMovieCloseWhenFinished': 'true',
                'BinkClearBackground': 'false',
                'BinkXOffsetOverride': '-310',
                'BinkYOffsetOverride': '-182',
                'BinkWidthOverride': '630',
                'BinkHeightOverride': '360',
                'BinkAlphaOverride': '1',
                'BinkAlphaOverrideValue': '1.0',
                'LocalizedAudio': '1',
                'bShowMouseCursor': 'false',
                'FitBinkBackgroundToScreen': 'True',
            },
            'manual_section': 'SummonProtector',
            'manual_entries': {
                'TopicType': 'Plasmid Descriptions',
                'FriendlyName': 'Summon Protector',
                'bHidden': 'true',
            },
            'manual_text': [
                'Entry=The Summon Protector Plasmid calls a Big Daddy to fight '
                'alongside you.',
                'Entry=\\nPress <Mapping=AltFire> to summon a Protector.',
                'Entry=\\nThe Big Daddy will attack any enemies in the area, '
                'drawing fire away from you and dealing heavy damage with its '
                'drill and charge attacks.',
            ],
            'inventory_config': {
                'section': 'SummonProtector',
                'FriendlyName': 'Summon Protector',
            },
            'plasmid_config': {
                'section': 'SummonProtector',
                'Track': 'TRACK_Plasmid',
                'Color': 'COLOR_Yellow',
                'Level': 'LEVEL_Basic',
            },
            'category': 'Restored Content',
        },
        {
            'key': 'ion_laser',
            'label': 'Ion Laser (DLC Weapon)',
            'desc': (
                "Transplants the Ion Laser from Minerva's Den into the main "
                "campaign.  Builds a DLCWeapons package with the weapon mesh, "
                "materials and textures.  Press F12 to obtain the weapon.  "
                "All three ammo types are purchasable from every El Ammo "
                "Bandito vendor."
            ),
            'keybind': 'F12 GiveWeapon DLCWeapons.PlayerLaserGun',
            'weapon_package': True,
            # Ammo entries for El Ammo Bandito vending machines
            'ammo_vending': [
                {
                    'item': "class'ShockGame.LaserGun_LaserAmmo'",
                    'pickup': "class'Pickups.MedHypo_Pickup'",
                    'stack': 30,
                },
                {
                    'item': "class'ShockGame.LaserGun_HeatAmmo'",
                    'pickup': "class'Pickups.MedHypo_Pickup'",
                    'stack': 20,
                },
                {
                    'item': "class'ShockGame.LaserGun_BurstAmmo'",
                    'pickup': "class'Pickups.MedHypo_Pickup'",
                    'stack': 12,
                },
            ],
            'ammo_sections': [
                'Education_Ammo', 'Education_AmmoA', 'Education_AmmoB',
                'Education_AmmoC', 'Education_AmmoD',
                'Ghetto_Ammo', 'Ghetto_AmmoA', 'Ghetto_AmmoB',
                'Ghetto_Ammo_Alt1', 'Ghetto_Ammo_Alt1A',
                'Redlight_Ammo', 'Redlight_Ammo_Alt1',
                'Redlight_Ammo_Alt1A', 'Redlight_Ammo_Alt2',
                'Redlight_Ammo_Alt2A', 'Redlight_Ammo_Alt2B',
                'Redlight_Ammo_Alt3',
                'Gallery_Ammo', 'Gallery_Ammo_Alt1', 'Gallery_Ammo_Alt1A',
                'Gallery_Ammo_Alt2', 'Gallery_Ammo_Alt2A',
                'Gallery_Ammo_Alt3', 'Gallery_Ammo_Alt4',
                'Abyss_Ammo', 'Abyss_Ammo_Alt1', 'Abyss_Ammo_Alt2',
                'Abyss_Ammo_Alt3', 'Abyss_Ammo_Alt4', 'Abyss_Ammo_Alt5',
                'Gulag_Ammo', 'Gulag_Ammo_Alt1', 'Gulag_Ammo_Alt2',
                'Gulag_Ammo_Alt3', 'Gulag_Ammo_Alt4', 'Gulag_Ammo_Alt5',
            ],
            # No GUI or manual needed -- IonLaser, LaserCell, HeatCell,
            # BurstCell sections already exist in Manual_perobjectconfig.ini
            'gui_section': None,
            'manual_section': None,
            'category': 'Restored Content',
        },
        # ── Summon Eleanor (Plasmid — available late-game in Outer Persephone) ──
        {
            'key': 'summon_eleanor',
            'label': 'Summon Eleanor',
            'desc': (
                'Adds the Summon Eleanor plasmid to every '
                "Gatherer's Garden.  Normally given by Eleanor in Outer "
                'Persephone near the end of the game — this makes it '
                'available for purchase from the first level.  Summons '
                'Eleanor Lamb (as a Big Sister) to fight alongside you.'
            ),
            # SummonBigSisterPlasmid lives in the Plasmids sub-package
            # inside each campaign BSM map (same outer as all other plasmids).
            'vending_class': "class'Plasmids.SummonBigSisterPlasmid'",
            'vending_sections': [
                'Education_Growth', 'Ghetto_Growth', 'Redlight_Growth',
                'Gallery_Growth', 'Abyss_Growth', 'Gulag_Growth',
            ],
            # GUI + Manual sections already exist in the shipped INI files
            'gui_section': None,
            'manual_section': None,
            'inventory_config': {
                'section': 'SummonBigSisterPlasmid',
                'FriendlyName': 'Summon Eleanor',
            },
            'plasmid_config': {
                'section': 'SummonBigSisterPlasmid',
                'Track': 'TRACK_Plasmid',
                'Color': 'COLOR_Yellow',
                'Level': 'LEVEL_Basic',
            },
            'category': 'Experimental',
        },
        # ── Gravity Well (DLC Plasmid — from Minerva's Den) ──
        {
            'key': 'gravity_well',
            'label': 'Gravity Well (DLC Plasmid)',
            'desc': (
                "Transplants the Gravity Well plasmid from the Minerva's "
                "Den DLC into the main campaign.  Throws a superdense polyp "
                "that bursts and sucks enemies into a vortex.  The compiled "
                "class (BioGrenadeBasicPlasmid) is already baked into every "
                "campaign map — this simply adds it to the Gatherer's Garden."
            ),
            # BioGrenadeBasicPlasmid lives in the DLCPlasmids sub-package
            # (same group as DLCSecurityCommand) inside every BSM map.
            'vending_class': "class'DLCPlasmids.BioGrenadeBasicPlasmid'",
            'vending_sections': [
                'Education_Growth', 'Ghetto_Growth', 'Redlight_Growth',
                'Gallery_Growth', 'Abyss_Growth', 'Gulag_Growth',
            ],
            # GUI section [BioGrenadeBasicPlasmid] already ships with the
            # Grav_Well_Plasmid.bik training video.
            # Manual section [GravityWellBasicPlasmid] already ships with
            # the full plasmid description text.
            'gui_section': None,
            'manual_section': None,
            'inventory_config': {
                'section': 'BioGrenadeBasicPlasmid',
                'FriendlyName': 'Gravity Well',
            },
            'plasmid_config': {
                'section': 'BioGrenadeBasicPlasmid',
                'Track': 'TRACK_Plasmid',
                'Color': 'COLOR_Yellow',
                'Level': 'LEVEL_Basic',
            },
            'category': 'Experimental',
        },
    ]

    def _build_extras_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text='  Extras  ')

        ttk.Label(tab, text=(
            "Engine tweaks and restored cut content.  Check a box to enable.  "
            "Restored content adds cut weapons and plasmids to vending machines."),
            foreground='#7f849c', wraplength=900).pack(anchor='w', pady=(0, 6))

        canvas, inner = make_scrollable(tab)

        # Combine extras and restored content for unified category grouping
        all_defs = list(self.EXTRAS_DEFS) + list(self.RESTORED_CONTENT_DEFS)
        categories = {}
        for edef in all_defs:
            cat = edef['category']
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(edef)

        # Render stable categories first, Experimental last
        CAT_ORDER = ['Plasmids', 'Weapon Upgrades', 'Weapons', 'Security', 'Restored Content', 'Experimental']
        sorted_cats = sorted(categories.keys(),
                             key=lambda c: (CAT_ORDER.index(c)
                                            if c in CAT_ORDER else -1, c))

        row = 0
        for cat_name, edefs in ((c, categories[c]) for c in sorted_cats):
            ttk.Label(inner, text=cat_name, style='MapName.TLabel').grid(
                row=row, column=0, columnspan=2, sticky='w', padx=2, pady=(10, 4))
            row += 1

            if cat_name == 'Experimental':
                ttk.Label(inner, text=(
                    "These features are work-in-progress and may not function "
                    "correctly.  Use at your own risk."),
                    foreground='#f38ba8', font=('Segoe UI', 8),
                    wraplength=900).grid(
                    row=row, column=0, columnspan=2, sticky='w',
                    padx=6, pady=(0, 2))
                row += 1

            ttk.Separator(inner, orient='horizontal').grid(
                row=row, column=0, columnspan=2, sticky='ew', pady=2)
            row += 1

            for edef in edefs:
                var = tk.BooleanVar(value=False)
                self.extras_vars[edef['key']] = var

                cb = ttk.Checkbutton(inner, text=edef['label'], variable=var,
                                     style='Extras.TCheckbutton')
                cb.grid(row=row, column=0, sticky='w', padx=(8, 4), pady=2)

                ttk.Label(inner, text=edef['desc'],
                          foreground='#6c7086', font=('Segoe UI', 8),
                          wraplength=500).grid(
                    row=row, column=1, sticky='w', padx=4, pady=2)
                row += 1

                # Flame drill: add emitter style dropdown
                if edef['key'] == 'flame_drill':
                    from core.shockgame_patcher import FLAME_EMITTERS
                    style_frame = ttk.Frame(inner)
                    style_frame.grid(row=row, column=0, columnspan=2,
                                     sticky='w', padx=(28, 4), pady=(0, 4))
                    ttk.Label(style_frame, text='Effect style:',
                              foreground='#7f849c',
                              font=('Segoe UI', 8)).pack(side='left')
                    self.flame_style_var = tk.StringVar(value='trap_fire')
                    style_values = ['%s  \u2014  %s' % (k, v[2])
                                    for k, v in FLAME_EMITTERS.items()]
                    style_keys = list(FLAME_EMITTERS.keys())
                    combo = ttk.Combobox(
                        style_frame, textvariable=self.flame_style_var,
                        values=style_keys, state='readonly', width=18)
                    combo.pack(side='left', padx=(6, 6))
                    # Description label that updates on selection
                    desc_var = tk.StringVar(
                        value=FLAME_EMITTERS['trap_fire'][2])
                    desc_lbl = ttk.Label(
                        style_frame, textvariable=desc_var,
                        foreground='#6c7086', font=('Segoe UI', 8))
                    desc_lbl.pack(side='left')

                    def _on_style_change(event, dv=desc_var, em=FLAME_EMITTERS,
                                         sv=self.flame_style_var):
                        key = sv.get()
                        if key in em:
                            dv.set(em[key][2])
                    combo.bind('<<ComboboxSelected>>', _on_style_change)
                    row += 1

    # ══════════════════════════════════════════════════════════════════════
    # PRESETS
    # ══════════════════════════════════════════════════════════════════════

    def _snapshot_all_settings(self):
        # Encounter multipliers
        enc_mults = {}
        for stem, mults in self.encounter_mults.items():
            sm = {}
            for label, var in mults.items():
                v = var.get()
                if v > 1:
                    sm[label] = v
            if sm:
                enc_mults[stem] = sm

        # Fallback: if no per-encounter overrides but global spinner > 1,
        # apply global value to every known encounter
        if not enc_mults:
            try:
                gv = self.all_encounter_var.get()
            except Exception:
                gv = 1
            if gv > 1:
                for stem, enc in self.encounter_data.items():
                    enc_mults[stem] = {label: gv for label in enc}

        # Extras checkboxes
        extras_enabled = [k for k, v in self.extras_vars.items() if v.get()]

        preset = {
            'version': 1,
            'spawners': {s: v.get() for s, v in self.spawner_vars.items()},
            'gather_defense': self.gather_defense_var.get(),
            'encounter_mults': enc_mults,
            'extras': extras_enabled,
            'flame_style': self.flame_style_var.get(),
            'damage': {},
            'loot': {},
            'dm': {},
        }
        # Damage
        for key, ddata in self.damage_data.items():
            try:
                val = float(ddata['amount'].get())
                if val != ddata['orig_amount']:
                    preset['damage']['%s_%d' % (ddata['section'], ddata['stim_idx'])] = {
                        'section': ddata['section'],
                        'stim_idx': ddata['stim_idx'],
                        'type': ddata['type'],
                        'amount': val,
                    }
            except ValueError:
                pass
        # Loot
        self._sync_loot_to_tables()
        for group, sections in self._loot_vars.items():
            for sec_name, table_vars in sections.items():
                specs = []
                for sv in table_vars:
                    try:
                        specs.append({
                            'item': sv.get('orig_item', sv['item'].get()),
                            'chance': int(sv['chance'].get()),
                            'min_stack': int(sv['min'].get()),
                            'max_stack': int(sv['max'].get()),
                            'table_name': sv.get('table_name', ''),
                        })
                    except ValueError:
                        pass
                if specs:
                    preset['loot'][sec_name] = specs
        # Damage multipliers
        for key, dmdata in self.dm_data.items():
            try:
                val = float(dmdata['multiplier'].get())
                if val != dmdata['orig_mult']:
                    preset['dm']['%s_%d' % (dmdata['section'], dmdata['idx'])] = {
                        'section': dmdata['section'],
                        'idx': dmdata['idx'],
                        'multiplier': val,
                    }
            except ValueError:
                pass
        # Vending
        vending_costs = {}
        for ic, var in self.vending_cost_vars.items():
            try:
                vending_costs[ic] = float(var.get())
            except ValueError:
                pass
        garden_costs = {}
        for ic, var in self.garden_cost_vars.items():
            try:
                garden_costs[ic] = float(var.get())
            except ValueError:
                pass
        preset['vending'] = {
            'unlock_vending': self.unlock_vending_var.get(),
            'unlock_garden': self.unlock_garden_var.get(),
            'vending_mult': self.vending_mult_var.get(),
            'garden_mult': self.garden_mult_var.get(),
            'vending_costs': vending_costs,
            'garden_costs': garden_costs,
        }
        # Enemy health multipliers
        eh = {}
        for set_name, var in self.enemy_health_vars.items():
            v = var.get()
            if abs(v - 1.0) > 0.01:
                eh[set_name] = v
        if eh:
            preset['enemy_health'] = eh
        return preset

    def _sync_loot_to_tables(self):
        from core.ini_config import LOOT_ITEMS_REV
        for group, sections in self._loot_vars.items():
            for sec_name, table_vars in sections.items():
                synced = []
                for sv in table_vars:
                    try:
                        friendly = sv['item'].get()
                        item_class = LOOT_ITEMS_REV.get(friendly, sv.get('orig_item', friendly))
                        synced.append({
                            'item': item_class,
                            'chance': int(sv['chance'].get()),
                            'min_stack': int(sv['min'].get()),
                            'max_stack': int(sv['max'].get()),
                            'table_name': sv.get('table_name', ''),
                        })
                    except (ValueError, AttributeError):
                        pass
                if sec_name in self._all_loot:
                    self._all_loot[sec_name] = synced

    def _apply_preset(self, preset):
        for s, v in preset.get('spawners', {}).items():
            if s in self.spawner_vars:
                self.spawner_vars[s].set(v)
        # Encounter multipliers
        for stem, mults in preset.get('encounter_mults', {}).items():
            if stem not in self.encounter_mults:
                self.encounter_mults[stem] = {}
            for label, v in mults.items():
                if label not in self.encounter_mults[stem]:
                    self.encounter_mults[stem][label] = tk.IntVar(value=v)
                else:
                    self.encounter_mults[stem][label].set(v)
        # Gather defense
        self.gather_defense_var.set(preset.get('gather_defense', 1))
        # Extras checkboxes
        enabled_extras = set(preset.get('extras', []))
        for key, var in self.extras_vars.items():
            var.set(key in enabled_extras)
        # Flame emitter style
        fs = preset.get('flame_style', 'trap_fire')
        if hasattr(self, 'flame_style_var'):
            self.flame_style_var.set(fs)
        # Damage values
        for pkey, pdata in preset.get('damage', {}).items():
            for key, ddata in self.damage_data.items():
                if ddata['section'] == pdata['section'] and ddata['stim_idx'] == pdata['stim_idx']:
                    ddata['amount'].set(str(pdata['amount']))
        # Damage multipliers
        for pkey, pdata in preset.get('dm', {}).items():
            for key, dmdata in self.dm_data.items():
                if dmdata['section'] == pdata['section'] and dmdata['idx'] == pdata['idx']:
                    dmdata['multiplier'].set(str(pdata['multiplier']))
        # Vending
        vending = preset.get('vending', {})
        self.unlock_vending_var.set(vending.get('unlock_vending', False))
        self.unlock_garden_var.set(vending.get('unlock_garden', False))
        self.vending_mult_var.set(vending.get('vending_mult', 1.0))
        self.garden_mult_var.set(vending.get('garden_mult', 1.0))
        for ic, cost in vending.get('vending_costs', {}).items():
            if ic in self.vending_cost_vars:
                self.vending_cost_vars[ic].set(str(cost))
        for ic, cost in vending.get('garden_costs', {}).items():
            if ic in self.garden_cost_vars:
                self.garden_cost_vars[ic].set(str(cost))
        # Enemy health
        for set_name, mult in preset.get('enemy_health', {}).items():
            if set_name in self.enemy_health_vars:
                self.enemy_health_vars[set_name].set(mult)
        self._log("Preset loaded.\n")

    def _save_preset(self):
        from tkinter import filedialog
        preset_dir = BIOMOD_DIR / "presets"
        preset_dir.mkdir(exist_ok=True)
        path = filedialog.asksaveasfilename(
            initialdir=str(preset_dir),
            defaultextension=".json",
            filetypes=[("Preset files", "*.json"), ("All files", "*.*")],
            title="Save Preset")
        if not path:
            return
        preset = self._snapshot_all_settings()
        with open(path, 'w') as f:
            json.dump(preset, f, indent=2)
        self._log("Preset saved to %s\n" % path)

    def _load_preset(self):
        from tkinter import filedialog, messagebox
        preset_dir = BIOMOD_DIR / "presets"
        preset_dir.mkdir(exist_ok=True)
        path = filedialog.askopenfilename(
            initialdir=str(preset_dir),
            filetypes=[("Preset files", "*.json"), ("All files", "*.*")],
            title="Load Preset")
        if not path:
            return
        try:
            with open(path, 'r') as f:
                preset = json.load(f)
            self._apply_preset(preset)
            self._log("Loaded preset from %s\n" % path)
        except Exception as e:
            messagebox.showerror("Preset Error", "Failed to load preset:\n%s" % e)

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════════════════

    def _log(self, msg):
        self.msg_queue.put(msg)
        if self._file_logger:
            try:
                ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
                for line in msg.rstrip('\n').split('\n'):
                    self._file_logger.info('[%s] %s' % (ts, line))
            except Exception:
                pass

    # ── File Logger ──────────────────────────────────────────────────────

    def _open_file_log(self, tag='apply'):
        """Open a timestamped log file under logs/. Deletes all previous logs."""
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Delete ALL previous logs so only the fresh one remains
        try:
            for old in LOG_DIR.glob('*.log'):
                old.unlink()
        except Exception:
            pass
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        self._log_path = LOG_DIR / ('%s_%s.log' % (tag, stamp))
        logger = logging.getLogger('wir2_%s' % stamp)
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        fh = logging.FileHandler(str(self._log_path), encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(fh)
        self._file_logger = logger
        return self._log_path

    def _close_file_log(self):
        """Flush and close the file logger."""
        if self._file_logger:
            for h in list(self._file_logger.handlers):
                h.flush()
                h.close()
                self._file_logger.removeHandler(h)
        self._file_logger = None

    def _log_system_info(self):
        """Write system / environment info to the file log."""
        if not self._file_logger:
            return
        L = self._file_logger.info
        L('=' * 70)
        L('  The War In Rapture — BioShock 2 Debug Log')
        L('=' * 70)
        L('Timestamp   : %s' % datetime.datetime.now().isoformat())
        L('OS          : %s' % platform.platform())
        L('Python      : %s' % sys.version.split()[0])
        L('Mod Dir     : %s' % BIOMOD_DIR)
        L('Game Root   : %s' % GAME_ROOT)
        L('Content Dir : %s' % CONTENT_DIR)
        L('Maps Dir    : %s (exists=%s)' % (MAPS_DIR, MAPS_DIR.exists()))
        L('Pristine Dir: %s (exists=%s)' % (PRISTINE_DIR, PRISTINE_DIR.exists()))
        # Game executable info
        exe_path = GAME_ROOT / 'Build' / 'Final' / 'Bioshock2HD.exe'
        if exe_path.exists():
            st = exe_path.stat()
            L('Game EXE    : %s (%d bytes, modified %s)' % (
                exe_path, st.st_size,
                datetime.datetime.fromtimestamp(st.st_mtime).isoformat()))
        else:
            L('Game EXE    : NOT FOUND at %s' % exe_path)
        # Disk space
        try:
            import shutil as _sh
            total, used, free = _sh.disk_usage(str(GAME_ROOT))
            L('Disk (game) : %.1f GB free / %.1f GB total' % (
                free / (1024**3), total / (1024**3)))
        except Exception:
            pass
        # List pristine backup files
        if PRISTINE_DIR.exists():
            pfiles = sorted(PRISTINE_DIR.glob('*'))
            L('Pristine files (%d):' % len(pfiles))
            for pf in pfiles:
                L('  %s  (%d bytes)' % (pf.name, pf.stat().st_size))
        else:
            L('Pristine Dir: MISSING — backups not created!')
        # IBF status
        ibf_game = CONTENT_DIR / "ConfigINI.IBF"
        ibf_bak  = CONTENT_DIR / "ConfigINI.IBF.bak"
        ibf_pris = PRISTINE_DIR / "ConfigINI.IBF"
        L('IBF status  : game=%s  bak=%s  pristine=%s' % (
            ibf_game.exists(), ibf_bak.exists(), ibf_pris.exists()))
        # Loose INI files
        sys_dir = CONTENT_DIR / "System"
        if sys_dir.exists():
            loose = sorted(sys_dir.glob('*.ini'))
            L('Loose INIs  : %d files in %s' % (len(loose), sys_dir))
            for lf in loose:
                L('  %-40s %8d bytes' % (lf.name, lf.stat().st_size))
        # Map files found
        if hasattr(self, 'map_files'):
            L('Map files   : %d BSM files found' % len(self.map_files))
        # Game logs (crash / session info)
        self._log_game_session(L)
        L('')

    def _log_game_session(self, L):
        """Scan the game's own log files for crash indicators & session info."""
        import os
        appdata = os.environ.get('APPDATA', '')
        bs2_dir = os.path.join(appdata, 'BioshockHD', 'Bioshock2')
        if not os.path.isdir(bs2_dir):
            L('Game logs   : AppData dir not found (%s)' % bs2_dir)
            return
        L('')
        L('  GAME SESSION REPORT  (%s)' % bs2_dir)
        L('-' * 70)
        # Main log
        game_log = os.path.join(bs2_dir, 'Bioshock2.log')
        script_log = os.path.join(bs2_dir, 'ScriptLog.log')
        for log_name, log_path in [('Bioshock2.log', game_log),
                                   ('ScriptLog.log', script_log)]:
            if not os.path.isfile(log_path):
                L('  %-20s: not found' % log_name)
                continue
            st = os.stat(log_path)
            mtime = datetime.datetime.fromtimestamp(st.st_mtime)
            L('  %-20s: %d bytes, last modified %s' % (
                log_name, st.st_size, mtime.strftime('%Y-%m-%d %H:%M:%S')))
            try:
                raw = open(log_path, 'r', encoding='utf-8', errors='replace').read()
                lines = [l.strip() for l in raw.strip().split('\n') if l.strip()]
                L('    Lines: %d' % len(lines))
                # Check for crash indicators
                crash_keywords = [
                    'crash', 'fatal', 'exception', 'access violation',
                    'assert', 'critical', 'gpf', 'unhandled', 'stack overflow',
                    'out of memory', 'ran out of', 'error',
                ]
                crash_lines = []
                for line in lines:
                    ll = line.lower()
                    if any(kw in ll for kw in crash_keywords):
                        crash_lines.append(line)
                if crash_lines:
                    L('    ** CRASH / ERROR INDICATORS FOUND (%d) **' % len(crash_lines))
                    for cl in crash_lines[:20]:
                        L('      %s' % cl[:200])
                # Check for clean vs dirty shutdown
                if lines:
                    last_line = lines[-1]
                    if 'closing by request' in last_line.lower():
                        L('    Last session: clean shutdown')
                    else:
                        L('    Last session: ABNORMAL EXIT (last line: %s)' %
                          last_line[:150])
                # Show last 5 lines for context
                L('    Last 5 lines:')
                for line in lines[-5:]:
                    L('      %s' % line[:200])
            except Exception as e:
                L('    Read error: %s' % e)
        # Check for crash dumps
        for f in os.listdir(bs2_dir):
            fl = f.lower()
            if fl.endswith('.dmp') or fl.endswith('.mdmp') or 'crash' in fl:
                fp = os.path.join(bs2_dir, f)
                st = os.stat(fp)
                mtime = datetime.datetime.fromtimestamp(st.st_mtime)
                L('  ** CRASH DUMP: %s (%d bytes, %s)' % (
                    f, st.st_size, mtime.strftime('%Y-%m-%d %H:%M:%S')))

    def _log_settings_summary(self, settings):
        """Write a compact summary of all mod settings to the file log."""
        if not self._file_logger:
            return
        L = self._file_logger.info
        L('-' * 70)
        L('  SETTINGS SNAPSHOT')
        L('-' * 70)
        # Spawners
        sp = {s: m for s, m in settings.get('spawners', {}).items() if m > 1}
        L('Spawners (>1x): %d maps' % len(sp))
        for s, m in sorted(sp.items()):
            L('  %-30s x%d' % (s, m))
        # Gather defense
        gd = settings.get('gather_defense', 1)
        L('Gather Defense : x%d' % gd)
        # Encounter multipliers
        enc = settings.get('encounter_mults', {})
        n_enc = sum(len(m) for m in enc.values())
        L('Encounters (>1x): %d across %d maps' % (n_enc, len(enc)))
        for stem, mults in sorted(enc.items()):
            for label, m in sorted(mults.items()):
                if m > 1:
                    L('  %-20s / %-30s x%d' % (stem, label, m))
        # Extras
        extras = settings.get('extras', [])
        L('Extras enabled (%d): %s' % (len(extras), ', '.join(extras) if extras else '(none)'))
        # Damage changes
        dmg = settings.get('damage', {})
        L('Damage overrides : %d' % len(dmg))
        for pk, pd in sorted(dmg.items()):
            L('  [%s] %s = %.1f' % (pd['section'], pd['type'], pd['amount']))
        # Damage multipliers
        dm = settings.get('dm', {})
        L('DM overrides    : %d' % len(dm))
        for pk, pd in sorted(dm.items()):
            L('  [%s] idx=%d mult=%.1f' % (pd['section'], pd['idx'], pd['multiplier']))
        # Loot tables — full detail
        loot = settings.get('loot', {})
        L('Loot tables     : %d sections modified' % len(loot))
        for sec_name, specs in sorted(loot.items()):
            L('  [%s] %d items:' % (sec_name, len(specs)))
            for sp in specs:
                L('    %-40s chance=%d min=%d max=%d' % (
                    sp.get('item', '?'), sp.get('chance', 0),
                    sp.get('min_stack', 0), sp.get('max_stack', 0)))
        # Vending
        vc = settings.get('vending', {})
        L('Vending unlock  : vending=%s  garden=%s' % (
            vc.get('unlock_vending', False), vc.get('unlock_garden', False)))
        L('Vending mult    : vending=%.2f  garden=%.2f' % (
            vc.get('vending_mult', 1.0), vc.get('garden_mult', 1.0)))
        v_costs = {k: v for k, v in vc.get('vending_costs', {}).items() if v != 1.0}
        g_costs = {k: v for k, v in vc.get('garden_costs', {}).items() if v != 1.0}
        if v_costs:
            L('Vending cost overrides (%d):' % len(v_costs))
            for ic, c in sorted(v_costs.items()):
                L('  %-50s = %.4f' % (ic, c))
        if g_costs:
            L('Garden cost overrides (%d):' % len(g_costs))
            for ic, c in sorted(g_costs.items()):
                L('  %-50s = %.4f' % (ic, c))
        L('')

    def _poll_queue(self):
        while not self.msg_queue.empty():
            try:
                msg = self.msg_queue.get_nowait()
                self.log_text.configure(state='normal')
                self.log_text.insert('end', msg)
                self.log_text.see('end')
                self.log_text.configure(state='disabled')
            except queue.Empty:
                break
        self.root.after(50, self._poll_queue)

    def _set_all_spawners(self):
        v = self.all_spawner_var.get()
        for var in self.spawner_vars.values():
            var.set(v)

    def _set_buttons(self, enabled):
        state = 'normal' if enabled else 'disabled'
        self.apply_btn.configure(state=state)
        self.restore_btn.configure(state=state)
        self.export_btn.configure(state=state)

    # ══════════════════════════════════════════════════════════════════════
    # BACKGROUND ANALYSIS
    # ══════════════════════════════════════════════════════════════════════

    def _start_analysis(self):
        t = threading.Thread(target=self._analysis_worker, daemon=True)
        t.start()

    def _analysis_worker(self):
        self._log("Analyzing maps and loading INI configs...\n")

        # Load INI configs
        try:
            from core.ini_config import load_all_configs
            ibf = PRISTINE_DIR / "ConfigINI.IBF"
            if not ibf.exists():
                ibf = CONTENT_DIR / "ConfigINI.IBF"
            if ibf.exists():
                self.ini_configs, self.ini_raw_files = load_all_configs(ibf)
                self._log("  Loaded %d INI files.\n" % len(self.ini_configs))
                self.root.after(0, self._populate_damage_tab)
                self.root.after(0, self._populate_loot_tab)
                self.root.after(0, self._populate_difficulty_tab)
                self.root.after(0, self._populate_vending_tab)
                self.root.after(0, self._populate_enemy_health_tab)
            else:
                self._log("  WARNING: ConfigINI.IBF not found.\n")
        except Exception as e:
            self._log("  ERROR loading INI configs: %s\n" % e)

        # Analyze maps for spawner counts + scripted encounters
        from core.bsm_spawn_patcher import analyze_map
        from core.bsm_script_patcher import get_map_encounter_info

        n_enc_total = 0
        for f in self.map_files:
            stem = f.stem
            try:
                pkg, spawner_data = analyze_map(str(f), verbose=False)
                spawner_counts = {cls: len(spawners) for cls, spawners in spawner_data.items()}
                self.map_data[stem] = {'spawner_counts': spawner_counts}
            except Exception as e:
                self._log("  Warning (spawners) %s: %s\n" % (stem, e))
                self.map_data[stem] = {'spawner_counts': {}}

            try:
                encounters, ai_types = get_map_encounter_info(str(f))
                if encounters:
                    self.encounter_data[stem] = encounters
                    n_enc_total += len(encounters)
            except Exception as e:
                self._log("  Warning (encounters) %s: %s\n" % (stem, e))

        n_sp = sum(sum(d['spawner_counts'].values()) for d in self.map_data.values())
        n_enc_spawns = sum(
            sum(e['spawns'] for e in enc.values())
            for enc in self.encounter_data.values()
        )
        self._log("Analysis complete: %d spawners, %d encounters (%d scripted spawns) across %d maps.\n" % (
            n_sp, n_enc_total, n_enc_spawns, len(self.map_data)))

        self.root.after(0, self._populate_repop_rows)
        self.root.after(0, self._populate_encounters_tab)

    # ══════════════════════════════════════════════════════════════════════
    # GAME DIRECTORY
    # ══════════════════════════════════════════════════════════════════════

    def _change_game_dir(self):
        from tkinter import filedialog, messagebox
        new_dir = filedialog.askdirectory(
            title="Select BioShock 2 Remastered game folder",
            initialdir=str(GAME_ROOT) if GAME_ROOT.exists() else "/"
        )
        if not new_dir:
            return
        new_path = Path(new_dir)
        if not (new_path / "ContentBaked" / "pc" / "Maps").exists():
            messagebox.showerror("Invalid Directory",
                "Could not find ContentBaked/pc/Maps inside:\n%s\n\n"
                "Select the root game folder." % new_dir)
            return
        _update_game_root(new_path)
        self.game_path_var.set(str(GAME_ROOT))
        self._log("Game directory changed to: %s\n" % GAME_ROOT)
        self.map_files = find_map_files()
        self.map_data = {}
        self._start_analysis()

    # ══════════════════════════════════════════════════════════════════════
    # BACKUP MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════

    def _ensure_backups(self):
        PRISTINE_DIR.mkdir(parents=True, exist_ok=True)
        count = 0

        existing = list(PRISTINE_DIR.glob("*.bsm"))
        if existing:
            self._log("Pristine backups: %d maps in %s\n" % (len(existing), PRISTINE_DIR))
        else:
            for f in self.map_files:
                dst = PRISTINE_DIR / f.name
                if not dst.exists():
                    shutil.copy2(str(f), str(dst))
                    count += 1

        ibf = CONTENT_DIR / "ConfigINI.IBF"
        ibf_bak = CONTENT_DIR / "ConfigINI.IBF.bak"
        ibf_dst = PRISTINE_DIR / "ConfigINI.IBF"
        if not ibf_dst.exists():
            src = ibf if ibf.exists() else ibf_bak
            if src.exists():
                shutil.copy2(str(src), str(ibf_dst))
                count += 1
                self._log("Backed up ConfigINI.IBF\n")

        lbf = CONTENT_DIR / "Localizedint.lbf"
        lbf_dst = PRISTINE_DIR / "Localizedint.lbf"
        if not lbf_dst.exists():
            if lbf.exists():
                shutil.copy2(str(lbf), str(lbf_dst))
                count += 1
                self._log("Backed up Localizedint.lbf\n")

        sg = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
        sg_dst = PRISTINE_DIR / "ShockGame.U"
        if sg.exists() and not sg_dst.exists():
            shutil.copy2(str(sg), str(sg_dst))
            count += 1
            self._log("Backed up ShockGame.U\n")

        # Backup Default.ini (Build/Final/) and DefUser.ini (System/)
        # Engine reads Default.ini from Build/Final/, NOT ContentBaked/System/
        di_src = GAME_ROOT / "Build" / "Final" / "Default.ini"
        di_dst = PRISTINE_DIR / "Default.ini"
        if di_src.exists() and not di_dst.exists():
            shutil.copy2(str(di_src), str(di_dst))
            count += 1
            self._log("Backed up Default.ini\n")

        sys_dir = CONTENT_DIR / "System"
        du_src = sys_dir / "DefUser.ini"
        du_dst = PRISTINE_DIR / "DefUser.ini"
        if du_src.exists() and not du_dst.exists():
            shutil.copy2(str(du_src), str(du_dst))
            count += 1
            self._log("Backed up DefUser.ini\n")

        if count:
            self._log("Created %d pristine backups in %s\n" % (count, PRISTINE_DIR))

    def _restore_pristine_maps(self):
        count = 0
        for f in self.map_files:
            src = PRISTINE_DIR / f.name
            if src.exists():
                shutil.copy2(str(src), str(f))
                count += 1
        return count

    # ══════════════════════════════════════════════════════════════════════
    # APPLY MOD
    # ══════════════════════════════════════════════════════════════════════

    def _apply_mod(self):
        if self.working:
            return
        self.working = True
        self._set_buttons(False)
        self.status_var.set("Applying...")
        self.status_label.configure(foreground='#fab387')

        settings = self._snapshot_all_settings()
        t = threading.Thread(target=self._apply_worker, args=(settings,), daemon=True)
        t.start()

    def _apply_worker(self, settings):
        old_stdout = sys.stdout
        sys.stdout = StdoutRedirector(self.msg_queue)
        log_path = self._open_file_log('apply')
        self._log_system_info()
        self._log_settings_summary(settings)
        try:
            self._log("\n" + "=" * 62 + "\n")
            self._log("  APPLYING MOD\n")
            self._log("=" * 62 + "\n\n")

            # Step 1: Restore pristine maps + ShockGame.U + Default.ini
            self._log("[1/4] Restoring pristine files...\n")
            n = self._restore_pristine_maps()
            sg_path = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
            sg_bak = PRISTINE_DIR / "ShockGame.U"
            if sg_bak.exists():
                shutil.copy2(str(sg_bak), str(sg_path))
                self._log("  Restored ShockGame.U\n")
            # Restore Default.ini so we always patch from clean state
            di_bak = PRISTINE_DIR / "Default.ini"
            di_game = GAME_ROOT / "Build" / "Final" / "Default.ini"
            if di_bak.exists():
                shutil.copy2(str(di_bak), str(di_game))
            self._log("  Restored %d maps.\n\n" % n)

            # Step 2: Spawner duplication (repopulation)
            spawner_maps = {s: m for s, m in settings['spawners'].items() if m > 1}
            self._log("[2/4] Duplicating repopulation spawners (%d maps)...\n" %
                      len(spawner_maps))

            # Clear old spawn backups
            sp_backup = BIOMOD_DIR / "backups" / "maps"
            if sp_backup.exists():
                for bf in sp_backup.glob("*.bsm"):
                    bf.unlink()

            spawner_total = 0
            if spawner_maps:
                from core.bsm_spawn_patcher import patch_map
                for f in self.map_files:
                    mult = spawner_maps.get(f.stem)
                    if not mult:
                        continue
                    try:
                        result = patch_map(str(f), mult, {})
                        if result:
                            spawner_total += result['new_count']
                            if self._file_logger:
                                self._file_logger.info(
                                    '  SPAWN: %-25s x%d -> +%d spawners (total %d)' % (
                                        f.stem, mult, result['new_count'],
                                        result.get('total_count', result['new_count'])))
                    except Exception as e:
                        self._log("  ERROR %s: %s\n" % (f.name, e))
                        if self._file_logger:
                            import traceback
                            self._file_logger.info('  SPAWN ERROR %s:\n%s' % (
                                f.name, traceback.format_exc()))
            self._log("  Spawners added: %d\n\n" % spawner_total)

            # Step 2b: Gather defense (AmbushSet MaxSpawned)
            gd_mult = settings.get('gather_defense', 1)
            if gd_mult > 1:
                self._log("  Patching gather defense waves (x%d)...\n" % gd_mult)
                from core.bsm_spawn_patcher import patch_ambush_sets
                gd_total = 0
                for f in self.map_files:
                    try:
                        n = patch_ambush_sets(str(f), gd_mult)
                        gd_total += n
                    except Exception as e:
                        self._log("  ERROR %s: %s\n" % (f.name, e))
                self._log("  AmbushSets patched: %d\n\n" % gd_total)

            # Step 3: Scripted encounter patching
            enc_mults = settings.get('encounter_mults', {})
            active_enc = {s: m for s, m in enc_mults.items() if m}
            enc_total = 0
            enc_maps = 0
            if active_enc:
                self._log("[3/4] Patching scripted encounters...\n")
                from core.bsm_script_patcher import patch_map_encounters
                for f in self.map_files:
                    stem = f.stem
                    mults = active_enc.get(stem, {})
                    # Only patch if at least one encounter > 1
                    boosted = {lbl: m for lbl, m in mults.items() if m > 1}
                    if not boosted:
                        continue
                    try:
                        result = patch_map_encounters(str(f), boosted)
                        if result:
                            enc_total += result['new_count']
                            enc_maps += 1
                            self._log("  %s: +%d scripted spawns\n" % (stem, result['new_count']))
                    except Exception as e:
                        self._log("  ERROR %s: %s\n" % (f.name, e))
                self._log("  Scripted spawns added: %d across %d maps\n\n" %
                          (enc_total, enc_maps))
            else:
                self._log("[3/4] Scripted encounters: no changes.\n\n")

            # Step 4: INI patches + ShockGame.U binary patches
            self._log("[4/4] Patching INI files...\n")
            self._apply_all_ini(settings)

            # ── Weapon display name renames (Localizedint.lbf) ──
            self._apply_lbf_patches(settings)

            extras_en = set(settings.get('extras', []))
            if 'summon_protector' in extras_en:
                from core.shockgame_patcher import patch_summon_protector
                sg_path = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
                res = patch_summon_protector(str(sg_path), str(PRISTINE_DIR))
                self._log("  ShockGame.U: %s\n" % res['message'])

            if 'dual_drill' in extras_en:
                from core.shockgame_patcher import patch_dual_drill
                sg_path = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
                res = patch_dual_drill(str(sg_path), str(PRISTINE_DIR))
                self._log("  ShockGame.U: %s\n" % res['message'])

            if 'flame_drill' in extras_en:
                from core.shockgame_patcher import patch_flame_drill, FLAME_EMITTERS
                sg_path = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
                style = self.flame_style_var.get()
                # Build DLCEffects.U if the selected style uses it
                emitter_info = FLAME_EMITTERS.get(style, (0, '', '', 'local'))
                if emitter_info[3] == 'dlceffects':
                    self._apply_dlc_effects()
                res = patch_flame_drill(str(sg_path), str(PRISTINE_DIR),
                                        emitter_style=style)
                self._log("  ShockGame.U: %s\n" % res['message'])

            if 'hades_grasp' in extras_en:
                from core.shockgame_patcher import patch_tk_upgrade, patch_tk_fire
                sg_path = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
                res = patch_tk_upgrade(str(sg_path), str(PRISTINE_DIR))
                self._log("  ShockGame.U: %s\n" % res['message'])
                res = patch_tk_fire(str(sg_path), str(PRISTINE_DIR))
                self._log("  ShockGame.U: %s\n" % res['message'])

            if 'winters_embrace' in extras_en:
                from core.shockgame_patcher import patch_tk_upgrade, patch_tk_freeze
                sg_path = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
                res = patch_tk_upgrade(str(sg_path), str(PRISTINE_DIR))
                self._log("  ShockGame.U: %s\n" % res['message'])
                res = patch_tk_freeze(str(sg_path), str(PRISTINE_DIR))
                self._log("  ShockGame.U: %s\n" % res['message'])

            if 'hellfire_decoy' in extras_en:
                from core.shockgame_patcher import (
                    patch_decoy_reflect, patch_decoy_fire, patch_decoy_cyclone)
                sg_path = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
                res = patch_decoy_reflect(str(sg_path), str(PRISTINE_DIR))
                self._log("  ShockGame.U: %s\n" % res['message'])
                res = patch_decoy_fire(str(sg_path), str(PRISTINE_DIR))
                self._log("  ShockGame.U: %s\n" % res['message'])
                res = patch_decoy_cyclone(str(sg_path), str(PRISTINE_DIR))
                self._log("  ShockGame.U: %s\n" % res['message'])

            if 'vampiric_thrall' in extras_en:
                from core.shockgame_patcher import patch_hypnotize_reflect
                sg_path = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
                res = patch_hypnotize_reflect(str(sg_path), str(PRISTINE_DIR))
                self._log("  ShockGame.U: %s\n" % res['message'])

            if 'ricochet_enhancement' in extras_en:
                from core.shockgame_patcher import patch_ricochet
                sg_path = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
                res = patch_ricochet(str(sg_path), str(PRISTINE_DIR))
                self._log("  ShockGame.U: %s\n" % res['message'])

            # ── Ion Laser: build DLCWeapons.U + patch Default.ini + keybind ──
            if 'ion_laser' in extras_en:
                self._apply_ion_laser(settings)

            # ── DLC Effects: register ServerPackages after ion laser ──
            # (ion laser may restore Default.ini from pristine)
            if 'flame_drill' in extras_en:
                style = self.flame_style_var.get()
                emitter_info = FLAME_EMITTERS.get(style, (0, '', '', 'local'))
                if emitter_info[3] == 'dlceffects':
                    self._register_server_package('DLCEffects')

            # ── Berserker Drill: register Weapon_Drill.ini in Default.ini ──
            # Must run AFTER ion laser to avoid pristine-based overwrite
            if 'dual_drill' in extras_en:
                self._register_drill_ini_in_default()

            # ── Summon Eleanor: AI.ini visibility fix ──
            if 'summon_eleanor' in extras_en:
                self._write_eleanor_ai_ini()
                self._register_ai_ini_in_default()
            self._log("\n")

            self._log("=" * 62 + "\n")
            self._log("  MOD APPLIED SUCCESSFULLY\n")
            self._log("=" * 62 + "\n")
            if self._log_path:
                self._log("Log saved to: %s\n" % self._log_path)
            self.root.after(0, self._on_apply_done)

        except Exception as e:
            self._log("\nFATAL ERROR: %s\n" % e)
            import traceback
            self._log(traceback.format_exc())
            if self._log_path:
                self._log("Debug log saved to: %s\n" % self._log_path)
            self.root.after(0, self._on_error)
        finally:
            self._close_file_log()
            sys.stdout = old_stdout
            self.working = False
            self.root.after(0, lambda: self._set_buttons(True))

    def _apply_all_ini(self, settings):
        from core.ibf_utils import extract_ibf, write_loose_ini, backup_ibf
        from core.ini_config import parse_ini, write_ini, set_value

        ibf_pristine = PRISTINE_DIR / "ConfigINI.IBF"
        ibf_game = CONTENT_DIR / "ConfigINI.IBF"
        ibf_bak = CONTENT_DIR / "ConfigINI.IBF.bak"

        source = None
        for p in (ibf_pristine, ibf_game, ibf_bak):
            if p.exists():
                source = p
                break
        if source is None:
            self._log("  WARNING: ConfigINI.IBF not found\n")
            return

        raw_files = extract_ibf(source)
        configs = {}
        for name, text in raw_files.items():
            configs[name] = parse_ini(text)

        # ── DamageSets.ini ───────────────────────────────────────────────
        ds_modified = False
        if 'DamageSets.ini' in configs:
            ds_entries = configs['DamageSets.ini']

            # Damage value patches
            if settings.get('damage'):
                from core.ini_config import patch_stimulus_amount
                d_count = 0
                for pkey, pdata in settings['damage'].items():
                    changed = patch_stimulus_amount(
                        ds_entries, pdata['section'], pdata['type'], pdata['amount'])
                    d_count += changed
                if d_count:
                    self._log("  DamageSets.ini: %d damage values patched\n" % d_count)
                    ds_modified = True

            # Extras: append stimuli to weapon/plasmid stimuli sets
            extras_enabled = set(settings.get('extras', []))
            if extras_enabled:
                e_count = 0
                for edef in self.EXTRAS_DEFS:
                    if edef['key'] not in extras_enabled:
                        continue
                    if not edef.get('add_stimuli'):
                        continue
                    # Support single 'section' or multiple 'sections'
                    target_secs = edef.get('sections') or ([edef['section']] if edef.get('section') else [])
                    for sec in target_secs:
                        for stim_type, amount, chance in edef['add_stimuli']:
                            new_val = '(Type=%s,Amount=%.1f,Chance=%.1f)' % (
                                stim_type, amount, chance)
                            # Find insertion point: last Stimulus line in this section
                            insert_idx = None
                            for i, (s, k, v, r) in enumerate(ds_entries):
                                if s == sec and k == 'Stimulus':
                                    insert_idx = i + 1
                            if insert_idx is not None:
                                raw = 'Stimulus=%s' % new_val
                                ds_entries.insert(insert_idx, (sec, 'Stimulus', new_val, raw))
                                e_count += 1
                if e_count:
                    self._log("  DamageSets.ini: %d extra stimuli added\n" % e_count)
                    ds_modified = True

            # Extras: patch existing stimulus amounts (fix broken values)
            if extras_enabled:
                from core.ini_config import patch_stimulus_amount
                sp_count = 0
                for edef in self.EXTRAS_DEFS:
                    if edef['key'] not in extras_enabled:
                        continue
                    for sec, stim_type, new_amt in edef.get('stimulus_patches', []):
                        sp_count += patch_stimulus_amount(
                            ds_entries, sec, stim_type, new_amt)
                if sp_count:
                    self._log("  DamageSets.ini: %d stimulus values patched\n" % sp_count)
                    ds_modified = True

            # Extras: DamageSets.ini key overrides (DamageType, MomentumScale, etc.)
            if extras_enabled:
                o_count = 0
                for edef in self.EXTRAS_DEFS:
                    if edef['key'] not in extras_enabled:
                        continue
                    overrides = edef.get('ds_overrides')
                    if not overrides:
                        continue
                    target_secs = edef.get('sections') or ([edef['section']] if edef.get('section') else [])
                    for sec in target_secs:
                        for okey, oval in overrides.items():
                            # Try to find and replace existing key in this section
                            found = False
                            for i, (s, k, v, r) in enumerate(ds_entries):
                                if s == sec and k == okey:
                                    ds_entries[i] = (s, k, oval, '%s=%s' % (k, oval))
                                    found = True
                                    o_count += 1
                                    break
                            if not found:
                                # Insert new key after last entry in this section
                                insert_idx = None
                                for i, (s, k, v, r) in enumerate(ds_entries):
                                    if s == sec:
                                        insert_idx = i + 1
                                if insert_idx is not None:
                                    ds_entries.insert(insert_idx,
                                        (sec, okey, oval, '%s=%s' % (okey, oval)))
                                    o_count += 1
                if o_count:
                    self._log("  DamageSets.ini: %d key overrides applied\n" % o_count)
                    ds_modified = True

            # Enemy Health multipliers: scale resistance AmountModification
            import re as _re
            eh_count = 0
            for _eh_friendly, _eh_set in self.ENEMY_HEALTH_SETS:
                var = self.enemy_health_vars.get(_eh_set)
                if not var:
                    continue
                mult = var.get()
                if abs(mult - 1.0) < 0.01:
                    continue
                for i, (s, k, v, r) in enumerate(ds_entries):
                    if s == _eh_set and k == 'Resistance' and 'STIMULUS_AI' in v:
                        m = _re.search(r'AmountModification=([0-9.]+)', v)
                        if m:
                            orig = float(m.group(1))
                            if orig > 0:
                                new_amt = orig / mult
                                new_v = v[:m.start(1)] + ('%.4f' % new_amt) + v[m.end(1):]
                                new_r = r[:r.find(m.group(0))] + ('AmountModification=%.4f' % new_amt) + r[r.find(m.group(0))+len(m.group(0)):]
                                ds_entries[i] = (s, k, new_v, new_r)
                                eh_count += 1
            if eh_count:
                self._log("  DamageSets.ini: %d enemy health values scaled\n" % eh_count)
                ds_modified = True

            # Extras: INI key-value patches (e.g. ResourceLimits.ini)
            if extras_enabled:
                for edef in self.EXTRAS_DEFS:
                    if edef['key'] not in extras_enabled:
                        continue
                    ini_patch = edef.get('ini_patches')
                    if not ini_patch:
                        continue
                    target_file = ini_patch['file']
                    if target_file not in configs:
                        continue
                    target_entries = configs[target_file]
                    kv = ini_patch['key_values']
                    p_count = 0
                    for i, (s, k, v, r) in enumerate(target_entries):
                        if k in kv:
                            target_entries[i] = (s, k, kv[k], r)
                            p_count += 1
                    if p_count:
                        self._log("  %s: %d values patched\n" % (target_file, p_count))

            # Extras: section-specific patches (e.g. rename FriendlyName in a section)
            if extras_enabled:
                for edef in self.EXTRAS_DEFS:
                    if edef['key'] not in extras_enabled:
                        continue
                    sp = edef.get('section_patches')
                    if not sp:
                        continue
                    target_file = sp['file']
                    if target_file not in configs:
                        continue
                    target_entries = configs[target_file]
                    p_count = 0
                    for sec, key, new_val in sp['patches']:
                        for i, (s, k, v, r) in enumerate(target_entries):
                            if s == sec and k == key:
                                target_entries[i] = (s, k, new_val, '%s=%s' % (k, new_val))
                                p_count += 1
                    if p_count:
                        self._log("  %s: %d section patches (%s)\n" % (
                            target_file, p_count, edef['key']))

        # ── Restored Content: patch LootTables, Gui, Manual ──────────────
        extras_enabled = set(settings.get('extras', []))
        restored_count = 0
        for rdef in self.RESTORED_CONTENT_DEFS:
            if rdef['key'] not in extras_enabled:
                continue

            if 'LootTables_perobjectconfig.ini' in configs:
                lt_entries = configs['LootTables_perobjectconfig.ini']

                # ── Gatherer's Garden plasmid entries ──
                if rdef.get('vending_class') and rdef.get('vending_sections'):
                    vending_line = (
                        "VendingLootSpec=(ItemClass=%s,"
                        "PickupClass=class'Pickups.MedHypo_Pickup',"
                        "StackSize=1,CostAdjustment=1,"
                        "DisplayWhenUnHacked=True,DisplayWhenHacked=True)"
                    ) % rdef['vending_class']
                    v_added = 0
                    for sec in rdef['vending_sections']:
                        insert_idx = None
                        for i, (s, k, v, r) in enumerate(lt_entries):
                            if s == sec:
                                insert_idx = i + 1
                        if insert_idx is not None:
                            lt_entries.insert(insert_idx,
                                             (sec, 'VendingLootSpec',
                                              vending_line.split('=', 1)[1],
                                              vending_line))
                            v_added += 1
                    if v_added:
                        self._log("  LootTables.ini: added %s to %d gardens\n"
                                  % (rdef['label'], v_added))
                        restored_count += v_added

                # ── El Ammo Bandito ammo entries ──
                if rdef.get('ammo_vending') and rdef.get('ammo_sections'):
                    a_added = 0
                    for sec in rdef['ammo_sections']:
                        for ammo in rdef['ammo_vending']:
                            ammo_line = (
                                "VendingLootSpec=(ItemClass=%s,"
                                "PickupClass=%s,"
                                "StackSize=%d,CostAdjustment=1,"
                                "DisplayWhenUnHacked=True,"
                                "DisplayWhenHacked=False)"
                            ) % (ammo['item'], ammo['pickup'], ammo['stack'])
                            insert_idx = None
                            for i, (s, k, v, r) in enumerate(lt_entries):
                                if s == sec:
                                    insert_idx = i + 1
                            if insert_idx is not None:
                                lt_entries.insert(
                                    insert_idx,
                                    (sec, 'VendingLootSpec',
                                     ammo_line.split('=', 1)[1],
                                     ammo_line))
                                a_added += 1
                    if a_added:
                        self._log("  LootTables.ini: added %s ammo to %d vendors\n"
                                  % (rdef['label'], len(rdef['ammo_sections'])))
                        restored_count += a_added

            # ── Gui_perobjectconfig: add training video section ──
            gui_sec = rdef.get('gui_section')
            if gui_sec and 'Gui_perobjectconfig.ini' in configs:
                gui_entries = configs['Gui_perobjectconfig.ini']
                if not any(s == gui_sec for s, k, v, r in gui_entries):
                    gui_entries.append((gui_sec, None, None, ''))
                    gui_entries.append((gui_sec, None, None,
                                        '[%s]' % gui_sec))
                    for gk, gv in rdef['gui_entries'].items():
                        raw = '%s=%s' % (gk, gv)
                        gui_entries.append((gui_sec, gk, gv, raw))
                    self._log("  Gui.ini: added [%s] section\n" % gui_sec)

            # ── Plasmids_perobjectconfig: set Track/Color/Level ──
            pcfg = rdef.get('plasmid_config')
            if pcfg and 'Plasmids_perobjectconfig.ini' in configs:
                pl_entries = configs['Plasmids_perobjectconfig.ini']
                pl_sec = pcfg['section']
                if not any(s == pl_sec for s, k, v, r in pl_entries):
                    pl_entries.append((pl_sec, None, None, ''))
                    pl_entries.append((pl_sec, None, None,
                                       '[%s]' % pl_sec))
                    for pk, pv in pcfg.items():
                        if pk == 'section':
                            continue
                        raw = '%s=%s' % (pk, pv)
                        pl_entries.append((pl_sec, pk, pv, raw))
                    self._log("  Plasmids.ini: added [%s] (Track=%s)\n"
                              % (pl_sec, pcfg.get('Track', '?')))

            # ── Manual_perobjectconfig: add description section ──
            man_sec = rdef.get('manual_section')
            if man_sec and 'Manual_perobjectconfig.ini' in configs:
                man_entries = configs['Manual_perobjectconfig.ini']
                if not any(s == man_sec for s, k, v, r in man_entries):
                    man_entries.append((man_sec, None, None, ''))
                    man_entries.append((man_sec, None, None,
                                        '[%s]' % man_sec))
                    for mk, mv in rdef['manual_entries'].items():
                        raw = '%s=%s' % (mk, mv)
                        man_entries.append((man_sec, mk, mv, raw))
                    for line in rdef['manual_text']:
                        k, v = line.split('=', 1)
                        man_entries.append((man_sec, k, v, line))
                    self._log("  Manual.ini: added [%s] section\n" % man_sec)

        if restored_count:
            self._log("  Restored content: %d vending entries added\n"
                      % restored_count)

        # ── DamageMultiplierSet.ini ──────────────────────────────────────
        if 'DamageMultiplierSet.ini' in configs and settings.get('dm'):
            dm_entries = configs['DamageMultiplierSet.ini']
            dm_count = 0
            # Rebuild multiplier entries
            import re
            for pkey, pdata in settings['dm'].items():
                sec = pdata['section']
                idx = pdata['idx']
                new_mult = pdata['multiplier']
                # Find the idx-th Multipliers entry in this section
                count = 0
                for i, (s, k, v, r) in enumerate(dm_entries):
                    if s == sec and k == 'Multipliers':
                        if count == idx:
                            new_v = re.sub(r'Multiplier\s*=\s*[0-9.]+',
                                          'Multiplier=%.1f' % new_mult, v)
                            if new_v != v:
                                dm_entries[i] = (s, k, new_v, r)
                                dm_count += 1
                            break
                        count += 1
            if dm_count:
                self._log("  DamageMultiplierSet.ini: %d multipliers patched\n" % dm_count)

        # ── LootTables_perobjectconfig.ini ───────────────────────────────
        if 'LootTables_perobjectconfig.ini' in configs and settings.get('loot'):
            from core.ini_config import rebuild_loot_table
            lt_entries = configs['LootTables_perobjectconfig.ini']
            l_count = 0
            for sec_name, specs in settings['loot'].items():
                rebuild_loot_table(lt_entries, sec_name, specs)
                l_count += 1
            if l_count:
                self._log("  LootTables.ini: %d tables rebuilt\n" % l_count)

        # ── Vending / Gatherer's Garden ───────────────────────────────
        vending_cfg = settings.get('vending', {})
        if 'LootTables_perobjectconfig.ini' in configs:
            lt = configs['LootTables_perobjectconfig.ini']
            from core.ini_config import (patch_vending_unlock_all,
                                         patch_vending_costs,
                                         patch_vending_item_cost)

            # Unlock all items
            uv = vending_cfg.get('unlock_vending', False)
            ug = vending_cfg.get('unlock_garden', False)
            if uv or ug:
                va, ga = patch_vending_unlock_all(lt, uv, ug)
                if va:
                    self._log("  LootTables.ini: %d vending items unlocked\n" % va)
                if ga:
                    self._log("  LootTables.ini: %d garden items unlocked\n" % ga)

            # Per-item cost overrides (applied before multipliers)
            vi_count = 0
            for ic, cost in vending_cfg.get('vending_costs', {}).items():
                if cost != 1.0:
                    vi_count += patch_vending_item_cost(lt, ic, cost, 'vending')
            for ic, cost in vending_cfg.get('garden_costs', {}).items():
                if cost != 1.0:
                    vi_count += patch_vending_item_cost(lt, ic, cost, 'growth')
            if vi_count:
                self._log("  LootTables.ini: %d vending item costs set\n" % vi_count)

            # Global price multipliers
            vm = vending_cfg.get('vending_mult', 1.0)
            gm = vending_cfg.get('garden_mult', 1.0)
            v_scaled = 0
            if vm != 1.0:
                v_scaled += patch_vending_costs(lt, vm, 'vending')
            if gm != 1.0:
                v_scaled += patch_vending_costs(lt, gm, 'growth')
            if v_scaled:
                self._log("  LootTables.ini: %d vending prices scaled "
                          "(Vending x%.1f, Garden x%.1f)\n" % (v_scaled, vm, gm))

        # ── Inventory.ini (FriendlyName for restored content items) ────
        inv_sections = {}
        for rdef in self.RESTORED_CONTENT_DEFS:
            if rdef['key'] not in extras_enabled:
                continue
            inv_cfg = rdef.get('inventory_config')
            if inv_cfg:
                sec = inv_cfg['section']
                inv_sections[sec] = {k: v for k, v in inv_cfg.items()
                                     if k != 'section'}

        if inv_sections:
            inv_lines = []
            for sec, kv in inv_sections.items():
                inv_lines.append('[%s]' % sec)
                for k, v in kv.items():
                    inv_lines.append('%s=%s' % (k, v))
                inv_lines.append('')
            inv_text = '\n'.join(inv_lines)
            inv_path = CONTENT_DIR / "System" / "Inventory.ini"
            inv_path.parent.mkdir(parents=True, exist_ok=True)
            with open(inv_path, 'w', encoding='utf-16-le') as out:
                out.write('\ufeff')
                out.write(inv_text)
            self._log("  Inventory.ini: wrote FriendlyName for %d items\n"
                      % len(inv_sections))

        # ── Plasmids.ini (Track / Color / Level for restored plasmids) ──
        plasm_sections = {}
        for rdef in self.RESTORED_CONTENT_DEFS:
            if rdef['key'] not in extras_enabled:
                continue
            pcfg = rdef.get('plasmid_config')
            if pcfg:
                sec = pcfg['section']
                plasm_sections[sec] = {k: v for k, v in pcfg.items()
                                       if k != 'section'}

        if plasm_sections:
            pl_lines = []
            for sec, kv in plasm_sections.items():
                pl_lines.append('[%s]' % sec)
                for k, v in kv.items():
                    pl_lines.append('%s=%s' % (k, v))
                pl_lines.append('')
            pl_text = '\n'.join(pl_lines)
            pl_path = CONTENT_DIR / "System" / "Plasmids.ini"
            pl_path.parent.mkdir(parents=True, exist_ok=True)
            with open(pl_path, 'w', encoding='utf-16-le') as out:
                out.write('\ufeff')
                out.write(pl_text)
            self._log("  Plasmids.ini: configured %d restored plasmids\n"
                      % len(plasm_sections))

        # ── Audit: detailed section counts for the file log ─────────────
        if self._file_logger:
            import re as _re
            L = self._file_logger.info
            L('')
            L('-' * 70)
            L('  INI AUDIT (file log only)')
            L('-' * 70)
            for fname, elist in sorted(configs.items()):
                n_entries = sum(1 for s, k, v, r in elist if k is not None)
                n_secs = len(set(s for s, k, v, r in elist if s))
                L('  %-40s %4d entries in %3d sections' % (fname, n_entries, n_secs))

            if 'LootTables_perobjectconfig.ini' in configs:
                _item_re = _re.compile(r"ItemClass=class'([^']+)'")
                _ss_re = _re.compile(r'SupplySize=(\d+)')
                _ca_re = _re.compile(r'CostAdjustment=([\d.]+)')
                _lt = configs['LootTables_perobjectconfig.ini']

                # Section summary
                sec_counts = {}
                for s, k, v, r in _lt:
                    if k == 'VendingLootSpec' and v:
                        sec_counts.setdefault(s, 0)
                        sec_counts[s] += 1
                L('')
                L('  Vending/Growth/Ammo section item counts:')
                for sec in sorted(sec_counts):
                    sl = sec.lower()
                    if 'test' in sl:
                        continue
                    if 'growth' in sl:
                        tag = 'GROWTH'
                    elif 'ammo' in sl:
                        tag = 'AMMO'
                    elif 'circus' in sl:
                        tag = 'CIRCUS'
                    elif 'vending' in sl:
                        tag = 'VENDING'
                    else:
                        tag = 'OTHER'
                    L('    %-40s %3d items  [%s]' % (sec, sec_counts[sec], tag))

                # Detailed per-item Growth audit
                L('')
                L('  GROWTH SECTION DETAIL (every item):')
                for s, k, v, r in _lt:
                    if k != 'VendingLootSpec' or not v:
                        continue
                    sl = s.lower()
                    if 'growth' not in sl or 'test' in sl:
                        continue
                    im = _item_re.search(v)
                    ss = _ss_re.search(v)
                    ca = _ca_re.search(v)
                    duh = 'DisplayWhenUnHacked=True' in v
                    dh = 'DisplayWhenHacked=True' in v
                    flags = []
                    if not ss:
                        flags.append('NO_SUPPLY')
                    if not ca:
                        flags.append('NO_COST')
                    if not duh:
                        flags.append('HIDDEN_UNHACKED')
                    flag_str = ' *** %s ***' % ','.join(flags) if flags else ''
                    L('    [%-30s] %-50s SS=%-3s CA=%-8s UnH=%s H=%s%s' % (
                        s,
                        im.group(1) if im else '???',
                        ss.group(1) if ss else 'NONE',
                        ca.group(1) if ca else 'NONE',
                        duh, dh, flag_str))

                # Sample vending entry for format comparison
                L('')
                L('  SAMPLE VENDING ENTRY (first non-test Vending section):')
                shown = False
                for s, k, v, r in _lt:
                    if k == 'VendingLootSpec' and v and 'Vending' in s and 'Test' not in s:
                        L('    [%s]' % s)
                        L('    RAW: %s' % ('%s=%s' % (k, v))[:200])
                        shown = True
                        break
                if not shown:
                    L('    (none found)')

                # Sample growth entry for format comparison
                L('')
                L('  SAMPLE GROWTH ENTRY (first non-test Growth section):')
                shown = False
                for s, k, v, r in _lt:
                    if k == 'VendingLootSpec' and v and 'Growth' in s and 'Test' not in s:
                        L('    [%s]' % s)
                        L('    RAW: %s' % ('%s=%s' % (k, v))[:200])
                        shown = True
                        break
                if not shown:
                    L('    (none found)')

            # DamageSets audit: dump plasmid/extras stimuli sections post-patch
            if 'DamageSets.ini' in configs:
                _ds = configs['DamageSets.ini']
                _audit_prefixes = (
                    'ElectroBolt', 'Incinerat', 'WinterBlast', 'Telekinesis',
                    'CycloneTrap', 'Swarm', 'SecurityBeacon', 'SummonProtector',
                    'Decoy', 'Scout', 'Hypnotize', 'SecurityCommand',
                )
                L('')
                L('  DAMAGESETS AUDIT (plasmid stimuli post-patch):')
                _seen_secs = set()
                for s, k, v, r in _ds:
                    if s and k == 'Stimulus' and any(s.startswith(p) for p in _audit_prefixes):
                        if s not in _seen_secs:
                            _seen_secs.add(s)
                            L('    [%s]' % s)
                        L('      %s' % v)
                if not _seen_secs:
                    L('    (no matching sections)')

            L('')

        # ── Berserker Drill (Dual Drill Power) ────────────────────────────
        extras_enabled_drill = set(settings.get('extras', []))
        if 'dual_drill' in extras_enabled_drill:
            self._apply_dual_drill(configs, extras_enabled_drill)

        # ── Write all INI files as loose files ───────────────────────────
        system_dir = CONTENT_DIR / "System"
        system_dir.mkdir(parents=True, exist_ok=True)

        for filename, raw_text in raw_files.items():
            if filename in configs:
                text = write_ini(configs[filename])
            else:
                text = raw_text
            out_path = system_dir / filename
            with open(out_path, 'w', encoding='utf-16-le') as out:
                out.write('\ufeff')  # BOM
                out.write(text)

        # Log output file sizes
        if self._file_logger:
            L = self._file_logger.info
            L('')
            L('  OUTPUT INI FILES:')
            for filename in sorted(raw_files.keys()):
                out_path = system_dir / filename
                if out_path.exists():
                    L('    %-40s %8d bytes' % (filename, out_path.stat().st_size))

        # Rename IBF so engine uses loose files
        if ibf_game.exists() and not ibf_bak.exists():
            shutil.move(str(ibf_game), str(ibf_bak))
            self._log("  ConfigINI.IBF -> .bak\n")
        elif ibf_game.exists():
            os.remove(str(ibf_game))

        self._log("  INI files written to %s\n" % system_dir)

    # ══════════════════════════════════════════════════════════════════════
    # LOCALIZATION — LBF PATCHING (weapon/ammo display names)
    # ══════════════════════════════════════════════════════════════════════

    def _apply_lbf_patches(self, settings):
        """Patch weapon/ammo display names in Localizedint.lbf."""
        import re
        from core.ibf_utils import extract_ibf, repack_ibf

        extras_enabled = set(settings.get('extras', []))
        # Collect all lbf_patches from enabled weapon mods
        all_patches = []  # (int_file, section, key, new_value)
        for edef in self.EXTRAS_DEFS:
            if edef['key'] not in extras_enabled:
                continue
            for patch in edef.get('lbf_patches', []):
                all_patches.append(patch)

        if not all_patches:
            return

        # Find pristine LBF
        lbf_pristine = PRISTINE_DIR / "Localizedint.lbf"
        lbf_game = CONTENT_DIR / "Localizedint.lbf"
        source = lbf_pristine if lbf_pristine.exists() else lbf_game
        if not source.exists():
            self._log("  LBF: Localizedint.lbf not found, skipping renames\n")
            return

        lbf_files = extract_ibf(str(source))

        # Group patches by int_file
        by_file = {}
        for int_file, section, key, new_val in all_patches:
            by_file.setdefault(int_file, []).append((section, key, new_val))

        p_count = 0
        for int_file, patches in by_file.items():
            if int_file not in lbf_files:
                self._log("  LBF: %s not found in archive\n" % int_file)
                continue
            text = lbf_files[int_file]
            for section, key, new_val in patches:
                # Match [Section] ... Key="old_value" and replace value
                # .int files use Key="value" (with quotes)
                pattern = (r'(\[' + re.escape(section) + r'\][^\[]*?'
                           + re.escape(key) + r'=)"[^"]*"')
                new_text, n = re.subn(pattern, r'\g<1>"' + new_val + '"',
                                      text, count=1, flags=re.DOTALL)
                if n:
                    text = new_text
                    p_count += 1
            lbf_files[int_file] = text

        if p_count:
            repack_ibf(lbf_files, str(lbf_game))
            self._log("  LBF: %d display names patched in Localizedint.lbf\n"
                      % p_count)

    # ══════════════════════════════════════════════════════════════════════
    # ION LASER — DLC WEAPON TRANSPLANT
    # ══════════════════════════════════════════════════════════════════════

    def _apply_ion_laser(self, settings):
        """Build DLCWeapons.U, patch Default.ini for ServerPackages, set keybind."""
        from core.dlc_package_builder import build_dlc_weapons_package

        minerva = MAPS_DIR / "Minerva_A.bsm"
        if not minerva.exists():
            # Try pristine backup
            minerva = PRISTINE_DIR / "Minerva_A.bsm"
        if not minerva.exists():
            self._log("  Ion Laser: SKIP — Minerva_A.bsm not found\n")
            return

        scripts_dir = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc"
        dlc_pkg = scripts_dir / "DLCWeapons.U"

        # 1) Build the DLCWeapons.U package
        self._log("  Ion Laser: building DLCWeapons.U...\n")
        try:
            build_dlc_weapons_package(str(minerva), str(dlc_pkg))
            self._log("  Ion Laser: DLCWeapons.U written (%d KB)\n"
                      % (dlc_pkg.stat().st_size // 1024))
        except Exception as e:
            self._log("  Ion Laser: FAILED to build package — %s\n" % e)
            return

        # 2) Patch Default.ini to add ServerPackages=DLCWeapons
        #    The engine reads Build/Final/Default.ini (ASCII), NOT ContentBaked.
        default_ini = GAME_ROOT / "Build" / "Final" / "Default.ini"
        pristine_di = PRISTINE_DIR / "Default.ini"
        # Always patch from pristine to avoid double-add
        src = pristine_di if pristine_di.exists() else default_ini
        if src.exists():
            raw = open(str(src), 'rb').read()
            if raw[:2] == b'\xff\xfe':
                text = raw[2:].decode('utf-16-le')
                enc = 'utf-16-le'
            else:
                text = raw.decode('utf-8', errors='replace')
                enc = 'utf-8'

            marker = 'ServerPackages=DLCWeapons'
            if marker not in text:
                # Insert after last ServerPackages line
                lines = text.split('\n')
                last_sp = -1
                for i, line in enumerate(lines):
                    if line.strip().startswith('ServerPackages='):
                        last_sp = i
                if last_sp >= 0:
                    lines.insert(last_sp + 1, marker)
                    text = '\n'.join(lines)
                    with open(str(default_ini), 'wb') as f:
                        if enc == 'utf-16-le':
                            f.write(b'\xff\xfe')
                        f.write(text.encode(enc))
                    self._log("  Default.ini: added %s\n" % marker)
                else:
                    self._log("  Default.ini: WARNING — no ServerPackages= found\n")
            else:
                if str(src) != str(default_ini):
                    shutil.copy2(str(src), str(default_ini))
                self._log("  Default.ini: ServerPackages=DLCWeapons already present\n")

        # 3) Patch F12 keybind to give the weapon
        self._patch_keybind('F12', 'GiveWeapon DLCWeapons.PlayerLaserGun')
        self._log("  Ion Laser: F12 keybind set\n")

    # ══════════════════════════════════════════════════════════════════════
    # DLC EFFECTS — EMITTER TRANSPLANT FOR FLAME DRILL
    # ══════════════════════════════════════════════════════════════════════

    def _apply_dlc_effects(self):
        """Build DLCEffects.U from Abyss.bsm and register ServerPackages."""
        from core.dlc_effects_builder import build_dlc_effects_package

        abyss = MAPS_DIR / "Abyss.bsm"
        if not abyss.exists():
            abyss = PRISTINE_DIR / "Abyss.bsm"
        if not abyss.exists():
            self._log("  DLC Effects: SKIP — Abyss.bsm not found\n")
            return

        scripts_dir = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc"
        dlc_pkg = scripts_dir / "DLCEffects.U"

        # 1) Build the DLCEffects.U package
        self._log("  DLC Effects: building DLCEffects.U...\n")
        try:
            build_dlc_effects_package(str(abyss), str(dlc_pkg))
            self._log("  DLC Effects: DLCEffects.U written (%d KB)\n"
                      % (dlc_pkg.stat().st_size // 1024))
        except Exception as e:
            self._log("  DLC Effects: FAILED to build package — %s\n" % e)
            return

        # NOTE: ServerPackages=DLCEffects is registered separately in the apply
        # flow AFTER ion_laser, which may restore Default.ini from pristine.

    def _register_server_package(self, pkg_name):
        """Add ServerPackages=<pkg_name> to Build/Final/Default.ini."""
        default_ini = GAME_ROOT / "Build" / "Final" / "Default.ini"
        if not default_ini.exists():
            self._log("  Default.ini: not found, cannot register %s\n" % pkg_name)
            return
        raw = open(str(default_ini), 'rb').read()
        if raw[:2] == b'\xff\xfe':
            text = raw[2:].decode('utf-16-le')
            enc = 'utf-16-le'
        else:
            text = raw.decode('utf-8', errors='replace')
            enc = 'utf-8'

        marker = 'ServerPackages=%s' % pkg_name
        if marker in text:
            self._log("  Default.ini: %s already present\n" % marker)
            return
        lines = text.split('\n')
        last_sp = -1
        for i, line in enumerate(lines):
            if line.strip().startswith('ServerPackages='):
                last_sp = i
        if last_sp >= 0:
            lines.insert(last_sp + 1, marker)
            text = '\n'.join(lines)
            with open(str(default_ini), 'wb') as f:
                if enc == 'utf-16-le':
                    f.write(b'\xff\xfe')
                f.write(text.encode(enc))
            self._log("  Default.ini: added %s\n" % marker)
        else:
            self._log("  Default.ini: WARNING — no ServerPackages= found\n")

    def _patch_keybind(self, key, cmd):
        """Patch a keybind into DefUser.ini and User.ini (AppData)."""
        import re

        # ── DefUser.ini (game template) ──
        defuser = CONTENT_DIR / "System" / "DefUser.ini"
        pristine_du = PRISTINE_DIR / "DefUser.ini"
        src = pristine_du if pristine_du.exists() else defuser
        if src.exists():
            raw = open(str(src), 'rb').read()
            if raw[:2] == b'\xff\xfe':
                text = raw[2:].decode('utf-16-le')
            else:
                text = raw.decode('utf-8', errors='replace')
            # Replace all occurrences of "KEY=" or "KEY=<anything>"
            pattern = re.compile(r'^(%s)=.*$' % re.escape(key), re.MULTILINE)
            new_line = '%s=%s' % (key, cmd)
            text, n = pattern.subn(new_line, text)
            if n:
                with open(str(defuser), 'wb') as f:
                    f.write(b'\xff\xfe')
                    f.write(text.encode('utf-16-le'))
                self._log("  DefUser.ini: set %s=%s (%d entries)\n" % (key, cmd, n))

        # ── User.ini (AppData — the file the game actually reads) ──
        user_ini = os.path.join(
            os.environ.get('APPDATA', ''), 'BioshockHD', 'Bioshock2', 'User.ini')
        if os.path.isfile(user_ini):
            raw = open(user_ini, 'rb').read()
            if raw[:2] == b'\xff\xfe':
                enc = 'utf-16-le'
                text = raw[2:].decode(enc)
            else:
                enc = 'utf-8'
                text = raw.decode(enc, errors='replace')
            pattern = re.compile(r'^(%s)=.*$' % re.escape(key), re.MULTILINE)
            new_line = '%s=%s' % (key, cmd)
            text, n = pattern.subn(new_line, text)
            if n:
                with open(user_ini, 'wb') as f:
                    if enc == 'utf-16-le':
                        f.write(b'\xff\xfe')
                    f.write(text.encode(enc))
                self._log("  User.ini: set %s=%s (%d entries)\n" % (key, cmd, n))

    # ══════════════════════════════════════════════════════════════════════
    # BERSERKER DRILL — DUAL DRILL POWER ENHANCEMENT
    # ══════════════════════════════════════════════════════════════════════

    # Drill damage/config values: (section, key_or_stim_type, original, modded)
    DUAL_DRILL_DAMAGE = {
        # DamageSets.ini — direct damage values
        'spin_dmg': {
            'file': 'DamageSets.ini',
            'section': 'DrillSpin_StimuliSet',
            'stim_type': 'STIMULUS_AIDrill',
            'amount': 50.0,     # stock 15
        },
        'swing_dmg': {
            'file': 'DamageSets.ini',
            'section': 'DrillSwing_StimuliSet',
            'stim_type': 'STIMULUS_AIDrill',
            'amount': 100.0,    # stock 40
        },
        'dash_drill': {
            'file': 'DamageSets.ini',
            'section': 'PlayerDashImpactStimuliSet',
            'stim_type': 'STIMULUS_AIDaddyDash',
            'amount': 100.0,    # stock 50
        },
        'dash_ap': {
            'file': 'DamageSets.ini',
            'section': 'PlayerDashImpactStimuliSet',
            'stim_type': 'STIMULUS_AIAntiPersonnel',
            'amount': 60.0,     # stock 30
        },
    }

    # DamageMultiplierSet.ini — headshot multipliers for drill attacks
    DUAL_DRILL_MULTIPLIERS = {
        'spin_head': {
            'section': 'AggressorDamageMultiplierSet',
            'stim_set': 'DrillSpin_StimuliSet',
            'new_mult': 2.0,    # stock 1.0
        },
        'swing_head': {
            'section': 'AggressorDamageMultiplierSet',
            'stim_set': 'DrillSwing_StimuliSet',
            'new_mult': 2.5,    # stock 1.0
        },
    }

    # Weapon_Drill.ini — Drill class config overrides
    # Section: [ShockGame.Drill]  (config(Weapon_Drill))
    DUAL_DRILL_CONFIG = {
        'MovementSpeedScalar': '1.4',        # stock ~1.0, faster drilling movement
        'LookSpeedScalar': '1.2',            # stock ~1.0, smoother look while drilling
        'DashAmmoCost': '15',                # stock ~30, cheaper dashes
        'ShieldDirectionThreshold': '0.3',   # stock ~0.5, wider shield arc (lower=wider)
        'ShieldDistanceThreshold': '600.0',  # stock ~400, larger shield range
        'BounceVelocityFactor': '1.5',       # stock ~1.0, stronger projectile reflection
        'MinTimeBetweenMaterialChanges': '0.05',  # stock ~0.1, snappier FX
    }

    # Difficulty_perobjectconfig.ini — fuel economy
    DUAL_DRILL_DIFFICULTY = {
        'section': 'DrillAmmoToEaseTable',
        'values': {
            # EaseValue -> new ammo amounts (stock: 0/100/150/200/275)
            '0': {'Low': '150', 'Normal': '150', 'High': '150'},
            '1': {'Low': '225', 'Normal': '225', 'High': '225'},
            '2': {'Low': '300', 'Normal': '300', 'High': '300'},
            '3': {'Low': '400', 'Normal': '400', 'High': '400'},
        },
    }

    # AI.ini — SummonedBigSister ControlMood fix
    # BaseShockAI declares config(AI), so BigSister reads ControlMood
    # from AI.ini.  BigSisterCommanderAction only calls Teleport(true)
    # (which executes SetHidden(false)) when ControlMood == MOOD_Friendly.
    # Without this, the summoned Eleanor stays hidden/invisible.
    ELEANOR_AI_MAPS = [
        'Abyss', 'Eden', 'Eden_CellBlock', 'Education', 'Gallery',
        'GalleryCarousel', 'Ghetto', 'GhettoMarket', 'Gulag',
        'Minerva_A', 'Minerva_B', 'Minerva_C', 'Prelude-2', 'PreludePool',
        'Redlight', 'RedlightChurch', 'WelcomeBack', 'WelcomeBackMaintenance',
    ]

    # Flame Drill — OnFiredEffects entries appended to Weapon_Drill.ini
    # Uses the FlameThrowerTestB emitter (3 SpriteEmitters) from FXClass in
    # ShockGame.U.  EA_Reset restarts the emitter each fire tick so the
    # flame persists while drilling.  Attached to the Drill bone.
    FLAME_DRILL_EFFECTS = [
        (
            'OnFiredEffects='
            '(EmitterClass=class\'FXClass.FlameThrowerTestB\','
            'AttachmentBone="Drill",'
            'LocationOffset=(X=0.0,Y=0.0,Z=0.0),'
            'RotationOffset=(Pitch=0,Yaw=0,Roll=0),'
            'AmmoType="",'
            'UpgradeType=US_All,'
            'EmitterAction=EA_Reset)'
        ),
    ]

    def _apply_dual_drill(self, configs, extras_enabled):
        """Apply Berserker Drill enhancements to parsed INI configs dict.

        Modifies DamageSets, DamageMultiplierSet, and Difficulty configs
        in-place.  Also writes Weapon_Drill.ini as a loose file and
        registers it in Default.ini.
        """
        import re

        changes = 0

        # ── 1) DamageSets.ini — boost drill damage values ────────────────
        if 'DamageSets.ini' in configs:
            ds = configs['DamageSets.ini']
            for dkey, ddef in self.DUAL_DRILL_DAMAGE.items():
                if ddef['file'] != 'DamageSets.ini':
                    continue
                sec = ddef['section']
                stim = ddef['stim_type']
                new_amt = ddef['amount']
                for i, (s, k, v, r) in enumerate(ds):
                    if s == sec and k == 'Stimulus' and v and stim in v:
                        new_v = re.sub(
                            r'Amount\s*=\s*[0-9.]+',
                            'Amount=%.1f' % new_amt, v)
                        if new_v != v:
                            ds[i] = (s, k, new_v, r)
                            changes += 1
            if changes:
                self._log("  Berserker Drill: %d DamageSets values patched\n"
                          % changes)

        # ── 2) DamageMultiplierSet.ini — headshot multipliers ────────────
        dm_changes = 0
        if 'DamageMultiplierSet.ini' in configs:
            dm = configs['DamageMultiplierSet.ini']
            for mkey, mdef in self.DUAL_DRILL_MULTIPLIERS.items():
                sec = mdef['section']
                stim_set = mdef['stim_set']
                new_mult = mdef['new_mult']
                for i, (s, k, v, r) in enumerate(dm):
                    if s == sec and k == 'Multipliers' and v and stim_set in v:
                        new_v = re.sub(
                            r'Multiplier\s*=\s*[0-9.]+',
                            'Multiplier=%.1f' % new_mult, v)
                        if new_v != v:
                            dm[i] = (s, k, new_v, r)
                            dm_changes += 1
            if dm_changes:
                self._log("  Berserker Drill: %d headshot multipliers boosted\n"
                          % dm_changes)

        # ── 3) Difficulty_perobjectconfig.ini — fuel economy ─────────────
        fuel_changes = 0
        dconf = self.DUAL_DRILL_DIFFICULTY
        if 'Difficulty_perobjectconfig.ini' in configs:
            diff = configs['Difficulty_perobjectconfig.ini']
            sec = dconf['section']
            for i, (s, k, v, r) in enumerate(diff):
                if s == sec and k == 'Entries' and v:
                    for ease_val, diffs in dconf['values'].items():
                        if 'EaseValue=%s' % ease_val in v:
                            for diff_name, new_val in diffs.items():
                                pat = r'%s\s*=\s*[0-9.]+' % diff_name
                                new_v = re.sub(pat, '%s=%s' % (diff_name, new_val), v)
                                if new_v != v:
                                    v = new_v
                                    fuel_changes += 1
                            if fuel_changes:
                                diff[i] = (s, k, v, r)
            if fuel_changes:
                self._log("  Berserker Drill: fuel capacity increased "
                          "(%d values)\n" % fuel_changes)

        # ── 4) Weapon_Drill.ini — class config overrides ─────────────────
        self._write_drill_ini(extras_enabled)

        total = changes + dm_changes + fuel_changes + len(self.DUAL_DRILL_CONFIG)
        self._log("  Berserker Drill: APPLIED (%d total modifications)\n" % total)

    def _write_drill_ini(self, extras_enabled):
        """Write Weapon_Drill.ini with config overrides from enabled extras.

        Combines Berserker Drill config vars and Flame Drill OnFiredEffects
        into a single [ShockGame.Drill] section.
        """
        system_dir = CONTENT_DIR / "System"
        system_dir.mkdir(parents=True, exist_ok=True)
        drill_ini_path = system_dir / "Weapon_Drill.ini"

        lines = ['[ShockGame.Drill]']
        count = 0

        if 'dual_drill' in extras_enabled:
            for k, v in self.DUAL_DRILL_CONFIG.items():
                lines.append('%s=%s' % (k, v))
                count += 1

        if 'flame_drill' in extras_enabled:
            for entry in self.FLAME_DRILL_EFFECTS:
                lines.append(entry)
                count += 1
            self._log("  Flame Drill: %d OnFiredEffects entries added\n" % len(
                self.FLAME_DRILL_EFFECTS))

        drill_text = '\n'.join(lines) + '\n'
        with open(str(drill_ini_path), 'w', encoding='utf-16-le') as f:
            f.write('\ufeff')
            f.write(drill_text)
        self._log("  Weapon_Drill.ini: wrote %d entries\n" % count)

    def _register_drill_ini_in_default(self):
        """Register Weapon_Drill.ini in Default.ini's [Perobjectconfig] section.

        Must be called AFTER _apply_ion_laser to avoid overwrite conflicts,
        since ion laser also patches Default.ini from pristine.
        Reads from the CURRENT Default.ini (which may already have ion laser
        changes) and appends the PerObjIniFile entry.
        """
        default_ini = GAME_ROOT / "Build" / "Final" / "Default.ini"
        if not default_ini.exists():
            return
        raw = open(str(default_ini), 'rb').read()
        if raw[:2] == b'\xff\xfe':
            text = raw[2:].decode('utf-16-le')
            enc = 'utf-16-le'
        else:
            text = raw.decode('utf-8', errors='replace')
            enc = 'utf-8'

        marker = 'PerObjIniFile=Weapon_Drill.ini'
        if marker not in text:
            ini_lines = text.split('\n')
            last_poi = -1
            for i, line in enumerate(ini_lines):
                if line.strip().startswith('PerObjIniFile='):
                    last_poi = i
            if last_poi >= 0:
                ini_lines.insert(last_poi + 1, marker)
                text = '\n'.join(ini_lines)
                with open(str(default_ini), 'wb') as f:
                    if enc == 'utf-16-le':
                        f.write(b'\xff\xfe')
                    f.write(text.encode(enc))
                self._log("  Default.ini: registered %s\n" % marker)

    def _write_eleanor_ai_ini(self):
        """Write AI.ini setting ControlMood=MOOD_Friendly for SummonedBigSister.

        BaseShockAI declares config(AI), so all AI pawn sub-classes —
        including BigSister — read ``var config`` variables from AI.ini.
        The BigSisterCommanderAction only calls Teleport(true), which
        executes SetHidden(false) to make Eleanor visible, when
        ControlMood == MOOD_Friendly.  Without this config the summoned
        Eleanor stays invisible because ControlMood defaults to MOOD_None.
        """
        system_dir = CONTENT_DIR / "System"
        system_dir.mkdir(parents=True, exist_ok=True)
        ai_ini_path = system_dir / "AI.ini"

        lines = []
        for map_name in self.ELEANOR_AI_MAPS:
            lines.append('[%s.SummonedBigSister]' % map_name)
            lines.append('ControlMood=MOOD_Friendly')
            lines.append('')

        with open(str(ai_ini_path), 'w', encoding='utf-16-le') as f:
            f.write('\ufeff')
            f.write('\n'.join(lines))
        self._log("  AI.ini: ControlMood=MOOD_Friendly for %d maps\n"
                  % len(self.ELEANOR_AI_MAPS))

    def _register_ai_ini_in_default(self):
        """Register AI.ini in Default.ini [Perobjectconfig] section.

        Must be called AFTER _apply_ion_laser (which may restore
        Default.ini from pristine) to avoid overwrite conflicts.
        """
        default_ini = GAME_ROOT / "Build" / "Final" / "Default.ini"
        if not default_ini.exists():
            return
        raw = open(str(default_ini), 'rb').read()
        if raw[:2] == b'\xff\xfe':
            text = raw[2:].decode('utf-16-le')
            enc = 'utf-16-le'
        else:
            text = raw.decode('utf-8', errors='replace')
            enc = 'utf-8'

        marker = 'PerObjIniFile=AI.ini'
        if marker not in text:
            ini_lines = text.split('\n')
            last_poi = -1
            for i, line in enumerate(ini_lines):
                if line.strip().startswith('PerObjIniFile='):
                    last_poi = i
            if last_poi >= 0:
                ini_lines.insert(last_poi + 1, marker)
                text = '\n'.join(ini_lines)
                with open(str(default_ini), 'wb') as f:
                    if enc == 'utf-16-le':
                        f.write(b'\xff\xfe')
                    f.write(text.encode(enc))
                self._log("  Default.ini: registered %s\n" % marker)

    # ══════════════════════════════════════════════════════════════════════
    # RESTORE
    # ══════════════════════════════════════════════════════════════════════

    def _restore_all(self):
        if self.working:
            return
        self.working = True
        self._set_buttons(False)
        self.status_var.set("Restoring...")
        self.status_label.configure(foreground='#fab387')
        t = threading.Thread(target=self._restore_worker, daemon=True)
        t.start()

    def _restore_worker(self):
        log_path = self._open_file_log('restore')
        self._log_system_info()
        try:
            self._log("\n" + "=" * 62 + "\n")
            self._log("  RESTORING ALL ORIGINALS\n")
            self._log("=" * 62 + "\n\n")

            n = self._restore_pristine_maps()
            self._log("  Restored %d map files\n" % n)

            sg_path = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc" / "ShockGame.U"
            sg_bak = PRISTINE_DIR / "ShockGame.U"
            if sg_bak.exists():
                shutil.copy2(str(sg_bak), str(sg_path))
                self._log("  Restored ShockGame.U\n")

            ibf_pristine = PRISTINE_DIR / "ConfigINI.IBF"
            ibf_game = CONTENT_DIR / "ConfigINI.IBF"
            ibf_bak = CONTENT_DIR / "ConfigINI.IBF.bak"
            system_dir = CONTENT_DIR / "System"

            # Collect game-original INI files that must survive loose-file cleanup
            preserve_inis = {'Default.ini', 'DefUser.ini'}

            if system_dir.exists():
                removed = 0
                for ini_f in system_dir.glob("*.ini"):
                    if ini_f.name in preserve_inis:
                        continue  # restored from pristine below
                    ini_f.unlink()
                    removed += 1
                if removed:
                    self._log("  Removed %d loose INI files\n" % removed)

            # Restore game-original INI files from pristine backups
            # DefUser.ini is in ContentBaked/System/, Default.ini is in Build/Final/
            du_bak = PRISTINE_DIR / "DefUser.ini"
            if du_bak.exists():
                shutil.copy2(str(du_bak), str(system_dir / "DefUser.ini"))
                self._log("  Restored DefUser.ini\n")
            di_bak = PRISTINE_DIR / "Default.ini"
            di_game = GAME_ROOT / "Build" / "Final" / "Default.ini"
            if di_bak.exists():
                shutil.copy2(str(di_bak), str(di_game))
                self._log("  Restored Default.ini\n")

            if ibf_bak.exists() and not ibf_game.exists():
                shutil.move(str(ibf_bak), str(ibf_game))
                self._log("  Restored ConfigINI.IBF\n")
            elif ibf_pristine.exists() and not ibf_game.exists():
                shutil.copy2(str(ibf_pristine), str(ibf_game))
                self._log("  Restored ConfigINI.IBF from pristine\n")

            # Restore Localizedint.lbf from pristine
            lbf_pristine = PRISTINE_DIR / "Localizedint.lbf"
            lbf_game = CONTENT_DIR / "Localizedint.lbf"
            if lbf_pristine.exists():
                shutil.copy2(str(lbf_pristine), str(lbf_game))
                self._log("  Restored Localizedint.lbf\n")

            # Remove DLC packages if they exist
            scripts_dir = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc"
            for dlc_name in ('DLCWeapons.U', 'DLCEffects.U'):
                dlc_pkg = scripts_dir / dlc_name
                if dlc_pkg.exists():
                    dlc_pkg.unlink()
                    self._log("  Removed %s\n" % dlc_name)

            # Reset User.ini keybind in AppData
            user_ini = os.path.join(
                os.environ.get('APPDATA', ''), 'BioshockHD', 'Bioshock2', 'User.ini')
            if os.path.isfile(user_ini):
                import re as _re
                raw = open(user_ini, 'rb').read()
                if raw[:2] == b'\xff\xfe':
                    enc = 'utf-16-le'
                    text = raw[2:].decode(enc)
                else:
                    enc = 'utf-8'
                    text = raw.decode(enc, errors='replace')
                pat = _re.compile(r'^(F12)=.*$', _re.MULTILINE)
                text_new, nr = pat.subn(r'F12=', text)
                if nr and text_new != text:
                    with open(user_ini, 'wb') as f:
                        if enc == 'utf-16-le':
                            f.write(b'\xff\xfe')
                        f.write(text_new.encode(enc))
                    self._log("  User.ini: reset F12 keybind\n")

            self._log("\n  RESTORE COMPLETE \u2014 all files are vanilla.\n")
            if self._log_path:
                self._log("Log saved to: %s\n" % self._log_path)
            self.root.after(0, self._on_restore_done)

        except Exception as e:
            self._log("\nERROR: %s\n" % e)
            import traceback
            self._log(traceback.format_exc())
            if self._log_path:
                self._log("Debug log saved to: %s\n" % self._log_path)
            self.root.after(0, self._on_error)
        finally:
            self._close_file_log()
            self.working = False
            self.root.after(0, lambda: self._set_buttons(True))

    # ── Status Callbacks ─────────────────────────────────────────────────

    def _on_apply_done(self):
        self.status_var.set("Mod Applied!")
        self.status_label.configure(foreground='#a6e3a1')

    def _on_restore_done(self):
        self.status_var.set("Restored to Vanilla")
        self.status_label.configure(foreground='#a6e3a1')

    def _on_error(self):
        self.status_var.set("Error \u2014 check log")
        self.status_label.configure(foreground='#f38ba8')

    # ══════════════════════════════════════════════════════════════════════
    # EXPORT INSTALLER
    # ══════════════════════════════════════════════════════════════════════

    def _export_installer(self):
        if self.working:
            return
        if not PRISTINE_DIR.exists():
            from tkinter import messagebox
            messagebox.showwarning("Export",
                "No pristine backups found.\n"
                "Apply the mod at least once first.")
            return
        # Let user choose output directory
        from tkinter import filedialog
        default_dir = str(BIOMOD_DIR / "installer_output")
        chosen = filedialog.askdirectory(
            title="Choose where to export the installer",
            initialdir=default_dir)
        if not chosen:
            return
        self._export_output_base = Path(chosen)
        self.working = True
        self._set_buttons(False)
        self.status_var.set("Exporting installer...")
        self.status_label.configure(foreground='#fab387')
        t = threading.Thread(target=self._export_worker, daemon=True)
        t.start()

    def _export_worker(self):
        import subprocess
        try:
            output_base = self._export_output_base
            output_dir = output_base / "TheWarInRapture2"
            mod_dir = output_dir / "mod_files"
            installer_gui_src = BIOMOD_DIR / "installer_gui.py"

            self._log("\n" + "=" * 62 + "\n")
            self._log("  EXPORTING INSTALLER\n")
            self._log("=" * 62 + "\n")
            self._log("  Output: %s\n\n" % output_dir)

            content_dir = CONTENT_DIR
            maps_dir = MAPS_DIR
            system_dir = content_dir / "System"
            scripts_dir = GAME_ROOT / "Build" / "Final" / "BakedScripts" / "pc"

            files = []  # list of (src_path, relative_path)

            # 1) BSM map files — only include changed ones
            self._log("[1] Checking map files...\n")
            map_count = 0
            for bsm in sorted(maps_dir.glob("*.bsm")):
                pristine = PRISTINE_DIR / bsm.name
                include = False
                if pristine.exists():
                    if bsm.stat().st_size != pristine.stat().st_size:
                        include = True
                        self._log("  CHANGED: %s (%+d bytes)\n" % (
                            bsm.name,
                            bsm.stat().st_size - pristine.stat().st_size))
                    else:
                        if bsm.read_bytes() != pristine.read_bytes():
                            include = True
                            self._log("  CHANGED: %s (same size, different content)\n" % bsm.name)
                else:
                    include = True
                    self._log("  NEW: %s\n" % bsm.name)
                if include:
                    rel = Path("ContentBaked") / "pc" / "Maps" / bsm.name
                    files.append((bsm, rel))
                    map_count += 1
            self._log("  Maps to include: %d\n" % map_count)

            # 2) Loose INI files in System/
            self._log("\n[2] Checking loose INI files...\n")
            stock_inis = {'Default.ini', 'DefUser.ini'}
            ini_count = 0
            if system_dir.exists():
                for ini_f in sorted(system_dir.glob("*.ini")):
                    if ini_f.name in stock_inis:
                        pristine = PRISTINE_DIR / ini_f.name
                        if pristine.exists() and ini_f.read_bytes() == pristine.read_bytes():
                            continue
                    rel = Path("ContentBaked") / "pc" / "System" / ini_f.name
                    files.append((ini_f, rel))
                    ini_count += 1
                    self._log("  %s (%d bytes)\n" % (ini_f.name, ini_f.stat().st_size))
            self._log("  INI files to include: %d\n" % ini_count)

            # 3) ShockGame.U
            self._log("\n[3] Checking ShockGame.U...\n")
            sg = scripts_dir / "ShockGame.U"
            sg_pristine = PRISTINE_DIR / "ShockGame.U"
            if sg.exists():
                if sg_pristine.exists() and sg.stat().st_size == sg_pristine.stat().st_size:
                    if sg.read_bytes() == sg_pristine.read_bytes():
                        self._log("  ShockGame.U: unchanged (skipping)\n")
                    else:
                        files.append((sg, Path("Build") / "Final" / "BakedScripts" / "pc" / "ShockGame.U"))
                        self._log("  ShockGame.U: CHANGED (same size, different content)\n")
                else:
                    files.append((sg, Path("Build") / "Final" / "BakedScripts" / "pc" / "ShockGame.U"))
                    self._log("  ShockGame.U: CHANGED (%+d bytes)\n" % (
                        sg.stat().st_size - (sg_pristine.stat().st_size if sg_pristine.exists() else 0)))

            # 4) DLC packages (DLCWeapons.U, DLCEffects.U)
            for dlc_name in ('DLCWeapons.U', 'DLCEffects.U'):
                dlc = scripts_dir / dlc_name
                if dlc.exists():
                    files.append((dlc, Path("Build") / "Final" / "BakedScripts" / "pc" / dlc_name))
                    self._log("  %s: %d bytes\n" % (dlc_name, dlc.stat().st_size))

            # 5) Default.ini (Build/Final/)
            self._log("\n[4] Checking Default.ini...\n")
            di = GAME_ROOT / "Build" / "Final" / "Default.ini"
            di_pristine = PRISTINE_DIR / "Default.ini"
            if di.exists():
                if di_pristine.exists() and di.read_bytes() == di_pristine.read_bytes():
                    self._log("  Default.ini: unchanged (skipping)\n")
                else:
                    files.append((di, Path("Build") / "Final" / "Default.ini"))
                    self._log("  Default.ini: CHANGED\n")

            # 6) Localizedint.lbf (display names for weapons/plasmids/ammo)
            self._log("\n[5] Checking Localizedint.lbf...\n")
            lbf = CONTENT_DIR / "Localizedint.lbf"
            lbf_pristine = PRISTINE_DIR / "Localizedint.lbf"
            if lbf.exists():
                if lbf_pristine.exists() and lbf.read_bytes() == lbf_pristine.read_bytes():
                    self._log("  Localizedint.lbf: unchanged (skipping)\n")
                else:
                    files.append((lbf, Path("ContentBaked") / "pc" / "Localizedint.lbf"))
                    self._log("  Localizedint.lbf: CHANGED (display names patched)\n")

            if not files:
                self._log("\nNo modified files found. Apply the mod first.\n")
                self.root.after(0, self._on_error)
                return

            # Build installer directory
            if output_dir.exists():
                shutil.rmtree(str(output_dir))
            output_dir.mkdir(parents=True)

            self._log("\n[6] Copying %d files to installer...\n" % len(files))
            total_size = 0
            for src, rel in files:
                dst = mod_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                total_size += src.stat().st_size
                self._log("  -> %s\n" % rel)

            map_names = [r.name for _, r in files
                         if str(r).startswith(str(Path("ContentBaked") / "pc" / "Maps"))]

            # Generate README
            readme = self._gen_readme(len(files), total_size, map_names)
            with open(output_dir / "README.txt", 'w', newline='\r\n') as f:
                f.write(readme)

            # ── Copy logo to output ────────────────────────────────────
            logo_src = BIOMOD_DIR / "installer_logo.png"
            if logo_src.exists():
                shutil.copy2(str(logo_src), str(output_dir / "installer_logo.png"))
                self._log("  Copied installer_logo.png\n")

            # ── Build .exe installer via PyInstaller ──────────────────
            exe_built = False
            if installer_gui_src.exists():
                self._log("\n[7] Building installer .exe with PyInstaller...\n")
                try:
                    import PyInstaller
                    pyinstaller_cmd = [sys.executable, '-m', 'PyInstaller']
                except ImportError:
                    pyinstaller_cmd = ['pyinstaller']

                exe_name = "WarInRapture_Install"
                build_tmp = BIOMOD_DIR / "_pyinstaller_build"
                if build_tmp.exists():
                    shutil.rmtree(str(build_tmp))

                cmd = pyinstaller_cmd + [
                    '--onefile', '--windowed',
                    '--name', exe_name,
                    '--distpath', str(output_dir),
                    '--workpath', str(build_tmp / 'build'),
                    '--specpath', str(build_tmp),
                    '--clean', '--noconfirm',
                ]
                if logo_src.exists():
                    cmd += ['--add-data', '%s%s.' % (str(logo_src), os.pathsep)]
                cmd.append(str(installer_gui_src))
                self._log("  Running PyInstaller...\n")
                try:
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=300)
                    if result.returncode == 0:
                        exe_path = output_dir / ("%s.exe" % exe_name)
                        if exe_path.exists():
                            self._log("  Built: %s (%.1f MB)\n" % (
                                exe_path.name,
                                exe_path.stat().st_size / 1024 / 1024))
                            exe_built = True
                        else:
                            self._log("  WARNING: PyInstaller ran but exe not found.\n")
                    else:
                        self._log("  WARNING: PyInstaller failed (exit %d)\n"
                                  % result.returncode)
                        if result.stderr:
                            for line in result.stderr.strip().split('\n')[-3:]:
                                self._log("    %s\n" % line)
                except subprocess.TimeoutExpired:
                    self._log("  WARNING: PyInstaller timed out.\n")
                except FileNotFoundError:
                    self._log("  WARNING: PyInstaller not installed.\n"
                              "  Install with: pip install pyinstaller\n")

                if build_tmp.exists():
                    shutil.rmtree(str(build_tmp), ignore_errors=True)
            else:
                self._log("\n[6] installer_gui.py not found — skipping .exe\n")

            # Fallback: copy Python script + launcher bat
            if not exe_built:
                self._log("  Copying installer_gui.py as fallback...\n")
                if installer_gui_src.exists():
                    shutil.copy2(str(installer_gui_src),
                                 str(output_dir / "installer_gui.py"))
                bat = (
                    '@echo off\n'
                    'echo Launching War In Rapture installer...\n'
                    'python "%~dp0installer_gui.py"\n'
                    'if errorlevel 1 (\n'
                    '    echo.\n'
                    '    echo Python not found. Install Python 3.8+ or use the .exe\n'
                    '    pause\n'
                    ')\n'
                )
                with open(output_dir / "install.bat", 'w', newline='\r\n') as f:
                    f.write(bat)

            self._log("\n" + "=" * 62 + "\n")
            self._log("  INSTALLER EXPORTED SUCCESSFULLY\n")
            self._log("=" * 62 + "\n")
            self._log("  Output:  %s\n" % output_dir)
            self._log("  Files:   %d\n" % len(files))
            self._log("  Size:    %.1f MB\n" % (total_size / 1024 / 1024))
            if exe_built:
                self._log("  Exe:     WarInRapture_Install.exe\n")
            else:
                self._log("  Exe:     NOT BUILT (PyInstaller unavailable)\n")
                self._log("           install.bat included as fallback\n")
            self._log("\n  Zip the TheWarInRapture2 folder to distribute.\n")
            self.root.after(0, self._on_export_done)

        except Exception as e:
            self._log("\nERROR: %s\n" % e)
            import traceback
            self._log(traceback.format_exc())
            self.root.after(0, self._on_error)
        finally:
            self.working = False
            self.root.after(0, lambda: self._set_buttons(True))

    def _on_export_done(self):
        self.status_var.set("Installer Exported!")
        self.status_label.configure(foreground='#a6e3a1')

    # ── README Generator ─────────────────────────────────────────────────

    def _gen_readme(self, file_count, total_size, map_names):
        L = []
        L.append('=' * 64)
        L.append('  THE WAR IN RAPTURE')
        L.append('  BioShock 2 Remastered \u2014 Game Modification')
        L.append('=' * 64)
        L.append('')
        L.append('INSTALLATION')
        L.append('------------')
        L.append('  1. Run WarInRapture_Install.exe')
        L.append('     (or install.bat if .exe is not available)')
        L.append('  2. The installer will auto-detect your game directory')
        L.append('     (or let you browse to it)')
        L.append('  3. Click "Install Mod"')
        L.append('  4. Original files are backed up to _WarInRapture_Backup/')
        L.append('     inside your game folder')
        L.append('  5. Launch BioShock 2 Remastered and start a NEW GAME')
        L.append('     (or load from a level transition save point)')
        L.append('')
        L.append('UNINSTALLATION')
        L.append('--------------')
        L.append('  Run WarInRapture_Install.exe and click "Uninstall Mod".')
        L.append('  Alternatively, verify game files through Steam:')
        L.append('  Right-click BioShock 2 > Properties > Local Files > Verify')
        L.append('')
        L.append('WHAT THIS MOD CHANGES')
        L.append('---------------------')
        L.append('  - Enemy spawner duplication in map files (more enemies)')
        L.append('  - Scripted encounter additions (bigger ambushes)')
        L.append('  - INI balance: damage, loot tables, difficulty scaling')
        L.append('  - Weapon upgrades: ricochet, knockback, new ammo effects')
        L.append('  - Plasmid enhancements: Electric Highlight, etc.')
        L.append('  - Enemy health scaling')
        L.append('  - Bytecode patches to ShockGame.U')
        L.append('')
        if map_names:
            L.append('  Modified maps: %s' % ', '.join(
                n.replace('.bsm', '') for n in sorted(map_names)))
        L.append('  Total files: %d (%.1f MB)' % (file_count, total_size / 1024 / 1024))
        L.append('')
        L.append('=' * 64)
        L.append('')
        return '\n'.join(L)


# ─── Entry Point ─────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    app = SpawnModManager(root)
    root.mainloop()

if __name__ == '__main__':
    main()
