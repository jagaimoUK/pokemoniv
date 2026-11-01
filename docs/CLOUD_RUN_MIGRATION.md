# Railway → Cloud Run 移行記録・再開手順

更新：2026-11-01 JST。**移行は未完了。本番切り替え禁止。**
正本は `jagaimoUK/pokemoniv`。作業ブランチ `migration/cloud-run-20261101`。
この文書とツールはコードであり、実データ・秘密値・バックアップを含まない。

## 1. 今回確認できた状態

| 項目 | 確認結果 |
|---|---|
| main | `98a74418a9bc5f4b993c8f31a0ebf7e021a420af` |
| main のCI | 取得した8チェックがすべてsuccess |
| 未統合PR | #51 `fix/minior-import-go-search-20261020`。本移行には混ぜない |
| Railway project | `e12a38a6-630a-47b9-b363-4201358810a8` |
| service / environment | `29c79711-3e8d-4ff0-9f99-0af28e75fe66` / `f1038685-140b-4318-a333-ddf0b5d58370` (production) |
| 最新デプロイ | `7e0d0354-3fe8-4a7a-b3c6-fca2e01a220d`、QUEUED、main `98a74418` |
| 直前の成功 | `3b70e6ab-2f59-4c49-9614-33a056fc47bf`、`083f7112091ade636e7ab402e2516b05bb9bb088` |
| volume | `dfce254f-532f-466e-a2ac-d9ab8829d09f`、`pvpoke-results`、/data、iad、割当500MB |
| 既存公開ポート | 8787。Dockerfile・Nginxは既にPORTを可変にしている |
| API health / app | 作業環境からそれぞれ3回GET、全応答200 |
| 永続ファイル実物 | **未取得**。接続されたvolumeの存在と割当容量を確認しただけ |
| Google Cloud | ConsoleがこのクラウドブラウザでSite Unavailable。gcloudと認証情報も未提供 |
| Docker | この実行環境にはCLI/daemonなし。GitHub既存CIでビルドを検証する |

QUEUEDのプラットフォーム内部原因は今回特定していない。古い「pre-deployでgunicornを起動」という説明を現在の原因と断定しない。現在取得した設定にそのコマンドはない。稼働環境への変更、再デプロイ、キューの追加、キャンセルは行っていない。

24時間/300秒間隔/289サンプルのRailwayメトリクス：CPU平均0.0181・最大1.1641、メモリ平均0.1945GB・最大0.8834GB、ディスク現時点0.2617GB。ディスクメトリクスは `/data` のファイル別容量や完全なデータ目録ではない。短い瞬間のピークを取りこぼす可能性もある。

作業環境からのHTTP参考値：health 4.109〜4.569秒、app 4.198〜5.528秒。プロキシ・経路を含むため、日本の利用者の応答時間、純粋なアプリ処理時間、東京/米国Cloud Runの比較値としては使わない。

## 2. 実装した範囲と未実装の境界

実装済み：

- SQLite backup API、安全な全ファイルバックアップ、SHA256、SQLite整合性・テーブル件数・スキーマ・行集合の照合、ZIP CRC、別フォルダへの復元確認。
- 未知ファイルも保護する。SQLite WAL等は単純コピーせずbackup APIに取り込む。シンボリックリンク、既存復元先、破損、転送中の通常ファイル変更は拒否する。
- 実行中コンテナ内で使える、ファイル容量・権限・DB件数の読み取り専用調査ツール。
- S3互換ストレージ→専用staging prefixへの条件付き作成・全量読み戻し照合。元データ削除・既存キー上書き・公開はしない。再実行時も一致する既存オブジェクトだけ再利用。
- `/app/migration` のブラウザ移行画面。技構成・再開情報・フラッシュカードIndexedDBをJSONへ保存。競合時に上書きを拒否し、容量不足では今回追加したWeb Storageを戻す。
- Cloud Run本番の起動ガード。分散保存・ジョブが未対応のため、K_SERVICEがある環境は使い捨て検証モード以外では起動しない。
- 課金承認ゲート付きCloud Build検証設定。既存Dockerfile使用、privateな検証サービス、min0/max1、リクエスト課金。予算・権限・API・リポジトリを勝手に作成しない。
- 既存security CIにブラウザ移行テスト、イメージ容量の参考計測を統合。新しい重複CIは増やさない。

