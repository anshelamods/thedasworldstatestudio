"""One semantic compiler for FBMOD export and, eventually, a bridge adapter."""
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from types import MappingProxyType

from export_worldstate import EbxParser, build_mod_values, read_mod
from .catalog import Catalog
from .model import ProfileError, fingerprint


class StoryConflict(ProfileError):
    pass


def choice_assignments(catalog, choices, choice_id, answer):
    battle = catalog.version >= 7 and 'dao.archdemon_killer' in choices
    finale = catalog.version >= 26 and 'da2.bethany_final_battle' in choices
    # An explicit recruitment answer replaces the older fate answer's copied
    # boolean. Clearing it restores that fallback, including for free histories.
    wynne_recruitment = catalog.version >= 35 and 'dao.wynne_recruited' in choices
    return {name: value for name, value in answer['export_values'].items()
            if not (battle and choice_id in {'dao.alistair_fate', 'dao.loghain_fate', 'dao.ferelden_leadership'}
                    and name in {'dao_alistair_killed_archdemon', 'dao_loghain_killed_archdemon'})
            and not (finale and choice_id == 'da2.bethany_fate' and name == 'da2_bethany_final_battle_death')
            and not (wynne_recruitment and choice_id == 'dao.wynne_fate' and name == 'dao_wynne_recruited')}


@dataclass(frozen=True)
class CompiledProfile:
    values: object
    max_overrides: object
    report: dict
    template_data: bytes = field(repr=False)
    effective_values: object = field(repr=False)


