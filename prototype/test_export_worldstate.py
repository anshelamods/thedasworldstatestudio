"""Export checks against the author's released presets, plus input protection."""
import json
import random
import struct
from pathlib import Path
import tempfile
import unittest

from export_worldstate import DEFAULT_TEMPLATE, ROOT, EbxParser, build_mod, export_file, read_mod, load_early_cases, encode_cas, decode_cas

EXECUTED_RELEASE = DEFAULT_TEMPLATE.with_name('Custom Worldstate - Queen Cousland - FHawke - Fenris.fbmod')


class ExportProofTests(unittest.TestCase):
    def test_compressed_bytes_match_all_eight_author_released_payloads(self):
        # Decoding alone masks differences in CAS flags and block boundaries.
        # The author's unchanged released payloads are independent golden data.
        templates = json.loads((ROOT / 'prototype/supported-templates.json').read_text())
        for entry in templates:
            with self.subTest(template=entry['path']):
                original = read_mod((ROOT / entry['path']).read_bytes())
                self.assertEqual(encode_cas(original['ebx']), original['payloads'][original['target']['index']])

    def test_incompressible_data_uses_native_whole_stream_raw_fallback(self):
        raw = random.Random(54321).randbytes(150000)
        encoded = encode_cas(raw)
        decoded, kinds = decode_cas(encoded)
        self.assertEqual(decoded, raw)
        self.assertEqual(kinds, [0, 0, 0])
        self.assertEqual(encoded[:8], struct.pack('>IHH', 65536, 0x0071, 0))

    def test_released_anders_payloads_match_including_compression(self):
        for answer, reference in [('alive', DEFAULT_TEMPLATE), ('executed', EXECUTED_RELEASE)]:
            with self.subTest(answer=answer):
                source = EXECUTED_RELEASE if answer == 'alive' else DEFAULT_TEMPLATE
                actual = read_mod(build_mod(source.read_bytes(), answer)[0])
                expected = read_mod(reference.read_bytes())
                self.assertEqual(actual['payloads'], expected['payloads'])
                self.assertEqual(actual['target']['raw'], expected['target']['raw'])

    def test_executed_reproduces_released_ebx_exactly(self):
        generated, report = build_mod(DEFAULT_TEMPLATE.read_bytes(), 'executed')
        actual = read_mod(generated)
        release = read_mod(EXECUTED_RELEASE.read_bytes())
        self.assertEqual(actual['ebx'], release['ebx'])
        self.assertEqual(len(report['fields']), 3)

    def test_alive_reproduces_released_ebx_in_reverse(self):
        generated, _ = build_mod(EXECUTED_RELEASE.read_bytes(), 'alive')
        self.assertEqual(read_mod(generated)['ebx'], read_mod(DEFAULT_TEMPLATE.read_bytes())['ebx'])

    def test_embedded_payloads_survive_export(self):
        source = read_mod(DEFAULT_TEMPLATE.read_bytes())
        generated = read_mod(build_mod(DEFAULT_TEMPLATE.read_bytes(), 'executed')[0])
        target_index = source['target']['index']
        for index, payload in enumerate(source['payloads']):
            if index != target_index:
                self.assertEqual(payload, generated['payloads'][index])

    def test_reviewed_templates_can_export_both_choices(self):
        templates = json.loads((ROOT / 'prototype/supported-templates.json').read_text())
        for entry in templates:
            for choice in ('alive', 'executed'):
                with self.subTest(template=entry['path'], choice=choice):
                    generated, _ = build_mod((ROOT / entry['path']).read_bytes(), choice)
                    result = read_mod(generated)
                    self.assertEqual(result['target']['name'], 'da3/configurations/online/bwworldstateconfigasset')

    def test_modified_template_is_rejected(self):
        changed = bytearray(DEFAULT_TEMPLATE.read_bytes())
        changed[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'not one of the reviewed'):
            build_mod(bytes(changed), 'executed')

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'prototype', prefix='.test-') as directory:
            self.assertTrue(Path(directory).resolve().is_relative_to((ROOT / 'prototype').resolve()))
            output = Path(directory) / 'existing.fbmod'
            output.write_bytes(b'preserve this file')
            with self.assertRaisesRegex(ValueError, 'does not overwrite'):
                export_file(DEFAULT_TEMPLATE, output, 'executed')
            self.assertEqual(output.read_bytes(), b'preserve this file')

    def test_sibling_cases_only_change_the_sibling_group_from_baseline(self):
        def variables(case):
            data = build_mod(DEFAULT_TEMPLATE.read_bytes(), scenario=case)[0]
            objects = EbxParser(read_mod(data)['ebx']).parse()['objects']
            return {obj['value']['VariableNameOnServer']: obj['value'] for obj in objects if obj['class'] == 'GameVaultVarInt'}
        baseline = variables('00-baseline')
        for case, expected_names in [
            ('01-bethany-warden', {'da2_bethany_career', 'da2_bethany_is_warden'}),
            ('02-bethany-dead', {'da2_bethany_career', 'da2_bethany_alive', 'da2_bethany_final_battle_death', 'da2_bethany_died_deep_roads'}),
        ]:
            with self.subTest(case=case):
                current = variables(case)
                self.assertEqual({name for name in baseline if baseline[name] != current[name]}, expected_names)

    def test_early_cases_preserve_every_field_outside_the_declared_assignments(self):
        source = EbxParser(read_mod(DEFAULT_TEMPLATE.read_bytes())['ebx']).parse()
        for case in load_early_cases()['cases']:
            with self.subTest(case=case):
                data, report = build_mod(DEFAULT_TEMPLATE.read_bytes(), scenario=case)
                current = EbxParser(read_mod(data)['ebx']).parse()
                allowed = {field['name'] for field in report['fields']}
                for old, new in zip(source['objects'], current['objects']):
                    if old['class'] == 'GameVaultVarInt' and old['value']['VariableNameOnServer'] in allowed:
                        old_metadata, new_metadata = dict(old['value']), dict(new['value'])
                        old_metadata.pop('DefaultValue')
                        new_metadata.pop('DefaultValue')
                        if case == '04-loghain-alive' and old['value']['VariableNameOnServer'] == 'dao_loghain_fate':
                            self.assertEqual(new_metadata['MaxValue'], 4)
                            old_metadata.pop('MaxValue')
                            new_metadata.pop('MaxValue')
                        self.assertEqual(old_metadata, new_metadata)
                    else:
                        self.assertEqual(old, new)

    def test_ruler_and_loghain_cases_have_consistent_core_flags(self):
        states = {}
        for case in ['00-baseline', '03-anora-rules', '04-loghain-alive']:
            data = build_mod(DEFAULT_TEMPLATE.read_bytes(), scenario=case)[0]
            objects = EbxParser(read_mod(data)['ebx']).parse()['objects']
            states[case] = {o['value']['VariableNameOnServer']: o['value']['DefaultValue'] for o in objects if o['class'] == 'GameVaultVarInt'}
        for values in states.values():
            self.assertEqual(sum(values[n] for n in ['dao_alistair_king_alone', 'dao_alistair_king_with_anora', 'dao_alistair_king_with_warden', 'dao_anora_queen_alone', 'dao_anora_queen_with_warden']), 1)
            self.assertEqual(values['dao_warden_married_alistair'], 0)
        self.assertEqual(states['03-anora-rules']['dao_anora_queen_alone'], 1)
        self.assertEqual(states['03-anora-rules']['dao_alistair_royal_status'], 0)
        self.assertEqual(states['03-anora-rules']['dao_alistair_state'], 3)
        self.assertEqual(states['04-loghain-alive']['dao_loghain_alive'], 1)
        self.assertEqual(states['04-loghain-alive']['dao_loghain_executed'], 0)
        self.assertEqual(states['04-loghain-alive']['dao_loghain_recruited'], 1)

    def test_ambiguous_or_unknown_choice_is_rejected(self):
        for arguments in [dict(), dict(anders='alive', scenario='00-baseline'), dict(scenario='unknown')]:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                build_mod(DEFAULT_TEMPLATE.read_bytes(), **arguments)


if __name__ == '__main__':
    unittest.main(verbosity=2)