**未実装・未実施**：Firestoreへのランタイム保存アダプター、DB実データ変換、アーカイブのオブジェクト保存への接続、Cloud Run Jobsへのディスパッチ、永続ジョブ・排他・再試行、実ボリューム/見本画像のバックアップ、Google Cloudリソース、Cloud Build GitHub接続/トリガー、予算アラート、本番用IAM、Cloud Run検証配備、最終移行、本番切り替え。

今回の設定だけで既存機能がCloud Run本番で安全に稼働するとは扱わない。検証モードのデータは失われてよい合成データだけ。スケールゼロやインスタンス再起動で失うことがある。

## 3. 保存場所の調査結果（ソース確認。実物は未確認）

| データ | 現行の保存先/形式 | 移行での扱い |
|---|---|---|
| パーティ、revision、メタ重要度、パーティ計算結果 | `archives/team_builder.sqlite3` のparties/meta_weights/runs | 重要。意味・revision・時刻を保持しFirestore等へ変換。runsの巨大JSONはオブジェクト保存＋参照を検討 |
| 同DBのcells | 対面キャッシュ | 元バックアップには含める。実行用キャッシュは再生成可 |
| 認証 | `auth.sqlite3` のcredentials(id/kind/expires/revoked/created) | 重要。idは指紋。失効を復活させない。全行保持して移行、秘密署名キーも同一性を確認 |
| 既存/複数カスタムメタ、由来、既定、お気に入り | `project_meta_opponents.csv`、`meta_presets.json`、`.json.bak`、`meta_snapshots/` | 重要。提示された一覧だけでは不足していたもの。全て保護 |
| メタ補完の処理状態 | `meta_variant_jobs/*.json`、process queue | 元ファイル保護。ジョブを永続化して再実行し、手動技構成を維持 |
| 計算結果 | `latest.zip`、`pvpoke_*.zip` | 過去結果を保護。保存中のZIPを公開しない。SHA256と既存manifestの条件を照合 |
| 結果/対面キャッシュ | `result_cache/`、`matchups.sqlite3` | バックアップ保存後、実行用はローカル一時キャッシュで開始可。正確な計算版が不明なら再利用しない |
| 入力、個別結果、24条件中間結果 | `WORK` 内 last_input.json、candidates.csv、opponents.csv、batch24_input.json、results/、batch24_results/、pvpoke_results_latest.zip等 | `/data`外にも保存される。個体値・途中結果を取りこぼさないためWORK全体を別rootとして取得 |
| 見本画像/学習ZIP | S3互換 `visual-memory/v1/owner/latest.zip` | VISUAL_BACKUP_S3_*の連携あり。R2とは未確認。エンドポイントを秘密表示せず確認し、実オブジェクトを別途保護 |
| 手動技構成 | localStorage `pvpoke-app-movesets-v1` | 元のブラウザでエクスポートが必要 |
| 個体値入力、計算結果、再開位置 | sessionStorage `pvpoke-app-batch`、`pvpoke-app-run` | 同じ元タブで保存。タブを閉じる前にエクスポート |
| フラッシュカードのデッキ/復習/セッション/undo等 | IndexedDB `pokemon-move-flashcards` v1 のkv/reviews | 全キー・値をブラウザ移行JSONへ含める。既存フラッシュカード独自の書き出しも併用可能 |

archivesは `PVP_ARCHIVE_DIR` または `RAILWAY_VOLUME_MOUNT_PATH` に **pvpoke_archivesを加えた場所**。PVP_ARCHIVE_DIR自体をそのサブフォルダにすると二重階層になるので注意。

WORKは通常Dockerでは `/home/appuser/pvpoke_automation_web` と推測されるが、実行ユーザーHOMEとdownloadsの存在で変わる。`tools/cloud_migration_inventory.py` の実行結果を正本にする。認証DBもPVP_AUTH_DB、永続root、`~/pvpoke_automation/auth.sqlite3`の順で変わる。

