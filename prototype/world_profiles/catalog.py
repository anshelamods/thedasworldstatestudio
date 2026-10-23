"""Versioned semantic mapping catalog; no paths from profile documents are executed."""
import copy
from dataclasses import replace
from pathlib import Path

from .model import ProfileError, UnsupportedVersion, fingerprint, new_profile, read_json
from app_runtime import resource_root

ROOT = resource_root()
CURRENT_MAPPING_VERSION = 44


class Catalog:
    def __init__(self, mapping_version=None):
        if mapping_version is not None and mapping_version not in range(1, CURRENT_MAPPING_VERSION + 1):
            raise UnsupportedVersion('Unsupported mapping catalog')
        filename = f'catalog-v{mapping_version}.json' if mapping_version in range(1, CURRENT_MAPPING_VERSION) else 'catalog.json'
        data = read_json(ROOT / 'prototype/world_profiles' / filename)
        policy = read_json(ROOT / 'assessment/export-policy.json')
        templates = read_json(ROOT / 'prototype/supported-templates.json')
        evidence = read_json(ROOT / 'assessment/reference/worldstate-evidence.json')
        self._flag_evidence = {entry['name']: dict(plot_guid=entry['plot_guid'],
            keep_maximum=entry.get('keep', {}).get('maximum')) for entry in evidence}
        self._templates = {entry['sha256']: entry for entry in templates}
        self._presets = {}
        for entry in templates:
            preset_id = 'template-' + entry['sha256'][:16]
            self._presets[preset_id] = dict(id=preset_id, label=Path(entry['path']).stem,
                template_sha256=entry['sha256'], export_values={},
                suggested_mode='experimental' if 'Experimental' in entry['path'] else 'ordinary')
        baseline = copy.deepcopy(data['baseline'])
        baseline['suggested_mode'] = 'ordinary'
        self._presets[baseline['id']] = baseline
        if 'default_baseline' in data:
            default = copy.deepcopy(data['default_baseline'])
            self._presets[default['id']] = default
        self.default_preset = data.get('default_baseline', baseline)['id']
        self._choices = copy.deepcopy(data['choices'])
        for definition in self._choices.values():
            if 'export_policy' in definition:
                decision = policy['decisions'][definition['export_policy']]
                definition['policy_evidence'] = decision
                for answer_id, answer in definition['answers'].items():
                    answer.update(copy.deepcopy(decision['choices'][answer_id]))
        self.version = data['mapping_version']
        self.story_rules = read_json(ROOT / 'prototype/world_profiles' / data['story_rules']) if data.get('story_rules') else None
        identity = dict(mapping_version=self.version, presets=self._presets,
                        choices=self._choices, flag_evidence=self._flag_evidence)
        if self.story_rules is not None:
            identity['story_rules'] = self.story_rules
        self.sha256 = fingerprint(identity)

    @property
    def flag_evidence(self):
        return copy.deepcopy(self._flag_evidence)

    @property
    def presets(self):
        return copy.deepcopy(self._presets)

    @property
    def choices(self):
        return copy.deepcopy(self._choices)

    def preset(self, preset_id):
        try:
            return copy.deepcopy(self._presets[preset_id])
        except KeyError as error:
            raise ProfileError('Unknown base preset: ' + str(preset_id)) from error

    def template_path(self, preset_id):
        preset = self.preset(preset_id)
        bundled = read_json(ROOT / 'prototype/bundled-presets.json')
        match = next((entry for entry in bundled['presets']
                      if entry['sha256'] == preset['template_sha256']), None)
        path = ROOT / (match or self._templates[preset['template_sha256']])['path']
        if not path.is_file():
            raise ProfileError('This history uses a legacy preset that is not included in this beta. '
                               'Open and export it with the original development build; its saved data is unchanged.')
        return path

    def validate(self, profile):
        source = self.for_profile(profile)
        if source is not self:
            return source.validate(profile)
        if profile.mapping_version != self.version or profile.mapping_sha256 != self.sha256:
            raise UnsupportedVersion('Profile mapping version/fingerprint differs; explicit migration is required')
        self.preset(profile.base_preset)
        if profile.mode == 'keep' and not self.story_rules:
            raise UnsupportedVersion('Keep restrictions require the current rules catalog')
        for choice_id, answer_id in profile.choices.items():
            if choice_id not in self._choices:
                raise ProfileError('Unsupported story choice: ' + choice_id)
            if answer_id not in self._choices[choice_id]['answers']:
                raise ProfileError('Unsupported answer for ' + choice_id + ': ' + answer_id)

    def for_profile(self, profile):
        if profile.mapping_version == self.version:
            return self
        if profile.mapping_version in range(1, CURRENT_MAPPING_VERSION) and self.version > profile.mapping_version:
            source = Catalog(mapping_version=profile.mapping_version)
            source.validate(profile)
            return source
        raise UnsupportedVersion('Unsupported profile mapping version')

    def upgrade(self, profile):
        """Upgrade without writing, allowing the reviewed v44 survival fallback."""
        source = self.for_profile(profile)
        source.validate(profile)
        if source is self:
            return self.normalize(profile)
        if any(self.presets.get(key) != value for key, value in source.presets.items()):
            raise UnsupportedVersion('Preset changes require a separate migration')
        for choice_id, definition in source.choices.items():
            for answer_id, old in definition['answers'].items():
                new_definition = self._choices.get(choice_id, {})
                new = new_definition.get('answers', {}).get(answer_id)
                if definition.get('export_behavior') != new_definition.get('export_behavior'):
                    raise UnsupportedVersion('Changed export behavior requires a separate migration')
                # v44 intentionally makes living, modded Bethany's unresolved
                # final fate default to survival, matching Circle/Warden Bethany.
                # Explicit final-battle choices still own the field. No career
                # or other assignments may change through this exception.
                survival_default = (source.version < 44 <= self.version
                    and (choice_id, answer_id) == ('da2.bethany_fate', 'alive_unspecified')
                    and old.get('export_values') == {'da2_bethany_alive': 1}
                    and new is not None and new.get('export_values') == {
                        'da2_bethany_alive': 1, 'da2_bethany_final_battle_death': 1})
                if new is None or (old.get('export_values', {}) != new.get('export_values', {})
                                   and not survival_default) or old.get('max_value_overrides', {}) != new.get('max_value_overrides', {}):
                    raise UnsupportedVersion('Changed answer mappings require a separate migration')
                old_requires = dict(definition.get('requires', {}), **old.get('requires', {}))
                new_requires = dict(new_definition.get('requires', {}), **new.get('requires', {}))
                # v2 intentionally relaxes sibling story restrictions at the
                # user's direction, while keeping every old flag assignment.
                if any(old_requires.get(key) != value for key, value in new_requires.items()):
                    raise UnsupportedVersion('Changed story requirements require a separate migration')
        return self.normalize(replace(profile, mapping_version=self.version, mapping_sha256=self.sha256))

    def normalize(self, profile):
        """Split legacy controls only when every effective game flag is preserved."""
        legacy_controls = {'da2.hawke_class', 'dao.warden_origin'} if self.version >= 4 else set()
        if self.version >= 6:
            legacy_controls.add('dao.ferelden_leadership')
        if not legacy_controls & profile.choices.keys():
            return profile
        self.validate(profile)
        from .compiler import compile_profile
        # Story conflicts do not prevent a lossless representation change.
        before = compile_profile(profile.edited(mode='experimental'), catalog=self)
        flags = before.effective_values
        choices = dict(profile.choices)
        if 'da2.hawke_class' in choices:
            gender = 'female' if flags['da2_hawke_mf'] == 1 else 'male'
            choices['da2.hawke_identity'] = gender + '_' + choices.pop('da2.hawke_class')
        if 'dao.warden_origin' in choices:
            gender = 'female' if flags['dao_warden_mf'] == 1 else 'male'
            choices['dao.warden_identity'] = gender + '_' + choices.pop('dao.warden_origin')
        if self.version >= 6 and 'dao.ferelden_leadership' in choices:
            old = choices.pop('dao.ferelden_leadership')
            choices['dao.ferelden_ruler'] = 'alistair_alone' if old == 'alistair_king_alone' else 'anora_alone'
            choices['dao.alistair_fate'] = 'king' if old == 'alistair_king_alone' else 'warden'
            choices['dao.alistair_relationship'] = 'never_lovers'
        candidate = profile.edited(choices=choices)
        after = compile_profile(candidate.edited(mode='experimental'), catalog=self)
        if before.effective_values != after.effective_values or before.max_overrides != after.max_overrides:
            raise UnsupportedVersion('Legacy control conversion would change game flags; explicit migration required')
        return candidate

    def create(self, name, *, base_preset=None, choices=None, mode=None):
        base_preset = self.default_preset if base_preset is None else base_preset
        preset = self.preset(base_preset)
        profile = new_profile(name, base_preset, self.version, self.sha256,
                              choices=choices, mode=preset['suggested_mode'] if mode is None else mode)
        self.validate(profile)
        return profile
