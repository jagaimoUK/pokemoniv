---
name: iv-selection
description: 「個体値厳選」「個体値厳選 d」「個体値厳選 s」またはポケモンGO PvPの個体値比較では、PvPoke MCPで全対面を計算し、高速一括分析を優先し、種名見出しの複数種・進化形も連続厳選する。S/A候補、重要対面、英語検索式を提示する。
---

# PvPoke 個体値厳選（高速分析対応）

## 自動起動とモード
- 「個体値厳選」およびポケモンGO PvP個体値比較では、PvPoke MCPを呼ぶ**前**に本スキルと必要な参照文書を読む。読み込みに失敗したら使用済みと主張しない。
- 指定なし・`s`・「簡易」は `batch_mode:'simple'`：相手Default IV× S0/S1/S2/i0y1/i0y2/i1y2＝6条件。
- `d`・「詳細」は `batch_mode:'detailed'`：Default/Rank1/Attack/Defense各6条件＝24条件。英字1文字は独立した行・空白区切りの指定としてのみ扱う。`d`と`s`はMCPにそのまま送らずフルIDに変換する。
- 単独 `d`/`s` は直前のポケモン・技・IVでモードを切り替えられる。ただし別の厳選依頼に無期限で引き継がない。
- 冗長な進捗説明や段階的な「次」の要求を避け、可能な処理をまとめて実行する。

## 入力と原本
- スーパーリーグCP1500以下、最大Lv50。通常／shadow区分、正確なPvPoke種ID、通常技1・ゲージ技2、攻撃/防御/HP順のIV 0～15。IV・技を無断変更しない。技省略時は検証済みプリセットまたは直前の同種設定を採用し、明記する。
- 毎回Project原本 `pvpokeメタポケモン.txt`（4列：species,fast,charged1,charged2）を読み、順序・重複・shadowを保存。`get_meta_status({})` でサーバーの行数・正規化SHA256と**実際に原本から計算した**SHA256を比較。異なる場合は `sync_meta_opponents({csv_text:原本})` で同期成功を確認してから計算する。比較ができなければ一致・同期済みと断言しない。
- `_shadow-shadow` の原本表記はサーバー入力時のみ末尾 `-shadow` を除く。情報源IVは自動採用せず、相手の別技構成や通常／shadowを別対面として扱う。原本にない構成を勝手に作らない。

## 見出し付き個体値リスト・複数種の連続厳選
- `#カメール` / `#カメール カメックス` のような種名見出しを入力区間として扱う。次の種名見出しまでの各IVを、列挙された**全対象**へ割り当てる。空の区間に前区間のIVを移したり、書かれていない進化形を追加したりしない。
- 見出しがある場合だけ `references/grouped-ivs.md` を読み、入力全体を一度で整理する。種ID・通常/shadow・技3つ・モード・CP/最大Lvが同一の候補をまとめ、同一グループ内の重複IVは計算を一回にする。元の行と対象の対応は保持する。
- 技・種・IVを全グループ分検証してから計算する。技を進化形間で無断コピーしない。省略技には確認済みの同種設定/プリセットを使い、不明・曖昧な入力を推測や無断除外で埋めない。
- 同じ依頼内では、読み込み済みのスキル/参照文書、変更されていないProject原本と正規化SHA256を再利用する。メタを最初に照合・必要時同期し、**各** `run_iv_selection` に同じ実ハッシュを渡してサーバー側の照合を維持する。不一致・原本変更・再起動時は再検証する。
- MCPは一回につき一候補種・単一ワーカー。最初に登場したグループ順に既存 `run_iv_selection` を一回ずつ実行し、runningならその `run_ref` だけで完了まで取得する。同時実行・二重起動・途中の「次」要求をしない。
- **各グループの完備性確認、全候補評価、必要な補足照会、取得済みRating/根拠の保持を終えてから次を開始する。** 最新ZIPやrun_refが次のジョブに置き換わった後、前グループを従来の最新ZIP取得ツールで照会しない。
- 最終回答は種ごとに分け、各種のおすすめ全個体・短い実測根拠・個別英語検索式だけを表示する。異なる進化形・技構成間の平均Ratingで個体を落とさず、S/A・完全支配は同一グループの全候補間で判断する。エラー・未実行・欠損は対象を明示する。