環境変数の確認済みの名前：AUTH0_ALLOWED_SUB、AUTH0_ISSUER、JWT_AUDIENCE、PORT、PVP_API_KEY、PVP_CAND_CHUNK、PVP_MCP_URL、PVP_OAUTH_SCOPE、PVP_OPP_CHUNK、VISUAL_BACKUP_S3_ACCESS_KEY_ID、VISUAL_BACKUP_S3_BUCKET、VISUAL_BACKUP_S3_ENDPOINT、VISUAL_BACKUP_S3_REGION、VISUAL_BACKUP_S3_SECRET_ACCESS_KEY、VISUAL_BACKUP_S3_STYLE。値は取得・記録していない。PVP_MCP_URLという現行の変数名はWeb側origin/OAuthでも使われるため、移行先URLに合わせた更新が必要だが、**ChatGPT接続のPvPoke MCPを呼ぶ理由にはならない**。

## 4. 推奨候補（未採用・未作成）

| 用途 | 候補と理由 | 条件・代替案 |
|---|---|---|
| HTTP/API | Cloud Runリクエスト課金、min0 | Webは計算スレッドを所有しない。リクエストが終わるとCPUが制限される |
| 長時間計算/メタ補完 | Cloud Run Jobs、task1/parallelism1 | インスタンス課金、最小1分。通常の小HTTP処理はJobsにしない。Cloud Tasksは30分制限があるため実測後に比較 |
| パーティ/認証/メタ/ジョブ管理 | Firestore Standard Native、default DB | トランザクションでrevision/失効/lease。新規named DBは無料枠を別にもらえるわけではない |
| 大きいZIP・過去結果・見本画像 | R2 Standard、private | 既存boto3を再利用可能。まずGCS同一リージョンとの実測比較が必要 |
| 一時計算・展開・キャッシュ | workerローカル/tmp | 再生成可。永続SQLiteのマウントはしない。メモリ消費量を測る |
| ビルド/保管 | Cloud Build default e2-standard-2 + 同一リージョンArtifact Registry | 課金承認後。現段階のCloud Build設定は検証専用 |
| 秘密 | Secret Manager、実行用サービスアカウント/ADC | JSON鍵をGitHubへ置かない。役割の違うキーを1つにまとめない |

初期リージョン候補はus-central1。Cloud Runの東京とus-central1はいずれもTier 1だが、無料計算枠と無料転送は別条件。日本からの通信遅延は東京が有利と予想されるものの未計測。東京を除外するほどの実測根拠はまだない。

FirestoreとCloud Run、Artifact Registryは同じリージョンにそろえる。R2のlocation hintはGCPのリージョン指定と同じ保証ではない。R2からのダウンロードは無料でも、**Google→R2のアップロード**とCloud Run経由の日本向けダウンロードにはGCP側の送信費があり得る。privateな短期署名URLでR2から直接配信すれば後者は減らせるが、現在の `/app-api/result` とAndroid契約を壊さない実装が必要。

GCSの米国5GB枠と操作枠が実利用に足り、結果を同一リージョン内で使うなら、GCSの方が認証・IAM・遅延・運用を簡単にできる可能性がある。GCS東京は米国限定の保存無料枠の対象外。実容量未取得のためR2に確定しない。

## 5. 料金の評価（2026-11-01調査、USD、税/為替は別）

無料枠は他プロジェクト/他用途との共有もある。**月額0円の保証、強制課金停止ではない。** Google Cloud Free Tierにも請求アカウントが必要。今回、契約・支払い・課金設定は操作していない。

