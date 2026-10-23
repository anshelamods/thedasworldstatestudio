"""Twelve direct DAO controls from reviewed original plots/dialogue/scripts.

Shared or absent flags do not become guessed answers. Callers supply active
DAO records or copied DAO records retained in DA2; missing records stay unknown.
"""

SUPPORTED = frozenset('dao.' + name for name in (
    'alistair_family', 'leliana_past', 'oghren_recruited', 'oghren_felsi',
    'flemeth_grimoire', 'ostagar_deserter', 'ostagar_mabari', 'irving_fate',
    'cullen_request', 'urn_poisoned', 'dagna_outcome', 'dagna_permission'))

FLAGS = {
    'goldanna_calmed': ('C2935B1B9E60470EAAEF083B012839AE', 2),
    'goldanna_hardened': ('C2935B1B9E60470EAAEF083B012839AE', 3),
    'goldanna_money': ('C2935B1B9E60470EAAEF083B012839AE', 11),
    'goldanna_house_left': ('C2935B1B9E60470EAAEF083B012839AE', 12),
    'goldanna_wanted': ('C2935B1B9E60470EAAEF083B012839AE', 16),
    'marjolaine_confronted': ('919B6591AA754F5E8B871766F25A68AB', 9),
    'marjolaine_killed': ('919B6591AA754F5E8B871766F25A68AB', 10),
    'marjolaine_spared': ('919B6591AA754F5E8B871766F25A68AB', 31),
    'oghren_recruited': ('25BC6F5E8DA847938245071233433332', 6),
    'oghren_killed': ('530C45E15B4548A5A41DEC739E1F2B2D', 5),
    'oghren_left': ('530C45E15B4548A5A41DEC739E1F2B2D', 6),
    'felsi_reunited': ('530C45E15B4548A5A41DEC739E1F2B2D', 1),
    'felsi_parted': ('530C45E15B4548A5A41DEC739E1F2B2D', 3),
    'felsi_met_oghren': ('530C45E15B4548A5A41DEC739E1F2B2D', 43),
    'felsi_failed': ('530C45E15B4548A5A41DEC739E1F2B2D', 44),
    # The Keep asks about Awakening's child/family quest. The Origins tavern
    # markers above describe a different event and cannot establish this answer.
    'awakening_felsi_visited': ('D4920BFFC3E24C2FAC5A513AFD87C6DE', 2),
    'awakening_felsi_encouraged': ('D4920BFFC3E24C2FAC5A513AFD87C6DE', 3),
    'awakening_felsi_resolution': ('6F08DC1CF4984FF699D7DC3CAD18B753', 6),
    'awakening_felsi_refused': ('6F08DC1CF4984FF699D7DC3CAD18B753', 11),
    'real_grimoire_given': ('70EF42CA62564177AA810FCD09C7AFD4', 1),
    'flemeth_quest_active': ('70EF42CA62564177AA810FCD09C7AFD4', 6),
    'flemeth_quest_complete': ('70EF42CA62564177AA810FCD09C7AFD4', 7),
    'real_grimoire_kept': ('70EF42CA62564177AA810FCD09C7AFD4', 12),
    'flemeth_spared': ('70EF42CA62564177AA810FCD09C7AFD4', 13),
    'flemeth_fight_started': ('70EF42CA62564177AA810FCD09C7AFD4', 18),
    'flemeth_slain': ('B8CF1381BB064193B358B808465729A9', 1),
    'prisoner_killed': ('F0CCF894E7F844A99BDF263D6DBB618A', 1),
    'prisoner_key_given': ('F0CCF894E7F844A99BDF263D6DBB618A', 5),
    'prisoner_guard_bribed': ('F0CCF894E7F844A99BDF263D6DBB618A', 6),
    'prisoner_food_obtained': ('F0CCF894E7F844A99BDF263D6DBB618A', 7),
    'prisoner_key_used': ('F0CCF894E7F844A99BDF263D6DBB618A', 11),
    'prisoner_fed': ('F0CCF894E7F844A99BDF263D6DBB618A', 13),
    'mabari_healed': ('208DD668D74C413994BD638732767B64', 4),
    'mabari_killed': ('208DD668D74C413994BD638732767B64', 5),
    'mabari_flower_without_quest': ('208DD668D74C413994BD638732767B64', 9),
    'circle_complete': ('C232DA078A044178AA9FCBC6E537FA75', 2),
    'circle_all_mages_dead': ('C232DA078A044178AA9FCBC6E537FA75', 12),
    'irving_alive': ('AE2F51ECCFCB46C0B145514455F6E0BB', 3),
    'irving_dead': ('AE2F51ECCFCB46C0B145514455F6E0BB', 4),
    'cullen_agreed': ('D078FB75A99A42248F4DA65F70076922', 14),
    'urn_complete': ('8B254175421D48E1B47FC915E8750228', 4),
    'urn_poisoned': ('7FD7A773C53142FABAB1BEDED0BED56A', 1),
    'dagna_accepted': ('3324ED085FC640308F8753382634149E', 0),
    'dagna_complete': ('3324ED085FC640308F8753382634149E', 2),
    'dagna_left': ('3324ED085FC640308F8753382634149E', 3),
    'dagna_refused': ('3324ED085FC640308F8753382634149E', 6),
    'dagna_irving_accepted': ('3324ED085FC640308F8753382634149E', 7),
    'dagna_failed': ('3324ED085FC640308F8753382634149E', 11),
    'dagna_greagoir_refused': ('3324ED085FC640308F8753382634149E', 14),
    'dagna_talked': ('78E0CA79AB3A4550ABFA13843AF75A76', 7),
}


