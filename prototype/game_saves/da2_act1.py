"""Act I outcomes from vanilla PLO/NCS/CNV and positive saved dialogue evidence.

Research provenance: assessment/output/save-import-survey/batch2 and
assessment/DA2 save import batch 2.md. Unset objectives are not negative answers.
"""

WAYWARD = 'FA936F2069D747E28EC0777AEE653893'
MERCY = '307D3D65906448C5BAD9059B13C6D3DE'
ENEMIES = 'C9A765ECB10B4405BBB32F0DB2B95F16'
SAEMUS = 'E717D8BA4554486C9E9604988A64F72C'
GHYSLAIN = 'AFA5F4DE32A04BFEAE8AC1E282085042'
THRASK = '1AF3A8CCAA954EBFAE607B611080716E'
KETOJAN = '499CFA8AA97D49E28B7833C52525610B'
MARTIN = 'E8991262E9304DEDAFF763B6D42B83D2'
KELDER = 'E0AB3D0762DE4E26B515838D8E72028E'
MINERS = '2BA51902E8F143A58412395C89C22E98'
TOMES = '6EA8964E2EB24C8B9731F67C68BC69DC'
FEYNRIEL_LETTER = 'D38183F074DC4C70BC2CB94538477E9E'
SUPPORTED = frozenset('da2.' + key for key in (
    'feynriel_destination', 'danzig_fate', 'idunna_fate', 'saemus_rescue', 'ginnis_fate',
    'ghyslain_truth', 'thrask_blackmail', 'ketojan_fate', 'martin_cargo', 'kelder_fate',
    'bone_pit_miners', 'keran_templars', 'act1_templars', 'karras_fate'))


