"""Direct DAO settlement outcomes; shared dialogue flags stay unresolved."""

SUPPORTED = frozenset('dao.' + k for k in (
    'redcliffe_preparation', 'bevin_fate', 'valena_fate', 'bella_fate',
    'filda_ruck', 'zerlinda_fate', 'mardy_relationship', 'mardy_son',
    'shaperate_tome', 'landry_fate', 'beggar_amulet', 'ignacio_fate'))

FLAGS = {
    'red_agreed': ('EC0948ED98544E25A47CD6790DA71469', 1),
    'red_abandoned': ('EC0948ED98544E25A47CD6790DA71469', 12),
    'red_siege_begins': ('EC0948ED98544E25A47CD6790DA71469', 21),
    'red_siege_over': ('C8BD51CF3BC0414192BFF6BC6BF8247C', 0),
    'red_weapons': ('7F2CA2180878495CA37EB6386C9CF9D5', 2),
    'red_stash_given': ('7F2CA2180878495CA37EB6386C9CF9D5', 6),
    'red_oil': ('7FB508D002574500A36DF27483862719', 0),
    'red_amulets': ('45E3A9D7375044769144EE3422B36A1A', 0),
    'red_dwyn': ('919D9962FBC346BF9054D7798CCEDB80', 2),
    'bevin_found': ('3EE3B5C37C8D4A15B2F62A0AED56AB0F', 6),
    'bevin_key': ('3EE3B5C37C8D4A15B2F62A0AED56AB0F', 10),
    'bevin_sword': ('3EE3B5C37C8D4A15B2F62A0AED56AB0F', 11),
    'bevin_sword_paid_medium': ('3EE3B5C37C8D4A15B2F62A0AED56AB0F', 15),
    'bevin_sword_paid_huge': ('3EE3B5C37C8D4A15B2F62A0AED56AB0F', 16),
    'bevin_huge_money': ('3EE3B5C37C8D4A15B2F62A0AED56AB0F', 17),
    'bevin_med_money': ('3EE3B5C37C8D4A15B2F62A0AED56AB0F', 18),
    'bevin_small_money': ('3EE3B5C37C8D4A15B2F62A0AED56AB0F', 19),
    'bevin_tiny_money': ('3EE3B5C37C8D4A15B2F62A0AED56AB0F', 20),
    'bevin_returned': ('3EE3B5C37C8D4A15B2F62A0AED56AB0F', 24),
    'valena_rescued': ('65518CE61C8C4004970E6A85A9E5127C', 1),
    'valena_left': ('65518CE61C8C4004970E6A85A9E5127C', 5),
    'bella_player_owns': ('C114C254A46B441DA2E87FBC35578B41', 0),
    'bella_in_charge': ('C114C254A46B441DA2E87FBC35578B41', 14),
    'bella_teagan': ('C114C254A46B441DA2E87FBC35578B41', 17),
    'bella_denerim': ('C114C254A46B441DA2E87FBC35578B41', 18),
    'bella_money': ('C114C254A46B441DA2E87FBC35578B41', 19),
    'lloyd_killed': ('C114C254A46B441DA2E87FBC35578B41', 9),
    'lloyd_siege_death': ('C8BD51CF3BC0414192BFF6BC6BF8247C', 10),
    'filda_accepted': ('47DFDD542B48460CBC08E55B9DFA9BBE', 0),
    'filda_said_dead': ('47DFDD542B48460CBC08E55B9DFA9BBE', 1),
    'filda_killed_truth': ('47DFDD542B48460CBC08E55B9DFA9BBE', 2),
    'filda_condition_truth': ('47DFDD542B48460CBC08E55B9DFA9BBE', 4),
    'ruck_killed': ('47DFDD542B48460CBC08E55B9DFA9BBE', 7),
    'ruck_promised_dead_story': ('47DFDD542B48460CBC08E55B9DFA9BBE', 6),
    'filda_not_found': ('47DFDD542B48460CBC08E55B9DFA9BBE', 11),
    'filda_talked': ('78E0CA79AB3A4550ABFA13843AF75A76', 43),
    'zerlinda_deep_roads': ('87AFF6349A0447B485A18D786E58682B', 2),
    'zerlinda_chantry': ('87AFF6349A0447B485A18D786E58682B', 3),
    'zerlinda_family': ('87AFF6349A0447B485A18D786E58682B', 5),
    'zerlinda_surface': ('87AFF6349A0447B485A18D786E58682B', 12),
    'mardy_met_origin': ('53175C027A464CEEB9BCC6F918EAED53', 3),
    'mardy_chosen': ('4D7A6069A935486D879C32F9EABBE770', 3),
    'mardy_both_chosen': ('4D7A6069A935486D879C32F9EABBE770', 4),
    'mardy_son_restored': ('C93EAEA757434D5A893E7D7E2F636F8A', 2),
    'mardy_son_accepted': ('C93EAEA757434D5A893E7D7E2F636F8A', 0),
    'mardy_son_refused': ('C93EAEA757434D5A893E7D7E2F636F8A', 4),
    'mardy_son_bhelen_promise': ('C93EAEA757434D5A893E7D7E2F636F8A', 9),
    'mardy_son_harrowmont_promise': ('C93EAEA757434D5A893E7D7E2F636F8A', 10),
    'mardy_son_final_promise': ('C93EAEA757434D5A893E7D7E2F636F8A', 11),
    'mardy_son_bhelen_agreed': ('C93EAEA757434D5A893E7D7E2F636F8A', 13),
    'mardy_son_harrowmont_agreed': ('C93EAEA757434D5A893E7D7E2F636F8A', 14),
    'tome_returned': ('2C50728792CD464E82C27F3512C8E511', 3),
    'tome_sold': ('2C50728792CD464E82C27F3512C8E511', 4),
    'landry_killed': ('DF5250E8C0A34857B3D96A00C74C798B', 8),
    'landry_peace': ('DF5250E8C0A34857B3D96A00C74C798B', 2),
    'landry_left': ('DF5250E8C0A34857B3D96A00C74C798B', 10),
    'beggar_returned': ('DD064DD1BFE64C7090ABE68292229296', 1),
    'ignacio_killed': ('9AE0BECCF5194FBEA1F70D8BD0B144BA', 17),
    'ignacio_attacked': ('9AE0BECCF5194FBEA1F70D8BD0B144BA', 5),
    'ignacio_done': ('9AE0BECCF5194FBEA1F70D8BD0B144BA', 7),
}


