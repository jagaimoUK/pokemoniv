---
name: iv-selection
description: 「個体値厳選」「個体値厳選 d」「個体値厳選 s」またはポケモンGO PvPの個体値比較では、PvPoke MCPで全対面を計算し、高速一括分析を優先し、種名見出しの複数種・進化形も連続厳選する。S/A候補、重要対面、英語検索式を提示する。
---
# PvPoke 個体値厳選

## 入力を一度で整理する
- MCPを呼ぶ前に本スキルを読む。通常の一括経路は本書だけで実行できる。参照は以下の必要条件に該当するものだけ読み、同じ依頼では再読しない。読めなかったスキルを使用済みと報告しない。
- `個体値厳選` / 独立した `s` / 簡易 → `batch_mode:"simple"`（Default×6条件）。独立した `d` / 詳細 → `"detailed"`（Default/Rank1/Attack/Defense×6＝24条件）。単独d/sは直前の同種・技・IVに限り引き継ぐ。
- CP1500以下・最大Lv50。種ID、通常/shadow、技3つ、攻撃/防御/HPのIV 0〜15を保持。技省略は確認済み同種設定/プリセットを採用し明記、不明なら確認。情報源IVを自動採用しない。
- 種名見出し `#カメール` / `#カメール カメックス` がある場合だけ `references/grouped-ivs.md` を読む。区間IVを列挙された全種へ割り当て、書かれていない進化形を追加しない。同じ種・技・モードの重複IVだけ統合する。技を進化形間でコピーしない。

## 原本照合と一括実行
1. Project原本 `pvpokeメタポケモン.txt` を読み、4列・順序・重複・shadowを保持して正規化SHA256を実際に計算する。UTF-8 BOMと空行を除き、各列の前後空白を除去し、CSV各行をカンマで連結、LFで連結して末尾LFを1つ付ける（サーバーの `pvpoke_meta_sync.serialize` と同じ）。末尾 `-shadow` を取り除く前の原本表記でハッシュする。
2. `run_iv_selection` があれば、**原本の実ハッシュを `expected_meta_sha256` に渡すことでサーバーに照合させる**。事前の `get_meta_status` / catalog / prepare / start / digest の重複照会は不要。サーバーはハッシュ不一致なら計算を開始せず拒否する。不一致時だけ `references/project-meta-batching.md` を読み、原本全体を `sync_meta_opponents` に渡して同期成功を確認し、一括実行を再試行する。開始済みなら再実行しない。
3. `run_iv_selection({candidate,ivs,batch_mode,expected_meta_sha256,focus_opponents,highlight_limit:20,review_limit:8,focus_limit:20,wait_seconds:12})` を1回呼ぶ。現行サーバーは既定で `decision-v2` を返す。新引数がツール一覧に未反映でも既定値で動くため、更新をユーザーに求めず進める。
4. `running` なら同じ `run_ref` で `get_iv_selection_result({run_ref})` を続ける。サーバーは既定最大12秒待って返す。別の待機・get_status・再起動を重ねない。`done` の reportsを検証・評価する。`error`、未知/古いrun_ref、再起動、欠損は簡潔に報告し古いZIPを今回の成果にしない。
5. 複数種は最初の登場順に単一ワーカーで順次実行。各種の根拠の保持・評価・必要な補足取得まで済ませて次へ進む。同じ依頼では原本・実ハッシュを再利用し、毎回runの照合を維持する。途中の「次」要求をしない。
- 実ハッシュを計算できない場合は照合済みと偽らない。既存データに根拠があればexpected引数を省略し、サーバーメタによる計算として区別する。不一致を無視して省略しない。
- 一括ツールが無い/失敗する場合だけ `references/fast-report.md` と必要に応じ `references/mcp-contract.md` を読み、従来のprepare→start1回→状態→digest経路に移る。開始済みジョブを二重起動しない。

