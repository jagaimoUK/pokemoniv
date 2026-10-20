"""Rules for translating an inventory form into a supported PvP starting form.

Only explicitly verified battle-entry transitions belong in this table.
Never collapse other forms or regional variants through name similarity.
"""
BATTLE_ENTRY_FORMS = {
    "minior_core": "minior_meteor",
}


def battle_entry_species(species_id: str, species: dict | None = None) -> str:
    """Use Meteor for a Core-form Minior at battle start (experimental CP model)."""
    target = BATTLE_ENTRY_FORMS.get(species_id, species_id)
    if species is not None and target not in species:
        raise ValueError(f"{species_id}: 対戦開始フォルム {target} がゲームデータにありません")
    return target


def battle_entry_notice(species_id: str) -> str | None:
    if species_id == "minior_core":
        return ("メテノ（コア）を読み取りました。対戦計算は流星フォルムから開始し、"
                "HP50%未満でコアに変化します。CP・レベルの扱いは試験的な近似です")
    return None