def infer_act1(s, put, notes):
    bit = s.bit
    def any_flag(guid, *flags):
        return any(bit(guid, flag) is True for flag in flags)

    def choose(key, candidates, reason=None):
        found = [(answer, evidence) for matches, answer, evidence in candidates if matches]
        answers = {answer for answer, _ in found}
        if len(answers) == 1:
            put(key, found[0][0], '; '.join(evidence for _, evidence in found))
        elif len(answers) > 1:
            notes['da2.' + key] = 'The save records conflicting outcomes; choose this outcome manually.'
        elif reason:
            notes['da2.' + key] = reason

    choose('feynriel_destination', [
        (bit(WAYWARD, 3), 'circle', 'Wayward Son 3: Feynriel sent to the Circle'),
        (bit(WAYWARD, 4), 'dalish', 'Wayward Son 4: Feynriel sent to the Dalish'),
        (bit(FEYNRIEL_LETTER, 0), 'dalish', 'Later Feynriel letter explicitly describes living with the Dalish'),
        (bit(FEYNRIEL_LETTER, 1), 'circle', 'Later Feynriel letter explicitly describes living in the Circle'),
    ])
    # 29 merely starts the fight. 51 executes the kill; 40 is the subsequent
    # search-the-slavers'-bodies objective. 30 is the explicit spared exit.
    choose('danzig_fate', [
        (any_flag(WAYWARD, 51, 40), 'killed', 'Wayward Son 51 execution / 40 corpse-search aftermath'),
        (bit(WAYWARD, 30), 'not_killed', 'mag130_danzig.cnv spared branch ends at Wayward Son 30'),
    ])
    choose('idunna_fate', [
        (bit(ENEMIES, 7) or bool(s.seen & {6084245, 6084875}), 'killed',
         'Enemies Among Us 7 or saved spoken execution branch from mag121_idunna.cnv (140/147)'),
        (bit(ENEMIES, 34), 'alive', 'Enemies Among Us 34 records Idunna arrested alive'),
        (bit(TOMES, 12), 'alive', 'Forbidden Knowledge letter: Idunna explicitly thanks Hawke for sparing her'),
        (6084881 in s.seen, 'alive', 'Saved spoken arrest branch from mag121_idunna.cnv (151)'),
    ])
    choose('saemus_rescue', [
        (bit(SAEMUS, 0), 'returned', 'Saemus rescue 0: returned to the viscount unharmed'),
        (any_flag(SAEMUS, 6, 8, 26), 'not_returned', 'Saemus rescue 6/8/26: left to the Winters/other mercenaries'),
    ])
    # In the vanilla rescue, the defense/wave aftermath follows Ginnis's
    # mandatory fight. A mere fight-start (9) is deliberately insufficient.
    choose('ginnis_fate', [
        (any_flag(SAEMUS, 0, 4, 7, 17), 'dead', 'Ginnis fight finished before the Saemus defense/rescue aftermath'),
        (any_flag(SAEMUS, 6, 8, 26) and bit(SAEMUS, 9) is False and bit(SAEMUS, 4) is False,
         'alive', 'Rescue declined without starting Ginnis’s fight'),
    ])
    choose('ghyslain_truth', [
        (bool(s.seen & {6104804, 6120630}), 'told', 'Saved spoken lines from ser120_ghyslain.cnv truth branch (20/27)'),
        (bool(s.seen & {6104821, 6104832}), 'concealed', 'Saved spoken lines from ser120_ghyslain.cnv concealed branch (29/34)'),
        (bit(GHYSLAIN, 17) and all(bit(GHYSLAIN, flag) is False for flag in (1, 2, 3, 4, 7)),
         'not_sought', 'Quest expired without any recorded investigation or completion'),
    ], 'The two completed Ghyslain branches share plot flag 7; their saved dialogue lines are needed to distinguish them.')
    choose('thrask_blackmail', [
        (bit(THRASK, 1) or bit(WAYWARD, 38), 'blackmailed', 'Thrask letter 1 / Wayward Son 38 blackmail response'),
        (bit(THRASK, 2) or bit(WAYWARD, 37), 'not_blackmailed', 'Thrask letter 2 / Wayward Son 37 explicitly keeps the secret'),
    ])
    # Combat 18 also occurs AFTER handing him over. It must not override 17.
    choose('ketojan_fate', [
        (bit(KETOJAN, 17), 'handed_over', 'qun131_taskmaster.cnv voluntary handover branch sets 17'),
        (bit(KETOJAN, 21) or (bit(KETOJAN, 17) is False and bit(KETOJAN, 18)),
         'defended', 'Ketojan’s gift after defense (21), or refused handover before the Arvaarad battle (18)'),
    ])
    choose('martin_cargo', [
        (bit(MARTIN, 1), 'returned', 'Finders Keepers 1: Martin has his cargo back'),
        (any_flag(MARTIN, 9, 24), 'not_returned', 'Finders Keepers 9/24: no help / cargo lost'),
    ])
    # Death is terminal; a prior escort objective can survive in the save.
    if any_flag(KELDER, 4, 6):
        put('kelder_fate', 'killed', 'Magistrate’s Orders 4 executes Kelder; 6 records his father’s revenge for his death')
    elif any_flag(KELDER, 5, 7, 11, 14):
        put('kelder_fate', 'not_killed', 'Magistrate’s Orders escort/reward/refused-reward outcome without a later death')
    choose('bone_pit_miners', [
        (any_flag(MINERS, 7, 8, 9, 10), 'solved', 'Missing Miners clearing aftermath / payment / partnership (7–10)'),
        (bit(MINERS, 11), 'not_solved', 'Missing Miners 11: Hubert left to find his own miners'),
    ])
    choose('keran_templars', [
        (bit(ENEMIES, 15), 'reinstated', 'Enemies Among Us 15: Keran reinstated'),
        (bit(ENEMIES, 16), 'expelled', 'Enemies Among Us 16: Keran expelled'),
    ])
    fought = bit(MERCY, 14) and any_flag(MERCY, 18, 25)
    persuaded = bit(MERCY, 13) and bit(MERCY, 19) and bit(MERCY, 14) is False
    choose('act1_templars', [
        (fought, 'fought', 'Act of Mercy hostile battle (14) followed by escape/departure aftermath (18/25)'),
        (persuaded, 'persuaded', 'Act of Mercy free-mages (13) and peaceful exit (19), without hostile battle'),
        (bit(MERCY, 15), 'mages_handed_over', 'Act of Mercy 15 explicitly records Karras taking the mages to the Circle'),
    ])
    choose('karras_fate', [
        (fought, 'killed', 'Act of Mercy hostile Karras battle completed before escape/departure aftermath'),
        (persuaded or bit(MERCY, 15), 'not_killed', 'Act of Mercy peaceful exit or mages handed to Karras'),
    ])