| サービス | 現在の主な無料枠 | 超過・注意点 |
|---|---|---|
| Cloud Run request billing | 月180,000 vCPU秒、360,000 GiB秒、200万リクエスト（Tier1価格相当） | CPU $0.000024/vCPU秒、RAM $0.0000025/GiB秒、リクエスト$0.40/100万。起動時間も計上 |
| Cloud Run Jobs | instance billing、月240,000 vCPU秒/450,000 GiB秒相当の無料枠が料金表に掲載 | 1実行最低1分。Web/Jobs併用と請求アカウント内の無料割当はSKU別の請求画面で確認し、単純合算で無料時間を水増ししない |
| Cloud Build | default e2-standard-2 月2,500分（変更可能なpromotional枠） | 超過$0.006/分。private pool等は別。自動トリガー乱発を避ける |
| Artifact Registry | 請求アカウント合計0.5GiB | 超過約$0.10/GiB月。複数世代・脆弱性スキャン・転送は別途評価 |
| Firestore Standard | 1GiB、読込50,000/日、書込20,000/日、削除20,000/日、送信10GiB/月 | 日次枠、DB1個。リージョン別単価。管理バックアップ/PITR/TTL等は無料でない |
| R2 Standard | 10GB月、A100万/月、B1,000万/月、送信無料 | 超過$0.015/GB月、A$4.50/100万、B$0.36/100万。請求単位切上げ。Infrequent Accessには同じ無料枠がない |
| GCS米国対象リージョン | 5GB月、A5,000/月、B50,000/月、北米から所定宛先への送信100GB/月 | us-east1/us-west1/us-central1限定の保存枠。東京には適用しない。soft deleteや世代保持も容量に算入 |
| Logging | 50GiB/プロジェクト/月、標準保持 | 超過$0.50/GiB、長期保持等は別。個体値本文・クエリ・秘密をログに出さない |
| Secret Manager | active6version、アクセス10,000/月 | 6個超のversionは約$0.06/version月、アクセス超過$0.03/10,000。無効versionもactiveとして料金対象 |

計算例（実測利用量ではない）：サービス1vCPU/1GiBで10時間/月ならCPU36,000秒・RAM36,000GiB秒。worker1vCPU/2GiBで10時間ならCPU36,000秒・RAM72,000GiB秒。小規模なら計算部分が無料枠内に入る可能性はあるが、大量24条件・自動メタ補完・コールドスタートの合計を測ること。

同じservice1vCPU/1GiBを200時間/月動かした場合、単独のrequest枠での計算部分の概算は `max(720000-180000,0)*0.000024 + max(720000-360000,0)*0.0000025 = $13.86/月`。通信・リクエスト超過等は別。max1でも連続利用なら課金される。

Registryに1.0GiBを保持するなら、0.5GiB超過分は概算$0.05/月。イメージの実容量は今回のCI成果物を確認し、最終的にはRegistry上の圧縮レイヤー容量/共有/全世代合計で判定する。gzipしたdocker saveは参考値であり、Registryの課金容量ではない。

R2 20GB月なら保存だけで概算$0.15/月。無料の「送信」はR2からの送信であり、GCP→R2やGCP→日本の転送を0円にしない。例として課金対象送信10GiB×$0.12なら$1.20。正しい送信元/宛先と最新Premium Tierを最終確認する。

費用を抑える順序：再計算抑制→ローカルキャッシュ→必要なZIPだけ書込→結果ポーリング頻度抑制→イメージの世代保持抑制。進捗は全対面ごとFirestoreに書かず、例えば10〜15秒/大きな進捗変化だけ。DBポーリングも無料読込枠を消費する。

予算アラート案は月USD1、50/90/100%＋予測100%。これは**未設定**で、承認後に既存請求通貨・他用途を確認して作成する。アラートは停止装置ではない。max1だけでもhard capではない。起動頻度、日次計算秒/対面数、ZIP最大容量、同時ジョブ1、要求レートをアプリ側でもトランザクションで制限し、実行前に見積もった計算予算を予約する。制限値は実利用と実測後に決める。

参照（公式、実行前にも最新条件を再確認）：

- https://cloud.google.com/run/pricing
- https://cloud.google.com/run/docs/locations
- https://cloud.google.com/build/pricing
- https://cloud.google.com/artifact-registry/pricing
- https://firebase.google.com/docs/firestore/pricing
- https://developers.cloudflare.com/r2/pricing/
- https://cloud.google.com/storage/pricing
- https://docs.cloud.google.com/free/docs/free-cloud-features
- https://cloud.google.com/products/observability/pricing
- https://cloud.google.com/secret-manager/pricing
- https://docs.cloud.google.com/billing/docs/how-to/budgets
- https://docs.cloud.google.com/run/docs/configuring/billing-settings
- https://docs.cloud.google.com/run/docs/container-contract