def compile_profile(profile, *, catalog=None):
    catalog = catalog or Catalog()
    catalog = catalog.for_profile(profile)
    catalog.validate(profile)
    preset = catalog.preset(profile.base_preset)
    template = catalog.template_path(profile.base_preset).read_bytes()
    if hashlib.sha256(template).hexdigest() != preset['template_sha256']:
        raise ProfileError('Reviewed base template has changed; refusing to reinterpret the profile')
    objects = EbxParser(read_mod(template)['ebx']).parse()['objects']
    effective = {obj['value']['VariableNameOnServer']: obj['value']['DefaultValue']
                 for obj in objects if obj['class'] == 'GameVaultVarInt'}
    inherited = dict(effective)
    values = dict(preset['export_values'])
    maximums, owners, selections = {}, {}, []
    definitions = catalog.choices
    battle_explicit = catalog.version >= 7 and 'dao.archdemon_killer' in profile.choices
    battle_flags = {'dao_alistair_killed_archdemon', 'dao_loghain_killed_archdemon'}
    legacy_battle_copies = {'dao.alistair_fate', 'dao.loghain_fate', 'dao.ferelden_leadership'}
    bethany_finale_explicit = catalog.version >= 26 and 'da2.bethany_final_battle' in profile.choices
    bethany_finale_flag = 'da2_bethany_final_battle_death'

    def assignments(choice_id, answer):
        # Old profiles keep their exact redundant assignments. Once the user
        # explicitly edits the battle, its kill flags have one authoritative
        # owner; survival/career fields are still owned by the fate controls.
        return choice_assignments(catalog, profile.choices, choice_id, answer)

    for choice_id, answer_id in sorted(profile.choices.items()):
        definition = definitions[choice_id]
        answer = definition['answers'][answer_id]
        profile_only = definition.get('export_behavior') == 'profile-only'
        if profile_only and (answer['export_values'] or answer.get('max_value_overrides')
                             or definition.get('requires') or answer.get('requires')):
            raise ProfileError('Profile-only choices cannot assign game values, ranges or story requirements')
        for name, value in assignments(choice_id, answer).items():
            if name in owners and values[name] != value:
                raise ProfileError('Mappings assign conflicting values to ' + name)
            values[name], owners[name] = value, choice_id
        for name, maximum in answer.get('max_value_overrides', {}).items():
            if name in maximums and maximums[name] != maximum:
                raise ProfileError('Mappings assign conflicting ranges to ' + name)
            maximums[name] = maximum
        selections.append(dict(choice_id=choice_id, answer_id=answer_id, label=answer['label'],
                               evidence_status=definition['evidence_status'], basis=definition['basis']))
        if profile_only:
            selections[-1]['export_behavior'] = 'profile-only'
    effective.update(values)
    # Compilation is also the future bridge boundary, so technical validation
    # belongs here as well as in the FBMOD writer.
    flags = {obj['value']['VariableNameOnServer']: obj['value']
             for obj in objects if obj['class'] == 'GameVaultVarInt'}
    evidence = catalog.flag_evidence
    if not set(maximums).issubset(values):
        raise ProfileError('A range override lacks a corresponding flag assignment')
    for name, value in values.items():
        if name not in flags or name not in evidence:
            raise ProfileError('Mapping references an unknown game flag: ' + name)
        flag = flags[name]
        if flag['PlotFlag']['PlotFlagId']['Guid'] != evidence[name]['plot_guid']:
            raise ProfileError('Plot GUID mismatch for ' + name)
        maximum = maximums.get(name, flag['MaxValue'])
        if name in maximums and maximum != evidence[name]['keep_maximum']:
            raise ProfileError('Unsupported range override for ' + name)
        if type(value) is not int or type(maximum) is not int or not flag['MinValue'] <= value <= maximum:
            raise ProfileError('Unsupported technical value for ' + name)
    conflicts = []
    for choice_id in profile.choices:
        definition = definitions[choice_id]
        answer = definition['answers'][profile.choices[choice_id]]
        requirements = dict(definition.get('requires', {}), **answer.get('requires', {}))
        if answer.get('requires_unrestricted') and profile.mode != 'experimental':
            conflicts.append(choice_id + ': this outcome requires No Story Restrictions')
        for name, expected in requirements.items():
            if effective.get(name) != expected:
                conflicts.append(f'{choice_id} requires {name}={expected}; inherited/selected value is {effective.get(name)}')
    if (effective.get('dao_loghain_recruited') == 1 and effective.get('dao_alistair_alive') == 1
            and effective.get('dao_alistair_state') == 3 and effective.get('dao_alistair_royal_status') == 0
            and effective.get('dao_alistair_drunk') == 0):
        conflicts.append('Recruited Loghain conflicts with Alistair remaining a non-royal Grey Warden')
    if catalog.version >= 6 and {'dao.ferelden_ruler', 'dao.alistair_fate'} & profile.choices.keys():
        if (effective.get('dao_alistair_royal_status') == 1) != (effective.get('dao_alistair_state') == 2):
            conflicts.append('The throne of Ferelden and Alistair’s fate disagree about whether Alistair is king')
    if catalog.version >= 7:
        ritual = effective.get('dao_morrigan_baby') in (1, 2, 3)
        killer = effective.get('dao_archdemon_killer')
        if {'dao.warden_fate', 'dao.archdemon_killer', 'dao.morrigan_child'} <= profile.choices.keys():
            survives = killer != 0 or ritual
            if effective['dao_warden_alive'] != int(survives):
                conflicts.append('The Warden’s survival disagrees with the selected final battle and Dark Ritual')
        if battle_explicit:
            for person in ('alistair', 'loghain'):
                fate_key = 'dao.' + person + '_fate'
                if fate_key not in profile.choices:
                    continue
                selected_killer = killer == (1 if person == 'alistair' else 2)
                sacrificed = profile.choices[fate_key] == 'sacrificed'
                alive = effective['dao_' + person + '_alive'] == 1
                if (selected_killer and (alive != ritual or (not ritual and not sacrificed))) or (sacrificed and (not selected_killer or ritual)):
                    conflicts.append(person.title() + '’s fate disagrees with the selected final battle and Dark Ritual')
                if selected_killer and person == 'loghain' and effective['dao_loghain_recruited'] != 1:
                    conflicts.append('Loghain must be recruited to deliver the killing blow to the Archdemon')
    if profile.mode == 'keep':
        from .story_rules import RuleSet
        conflicts.extend(RuleSet(catalog).messages(effective, profile.choices, preset_id=profile.base_preset))
    if conflicts and profile.mode in ('ordinary', 'keep'):
        raise StoryConflict('; '.join(conflicts) + '. Adjust the choices or deliberately use experimental mode.')
    warnings = [
        'The author reports extensive testing of the working documentation. These generated configurations have representative gameplay observations for Warden Bethany and Loghain alive / Alistair king; other branches are not individually confirmed here.',
        'Unmapped history is inherited from the reviewed preset, including any unresolved source inconsistencies.'
    ]
    warnings.extend(conflicts)
    if preset.get('inherited_rule_exceptions'):
        warnings.append('The original game asset has inconsistent Isabela recruitment/return defaults. '
                        'These are preserved while both choices are inherited; editing either applies normal story restrictions.')
    if catalog.version >= 6 and {'dao.ferelden_ruler', 'dao.alistair_fate', 'dao.alistair_relationship'} & profile.choices.keys():
        warnings.append('Political outcomes do not automatically change primary romance, hero identity, or ritual/final-battle history; only the implemented explicit-choice consistency checks are enforced.')
    if catalog.version >= 7 and 'dao.morrigan_child' in profile.choices:
        warnings.append('dao_morrigan_has_child needs verification: exports follow the author’s documented/released setup (1 for any child), despite the supplied editor’s normal-child-only label.')
    if any(selection['evidence_status'] == 'disputed' for selection in selections):
        warnings.append('One or more selected mappings have conflicting source evidence; see selections for their basis.')
    resolved = {}
    for choice_id, definition in definitions.items():
        if definition.get('export_behavior') == 'profile-only':
            # Empty assignments carry no inherited game meaning. Resolve only
            # an explicit profile selection, without guessing from the template.
            answer_id = profile.choices.get(choice_id)
            resolved[choice_id] = dict(answer_id=answer_id,
                source='explicit_selection' if answer_id else 'not_selected',
                evidence_status=definition['evidence_status'], export_behavior='profile-only',
                label=definition['answers'][answer_id]['label'] if answer_id else None)
            if answer_id:
                warnings.append(choice_id + ': saved in the profile only; not exported to DAI.')
            continue
        matches = [answer_id for answer_id, answer in definition['answers'].items()
                   if (not answer.get('requires_unrestricted') or profile.choices.get(choice_id) == answer_id)
                   and all(effective.get(name) == value for name, value in assignments(choice_id, answer).items())]
        selected = profile.choices.get(choice_id)
        answer_id = selected if selected in matches else matches[0] if len(matches) == 1 else None
        choice_flags = {name for answer in definition['answers'].values() for name in answer['export_values']}
        source = ('explicit_selection' if choice_id in profile.choices else
                  'base_preset' if choice_flags & preset['export_values'].keys() else 'inherited_template')
        resolved[choice_id] = dict(answer_id=answer_id, source=source,
                                  evidence_status=definition['evidence_status'],
                                  label=definition['answers'][answer_id]['label'] if answer_id else None)
        if answer_id is None:
            warnings.append(choice_id + ': the effective flags do not match one supported answer; preserved without guessing.')
    report = dict(profile_id=profile.profile_id, revision=profile.revision, name=profile.name,
                  profile_sha256=profile.sha256, mapping_version=catalog.version, mapping_sha256=catalog.sha256,
                  base_preset=profile.base_preset, template_sha256=preset['template_sha256'],
                  mode=profile.mode, selections=selections, resolved_choices=resolved,
                  warnings=warnings, story_conflicts=conflicts,
                  inherited_flag_count=len(inherited.keys() - values.keys()),
                  compiled_values_sha256=fingerprint(dict(values=values, max_value_overrides=maximums)),
                  hero_appearance=dict(
                      dao=dict(gender='female' if effective.get('dao_warden_mf') == 1 else 'male',
                               race={0: 'human', 1: 'elf', 2: 'dwarf'}.get(effective.get('dao_warden_race'), 'human'),
                               **{'class': {0: 'warrior', 1: 'rogue', 2: 'mage'}.get(effective.get('dao_warden_class'), 'warrior')}),
                      da2=dict(gender='female' if effective.get('da2_hawke_mf') == 1 else 'male')),
                  gameplay_tested=False, bridge_available=False)
    if battle_explicit:
        report['battle_flag_ownership'] = dict(owner='dao.archdemon_killer',
            flags={name: effective[name] for name in sorted(battle_flags)},
            superseded_copies=[dict(choice_id=key, flag=name, legacy_value=answer['export_values'][name])
                for key in sorted(profile.choices.keys() & legacy_battle_copies)
                for answer in [definitions[key]['answers'][profile.choices[key]]]
                for name in sorted(answer['export_values'].keys() & battle_flags)])
    if bethany_finale_explicit:
        report['bethany_final_battle_ownership'] = dict(owner='da2.bethany_final_battle',
            flag=bethany_finale_flag, value=effective[bethany_finale_flag],
            superseded_copies=[dict(choice_id='da2.bethany_fate', flag=bethany_finale_flag,
                legacy_value=definitions['da2.bethany_fate']['answers'][profile.choices['da2.bethany_fate']]['export_values'][bethany_finale_flag])]
                if 'da2_bethany_final_battle_death' in definitions['da2.bethany_fate']['answers'].get(profile.choices.get('da2.bethany_fate'), {}).get('export_values', {}) else [])
    return CompiledProfile(MappingProxyType(values), MappingProxyType(maximums), report, template,
                           MappingProxyType(effective))


