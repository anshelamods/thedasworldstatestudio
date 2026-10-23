"""Narrow FBMOD export proof for the supplied world-state templates.

This development prototype reuses the assessment's EBX reader. It is not the
finished application. The reviewed templates feed the Anders policy, named
early gameplay cases, and the initial semantic profile compiler's shared writer.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import zlib
from fbmod_metadata import FBMOD_VERSION, metadata_text, validate_icon
from app_runtime import APP_VERSION, resource_root

ROOT = resource_root()
from frostbite_reader import EbxParser, Reader, decode_cas

ASSET = 'da3/configurations/online/bwworldstateconfigasset'
WRITER_VERSION = '0.3-image-slots'
DEFAULT_TEMPLATE = ROOT / 'Customized Worldstates/Custom Worldstates - Vanilla/Custom Worldstate - Queen Cousland - FHawke - Fenris v2.fbmod'


class LocatedEbxParser(EbxParser):
    """Locate named scalar fields while walking the EBX's actual schema."""
    def __init__(self, data):
        super().__init__(data)
        self.frames = []
        self.variables = []

    def read_class(self, cls):
        frame = {'class': cls['name'], 'fields': {}}
        self.frames.append(frame)
        try:
            value = super().read_class(cls)
            if cls['name'] == 'GameVaultVarInt':
                self.variables.append({'value': value, 'fields': frame['fields']})
            return value
        finally:
            self.frames.pop()

    def read_field(self, field):
        if self.frames and self.frames[-1]['class'] == 'GameVaultVarInt' and field['name'] in ('DefaultValue', 'MinValue', 'MaxValue'):
            if field['type_id'] != 0x0f:
                raise ValueError('Expected a signed 32-bit world-state field')
            self.frames[-1]['fields'][field['name']] = self.pos
        return super().read_field(field)


def read_mod(data):
    reader = Reader(data)
    if reader.num('<Q') != 0x01005954534f5246 or reader.num('<I') != 5:
        raise ValueError('Only binary FBMOD format 5 is supported')
    manifest_offset, manifest_count = reader.num('<q'), reader.num('<i')
    profile = reader.take(reader.num('B')).decode('utf8')
    game_version = reader.num('<i')
    if profile != 'DragonAgeInquisition' or game_version != 598987:
        raise ValueError('Unexpected game profile or game data version')
    metadata_start = reader.pos
    # Frosty's NativeReader maps each metadata byte directly to a character.
    # UTF-8 here looks correct to a UTF-8-only checker but garbles in Frosty.
    details = []
    for _ in range(6):
        text = bytearray()
        while (byte := reader.take(1)) != b'\0':
            text.extend(byte)
        details.append(text.decode('latin-1'))
    records = []
    for _ in range(reader.num('<i')):
        start = reader.pos
        kind, index, name = reader.num('B'), reader.num('<i'), reader.string()
        if kind not in (0, 1):
            raise ValueError('Only embedded images and the world-state EBX are supported')
        record = {'kind': kind, 'index': index, 'name': name}
        if index != -1:
            record['sha_offset'] = reader.pos - start
            record.update(sha1=reader.take(20), size=reader.num('<q'), flags=reader.num('B'), handler=reader.num('<i'), user_data=reader.string())
        record['bundles'] = [reader.num('<i') for _ in range(reader.num('<i'))]
        record['raw'] = data[start:reader.pos]
        records.append(record)
    if reader.pos != manifest_offset or not 0 < manifest_count < 100:
        raise ValueError('Unexpected FBMOD manifest layout')
    payloads = []
    for index in range(manifest_count):
        offset, size = struct.unpack_from('<qq', data, manifest_offset + index * 16)
        start = manifest_offset + manifest_count * 16 + offset
        if offset < 0 or size < 0 or start + size > len(data):
            raise ValueError('Invalid manifest payload range')
        payloads.append(data[start:start + size])
    modified = [record for record in records if record['kind'] == 1]
    if len(modified) != 1 or modified[0]['name'] != ASSET or modified[0]['handler'] != 0:
        raise ValueError('Expected one regular world-state replacement asset')
    target = modified[0]
    if not 0 <= target['index'] < len(payloads):
        raise ValueError('Invalid world-state payload index')
    packed = payloads[target['index']]
    if hashlib.sha1(packed).digest() != target['sha1']:
        raise ValueError('World-state payload hash does not match')
    raw, _ = decode_cas(packed)
    if len(raw) != target['size']:
        raise ValueError('World-state payload size does not match')
    return dict(prefix=data[:metadata_start], details=details, records=records, target=target, payloads=payloads, ebx=raw)


