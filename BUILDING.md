# Building the Installer Executable

This document explains exactly how the currently distributed `WarInRapture_Install.exe` was built from source, why it triggers antivirus false positives, and how the upcoming version resolves this.

---

## What the Installer Does

The installer is a single Python script (`installer_gui.py`) compiled into a standalone `.exe`. It does **not** access the internet, modify system files, or do anything outside the BioShock 2 game directory.

All it does:

1. Auto-detects the BioShock 2 Remastered install path via the Steam registry key
2. Backs up original game files to a `_WarInRapture_Backup/` folder
3. Copies modded `.ini`, `.bsm`, `.U`, and `.lbf` files from the bundled `mod_files/` directory into the game directory
4. Renames `ConfigINI.IBF` → `ConfigINI.IBF.bak` so the engine reads loose INI overrides

Uninstall reverses all of the above by restoring from backup.

The installer uses only Python standard library modules: `tkinter`, `shutil`, `os`, `sys`, `threading`, `winreg`, `pathlib`, `ctypes`. **Zero third-party runtime dependencies.**

---

## Current Version (PyInstaller Build)

The version currently uploaded to Nexus Mods was built with **PyInstaller** using the following command:

### Prerequisites

```bash
pip install pyinstaller
```

### Build Command

```bash
pyinstaller ^
    --onefile ^
    --windowed ^
    --name WarInRapture_Install ^
    --add-data "installer_logo.png;." ^
    installer_gui.py
```

**Flag explanation:**
| Flag | Purpose |
|------|---------|
| `--onefile` | Bundle everything into a single `.exe` |
| `--windowed` | Hide the console window (GUI app) |
| `--name` | Name the output executable |
| `--add-data` | Embed the logo image inside the exe |

### Why It Triggers Antivirus

**PyInstaller** bundles the Python interpreter + bytecode into a self-extracting archive with a bootloader stub. At runtime, it:
1. Extracts bundled files to a temporary directory (`%TEMP%\_MEIxxxxx`)
2. Loads the Python DLL from that temp location
3. Executes the extracted bytecode

This unpack-and-execute behavior closely mimics how actual malware operates, which causes heuristic-based antivirus scanners to flag it. **This affects virtually every PyInstaller-built application**, not just ours.

This is a well-documented, long-standing industry issue:
- https://github.com/pyinstaller/pyinstaller/issues?q=is%3Aissue+virus+false+positive
- Thousands of legitimate open-source tools built with PyInstaller face the same problem

**The executable contains no malicious code.** You can verify this by:
1. Reading `installer_gui.py` in this repository — it is the complete source
2. Building it yourself with the command above
3. Comparing the behavior: it only reads/writes files within the game directory

---

## Upcoming Version (Nuitka Build)

The next release will be built with **Nuitka** instead, which compiles Python source code to C and then to a native executable via MSVC. The result is a real native Windows binary — no bootloader, no temp extraction, no bytecode unpacking.

### Prerequisites

```bash
pip install nuitka zstandard ordered-set
```

Also requires MSVC (Microsoft Visual C++) — included with [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) ("Desktop development with C++" workload).

### Build Command

```bash
python -m nuitka ^
    --onefile ^
    --windows-console-mode=disable ^
    --output-filename=WarInRapture_Install.exe ^
    --enable-plugin=tk-inter ^
    --include-data-files=installer_logo.png=installer_logo.png ^
    --assume-yes-for-download ^
    --remove-output ^
    installer_gui.py
```

This produces a ~9 MB native `.exe` that should not trigger antivirus heuristics.

---

## Run Without Compiling

If you prefer not to compile at all, you can run the installer directly with Python:

```bash
python installer_gui.py
```

This requires Python 3.10+ with tkinter (included in standard Windows Python installs).

---

## Project Structure

```
TheWrathOfLamb/
├── installer_gui.py             # <-- THIS is what gets compiled to .exe
├── installer_logo.png           # Logo embedded in the installer
├── war_in_rapture_2.py          # Mod manager GUI (developer tool, not distributed)
├── export_installer.py          # Export pipeline (developer tool)
├── core/                        # Patcher modules (developer tools)
│   ├── bsm_parser.py            # Unreal Engine package reader
│   ├── bsm_spawn_patcher.py     # Spawner duplication
│   ├── bsm_script_patcher.py    # Scripted encounter cloning
│   ├── shockgame_patcher.py     # ShockGame.U bytecode patches
│   ├── ini_config.py            # INI config parser
│   ├── ibf_utils.py             # IBF/LBF archive tools
│   ├── dlc_package_builder.py   # Ion Laser package builder
│   └── dlc_effects_builder.py   # DLC effects builder
```

Only `installer_gui.py` and `installer_logo.png` are used to build the distributed `.exe`. The `core/` modules and other scripts are the developer tools used to generate the mod files — they are not part of the installer.