def build_profile_mod(profile, *, catalog=None, title=None, metadata=None):
    catalog = catalog or Catalog()
    compiled = compile_profile(profile, catalog=catalog)
    # The writer repeats the template/hash, GUID, range and preservation checks.
    data, report = build_mod_values(compiled.template_data, compiled.values,
                                   max_overrides=compiled.max_overrides, title=title if title is not None else 'World State - ' + profile.name,
                                   explanation='Saved profile revision ' + str(profile.revision) + '. ' +
                                   'Only supported selections are changed; other history is inherited from the reviewed preset.', metadata=metadata)
    report['profile'] = compiled.report
    return data, report


class ExportCollision(ProfileError):
    """An output name was already taken, including by another app process."""


def export_profile_mod(profile, output, *, catalog=None, title=None, metadata=None):
    from .storage import write_new_json, write_new_bytes
    output = Path(output)
    report_path = output.with_suffix('.report.json')
    if output.suffix.lower() != '.fbmod':
        raise ProfileError('FBMOD output must end in .fbmod')
    if output.exists() or report_path.exists():
        raise ExportCollision('Choose new export filenames; existing outputs are preserved')
    data, report = build_profile_mod(profile, catalog=catalog, title=title, metadata=metadata)
    report.update(output=str(output.resolve()), output_sha256=hashlib.sha256(data).hexdigest())
    # Reserve the report first. A failed mod write removes only our own new report.
    try:
        write_new_json(report_path, report)
    except FileExistsError as error:
        raise ExportCollision('The export report filename is already in use') from error
    try:
        write_new_bytes(output, data)
    except FileExistsError as error:
        report_path.unlink()
        raise ExportCollision('The export filename is already in use') from error
    except BaseException:
        report_path.unlink()
        raise
    return report