def infer(history):
    choices, evidence, notes = {}, {}, {}

    def flag(n):
        guid, bit = FLAGS[n]
        words = history.plots.get(guid)
        return None if words is None else bool(words[bit // 32] & (1 << (bit % 32)))
    def clear(*names): return all(flag(n) is False for n in names)
    def empty(n):
        words = history.plots.get(FLAGS[n][0])
        return words is not None and not any(words)
    def put(k, a, *sources):
        k = 'dao.' + k
        choices[k] = a
        evidence[k] = 'DAO save active history: ' + '; '.join(
            f'{n} [{FLAGS[n][0]}#{FLAGS[n][1]}]' if n in FLAGS else n for n in sources)
    def note(k, text): notes['dao.' + k] = text

    completed = history.flag(2089) is True
    prep = ('red_weapons', 'red_stash_given', 'red_oil', 'red_amulets', 'red_dwyn')
    if flag('red_abandoned'):
        put('redcliffe_preparation', 'not_helped', 'red_abandoned')
    elif flag('red_abandoned') is False and (any(flag(n) for n in prep)
            or flag('red_agreed') and (flag('red_siege_begins') or flag('red_siege_over'))):
        put('redcliffe_preparation', 'helped', 'Preparation delivered or agreed assistance carried into siege', *prep, 'red_agreed')
    elif completed and clear('red_agreed', *prep):
        put('redcliffe_preparation', 'not_helped', 'Origins completed', 'No accepted/delivered preparation')

    money = ('bevin_huge_money', 'bevin_med_money', 'bevin_small_money', 'bevin_tiny_money')
    if flag('bevin_returned'):
        put('bevin_fate', 'returned_sword', 'bevin_returned')
    elif flag('bevin_returned') is False and any(flag(n) for n in (
            'bevin_sword_paid_medium', 'bevin_sword_paid_huge')):
        # Kaitlyn 34/40 acknowledge a sword purchase. Travel assistance shares
        # money flags 17/18, but skips these sword-specific acknowledgments.
        put('bevin_fate', 'paid_for_sword', 'bevin_sword_paid_medium', 'bevin_sword_paid_huge')
    elif flag('bevin_sword') and clear('bevin_returned',
            'bevin_sword_paid_medium', 'bevin_sword_paid_huge', *money):
        put('bevin_fate', 'took_sword', 'bevin_sword', 'No returned sword or payment')
    elif completed and clear('bevin_found', 'bevin_sword', 'bevin_returned'):
        put('bevin_fate', 'not_helped', 'Origins completed', 'No Bevin rescue/sword outcome')
    else:
        note('bevin_fate', 'Sword promises, the chest key and money given to Kaitlyn do not uniquely establish the final sword outcome; payment flags also cover travel assistance. Review manually.')

    if flag('valena_rescued') or flag('valena_left'):
        put('valena_fate', 'rescued', 'valena_rescued', 'valena_left')
    elif completed and clear('valena_rescued', 'valena_left'):
        put('valena_fate', 'not_rescued', 'Origins completed', 'No completed Valena escape')

    left = flag('bella_teagan') or flag('bella_denerim')
    if flag('red_abandoned') and left:
        note('bella_fate', 'Bella has both departure and abandoned-village evidence; review her outcome.')
    elif flag('bella_teagan') and flag('bella_denerim'):
        note('bella_fate', 'Bella has conflicting Teagan and Denerim destinations.')
    elif flag('bella_denerim') and flag('bella_money') and flag('bella_teagan') is False:
        put('bella_fate', 'brewery', 'bella_denerim', 'bella_money')
    elif flag('bella_teagan') and flag('bella_denerim') is False:
        put('bella_fate', 'left', 'bella_teagan')
    elif flag('red_abandoned') and clear('bella_teagan', 'bella_denerim', 'bella_money'):
        put('bella_fate', 'died', 'red_abandoned', 'No departure')
    elif flag('bella_in_charge') and clear('bella_player_owns', 'bella_teagan', 'bella_denerim') and (
            flag('lloyd_killed') or flag('lloyd_siege_death')):
        put('bella_fate', 'tavern_owner', 'bella_in_charge', 'bella_player_owns', 'Lloyd deceased; no alternate departure')
    else:
        note('bella_fate', 'Running the tavern for Lloyd/the Warden is not ownership, and an unfulfilled departure promise is not a final destination.')

    outcomes = ('filda_said_dead', 'filda_killed_truth', 'filda_condition_truth', 'filda_not_found')
    if sum(flag(n) is True for n in outcomes) > 1:
        note('filda_ruck', 'Filda has conflicting final conversation outcomes.')
    elif flag('filda_killed_truth') and flag('ruck_killed'):
        put('filda_ruck', 'killed_truth', 'filda_killed_truth', 'ruck_killed')
    elif flag('filda_condition_truth') and flag('ruck_killed') is False:
        put('filda_ruck', 'condition_truth', 'filda_condition_truth', 'ruck_killed')
    elif flag('filda_said_dead') and flag('ruck_killed') is False:
        put('filda_ruck', 'said_dead', 'filda_said_dead', 'ruck_killed')
    elif flag('filda_said_dead') and flag('ruck_killed') and flag('ruck_promised_dead_story') is False:
        # Filda 90 (heroic) requires death 7; plain lie 98 requires promise 6.
        # With 6 explicitly clear, only the heroic branch reaches completion 1.
        put('filda_ruck', 'killed_heroic', 'filda_said_dead', 'ruck_killed',
            'ruck_promised_dead_story', 'Heroic dialogue 90; plain death lie 98 unavailable')
    elif flag('filda_not_found') and flag('ruck_killed'):
        put('filda_ruck', 'killed_lied', 'filda_not_found', 'ruck_killed')
    elif completed and flag('filda_talked') is False and empty('filda_accepted'):
        put('filda_ruck', 'not_met', 'Origins completed', 'No Filda encounter/quest records')
    else:
        note('filda_ruck', 'Filda’s shared death-news flag can remain ambiguous if Ruck was spared/promised a death story before being killed. Unfinished/unsupported conversations need review.')

    z = {'zerlinda_deep_roads': 'deep_roads', 'zerlinda_chantry': 'chantry',
         'zerlinda_family': 'reconciled', 'zerlinda_surface': 'surface'}
    found = [n for n in z if flag(n)]
    if len(found) == 1:
        put('zerlinda_fate', z[found[0]], found[0])
    elif len(found) > 1:
        note('zerlinda_fate', 'Zerlinda has conflicting final destinations.')
    elif completed and clear(*z):
        put('zerlinda_fate', 'dust_town', 'Origins completed', 'No final departure/reconciliation')

    relations = flag('mardy_chosen') or flag('mardy_both_chosen')
    no_relations = clear('mardy_chosen', 'mardy_both_chosen')
    if completed and relations:
        # The original son's computed eligibility #267 uses these same flags.
        put('mardy_relationship', 'had_relations', 'Origins completed', 'mardy_chosen', 'mardy_both_chosen')
    elif completed and no_relations:
        if flag('mardy_met_origin'): put('mardy_relationship', 'no_relations', 'mardy_met_origin', 'No Mardy sex choice')
        elif flag('mardy_met_origin') is False and empty('mardy_chosen'):
            put('mardy_relationship', 'not_met', 'Origins completed', 'No origin meeting/relationship')
    if flag('mardy_son_restored'):
        put('mardy_son', 'restored', 'mardy_son_restored')
    elif completed and no_relations and clear(*(n for n in FLAGS if n.startswith('mardy_son_'))):
        # Generic failed-quest and donation flags do not establish fatherhood.
        put('mardy_son', 'no_son', 'Origins completed', 'No Mardy sex choice or specific child/restoration evidence')
    elif completed and relations and flag('mardy_son_restored') is False:
        if empty('mardy_son_restored'):
            put('mardy_son', 'not_encountered', 'Origins completed', 'Mardy child eligibility; child quest empty')
        elif any(flag(n) for n in FLAGS if n.startswith('mardy_son_')):
            put('mardy_son', 'not_restored', 'Origins completed', 'Specific child encounter without restoration')
        else:
            note('mardy_son', 'Generic child-quest failure or an introductory response does not establish meeting the son; review encounter and birthright manually.')

    if flag('tome_returned') and flag('tome_sold'):
        note('shaperate_tome', 'The stolen tome is recorded both returned and sold.')
    elif flag('tome_returned') and flag('tome_sold') is False: put('shaperate_tome', 'returned', 'tome_returned')
    elif flag('tome_sold') and flag('tome_returned') is False: put('shaperate_tome', 'sold', 'tome_sold')
    elif completed and clear('tome_returned', 'tome_sold') and empty('tome_returned'):
        put('shaperate_tome', 'not_investigated', 'Origins completed', 'Tome quest not recorded')

    if flag('landry_killed'): put('landry_fate', 'killed', 'landry_killed')
    elif flag('landry_killed') is False and (flag('landry_peace') or flag('landry_left') or completed):
        put('landry_fate', 'alive', 'landry_killed', 'Peaceful resolution/departure or completed Origins')
    if flag('beggar_returned'): put('beggar_amulet', 'returned', 'beggar_returned')
    elif completed and flag('beggar_returned') is False:
        put('beggar_amulet', 'not_returned', 'Origins completed', 'beggar_returned')
    if flag('ignacio_killed') and flag('ignacio_done'):
        note('ignacio_fate', 'Ignacio is recorded both killed and all quests completed.')
    elif flag('ignacio_killed'): put('ignacio_fate', 'killed', 'ignacio_killed')
    elif flag('ignacio_done') and flag('ignacio_killed') is False:
        put('ignacio_fate', 'completed', 'ignacio_done')
    elif completed and clear('ignacio_killed', 'ignacio_done', 'ignacio_attacked'):
        put('ignacio_fate', 'not_completed', 'Origins completed', 'No completed Crows chain/death')
    return choices, evidence, notes
