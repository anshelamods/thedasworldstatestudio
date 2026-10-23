"""DAO history carried by DA2, using the shipped worldvault.gda specification.

Saved scalar values (17603 / 17607) take precedence over copied DAO plots:
these are the world-vault values DA2 actually uses. No GDA expression is executed.
"""
from .gff import ListView, Node, SaveFormatError


def _rows(value, limit, name):
    if not isinstance(value, (ListView, tuple, list)) or len(value) > limit:
        raise SaveFormatError('Invalid or oversized carried DAO ' + name + ' table.')
    return value


class DaoHistory:
    def __init__(self, reader):
        self.booleans, self.integers, self.plots = {}, {}, {}
        vault = reader.get((16024,))
        if vault is None:
            return
        if not isinstance(vault, Node):
            raise SaveFormatError('Invalid carried DAO world vault.')
        for label, target in ((17603, self.integers), (17607, self.booleans)):
            for row in _rows(vault.get(label, ()), 10000, 'value'):
                if not isinstance(row, Node):
                    raise SaveFormatError('Invalid carried DAO value record.')
                key, value = row.get(17601), row.get(17602)
                if type(key) is not int or key in target or type(value) is not int:
                    raise SaveFormatError('Duplicate or invalid carried DAO value.')
                if label == 17607 and value not in (0, 1):
                    raise SaveFormatError('Invalid carried DAO boolean.')
                target[key] = value
        for row in _rows(vault.get(16401, ()), 20000, 'plot'):
            if not isinstance(row, Node):
                raise SaveFormatError('Invalid carried DAO plot record.')
            guid = row.get(16402)
            if not isinstance(guid, str) or len(guid) != 32 or any(c not in '0123456789abcdefABCDEF' for c in guid):
                continue  # Named mod plots cannot match the vanilla definitions.
            guid = guid.upper()
            words = tuple(row.get(i) for i in range(16403, 16407))
            if guid in self.plots or any(type(w) is not int or not -2**31 <= w < 2**32 for w in words):
                raise SaveFormatError('Duplicate or invalid carried DAO plot.')
            self.plots[guid] = tuple(w & 0xffffffff for w in words)

    def flag(self, key):
        if key in self.booleans:
            return bool(self.booleans[key])
        source = DIRECT.get(key)
        if source and source[0] in self.plots:
            return bool(self.plots[source[0]][source[1] // 32] & (1 << (source[1] % 32)))
        return None


SUPPORTED = frozenset('dao.' + key for key in (
    'warden_identity', 'warden_class', 'warden_romance', 'ferelden_ruler', 'alistair_fate',
    'alistair_relationship', 'loghain_fate', 'warden_fate', 'archdemon_killer', 'morrigan_child',
    'broken_circle', 'connor_fate', 'isolde_fate', 'nature_outcome', 'orzammar_ruler', 'anvil_fate',
    'dog_recruited', 'zevran_recruited', 'zevran_fate', 'architect_fate', 'nathaniel_fate',
    'avernus_fate', 'shale_fate', 'shale_recruited', 'witch_hunt', 'redcliffe_defense'))


def infer_dao(v):
    choices, evidence, notes = {}, {}, {}
    f = v.flag
    def put(key, answer, source):
        choices['dao.' + key] = answer
        evidence['dao.' + key] = getattr(v, 'source_label', 'DAO history stored in DA2') + ': ' + source

    def all_false(keys):
        return all(f(key) is False for key in keys)

    def choose(key, candidates):
        found = [(answer, source) for condition, answer, source in candidates if condition]
        if len({answer for answer, _ in found}) == 1:
            put(key, found[0][0], '; '.join(source for _, source in found))
        elif found:
            notes['dao.' + key] = 'The DAO history records conflicting outcomes; no answer was guessed.'

    origin_candidates = [(2001, 'dwarf_commoner'), (2002, 'dwarf_noble'), (2003, 'city_elf'),
                         (2004, 'dalish_elf'), (2005, 'human_noble')]
    origins = [origin for key, origin in origin_candidates if f(key)]
    if f(2000):
        race = v.integers.get(1001)
        # These are DAO's race values carried verbatim, not DA2 creature races.
        origins.append({3: 'human_mage', 2: 'elven_mage'}.get(race))
    gender = {1: 'male', 2: 'female'}.get(v.integers.get(1000))
    if gender and len(origins) == 1 and origins[0]:
        put('warden_identity', gender + '_' + origins[0], 'Hero gender 1000, race 1001 and background booleans 2000–2005')
    job = {1: 'warrior', 2: 'mage', 3: 'rogue'}.get(v.integers.get(1045))
    if job:
        put('warden_class', job, 'Hero class 1045, imported from DAO stat property 27')
    elif 1045 not in v.integers and f(2000) and len(origins) == 1:
        put('warden_class', 'mage', 'Circle mage background 2000; warrior/rogue are never inferred from origin alone')

    killers = [(2028, 'alistair'), (2029, 'loghain'), (2030, 'warden')]
    choose('archdemon_killer', [(f(k), answer, f'Archdemon killer {k}') for k, answer in killers])
    killer = choices.get('dao.archdemon_killer')
    completed = f(2089) if f(2089) is not None else bool(killer)
    ritual_ids = (2034, 2035, 2036, 2100, 2101, 2102)
    ritual = f(2104)
    ritual_conflict = ((ritual is False and any(f(k) for k in ritual_ids)) or
                       (ritual is True and all_false(ritual_ids)))
    if ritual_conflict:
        ritual = None
        notes['dao.morrigan_child'] = 'The ritual-performed value disagrees with the ritual-parent markers.'
    if ritual is None and not ritual_conflict:
        if any(f(k) for k in ritual_ids):
            ritual = True
        elif all_false(ritual_ids):
            ritual = False
    if not ritual_conflict:
        choose('morrigan_child', [
            (f(2034) or f(2100), 'old_god_alistair', 'Ritual with Alistair: 2034 / 2100'),
            (f(2035) or f(2102), 'old_god_warden', 'Ritual with Warden: 2035 / 2102'),
            (f(2036) or f(2101), 'old_god_loghain', 'Ritual with Loghain: 2036 / 2101'),
            (completed and ritual is False and f(2047) is False, 'none', 'Completed Origins, no ritual and no Morrigan make-love marker'),
            (completed and ritual is False and f(2047) and gender == 'male', 'human_warden',
             'Completed Origins, male Warden, Morrigan make-love 2047 and no ritual'),
        ])
    if killer and (killer != 'warden' or ritual is not None):
        put('warden_fate', 'sacrificed' if killer == 'warden' and ritual is False else 'alive',
            'Recorded Archdemon killer and ritual-performed state')

    romance_ids = [(2040, 'alistair'), (2042, 'leliana'), (2046, 'morrigan'), (2048, 'zevran')]
    choose('warden_romance', [(f(k), answer, f'Active romance {k}') for k, answer in romance_ids])
    if completed and all_false([k for k, _ in romance_ids]):
        put('warden_romance', 'none', 'All four active-romance values explicitly clear after Origins completion')
    # Marriage flags are more specific than the broad king/queen booleans.
    if completed:
        marriages = [(2020, 'alistair_anora'), (2026, 'alistair_warden'), (2024, 'anora_warden')]
        if any(f(k) for k, _ in marriages):
            choose('ferelden_ruler', [(f(k), a, f'Landsmeet marriage {k}') for k, a in marriages])
        elif all_false([k for k, _ in marriages]):
            choose('ferelden_ruler', [(f(2021), 'alistair_alone', 'Alistair king 2021; no consort'),
                                      (f(2027), 'anora_alone', 'Anora queen 2027; no consort')])
        king = any(f(k) for k in (2020, 2021, 2026))
        if f(2023) and killer == 'alistair' and ritual is False:
            notes['dao.alistair_fate'] = 'The history records both Alistair’s execution and his Archdemon sacrifice.'
        elif f(2023):
            put('alistair_fate', 'executed', 'Alistair executed 2023')
        elif killer == 'alistair' and ritual is not True:
            if ritual is False:
                put('alistair_fate', 'sacrificed', 'Alistair killed the Archdemon without the ritual')
        elif killer is None and ritual is not True:
            pass  # A Landsmeet role alone does not prove final survival.
        elif king:
            put('alistair_fate', 'king', 'King/royal marriage 2020 / 2021 / 2026 after Origins completion')
        elif f(2022) and f(2023) is False:
            put('alistair_fate', 'drunk', 'Alistair left permanently (2022), without execution')
        elif all_false((2020, 2021, 2022, 2023, 2026, 2097)):
            put('alistair_fate', 'warden', 'Completed Origins; no kingship, departure, execution or recruited Loghain')
        if f(2026):
            put('alistair_relationship', 'queen', 'Warden engaged/married to Alistair (2026)')
        elif f(2040) and choices.get('dao.warden_fate') == 'alive':
            fate = choices.get('dao.alistair_fate')
            if fate == 'warden': put('alistair_relationship', 'wardens_together', 'Active Alistair romance; both survive as Wardens')
            elif fate == 'king': put('alistair_relationship', 'mistress', 'Active Alistair romance; king without Warden marriage')
        elif f(2040) is False and f(2041):
            put('alistair_relationship', 'ended', 'Prior Alistair make-love marker with active romance explicitly clear')
        if killer == 'loghain' and ritual is False:
            put('loghain_fate', 'sacrificed', 'Loghain killed the Archdemon without the ritual')
        elif f(2097) and killer is not None and (killer != 'loghain' or ritual is True):
            put('loghain_fate', 'alive_recruited', 'Loghain lives/recruited (2097), without Archdemon sacrifice')
        elif f(2025):
            notes['dao.loghain_fate'] = 'The mapped history records Loghain killed, but the confirmed values do not identify his executioner or distinguish the duel.'

    # This is the relationship at save time, so a platonic answer does not
    # require finishing Origins. Active romance alone cannot distinguish a
    # prior relationship: also inspect the retained cut-off/rejection history.
    alistair = v.plots.get(DIRECT[2040][0])
    if ('dao.alistair_relationship' not in choices and f(2026) is not True
            and all_false((2040, 2041)) and alistair is not None
            and all(not alistair[bit // 32] & (1 << (bit % 32)) for bit in (27, 28, 30, 32, 34))):
        put('alistair_relationship', 'never_lovers',
            'No Alistair marriage/active romance/make-love markers; retained APP cut-off, rejection, backed-out, still-in-love and cannot-restart history (27/28/30/32/34) explicitly clear')

    choose('broken_circle', [(f(2012), 'mages', 'Mages in army 2012'), (f(2013), 'templars', 'Templars in army 2013')])
    choose('orzammar_ruler', [(f(2018), 'bhelen', 'Bhelen 2018'), (f(2019), 'harrowmont', 'Harrowmont 2019')])
    choose('anvil_fate', [(f(2081), 'preserved', 'Branka alive / Anvil preserved 2081'),
                          (f(2082), 'branka_destroyed', 'Branka suicide / Anvil destroyed 2082'),
                          (f(2083), 'warden_destroyed', 'Caridin / Anvil destroyed 2083')])
    if f(2016) and f(2017):
        notes['dao.nature_outcome'] = 'Conflicting werewolf-alliance and Zathrian-sacrifice outcomes.'
    elif f(2017): put('nature_outcome', 'peace', 'Zathrian sacrificed himself (2017); elf-alliance flag can also be set in peace')
    elif f(2016): put('nature_outcome', 'werewolves', 'Werewolf alliance 2016')
    elif completed and f(2015) and all_false((2016, 2017)): put('nature_outcome', 'elves', 'Elf alliance without peace or werewolf alliance')
    if f(2007) and (f(2006) or f(2008)):
        notes['dao.connor_fate'] = 'The history records both Connor freed and Connor executed.'
    elif f(2011) and f(2010) is False:
        put('connor_fate', 'possessed', 'Accepted the Fade demon’s offer (2011); the demon retains its claim on Connor')
    elif f(2007) and (f(2011) is False or f(2010)):
        put('connor_fate', 'freed', 'Connor freed (2007), without accepting the demon’s claim or after intimidating it into release (2010)')
    elif not f(2007) and (f(2006) or f(2008)):
        put('connor_fate', 'dead', 'Isolde kills Connor (2006), or is knocked out before his execution (2008)')
    choose('isolde_fate', [(f(2086), 'sacrificed', 'Jowan blood ritual 2086'),
                           (f(2087), 'alive', 'Circle ritual 2087')])
    if f(2099): put('redcliffe_defense', 'not_helped', 'Redcliffe village abandoned 2099')
    elif f(2098) and f(2099) is False: put('redcliffe_defense', 'helped', 'Redcliffe siege over 2098 without abandonment')
    if f(2037): put('dog_recruited', 'recruited', 'Dog recruited 2037')
    elif completed and f(2037) is False: put('dog_recruited', 'not_recruited', 'Dog recruitment explicitly clear after Origins completion')
    if f(2039): put('zevran_recruited', 'recruited', 'Zevran recruitment 2039')
    elif f(2106): put('zevran_recruited', 'not_recruited', 'Zevran killed before introduction 2106')
    if f(2106): put('zevran_fate', 'dead', 'Zevran killed before introduction 2106')
    elif completed and f(2039) and all_false((2050, 2105, 2106)):
        put('zevran_fate', 'alive', 'Recruited Zevran, Origins completed, no ambush hostility or pre-introduction death')
    choose('architect_fate', [(f(2063), 'killed', 'Architect killed 2063'), (f(2096), 'spared', 'Deal with Architect 2096')])
    if f(2084): put('nathaniel_fate', 'dead', 'Nathaniel died in Vigil’s Keep siege 2084')
    elif f(2091) and f(2065) and f(2084) is False:
        put('nathaniel_fate', 'alive', 'Awakening completed; Nathaniel recruited, without siege death')
    if f(2069):
        if f(2067) and f(2068): put('avernus_fate', 'both_perished', 'Completed Warden’s Keep; Sophia and Avernus killed')
        elif f(2067) is False and f(2068): put('avernus_fate', 'sided_sophia', 'Completed Warden’s Keep; Avernus killed, Sophia spared')
        elif f(2067) and f(2068) is False:
            choose('avernus_fate', [(f(2070), 'unrestricted_research', 'Avernus bad/unrestricted experiments 2070'),
                                    (f(2071), 'ethical_research', 'Avernus ethical experiments 2071')])
            avernus = v.plots.get(DIRECT[2071][0])
            if ('dao.avernus_fate' not in choices and avernus is not None
                    and avernus[0] & (1 << 4)):
                notes['dao.avernus_fate'] = ('Sophia died and Avernus is not marked killed, but neither ethical nor unrestricted research is recorded. '
                    'GWB_AVERNUS_LEAVES (flag 4) is set; that marker alone does not establish the research outcome. '
                    'Choose Avernus’s outcome manually.')
    if f(2076):
        put('shale_recruited', 'recruited', 'Shale follows 2076')
        if completed and f(2077) is False: put('shale_fate', 'alive', 'Shale follows and did not attack, after Origins completion')
    if completed and f(2077) and f(2081): put('shale_fate', 'died_with_branka', 'Shale attacked when the Anvil was preserved with Branka')
    choose('witch_hunt', [(f(2078), 'did_not_follow', 'Morrigan left through eluvian 2078'),
                           (f(2079), 'followed', 'Warden followed Morrigan 2079'),
                           (f(2080), 'stabbed', 'Warden stabbed Morrigan 2080')])
    if 'dao.witch_hunt' not in choices and all_false((2078, 2079, 2080)):
        notes['dao.witch_hunt'] = ('No Witch Hunt ending is recorded: the flags for letting Morrigan leave, '
            'following her through the eluvian, and stabbing her are all clear. '
            'This is separate from the Warden’s romance. Choose the eluvian outcome manually.')
    return choices, evidence, notes

# Direct boolean definitions independently checked against the original GDA.
DIRECT = {
    2000: ('C9736A91F42440758E570D9ECD796597', 0),  # GEN_BACK_CIRCLE
    2001: ('C9736A91F42440758E570D9ECD796597', 1),  # GEN_BACK_DWARF_COMMONER
    2002: ('C9736A91F42440758E570D9ECD796597', 2),  # GEN_BACK_DWARF_NOBLE
    2003: ('C9736A91F42440758E570D9ECD796597', 3),  # GEN_BACK_ELF_CITY
    2004: ('C9736A91F42440758E570D9ECD796597', 4),  # GEN_BACK_ELF_DALISH
    2005: ('C9736A91F42440758E570D9ECD796597', 7),  # GEN_BACK_HUMAN_NOBLE
    2006: ('245482960AA04DB58C90E40C8354B6B5', 20),  # ARL_REMOVE_DEMON_ISOLDE_KILLS_CONNOR
    2007: ('245482960AA04DB58C90E40C8354B6B5', 19),  # ARL_REMOVE_DEMON_CONNOR_FREED
    2008: ('245482960AA04DB58C90E40C8354B6B5', 18),  # ARL_REMOVE_DEMON_ISOLDE_KNOCKED_OUT
    2009: ('245482960AA04DB58C90E40C8354B6B5', 32),  # ARL_REMOVE_DEMON_PC_REFUSED_TO_LET_ISOLDE_KILL_CONNOR
    2010: ('80D1FC2FA12E457896C0F1B64E51EEBC', 17),  # ARL_FADE_DEMON_INTIMIDATED
    2011: ('80D1FC2FA12E457896C0F1B64E51EEBC', 7),  # ARL_FADE_OFFER_ACCEPTED_FROM_DEMON
    2012: ('C232DA078A044178AA9FCBC6E537FA75', 5),  # MAGES_IN_ARMY
    2013: ('C232DA078A044178AA9FCBC6E537FA75', 4),  # TEMPLARS_IN_ARMY
    2014: ('8B254175421D48E1B47FC915E8750228', 3),  # GENITIVI_RETURNS_TO_DENERIM
    2015: ('63DD3FD0AE584D59877B55269963459D', 0),  # NTB_MAIN_ELVES_PROMISED_ALLIANCE
    2016: ('63DD3FD0AE584D59877B55269963459D', 13),  # NTB_MAIN_WEREWOLVES_PROMISED_ALLIANCE
    2017: ('63DD3FD0AE584D59877B55269963459D', 14),  # NTB_MAIN_ZATHRIAN_SACRIFICES_HIMSELF
    2018: ('B571814CBBA44127B605740BD5483A69', 7),  # ORZ_MAIN___PLOT_04_COMPLETED_KING_IS_BHELEN
    2019: ('B571814CBBA44127B605740BD5483A69', 8),  # ORZ_MAIN___PLOT_04_COMPLETED_KING_IS_HARROWMONT
    2020: ('841A4E6E0CDD43D3BA3BA484D9A2771F', 3),  # LANDSMEET_ALISTAIR_ENGAGED_TO_ANORA
    2021: ('841A4E6E0CDD43D3BA3BA484D9A2771F', 1),  # LANDSMEET_ALISTAIR_IS_KING
    2022: ('841A4E6E0CDD43D3BA3BA484D9A2771F', 16),  # LANDSMEET_ALISTAIR_LEAVES_FOREVER
    2023: ('841A4E6E0CDD43D3BA3BA484D9A2771F', 17),  # LANDSMEET_ALISTAIR_KILLED
    2024: ('841A4E6E0CDD43D3BA3BA484D9A2771F', 5),  # LANDSMEET_PLAYER_IS_KING
    2025: ('841A4E6E0CDD43D3BA3BA484D9A2771F', 6),  # LANDSMEET_LOGHAIN_KILLED
    2026: ('841A4E6E0CDD43D3BA3BA484D9A2771F', 56),  # LANDSMEET_ALISTAIR_ENGAGED_TO_PLAYER
    2027: ('841A4E6E0CDD43D3BA3BA484D9A2771F', 4),  # LANDSMEET_ANORA_IS_QUEEN
    2028: ('A5FA53EF3C24463693440319F1D564B2', 2),  # CLIMAX_ARCHDEMON_ALISTAIR_KILLS_ARCHDEMON
    2029: ('A5FA53EF3C24463693440319F1D564B2', 5),  # CLIMAX_ARCHDEMON_LOGHAIN_KILLS_ARCHDEMON
    2030: ('A5FA53EF3C24463693440319F1D564B2', 4),  # CLIMAX_ARCHDEMON_PC_KILLS_ARCHDEMON
    2031: ('7F50C9E955D6461BB34B1A21A88CD4AD', 0),  # EPI_REWARD_CHANCELLOR
    2032: ('7F50C9E955D6461BB34B1A21A88CD4AD', 13),  # EPI_REWARD_CIRCLE
    2033: ('7F50C9E955D6461BB34B1A21A88CD4AD', 8),  # EPI_REWARD_DALISH
    2034: ('C354FB10309D4569A325BD82C047E812', 10),  # POST_MORRIGAN_RITUAL_WITH_ALISTAIR
    2035: ('C354FB10309D4569A325BD82C047E812', 12),  # POST_MORRIGAN_RITUAL_WITH_PLAYER
    2036: ('C354FB10309D4569A325BD82C047E812', 11),  # POST_MORRIGAN_RITUAL_WITH_LOGHAIN
    2037: ('25BC6F5E8DA847938245071233433332', 1),  # GEN_DOG_RECRUITED
    2038: ('25BC6F5E8DA847938245071233433332', 4),  # GEN_LELIANA_RECRUITED
    2039: ('25BC6F5E8DA847938245071233433332', 9),  # GEN_ZEVRAN_RECRUITED
    2040: ('840C666EA1FE48CBA260AB1FE42FCFA7', 21),  # APP_ALISTAIR_ROMANCE_ACTIVE
    2041: ('840C666EA1FE48CBA260AB1FE42FCFA7', 29),  # APP_ALISTAIR_MAKE_LOVE
    2042: ('E8CEBFA6EB2345EBB704DF06D794C803', 21),  # APP_LELIANA_ROMANCE_ACTIVE
    2043: ('E8CEBFA6EB2345EBB704DF06D794C803', 29),  # APP_LELIANA_MAKE_LOVE
    2044: ('919B6591AA754F5E8B871766F25A68AB', 19),  # LELIANA_MAIN_LEAVES_LOTHERING_FOREVER
    2045: ('919B6591AA754F5E8B871766F25A68AB', 41),  # LELIANA_MAIN_ATTACKS_PC
    2046: ('E8E833AC06C04BF2A3261A7937542D75', 21),  # APP_MORRIGAN_ROMANCE_ACTIVE
    2047: ('E8E833AC06C04BF2A3261A7937542D75', 29),  # APP_MORRIGAN_MAKE_LOVE
    2048: ('68F1B23EB3EA42F5B363ABE7FEB86A50', 21),  # APP_ZEVRAN_ROMANCE_ACTIVE
    2049: ('68F1B23EB3EA42F5B363ABE7FEB86A50', 29),  # APP_ZEVRAN_MAKE_LOVE
    2050: ('1763DEA8045E4B1F911B44E51CA314D1', 14),  # ZEVRAN_MAIN_GOES_HOSTILE
    2051: ('1763DEA8045E4B1F911B44E51CA314D1', 38),  # ZEVRAN_MAIN_LEAVES_PARTY_AND_GOES
    2052: ('417FCFECF184466D83210AB7CD9B8077', 23),  # ISABELA_AND_ALISTAIR_THREESOME
    2053: ('417FCFECF184466D83210AB7CD9B8077', 24),  # ISABELA_AND_LELIANA_THREESOME
    2054: ('417FCFECF184466D83210AB7CD9B8077', 26),  # ISABELA_AND_ZEVRAN_THREESOME
    2055: ('417FCFECF184466D83210AB7CD9B8077', 28),  # ISABELA_IN_FOURSOME
    2056: ('417FCFECF184466D83210AB7CD9B8077', 27),  # ISABELA_SLEPT_WITH
    2057: ('A29AAAF18A7A42F38A4A6CED9B689AE5', 0),  # GXA_BACK_ORLESIAN_WARDEN
    2058: ('923E283E44DB4F48BA557085F77D1152', 7),  # VGK_SIEGE___PLOT_09_COMPLETED
    2059: ('1C7395DEAAC14F889A5D41F86854F48B', 7),  # AOA_SIEGE_AMARANTHINE_SAVED
    2060: ('2B2A42D365084FA2A082449D8E397A1C', 3),  # VGK_DEFENSES_ROADS_CHOSEN
    2061: ('2B2A42D365084FA2A082449D8E397A1C', 2),  # VGK_DEFENSES_FARMS_CHOSEN
    2062: ('217BD5BDBB814D2DB41E32F8A05FFC05', 5),  # VGK_HERREN_COMPLETED_SILVERITE
    2063: ('865CD1C26920459CAD2C670099CE8FBE', 3),  # LTM_MAIN___PLOT_03_KILLED_ARCHITECT
    2064: ('E3F7CA9BE9C543378764CD4D5AFC00A3', 6),  # GXA_ANDERS_RECRUITED
    2065: ('E3F7CA9BE9C543378764CD4D5AFC00A3', 9),  # GXA_NATHANIEL_RECRUITED
    2066: ('80370AD2555A4CFDB33A1288F75CFC2D', 13),  # COD_CHA_ANDERS_DIED_IN_VGK_SIEGE
    2067: ('2F247F5F5B1C41F7845E3D09F20D5144', 2),  # GWB_MAIN_SOPHIA_KILLED
    2068: ('2F247F5F5B1C41F7845E3D09F20D5144', 17),  # GWB_MAIN_AVERNUS_KILLED
    2069: ('2F247F5F5B1C41F7845E3D09F20D5144', 13),  # GWB_MAIN_COMPLETED
    2070: ('14D501EF13CE49559111ED9DC9C44457', 5),  # GWB_AVERNUS_DOING_BAD_EXPERIMENTS
    2071: ('14D501EF13CE49559111ED9DC9C44457', 3),  # GWB_AVERNUS_DOING_GOOD_EXPERIMENTS
    2072: ('3647F8987C154EC3879BC9D6C39F0FB9', 5),  # KCC_CAILAN_BURNT
    2073: ('3647F8987C154EC3879BC9D6C39F0FB9', 7),  # KCC_CAILAN_LEFT
    2074: ('3647F8987C154EC3879BC9D6C39F0FB9', 6),  # KCC_CAILAN_WOLVES
    2075: ('028CD0B7B4054E8C8A1C5151DDAEAFB7', 6),  # SHL_LEAVES
    2076: ('028CD0B7B4054E8C8A1C5151DDAEAFB7', 7),  # SHL_FOLLOWS
    2077: ('028CD0B7B4054E8C8A1C5151DDAEAFB7', 8),  # SHL_ATTACKS
    2078: ('731EAE9148E94CE3B80B903A24C46E4A', 0),  # STR_MORRIGAN_LEFT
    2079: ('731EAE9148E94CE3B80B903A24C46E4A', 1),  # STR_MORRIGAN_FOLLOWED
    2080: ('731EAE9148E94CE3B80B903A24C46E4A', 2),  # STR_MORRIGAN_STABBED
    2081: ('86FBBD4CB45D47FF885B0B2BB5407D1E', 4),  # ORZ_ANVIL___PLOT_08_COMPLETED_BRANKA_ALIVE
    2082: ('86FBBD4CB45D47FF885B0B2BB5407D1E', 10),  # ORZ_ANVIL___PLOT_08_COMPLETED_BRANKA_SUICIDES
    2083: ('86FBBD4CB45D47FF885B0B2BB5407D1E', 26),  # ORZ_ANVIL___PLOT_08_COMPLETED_CARIDIN
    2084: ('F29B4323C13049BABE1D2E3007C6AD1D', 12),  # COD_CHA_NATHANIEL_DIED_IN_VGK_SIEGE
    2085: ('5DABBE1A8F3A440592A9F3078D3ABE16', 22),  # GXA_APP_NATHANIEL_FRIENDLY_ELIGIBLE
    2086: ('245482960AA04DB58C90E40C8354B6B5', 21),  # ARL_REMOVE_DEMON_JOWAN_DOES_RITUAL
    2087: ('245482960AA04DB58C90E40C8354B6B5', 28),  # ARL_REMOVE_DEMON_CIRCLE_DOES_RITUAL
    2096: ('865CD1C26920459CAD2C670099CE8FBE', 2),  # LTM_MAIN___PLOT_03_DEAL_WITH_ARCHITECT
    2097: ('841A4E6E0CDD43D3BA3BA484D9A2771F', 8),  # LANDSMEET_LOGHAIN_LIVES
    2098: ('C8BD51CF3BC0414192BFF6BC6BF8247C', 0),  # ARL_SIEGE_SIEGE_OVER
    2099: ('EC0948ED98544E25A47CD6790DA71469', 12),  # ARL_SIEGE_PREP_VILLAGE_ABANDONED
    2100: ('764C8DAFF2274DFEBC7C7B32FA2BB0CD', 2),  # MORRIGAN_RITUAL_WITH_ALISTAIR
    2101: ('764C8DAFF2274DFEBC7C7B32FA2BB0CD', 12),  # MORRIGAN_RITUAL_WITH_LOGHAIN
    2102: ('764C8DAFF2274DFEBC7C7B32FA2BB0CD', 4),  # MORRIGAN_RITUAL_WITH_PLAYER
    2105: ('1763DEA8045E4B1F911B44E51CA314D1', 9),  # ZEVRAN_MAIN_START_AMBUSH_FIGHT_ZEVRAN_ENEMY
    2106: ('1763DEA8045E4B1F911B44E51CA314D1', 34),  # ZEVRAN_MAIN_KILLED_BEFORE_INTRODUCTION
    2107: ('1763DEA8045E4B1F911B44E51CA314D1', 37),  # ZEVRAN_MAIN_LEAVES_AFTER_KISSING_FAREWELL
    2108: ('1763DEA8045E4B1F911B44E51CA314D1', 19),  # ZEVRAN_MAIN_LEAVES_FOR_GOOD
}
