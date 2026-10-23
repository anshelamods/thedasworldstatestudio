# Build only reviewed runtime data; never recursively collect the workspace.
from pathlib import Path
import json
import os
import sys

project = Path(SPECPATH).parent
sys.path.insert(0, str(project / 'prototype'))
from package_contents import EXCLUDED_MODULES, asset_manifests, runtime_evidence
data = []

def include(relative):
    source = project / relative
    assert source.is_file(), source
    data.append((str(source), str(Path(relative).parent)))

for relative in ('assessment/export-policy.json',
                 'prototype/supported-templates.json', 'prototype/bundled-presets.json'):
    include(relative)
for source in (project / 'prototype/world_profiles').glob('*.json'):
    include(source.relative_to(project))
for name in ('index.html', 'app.js', 'choice-controls.js', 'style.css', 'tapestry-layout.css',
             'keep-interactions.css', 'presentation.json', 'categories.json'):
    include('prototype/gui/' + name)
stage = Path(os.environ['THEDAS_BUILD_STAGE'])
evidence_path = stage / 'assessment/reference/worldstate-evidence.json'
evidence_path.parent.mkdir(parents=True, exist_ok=True)
evidence_path.write_text(json.dumps(runtime_evidence(project), indent=2) + '\n', encoding='utf-8')
data.append((str(evidence_path), 'assessment/reference'))
manifests, removed_assets = asset_manifests(project)
for folder, manifest in manifests.items():
    manifest_path = stage / 'assets' / folder / 'manifest.json'
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    data.append((str(manifest_path), 'assets/' + folder))
    for entry in manifest['assets']:
        include('assets/' + folder + '/' + entry['path'])
(stage / 'content-audit.json').write_text(json.dumps(dict(excluded_modules=EXCLUDED_MODULES,
    removed_assets=removed_assets), indent=2), encoding='utf-8')
presets = json.loads((project / 'prototype/bundled-presets.json').read_text(encoding='utf-8'))
for entry in presets['presets']:
    include(entry['path'])

a = Analysis([str(project / 'prototype/beta_launcher.py')],
    pathex=[str(project / 'prototype'),
            str(project / 'assessment/reference/DAI_Exporter')],
    binaries=[], datas=data, hiddenimports=['tkinter', 'tkinter.filedialog'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=list(EXCLUDED_MODULES), noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Thedas World State Studio',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          icon=str(project / 'assets/keep-interface/keep-tower.ico'),
          version=str(project / 'prototype/beta_version.txt'))
collect = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Thedas World State Studio')
