"""Select PvPoke opponent IV presets for Great League using GameMaster data."""

import math

AUTO_IV_MODES = ("default", "rank1", "attack", "defense")
MANUAL_IV_MODES = ("source", "custom")
IV_MODES = MANUAL_IV_MODES + AUTO_IV_MODES


def _levels(pokemon, cpms, level_cap):
    highest = min(float(level_cap), float(pokemon.get("levelCap") or level_cap))
    lowest = max(1.0, float(pokemon.get("levelFloor") or 1))
    choices = [
        (half / 2, float(cpms[half - 2]))
        for half in range(math.ceil(lowest * 2), math.floor(highest * 2) + 1)
        if 0 <= half - 2 < len(cpms)
    ]
    if not choices:
        raise ValueError("選択可能なレベルがありません")
    return choices


def _cp(base, cpm, atk, defense, hp):
    return max(10, math.floor(
        (base["atk"] + atk) * math.sqrt(base["def"] + defense) *
        math.sqrt(base["hp"] + hp) * cpm ** 2 / 10
    ))


def select_opponent_ivs(pokemon, cpms, mode, moves=(), cp_cap=1500, level_cap=50):
    """Return (attack_iv, defense_iv, hp_iv, level_override).

    default: GameMaster's exact cp1500 preset including its stored level.
    rank1: max stat product; attack and defense maximize each actual stat.
    Follows PvPoke's IV floors, level cap and stable IV tie order.
    """
    if mode not in AUTO_IV_MODES:
        raise ValueError("自動個体値モードは default / rank1 / attack / defense です")

    levels = _levels(pokemon, cpms, level_cap)
    base = pokemon["baseStats"]

    if mode == "default":
        preset = (pokemon.get("defaultIVs") or {}).get("cp1500")
        if not isinstance(preset, (list, tuple)) or len(preset) != 4:
            raise ValueError(f'{pokemon["speciesId"]}: PvPokeデフォルト(cp1500)が未登録です')
        level = float(preset[0])
        ivs = tuple(int(x) for x in preset[1:])
        valid_level = next((cpm for lv, cpm in levels if abs(lv - level) < 0.001), None)
        if valid_level is None or any(not 0 <= x <= 15 for x in ivs):
            raise ValueError(f'{pokemon["speciesId"]}: デフォルト個体値・レベルが無効です')
        if _cp(base, valid_level, *ivs) > cp_cap:
            raise ValueError(f'{pokemon["speciesId"]}: デフォルトCPが{cp_cap}を超えています')
        return (*ivs, level)

    tags = set(pokemon.get("tags") or ())
    floor = 0
    if ("legendary" in tags or "ultrabeast" in tags) and "wildlegendary" not in tags:
        floor = 1
    if ("legendary" in tags or "ultrabeast" in tags) and (
        "shadow" in tags or pokemon["speciesId"].endswith("_shadow")
    ):
        floor = 6
    if "untradeable" in tags:
        floor = 10
    if "RETURN" in moves:
        floor = 2

    best, best_score = None, -1.0
    # PvPoke enumerates HP, DEF and ATK in descending IV order.
    for hp in range(15, floor - 1, -1):
        for defense in range(15, floor - 1, -1):
            for attack in range(15, floor - 1, -1):
                lo, hi, selected = 0, len(levels) - 1, -1
                while lo <= hi:
                    mid = (lo + hi) // 2
                    if _cp(base, levels[mid][1], attack, defense, hp) <= cp_cap:
                        selected = mid
                        lo = mid + 1
                    else:
                        hi = mid - 1
                if selected == -1:
                    continue
                level, cpm = levels[selected]
                actual_atk = (base["atk"] + attack) * cpm
                actual_def = (base["def"] + defense) * cpm
                actual_hp = max(10, math.floor((base["hp"] + hp) * cpm))
                if pokemon.get("dex") == 292:
                    actual_hp = 10
                if mode == "rank1":
                    score = actual_atk * actual_def * actual_hp
                elif mode == "attack":
                    score = actual_atk
                else:
                    score = actual_def
                if score > best_score:
                    best, best_score = (attack, defense, hp, level), score
    if best is None:
        raise ValueError(f'{pokemon["speciesId"]}: CP{cp_cap}以下に適合する個体値がありません')
    return best
