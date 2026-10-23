"""Build an allowlisted, self-contained source archive without personal data."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from app_runtime import APP_VERSION, resource_root
from package_contents import asset_manifests, runtime_evidence
from world_profiles import Catalog
from world_profiles.catalog import CURRENT_MAPPING_VERSION

ROOT = resource_root()
APPLICATION = ('app_runtime.py', 'beta_launcher.py', 'editor_lifecycle.py', 'export_destination.py',
               'export_worldstate.py', 'fbmod_metadata.py', 'frostbite_reader.py', 'gui.py', 'profile_cli.py')
BUILD = ('build_beta.py', 'build_source.py', 'package_contents.py', 'beta_build.spec',
         'beta_version.txt', 'beta-build-requirements.txt', 'BETA-README.txt',
         'SOURCE-README.md', 'SOURCE-NOTICES.txt', 'run_portable_tests.py')
WEB = ('index.html', 'app.js', 'choice-controls.js', 'style.css', 'tapestry-layout.css',
       'keep-interactions.css', 'presentation.json', 'categories.json')
PARSER = 'assessment/reference/DAI_Exporter/ebx_parser.py'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build(destination):
    destination = destination.resolve()
    archive = destination.parent / (destination.name + '.zip')
    if destination.exists() or archive.exists() or archive.with_suffix('.zip.sha256').exists():
        raise ValueError('Choose a new source destination; existing files are preserved')
    destination.mkdir(parents=True)
    runtime_sources = []

    def copy(relative, target=None):
        source = (ROOT / relative).resolve()
        source.relative_to(ROOT.resolve())
        output = destination / (target or relative)
        output.resolve().relative_to(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, output)

    def write(relative, value):
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    for name in (*APPLICATION, *BUILD, 'supported-templates.json', 'bundled-presets.json'):
        copy('prototype/' + name)
    runtime_sources.extend('prototype/' + name for name in APPLICATION)
    for folder in ('game_saves', 'world_profiles'):
        for source in sorted((ROOT / 'prototype' / folder).glob('*.py')):
            relative = source.relative_to(ROOT).as_posix()
            copy(relative)
            runtime_sources.append(relative)
    for source in sorted((ROOT / 'prototype/world_profiles').glob('*.json')):
        copy(source.relative_to(ROOT).as_posix())
    for name in WEB:
        copy('prototype/gui/' + name)
    for pattern in ('test_*.py', 'test_*.cjs'):
        for source in sorted((ROOT / 'prototype').glob(pattern)):
            copy(source.relative_to(ROOT).as_posix())
    copy(PARSER)
    runtime_sources.append(PARSER)
    copy('assessment/export-policy.json')
    write('assessment/reference/worldstate-evidence.json', runtime_evidence(ROOT))
    manifests, _ = asset_manifests(ROOT)
    for folder, manifest in manifests.items():
        write('assets/' + folder + '/manifest.json', manifest)
        for entry in manifest['assets']:
            copy('assets/' + folder + '/' + entry['path'])
    copy('assets/keep-interface/keep-tower.ico')
    bundled = json.loads((ROOT / 'prototype/bundled-presets.json').read_text(encoding='utf-8'))
    expected_presets = set()
    for preset in bundled['presets']:
        expected_presets.add(preset['path'])
        copy(preset['path'])
        assert sha((destination / preset['path']).read_bytes()) == preset['sha256']
    copy('prototype/SOURCE-README.md', 'README.md')
    copy('prototype/SOURCE-NOTICES.txt', 'SOURCE-NOTICES.txt')
    (destination / '.gitignore').write_text(
        '__pycache__/\n*.py[cod]\n.dev-data/\n.build-env/\nprofiles/\nexports/\nreleases/\n'
        'prototype/output/\nprototype/profile-data/\nprototype/gui-logs/\n*.log\n', encoding='utf-8')
    inventory = [dict(path=path.relative_to(destination).as_posix(), bytes=path.stat().st_size,
                      sha256=sha(path.read_bytes())) for path in sorted(destination.rglob('*')) if path.is_file()]
    forbidden = {'profiles', 'exports', 'preservation', 'Customized Worldstates', '.git', '.codex',
                 '__pycache__', 'output', '.dev-data', '.build-env', 'gui-logs', 'profile-data'}
    for row in inventory:
        path = Path(row['path'])
        assert not forbidden.intersection(path.parts), row['path']
        assert path.suffix.lower() not in {'.das', '.sav', '.exe', '.dll', '.pyd', '.zip', '.log', '.pyc'}, row['path']
        assert not row['path'].endswith(('.profile.json', '.report.json'))
    assert {r['path'] for r in inventory if r['path'].endswith('.fbmod')} == expected_presets
    manifest = dict(version=APP_VERSION, kind='source', catalog_version=CURRENT_MAPPING_VERSION,
        files=inventory, runtime_source_sha256={path: sha((destination / path).read_bytes()) for path in sorted(runtime_sources)},
        catalog_fingerprints={str(version): Catalog(version).sha256 for version in range(1, CURRENT_MAPPING_VERSION + 1)},
        expected_presets=sorted(expected_presets))
    write('SOURCE-MANIFEST.json', manifest)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(destination.rglob('*')):
            if path.is_file():
                bundle.write(path, str(Path('Thedas World State Studio Source') / path.relative_to(destination)))
    digest = sha(archive.read_bytes())
    archive.with_suffix('.zip.sha256').write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
    return dict(version=APP_VERSION, files=len(inventory) + 1, archive=str(archive), sha256=digest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    print(json.dumps(build(parser.parse_args().destination)))
