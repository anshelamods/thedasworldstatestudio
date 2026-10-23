"""Original DAO execution actors, including records copied into DA2's vault."""

PLOT = '841A4E6E0CDD43D3BA3BA484D9A2771F'


def infer(history):
    words = history.plots.get(PLOT)
    if words is None:
        return {}, {}, {}

    def bit(n): return bool(words[n // 32] & (1 << (n % 32)))

    key = 'dao.loghain_fate'
    warden, alistair, duel = bit(20), bit(22), bit(24)
    if not (warden or alistair):
        return {}, {}, {}  # A suggestion or duel start is not an execution.
    if warden == alistair or not bit(6) or bit(8) or history.flag(2029) is True:
        return {}, {}, {key: 'Loghain has conflicting or unfinished execution/survival records; review manually.'}
    answer = 'executed_by_warden' if warden else 'killed_in_duel' if duel else 'executed_by_alistair'
    source = (f'DAO save active history: {PLOT} / execution 20={int(warden)}, '
              f'22={int(alistair)}, Alistair duel 24={int(duel)}; death 6, survival 8 clear')
    return {key: answer}, {key: source}, {}