def encode_cas(raw):
    """Match Frosty 1.0.6.3's DAI writer, including flags and block boundaries.

    CasReader masks header bits and accepts smaller intermediate blocks, so a
    successful decode is insufficient evidence of game-compatible encoding.
    Frosty's CompressFile uses 64 KiB blocks, zlib level 9 and code 0x0270
    written big-endian. If any compressed block exceeds 64 KiB it restarts
    the entire stream without compression (code 0x0070 plus size high bits).
    """
    blocks = [bytes(raw[start:start + 65536]) for start in range(0, len(raw), 65536)]
    packed_blocks = [zlib.compress(block, level=9) for block in blocks]
    use_raw = any(len(packed) > 65536 for packed in packed_blocks)
    output = bytearray()
    for block, packed in zip(blocks, packed_blocks):
        if use_raw:
            packed = block
        code = (0x0070 if use_raw else 0x0270) | ((len(packed) >> 16) & 15)
        output.extend(struct.pack('>IHH', len(block), code, len(packed) & 0xffff))
        output.extend(packed)
    return bytes(output)


def load_early_cases():
    return json.loads((ROOT / 'prototype/early-test-cases.json').read_text(encoding='utf8'))


def build_mod(template_data, anders=None, *, scenario=None):
    if (anders is None) == (scenario is None):
        raise ValueError('Select exactly one Anders choice or named early test case')
    max_overrides = {}
    if scenario is not None:
        cases = load_early_cases()
        if scenario not in cases['cases']:
            raise ValueError('Unknown early test case')
        case = cases['cases'][scenario]
        values = dict(cases['common_values'], **case['values'])
        max_overrides = case.get('max_value_overrides', {})
        title = case['title']
        explanation = case['summary']
    else:
        policy = json.loads((ROOT / 'assessment/export-policy.json').read_text(encoding='utf8'))
        if anders not in policy['decisions']['anders_fate']['choices']:
            raise ValueError('Unknown Anders choice')
        values = policy['decisions']['anders_fate']['choices'][anders]['export_values']
        title = 'World State Prototype - Anders ' + anders.title()
        explanation = 'Anders follows the user-tested documented mapping.'
    output, report = build_mod_values(template_data, values, max_overrides=max_overrides,
                                     title=title, explanation=explanation)
    if scenario is not None:
        report.update(scenario=scenario, summary=explanation)
    else:
        report.update(anders=anders)
    return output, report


def manager_image_resources(records):
    """Frosty v5 loads slots 0..4 as icon/screenshots by position, not name.

    Preserve existing template bytes/hashes for profile compatibility, while
    upgrading sparse original-game templates at the export boundary.
    """
    images = {}
    names = ['Icon', *('Screenshot' + str(index) for index in range(4))]
    for record in records:
        if record['kind'] == 0 and record['name'] in names:
            if record['name'] in images:
                raise ValueError('Duplicate FBMOD image resource')
            images[record['name']] = record
    if 'Icon' not in images:
        raise ValueError('The FBMOD template has no icon slot')
    for name in names[1:]:
        if name not in images:
            images[name] = dict(kind=0, index=-1, name=name, bundles=[],
                raw=struct.pack('<Bi', 0, -1) + name.encode('ascii') + b'\0' + struct.pack('<i', 0))
    image_ids = {id(record) for record in images.values()}
    return [images[name] for name in names] + [record for record in records if id(record) not in image_ids]