## 6. バックアップ実施手順（まだ実データでは実行していない）

Railway SSH/CLI等のアクセスを確保した後、検証済みコミットのツールを**稼働中コンテナ**に持ち込み実行する。ローカルcloneで実行してもRailwayのデータは取得できない。環境変数全値のダンプや公開APIのバックアップエンドポイントは作らない。

```sh
umask 077
python tools/cloud_migration_inventory.py > /tmp/pokemoniv-storage-inventory.json
```

inventoryのWORK/auth実パス、`/data`の空き容量を私有の作業記録で確認する。sourceへバックアップを混ぜない。volume/workが重複する場合は親のrootを1つだけ指定する。

```sh
# パスはinventoryで確認してから置き換える。以下のworkは未確認の例。
python tools/cloud_migration_backup.py backup \
  --root volume=/data \
  --root work=/home/appuser/pvpoke_automation_web \
  --destination /tmp/pokemoniv-20261101.migration-backup
python tools/cloud_migration_backup.py verify /tmp/pokemoniv-20261101.migration-backup
python tools/cloud_migration_backup.py restore /tmp/pokemoniv-20261101.migration-backup \
  --destination /tmp/pokemoniv-separate-restore
```

別のlegacy auth DBがroot外にある場合は、それだけを安全にbackup APIで取得して専用rootに含める。HOME全体を無差別に取り込まない。

バックアップ成功時には別ディレクトリでの復元・照合も自動実行する。SQLiteは全テーブルとschema/user_versionを確認する。DB単位の整合性であり、ファイル間の一貫性までは保証しない。最終移行では**認証発行/失効、保存、メタ更新、計算、見本アップロードを止めてから**最終取得する。未知ファイル、empty directoryも保護する。

ZIP CRC成功はバッチの意味が正しいことの証明ではない。実データが取得できたら、24条件ZIPは `pvpoke_archive.verify_zip` と結果manifest（候補IV、メタhash、計算版、6/24条件）でも照合する。通常のZIPと学習ZIPを24条件形式と誤認して捨てない。

`/tmp`のバックアップはコンテナ再起動で失われる。成功したprivate bundleを暗号化転送し、Railway外へ保存し、**別の環境でverify/restore**してから段階A完了とする。manifest内のハッシュだけでは悪意ある改ざんの真正性は保証しないので、転送元で得たmanifest SHA256を別の安全な経路でも照合する。復元先の権限は0700/0600。実行用UIDへの付け替えは、復元後に専用ディレクトリだけを対象に行う。

実データ/manifest/レポートはリポジトリ外かignore済みprivate-migration/内へ。誤commit防止のignoreは暗号化・アクセス制御の代わりではない。公開CI artifactや通常のGitHub添付へバックアップをアップロードしない。

S3/R2転送は `tools/cloud_migration_objects.py plan --plan <private-json>` で内容・転送量を先にレビューする。SOURCE_S3_* / TARGET_S3_*は秘密管理から渡し、コマンド行やログに秘密を載せない。copyは専用migration-.../のみ、上限1GiBが既定。確認済みのplan hash、出力report新規パスが必要。失敗時のstagingは未公開のまま保ち、原本は変更しない。元bucketにversioningがなければ上書き前の版はこのツールでは復元できない。

## 7. 残りの実装設計

### 保存アダプター

SQL接続をオブジェクトストレージに置き換えない。PartyStore/CredentialStore/MetaStoreの既存操作単位に、SQLite実装とFirestore実装を用意する。既存Railwayをデフォルトにし、Cloud Run側だけ切り替える。

- parties/{id}: 内容、revision、updated。トランザクションでexpected revision比較と32件上限を保つ。同時新規作成にもcounter文書が必要。
- credential fingerprint: kind/expires/revoked/createdを保持。失効は不可逆に扱い、失効文書を古いバックアップで上書きしない。TTL削除は自動採用しない。秘密署名キーと指紋DBは別物。
- meta: 既定・お気に入り・由来・revisionとCSV hashを保持。50カスタム×80KBは1文書へまとめない。メタごとの文書/オブジェクト、全体revisionとのトランザクションを設計する。
- runs: Firestoreの1MiB文書制限に注意。巨大なパーティ詳細JSONとZIPはオブジェクトへ先に確定し、そのSHA256と参照をFirestoreに公開する。
- SQLite→JSON→Firestore変換は型と行件数・主キー・revision・失効数を検証し、隔離namespaceへのdry run/復元比較後に本番へ反映する。生のSQLiteをマウントしない。
- 未知スキーマを自動で読み飛ばさない。schema hashの不一致はレビューを要求する。既存DBには編集履歴専用テーブルがなく、存在しない履歴を「移行済み」と扱わない。

