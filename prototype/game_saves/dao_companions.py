"""Direct Origins companion outcomes, checked against original plots/scripts.

Callers supply active DAO plots or their copied records retained in DA2, with
missing records kept unknown. Computed plot IDs are never saved bits.
"""

SUPPORTED = frozenset('dao.' + key for key in (
    'sten_recruited', 'sten_release', 'sten_sword', 'leliana_fate', 'wynne_recruited', 'wynne_fate'))

# name: (source plot GUID, stored flag). No runtime source archives are needed.
FLAGS = {
    'sten_recruited': ('25BC6F5E8DA847938245071233433332', 13),
    'leliana_recruited': ('25BC6F5E8DA847938245071233433332', 4),
    'wynne_recruited': ('25BC6F5E8DA847938245071233433332', 8),
    'sten_released': ('2B9F3A9F5D024CA794874529BDC6F9B0', 0),
    'sten_lock_picked': ('2B9F3A9F5D024CA794874529BDC6F9B0', 13),
    'sten_key_permission': ('2B9F3A9F5D024CA794874529BDC6F9B0', 9),
    'mother_threatened': ('FD98290AFDD34B89B50F8A0404BC9E6E', 0),
    'mother_attacked': ('FD98290AFDD34B89B50F8A0404BC9E6E', 1),
    'sten_left': ('AF48E71C721A4240B4E1FF4FB592C99F', 5),
    'sten_sword_returned': ('AF48E71C721A4240B4E1FF4FB592C99F', 13),
    'leliana_attacked': ('919B6591AA754F5E8B871766F25A68AB', 41),
    'leliana_left': ('919B6591AA754F5E8B871766F25A68AB', 42),
    'leliana_joined_initially': ('B2FD69B4E06247C09E4A7A985E5C97EB', 4),
    'leliana_joined_at_gates': ('B2FD69B4E06247C09E4A7A985E5C97EB', 5),
    'leliana_fired': ('B2FD69B4E06247C09E4A7A985E5C97EB', 9),
    'leliana_second_crisis': ('0AF116EDB51E47C3959348FFF1692E4A', 84),
    'leliana_urn_reaction': ('0AF116EDB51E47C3959348FFF1692E4A', 85),
    'urn_tainted': ('7FD7A773C53142FABAB1BEDED0BED56A', 1),
    'circle_complete': ('C232DA078A044178AA9FCBC6E537FA75', 2),
    'wynne_killed_circle': ('C232DA078A044178AA9FCBC6E537FA75', 6),
    'wynne_helped': ('C232DA078A044178AA9FCBC6E537FA75', 7),
    'wynne_did_not_join': ('C232DA078A044178AA9FCBC6E537FA75', 25),
    'wynne_left_circle': ('C232DA078A044178AA9FCBC6E537FA75', 37),
    'wynne_killed_at_cullen': ('C232DA078A044178AA9FCBC6E537FA75', 51),
    'wynne_codex_killed': ('622A25A2E4F5408EADFA2463750CA6F3', 4),
    'wynne_codex_joined': ('622A25A2E4F5408EADFA2463750CA6F3', 5),
    'wynne_killed_urn': ('622A25A2E4F5408EADFA2463750CA6F3', 6),
}


