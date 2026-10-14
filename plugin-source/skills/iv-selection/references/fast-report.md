# PvPoke高速分析ツール（2026-10-14追加）

- 本番MCPで `get_selection_report` が見えている場合だけ使用する。ツール一覧への反映はMCP接続の更新を要することがある。
- 例：`get_selection_report({"mode":"default","focus_opponents":["Corsola","Tinkaton","Clodsire","Corviknight"],"max_flips":120})`。
- `mode`：`default`、`rank1`、`attack`、`defense`。簡易はDefault1回、詳細は4回。各呼び出しは6シールド条件すべてを1回のZIPダウンロードから検証する。
- `rankings`：全候補の平均Rating・等シールド平均・不利シールド平均・500超の対面数など。正規の勝利数ではない。
- `crossovers`：同じ相手・シールドで候補同士のRatingが500の境界を横切る差を、重要度と差の大きさで整列して返す。`crossovers_total` と `crossovers_returned` を必ず確認し、切り捨てられた時は根拠として未取得部分を扱わない。
- `focus_matchups`：名前部分一致（最大15語）で指定した相手の全候補×全6条件Rating。収録構成が複数なら別対面として扱う。
- `complete`、`candidate_count`、`opponent_count`、`total_ratings_checked`を検査し、異なる相手順序、候補欠損、無効Ratingなどのエラーでは評価を中止し従来ツールで点検する。
- `get_selection_report`は既存のバトル計算を省略せず、既存ZIPだけを分析する。`get_results`は引き続き利用可能。サービスの `done` を確認する前に結果を取得しない。
- ツールが非表示／失敗の場合は従来の `get_24_summary`と `get_results(mode,shield,offset,limit<=20)` を使用して不足条件を回収する。

## コンパクトダイジェスト（第2段階）
- `get_selection_digest({"mode":"default","focus_opponents":["Corsola","Tinkaton","Clodsire","Corviknight","Feraligatr","Melmetal"],"highlight_limit":20,"review_limit":8,"focus_limit":20})`。簡易1回、詳細は各IVモード1回で計4回。
- `complete:true` は6条件CSVの欠損、候補順、相手順、Ratingの妥当性を確認できたこと。`total_ratings_checked` は全候補×メタ構成×6と一致しなければならない。`excluded`も確認。
- `ranking_columns` に対応する `ranking_rows` は**全候補**の圧縮表。`dominated_by` は全Ratingの同条件比較で他個体に完全支配される候補の辞書。`review_ivs` は検討候補を選ぶアルゴリズム上の補助指標で、S/Aランクではない。
- `priority_crossovers` は `crossovers_total` 中の最大 `highlight_limit` 件、`focus_matchups` は `focus_matchups_total` 中の最大 `focus_limit` 技構成・`review_ivs`の個体のみ。欠けた対面・候補を『対面不存在』『互角未満』と断定しない。
- `crossovers_truncated` または `focus_matchups_truncated` がtrueで、重要対面や採否判断に必要な根拠が欠けるなら、旧 `get_selection_report` または `get_results` を追加取得する。必要なら元のZIPも保持される。
- サーバーは対戦を再計算せず、ZIPを解析・縮約するだけ。Rating由来の>500とPvPoke勝敗カウンターを混同しない。GPTは重要対面の文脈で推薦を作成する。
- 本番MCPの接続に新ツールが公開されていない場合は、従来の `get_selection_report` にフォールバックする。スキルの更新だけではツール一覧の即時更新は保証されない。

## 一括実行のMCPツール
- `run_iv_selection({candidate:{species,fast,charged1,charged2},ivs:"0,11,12\n2,15,13",batch_mode:"simple",expected_meta_sha256:"Project実ハッシュ",focus_opponents:["Corsola","Tinkaton"],highlight_limit:20,review_limit:8,focus_limit:10,wait_seconds:12})` は既存 `/api/run24` の検証とジョブ開始を一回で行い、最大20秒まで待機（既定12秒）。対象の `run_ref` を返す。
- 計算済みで `state:"done"` なら ZIP照合後 `reports` にcompact digestを返す。遅ければ `state:"running"` の `run_ref` に `get_iv_selection_result({run_ref})` を繰り返す。相手IV4モードの詳細は一回のZIPで4レポートを取得する。
- 実行途中に新たな `run_iv_selection` を送らない。`get_iv_selection_result` は記録されたジョブ時刻とバッチモード、保存ZIPのポケモンID・技・全IVを照合し、古い結果混入を拒否する。サーバー再起動後の古いrun_refも使わない。
- `expected_meta_sha256` を渡す場合は厳選Project原本から正しく計算・照合したSHA256に限る。未照合の場合は省略して自動同期済みと主張しない。必ず原本読み込み→同期確認を優先する。
- `get_selection_digest` / `get_selection_report` / `get_results` は重要対面・Ratingの補足取得とフォールバックに残す。S/Aを自動確定せず、ユーザーの先頭・裏ポケモン想定で評価する。


## v0.3.20 の応答と待機
- 一括ツールの既定はdecision-v2。全候補の指標・代表例・境界反転を保持し、相手名と境界反転のIVを各reportの0始まり索引へ圧縮する。解釈はSKILL.mdのv2手順に従う。全候補のトレードオフもアプリが集計する。report_format:"decision-v1"または"compact"で以前の形式を指定できるが、形式変更だけの再計算はしない。get_selection_digestは旧形式を維持する。
- get_iv_selection_resultは既定最大12秒の待機、公開済み引数wait_seconds:0〜20で変更可能。同じrun_refの完成レポートはメモリ内再利用するが、毎回ジョブ同一性を照合する。別ジョブや再起動後への再利用はしない。
- 原本実ハッシュをrun_iv_selectionに渡せるなら事前get_meta_statusを省略できる。サーバー照合が失敗した場合のみ原本同期し再試行する。
