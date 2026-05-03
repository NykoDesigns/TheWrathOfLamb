# The Wrath Of Lamb — BioShock 2 Remastered Overhaul Mod

![The Wrath Of Lamb](The%20Wrath%20Of%20Lamb%20Logo.png)

A comprehensive mod manager and installer for **BioShock 2 Remastered** that overhauls combat, enemy encounters, weapons, plasmids, loot, and more — all configurable through a GUI with no manual file editing required.

---

## Features

### Combat & Encounters
- **Enemy Spawn Multipliers** — increase or decrease repopulation spawner density per map
- **Scripted Encounter Scaling** — multiply enemies in scripted combat events (Splicers, Brutes, Big Daddies)
- **Enemy Health Tuning** — per-enemy-type health multipliers (13 enemy classes)
- **Harvest Defense Scaling** — adjust Little Sister gather event ambush intensity

### Weapons
- **Damage Values** — granular control over every weapon and ammo type
- **Weapon Upgrades** — elemental ammo overhauls:
  - **Hellfire Drill** — drill ignites enemies on hit
  - **Ice Rivets** — standard rivets freeze enemies
  - **Rage Rivets** — heavy rivets enrage and launch enemies
  - **Static Rounds** — MG rounds shock and stun
  - **Shredder Rounds** — MG anti-personnel rounds cause bleeding DOT
  - **Explosive Shells** — 00 Buck detonates on impact
  - **Explosive Shot** — Solid Slugs explode on hit
  - **Disease Buck** — 00 Buck inflicts bleeding DOT
  - **Weighted Spear** — spears knock enemies back on hit
  - **Berserker Drill** — massive drill stat overhaul (damage, fuel, speed, headshots)
- **Ricochet Enhancement** — Rivet Gun and Shotgun rounds ricochet off surfaces
- **Ion Laser** — transplants the DLC Ion Laser weapon into the main campaign via vendor machines

### Plasmids
- **Hades Grasp** — Telekinesis picks up living enemies and ignites them
- **Winter's Embrace** — Telekinesis picks up living enemies and freezes them
- **Hell Fire Decoy** — Decoy reflects damage, spawns a fire cyclone trap
- **Vampiric Thrall** — Hypnotized enemies reflect 100% damage back to attackers
- **Frej Swarm** — Insect Swarm freezes enemies on contact
- **Electric Highlight** — Electro Bolt also tags enemies for security
- **Gravity Well** — restores the DLC Gravity Well plasmid to the main campaign

### Economy & Progression
- **Loot Tables** — adjust drop rates, item stacks, and loot deck composition per enemy type
- **Vending Prices** — customize costs for all vending machine items
- **Difficulty Settings** — tweak damage multipliers, economy values, and AI behavior per difficulty tier

### Restored Content
- **Summon Protector** — re-enables the cut Big Daddy summoning ability
- **Dual Drill** — visual second drill model on the left hand
- **Flame Drill** — drill melee leaves fire VFX on hit

---

## For End Users (Installing the Mod)

**You do NOT need Python.** Download the release zip from [Nexus Mods](https://www.nexusmods.com/) and run `WarInRapture_Install.exe`.

The installer will:
1. Auto-detect your BioShock 2 Remastered installation via Steam
2. Back up your original game files to `_WarInRapture_Backup`
3. Copy all modded files into the game directory
4. Disable `ConfigINI.IBF` so the game reads loose INI overrides

To uninstall, run the same `.exe` and click **Uninstall** — it restores everything from backup.

---

## For Developers

### Project Structure

```
TheWrathOfLamb/
├── war_in_rapture_2.py          # Main mod manager GUI (tkinter)
├── installer_gui.py             # Standalone installer/uninstaller GUI
├── export_installer.py          # Export pipeline + PyInstaller compilation
├── bsm_spawn_adjustments.json   # Per-map spawn tuning data
├── installer_logo.png           # Resized logo for installer GUI
├── core/
│   ├── bsm_parser.py            # Unreal Engine .bsm package reader/writer
│   ├── bsm_spawn_patcher.py     # Repopulation spawner duplication
│   ├── bsm_script_patcher.py    # Scripted encounter cloning
│   ├── shockgame_patcher.py     # ShockGame.U bytecode patching
│   ├── ini_config.py            # INI config parser (round-trip preserving)
│   ├── ibf_utils.py             # ConfigINI.IBF / Localizedint.lbf archive tools
│   ├── dlc_package_builder.py   # Ion Laser DLCWeapons.U builder
│   └── dlc_effects_builder.py   # DLC visual effects builder
```

### Requirements

- **Python 3.10+**
- **tkinter** (included with standard Python on Windows)
- **PyInstaller** (optional, for compiling the installer to `.exe`)

```bash
pip install pyinstaller
```

### How It Works

The mod operates through two patching systems:

1. **INI Config Patching** — The game packs all `.ini` config files into `ConfigINI.IBF` (a simple binary archive). The mod extracts them, applies changes in memory, writes loose `.ini` files to `ContentBaked/pc/System/`, and renames the IBF so the engine loads the loose files instead.

2. **Binary Patching (`.bsm` / `.U`)** — Unreal Engine 2.5 "Vengeance Engine" map packages and script packages are patched directly:
   - Spawner exports are duplicated with offset positions and registered in the Level actor list
   - Scripted encounter `ActionSpawnAI` exports are cloned with modified AI type references
   - ShockGame.U functions receive bytecode injections for new abilities (TK pickup, damage reflection, cyclone spawning, etc.)

3. **Localization Patching** — Display names for renamed weapons/plasmids are patched inside `Localizedint.lbf` (the localization archive containing `.int` files).

### Building the Installer

```bash
python export_installer.py
```

This will:
1. Collect all modified game files by comparing against pristine backups
2. Copy them to an output directory with the installer script
3. Compile `installer_gui.py` into `WarInRapture_Install.exe` via PyInstaller
4. Generate a `README.txt` for end users

### Running the Mod Manager

```bash
python war_in_rapture_2.py
```

On first launch, select your BioShock 2 Remastered game directory. The mod manager will back up pristine copies of all game files before making any changes.

---

## Technical Notes

- **BSM Format**: Version 143, Licensee 59 (modified Unreal Engine 2.5 "Vengeance Engine")
- **Compact Index**: Variable-length integer encoding used throughout Unreal packages
- **IBF Format**: Simple archive with compact-index length fields and UTF-16LE content
- **All patches are reversible** — pristine backups are maintained and restored on uninstall or before each new apply

---

## License

This project is provided as-is for modding purposes. BioShock 2 Remastered is the property of 2K Games / Take-Two Interactive.
