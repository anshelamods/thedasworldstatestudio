"""Later successful rescue can outweigh stale inherited Awakening death."""
PLOT = '478CEED95AD54937ACD9594206E57642'
SUCCESS = 6
ABANDONED = (15, 21)
SUPPORTED = frozenset({'da2.finding_nathaniel'})


def reconcile(snapshot, choices, evidence, notes):
    key = 'da2.finding_nathaniel'
    bit = lambda n: snapshot.bit(PLOT, n)
    if bit(SUCCESS) and any(bit(n) for n in ABANDONED):
        notes[key] = 'Finding Nathaniel records both a successful rescue and abandonment; no outcome or inherited-survival correction was guessed.'
        return False
    if bit(SUCCESS) and all(bit(n) is False for n in ABANDONED):
        choices[key] = 'rescued'
        evidence[key] = f'DA2 active history: {PLOT}#6; Nathaniel’s successful escape/reward conversation completed, without abandonment.'
        corrected = choices.get('dao.nathaniel_fate') == 'dead'
        choices['dao.nathaniel_fate'] = 'alive'
        evidence['dao.nathaniel_fate'] = (f'DA2 successful Finding Nathaniel rescue [{PLOT}#6] proves later survival; '
            'overrides stale inherited Awakening death.' if corrected else
            f'DA2 successful Finding Nathaniel rescue [{PLOT}#6] proves Nathaniel survived Awakening.')
        notes.pop('dao.nathaniel_fate', None)
        return corrected
    words = snapshot.plots.get(PLOT)
    if words is not None and not any(words) and snapshot.bit('49BEAD07708649F0AC61A9AF4FF03127', 5):
        fate = choices.get('dao.nathaniel_fate')
        if fate in ('alive', 'dead'):
            choices[key] = 'not_encountered' if fate == 'alive' else 'not_survived'
            evidence[key] = 'Post-campaign DA2; explicitly empty Nathaniel quest plot and recovered Awakening survival/death.'
    elif any(bit(n) for n in ABANDONED):
        notes[key] = 'Nathaniel was found but left behind; that is not the tapestry’s “did not encounter” or “died in Awakening” answer. Review manually.'
    return False
