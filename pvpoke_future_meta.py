"""Future meta scenario definitions, tournament observations, and isolated weighting.

Strictly separates observed tournament adoption data from causal hypotheses.
Never sums overlapping observation periods, never treats outside-Top-12 as 0%,
and never fabricates co-occurrence pairs/triples from adoption-rate tables alone.
"""
from __future__ import annotations

import copy
import math
import re
import uuid

MAX_SCENARIOS = 32
MAX_CHAIN_STEPS = 3
MAX_CUSTOM_ENTRIES = 24
SPECIES_RE = re.compile(r"^[a-z0-9_]{1,100}$")

# Exact verified tournament observation snapshots (top-left image dates are authoritative).
# Periods overlap (e.g. 9/8-13 and 9/13-22), so naive summation is strictly prohibited.
OBSERVATION_METADATA = {
    "date_authority": "top_left_image_date",
    "overlapping_periods": True,
    "naive_summation_prohibited": True,
    "outside_top12_is_not_zero": True,
    "cooccurrence_status": "unavailable_without_raw_6mon_rosters",
    "cooccurrence_note": "採用率画像のみではペア・3体共起は算出不可（生の6体ロスターが必要）",
}

OBSERVATION_PERIODS = (
    {"id": "2026-09-08_09-13", "label": "9/8–9/13", "tournaments": 20, "teams": 475},
    {"id": "2026-09-13_09-22", "label": "9/13–9/22", "tournaments": 28, "teams": 640},
    {"id": "2026-09-30_10-14", "label": "9/30–10/14", "tournaments": 19, "teams": 479},
    {"id": "2026-10-15_10-27", "label": "10/15–10/27", "tournaments": 19, "teams": 441},
    {"id": "2026-10-28_11-13", "label": "10/28–11/13", "tournaments": 13, "teams": 200},
)

# None indicates outside the Top-12 table in that period (NOT 0%).
OBSERVED_ADOPTION_SERIES = (
    {"species": "melmetal", "label_ja": "メルメタル", "rates": (50, 55, 34, 43, 46)},
    {"species": "florges", "label_ja": "フラージェス", "rates": (39, 49, 42, 39, 33)},
    {"species": "corsola_galarian", "label_ja": "ガラルサニーゴ", "rates": (47, 47, 33, 26, 18)},
    {"species": "ninetales", "label_ja": "キュウコン", "rates": (45, 33, 23, 22, 20)},
    {"species": "altaria", "label_ja": "チルタリス", "rates": (45, 33, 17, 31, 35)},
    {"species": "quagsire", "label_ja": "ヌオー", "rates": (20, 24, 34, 31, 31)},
    {"species": "sableye", "label_ja": "ヤミラミ", "rates": (25, 27, 31, 27, 23)},
    {"species": "dunsparce", "label_ja": "ノコッチ", "rates": (None, None, 31, 39, 36)},
)

# Unconfirmed qualitative user observations kept strictly separate from measured rates.
UNCONFIRMED_USER_OBSERVATIONS = (
    {
        "id": "obs_shadow_machamp_counter",
        "species": "machamp_shadow",
        "label_ja": "シャドウカイリキー",
        "note": "ユーザー観測：カウンター役として人気（採用率・具体的対策対象は未確認）",
        "adoption_rate": None,
        "counter_targets": "unconfirmed",
        "status": "hypothesis_unconfirmed",
    },
)