### 計算ジョブ

現在のIVWorkflow._ticket、web.STATUS、PartyBuilder._active、meta_variantsのqueueはいずれもプロセスに依存する。1インスタンス固定やcookie affinityで解決したことにしない。

1. 認証後、既存APIのrun_ref/job_idに対応する永続IDを作る。idempotency keyはユーザー単位＋正規化した入力＋メタhash＋計算版。ただし明示的再計算は新規request IDを持つ。
2. Firestoreトランザクションでjobとグローバル計算lease/予算予約を作る。単なる「キューに書けた」後のJobs起動失敗に備えてlaunch-pendingを保持し、再試行で既存launchを照合する。外部Jobs起動をFirestore transaction内で呼ばない。
3. Cloud Run Jobsは同じイメージの専用worker entrypointを使う。HTTPサーバーとThreadを立てて応答を返す方式を使わない。1 task/並列1、初期maxRetries0から、冪等性と二重起動防止の実証後に再試行を許可する。
4. workerがleaseと増加するfencing tokenを取得。15秒程度のheartbeat、十分なlease期限、保存のたびにtokenを照合。期限切れworkerは結果を確定できない。同じ計算が2重に起動しても最初のlease保持者だけが実行する。
5. job IDごとの一時作業フォルダで既存計算エンジンを実行。IV、技の手動指定、シールド、推薦ロジックは変更しない。現在の共有ファイルパスをジョブごとに分離する。
6. ZIP検証→不変キーでupload→全量/必要箇所照合→Firestoreでdone確定。失敗時にlatestを書き換えない。再実行は同じ確定済み成果物を再利用できる。
7. cancel_requested、attempt、deadline、heartbeat、lease token、error分類を保存。SIGTERMは子Nodeを止め、中断状態を残す。OOM/killではheartbeat期限から中断を判定し、未知の結果を成功にしない。
8. ブラウザが閉じてもjobは存続。別インスタンス/再ログイン後も同じIDから進捗・結果へ到達。APIの既存レスポンス形とAndroidの取り込み/共有仕様を保つ。

Firestore障害時にローカルSQLiteへ勝手にfallbackして成功扱いしない。認証ストア障害はfail closed、保存失敗は明示、キャッシュ失敗だけは安全に再計算。R2障害で結果を公開しない。R2のETagは特にmultipart時にMD5とは限らないためSHA256を別途持つ。

## 8. ブラウザ・Androidの移行

新しいページは**このブランチにあるだけで既存Railway本番には未反映**。旧origin上でページを提供する配備方法を先に確保する必要がある。別サイトにこのHTMLを置いても旧ブラウザの保存内容は読めない。Railwayのキューが解消しない限り、この点も移行の前提として残る。必要ならブラウザexportだけの小変更を別途承認して旧originへ反映するが、このPRを安易にmainへmergeしない。

sessionStorageはタブ単位なので、元の計算タブ内で `/app/migration` に遷移して保存する。別のタブやWorkのクラウドブラウザには本人の保存データが自動的に現れない。復元も同じ移行先タブ内で行い、ページ下部のリンクからアプリへ戻る。IndexedDB/localStorageは同originの他タブと共有されるため、ほかのアプリタブを閉じてから操作する。

Cookieはドメインが変わると移らない。再ログインが必要。HttpOnly CookieやAPIキーをJSONへ含めない。既存指紋/失効履歴はサーバー側で移行し、認証元issuer/audience/allowed-sub/署名キーは別途安全に移す。Auth0の許可origin/callback、アプリ内PVP_MCP_URL由来APP_ORIGIN、Android内固定URL/見本接続情報も要確認。