## 結果を一度で検証・評価する
- 簡易はreports.default、詳細はdefault/rank1/attack/defenseの全4つ。各complete、candidate_count、opponent_count、condition_count=6、total_ratings_checked=候補×相手×6、excluded、全候補証拠件数を確認する。候補・技・モード・メタハッシュが依頼と一致することを検証する。欠損や除外を黙って隠さない。
- `decision-v1/v2` は **columns配列に対応するrows配列**。`evidence_rows` が全候補の指標、`examples_by_iv` が個体別代表例、`crossover_rows` が境界反転の抜粋。列順を推測せず返却columnsで読む。空のexamples_by_ivは比較信号の例なしであり評価失敗ではない。
- **v2の索引は各report内で0始まり。** `opponent_index` は同reportの `opponents[index]`。境界反転の `above500_candidate_indices` と `best/second/worst_index_rating` の個体indexは `candidate_ivs[index]` に変換する（後者は `[index,Rating]`）。別モードの辞書を流用しない。ranking/evidence/examplesのIVは従来どおり文字列。
- v2の `tradeoff_rows` は **candidate_ivsと同じ順序で全候補を収録**。columnsに従い、lower_than_best＝その対面の最高候補より低い条件数、lost_gt500＝自分500以下・他候補500超の条件数。exampleはtradeoff_example_columnsで読み、具体的な損失と代替IVに使う。比較相手のbest_ivは対面ごとに変わるため完全支配とは別物。代表例は1つの抜粋であり、nullも弱点ゼロを意味しない。S/Aや順位は自動確定しない。
- v1の相手名と境界反転IVは文字列。`ranking_rows`、`dominated_by`、focusの `by_iv` はv1/v2共通。focusはv2だけ相手名をopponent_indexで参照する。
- 旧形式は `candidate_evidence` と `priority_crossovers`。どちらも全候補・同一相手・同一IVモード・同一シールドで比較する。形式変換のためだけに別レポートを取得しない。
- `unique_gt500`＝他候補すべて500以下でその個体だけ500超、`clear_leads`＝次点より20以上高い条件。focus / disadvantage内訳、strict_leads、examples_total / examples_truncatedを全候補で確認する。指標は採用価値の発見用であり自動S/Aではない。Rating500超は勝利方向の推定で正式な勝数ではない。
- 平均だけで決めず、重要メタ、500境界逆転、不利シールド、安定性、代替不能な役割を評価する。全条件で他候補以上かつ1条件で上なら完全支配。完全同値は同等。低平均・review_ivs外・新指標ゼロだけで落とさない。詳細のモード間の強みと損失も照合する。
- ユーザーが先頭/裏/苦手を指定したら優先する。「強い個体」は先頭メタの裏に来る相手へ互角以上に対応する個体。指定がなければ差が大きい収録相手を重視し、使用率を推測で断定しない。
- S候補＝重要対面の独自改善、または重要対面と不利条件を横断する強みを持つ非支配の第一候補。A候補＝有力代替または用途限定の独自役割。根拠不足は暫定/保留。推薦数の上限・最低件数は設けない。
- **抜粋フラグがtrueという理由だけで追加照会しない。** 既存例・境界反転・focusの実測値で採用根拠とトレードオフを説明できれば回答する。未収録の重要対面が推薦・説明を変え得る場合だけ `get_selection_report` / `get_results` を必要範囲で補足取得する。focusに載るのはreview候補のみなので全候補の対面網羅と誤認しない。必要な精査には `references/evaluation.md` を読む。

## 最終回答
- 通常の厳選は、種ごとのおすすめ全個体と個別英語検索式だけ。前置き、件数、ツール状況、比較表、時間、独立した結論、末尾の提案は省く。実行失敗・欠損・重大な根拠不足のみ短く報告。ユーザーの追加出力指定は優先する。
- 各個体を `1位｜0/11/12｜S候補｜重要メタ対応型` の独立見出し、1〜2文の具体的な相手・シールド・Rating根拠、その直下の検索式コードブロックの順で表示する。CP/Lvは確認済みのみ記載する。実測例を流用せず、取得した数値で説明する。
- 検索式 `EnglishSpecies&Nattack&Ndefense&Nhp`。IV区分：0→0、1〜5→1、6〜10→2、11〜14→3、15→4。shadowなら `&shadow`。日本語・図鑑番号・+・星評価・不要な条件を付けない。種名の英語表記が不明/特殊なら `references/search-strings.md` を読む。
- CSV成果物は明示要求時のみ。内部CSV/ZIP・既存結果は保持する。表示を省略しても全件検証・全候補比較を省略しない。

## 計測（開発時だけ）
- 応答のtimingはサーバー受付→結果とZIP解析の時間。GPTの評価・最終返答・通信時間を含まない。全体比較は同じ候補・技・メタ・モード・モデル/思考量で、呼び出し回数・データ量・新規/キャッシュを記録して行う。通常回答に計測値を出さない。