BUILTIN_SCENARIOS = (
    {
        "id": "builtin:mimikyu_rise",
        "name": "ミミッキュ普及",
        "kind": "future",
        "builtin": True,
        "revision": 1,
        "summary": "ミミッキュ実装・普及の初期局面を想定（ばけのかわは現行エンジン未検証のためunknown扱い）",
        "weights": {
            "mimikyu": 5.0,
            "melmetal": 4.0,
            "florges": 3.0,
            "altaria": 3.0,
            "dunsparce": 3.0,
            "quagsire": 2.5,
            "sableye": 2.0,
            "corsola_galarian": 1.5,
            "ninetales": 1.5,
        },
        "chain_steps": [
            {
                "stage": 1,
                "kind": "increase",
                "title": "ミミッキュ普及（仮説）",
                "basis": "hypothesis",
                "detail": "新規注目枠としてミミッキュの採用が急増する仮説。ばけのかわは未検証のため勝敗断定せずunknown表示。",
            },
            {
                "stage": 2,
                "kind": "counter_increase",
                "title": "鋼・ノーマル等の既存上位が対抗軸として維持/増加（仮説）",
                "basis": "historical_and_matchup_aux",
                "detail": "実測でも10/28-11/13にメルメタル46%・ノコッチ36%が高水準。ゴースト耐性や鋼打点が注目される仮説。",
            },
            {
                "stage": 3,
                "kind": "adaptation",
                "title": "フェアリー/ドラゴンの配分変化（仮説）",
                "basis": "hypothesis",
                "detail": "フラージェス(39→33%低下傾向)・チルタリス(17→35%回復)など実測推移を踏まえつつ、対策枠との共存を再調整。",
            },
        ],
        "assumptions": [
            "観測データ（9/8–11/13の5期間）と仮説を分離して記録しています。",
            "ミミッキュの「ばけのかわ」は現行エンジン未検証のため、対面結果はunknownとして扱い勝敗を断定しません。",
            "重みは仮説上の重要度であり、実測採用率そのものではありません。",
        ],
        "include_unconfirmed_hypotheses": [],
    },
    {
        "id": "builtin:mimikyu_counters",
        "name": "ミミッキュ対策普及",
        "kind": "future",
        "builtin": True,
        "revision": 1,
        "summary": "ミミッキュ普及に対する対策枠（鋼・ノーマル・カウンター役等）増加と再適応を想定",
        "weights": {
            "melmetal": 5.0,
            "dunsparce": 4.0,
            "quagsire": 4.0,
            "altaria": 3.5,
            "mimikyu": 3.0,
            "florges": 2.5,
            "ninetales": 2.5,
            "sableye": 2.0,
            "corsola_galarian": 1.5,
        },
        "chain_steps": [
            {
                "stage": 1,
                "kind": "increase",
                "title": "ミミッキュ普及後の環境圧力（仮説）",
                "basis": "hypothesis",
                "detail": "ミミッキュの存在を前提に選出・構築が組まれる段階。",
            },
            {
                "stage": 2,
                "kind": "counter_increase",
                "title": "鋼・ノーマル・格闘カウンター役の増加（仮説）",
                "basis": "historical_and_matchup_aux",
                "detail": "実測高水準のメルメタル(46%)・ノコッチ(36%)に加え、ユーザー観測のシャドウカイリキー（採用率・対象未確認）の台頭を検証対象に含む。",
            },
            {
                "stage": 3,
                "kind": "resurgence",
                "title": "鋼/格闘対策の地面・飛行・炎の再増加（仮説）",
                "basis": "historical_and_matchup_aux",
                "detail": "実測でも安定推移のヌオー(31%)・回復中のチルタリス(35%)・キュウコン(20%)など対策の対策が再評価される仮説。",
            },
        ],
        "assumptions": [
            "増加→対策増加→再増加/復活の3段階仮説です。因果関係を実測とは扱いません。",
            "シャドウカイリキーの採用率・対策対象は未確認のため、自動での重み捏造は行わずユーザーが明示的に調整できます。",
            "ミミッキュの「ばけのかわ」は現行エンジン未検証のためunknown扱いとなります。",
        ],
        "include_unconfirmed_hypotheses": ["obs_shadow_machamp_counter"],
    },
)

BUILTIN_SCENARIO_MAP = {item["id"]: item for item in BUILTIN_SCENARIOS}

FORBIDDEN_DUPLICATE_CURRENT_NAMES = frozenset({
    "現行環境維持",
    "現行メタ維持",
    "現行環境",
    "現行メタ",
})


def observation_snapshot() -> dict:
    """Return immutable copy of verified tournament observations & caveats."""
    return {
        "metadata": dict(OBSERVATION_METADATA),
        "periods": [dict(p) for p in OBSERVATION_PERIODS],
        "series": [dict(s, rates=list(s["rates"])) for s in OBSERVED_ADOPTION_SERIES],
        "unconfirmed_observations": [dict(u) for u in UNCONFIRMED_USER_OBSERVATIONS],
    }


def builtin_scenarios() -> list[dict]:
    """Return deep copies of built-in future meta scenarios."""
    return [copy.deepcopy(item) for item in BUILTIN_SCENARIOS]