def build_mod_values(template_data, values, *, max_overrides=None, title, explanation, metadata=None):
    """Shared writer for compiled profiles and the unchanged comparison cases."""
    supported = json.loads((ROOT / 'prototype/supported-templates.json').read_text(encoding='utf8'))
    digest = hashlib.sha256(template_data).hexdigest()
    bundled = json.loads((ROOT / 'prototype/bundled-presets.json').read_text(encoding='utf8'))
    if digest not in {entry['sha256'] for entry in [*supported, *bundled['presets']]}:
        raise ValueError('This template is not one of the reviewed supplied mods')
    mod = read_mod(template_data)
    resources = manager_image_resources(mod['records'])
    values = dict(values)
    max_overrides = dict(max_overrides or {})
    if any(type(value) is not int for value in [*values.values(), *max_overrides.values()]):
        raise ValueError('World-state values must be integers, not booleans or strings')
    if not title or any('\0' in text for text in (title, explanation)):
        raise ValueError('Invalid mod metadata')
    if metadata is not None:
        if not isinstance(metadata, dict) or set(metadata) - {'author', 'description', 'icon'}:
            raise ValueError('Unsupported FBMOD metadata field')
        metadata_text(title, 'Mod title', 160, required=True)
        for key, maximum in [('author', 120), ('description', 8000)]:
            if key in metadata:
                metadata_text(metadata[key], key.title(), maximum)
        if metadata.get('icon') is not None:
            validate_icon(metadata['icon'])
    evidence = json.loads((ROOT / 'assessment/reference/worldstate-evidence.json').read_text(encoding='utf8'))
    by_name = {entry['name']: entry for entry in evidence}
    if not set(values).issubset(by_name) or not set(max_overrides).issubset(values):
        raise ValueError('Test policy contains an unrecognized world-state variable')
    for name, maximum in max_overrides.items():
        if maximum != by_name[name].get('keep', {}).get('maximum'):
            raise ValueError('Declared range override does not match the captured Keep evidence')
    parser = LocatedEbxParser(mod['ebx'])
    before = parser.parse()
    raw = bytearray(mod['ebx'])
    changes, matched = [], set()
    for variable in parser.variables:
        value = variable['value']
        name = value['VariableNameOnServer']
        if name not in values:
            continue
        guid = value['PlotFlag']['PlotFlagId']['Guid']
        if guid != by_name[name]['plot_guid']:
            raise ValueError('Plot GUID mismatch for ' + name)
        new_value = values[name]
        maximum = max_overrides.get(name, value['MaxValue'])
        if not value['MinValue'] <= new_value <= maximum:
            raise ValueError('Out-of-range value for ' + name)
        offset = variable['fields'].get('DefaultValue')
        if offset is None:
            raise ValueError('Could not locate the default field for ' + name)
        struct.pack_into('<i', raw, offset, new_value)
        if name in max_overrides:
            max_offset = variable['fields'].get('MaxValue')
            if max_offset is None:
                raise ValueError('Could not locate the maximum field for ' + name)
            struct.pack_into('<i', raw, max_offset, maximum)
        matched.add(name)
        change = dict(name=name, plot_guid=guid, before=value['DefaultValue'], after=new_value)
        if name in max_overrides:
            change.update(maximum_before=value['MaxValue'], maximum_after=maximum)
        changes.append(change)
    if matched != set(values):
        raise ValueError('The template is missing required flags')
    expected = copy.deepcopy(before)
    for obj in expected['objects']:
        value = obj['value']
        if obj['class'] == 'GameVaultVarInt' and value['VariableNameOnServer'] in values:
            value['DefaultValue'] = values[value['VariableNameOnServer']]
            if value['VariableNameOnServer'] in max_overrides:
                value['MaxValue'] = max_overrides[value['VariableNameOnServer']]
    if EbxParser(bytes(raw)).parse() != expected:
        raise ValueError('The edit changed unexpected EBX data')
    packed = encode_cas(raw)
    payloads = list(mod['payloads'])
    payloads[mod['target']['index']] = packed
    details = list(mod['details'])
    details[0] = title
    details[3] = FBMOD_VERSION
    details[4] = ('Export proof based on: ' + mod['details'][0] + '. ' + explanation + ' Choices outside the listed test fields are inherited from the template. Requires gameplay verification.')
    icon_record = None
    icon_data = metadata.get('icon') if metadata else None
    if metadata is not None:
        for key, index in [('author', 1), ('description', 4)]:
            if key in metadata:
                details[index] = metadata[key]
    if icon_data is not None:
        icons = [record for record in mod['records'] if record['kind'] == 0 and record['name'] == 'Icon']
        if len(icons) != 1:
            raise ValueError('Expected one embedded Icon resource')
        icon_record = icons[0]
        index = icon_record['index']
        if index < 0 or any(record is not icon_record and record['index'] == index for record in mod['records']):
            index = len(payloads)
            payloads.append(icon_data)
        else:
            payloads[index] = icon_data
        # Frosty's EmbeddedResource uses a zero SHA-1, a byte length, no handler,
        # and no added bundles. Game resources and screenshots stay untouched.
        icon_raw = (struct.pack('<Bi', 0, index) + b'Icon\0' + bytes(20) +
                    struct.pack('<qBi', len(icon_data), 0, 0) + b'\0' + struct.pack('<i', 0))
    output = bytearray(mod['prefix'])
    for value in details:
        metadata_text(value, 'Mod metadata', 16000)
        output.extend(value.encode('latin-1') + b'\0')
    output.extend(struct.pack('<i', len(resources)))
    for record in resources:
        raw_record = bytearray(icon_raw if record is icon_record else record['raw'])
        if record is mod['target']:
            offset = record['sha_offset']
            raw_record[offset:offset + 20] = hashlib.sha1(packed).digest()
            struct.pack_into('<q', raw_record, offset + 20, len(raw))
        output.extend(raw_record)
    manifest_offset = len(output)
    offset = 0
    for payload in payloads:
        output.extend(struct.pack('<qq', offset, len(payload)))
        offset += len(payload)
    for payload in payloads:
        output.extend(payload)
    struct.pack_into('<qi', output, 12, manifest_offset, len(payloads))
    generated = read_mod(bytes(output))
    if generated['ebx'] != bytes(raw) or generated['payloads'] != payloads:
        raise ValueError('Generated container failed readback')
    report = dict(app_version=APP_VERSION, writer_version=WRITER_VERSION, template_sha256=digest, fields=changes, game_profile='DragonAgeInquisition', game_data_version=598987, inherited_choices='Choices outside the listed fields are copied from the chosen template.', gameplay_tested=False, launch_tested=False)
    icon = next((record for record in generated['records'] if record['kind'] == 0 and record['name'] == 'Icon'), None)
    actual_icon = generated['payloads'][icon['index']] if icon and icon['index'] >= 0 else None
    report['mod_metadata'] = dict(title=details[0], author=details[1], category=details[2],
        version=details[3], description=details[4], icon_sha256=hashlib.sha256(actual_icon).hexdigest() if actual_icon else None,
        icon_bytes=len(actual_icon) if actual_icon else 0)
    return bytes(output), report


def export_file(template, output, anders=None, *, scenario=None):
    template, output = Path(template).resolve(), Path(output).resolve()
    if output == template or output.exists() or output.with_suffix('.report.json').exists():
        raise ValueError('Choose new output filenames; this prototype does not overwrite files')
    data, report = build_mod(template.read_bytes(), anders, scenario=scenario)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as file:
        file.write(data)
    report.update(template=str(template), output=str(output), output_sha256=hashlib.sha256(data).hexdigest())
    with output.with_suffix('.report.json').open('x', encoding='utf8') as file:
        json.dump(report, file, indent=2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, default=DEFAULT_TEMPLATE)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--anders', choices=['alive', 'executed'])
    choice.add_argument('--scenario', choices=list(load_early_cases()['cases']))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = export_file(args.template, args.output, args.anders, scenario=args.scenario)
    except (ValueError, OSError, AssertionError) as error:
        parser.exit(1, f'Export failed: {error}\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
