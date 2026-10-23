"""Conservative DA2 -> semantic choices adapter, with per-choice provenance.

Active Hawke plots supply DA2 choices. The separate imported DAO world-vault
table supplies DAO choices and is never treated as Hawke's history. See assessment/DA2 save
import mappings.md for the vanilla plot/script evidence behind these rules.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata

from . import suggested_import_name
from .gff import ListView, Node, SaveFormatError, SaveReader
from .da2_act1 import infer_act1, SUPPORTED as ACT1_SUPPORTED
from .da2_companions import infer_companions, SUPPORTED as COMPANION_SUPPORTED
from .worldvault import DaoHistory, infer_dao, SUPPORTED as DAO_SUPPORTED
from .dao_carried import infer as infer_carried_dao, SUPPORTED as CARRIED_DAO_SUPPORTED
from .da2_nathaniel import reconcile as reconcile_nathaniel, SUPPORTED as NATHANIEL_SUPPORTED
from .da2_remaining import infer_remaining, reconcile_crows, SUPPORTED as REMAINING_SUPPORTED

ACT = '49BEAD07708649F0AC61A9AF4FF03127'
PARTY = '18854EB329424101AAD5D80BD648D445'
PERSONALITY = 'D1C4E624FFF54413AD7DADD63B1CC2F3'
FINALE = '5FDEFF4F87044A6E8E84965764A1C4B2'
QUNARI = 'C930F422EBC743F59CEDFAADC7E8FD35'
DANARIUS = '9604A548CADF473D89E6B5FB89264597'
BARTRAND = 'F216801F3A5040E6B81F2F1594C6563E'
IDOL = '6ECB8A5A28804B28949238CA3A45B81B'
FEYNRIEL = '1831240234E24ECC88C5163837BBC0D6'
ROMANCES = {
    'anders': '094CAC525ED84A5B9D50FCBE256524F6',
    'fenris': '440003846E3F4EAEA385568EBCBE3534',
    'isabela': '5FBF48C14DF34B8DBB5D8F9A06FA114F',
    'merrill': '2B206E2501BF40A48ED9A4B6EF7533A4',
}
SEBASTIAN = '6715A6F7397B46668E0D89DC8DFC2669'
SUPPORTED = ACT1_SUPPORTED | COMPANION_SUPPORTED | NATHANIEL_SUPPORTED | REMAINING_SUPPORTED | frozenset('da2.' + key for key in (
    'hawke_identity', 'hawke_personality', 'final_allegiance', 'bethany_fate', 'carver_fate',
    'hawke_romance', 'fenris_recruited', 'isabela_recruited', 'sebastian_recruited', 'feynriel_fate',
    'bartrand_fate', 'varric_idol', 'varric_quest', 'varric_relationship', 'isabela_book',
    'isabela_handover', 'arishok_fate', 'fenris_danarius', 'fenris_fate', 'anders_fate', 'merrill_fate'))
RETIRED = {'da2.hawke_class', 'dao.warden_origin', 'dao.ferelden_leadership'}


def sequence(value, limit, name):
    if not isinstance(value, (ListView, tuple, list)) or len(value) > limit:
        raise SaveFormatError('Invalid or oversized ' + name + ' table in the save.')
    return value


class Snapshot:
    def __init__(self, payload):
        self.reader = SaveReader(payload)
        seen = sequence(self.reader.get((16003, 16503), ()), 200000, 'spoken dialogue')
        if any(type(ref) is not int or not 0 <= ref <= 0xFFFFFFFF for ref in seen):
            raise SaveFormatError('Invalid spoken dialogue record.')
        self.seen = frozenset(seen)
        self.plots = {}
        self.unrecognized_plots = 0
        for row in sequence(self.reader.get((16003, 16400, 16401)), 20000, 'active plot'):
            if not isinstance(row, Node):
                raise SaveFormatError('Invalid active plot record.')
            guid = row.get(16402)
            if not isinstance(guid, str) or not re.fullmatch('[0-9a-fA-F]{32}', guid):
                # Some mods use resource names (e.g. cov_mount_mac) as plot
                # identifiers. They cannot match any vanilla mapping.
                self.unrecognized_plots += 1
                continue
            guid = guid.upper()
            words = tuple(row.get(i) for i in range(16403, 16407))
            if guid in self.plots or any(type(w) is not int or not -2**31 <= w < 2**32 for w in words):
                raise SaveFormatError('Duplicate or invalid active plot record.')
            self.plots[guid] = tuple(w & 0xFFFFFFFF for w in words)
        if not self.plots or ACT not in self.plots:
            raise SaveFormatError('This save does not contain the supported DA2 campaign plot data.')
        self.party = {}
        for row in sequence(self.reader.get((16003, 16204), ()), 256, 'follower'):
            if not isinstance(row, Node):
                raise SaveFormatError('Invalid follower record.')
            template = row.get(3)
            if not isinstance(template, str):
                continue
            template = template.lower().removesuffix('.utc')
            if template in self.party:
                raise SaveFormatError('Duplicate follower template in the save.')
            self.party[template] = (row.get(16203), row.get(23))
        self.approvals = {}
        for row in sequence(self.reader.get((16003, 16275), ()), 256, 'follower approval'):
            if not isinstance(row, Node):
                raise SaveFormatError('Invalid follower approval record.')
            who, value = row.get(16276), row.get(16277)
            if type(who) is int and type(value) is int:
                if who in self.approvals:
                    raise SaveFormatError('Duplicate follower approval record.')
                self.approvals[who] = value

    def bit(self, guid, flag):
        words = self.plots.get(guid)
        return None if words is None else bool(words[flag // 32] & (1 << (flag % 32)))

    def available(self, name):
        return self.party.get('gen00fl_' + name, (None, None))[0] in (1, 2)

    def approval(self, name):
        who = self.party.get('gen00fl_' + name, (None, None))[1]
        return self.approvals.get(who)


def infer(snapshot):
    """Pure, conservative inference; missing records never mean negative flags."""
    s, bit = snapshot, snapshot.bit
    choices, evidence, notes = {}, {}, {}

    def put(key, answer, source):
        choices['da2.' + key] = answer
        evidence['da2.' + key] = source

    def unique(key, guid, outcomes):
        found = [(flag, answer) for flag, answer in outcomes.items() if bit(guid, flag)]
        if len(found) == 1:
            flag, answer = found[0]
            put(key, answer, f'{guid} / stored flag {flag}')
        elif len(found) > 1:
            notes['da2.' + key] = 'The save contains conflicting outcome markers; choose this outcome manually.'

    act3 = bool(bit(ACT, 4) or bit(ACT, 5))
    final_side = bool(bit(FINALE, 0) or bit(FINALE, 1))
    unique('hawke_personality', PERSONALITY, {3: 'aggressive', 4: 'diplomatic', 5: 'humourous'})
    unique('final_allegiance', FINALE, {0: 'mages', 1: 'templars'})

    for name, outcomes in (
        ('bethany', {7: 'warden', 9: 'circle', 11: 'lothering_death', 13: 'deep_roads_death'}),
        ('carver', {6: 'warden', 8: 'templar', 10: 'lothering_death', 12: 'deep_roads_death'}),
    ):
        key = name + '_fate'
        unique(key, ACT, outcomes)
        # Only after the Deep Roads is it meaningful to ask for a career. A
        # living, available modded sibling without one must not acquire a career
        # or a class-based death merely to satisfy vanilla story restrictions.
        if ('da2.' + key not in choices and 'da2.' + key not in notes
                and bit(ACT, 2) and s.available(name)):
            put(key, 'alive_unspecified', 'Available living follower after Act I; no stored standard career/death marker')

    completed, active = [], []
    for name, guid in ROMANCES.items():
        if bit(guid, 15):
            continue  # ended explicitly clears active in vanilla game logic
        if bit(guid, 18):
            completed.append(name)
        elif bit(guid, 13):
            active.append(name)
    if bit(SEBASTIAN, 11):
        completed.append('sebastian')
    elif bit(SEBASTIAN, 10):
        active.append('sebastian')
    if len(completed) == 1:
        put('hawke_romance', completed[0], 'Unique completed romance (APP 18 / Sebastian marriage 11); earlier active romances do not override completion')
    elif not completed and len(active) == 1:
        put('hawke_romance', active[0], 'Unique active, non-ended romance in this save (APP 13 / Sebastian 10)')
    elif not completed and not active and all(g in s.plots for g in (*ROMANCES.values(), SEBASTIAN)):
        put('hawke_romance', 'none', 'All supported romance plots are present with no active or completed relationship')
    else:
        notes['da2.hawke_romance'] = 'Romance markers are missing or indicate multiple partners; no partner was guessed.'

    for name, flag in (('fenris', 26), ('isabela', 17), ('sebastian', 28)):
        if bit(PARTY, flag) or s.available(name):
            put(name + '_recruited', 'recruited', f'{PARTY} / recruitment {flag}, or currently available follower')

    unique('feynriel_fate', FEYNRIEL, {8: 'tranquil', 9: 'tevinter', 10: 'possessed'})
    unique('bartrand_fate', BARTRAND, {6: 'killed', 7: 'alive'})
    unique('varric_idol', IDOL, {3: 'kept', 11: 'not_kept'})
    if bit(IDOL, 3) or bit(IDOL, 11):
        put('varric_quest', 'completed', f'{IDOL} / fragment kept (3) or forged into a rune (11)')
    approval = s.approval('varric')
    if approval is not None:
        put('varric_relationship', 'friends' if approval >= 0 else 'rivals',
            'Follower approval table (16275), matched to Varric object ID; vanilla APP 261 tests approval >= 0')

    if bit(QUNARI, 30):
        put('isabela_recruited', 'recruited', f'{QUNARI} / handed over (30) establishes prior recruitment')
        put('isabela_book', 'returned', f'{QUNARI} / handed over (30) after her return')
        put('isabela_handover', 'handed_over', f'{QUNARI} / 30')
        if act3:
            put('arishok_fate', 'not_killed', f'{QUNARI} / departure with Isabela (30), Act III reached')
    elif act3 and (bit(QUNARI, 26) or bit(QUNARI, 29)):
        # 26 and 29 initiate battles too; reaching Act III establishes that the
        # battle resolved. Testing either without this gate imports future events.
        put('arishok_fate', 'killed', f'{QUNARI} / duel (26) or battle (29), Act III reached')
        put('isabela_handover', 'not_handed_over', f'{QUNARI} / battle resolved and handover (30) clear')
    if bit(QUNARI, 25) or (act3 and s.available('isabela') and bit(QUNARI, 30) is False):
        put('isabela_recruited', 'recruited', 'Isabela return scene (QCR 25), or available in Act III without handover')
        put('isabela_book', 'returned', 'Isabela return scene (QCR 25), or available in Act III without handover')

    if bit(DANARIUS, 3) or bit(DANARIUS, 12):
        put('fenris_recruited', 'recruited', f'{DANARIUS} / returned to Danarius')
        put('fenris_danarius', 'returned', f'{DANARIUS} / 3 or 12')
        put('fenris_fate', 'returned', f'{DANARIUS} / 3 or 12')
    elif bit(DANARIUS, 8) or bit(DANARIUS, 9):
        put('fenris_danarius', 'not_returned', f'{DANARIUS} / sister aftermath after defeating Danarius (8 or 9)')
        if s.available('fenris') and not bit(FINALE, 53):
            put('fenris_fate', 'alive', 'Danarius defeated; Fenris is available without final hostile removal')

    if final_side and (bit(FINALE, 96) or bit(FINALE, 97)) and not bit(FINALE, 56):
        put('anders_fate', 'alive', f'{FINALE} / sent away alive (96) or asked to help (97), without hostile removal')
    if final_side and s.available('merrill') and bit(FINALE, 55) is False:
        put('merrill_fate', 'alive', 'Merrill is available at the final allegiance choice without hostile removal')

    infer_act1(s, put, notes)
    infer_companions(s, put, notes)
    infer_remaining(s, put, notes)
    return choices, evidence, notes


def import_save(payload, catalog):
    snapshot = Snapshot(payload)
    choices, evidence, notes = infer(snapshot)
    r = snapshot.reader
    name = r.get((16002, 16208, 16255))
    name = ''.join(c for c in name if not unicodedata.category(c).startswith('C')).strip()[:80] if isinstance(name, str) else ''
    name = name or 'Hawke'
    gender = {1: 'male', 2: 'female'}.get(r.get((16002, 16208, 16320, 16322)))
    primary = []
    for row in sequence(r.get((16002, 16208, 16209, 16350), ()), 512, 'player property'):
        if isinstance(row, Node) and row.get(16353) == 50:
            primary.append(row.get(16300))
    value = primary[0] if len(primary) == 1 else None
    hero_class = {1: 'warrior', 2: 'rogue', 3: 'mage'}.get(value) if type(value) in (int, float) and math.isfinite(value) else None
    if gender and hero_class:
        choices['da2.hawke_identity'] = gender + '_' + hero_class
        evidence['da2.hawke_identity'] = 'Player appearance gender (16322) and primary attribute property 50 (Strength / Dexterity / Magic); standard-class inference'
    else:
        notes['da2.hawke_identity'] = 'Player gender or standard class could not be established; custom class data needs review.'
    history = DaoHistory(r)
    dao_choices, dao_evidence, dao_notes = infer_dao(history)
    recovered, sources, reasons = infer_carried_dao(history)
    # Enrich missing outcomes without replacing an existing world-vault answer.
    # Later DA2 quest reconciliations keep their separate authority below.
    for key, answer in recovered.items():
        if key not in dao_choices:
            dao_choices[key] = answer
            dao_evidence[key] = sources[key]
            dao_notes.pop(key, None)
    dao_notes.update({key: reason for key, reason in reasons.items() if key not in dao_choices})
    choices.update(dao_choices)
    evidence.update(dao_evidence)
    notes.update(dao_notes)
    reconcile_crows(snapshot, choices, evidence, notes)
    corrected_nathaniel = reconcile_nathaniel(snapshot, choices, evidence, notes)
    definitions = catalog.choices
    for key, answer in choices.items():
        if key not in definitions or answer not in definitions[key]['answers']:
            raise SaveFormatError('The importer and mapping catalog are incompatible.')
    recognized = [dict(choice_id=key, answer_id=answer, label=definitions[key]['answers'][answer]['label'], evidence=evidence[key])
                  for key, answer in choices.items()]
    supported = SUPPORTED | DAO_SUPPORTED | CARRIED_DAO_SUPPORTED
    unresolved = [dict(choice_id=key, reason=notes.get(key,
                    'The required outcome evidence is missing, conflicting, or has not been reached in this save.'
                    if key in supported else 'This choice does not yet have a confirmed import rule.'),
                    status='needs_review' if key in supported else 'not_mapped')
                  for key in definitions if key not in choices and key not in RETIRED]
    counts = {game: dict(recovered=sum(key.startswith(game + '.') for key in choices),
                        unresolved=sum(e['choice_id'].startswith(game + '.') for e in unresolved))
              for game in ('da2', 'dao')}
    warnings = ['Some DA2 outcomes and carried DAO outcomes still require review. Review unresolved choices before exporting.',
                'Unresolved choices retain the default world state; they were not recovered from this save.',
                'Outcomes reflect the save at the time it was made, including any mods.']
    if corrected_nathaniel:
        warnings.append('Nathaniel’s recovered DAO answer is alive: Hawke’s successful Finding Nathaniel rescue '
                        'overrides the inherited Awakening death flag. Your original save is unchanged.')
    return dict(character=name, suggested_name=suggested_import_name(name, 'DA2'), choices=choices,
                recognized=recognized, unresolved=unresolved, counts=counts,
                save_sha256=hashlib.sha256(payload).hexdigest(),
                stage='Post-campaign' if snapshot.bit(ACT, 5) else 'Act III' if snapshot.bit(ACT, 4) else
                      'Act II' if snapshot.bit(ACT, 2) else 'Act I / prologue',
                warnings=warnings)