def infer(history):
    choices, evidence, notes = {}, {}, {}

    def flag(name):
        guid, bit = FLAGS[name]
        words = history.plots.get(guid)
        return None if words is None else bool(words[bit // 32] & (1 << (bit % 32)))

    def clear(*names): return all(flag(n) is False for n in names)

    def put(name, answer, *sources):
        key = 'dao.' + name
        choices[key] = answer
        evidence[key] = 'DAO save active history: ' + '; '.join(
            f'{s} [{FLAGS[s][0]}#{FLAGS[s][1]}]' if s in FLAGS else s for s in sources)

    def note(name, text): notes['dao.' + name] = text

    completed = history.flag(2089) is True
    family = ('goldanna_calmed', 'goldanna_hardened', 'goldanna_money', 'goldanna_house_left')
    if any(flag(n) for n in family):
        put('alistair_family', 'helped', 'Goldanna meeting/conversation outcome', *family)
    elif completed and clear(*family):
        if flag('goldanna_wanted'):
            put('alistair_family', 'not_helped', 'Origins completed', 'goldanna_wanted', 'No meeting outcome')
        elif flag('goldanna_wanted') is False:
            put('alistair_family', 'not_encountered', 'Origins completed', 'No Goldanna request or meeting')

    if flag('marjolaine_killed') and flag('marjolaine_spared'):
        note('leliana_past', 'Marjolaine is recorded both killed and spared; review her outcome.')
    elif flag('marjolaine_killed') and flag('marjolaine_spared') is False:
        put('leliana_past', 'killed', 'marjolaine_killed')
    elif flag('marjolaine_spared') and flag('marjolaine_killed') is False:
        put('leliana_past', 'sent_away', 'marjolaine_spared')
    elif completed and clear('marjolaine_confronted', 'marjolaine_killed', 'marjolaine_spared'):
        put('leliana_past', 'not_encountered', 'Origins completed', 'No Marjolaine confrontation/outcome')

    if flag('oghren_left') or flag('oghren_killed'):
        note('oghren_recruited', 'Oghren has a later departure/death record that clears current recruitment; review his recruitment history.')
    elif flag('oghren_recruited') and clear('oghren_left', 'oghren_killed'):
        put('oghren_recruited', 'recruited', 'oghren_recruited')
    elif completed and clear('oghren_recruited', 'oghren_left', 'oghren_killed'):
        put('oghren_recruited', 'not_recruited', 'Origins completed', 'oghren_recruited', 'No later departure/death')

    if flag('awakening_felsi_encouraged'):
        # gxa000_oghren.dlg node 42 records his promise to visit/write as a father.
        # Felsi leaving the Keep earlier is part of this quest, not its bad ending.
        put('oghren_felsi', 'reunited', 'awakening_felsi_encouraged')
    elif history.flag(2091) is True and clear('awakening_felsi_visited', 'awakening_felsi_encouraged',
                                           'awakening_felsi_resolution', 'awakening_felsi_refused'):
        put('oghren_felsi', 'not_helped', 'Awakening completed', 'No Awakening family visit or resolution')
    else:
        note('oghren_felsi', 'The Awakening family outcome is not established by the retained records. '
             'The earlier Origins tavern reunion/failure is a different event; choose the family outcome manually.')

    acquired = flag('real_grimoire_given') or flag('real_grimoire_kept')
    if acquired:
        if flag('flemeth_spared') and flag('flemeth_slain'):
            note('flemeth_grimoire', 'The real grimoire was acquired, but Flemeth is recorded both spared and slain.')
        elif flag('flemeth_spared') and flag('flemeth_slain') is False:
            put('flemeth_grimoire', 'peaceful', 'Real grimoire possession confirmed', 'flemeth_spared', 'flemeth_slain')
        elif flag('flemeth_slain') and flag('flemeth_spared') is False:
            put('flemeth_grimoire', 'defeated_flemeth', 'Real grimoire possession confirmed', 'flemeth_slain', 'flemeth_spared')
    elif completed and clear('real_grimoire_given', 'real_grimoire_kept', 'flemeth_quest_active',
            'flemeth_quest_complete', 'flemeth_spared', 'flemeth_fight_started', 'flemeth_slain'):
        put('flemeth_grimoire', 'not_acquired', 'Origins completed', 'No real-book or Flemeth quest outcome')
    if 'dao.flemeth_grimoire' not in choices and 'dao.flemeth_grimoire' not in notes:
        note('flemeth_grimoire', 'The Tower book, a hut key or fighting Flemeth alone does not confirm acquiring her real grimoire; review possession and method.')

    if flag('prisoner_killed'):
        # Killing also gives the key and sets FED. Death takes precedence.
        put('ostagar_deserter', 'killed', 'prisoner_killed')
    elif flag('prisoner_killed') is False and flag('prisoner_fed'):
        if flag('prisoner_guard_bribed') and flag('prisoner_food_obtained'):
            put('ostagar_deserter', 'bought_food', 'prisoner_fed', 'prisoner_guard_bribed', 'prisoner_food_obtained')
        else:
            note('ostagar_deserter', 'The prisoner was fed, but the same food-acquisition flag records stolen food and the guard sharing lunch. Choose the method manually.')
    else:
        note('ostagar_deserter', 'The reviewed plot flags cannot uniquely distinguish leaving the prisoner alone from unrecorded key theft. Review this choice manually.')

    if flag('mabari_healed') and flag('mabari_killed'):
        note('ostagar_mabari', 'The hound is recorded both healed and killed.')
    elif flag('mabari_healed') and flag('mabari_killed') is False:
        put('ostagar_mabari', 'cured', 'mabari_healed')
    elif flag('mabari_killed') and flag('mabari_healed') is False:
        put('ostagar_mabari', 'killed', 'mabari_killed')
    elif flag('mabari_flower_without_quest') and clear('mabari_healed', 'mabari_killed'):
        # The user defines kennel flower delivery as the equivalent cured
        # answer, regardless of origin or whether the muzzle quest set flag 4.
        put('ostagar_mabari', 'cured', 'mabari_flower_without_quest',
            'Kennel-master flower hand-in counts as healing; no explicit death')
    elif completed and clear('mabari_healed', 'mabari_killed'):
        # With neither a specific outcome nor the equivalent flower hand-in,
        # the completed three-answer quest falls back to not done.
        put('ostagar_mabari', 'not_helped', 'Origins completed',
            'Specific hound cure/death explicitly clear; no kennel flower hand-in')

    if flag('irving_alive') and flag('irving_dead'):
        note('irving_fate', 'Irving has conflicting survival and death codex entries.')
    elif flag('irving_alive') and flag('irving_dead') is False:
        put('irving_fate', 'alive', 'irving_alive')
    elif flag('irving_dead') and flag('irving_alive') is False:
        put('irving_fate', 'dead', 'irving_dead')

    if flag('cullen_agreed'):
        put('cullen_request', 'agreed', 'cullen_agreed')
    elif flag('circle_complete') and flag('cullen_agreed') is False:
        put('cullen_request', 'disagreed', 'circle_complete', 'cullen_agreed')

    if flag('urn_poisoned'):
        put('urn_poisoned', 'poisoned', 'urn_poisoned')
    elif completed and flag('urn_complete') and flag('urn_poisoned') is False:
        put('urn_poisoned', 'preserved', 'Origins completed', 'urn_complete', 'urn_poisoned')

    if flag('dagna_irving_accepted') or flag('dagna_greagoir_refused'):
        put('dagna_permission', 'requested', 'dagna_irving_accepted', 'dagna_greagoir_refused')
    elif completed and clear('dagna_irving_accepted', 'dagna_greagoir_refused'):
        put('dagna_permission', 'not_requested', 'Origins completed', 'No Irving/Greagoir request response')

    if flag('dagna_left') and flag('dagna_failed'):
        note('dagna_outcome', 'Dagna is recorded both departed and failed; review the conflicting quest history.')
    elif flag('dagna_left'):
        put('dagna_outcome', 'studied', 'dagna_left')
    elif flag('dagna_failed'):
        note('dagna_outcome', 'A failed Dagna quest does not uniquely establish the Keep’s stayed-with-her-father outcome.')
    elif flag('dagna_refused') and clear('dagna_accepted', 'dagna_complete', 'dagna_left'):
        put('dagna_outcome', 'refused', 'dagna_refused', 'No subsequent accepted/completed quest')
    elif completed and flag('dagna_complete') and flag('circle_all_mages_dead') and clear(
            'dagna_left', 'dagna_refused', 'dagna_irving_accepted', 'dagna_greagoir_refused', 'dagna_failed'):
        put('dagna_outcome', 'circle_destroyed', 'dagna_complete', 'circle_all_mages_dead', 'No departure or alternate response')
    elif completed and clear('dagna_talked', 'dagna_accepted', 'dagna_complete', 'dagna_left',
            'dagna_refused', 'dagna_irving_accepted', 'dagna_greagoir_refused', 'dagna_failed'):
        put('dagna_outcome', 'not_met', 'Origins completed', 'No Dagna conversation or quest evidence')
    else:
        note('dagna_outcome', 'Dagna’s quest is incomplete or its shared completion flags do not uniquely identify a Keep answer.')
    return choices, evidence, notes