## 最優先：一括実行MCP（2026-10-14追加）
- 本番MCPに `run_iv_selection` が公開されていれば、従来の `prepare_24_conditions` / `start_24_conditions` / `get_status` / `get_selection_digest` の**4工程を重複実行しない**。Project原本とサーバーメタSHA256を検証・必要時同期し、次に `run_iv_selection({candidate,ivs,batch_mode,expected_meta_sha256,focus_opponents,highlight_limit:20,review_limit:8,focus_limit:20,wait_seconds:12})` を**一回**呼ぶ。`batch_mode`は省略/s→`simple`、d→`detailed`。CLIではなく本番MCPツールに入力する。
- `expected_meta_sha256` は**現在のProject原本から実際に求めた正規化ハッシュ**だけを渡す。利用できない場合は勝手なハッシュを作らず、同期未検証を報告し、他に根拠があれば引数省略のうえサーバーメタとしての計算を区別する。実際に不一致ならツールは計算を開始せず拒否する。
- 戻り値が `state:'done'` の場合、`reports.default`（簡易）か `reports.default/rank1/attack/defense`（詳細）をそのまま検証・評価する。各 `complete`、件数、除外、抜粋フラグを確認し、回答のS/A根拠を必要に応じ補足照会する。PvPokeの全バトル計算は従来どおり行われる。
- 戻り値が `state:'running'` の場合、同一 `run_ref` を使って `get_iv_selection_result({run_ref})` を**自分で継続的に実行**し、完了後に分析。**`run_iv_selection`を再度呼んで二重計算しない。** 途中の進捗だけを完了と報告しない。`state:'error'` は失敗として報告。ユーザーに毎回「次」と言わせない。
- `run_ref` は現行サーバープロセスのジョブを指す。Railway再起動などで失われた場合、古いZIPを今回の計算成果と偽って使わない。ユーザー入力・保存データと照合できない場合は制約を明示する。
- `run_iv_selection`が未公開なら、下の**従来のMCP経路**にフォールバックする。MCP一覧の更新はChatGPT側の接続更新が必要な場合がある。

## 従来のMCP経路（一括ツールが使えない場合）
1. `get_catalog({})`で種・技・GameMaster日付を確認し、メタを照合・必要時同期する。
2. `prepare_24_conditions({candidate,ivs,batch_mode})`で21体など全候補、メタ数、条件数を事前検証。各候補のCPとLvを知る必要があれば `prepare_battle` も使用する。
3. `start_24_conditions({candidate,ivs,batch_mode})` を**1回だけ**呼ぶ。`get_status({})` で `done` まで確認し、`error` や未完了を成功と呼ばない。競合する追加ジョブは開始しない。
4. **最短・推奨**：本番MCPに `get_selection_digest` が公開されていれば、ZIP完成後に `get_selection_digest({mode:'default',focus_opponents:['Corsola','Tinkaton','Clodsire','Corviknight','Feraligatr','Melmetal'],highlight_limit:20,review_limit:8,focus_limit:20})` で全候補×相手87構成×6シールドを検証し、コンパクトな根拠を取得する。簡易はDefaultを1回、詳細はDefault/Rank1/Attack/Defenseを各1回（4回）。返る `ranking_rows` は全候補、`priority_crossovers`と`focus_matchups`は抜粋。`dominated_by`は全対面を使った完全支配検査、`review_ivs`は精査対象でS/Aランクではない。`complete`、candidate_count、opponent_count、condition_count=6、total_ratings_checked、excluded、crossovers_total/returned、focus_matchups_total/returned、切捨てフラグを検証。**抜粋から全対面を評価済みと推測しない**。必要な根拠が抜粋されていればフルレポートか指定シールドのget_resultsを追加で読み取る。`get_24_summary`はCP/補足集計等を確認する必要がある場合に取得し、重複する全件回収は避ける。
5. **コンパクトツールが見えない／失敗**：`get_selection_report({mode:'default',focus_opponents:['Corsola','Tinkaton','Clodsire','Corviknight','Quagsire','Melmetal'],max_flips:120})` を各モードで1回取得する。返る`rankings`、`crossovers`、`focus_matchups`を使用し、完全性と切捨てを確認する。必要時のみ `get_24_summary({offset:0,limit:50,mode?})`を取得する。
6. **両ツールが使用不可**：従来の `get_24_summary`と `get_results({mode,shield,offset,limit:20})`で完了ZIPを取得する。全候補・全条件を確認し、未実測・欠損を完了済みと誤認しない。直前の別ポケモンの保存ZIPを使わない。
7. 順位・S/A推薦は平均だけで決めず、同一相手・同モード・同シールドRating比較、特に500境界の逆転、重要対面と不利シールドでの代替性を見る。コンパクト版は全件から集計しているが個々の提示証拠は抜粋なので、重要な判断根拠が不足したら追加照会する。500超は正式なPvPoke勝敗カウンターではなくRating由来の推定。

