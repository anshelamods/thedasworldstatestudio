"""Build an allowlisted standalone application; never copy personal workspace data."""
import argparse
from datetime import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from app_runtime import APP_VERSION, resource_root
from world_profiles.catalog import CURRENT_MAPPING_VERSION

ROOT = resource_root()


def inventory(directory):
    return [{'path': path.relative_to(directory).as_posix(), 'bytes': path.stat().st_size,
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(directory.rglob('*')) if path.is_file() and path.name != 'package-manifest.json']


def build(destination):
    if destination.exists():
        raise ValueError('Choose a new release folder; existing builds are preserved')
    work = ROOT / 'prototype/output/beta-build' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    work.mkdir(parents=True)
    env = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(work / 'cache'), THEDAS_BUILD_STAGE=str(work / 'staged-data'),
               TEMP=str(work), TMP=str(work))
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--workpath', str(work / 'work'),
                    '--distpath', str(work / 'dist'), str(ROOT / 'prototype/beta_build.spec')],
                   cwd=ROOT, env=env, check=True)
    shutil.copytree(work / 'dist/Thedas World State Studio', destination)
    shutil.copyfile(ROOT / 'prototype/BETA-README.txt', destination / 'README.txt')
    licenses = destination / 'licenses'
    licenses.mkdir()
    runtime = Path(sys.base_prefix)
    shutil.copyfile(runtime / 'LICENSE.txt', licenses / 'Python-LICENSE.txt')
    pyinstaller = Path(importlib.metadata.distribution('pyinstaller').locate_file('pyinstaller-6.22.3.dist-info/licenses/COPYING.txt'))
    shutil.copyfile(pyinstaller, licenses / 'PyInstaller-COPYING.txt')
    for name in ('tk8.6/license.terms', 'tcl8.6/license.terms'):
        path = runtime / 'tcl' / name
        if path.is_file():
            shutil.copyfile(path, licenses / (name.split('/')[0] + '-license.terms'))
    (destination / 'THIRD-PARTY-NOTICES.txt').write_text(
        'Thedas World State Studio ' + APP_VERSION + '\n\n'
        'Unofficial fan project. Dragon Age artwork, interface assets and fonts: EA / BioWare and their respective owners.\n'
        'Optional Queen Cousland / Rogue Hawke presets: anshela (supplied by the author).\n'
        'EBX reader adapted from DAI Exporter.\n'
        'Python 3.12 runtime: Python Software Foundation; see Python-LICENSE.txt for upstream component notices.\n'
        'This offline build excludes OpenSSL/TLS and unused bzip2/lzma/decimal extensions; hashing uses Python built-in implementations.\n'
        'Tcl/Tk 8.6: their respective contributors; see licenses.\n'
        'PyInstaller 6.22.3 bootloader: see PyInstaller-COPYING.txt, including the bootloader exception.\n'
        'Build tools and personal source/reference documents are not part of this package.\n', encoding='utf-8')
    return seal(destination)


def seal(destination):
    files = inventory(destination)
    templates = [item for item in files if item['path'].endswith('.fbmod')]
    expected = {'_internal/prototype/resources/presets/' + name for name in
                ('original-game.fbmod', 'queen-cousland-fenris.fbmod', 'queen-cousland-anders.fbmod')}
    if {item['path'] for item in templates} != expected:
        raise ValueError('Unexpected templates in release inventory')
    forbidden = {'profiles', 'exports', 'Customized Worldstates', 'screenshots', 'gui-logs', '.git', '.codex'}
    if any(forbidden.intersection(Path(item['path']).parts)
           or item['path'].endswith(('.report.json', '.profile.json', '.docx'))
           or (item['path'].endswith('.zip') and item['path'] != '_internal/base_library.zip') for item in files):
        raise ValueError('Unexpected personal/development data in release')
    manifest = dict(version=APP_VERSION, platform='Windows x64', catalog_version=CURRENT_MAPPING_VERSION,
                    built_at=datetime.now().astimezone().isoformat(), files=files)
    (destination / 'package-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def archive(directory):
    manifest = json.loads((directory / 'package-manifest.json').read_text(encoding='utf-8'))
    if manifest['files'] != inventory(directory):
        raise ValueError('Release contents changed after the manifest was written')
    output = directory.parent / (directory.name + '.zip')
    if output.exists():
        raise ValueError('Existing ZIP preserved; choose a new release folder')
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                bundle.write(path, str(Path('Thedas World State Studio') / path.relative_to(directory)))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest + '  ' + output.name + '\n', encoding='ascii')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--archive', action='store_true', help='Archive an already built and verified release')
    parser.add_argument('--seal', action='store_true', help='Recheck inventory and manifest for a completed build')
    args = parser.parse_args()
    if args.archive:
        print(archive(args.destination.resolve()))
    elif args.seal:
        print(json.dumps({'version': APP_VERSION, 'files': len(seal(args.destination.resolve())['files'])}))
    else:
        print(json.dumps({'version': APP_VERSION, 'files': len(build(args.destination.resolve())['files'])}))
