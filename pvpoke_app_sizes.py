"""Explicit GO/PvPoke size forms for Pumpkaboo and Gourgeist.

The four varieties are different battle species, not cosmetic height tags.
Keep all aliases tied to a real form ID; never guess a bare species.
"""
FAMILIES = {"pumpkaboo": "バケッチャ", "gourgeist": "パンプジン"}
FORM_INFO = {
    "small": ("こだましゅ", "XS", ("こだましゅ", "コダマシュ", "小玉種", "ちいさいサイズ", "小さいサイズ", "small", "small size", "small variety", "xs")),
    "average": ("ちゅうだましゅ", "通常", ("ちゅうだましゅ", "チュウダマシュ", "中玉種", "ふつうサイズ", "ふつうのサイズ", "普通サイズ", "average", "average size", "medium", "medium size", "medium variety", "normal", "standard", "m")),
    "large": ("おおだましゅ", "XL", ("おおだましゅ", "オオダマシュ", "大玉種", "おおきいサイズ", "大きいサイズ", "large", "large size", "large variety", "xl")),
    "super": ("ギガだましゅ", "XXL", ("ぎがだましゅ", "ギガだましゅ", "ギガダマシュ", "ギガ玉種", "とくだいサイズ", "特大サイズ", "super", "super size", "jumbo", "jumbo variety", "xxl")),
}


def pumpkin_form(sid):
    """Return (English species, Japanese species, variety) for real form IDs."""
    if not isinstance(sid, str):
        return None
    base, sep, variety = sid.partition("_")
    if sep and base in FAMILIES and variety in FORM_INFO:
        return base.capitalize(), FAMILIES[base], variety
    return None


def pumpkin_aliases(sid):
    form = pumpkin_form(sid)
    if not form:
        return []
    english, japanese, variety = form
    words = FORM_INFO[variety][2]
    result = []
    for root in (japanese, english):
        for word in words:
            result.extend((root + " " + word, root + "(" + word + ")",
                           root + word))
            if root == japanese:
                result.append(root + "の" + word)
    return list(dict.fromkeys(result))


def pumpkin_display_name(sid):
    form = pumpkin_form(sid)
    if not form:
        return None
    _, japanese, variety = form
    word, size, _ = FORM_INFO[variety]
    return japanese + "(" + word + "・" + size + ")"


def pumpkin_search(sid):
    """Use GO's size search instead of an unsearchable PvPoke form suffix.

    Normal size has no positive GO keyword, so exclude every special size.
    """
    form = pumpkin_form(sid)
    if not form:
        return None
    english, _, variety = form
    filter_by_form = {"small": "&xs", "average": "&!xxs&!xs&!xl&!xxl",
                      "large": "&xl", "super": "&xxl"}
    return english, filter_by_form[variety]
