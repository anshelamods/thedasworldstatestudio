"""Remaining DA2 controls from original scripts, dialogue and active plots.

Missing records are unknown. Shared endings do not guess dialogue choices.
Tallis's completed outcome follows her dungeon route, independently of flirting
and the tone of individual replies about the Qun.
"""

ACT = '49BEAD07708649F0AC61A9AF4FF03127'
FINALE = '5FDEFF4F87044A6E8E84965764A1C4B2'
CROWS = '6F4E853DF7EE4DE3841C31928BF663C3'
GAMLEN = '579EF5C64BDE4D3E933F9F24AB5278E7'
COLD = '66694D5D17A043338F9D7DE569FCA7D5'
EMILE = 'E7D7E1410D764B21BA467306B4676A57'
SUSPECT = '4C70E236B3564CE5AD93C4F0046B4752'
REMAINS = 'A3A9A6C9214E465E9A638E277729261E'
JAVARIS = '2D7ABC9F51FD42BA9453871B55CA147D'
CARGO = '8EACA8B728DB4BE58B540A8D34DD8C11'
DRAGON = '4B8B7E29B095420EB70D030C1685665A'
GOLD = '01B66793B8F44AF791B758D4723D26E7'
CLIFF = 'DBAFF925CAA64D7A9C5C3DA305FC5255'
VARNELL = 'B333CF017E2E45C0923351A3F3F298E9'
PETRICE = '6523FD925E7C410486A274AD5EA57447'
PROLOGUE = 'A8C7F47C7B0D47A0A39A2A3CA2F449CD'
LEGACY = 'E17552763C8A4E91841F85E8AC1ABE3B'
MALCOLM = '36EEF4A5F59C46A2AFA6060EC769C257'
ASSASSIN = 'DC06BC0C0B204213B7C193EF38EC31CB'
TALLIS = '3CDCD7551A474FD5A8E4B6CE7E86CFEC'
DUNGEON = '9F3291612A624123A0351DA4F8CEBF75'

SUPPORTED = frozenset('da2.' + k for k in (
    'legacy_played', 'legacy_side', 'murder_of_crows', 'zevran_freed',
    'gamlen_treasure', 'malcolm_will', 'conspirators', 'emile_fate',
    'keran_fate', 'bone_pit_dragon', 'gascard_fate', 'javaris_fate',
    'hubert_caravans', 'fools_gold', 'cliff_raiders', 'varnell_side',
    'petrice_side', 'tallis_kiss', 'tallis_reaction', 'prologue_allegiance'))

# mag311_keran.cnv: the handover and release both reach #14/#13. Only the
# actual spoken choice distinguishes them. Threatening to kill him (#107)
# still permits changing one's mind and is deliberately not a killed marker.
KERAN_RELEASED = frozenset({6041588, 6041740})  # nodes 95, 106
KERAN_TEMPLARS = frozenset({6041704})  # node 127


