"""Additional DAO outcomes from plot records copied into DA2 saves.

Missing records stay missing. Saved world-vault scalars override overlapping
copied bits. Hawke's plots/identity/dialogue and DAO siege-bug repair are not
used here; DA2's existing Nathaniel rescue reconciliation runs afterward.
"""
from .worldvault import DaoHistory, DIRECT
from . import dao_companions, dao_quests, dao_sidequests, dao_settlements, dao_finalquests, dao_landsmeet

ADAPTERS = (dao_companions, dao_quests, dao_sidequests, dao_settlements, dao_finalquests)
SUPPORTED = frozenset().union(*(module.SUPPORTED for module in ADAPTERS), {'dao.loghain_fate'})


class CarriedPlots(DaoHistory):
    def __init__(self, original):
        self.booleans = dict(original.booleans)
        self.integers = dict(original.integers)
        self.plots = dict(original.plots)
        for key, (guid, bit) in DIRECT.items():
            if key not in self.booleans or guid not in self.plots:
                continue
            words = list(self.plots[guid])
            mask = 1 << (bit % 32)
            words[bit // 32] = words[bit // 32] | mask if self.booleans[key] else words[bit // 32] & ~mask
            self.plots[guid] = tuple(words)

    def flag(self, key):
        if key in self.booleans:
            return super().flag(key)
        inputs = {2089: (2028, 2029, 2030), 2091: (2063, 2096),
                  2104: (2034, 2035, 2036, 2100, 2101, 2102)}
        if key in inputs:
            values = [super(CarriedPlots, self).flag(k) for k in inputs[key]]
            return True if any(v is True for v in values) else False if all(v is False for v in values) else None
        return super().flag(key)


def infer(history):
    copied = CarriedPlots(history)
    choices, evidence, notes = {}, {}, {}
    for module in (*ADAPTERS, dao_landsmeet):
        recovered, sources, reasons = module.infer(copied)
        for key in reasons:
            choices.pop(key, None)
            evidence.pop(key, None)
        for key in recovered:
            notes.pop(key, None)
        choices.update(recovered)
        evidence.update({key: source.replace('DAO save active history:',
            'DAO plot history copied into DA2 (saved world-vault values take precedence):', 1)
            for key, source in sources.items()})
        notes.update(reasons)
    return choices, evidence, notes
