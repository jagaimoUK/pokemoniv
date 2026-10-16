"""Compact, catalog-unique ASCII labels for GO nicknames (four characters max)."""
import itertools
import re
import unicodedata

# Familiar compact labels, including adjacent evolution stages.
PREFERRED = {'quagsire': 'Quag', 'corviknight': 'Cor', 'feraligatr': 'Fer',
             'swadloon': 'Swd', 'leavanny': 'Lea', 'swampert': 'Swa',
             'nacli': 'Ncl', 'naclstack': 'Nst', 'garganacl': 'Gag',
             'squirtle': 'Sqt', 'wartortle': 'Wrt', 'blastoise': 'Bls',
             'bulbasaur': 'Bul', 'ivysaur': 'Ivy', 'venusaur': 'Ven'}
FORM_JA = {'Shadow': 'シャドウ', 'Galarian': 'ガラル', 'Alolan': 'アローラ',
           'Hisuian': 'ヒスイ', 'Paldean': 'パルデア', 'Mega': 'メガ',
           'Male': 'オス', 'Female': 'メス', 'Shield': 'シールド', 'Blade': 'ブレード',
           'Attack': 'アタック', 'Defense': 'ディフェンス', 'Speed': 'スピード',
           'Normal': 'ノーマル', 'Altered': 'アナザー', 'Origin': 'オリジン',
           'Plant': 'くさき', 'Sandy': 'すなち', 'Trash': 'ゴミ',
           'Full Belly': 'まんぷくもよう', 'Hangry': 'はらぺこもよう',
           'Hero': 'れきせんのゆうしゃ', 'Crowned Sword': 'けんのおう',
           'Crowned Shield': 'たてのおう', 'Average': 'ふつう', 'Large': 'おおきい',
           'Small': 'ちいさい', 'Super': 'とくだい', 'Standard': 'ノーマル',
           'Combat': 'コンバット', 'Blaze': 'ブレイズ', 'Aqua': 'ウォーター',
           'Incarnate': 'けしん', 'Therian': 'れいじゅう', 'Zen': 'ダルマモード',
           'Primal': 'ゲンシ', 'Overcast': 'ネガ', 'Sunshine': 'ポジ',
           'Land': 'ランド', 'Sky': 'スカイ', 'Midday': 'まひる',
           'Midnight': 'まよなか', 'Dusk': 'たそがれ',
           'Sunny': 'たいよう', 'Rainy': 'あまみず', 'Snowy': 'ゆきぐも'}


# Short labels are joined directly to an A/S grade in GO nicknames.
# Validate the composed prefix too: A + Nal becomes the rejected word ANal.
# This is a conservative local screen, not an official exhaustive GO word list.
BLOCKED_NICKNAME_FRAGMENTS = ('anal', 'ass', 'bitch', 'cunt', 'dick',
                              'fuck', 'nazi', 'porn', 'sex', 'shit', 'slut')


def safe_nickname_fragment(code):
    return all(not any(term in (grade + code).casefold()
                       for term in BLOCKED_NICKNAME_FRAGMENTS)
               for grade in ('', 'A', 'S'))


def japanese_form_suffix(suffix):
    for en, ja in sorted(FORM_JA.items(), key=lambda x: -len(x[0])):
        suffix = re.sub(r'\b' + en + r'\b', ja, suffix)
    return suffix


def assign_nickname_codes(payload):
    """Unique across the whole active catalog, not just the displayed batch.

    Prefer recognizable name fragments. The numeric fallback is only for
    exceptionally dense/custom catalogs; never silently reuse a form's code.
    """
    used = set()
    for sid in sorted(payload, key=lambda s: ('_' in s, s not in PREFERRED, s)):
        entry = payload[sid]
        base = sid.split('_')[0]
        letters = re.sub('[^a-z]', '', unicodedata.normalize('NFKD', base).lower()) or 'pkm'
        parts = sid.split('_')[1:]
        suffix = ''.join({'shadow': 's', 'galarian': 'G', 'alolan': 'A',
                          'hisuian': 'H', 'paldean': 'P', 'mega': 'M',
                          'male': 'm', 'female': 'f',
                          'small': 'X', 'average': 'M', 'large': 'L', 'super': 'Z'}.get(x, x[:1].upper()) for x in parts)
        suffix = suffix[:2]
        limit = 4 - len(suffix)
        preferred = PREFERRED.get(base, letters[:3].capitalize())
        def options():
            yield preferred[:limit] + suffix
            for width in (min(3, limit), limit):
                for indices in itertools.combinations(range(1, len(letters)), width - 1):
                    yield (letters[0] + ''.join(letters[i] for i in indices)).capitalize() + suffix
            for n in range(10000):
                yield letters[0].upper() + str(n)
        code = next(c for c in options() if 1 <= len(c) <= 4 and c.casefold() not in used
                    and safe_nickname_fragment(c))
        used.add(code.casefold())
        entry['nickname_code'] = code