def infer_remaining(s, put, notes):
    bit = s.bit
    def any_flag(g, *flags): return any(bit(g, f) is True for f in flags)
    def clear(g, *flags): return all(bit(g, f) is False for f in flags)
    def empty(g): return g in s.plots and not any(s.plots[g])
    def choose(key, candidates, reason=None):
        found = [(a, src) for matches, a, src in candidates if matches]
        answers = {a for a, _ in found}
        if len(answers) == 1:
            put(key, found[0][0], '; '.join(src for _, src in found))
        elif len(answers) > 1:
            notes['da2.' + key] = 'The save records conflicting final outcomes; choose this outcome manually.'
        elif reason:
            notes['da2.' + key] = reason

    # The final allegiance scene closes main-game side quests. Act III closes
    # Act II-only quests. DLC negatives describe the current saved history,
    # not a prediction that the player cannot play post-campaign DLC later.
    closed = bool(bit(ACT, 5) or any_flag(FINALE, 0, 1))
    act3 = bool(any_flag(ACT, 4, 5))
    choose('prologue_allegiance', [
        (bit(PROLOGUE, 69), 'smugglers', f'{PROLOGUE} / 69: Athenril welcomes Hawke aboard'),
        (bit(PROLOGUE, 59), 'mercenaries', f'{PROLOGUE} / 59: Meeran welcomes Hawke to the Red Iron'),
    ])

    offered = any_flag(CROWS, 1, 3, 5, 6, 7, 8, 9, 10, 11, 12)
    choose('murder_of_crows', [
        (offered, 'offered_help', f'{CROWS} / accepted quest 1 or later investigation/resolution'),
        (bit(CROWS, 2), 'not_helped', f'{CROWS} / 2: Nuncio declined'),
    ])
    choose('zevran_freed', [
        (bit(CROWS, 7), 'freed', f'{CROWS} / 7: Zevran released from the cave'),
        (bit(CROWS, 6), 'not_freed', f'{CROWS} / 6: Zevran taken to Nuncio; later Crow battle does not change that choice'),
        ((closed and empty(CROWS)) or (bit(CROWS, 2) and not offered),
         'not_encountered', f'{CROWS} / declined or final explicitly empty quest history'),
        (closed and bit(CROWS, 23) and clear(CROWS, 5, 6, 7), 'not_encountered',
         f'{CROWS} / quest expired 23 without an encounter/disposition'),
    ])
    gamlen_done = bit(GAMLEN, 19)
    choose('gamlen_treasure', [
        (gamlen_done and bit(GAMLEN, 17), 'reunited', f'{GAMLEN} / completed 19 and Charade-reunion route 17'),
        (gamlen_done and bit(GAMLEN, 18), 'returned_gem', f'{GAMLEN} / completed 19 and gem-only route 18'),
        (closed and bit(GAMLEN, 19) is False, 'not_helped', f'{GAMLEN} / final history without completed treasure quest'),
    ])
    choose('conspirators', [
        (bit(COLD, 42), 'orsino', f'{COLD} / 42: conspiracy reported to Orsino'),
        (bit(COLD, 43), 'meredith', f'{COLD} / 43: conspiracy reported to Meredith'),
    ])
    choose('emile_fate', [
        (bit(EMILE, 2), 'freed', f'{EMILE} / 2: Emile explicitly freed'),
        (bit(EMILE, 3), 'circle', f'{EMILE} / 3: Emile returned to the Circle'),
    ])
    choose('keran_fate', [
        (bit(COLD, 15), 'killed', f'{COLD} / 15: execution in mag311_keran.cnv 120'),
        (bool(s.seen & KERAN_RELEASED), 'released', 'Saved spoken release branch: mag311_keran.cnv 95/106'),
        (bool(s.seen & KERAN_TEMPLARS), 'templars', 'Saved spoken handover: mag311_keran.cnv 127'),
    ], 'Keran’s released and handed-over branches share flags 14/13. A distinct saved spoken choice is required; his Act I reinstatement does not decide his Act III fate.')

    # Both encounters occur in Act II. A later kill supersedes earlier mercy.
    gas_dead = any_flag(SUSPECT, 6, 15) or bit(REMAINS, 22)
    hostile_resolved = bit(REMAINS, 6) and (act3 or bit(REMAINS, 29))
    if gas_dead or hostile_resolved:
        put('gascard_fate', 'killed', f'{SUSPECT} / death 6/15; {REMAINS} / execution 22 or hostile 6 after resolved Quentin battle')
    elif bit(REMAINS, 23) or (act3 and clear(SUSPECT, 6, 15) and clear(REMAINS, 6, 22)):
        put('gascard_fate', 'not_killed', f'{REMAINS} / explicitly spared 23 or Act II closed with both encounters’ death markers explicitly clear')
    choose('javaris_fate', [
        (bit(JAVARIS, 16), 'dead', f'{JAVARIS} / 16: Javaris executed'),
        (bit(JAVARIS, 5) and bit(JAVARIS, 16) is False, 'alive', f'{JAVARIS} / departure 5 without execution 16'),
    ])
    discovered = any_flag(CARGO, 11, 12, 13, 40, 41, 42)
    choose('hubert_caravans', [
        (discovered, 'discovered', f'{CARGO} / Brekker identified 11 or later completion 12/13/40–42'),
        ((bit(CARGO, 46) and not discovered) or (act3 and empty(CARGO)),
         'not_discovered', f'{CARGO} / expired 46 without finding the culprit, or empty history after Act II'),
    ])
    choose('bone_pit_dragon', [
        (bit(DRAGON, 26), 'killed', f'{DRAGON} / 26: Hubert thanks Hawke for eliminating the dragons; profile-only choice'),
        (bit(DRAGON, 28), 'not_killed', f'{DRAGON} / 28: high dragon left alone; profile-only choice'),
        (closed and empty(DRAGON), 'not_killed', f'{DRAGON} / final explicitly empty quest; profile-only choice'),
    ])
    gold_end = any_flag(GOLD, 11, 19)
    choose('fools_gold', [
        (gold_end and bit(GOLD, 8) and bit(GOLD, 12) and clear(GOLD, 7, 13),
         'iwan', f'{GOLD} / Iwan route 8, Merin corpse 12, final return 11/19'),
        (gold_end and bit(GOLD, 7) and bit(GOLD, 13) and clear(GOLD, 8, 12),
         'merin', f'{GOLD} / Merin rescued 7, Iwan corpse 13, final return 11/19'),
        (act3 and empty(GOLD), 'not_encountered', f'{GOLD} / explicitly empty quest after Act II'),
    ], 'The Keep has no answer for every failed or unfinished rescue. Quest acceptance, a temporary follower or an unexplained corpse alone is insufficient.')
    cliff_abandoned = bit(CLIFF, 12) or (act3 and bit(CLIFF, 15) and clear(CLIFF, 1, 2, 3))
    choose('cliff_raiders', [
        (cliff_abandoned, 'abandoned', f'{CLIFF} / guards abandoned 12 or explicit refusal 15 after Act II'),
        (bit(CLIFF, 1) and clear(CLIFF, 3, 12), 'alone', f'{CLIFF} / 1: told guards to stay behind; supersedes earlier together proposal 2'),
        (bit(CLIFF, 2) and clear(CLIFF, 1, 3, 12), 'with_guards', f'{CLIFF} / 2: attacked alongside the guards'),
        (act3 and empty(CLIFF), 'not_encountered', f'{CLIFF} / explicitly empty quest after Act II'),
    ], 'Covering a retreat or an unfinished/conflicting guard encounter has no confirmed matching Keep answer.')
    choose('varnell_side', [
        (bit(VARNELL, 11), 'sided', f'{VARNELL} / 11: Qunari turn hostile after Hawke endorses Varnell'),
        (bit(VARNELL, 5) and bit(VARNELL, 6) and bit(VARNELL, 11) is False,
         'not_sided', f'{VARNELL} / opposed-Varnell battle 5 resolved 6 without siding route 11'),
        (act3 and empty(VARNELL), 'not_sided', f'{VARNELL} / no encounter recorded after Act II'),
    ])
    choose('petrice_side', [
        (bit(PETRICE, 14), 'sided', f'{PETRICE} / 14: joins Petrice against the Qunari'),
        (any_flag(PETRICE, 5, 7), 'not_sided', f'{PETRICE} / turns against Petrice 5/7, even after earlier support'),
        (act3 and empty(PETRICE), 'not_sided', f'{PETRICE} / no encounter recorded after Act II'),
    ])

    legacy_started = any_flag(LEGACY, 1, 2, 3, 4, 25, 26, 42)
    legacy_absent = closed and empty(LEGACY)
    choose('legacy_played', [
        (legacy_started, 'played', f'{LEGACY} / actual Legacy exploration or completion, not DLC availability flags'),
        (legacy_absent, 'not_played', f'{LEGACY} / explicitly empty Legacy history at final allegiance/post-campaign'),
    ])
    choose('legacy_side', [
        (bit(LEGACY, 25), 'larius', f'{LEGACY} / 25: Larius survives the final Corypheus resolution; drk000_world_state reads this exact flag'),
        (bit(LEGACY, 42), 'janeka', f'{LEGACY} / 42: Janeka survives the final Corypheus resolution; drk000_world_state reads this exact flag'),
    ], 'The initial ally can be changed near Corypheus. A final Larius/Janeka outcome is required.')
    choose('malcolm_will', [
        (bit(MALCOLM, 2), 'found', f'{MALCOLM} / 2: Malcolm’s Will completed; original Legacy export reads this flag'),
        (bit(MALCOLM, 2) is False and (bit(MALCOLM, 14) or bit(LEGACY, 26) or legacy_absent),
         'not_found', f'{MALCOLM} / completion explicitly clear after expiration/Legacy completion, or Legacy unplayed'),
    ])
    never_tallis = closed and empty(ASSASSIN) and empty(TALLIS) and s.party.get('eye00fl_tallis', (None,))[0] not in (1, 2)
    choose('tallis_kiss', [
        (bit(TALLIS, 5), 'kissed', f'{TALLIS} / 5: final kiss, distinct from flirt flag 0'),
        ((bit(TALLIS, 6) and bit(TALLIS, 5) is False) or never_tallis,
         'not_kissed', f'{TALLIS} / final farewell 6 with kiss clear, or never met'),
    ])
    tallis_done = bit(ASSASSIN, 43) and bit(TALLIS, 6)
    tallis_left = bit(DUNGEON, 11) and bit(DUNGEON, 12)
    # The down-mountain exit sets both 12 and 11. Reward handling can later
    # set joined marker 10 again, so a completed departure takes precedence.
    # Do not infer a route from missing data, generic farewells or Qun replies.
    choose('tallis_reaction', [
        (never_tallis, 'never_met', f'{ASSASSIN} and {TALLIS} / explicitly empty DLC/companion history at final allegiance/post-campaign'),
        (tallis_done and tallis_left, 'angry', f'{DUNGEON} / departure 11/12 retained after MotA completion 43 and Tallis farewell 6'),
        (tallis_done and any_flag(DUNGEON, 10, 13) and clear(DUNGEON, 11, 12),
         'not_angry', f'{DUNGEON} / joined/helped 10/13 with departure 11/12 explicitly clear; MotA completed and Tallis farewell recorded'),
    ], 'Tallis’s reaction needs a completed MotA farewell and a clear joined/left dungeon route. Missing or unfinished route records remain for review; flirting and individual Qun replies do not decide this outcome.')


def reconcile_crows(s, choices, evidence, notes):
    """Distinguish an unavailable Crow quest from simply never helping Nuncio.

    The Keep's not-sought answer requires a dead Zevran. An empty quest alone
    cannot establish that. Only recovered DAO fate is used, never defaults.
    """
    if ('da2.murder_of_crows' in choices or 'da2.murder_of_crows' in notes
            or CROWS not in s.plots or any(s.plots[CROWS])
            or not (s.bit(ACT, 5) or s.bit(FINALE, 0) or s.bit(FINALE, 1))):
        return
    fate = choices.get('dao.zevran_fate')
    if fate in ('alive', 'dead'):
        key = 'da2.murder_of_crows'
        choices[key] = 'not_sought' if fate == 'dead' else 'not_helped'
        evidence[key] = (f'{CROWS} / late, explicitly empty quest; recovered DAO Zevran {fate} '
            'distinguishes unavailable quest from not helping; no inherited default was used')
    else:
        notes['da2.murder_of_crows'] = ('The Crow quest is empty, but Zevran’s imported fate could not be recovered. '
            'An unavailable quest and not helping Nuncio cannot be distinguished from this record alone.')
