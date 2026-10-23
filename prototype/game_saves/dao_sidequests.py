"""Direct DAO side quests from original plot and conversation evidence."""

SUPPORTED = frozenset('dao.' + key for key in (
    'cammen_relationship', 'elora_halla', 'athras_danyla', 'varathorn_ironbark',
    'deygan_fate', 'burkel_chantry', 'orta_ancestry', 'legion_noble_house',
    'rogek_lyrium', 'oswyn_sighard', 'irminric_ring', 'justine_scroll'))

FLAGS = {
    'cammen_separated': ('18B66CC3E6E949FE93E85ED237EF934B', 3),
    'cammen_together': ('18B66CC3E6E949FE93E85ED237EF934B', 4),
    'cammen_met': ('DB2FB13C86A04A71A10B4A5E97500523', 1),
    'gheyna_met': ('DB2FB13C86A04A71A10B4A5E97500523', 2),
    'halla_saved': ('8BFAAEE6FDD344A4932C1BFF152ABE4D', 3),
    'halla_killing': ('8BFAAEE6FDD344A4932C1BFF152ABE4D', 5),
    'halla_killed': ('8BFAAEE6FDD344A4932C1BFF152ABE4D', 6),
    'athras_told': ('7B5C94475ECF428F83E8F548D390EF91', 3),
    'athras_reward': ('7B5C94475ECF428F83E8F548D390EF91', 5),
    'athras_angry': ('7B5C94475ECF428F83E8F548D390EF91', 6),
    'athras_scarf': ('7B5C94475ECF428F83E8F548D390EF91', 16),
    'ironbark_complete': ('BE651409871F475E9FC20C48F6FBC8CE', 5),
    'ironbark_bow': ('BE651409871F475E9FC20C48F6FBC8CE', 6),
    'ironbark_armor': ('BE651409871F475E9FC20C48F6FBC8CE', 7),
    'ironbark_jewelry': ('BE651409871F475E9FC20C48F6FBC8CE', 8),
    'ironbark_both': ('BE651409871F475E9FC20C48F6FBC8CE', 9),
    'ironbark_gift': ('BE651409871F475E9FC20C48F6FBC8CE', 10),
    'ironbark_money': ('BE651409871F475E9FC20C48F6FBC8CE', 11),
    'deygan_returned_body': ('AECCCA7FE54A4F28AC2838B15AC39ED6', 0),
    'deygan_returned_alive': ('AECCCA7FE54A4F28AC2838B15AC39ED6', 1),
    'deygan_healed': ('AECCCA7FE54A4F28AC2838B15AC39ED6', 2),
    'deygan_killed': ('AECCCA7FE54A4F28AC2838B15AC39ED6', 10),
    'burkel_complete': ('6EA7AC67D12B402084CA9905D3815F7D', 1),
    'burkel_failed': ('6EA7AC67D12B402084CA9905D3815F7D', 2),
    'burkel_permission': ('6EA7AC67D12B402084CA9905D3815F7D', 5),
    'orta_complete': ('1CF820951F69492495FBF635A8B0F68E', 4),
    'orta_failed': ('1CF820951F69492495FBF635A8B0F68E', 5),
    'orta_assembly': ('1CF820951F69492495FBF635A8B0F68E', 6),
    'legion_filed': ('FF482830F073470CACEA04B640C2560F', 2),
    'legion_codex_filed': ('EDA07192072C4B7D96ACB432DBDDE790', 4),
    'rogek_complete': ('D5ED00AC5DBD4AFE9E9AC5704FCDBA34', 5),
    'rogek_failed': ('D5ED00AC5DBD4AFE9E9AC5704FCDBA34', 9),
    'oswyn_spoke_sighard': ('6A46B80DFEDB44B09219CC6527AFCF76', 93),
    'irminric_proof_given': ('6A46B80DFEDB44B09219CC6527AFCF76', 49),
    'justine_scroll_given': ('51ECED21579443BD95DEF73AF5BBB9C4', 5),
}


