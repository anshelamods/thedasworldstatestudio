"""Final six DAO controls, inferred only from reviewed active vanilla plots.

Awakening Keep survival uses the original epilogue expression, not a guessed
combination of every available upgrade. Computed flags are never saved bits.
"""

SUPPORTED = frozenset('dao.' + name for name in (
    'slim_couldry', 'kylon_falcons', 'kylon_crimson_oars',
    'awakening_protection', 'power_of_blood', 'kitty_amalia'))

FLAGS = {
    'couldry_done': ('5840679048B84D1DB4B1EFA5C3D058F5', 9),
    'falcons_quelled': ('5C301313E4424E56BF1F3C08B065084C', 1),
    'falcons_killed': ('5C301313E4424E56BF1F3C08B065084C', 2),
    'falcons_left': ('5C301313E4424E56BF1F3C08B065084C', 12),
    'oars_killed': ('1486DD45DAED4876B1DEDB749D8E8791', 3),
    'oars_left': ('1486DD45DAED4876B1DEDB749D8E8791', 4),
    'oars_sided_with': ('1486DD45DAED4876B1DEDB749D8E8791', 5),
    'amaranthine_saved': ('1C7395DEAAC14F889A5D41F86854F48B', 7),
    'amaranthine_abandoned': ('1C7395DEAAC14F889A5D41F86854F48B', 25),
    'keep_defended': ('923E283E44DB4F48BA557085F77D1152', 7),
    'keep_failed': ('923E283E44DB4F48BA557085F77D1152', 8),
    'granite_complete': ('542D51BDE496410FAE275169B06ABF3E', 4),
    'granite_without_men': ('542D51BDE496410FAE275169B06ABF3E', 6),
    'walls_funded': ('2C681ED0363B40769313A929A9B32C65', 1),
    'blood_accepted': ('0802E25F3C1144A5B59109F27AAE6CA7', 0),
    'blood_destroyed': ('0802E25F3C1144A5B59109F27AAE6CA7', 1),
    'matthias_dead': ('A8211E73A50347D9B72448F24648064C', 0),
    'amalia_escaped': ('A8211E73A50347D9B72448F24648064C', 6),
    'amalia_possessed': ('A8211E73A50347D9B72448F24648064C', 8),
    'amalia_dead': ('A8211E73A50347D9B72448F24648064C', 21),
    'matthias_possessed': ('A8211E73A50347D9B72448F24648064C', 23),
    'left_amalia_free': ('A8211E73A50347D9B72448F24648064C', 24),
    'left_amalia_possessed': ('A8211E73A50347D9B72448F24648064C', 25),
    'left_without_amalia': ('A8211E73A50347D9B72448F24648064C', 26),
    'left_matthias_possessed': ('A8211E73A50347D9B72448F24648064C', 27),
}