def validate_weights(weights) -> dict[str, float]:
    """Validate an isolated per-species weight dictionary."""
    if weights is None:
        return {}
    if not isinstance(weights, dict) or len(weights) > 500:
        raise ValueError("シナリオの重要度は最大500種のオブジェクトで指定してください")
    clean: dict[str, float] = {}
    for sid, value in weights.items():
        if (
            not isinstance(sid, str)
            or not SPECIES_RE.fullmatch(sid)
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("シナリオの重要度はポケモンIDと0以上の有限数で指定してください")
        clean[sid] = float(value)
    return clean


def validate_chain_steps(steps) -> list[dict]:
    """Validate causal hypothesis chain (maximum 3 stages)."""
    if steps is None:
        return []
    if not isinstance(steps, list) or len(steps) > MAX_CHAIN_STEPS:
        raise ValueError(f"影響連鎖の仮説は最大{MAX_CHAIN_STEPS}段階です")
    clean = []
    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError("影響連鎖の各段階はオブジェクトで指定してください")
        title = str(step.get("title") or "").strip()
        detail = str(step.get("detail") or "").strip()
        if not title or len(title) > 120 or len(detail) > 500:
            raise ValueError("影響連鎖のタイトル(1〜120文字)と説明(500文字以内)を確認してください")
        kind = str(step.get("kind") or "hypothesis").strip()
        if kind not in ("increase", "counter_increase", "resurgence", "adaptation", "hypothesis"):
            kind = "hypothesis"
        basis = str(step.get("basis") or "hypothesis").strip()
        if basis not in ("observed", "historical_and_matchup_aux", "hypothesis"):
            basis = "hypothesis"
        clean.append({
            "stage": idx,
            "kind": kind,
            "title": title,
            "basis": basis,
            "detail": detail,
        })
    return clean


def validate_scenario_payload(payload: dict) -> dict:
    """Validate and normalize a custom future scenario payload."""
    if not isinstance(payload, dict):
        raise ValueError("シナリオの入力形式が不正です")
    name = payload.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        raise ValueError("シナリオ名は1〜60文字で入力してください")
    name = name.strip()
    if name in FORBIDDEN_DUPLICATE_CURRENT_NAMES:
        raise ValueError("現行メタは基準として既に存在します。変化の対象が分かる未来シナリオ名を付けてください")
    sid = payload.get("id")
    if sid is not None:
        if not isinstance(sid, str) or len(sid) > 64 or sid.startswith("builtin:"):
            raise ValueError("シナリオIDが不正か、組み込みシナリオは直接上書きできません（別名保存してください）")
    else:
        sid = "future:" + uuid.uuid4().hex
    rev = payload.get("revision", 0)
    if type(rev) is not int or rev < 0:
        raise ValueError("シナリオのrevisionが不正です")
    base_meta_id = str(payload.get("base_meta_id") or "legacy").strip()
    if not base_meta_id or len(base_meta_id) > 80:
        raise ValueError("基準メタIDが不正です")
    base_meta_sha256 = str(payload.get("base_meta_sha256") or "").strip()
    if len(base_meta_sha256) > 64:
        raise ValueError("基準メタSHA256が不正です")
    summary = str(payload.get("summary") or "").strip()[:300]
    weights = validate_weights(payload.get("weights"))
    chain_steps = validate_chain_steps(payload.get("chain_steps"))
    assumptions_raw = payload.get("assumptions") or []
    if not isinstance(assumptions_raw, list) or len(assumptions_raw) > 12:
        raise ValueError("仮定メモは最大12件の配列で指定してください")
    assumptions = [str(x).strip()[:300] for x in assumptions_raw if str(x).strip()]
    custom_entries_raw = payload.get("custom_entries") or []
    if (
        not isinstance(custom_entries_raw, list)
        or len(custom_entries_raw) > MAX_CUSTOM_ENTRIES
        or any(not isinstance(x, dict) for x in custom_entries_raw)
    ):
        raise ValueError(f"シナリオ追加候補は最大{MAX_CUSTOM_ENTRIES}件の配列です")
    return {
        "id": sid,
        "revision": rev,
        "name": name,
        "kind": "future",
        "builtin": False,
        "base_meta_id": base_meta_id,
        "base_meta_sha256": base_meta_sha256,
        "summary": summary,
        "weights": weights,
        "chain_steps": chain_steps,
        "assumptions": assumptions,
        "custom_entries": custom_entries_raw,
    }


def resolve_effective_weights(
    scenario: dict | None,
    explicit_weights: dict | None = None,
) -> dict[str, float]:
    """Compute effective per-species weights for a single scenario without double-counting.

    - If scenario is None (current meta baseline), use explicit_weights directly.
    - If scenario is provided, start from scenario['weights'] and apply explicit_weights
      as direct per-species replacement (NEVER multiplying or adding to avoid double-counting).
    """
    base = validate_weights(scenario.get("weights") if scenario else {})
    overrides = validate_weights(explicit_weights)
    merged = dict(base)
    merged.update(overrides)
    return merged
