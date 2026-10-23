"""Assemble the static GitHub Pages site for the browser build of the editor.

The site serves prototype/gui unchanged in structure, the local artwork and
fonts, a Pyodide runtime from node_modules (run `npm ci` first) and a zip of
the Python application that web/worker.js unpacks in the browser.
"""
import argparse
import hashlib
import io
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
MARKER = '.thedas-web-build'
BUILD_PLACEHOLDER = '__BUILD_ID__'
PAGES = ('index.html', 'app.js', 'choice-controls.js', 'style.css', 'tapestry-layout.css', 'keep-interactions.css')
WEB = ('backend.js', 'worker.js')
ART = {'art': 'assets/keep', 'interface-art': 'assets/keep-interface', 'fonts': 'assets/keep-fonts'}
PYODIDE = ('pyodide.js', 'pyodide.asm.js', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json')
# Python sources and the data files they read at runtime, relative to ROOT.
PYTHON = ('prototype/*.py', 'prototype/world_profiles/*.py', 'prototype/world_profiles/*.json',
          'prototype/game_saves/*.py', 'prototype/resources/presets/*.fbmod',
          'prototype/bundled-presets.json', 'prototype/supported-templates.json',
          'prototype/gui/presentation.json', 'prototype/gui/categories.json',
          'assessment/export-policy.json', 'assessment/reference/worldstate-evidence.json',
          'assessment/reference/DAI_Exporter/ebx_parser.py',
          'assets/keep/manifest.json', 'assets/keep-interface/manifest.json', 'web/web_backend.py')
# Desktop build tooling and tests are not needed in the browser.
PYTHON_EXCLUDED = ('prototype/test_*.py', 'prototype/build_*.py', 'prototype/beta_*.py',
                   'prototype/run_portable_tests.py', 'prototype/package_contents.py', 'prototype/profile_cli.py')


def python_archive():
    files = set()
    for pattern in PYTHON:
        matches = sorted(ROOT.glob(pattern))
        if not matches:
            raise SystemExit('Missing runtime file: ' + pattern)
        files.update(matches)
    files = sorted(path for path in files
                   if not any(path.relative_to(ROOT).match(pattern) for pattern in PYTHON_EXCLUDED))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            # Fixed timestamps keep the archive identical between builds.
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


def build(destination):
    if destination.exists():
        if any(destination.iterdir()) and not (destination / MARKER).exists():
            raise SystemExit(f'{destination} is not empty and is not a previous web build')
        shutil.rmtree(destination)
    pyodide = ROOT / 'node_modules/pyodide'
    if not (pyodide / 'pyodide.js').is_file():
        raise SystemExit('Pyodide is not installed. Run `npm ci` first.')
    destination.mkdir(parents=True)
    (destination / MARKER).write_text('')
    (destination / '.nojekyll').write_text('')
    for name in PAGES:
        shutil.copyfile(ROOT / 'prototype/gui' / name, destination / name)
    for name in WEB:
        shutil.copyfile(ROOT / 'web' / name, destination / name)
    for target, source in ART.items():
        shutil.copytree(ROOT / source, destination / target, ignore=shutil.ignore_patterns('manifest.json'))
    (destination / 'pyodide').mkdir()
    for name in PYODIDE:
        shutil.copyfile(pyodide / name, destination / 'pyodide' / name)
    (destination / 'python.zip').write_bytes(python_archive())

    # Version the page's own files so browsers never mix cached releases.
    digest = hashlib.sha256()
    for path in sorted(destination.rglob('*')):
        if path.is_file():
            digest.update(path.relative_to(destination).as_posix().encode() + b'\0' + path.read_bytes())
    build_id = digest.hexdigest()[:12]
    for name in ('index.html', *WEB):
        path = destination / name
        path.write_text(path.read_text(encoding='utf-8').replace(BUILD_PLACEHOLDER, build_id), encoding='utf-8')
    return build_id


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=ROOT / '_site')
    args = parser.parse_args(argv)
    build_id = build(args.destination.resolve())
    size = sum(path.stat().st_size for path in args.destination.rglob('*') if path.is_file())
    print(f'Built {args.destination} (build {build_id}, {size / 1_048_576:.1f} MB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
