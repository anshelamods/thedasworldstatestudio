# Thedas World State Studio — 1.0.4 source

Application version **1.0.4**, catalog **44**, story rules **v10**.
This is a separate, self-contained source distribution for the Windows application.

The source includes the editor, local resources, save importers and direct FBMOD
writer. Exported FBMODs display version 1.0 independently of the application.

## Run

Use **Python 3.12 on Windows**, with Tcl/Tk installed (included by the standard
Windows Python installer). The application has no pip runtime dependencies and
loads its artwork/fonts from this archive.

From the extracted source root:

```powershell
python prototype/gui.py --data-dir .dev-data
```

This creates isolated development World States, settings and exports in
`.dev-data`. Keep the terminal open while using the editor. Close the editor
window or press Ctrl+C in the terminal to stop it. To run without opening a
window, add `--no-open`; the terminal prints the local session URL.

The installed app uses `%LOCALAPPDATA%\ThedasWorldstateStudio`. Point a development
copy at separate data while editing/testing. The optional profile CLI is:

```powershell
python prototype/profile_cli.py --help
```

World State folders have readable names, a current portable JSON and a History
subfolder. Changed saves retain 20 versions including the current version.
Saved revisions can clear earlier versions while keeping the current save.
Startup migrates legacy storage without changing its choices or revision
contents; initial migration retains legacy history until the next changed save.
Keep independent backups outside app-managed folders and import JSON to apply
external edits. Use separate data copies when comparing older app versions.

## Build the Windows application

The following commands use a fresh build environment and the same pinned build
tools used for this release. Installing these tools requires access to a Python package
index; running the resulting app does not.

```powershell
python -m venv .build-env
.\.build-env\Scripts\python.exe -m pip install -r prototype/beta-build-requirements.txt
.\.build-env\Scripts\python.exe prototype/build_beta.py --destination releases/My-Windows-build
```

The destination must not already exist. Create its
ZIP and checksum:

```powershell
.\.build-env\Scripts\python.exe prototype/build_beta.py --archive --destination releases/My-Windows-build
```

The executable keeps the tower icon. Python, Tcl/Tk, assets and the three bundled
presets are collected by the allowlisted spec; personal data and tests are not
included in the Windows binary package. Builds are functionally reproducible,
but timestamps, Python installations and compiler metadata may change EXE/ZIP
bytes. Do not expect a byte-identical executable from a different machine.

## Layout and contents

- `prototype/gui.py`, `gui/`: local API and browser interface.
- `prototype/world_profiles/`: profiles, revisions, compiler, catalogs and rules.
- `prototype/game_saves/`: bounded GFF readers and DAO/DA2 import mappings.
- `prototype/export_worldstate.py`, `frostbite_reader.py`: FBMOD/EBX export.
- `prototype/resources/presets/`: original defaults and the two optional author presets included in the Windows release.
- `assessment/export-policy.json`, `assessment/reference/worldstate-evidence.json`:
  required mapping data, with research/source annotations removed from the latter.
- `assessment/reference/DAI_Exporter/ebx_parser.py`:
  the EBX parser used by the application.
- `assets/`: local artwork, fonts, manifests and the build icon.
- `prototype/build_beta.py`, `beta_build.spec`, `package_contents.py`: Windows build tools.
- `prototype/build_source.py`: recreate a source archive from this tree.

To recreate the source ZIP in a new location:

```powershell
python prototype/build_source.py --destination releases/My-source
```

`SOURCE-MANIFEST.json` lists the distributed files and their hashes, including
the exact runtime source files. The package contains no personal saves, saved
World States, credentials, sessions, logs, preservation downloads, private
research extracts, compiled application, build environment or Python runtime.

## Attribution and licensing

See `SOURCE-NOTICES.txt`. This archive does not add or change licensing terms.
Dragon Age artwork/fonts/game assets and the bundled author presets retain
their existing ownership; no blanket license for third-party content is implied.
