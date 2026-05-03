# Building the Installer Executable

This document explains exactly how `WarInRapture_Install.exe` is built from source.

## What the Installer Is

The installer is a single Python script (`installer_gui.py`) compiled into a native Windows executable using **Nuitka**, which translates Python source code into C and compiles it with MSVC into a real `.exe`. There is no bytecode unpacker or bootloader — the result is a genuine native binary.

The installer does **not** access the internet, modify system files, or do anything outside the BioShock 2 game directory. It:

1. Auto-detects the game install path via the Steam registry key
2. Backs up original game files to `_WarInRapture_Backup/`
3. Copies modded `.ini`, `.bsm`, `.U`, and `.lbf` files from the bundled `mod_files/` folder
4. Renames `ConfigINI.IBF` → `ConfigINI.IBF.bak` so the engine reads loose INI overrides

Uninstall reverses all of the above by restoring from backup.

---

## Prerequisites

- **Python 3.10+** (tested with 3.14) — https://www.python.org/downloads/
- **Nuitka** — Python-to-C compiler
- **MSVC** (Microsoft Visual C++) — included with Visual Studio Build Tools or Visual Studio Community
  - Install "Desktop development with C++" workload
  - https://visualstudio.microsoft.com/visual-cpp-build-tools/

### Install Nuitka and dependencies

```bash
pip install nuitka zstandard ordered-set
```

---

## Build Steps

### 1. Clone the repository

```bash
git clone https://github.com/NykoDesigns/TheWrathOfLamb.git
cd TheWrathOfLamb
```

### 2. Review the source

The entire installer is a single file:

- **`installer_gui.py`** — tkinter GUI that performs install/uninstall

It uses only Python standard library modules (`tkinter`, `shutil`, `os`, `sys`, `threading`, `winreg`, `pathlib`, `ctypes`). No third-party runtime dependencies.

### 3. Compile with Nuitka

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

**Flag explanation:**
| Flag | Purpose |
|------|---------|
| `--onefile` | Produce a single standalone `.exe` |
| `--windows-console-mode=disable` | Hide the console window (GUI app) |
| `--output-filename=...` | Name the output executable |
| `--enable-plugin=tk-inter` | Bundle tkinter (the GUI framework) |
| `--include-data-files=...` | Embed the logo image inside the exe |
| `--assume-yes-for-download` | Auto-download Nuitka helper tools if needed |
| `--remove-output` | Clean up intermediate C/build files after compilation |

### 4. Verify the output

The build produces `WarInRapture_Install.exe` (~9 MB). You can verify it:

```bash
# Check it runs
.\WarInRapture_Install.exe

# Check file properties — it will show as a native Windows PE executable
# No Python bootloader, no self-extracting archive
```

---

## Alternative: Run Without Compiling

If you don't want to compile, you can run the installer directly with Python:

```bash
python installer_gui.py
```

This requires Python 3.10+ with tkinter (included in standard Windows Python installs).

---

## Why Does the Old Version Trigger Antivirus?

The previous version was built with **PyInstaller**, which works differently from Nuitka:

- **PyInstaller** bundles Python bytecode into a self-extracting archive with a bootloader stub. At runtime, it extracts files to a temp directory and executes them. This unpacking behavior triggers heuristic-based antivirus scanners because it resembles malware behavior.
- **Nuitka** compiles Python source to C code, then compiles the C to a native executable via MSVC. The result is a real `.exe` with no unpacker, no temp extraction, and no bootloader — just native machine code.

This is a well-documented industry issue with PyInstaller:
https://github.com/pyinstaller/pyinstaller/issues?q=is%3Aissue+virus+false+positive

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

Only `installer_gui.py` and `installer_logo.png` are used to build the distributed `.exe`. The `core/` modules and other scripts are developer tools used to create the mod files — they are not part of the installer.
