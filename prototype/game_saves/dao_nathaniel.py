"""Correct the original Amaranthine siege/codex bug using epilogue conditions.

Only direct DAO active plots are reconciled. DA2 vault scalars are untouched.
Computed epilogue IDs 257/264 are expressions, never stored save bits.
"""

FLAGS = {
    'siege_death': ('F29B4323C13049BABE1D2E3007C6AD1D', 12),
    'executed': ('F29B4323C13049BABE1D2E3007C6AD1D', 1),
    'killed_after_return': ('F29B4323C13049BABE1D2E3007C6AD1D', 6),
    'left_crisis': ('F29B4323C13049BABE1D2E3007C6AD1D', 13),
    'hanged': ('5BEE8FEFF2AC44788A13AD590C96E67A', 5),
    'killed_by_player': ('5BEE8FEFF2AC44788A13AD590C96E67A', 12),
    'left_for_good': ('5BEE8FEFF2AC44788A13AD590C96E67A', 0),
    'left_after_release': ('5BEE8FEFF2AC44788A13AD590C96E67A', 11),
    'amaranthine_party': ('5BEE8FEFF2AC44788A13AD590C96E67A', 10),
    'joining_complete': ('5BEE8FEFF2AC44788A13AD590C96E67A', 27),
    'amaranthine_saved': ('1C7395DEAAC14F889A5D41F86854F48B', 7),
    'granite_complete': ('542D51BDE496410FAE275169B06ABF3E', 4),
    'granite_without_men': ('542D51BDE496410FAE275169B06ABF3E', 6),
    'walls_funded': ('2C681ED0363B40769313A929A9B32C65', 1),
}


def reconcile(history, choices, evidence, notes):
    def flag(name):
        guid, bit = FLAGS[name]
        words = history.plots.get(guid)
        return None if words is None else bool(words[bit // 32] & (1 << (bit % 32)))

    if not (flag('siege_death') is True and flag('amaranthine_saved') is True
            and flag('amaranthine_party') is False and history.flag(2065) is True
            and flag('joining_complete') is True):
        return
    terminal = ('executed', 'killed_after_return', 'left_crisis', 'hanged',
                'killed_by_player', 'left_for_good', 'left_after_release')
    if not all(flag(n) is False for n in terminal): return
    granite_bits = (flag('granite_complete'), flag('granite_without_men'))
    granite = True if True in granite_bits else False if all(v is False for v in granite_bits) else None
    # Exact original Voldrik #257 and Nathaniel-defined #264 expressions.
    funded = flag('walls_funded')
    strong_keep = False if granite is False or funded is False else True if granite is True and funded is True else None
    if strong_keep:
        key = 'dao.nathaniel_fate'
        choices[key] = 'alive'
        evidence[key] = ('DAO save active history: corrected Awakening siege/codex bug; '
            'recruited and joined Nathaniel left at the Keep; Amaranthine saved; '
            'funded granite walls satisfy the original Nathaniel survival epilogue; '
            'no separate execution, player-kill or permanent-departure markers. ' + '; '.join(
                f'{n} [{FLAGS[n][0]}#{FLAGS[n][1]}]' for n in
                ('siege_death', 'amaranthine_party', 'amaranthine_saved',
                 'granite_complete', 'granite_without_men', 'walls_funded')))
        notes.pop(key, None)
    elif strong_keep is None:
        key = 'dao.nathaniel_fate'
        choices.pop(key, None)
        evidence.pop(key, None)
        notes[key] = ('Nathaniel has Awakening’s bug-prone siege-death marker after being left at the Keep, '
                      'but the wall-upgrade evidence needed to distinguish survival is missing. Review his fate manually.')