Androidは今回変更していない。APK内にRailway URLが埋め込まれている箇所を検索し、Cloud Runへ移る場合はURL変更または移行期間中の旧API互換プロキシを設計する。旧URLを突然止めると共有画面・見本バックアップ・フラッシュカードが切れる恐れがある。Android WebViewとChromeの保存領域も同一とは限らない。APK署名・versionCode・実機確認はこの後の別ゲート。

今回のソース検索では `android-integration/overlayqueue/OverlayCopyQueueImportActivity.kt:86` の非厳選検索へのリンクがRailway固定だった。`flashcards_ui.js` のORIGIN定数も旧URLだが、現行ファイルでその定数の使用は見つからなかった。不要なURL一括置換はしない。Auth0の `JWT_AUDIENCE` は論理的なAPI識別子でもあるため、ホスト移行を理由に機械的に変えない。既存issuer/audienceと既存トークンを検証し、変更が本当に必要な場合だけ別途移行する。

## 8a. 実施した検証の記録

- 元のmainのローカル基準：395 tests、失敗なし、5 skipped。
- 初回PRコミット `24b0fa5058fdb2a2e581c863b7a60e4c4b0084b1`：GitHubの16チェックすべてsuccess。Docker本番image、privateポート検証、8080待受・health・未認証拒否・Cloud Run本番ガード、390px Chromium/CSP、160件の個体値再開情報・手動技・IndexedDBの別profile復元・再読込・競合拒否・quota rollbackが成功。依存/履歴秘密/OS監査も成功。
- その後のレビュー補強：同時に作成された復元先への上書き禁止、UTF-8での容量上限、実JSONダウンロード照合、ツールのcontainer同梱、imageサイズのログ出力。
- 補強後ローカル：416 tests、409成功/7 skipped（Docker・Nginx等の環境依存を含む）。新規のcloud系は23 tests、21成功/2 Docker skipped。既存JavaScript suitesとmigration schema checks成功。補強版のDocker/ブラウザは最新PR CIを確認する。
- 実データ、実Cloud Runの再起動/scale zero/複数instance、Firestore、R2本物の障害・データ一致、Android実機は未確認。

GitHub CIは既存のpath filterに従い、複数の既存workflowがDockerfile変更で動く。新規workflowは増やしていないが、既存の重複Dockerビルドを統合する余地は残る。本移行と無関係なCI再設計は今回行わない。検証用の合成データだけをCIへ渡す。

## 9. 配備・IAM・CI/CDの手順

`cloudbuild.cloudrun.yaml` は**完成した本番CI/CDではない**。費用承認後の使い捨て検証配備用テンプレート。既定の `_COST_APPROVAL` は `NOT_APPROVED` で、初段が停止する。承認後に `APPROVED_VALIDATION_ONLY` を明示する。

ゲートで止まってもCloud Buildそのものの起動時間は計上されるため、**承認前にbuildをsubmitしてはいけない**。

事前に承認が必要なもの：請求アカウント紐付け、API有効化、Firestore/GCS/R2/Registry/Cloud Runリソース、Secretの設定、Google/GitHub接続、セキュリティ権限・予算変更。現段階では作成しない。

承認後の設定：

