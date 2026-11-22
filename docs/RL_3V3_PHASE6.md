# Phase 6 — 3対3と6-3選出の学習環境

[Draft PR #123](https://github.com/jagaimoUK/pokemoniv/pull/123) の
`1f7fc5a852a11fe1d6f40138d9375ab20a89740f` を起点とする。ベースは
[PR #122](https://github.com/jagaimoUK/pokemoniv/pull/122) の `a41f8b40`。
そのベースは [PR #117](https://github.com/jagaimoUK/pokemoniv/pull/117) の `429510d`。

## ローカルの学習インターフェース

`pvpoke_rl_team_env.py` の `SixToThreeEnvironment` は、既存の
`SixToThreeSelection` と同じ6体の入力を受け取る。相手側の選出3体と先発は、
評価側から事前に渡す。選出側の方策に渡す値は `observation` だけにする。
対戦だけを実行する場合は、先発を先頭に並べた既存の内部ハンドオフを
`ThreeVThreeEnvironment.reset(handoff, seed=...)` に渡す。

```python
from pvpoke_rl_team_env import SixToThreeEnvironment

with SixToThreeEnvironment(
    gamemaster_path, own_six, opponent_public_six, opponent_private_six,
    opponent_chosen_three, opponent_lead, ruleset_id="great-league-v1",
) as env:
    observation, info = env.reset(seed=12)
    while observation is not None:
        action = policy(observation)
        observation, reward, terminated, truncated, info = env.step(action)
    if terminated and info["training_eligible"]:
        # 終端の reward を戦術の軌跡に、同じ勝敗の selection_reward を選出に渡す。
        record_completed_match(reward, info["selection_reward"])
```

`observe()` は現在の観測のコピーを返す。`legal_actions()` はその時点で選べる
行動を返す。6-3の最初の行動は `0,1,4|4` のような「3枠|先発枠」で、合計60通り。
対戦に入ると `turn`、`shield`、`replace` の各フェーズの行動に切り替わる。
途中の報酬は `None`。全滅で決着した場合は勝ちが `1`、負けが `-1`、
双方全滅が `0`。時間切れ・未対応の終端は報酬が `None` で、学習対象外。
不正な入力やワーカー障害は例外となり、勝敗を生成しない。

対戦方策には、自分の3体・選択肢と、相手の場に出た種、HPの5%刻みの表示、
共有シールド、実際に公開された技だけを渡す。ゲージ技の告知時点では技名を伏せ、
シールドの意思決定後に解決イベントとして公開する。CPUも自分側から見た同じ形式の
観測で、技・交代・シールドを選ぶ。CPUは学習済みモデルを必要としない固定ルール。

`private_replay()` は評価側専用。選出、両者の初期編成、ゲームデータの SHA-256、
乱数seed、乱数の抽選、双方の行動、公開イベント、最終リソースを含む。
同じコミット・同じデータを用い、`tests/test_rl_team_native.cjs` の例と同様に
`createTeamSession()` へ初期条件を渡し、`decisions[].actions` を順に適用すると
再生できる。この記録には非公開の選出・技・個体値が含まれるため、
方策・観測のログ・外部送信の入力には含めない。

## 計算の範囲

- CP1500以下、レベル50以下かつ種族別のレベル制約内、通常技1つ・ゲージ技2つの
  PvPoke準備済み編成が対象。`ruleset_id` は出所を識別するラベル。
  特殊カップの種族可否は編成を準備する側で検証する。
- ダメージ・エネルギー・シールドによる減算・能力変化・技の待ち行列は
  固定した PvPoke `Battle.js` を使用する。3対3だけで同値CMPの乱数、
  シールド入力での中断・再開、ゲージ技直後の通常技着弾と交代の優先順を有効にする。
  HPとエネルギーは個体に残り、能力変化をリセットし、シールドはチームで共有する。
- この環境の時計は通常ターン500 ms、ゲージ技1回10秒、交代45秒、
  バトル240秒。強制交代は入力後に時計を進めず処理する。時間内に解決できない
  ゲージ技は勝敗に使わない。実通信での入力窓、強制交代画面での待機、
  時間切れの実機判定、ゲージ技のチャージ量はこのモデルの検証範囲外。
- 動的フォーム、Minior、メガ、通常の処理順を飛び越える特殊技は、
  その個体が出場した時点または技が解決される時点で `unsupported` となる。
  同値CMPと確率効果はseedで再現する。実機での確率や入力タイミングへの一致は未確認。
- 既存のダメージ計算の挙動は同じ。変更したJSを含む計算のフィンガープリントは
  更新されるため、過去の直接計算キャッシュは初回に再計算され得る。

## Antigravityでの独立レビュー

PR #123 の Phase 6 コミットをチェックアウトし、Node 22 と Python 3.12 で実行する。

```sh
node tests/test_rl_team_native.cjs
PYTHONPATH=.:tests python -m unittest test_rl_team_env test_rl_team_preview \
  test_rl_stateful_native test_rl_step_client test_rl_replay_env test_observed_v2_native test_sandbox
python -m unittest discover -s tests -p 'test*.py'
```

1. `Battle.js` の準備処理からシールド決定まで追い、停止・再開で技の投入、
   経過時間、シールド消費が二重にならないことを確認する。異なる攻撃実数値での
   CMP、同値CMP、双方の通常技KO、同発後手のキャンセルを再確認する。
2. 交代前後のHP・エネルギー・能力変化・残りシールド・時計を追う。
   ゲージ技直後の着弾、交代予定の個体が倒れたケース、両者同時の強制交代を確認する。
3. 片側の控え、技、個体値だけを差し替え、公開状態が同じ間の観測とCPUの行動を比較する。
   `team_replay` の結果が選出・戦術方策に渡らないことを確認する。
4. 同じワーカーで複数の対戦をリセットしながら実行し、プロセス再利用、終了後の
   行動拒否、同じseed・行動での再生、タイムアウト時の学習除外を確認する。
5. 既存1対1・Sandbox・個体値厳選の回帰と、Phase 6 コミットに対応する
   GitHub Actions の結果を確認する。

レビュー結果には対象コミット、再現できた範囲、阻害事項を記録する。