def infer(history):
    choices, evidence, notes = {}, {}, {}

    def flag(name):
        guid, bit = FLAGS[name]
        words = history.plots.get(guid)
        return None if words is None else bool(words[bit // 32] & (1 << (bit % 32)))

    def clear(*names): return all(flag(n) is False for n in names)

    def empty_plot(name):
        words = history.plots.get(FLAGS[name][0])
        return words is not None and not any(words)

    def put(key, answer, *sources):
        key = 'dao.' + key
        choices[key] = answer
        evidence[key] = 'DAO save active history: ' + '; '.join(
            f'{n} [{FLAGS[n][0]}#{FLAGS[n][1]}]' if n in FLAGS else n for n in sources)

    def note(key, text): notes['dao.' + key] = text

    completed = history.flag(2089) is True
    if flag('cammen_separated') and flag('cammen_together'):
        note('cammen_relationship', 'Cammen and Gheyna are recorded both separated and together.')
    elif flag('cammen_separated') and flag('cammen_together') is False:
        put('cammen_relationship', 'broke_up', 'cammen_separated')
    elif flag('cammen_together') and flag('cammen_separated') is False:
        put('cammen_relationship', 'together', 'cammen_together')
    elif completed and clear('cammen_met', 'gheyna_met') and empty_plot('cammen_separated'):
        put('cammen_relationship', 'not_met', 'Origins completed', 'Neither character met; quest plot empty')
    else:
        note('cammen_relationship', 'A meeting, pelt promise or persuasion attempt alone does not establish a final relationship; the tapestry has no unfinished answer.')

    dead_halla = flag('halla_killing') or flag('halla_killed')
    if flag('halla_saved') and dead_halla:
        note('elora_halla', 'The halla is recorded both saved and killed.')
    elif flag('halla_saved') and clear('halla_killing', 'halla_killed'):
        put('elora_halla', 'saved', 'halla_saved')
    elif dead_halla and flag('halla_saved') is False:
        put('elora_halla', 'killed', 'halla_killing', 'halla_killed')
    elif completed and clear('halla_saved', 'halla_killing', 'halla_killed'):
        put('elora_halla', 'not_helped', 'Origins completed', 'No saved/killed outcome')

    if flag('athras_told'):
        put('athras_danyla', 'told', 'athras_told')
    elif completed and clear('athras_told', 'athras_reward', 'athras_angry', 'athras_scarf'):
        put('athras_danyla', 'not_told', 'Origins completed', 'No final news or alternate conversation outcome')
    elif flag('athras_angry') or flag('athras_reward') or flag('athras_scarf'):
        note('athras_danyla', 'Athras has an alternate or unfinished conversation record without the confirmed news marker; review what he was told.')

    ironbark = tuple(n for n in FLAGS if n.startswith('ironbark_'))
    if any(flag(n) for n in ironbark):
        put('varathorn_ironbark', 'brought', *ironbark)
    elif completed and clear(*ironbark):
        put('varathorn_ironbark', 'not_brought', 'Origins completed', 'No ironbark handover/reward')

    returned_alive = flag('deygan_returned_alive') or flag('deygan_healed')
    if flag('deygan_killed') and returned_alive:
        note('deygan_fate', 'Deygan is recorded both killed and returned alive/healed.')
    elif flag('deygan_killed'):
        # Returning his dead body must not overwrite the player killing him.
        put('deygan_fate', 'killed', 'deygan_killed')
    elif (returned_alive or flag('deygan_returned_body')) and flag('deygan_killed') is False:
        put('deygan_fate', 'returned', 'deygan_returned_body', 'deygan_returned_alive', 'deygan_healed')
    elif completed and empty_plot('deygan_killed'):
        put('deygan_fate', 'not_met', 'Origins completed', 'Deygan encounter plot empty')
    else:
        note('deygan_fate', 'Deygan was encountered without a supported terminal outcome; leaving him in the forest is not “did not encounter.”')

    if flag('burkel_complete') and flag('burkel_failed'):
        note('burkel_chantry', 'Burkel has conflicting completion and failure records.')
    elif flag('burkel_complete') and flag('burkel_failed') is False:
        put('burkel_chantry', 'helped', 'burkel_complete')
    elif completed and clear('burkel_complete', 'burkel_permission'):
        put('burkel_chantry', 'not_helped', 'Origins completed', 'No completed Chantry or permission')

    helped_orta = flag('orta_assembly') or flag('orta_complete')
    if helped_orta and flag('orta_failed'):
        note('orta_ancestry', 'Orta has conflicting Assembly/completion and failure records.')
    elif helped_orta and flag('orta_failed') is False:
        put('orta_ancestry', 'helped', 'orta_assembly', 'orta_complete')
    elif completed and clear('orta_assembly', 'orta_complete'):
        put('orta_ancestry', 'not_helped', 'Origins completed', 'No records delivered to Orta/Assembly outcome')

    if flag('legion_filed') or flag('legion_codex_filed'):
        put('legion_noble_house', 'proven', 'legion_filed', 'legion_codex_filed')
    elif completed and clear('legion_filed', 'legion_codex_filed'):
        put('legion_noble_house', 'not_proven', 'Origins completed', 'Connection not filed in the Memories')

    if flag('rogek_complete') and flag('rogek_failed'):
        note('rogek_lyrium', 'Rogek has conflicting final completion and failure records.')
    elif flag('rogek_complete') and flag('rogek_failed') is False:
        put('rogek_lyrium', 'completed', 'rogek_complete')
    elif completed and flag('rogek_complete') is False:
        put('rogek_lyrium', 'not_completed', 'Origins completed', 'rogek_complete')

    for key, marker, yes, no in (
        ('oswyn_sighard', 'oswyn_spoke_sighard', 'told', 'not_told'),
        ('irminric_ring', 'irminric_proof_given', 'given', 'not_given'),
        ('justine_scroll', 'justine_scroll_given', 'brought', 'not_brought')):
        if flag(marker): put(key, yes, marker)
        elif completed and flag(marker) is False: put(key, no, 'Origins completed', marker)
    return choices, evidence, notes