- GitHub接続は既存リポジトリのみ。初回は移行ブランチ手動build、定期実行なし。main更新をトリガーにしない。
- build service accountは対象Registryへのwriter、検証serviceへのdeploy権限、実行用SAへのactAsだけ。API有効化・課金管理・DB操作・production secretsの権限を与えない。最初のservice作成が必要な場合は別途権限を限定する。
- runtime service accountは検証では本番Firestore/R2へアクセス不可。検証専用APIキーのSecret versionだけ読める。Secretは既存本番キーを流用しない。
- productionではWeb用/Jobs用SAを分け、WebにはJobs起動（必要なoverride権限に注意）、両者には必要なDBと対象bucket/prefixだけ。R2トークンはbucket単位、GCP鍵ファイルは作らない。
- 検証サービスはIAM private。gcloud run services proxy等でアクセスする。無認証公開のIAM変更は自動で行わない。公開運用時もアプリ側の認証を維持する。
- validationのmin0/max1/concurrency8、1vCPU/2GiB、timeout300秒は暫定。1リクエスト設定にしてstatus/cancelが詰まる設計にはしない。現行async計算の耐障害性を証明する設定ではない。
- テンプレートは事前承認して作成済みの使い捨て検証サービス（label `pokemoniv_role=validation`）を要求する。既存URLを読んでPVP_MCP_URL/originを配備前に設定し、originだけのための追加revisionを避ける。秘密はビルドへ渡さない。IAM proxy経由のローカルoriginテストと本番originテストを区別する。
- `deploy/cloudrun/artifact-cleanup.dry-run.json` は7日超削除/最近2版保持の**案**。`--dry-run`を明示して設定・対象を確認後、別承認で有効化。現在/復旧対象digestは保持する。イメージ削除が将来のrollbackに影響する点を確認する。
- 予算アラート、メトリクス、アプリ利用上限を設定・検証後に自動デプロイ用triggerを設計する。テスト成功→候補revision→照合→承認→traffic切替の順。本番auto-trafficはまだ追加しない。

既存GitHub security-regression CIが全Python/JS、Docker、CSP付きモバイルブラウザ、依存/OS監査を担当。新たな大規模CIは追加していない。PRの全チェックがgreenでも、Cloud Run実環境や実データ移行の成功を意味しない。

## 10. 検証ゲートと復旧

| ゲート | 必須証跡 | 今回の状態 |
|---|---|---|
| A 実データ取得 | actual path/bytes/mode、全DB件数/hash、ZIP・学習オブジェクト、別環境復元 | 未実施。合成fixtureだけ成功 |
| B 分散保存/worker | revision競合、指紋失効、メタ、永続job/lease/fencing、immutable結果 | 未実装。本番起動をブロック |
| C Cloud Run | 実URL、全回帰、cold start/再起動/断線/複数リクエスト、OOM/timeout/storage failure | 未配備 |
| D 最終差分 | 全writer凍結→最終バックアップ→staging変換→件数/内容hash/revision/失効照合 | 未実施 |
| E 切替 | A〜D成功、費用説明、ユーザーの明示承認、Android/旧ブラウザ/認証計画 | 未承認・未実施 |

回帰対象：150体以上の取り込み、内部direct PvPoke計算、6/24条件、手動技/保存、メタ追加/上書き/CSV、推薦/検索/ニックネーム、Android共有、パーティ作成/編集/復元/6見せ3選/詳細戦略、メタ重要度、フラッシュカード、login/logout/失効、再起動復元、大量・連続・同時操作、再試行、OOM・タイムアウト・保存障害。特に外部job起動とDBcommit間の失敗、lease期限後の古いworkerの結果確定、切断後の再送を試す。

切替前のrollbackは「何も切り替えずRailwayを使い続ける」。既存Railwayサービス/volume/mainは今回変更しない。

切替後にCloud Runで新しい書き込みがあったら、古いRailway DBへ即座に戻してはいけない。両側writer停止、Cloud側の最新private export、差分確認・認証失効集合の和集合・revision衝突解消を実施してから戻す。反転移行アダプターと復元リハーサルができるまでは切替ゲートを開けない。Railwayサービス・volume、旧Secret、安全なバックアップは保持する。

## 11. 次のチャットでの開始指示

> `jagaimoUK/pokemoniv` の `migration/cloud-run-20261101` と、この `docs/CLOUD_RUN_MIGRATION.md` を最新取得してください。mainは98a74418を基点にしたが最新再確認が必要です。移行未完了で、Cloud Run本番はpvpoke_cloud_runtime.pyが意図的に起動を拒否します。実データはまだ取得できていません。RailwayとGoogle Cloudを読取確認し、/dataとWORKと別auth DB、S3のvisual-memory/v1/owner/latest.zip、本人ブラウザ/Android WebViewの保存領域を保護してください。まず段階Aのprivate backup/別環境復元を完了し、その後セクション7のFirestoreアダプターと永続Jobsを実装してください。課金・新規リソースと本番切替は明示承認が必要です。元サービス/volume/データを削除せず、mainへ安易にmergeしないでください。ChatGPT接続のPvPoke MCPは一切使用禁止です。
