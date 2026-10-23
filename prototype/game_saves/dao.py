"""Read-only PC Origins importer, using active DAO plots rather than a vault.

The reviewed worldvault.gda direct definitions supply the DAO plot GUID/bit
mapping. Only the three needed derived booleans are implemented explicitly;
no GDA expression, defaults or uploaded code is executed.
"""
import hashlib
import math
import re
import unicodedata

from . import suggested_import_name
from .gff import SaveReader, SaveFormatError, Node, ListView
from .worldvault import DaoHistory, infer_dao, SUPPORTED
from .dao_companions import infer as infer_companions, SUPPORTED as COMPANIONS_SUPPORTED
from .dao_quests import infer as infer_quests, SUPPORTED as QUESTS_SUPPORTED
from .dao_sidequests import infer as infer_sidequests, SUPPORTED as SIDEQUESTS_SUPPORTED
from .dao_nathaniel import reconcile as reconcile_nathaniel
from .dao_settlements import infer as infer_settlements, SUPPORTED as SETTLEMENTS_SUPPORTED
from .dao_finalquests import infer as infer_finalquests, SUPPORTED as FINALQUESTS_SUPPORTED
from .dao_landsmeet import infer as infer_landsmeet

ALL_SUPPORTED = SUPPORTED | COMPANIONS_SUPPORTED | QUESTS_SUPPORTED | SIDEQUESTS_SUPPORTED | SETTLEMENTS_SUPPORTED | FINALQUESTS_SUPPORTED


def _rows(value, limit, name):
    if not isinstance(value, (ListView, tuple, list)) or len(value) > limit:
        raise SaveFormatError('Invalid or oversized DAO ' + name + ' table.')
    return value


class DaoSaveHistory(DaoHistory):
    source_label = 'DAO save active history'

    def __init__(self, reader):
        self.reader = reader
        self.booleans, self.integers, self.plots = {}, {}, {}
        for row in _rows(reader.get((16003, 16400, 16401)), 20000, 'active plot'):
            if not isinstance(row, Node):
                raise SaveFormatError('Invalid DAO plot record.')
            guid = row.get(16402)
            if not isinstance(guid, str) or not re.fullmatch('[0-9a-fA-F]{32}', guid):
                continue  # Named mod plots cannot match reviewed vanilla GUIDs.
            guid = guid.upper()
            words = tuple(row.get(i) for i in range(16403, 16407))
            if guid in self.plots or any(type(w) is not int or not -2**31 <= w < 2**32 for w in words):
                raise SaveFormatError('Duplicate or invalid DAO plot record.')
            self.plots[guid] = tuple(w & 0xffffffff for w in words)
        if not self.plots:
            raise SaveFormatError('No supported active DAO plot data was found.')
        for key, path in ((1000, (16002, 16208, 16320, 16322)), (1001, (16002, 16208, 16460))):
            value = reader.get(path)
            if type(value) is int:
                self.integers[key] = value
        classes = [row.get(16300) for row in _rows(reader.get((16002, 16208, 16209, 16350), ()), 512, 'player property')
                   if isinstance(row, Node) and row.get(16353) == 27]
        if len(classes) == 1 and type(classes[0]) in (int, float) and math.isfinite(classes[0]) and classes[0] == int(classes[0]):
            self.integers[1045] = int(classes[0])
        elif classes:
            self.integers[1045] = -1  # Explicit malformed/custom class is not a missing mage class.

    def flag(self, key):
        inputs = {2089: (2028, 2029, 2030), 2091: (2063, 2096),
                  2104: (2034, 2035, 2036, 2100, 2101, 2102)}
        if key in inputs:
            values = [super(DaoSaveHistory, self).flag(k) for k in inputs[key]]
            return True if any(v is True for v in values) else False if all(v is False for v in values) else None
        return super().flag(key)


def import_save(payload, catalog):
    reader = SaveReader(payload, game='dao')
    history = DaoSaveHistory(reader)
    choices, evidence, notes = infer_dao(history)
    for adapter in (infer_companions, infer_quests, infer_sidequests, infer_settlements, infer_finalquests):
        recovered, sources, reasons = adapter(history)
        choices.update(recovered)
        evidence.update(sources)
        notes.update(reasons)
    recovered, sources, reasons = infer_landsmeet(history)
    # Direct execution actors resolve the generic vault ambiguity. Explicit
    # conflicting actors must not retain an earlier inferred survival answer.
    for key in reasons:
        choices.pop(key, None)
        evidence.pop(key, None)
    for key in recovered:
        notes.pop(key, None)
    choices.update(recovered)
    evidence.update(sources)
    notes.update(reasons)
    reconcile_nathaniel(history, choices, evidence, notes)
    name = reader.get((16002, 16208, 16255))
    name = ''.join(c for c in name if not unicodedata.category(c).startswith('C')).strip()[:80] if isinstance(name, str) else ''
    name = name or 'The Warden'
    if 1045 in history.integers and history.integers[1045] not in (1, 2, 3):
        notes['dao.warden_class'] = 'The save has a custom, conflicting or unsupported class value; choose the Warden’s class manually.'
    definitions = catalog.choices
    for key, answer in choices.items():
        if not key.startswith('dao.') or key not in definitions or answer not in definitions[key]['answers']:
            raise SaveFormatError('The DAO importer and mapping catalog are incompatible.')
    recognized = [dict(choice_id=key, answer_id=answer, label=definitions[key]['answers'][answer]['label'], evidence=evidence[key])
                  for key, answer in choices.items()]
    retired = {'dao.warden_origin', 'dao.ferelden_leadership'}
    unresolved = [dict(choice_id=key, reason=notes.get(key,
                    'The required outcome evidence is missing, conflicting, or has not been reached in this save.'
                    if key in ALL_SUPPORTED else 'This choice does not yet have a confirmed import rule.'),
                    status='needs_review' if key in ALL_SUPPORTED else 'not_mapped')
                  for key in definitions if key.startswith('dao.') and key not in choices and key not in retired]
    stage = 'Origins completed' if history.flag(2089) else 'Origins in progress'
    warnings = ['Some DAO outcomes may still require review. Review unrecovered choices before exporting.',
                'Missing outcomes do not become selections; they retain the destination history’s inherited values.']
    if 'corrected Awakening siege/codex bug' in evidence.get('dao.nathaniel_fate', ''):
        warnings.append('Nathaniel was imported alive using the original survival epilogue: he was left at the Keep, '
                        'Amaranthine was saved, and its granite walls were funded. This corrects Awakening’s '
                        'automatic siege-death marker; your original save is unchanged.')
    return dict(game='dao', character=name, suggested_name=suggested_import_name(name, 'DAO'),
                choices=choices, recognized=recognized, unresolved=unresolved,
                counts={'dao': dict(recovered=len(choices), unresolved=len(unresolved)),
                        'da2': dict(recovered=0, unresolved=0)},
                save_sha256=hashlib.sha256(payload).hexdigest(), stage=stage,
                warnings=warnings)