def infer(history):
    choices, evidence, notes = {}, {}, {}

    def flag(name):
        guid, bit = FLAGS[name]
        words = history.plots.get(guid)
        return None if words is None else bool(words[bit // 32] & (1 << (bit % 32)))

    def clear(*names): return all(flag(name) is False for name in names)

    def put(key, answer, *sources):
        key = 'dao.' + key
        choices[key] = answer
        evidence[key] = 'DAO save active history: ' + '; '.join(
            f'{name} [{FLAGS[name][0]}#{FLAGS[name][1]}]' if name in FLAGS else name for name in sources)

    def note(key, message): notes['dao.' + key] = message

    completed = history.flag(2089) is True
    recruited = flag('sten_recruited')
    if flag('sten_left'):
        note('sten_recruited', 'Sten left after recruitment; the tapestry has no separate departure answer. Review his recruitment manually.')
    elif recruited:
        put('sten_recruited', 'recruited', 'sten_recruited')
    elif completed and recruited is False and clear('sten_left', 'sten_sword_returned'):
        put('sten_recruited', 'not_recruited', 'Origins completed', 'sten_recruited', 'sten_left', 'sten_sword_returned')

    if flag('sten_released'):
        if flag('sten_lock_picked'):
            put('sten_release', 'picked_lock', 'sten_released', 'sten_lock_picked')
        elif flag('sten_key_permission') and clear('sten_lock_picked', 'mother_threatened', 'mother_attacked'):
            put('sten_release', 'persuaded', 'sten_released', 'sten_key_permission', 'mother_threatened', 'mother_attacked')
        elif flag('mother_threatened') or flag('mother_attacked'):
            # Threatened is also set by FAILED threats, and the same history
            # can later obtain permission through persuasion/Leliana. No
            # persistent flag proves which attempt actually secured the key.
            note('sten_release', 'Sten was freed, but threats/violence and key permission do not uniquely identify how he was released. Review the method manually.')
    elif completed and flag('sten_released') is False and clear('sten_lock_picked', 'sten_recruited', 'sten_left'):
        put('sten_release', 'not_freed', 'Origins completed', 'sten_released', 'sten_lock_picked', 'sten_recruited', 'sten_left')

    if flag('sten_sword_returned'):
        put('sten_sword', 'returned', 'sten_sword_returned')
    elif completed and flag('sten_sword_returned') is False:
        if choices.get('dao.sten_recruited') == 'not_recruited':
            put('sten_sword', 'not_recruited', 'Origins completed', 'sten_recruited', 'sten_left')
        elif recruited and flag('sten_left') is False:
            put('sten_sword', 'not_returned', 'Origins completed', 'sten_recruited', 'sten_sword_returned')

    recruited = flag('leliana_recruited')
    attacked, left = flag('leliana_attacked'), flag('leliana_left')
    if attacked and left or recruited and (attacked or left):
        note('leliana_fate', 'Leliana has conflicting recruitment, hostility or departure evidence; no final fate was guessed.')
    elif attacked:
        if completed and flag('urn_tainted') and left is False and recruited is False:
            put('leliana_fate', 'killed_at_urn', 'Origins completed', 'leliana_attacked', 'urn_tainted', 'leliana_recruited')
        else:
            note('leliana_fate', 'Leliana turned hostile, but a completed, consistent Urn outcome is not established by this save.')
    elif left:
        if flag('urn_tainted') and flag('leliana_urn_reaction') and flag('leliana_second_crisis') is False and recruited is False:
            put('leliana_fate', 'left_after_urn', 'leliana_left', 'urn_tainted', 'leliana_urn_reaction', 'leliana_second_crisis')
        else:
            note('leliana_fate', 'Leliana’s departure flag is shared by the Urn and approval crisis; the specific departure needs review.')
    elif completed and recruited and clear('leliana_attacked', 'leliana_left'):
        put('leliana_fate', 'alive', 'Origins completed', 'leliana_recruited', 'leliana_attacked', 'leliana_left')
    elif completed and recruited is False and clear('leliana_attacked', 'leliana_left',
            'leliana_joined_initially', 'leliana_joined_at_gates', 'leliana_fired'):
        put('leliana_fate', 'not_recruited', 'Origins completed', 'leliana_recruited',
            'leliana_joined_initially', 'leliana_joined_at_gates', 'leliana_fired')

    circle_death = any(flag(name) is True for name in ('wynne_killed_circle', 'wynne_killed_at_cullen', 'wynne_codex_killed'))
    urn_death = flag('wynne_killed_urn')
    recruited = flag('wynne_recruited')
    if circle_death and urn_death:
        note('wynne_fate', 'The save records Wynne dying both at the Circle and at the Urn; no fate was guessed.')
        note('wynne_recruited', 'Wynne’s conflicting death records leave her recruitment history ambiguous.')
    else:
        if recruited:
            put('wynne_recruited', 'recruited', 'wynne_recruited')
        elif urn_death:
            # The Urn script clears the current-party recruitment flag before
            # combat. A confirmed Urn death proves she had been recruited.
            put('wynne_recruited', 'recruited', 'wynne_killed_urn', 'Recruited before the Urn death')
        elif recruited is False and (circle_death or completed and flag('circle_complete') and
                clear('wynne_helped', 'wynne_left_circle', 'wynne_codex_joined', 'wynne_killed_urn')):
            put('wynne_recruited', 'not_recruited', 'wynne_recruited', 'Circle outcome without retained recruitment')
        if circle_death:
            put('wynne_fate', 'died_at_circle', 'wynne_killed_circle', 'wynne_killed_at_cullen', 'wynne_codex_killed')
        elif urn_death:
            put('wynne_fate', 'killed_at_urn', 'wynne_killed_urn')
        elif completed and recruited and clear('wynne_killed_circle', 'wynne_killed_at_cullen',
                'wynne_codex_killed', 'wynne_killed_urn', 'wynne_did_not_join', 'wynne_left_circle'):
            put('wynne_fate', 'alive', 'Origins completed', 'wynne_recruited', 'No Circle or Urn death/departure markers')
        elif choices.get('dao.wynne_recruited') == 'not_recruited' and completed and clear(
                'wynne_killed_circle', 'wynne_killed_at_cullen', 'wynne_codex_killed', 'wynne_killed_urn'):
            put('wynne_fate', 'not_recruited', 'Origins completed', 'wynne_recruited', 'No prior recruitment or death')
    return choices, evidence, notes
