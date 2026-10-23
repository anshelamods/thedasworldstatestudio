"""Conservative build-only reachability rules for packaged artwork and imports."""
import copy
import json
from pathlib import Path

# The application serves local HTTP and reads/writes JSON/FBMOD/CAS, not TLS,
# archive files, or decimal/statistical calculations. Standard-library imports
# for these optional paths would otherwise collect their native extensions.
EXCLUDED_MODULES = ('ssl', '_ssl', '_hashlib', 'statistics', 'fractions', 'decimal',
                    '_decimal', '_pydecimal', 'tarfile', 'bz2', '_bz2', 'lzma', '_lzma')


def runtime_evidence(project):
    evidence = json.loads((Path(project) / 'assessment/reference/worldstate-evidence.json').read_text(encoding='utf-8'))
    # These are the only fields consumed by Catalog and the FBMOD writer.
    # Original descriptions, source locations and all eight preset-value tables
    # remain development evidence rather than runtime package data.
    return [dict(name=entry['name'], plot_guid=entry['plot_guid'],
                 keep={'maximum': entry.get('keep', {}).get('maximum')}) for entry in evidence]


def asset_manifests(project):
    project = Path(project)
    presentation = json.loads((project / 'prototype/gui/presentation.json').read_text(encoding='utf-8'))
    categories = json.loads((project / 'prototype/gui/categories.json').read_text(encoding='utf-8'))
    flags = {entry['art_flag'] for entry in presentation.values() if entry.get('art_flag')}
    explicit = {entry['art'] for entry in categories if entry.get('art')}
    for entry in presentation.values():
        explicit.update(answer['archive_art'] for answer in entry['answers'].values() if answer.get('archive_art'))
    result, removed = {}, []
    for folder in ('keep', 'keep-interface', 'keep-fonts'):
        manifest = json.loads((project / 'assets' / folder / 'manifest.json').read_text(encoding='utf-8'))
        retained = []
        for entry in manifest['assets']:
            needed = (folder != 'keep' or entry['path'] in explicit
                      or any(reference['flag'] in flags for reference in entry['references']))
            # ICO is embedded into the EXE during build. The browser uses PNG.
            if folder == 'keep-interface' and entry['path'] == 'keep-tower.ico':
                needed = False
            if needed:
                retained.append(entry)
            else:
                removed.append(dict(path='assets/' + folder + '/' + entry['path'], bytes=entry['bytes']))
        packaged = copy.deepcopy(manifest)
        packaged['assets'] = retained
        result[folder] = packaged
    return result, removed