def infer(history):
    choices, evidence, notes = {}, {}, {}

    def flag(name):
        guid, bit = FLAGS[name]
        words = history.plots.get(guid)
        return None if words is None else bool(words[bit // 32] & (1 << (bit % 32)))
    def clear(*names): return all(flag(n) is False for n in names)
    def put(key, answer, *names):
        key = 'dao.' + key
        choices[key] = answer
        evidence[key] = 'DAO save active history: ' + '; '.join(
            f'{n} [{FLAGS[n][0]}#{FLAGS[n][1]}]' if n in FLAGS else n for n in names)
    def note(key, text): notes['dao.' + key] = text

    completed = history.flag(2089) is True
    if flag('couldry_done'):
        put('slim_couldry', 'completed', 'couldry_done')
    elif completed and flag('couldry_done') is False:
        put('slim_couldry', 'not_completed', 'Origins completed', 'couldry_done')

    falcons = ('falcons_quelled', 'falcons_killed', 'falcons_left')
    if any(flag(n) for n in falcons):
        put('kylon_falcons', 'helped', *falcons)
    elif completed and clear(*falcons):
        put('kylon_falcons', 'not_helped', 'Origins completed', *falcons)

    oars_cleared = bool(flag('oars_killed') or flag('oars_left'))
    if oars_cleared and flag('oars_sided_with'):
        note('kylon_crimson_oars', 'The save records both clearing and siding with the Crimson Oars. Review this outcome manually.')
    elif oars_cleared and flag('oars_sided_with') is False:
        put('kylon_crimson_oars', 'handled', 'oars_killed', 'oars_left', 'oars_sided_with')
    elif (flag('oars_sided_with') and not oars_cleared) or (completed and clear('oars_killed', 'oars_left')):
        put('kylon_crimson_oars', 'not_handled', 'oars_sided_with', 'oars_killed', 'oars_left')

    if flag('amaranthine_saved') and (flag('amaranthine_abandoned') or flag('keep_defended')):
        note('awakening_protection', 'Both mutually exclusive final siege routes are recorded. Review which places were protected.')
    elif flag('amaranthine_saved') and clear('amaranthine_abandoned', 'keep_defended', 'keep_failed'):
        # Original vgk100pt_voldrik #257; used by ep1_epilogue node 28.
        granite = flag('granite_complete') or flag('granite_without_men')
        if granite and flag('walls_funded'):
            put('awakening_protection', 'both', 'amaranthine_saved', 'granite_complete',
                'granite_without_men', 'walls_funded', 'Original Keep-survival epilogue condition')
        elif clear('granite_complete', 'granite_without_men') or flag('walls_funded') is False:
            put('awakening_protection', 'amaranthine', 'amaranthine_saved',
                'granite_complete', 'granite_without_men', 'walls_funded')
        else:
            note('awakening_protection', 'Amaranthine was saved, but the wall-upgrade evidence needed to determine Keep survival is missing.')
    elif flag('keep_defended') and flag('amaranthine_abandoned') and clear('amaranthine_saved', 'keep_failed'):
        put('awakening_protection', 'keep', 'keep_defended', 'amaranthine_abandoned')

    if flag('blood_accepted') and flag('blood_destroyed'):
        note('power_of_blood', 'The concoction is recorded as both consumed and destroyed. Review this outcome manually.')
    elif flag('blood_accepted') and flag('blood_destroyed') is False:
        put('power_of_blood', 'drank', 'blood_accepted')
    elif (flag('blood_destroyed') and flag('blood_accepted') is False) or (completed and clear('blood_accepted', 'blood_destroyed')):
        put('power_of_blood', 'did_not_drink', 'blood_accepted', 'blood_destroyed', 'Destroyed or not consumed at completed Origins')

    # Validate the complete state, including final departure markers. In modded
    # or edited histories, do not choose an arbitrary winner between endings.
    kitty_names = ('matthias_dead', 'amalia_escaped', 'amalia_possessed', 'amalia_dead',
        'matthias_possessed', 'left_amalia_free', 'left_amalia_possessed',
        'left_without_amalia', 'left_matthias_possessed')
    if flag('matthias_dead') is not None:
        dead_m, escaped, possessed_a, dead_a, possessed_m, free_end, a_end, dead_end, m_end = [flag(n) for n in kitty_names]
        candidates = []
        if (escaped or free_end) and not any((dead_m, possessed_a, dead_a, possessed_m, a_end, dead_end, m_end)):
            candidates.append('both_unpossessed')
        if (possessed_a or a_end) and not any((dead_m, escaped, dead_a, possessed_m, free_end, dead_end, m_end)):
            candidates.append('amalia_possessed')
        if (possessed_m or m_end) and not any((dead_m, possessed_a, dead_a, free_end, a_end, dead_end)):
            candidates.append('matthias_possessed')
        # The original Matthias dialogue sets possession 23 before the player
        # can attack him and set death 0. That historical possession is expected,
        # not a conflicting final fate (Matthias dialogue 8 -> 10 -> 12 -> 121).
        if dead_m and (escaped or possessed_m) and not any((possessed_a, dead_a, a_end, dead_end, m_end)):
            candidates.append('matthias_dead')
        if dead_a and not any((dead_m, escaped, possessed_a, possessed_m, free_end, a_end, m_end)):
            candidates.append('amalia_dead')
        if len(candidates) == 1:
            put('kitty_amalia', candidates[0], *kitty_names)
        elif any(flag(n) for n in kitty_names):
            note('kitty_amalia', 'Kitty’s encounter has incomplete or conflicting escape, death or possession outcomes. Review Matthias and Amalia manually.')
    return choices, evidence, notes