## 評価と出力（2026-10-14：推薦と英語検索式だけ表示）
- **通常の個体値厳選の最終回答は「おすすめ個体と英語検索式」だけ**。冒頭の前置き、計算件数、ツール名、メタ照合、処理時間、完備性表、対面比較表、全体平均一覧、独立した「結論」や「注意事項」、最後のまとめ・次の提案を**表示しない**。ただし実行失敗、欠損、根拠不足などで推薦を正確に出せない場合は、誤解を防ぐために必要な理由だけ簡潔に示す。ユーザーが追加出力を明示した場合はその指定に従う。
- **表示するのは本当に採用価値がある個体すべて**。3体、5体、8体などの固定上限も最低件数も設けない。全入力候補から独自の重要対面改善・Rating500境界の逆転・不利シールドの差分・役割に関わる安定性などを裏付けとして採用。平均との差が僅かで役割が重複するだけの候補、全対面で実測優位な別候補に完全支配される個体などは原則表示しない。
- **v0.3.16：全候補差分を最優先で評価。** `candidate_evidence_complete:true` と `candidate_evidence_count==candidate_count` を検証し、`candidate_evidence` の全個体について `unique_gt500`（他の全候補が500以下でその個体だけ500超）、`unique_gt500_focus`、`unique_gt500_disadvantage`、`clear_leads`（同一相手・条件で次点より20以上高い）、`clear_leads_focus`、`clear_leads_disadvantage`、`dominated` を確認する。`examples` は各個体最大3件の実測差分で、`examples_total` と `examples_truncated` を点検する。これらはS/A判定の**証拠・候補発見用の指標**であり、公式勝利数・確定推薦ではない。
- `candidate_evidence` は **`review_ivs` の上限12やクロスオーバーハイライト数とは独立して全候補を列挙**する。低総合順位でも重要な独自勝ち筋・不利シールド改善があれば推薦候補として検討する。小さな平均差だけではS/Aにしない。逆に新指標で値0でも安定型の採用価値を即断で否定しない。全Ratingと文脈で最終判断する。
- `focus_limit:20` はAPI上限内で重要相手の複数技構成をなるべく一括取得し、不要な追加照会を減らす設定。`focus_matchups_truncated` がfalseなら同じ相手構成を再取得しない。trueなら採用判断に必要な構成だけ補足取得。全候補差分は `candidate_evidence` で別途検証する。
- `review_ivs` はサーバー内部の優先精査対象抜粋にすぎない。`candidate_evidence`が見えない旧サーバー、件数不一致、例が不足して重要対面の採否が変わり得る場合に限り `get_selection_report` または `get_results` で追加照会する。ハイライトにないだけで候補を落とさない。
- 各個体を次の順で**独立表示**し、検索式をその個体の説明の直下に置く。見出しは `1位｜0/11/12｜S候補｜重要メタ対応型` のように、実際の推薦順位・攻撃/防御/HP・S/A候補・固有の役割を明記。CPとLvは実際に確認済みの場合だけ短く付記。説明は原則1〜2文で、独自改善する相手名と条件（S0/S1/S2、i0y1/i0y2/i1y2）、可能なら差を示すRating値を最低1つ含める。不要な総論を付けず、その直下に英語のゲーム内検索式を**1体ごとに個別のコードブロック**で置く。
- Sは重要対面で独自改善またはシールド不利を横断する強みが実測された非支配の第一候補、Aは有力代替または用途限定候補。平均RatingだけでS/Aとせず、根拠不足なら見出し内で「暫定」などと示す。比較根拠が不十分なら追加照会し、数合わせでS/Aを増やさない。
- 検索式 `EnglishSpecies&Nattack&Ndefense&Nhp`。IV区分0→0、1～5→1、6～10→2、11～14→3、15→4。日本語、図鑑番号、`+`、星評価の末尾条件は不要。シャドウには`&shadow`。`references/search-strings.md`を参照。検索式は範囲指定で完全一致ではないが、通常はこの注意書きを表示しない。
- 計算の完備性、全件Rating比較、別候補とのトレードオフ、データ制限を**内部では必ず検証**する。表示を省略するだけで、検証そのものを減らさない。明確な欠損・除外や致命的な不確実性を黙って隠すことはしない。
- ユーザーが明示的に求めない限りCSV成果物を作成・添付しない（PvPoke内部の計算用CSV/ZIPは例外）。実測していないBattle RatingやS/Aの確定を報告しない。保存済みZIP、メタ原本を消さない。

## 参照文書
- `references/evaluation.md`：評価方法、同一条件比較、S/A分類。
- `references/mcp-contract.md`：モード・MCP標準入出力・既存取得法。
- `references/project-meta-batching.md`：原本同期・shadow取扱い。
- `references/search-strings.md`：英語検索式。
- `references/fast-report.md`：フルレポート・コンパクトダイジェスト両方の契約、制約、フォールバック。
- `references/grouped-ivs.md`：種名見出しの区間割当、候補統合、進化形ごとの連続実行（見出し入力時だけ読む）。
