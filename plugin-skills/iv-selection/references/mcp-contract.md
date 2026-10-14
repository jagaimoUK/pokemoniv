# PvPoke MCPの簡易・詳細モード契約

**既定は簡易（6条件）。毎回の厳選で指定がなければ `batch_mode:"simple"` を使う。`d` /「詳細」指定のある依頼だけ詳細（24条件）にする。単独 `d` は直後の依頼に有効だが、無期限に引き継がない。**

**ChatGPT向け短縮命令：** 単独の `d` / `D` → `batch_mode:"detailed"`（詳細24条件）、単独の `s` / `S` → `batch_mode:"simple"`（簡易6条件）。`詳細` / `簡易` だけでも有効。「モード」の入力は不要。ChatGPT側で変換し、MCPのbatch_mode引数には必ず `simple` か `detailed` を渡す。直前の種とIVが有効なら1文字だけの後続命令で切替可能。英語ポケモン名・技名内部の文字と混同しない。

接続先：`https://pokemoniv-production.up.railway.app/mcp`。認証情報を出力・GitHubに保存しない。既存の8ツールを継続利用し、ツール名の変更はない。

- `get_catalog({})`：種・技とGameMaster時刻。
- `prepare_24_conditions({candidate,ivs,batch_mode?})`：事前確認。`batch_mode`は`simple`（Defaultのみ6条件）または`detailed`（4モード24条件）、未指定は簡易。
- `start_24_conditions({candidate,ivs,batch_mode?})`：同様の実計算を一度だけ開始。ジョブ同時実行不可。
- `get_status({})`：running/done/error。doneになるまで結果を断定しない。
- `get_24_summary({offset?,limit?,mode?})`：簡易なら`mode:'default'`だけ存在。詳細ならdefault/rank1/attack/defenseの4種類。
- `get_results({shield?,mode?,offset?,limit?})`：`mode:'default'`などを明示。`shield`はs0,s1,s2,i0y1,i0y2,i1y2。limit最大20。
- `prepare_battle({candidate,ivs,opponents,shields?,opponent_iv_mode?})`、`start_battle(...)`は対戦相手を手動で指定する旧経路であり、メタ87の簡易とは異なる。

**計算**：相手87技構成、CP1500／最大Lv50。簡易なら候補×87×6、詳細なら候補×87×24。`batch_mode`を受け取るMCPサーバーへ実際に渡す。新しいMCP引数がクライアントに表示されない場合、接続更新の必要性を確認する。

**保存**：結果ZIPはmanifestに`batch_mode`を記録。簡易は`default_*.csv`6本＋集計、詳細は4×6＝24本＋集計。検証済みZIPをRailway永続ストレージに保存し、一時ファイルはその後に削除。過去の実行ZIPは別名で保存。再起動後は最新ZIPが再取得できる。

**注意**：Project原本とGitHub同梱メタCSVは自動同期されない。source IVは手動のみ。`rating_gt500`やwins等は推定値のことがある。S/AはChatGPTが実測重要対面を比較して決める。ゲーム内検索式は英語、Notion用CSVは依頼されない限り不要。

## メタ自動同期・ZIP保存量の追加MCP
- `get_meta_status({})`：サーバーで利用している技構成リストの行数・SHA256・同梱/同期済みの別を返す。
- `sync_meta_opponents({csv_text})`：Project原本の4列CSV全文を送る。現行GameMasterで**全行**検証し、失敗時は前版を保存。計算中は更新拒否。正常な原本のみRailwayの既存永続ボリュームに原子的に保存。
- `get_storage_status({})`：保存済み履歴ZIPの件数と使用量を確認する。
- 厳選開始前にProject原本とメタのハッシュを照合し、差があれば同期する。Projectをサーバー側から直接監視する仕組みではない。MCPに新ツールが見えなければ接続更新を確認し、同期できたとは断定しない。
- 保存領域には古い計算結果を際限なく蓄積しない。計算完了時に直近20件・合計200MiBを目安に整理し、最低5件と `latest.zip` は必ず保持する。
