# 第22工程：未学習の「待機」が負の経験より優先される仮説の検証

## 既存v2学習器で確認した事実（変更前）

PR #123 / `ef5c80feede34c4c12893a58459ee1cf81cc4027` の CIは8/8成功、Python回帰784件成功。

前工程と同じ、新しい合成holdout6条件。学習12試合、評価時の自己3体と先発は両方の方策で統一した。

| 選出 | 学習済みv2完走 | 正/負/未観測の選択判断 | 通常技が使えるのにwait |
|---|---|---|---:|
| `2,3,5\|2` | 6/6、4勝2敗 | +158 / -15 / 未観測638 | 3回 |
| `0,4,5\|4` | 5/6、0勝5敗 | +0 / -74 / 未観測768 | 62回 |

「負」は個々の行動が悪いと証明された意味ではない。現在の`first-visit Monte Carlo`は、試合完走時の結果(-1/0/+1)を同試合中に選んだ各state/actionへ与えるため、チームや対面全体の強弱が行動値に混じる。また、未観測actionの暫定期待値は0であり、負の経験を持つfastより未観測のwaitが高くなる場合がある。

**上記数値だけでは62回のwaitが敗北の直接原因だとは断言できない。** 攻撃可能時の意図的待機が有用な戦術である場合もある。

## 今回の実験用方策（本番未導入）

`tools/rl_wait_guard.py` の`GuardedWaitMonteCarloPolicy`はv2の公開状態キーとチェックポイントをそのまま使用する。新しい学習スキーマは発行せず、トレーニング自体は**元のv2で一度だけ**行う。

- 評価時 `epsilon=0`、`tactics`局面で`fast`または`charge_*`が合法であり、`wait`に**正の既学習平均値がない**場合に限り、当該一判断の候補から`wait`を除く。
- `wait`しか合法でない強制待機は許可。既学習で平均報酬が正の`wait`は選択候補に残す。学習探索 `epsilon>0` はv2と同一。
- 状態キーは**常に元の完全な合法行動集合から作ったv2キー**を使う。候補からwaitを除いてもモデルキーは変えず、学習済み重みやstate/action記録を改変しない。
- `tools/evaluate_rl_mc.py` はオプションの第四方策 `guarded` を既存の`fixed/untrained/trained`へ追加できるようにし、同一選出、同一初期seedと相手シナリオで対応付き比較。`guarded_vs_trained`と`guarded_vs_untrained`の双方完走分母を明記する。
- `tools/evaluate_rl_fresh_holdout.py --guarded-ablation`を指定したときだけ第四方策を評価し、同じ学習済みモデルを別インスタンスへ復元する。従来の実験CLIはデフォルトでv2のみのまま。
- 評価中はtrained/guardedともチェックポイントが不変であることを検証する。

実行コマンド:

```bash
PYTHONPATH=.:tests python -m unittest test_rl_wait_guard test_rl_fresh_holdout test_rl_mc_evaluation
PYTHONPATH=.:tests python tools/evaluate_rl_fresh_holdout.py --policy v2 --train 12 --evaluate 6 --seed 12 --guarded-ablation
```

## 成功・失敗の解釈

このガードを適用しても**勝率が必ず改善するとは限らない**。通常技と待機以外の行動、shield、相手CPU、合成チームの強弱などが結果に影響する。

有用な観察項目:
- 元のv2とguardedの完走数、timeout数
- 双方正常終了のエピソード数、guardedの勝/同/負の報酬比較
- `public_wait_reasons.fast_available_when_waiting`、学習済みstate/action再利用と評価値の符号
- 同じcheckpointと公開状態キーを使ったこと

同じ初期シードであっても、異なる行動はネイティブ乱数の消費順を変えうる。結果差はこの小標本だけでは因果効果や実戦性能を保証しない。また2編成は先行合成試験の結果から探索的に選ばれたため、独立した競技評価ではない。

悪化を減らせる傾向が出た場合でも、新しいseed・別編成の確認と、待機が戦術上有利な状況に対する負の影響の検証が必要。未確認ならアルゴリズムを本番導入しない。

ChatGPT接続PvPoke MCPは不使用。PvPoke/Battle.js、試合時間、報酬、モデルcheckpoint仕様、実サービス、DB、設定、既存機能は変更していない。PR #123はDraftのままで、merge/deployは未実施。
