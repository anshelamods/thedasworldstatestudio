"""Companion outcomes from vanilla plot scripts and positive spoken branches.

Sources and limits: assessment/DA2 save import companion outcomes.md.
"""

ACT = '49BEAD07708649F0AC61A9AF4FF03127'
FINALE = '5FDEFF4F87044A6E8E84965764A1C4B2'
MERRILL = '2467D59345A3466CB1881E9C84B8CCF4'
NEW_PATH = '57E9117224024F11AF77017CB6E5697B'
LONG_ROAD = '1D823DCD0ACB48489A54E13773148F31'

ANDERS_APPROVED = frozenset({6127591})  # mcr310_argument.cnv, line 85
ANDERS_DISAPPROVED = frozenset({6075100, 6075110, 6127563})  # lines 35, 43, 64
MIRROR_KEPT = frozenset({6146943})  # gen00fl_merrill.cnv, line 189
MIRROR_DESTROYED = frozenset({6145214})  # same conversation, line 187

SUPPORTED = frozenset('da2.' + name for name in (
    'merrill_eluvian', 'merrill_clan', 'merrill_remained', 'aveline_marriage',
    'aveline_remained', 'anders_approval', 'bethany_final_battle'))


def infer_companions(s, put, notes):
    bit = s.bit
    act3 = bool(bit(ACT, 4) or bit(ACT, 5))
    finished = bool(bit(ACT, 5) or bit(FINALE, 76))
    allegiance = bool(bit(FINALE, 17) and (bit(FINALE, 0) != bit(FINALE, 1)))

    def choose(key, candidates, reason=None):
        found = [(answer, source) for matches, answer, source in candidates if matches]
        if len({answer for answer, _ in found}) == 1:
            put(key, found[0][0], '; '.join(source for _, source in found))
        elif found:
            notes['da2.' + key] = 'The save records conflicting outcomes; no answer was guessed.'
        elif reason:
            notes['da2.' + key] = reason

    # 26 shows the shattered mirror. 27 also fires after the kept-mirror
    # conversation, so hiding the whole scene prop alone is not destruction.
    broken = bool(bit(MERRILL, 26) or bit(NEW_PATH, 4)
                  or s.seen & MIRROR_DESTROYED)
    kept = bool(bit(NEW_PATH, 5) or s.seen & MIRROR_KEPT)
    completed_intact = (finished and s.available('merrill')
                        and bit(MERRILL, 26) is False
                        and bit(NEW_PATH, 4) is False)
    choose('merrill_eluvian', [
        (broken, 'destroyed', 'Merrill main 26 shows the shattered mirror; New Path 4 or explicit post-destruction dialogue corroborates'),
        (kept or completed_intact, 'preserved', 'New Path 5 / explicit kept-mirror dialogue, or completed campaign with available Merrill and all destruction markers explicitly clear'),
    ])

    # 15 starts a fight; 16 is the actual clan-death outcome used in dialogue.
    choose('merrill_clan', [
        (bit(NEW_PATH, 16), 'killed', 'New Path 16 gates Merrill’s explicit whole-clan death dialogue'),
        (bit(NEW_PATH, 14) and bit(NEW_PATH, 16) is False, 'survived', 'New Path 14: Fenarel permits departure with Merrill; clan-death marker clear'),
        (finished and all(bit(NEW_PATH, f) is False for f in (15, 16)), 'survived', 'Campaign finished without starting the clan fight or recording clan deaths'),
    ])

    # Final allegiance branches are persistent. Party availability alone is
    # transient, and the post-campaign pool can contain departed followers.
    if allegiance:
        if bit(FINALE, 14) or bit(FINALE, 55):
            put('merrill_remained', 'left', 'Final allegiance: Merrill refuses Hawke (14) or subsequent hostile removal (55)')
        elif bit(FINALE, 14) is False and bit(FINALE, 55) is False and s.available('merrill'):
            put('merrill_remained', 'stayed', 'Final allegiance dialogue completed (17); available Merrill has neither refusal (14) nor hostile removal (55)')
        if bit(FINALE, 12) or bit(FINALE, 54):
            put('aveline_remained', 'left', 'Final allegiance: Aveline refuses Hawke (12) or subsequent hostile departure (54)')
        elif bit(FINALE, 12) is False and bit(FINALE, 54) is False and s.available('aveline'):
            put('aveline_remained', 'stayed', 'Final allegiance dialogue completed (17); available Aveline has neither refusal (12) nor hostile departure (54)')

    # Long Road 20 is dating during Act II. Act III explicitly calls Donnic
    # her husband under the same condition, so do not import an early wedding.
    if act3:
        choose('aveline_marriage', [
            (bit(LONG_ROAD, 20), 'married', 'Act III reached; Long Road 20 gates Aveline calling Donnic her husband'),
            (bit(LONG_ROAD, 20) is False and any(bit(LONG_ROAD, f) for f in (1, 26)),
             'not_married', 'Act III reached; Long Road explicitly refused (1) or expired (26), with relationship outcome clear'),
        ])

    choose('anders_approval', [
        (bool(s.seen & ANDERS_APPROVED), 'approved', 'Saved spoken mcr310_argument line 85 explicitly calls Anders’s cause noble'),
        (bool(s.seen & ANDERS_DISAPPROVED), 'disapproved', 'Saved spoken mcr310_argument critical responses 35/43/64'),
    ], 'No unambiguous approval or criticism branch is retained. Forgiveness, romance and sparing Anders do not by themselves establish approval of the bombing.')

    early_death = bool(bit(ACT, 11) or bit(ACT, 13))
    final_death = bool(bit(FINALE, 84))
    living = bool(bit(ACT, 7) or bit(ACT, 9) or s.available('bethany'))
    if early_death and living:
        notes['da2.bethany_final_battle'] = 'Bethany has both an earlier death marker and a living career/availability record; her final survival needs review.'
        return
    choose('bethany_final_battle', [
        (early_death, 'before_war', 'Bethany’s explicit Lothering (ACT 11) or Deep Roads death (ACT 13)'),
        (final_death, 'died', 'Meredith’s execution of Bethany sets finale 84'),
        (finished and living and not early_death and bit(FINALE, 84) is False,
         'survived', 'Campaign/final battle completed, living Bethany career or modded availability retained, and execution marker explicitly clear'),
    ], 'Bethany’s final survival needs a completed final battle; an available follower before that point does not predict the outcome.')
    if living and not early_death and 'da2.bethany_final_battle' in notes:
        notes['da2.bethany_final_battle'] += ' Living Bethany defaults to surviving until an actual final outcome is recovered or selected; this is not recovered survival evidence.'
