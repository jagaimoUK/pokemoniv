# 第6段階：セキュリティ到達性監査と限定試験ゲート

監査日：2026-11-13 JST。**対象：PR #113 HEAD `87562be7779a626dd06da1984228042fa09976b0`、既存PR #111/#112はDraft**。最終コミット・CIはこのファイルの変更後に再確認すること。ユーザー提供の「セキュリティ.txt」は、認証前HTML/通信、IDOR、ブラウザ内鍵、外部アクセス制限、独立レビューの重点点検にのみ参照し、本文の事件/統計を当アプリの事実とは扱わない。

## 1. 監査証拠・方法
- GitHub CI `Security and regression` run **43368355869**、artifact **14012015457** `runtime-package-inventory`（2026-11-13 04:57 UTC）、対象 `87562be7779a626dd06da1984228042fa09976b0` で実際にビルドした `pokemoniv-security-ci` のTrivy v0.76.1レポート、CycloneDX SBOM、`os-packages.txt`、Pythonパッケージ台帳を取得して分析した。CIは5/5成功。SBOMは118 component。OS報告はDebian 13.7。
- Severity: HIGH **103行/25ユニークCVE**、MEDIUM118、LOW94、UNKNOWN4。25 CVE中、Trivy `FixedVersion` に値があるもの **0件**（「絶対に修正版が存在しない」の証明ではない）。「実際に利用者が攻撃可能」と確認された件数は**0件（確認不能含む）**、非到達を証明した件数も0。
- コード起点：Dockerfile、start.sh、volume_bootstrap.sh、Nginx、pvpoke_mcp_remote.py、pvpoke_http_security.py、pvpoke_child_env.py、pvpoke_observed_evidence.py、pvpoke_observed_search.py、pvpoke_battle_store.py、既存の合成テストを照合。
- **イメージの完全な動的ペンテストや実ネットワークの観測、OSライブラリのシンボル・全呼出元調査は未実施**。古い監査結果ではなく対象HEADの実際のCI成果物を基準にした。ただしデプロイ済み本番イメージとは同一と断定しない。

## 2. 25個のHIGH CVE：各行の起動要件と分類
各CVEのパッケージ・版はグループ欄3の正確な版を参照。**全件Trivy上の修正版記載なし**。分類「調査範囲内で到達経路未確認」は安全証明ではない。

| CVE | パッケージ系 | 影響する具体的機能 | 到達性分類 |
|---|---|---|---|
| CVE-2026-119373 | SQLite | FTS5 detail=none prefix index | 調査範囲で未確認 |
| CVE-2026-119374 | SQLite | 破損したFTS5索引 | 調査範囲で未確認 |
| CVE-2026-119379 | SQLite | session changeset適用 | 調査範囲で未確認 |
| CVE-2026-107364 | MIT Kerberos | KDC ASN.1 読取異常 | 調査範囲で未確認 |
| CVE-2026-112315 | MIT Kerberos | kadmind RPCSEC_GSS decode | 調査範囲で未確認 |
| CVE-2026-112316 | MIT Kerberos | kadmind authenticated XDR decode | 調査範囲で未確認 |
| CVE-2026-112317 | MIT Kerberos | KDC keytab復号後エラー | 調査範囲で未確認 |
| CVE-2026-112318 | MIT Kerberos | kadmind NULL policy名 | 調査範囲で未確認 |
| CVE-2026-112319 | MIT Kerberos | kadmind無制限XDR割当 | 調査範囲で未確認 |
| CVE-2026-112320 | MIT Kerberos | kadmind GSS-RPC認証切替 | 調査範囲で未確認 |
| CVE-2026-112321 | MIT Kerberos | kadmind AUTH_GSSAPI_INIT失敗 | 調査範囲で未確認 |
| CVE-2026-112322 | MIT Kerberos | kadmindクライアント清掃CPU | 調査範囲で未確認 |
| CVE-2026-112323 | MIT Kerberos | kadmind認証失敗メモリ | 調査範囲で未確認 |
| CVE-2026-118380 | MIT Kerberos | kadmind RPCSEC_GSS改ざん/漏えい | 調査範囲で未確認 |
| CVE-2026-119079 | MIT Kerberos | KDC ASN.1配列CPU | 調査範囲で未確認 |
| CVE-2026-71199 | MIT Kerberos | KDC認証指標CAMMAC | 調査範囲で未確認 |
| CVE-2026-71200 | MIT Kerberos | PKINIT KDC NULL参照 | 調査範囲で未確認 |
| CVE-2026-76642 | util-linux | mount補助失敗後のprivileged hook | 調査範囲で未確認 |
| CVE-2026-78408 | util-linux | nsenter cgroup権限FD | 調査範囲で未確認 |
| CVE-2026-78409 | util-linux | X-mount.subdir symlink | 調査範囲で未確認 |
| CVE-2026-78410 | util-linux | bind mount source TOCTOU | 調査範囲で未確認 |
| CVE-2025-69720 | ncurses | infocmp stack overflow | 調査範囲で未確認 |
| CVE-2026-16742 | systemd | systemd-homed署名欠落 | 調査範囲で未確認 |
| CVE-2026-54369 | libacl | symlink経由の権限昇格 | 情報不足 |
| CVE-2026-9538 | Perl Archive::Tar | 巨大tar headerでDoS | 調査範囲で未確認 |

### 3. インストール版・アクセス条件・緩和・残存リスク
**SQLite**：`libsqlite3-0 3.46.1-7+deb13u2`。現行アプリは標準SQLiteテーブルを積極的に使う。FTS5 virtual table / sqlite3changeset_applyのアプリ呼出しは既存監査範囲で見つからない。入力として任意SQLite DBを受けるHTTPエンドポイントは確認されず。ただし依存ライブラリ・復元/破損ファイル経由の間接到達は未証明。認証・DBパス固定・バックアップ検証を維持。任意DB/changeset取込は禁止。 **残存**：該当CVEが未修正のままで、調査範囲外のネイティブ依存や運用操作からの到達は否定できない。**対応**：固定バージョンを保ち、上流修正版・実行時capability/ライブラリ利用を隔離環境で再検証する。

**MIT Kerberos**：`libgssapi-krb5-2/libk5crypto3/libkrb5-3/libkrb5support0 1.21.3-5+deb13u1`。KDC/kadmindの起動はstart.sh・Dockerfileにない。HTTP認証は固定APIキー、署名Cookie、条件付きAuth0 JWTであり、Kerberos KDC公開経路は確認されない。GSSAPIの間接ロードや侵害後のローカル経路は未検証。KDC/kadmindを起動/公開しない。 **残存**：該当CVEが未修正のままで、調査範囲外のネイティブ依存や運用操作からの到達は否定できない。**対応**：固定バージョンを保ち、上流修正版・実行時capability/ライブラリ利用を隔離環境で再検証する。

**util-linux**：`util-linux/mount等 2.41.5-0+deb13u1（binary packageにepoch差あり）`。アプリHTTPからmount/nsenter/X-mountを起動する処理を発見していない。起動時はrootからgosuでappuserに降格。脆弱性は権限のあるmount/nsenterや特定のローカル操作が成立条件。コンテナcapability/host設定は未検証。不要capability禁止、マウント経路はtrusted設定限定。 **残存**：該当CVEが未修正のままで、調査範囲外のネイティブ依存や運用操作からの到達は否定できない。**対応**：固定バージョンを保ち、上流修正版・実行時capability/ライブラリ利用を隔離環境で再検証する。

**ncurses**：`ncurses系 6.5+20250216-2`。infocmp実行経路はアプリ起動・HTTP処理に未検出。端末/診断環境での別実行は未確認。外部入力によるterminfo/infocmpの実行を禁止。 **残存**：該当CVEが未修正のままで、調査範囲外のネイティブ依存や運用操作からの到達は否定できない。**対応**：固定バージョンを保ち、上流修正版・実行時capability/ライブラリ利用を隔離環境で再検証する。

**systemd**：`libsystemd0/libudev1 257.13-1~deb13u1`。systemd-homedデーモンはコンテナ起動に含まれない。ホストのsystemdは対象イメージとは別。homed管理ユーザーへのローカルアクセスが前提。未起動を維持。 **残存**：該当CVEが未修正のままで、調査範囲外のネイティブ依存や運用操作からの到達は否定できない。**対応**：固定バージョンを保ち、上流修正版・実行時capability/ライブラリ利用を隔離環境で再検証する。

**libacl**：`libacl1 2.3.2-2+b1`。ライブラリはインストール済み。ACL pathname関数をHTTP入力から呼ぶ経路は発見できていないが、間接呼出し未調査。ローカル攻撃者とsymlink制御などが成立条件。非root実行と固定ディレクトリ権限を維持。 **残存**：該当CVEが未修正のままで、調査範囲外のネイティブ依存や運用操作からの到達は否定できない。**対応**：固定バージョンを保ち、上流修正版・実行時capability/ライブラリ利用を隔離環境で再検証する。

**Perl Archive::Tar**：`perl-base 5.40.1-6+deb13u1`。HTTP APIでPerl Archive::Tarを起動する経路は未検出。既存バックアップはPython zipfileを利用。外部tarをPerlで解析しない。OSメンテナンス等の間接経路は未確認。 **残存**：該当CVEが未修正のままで、調査範囲外のネイティブ依存や運用操作からの到達は否定できない。**対応**：固定バージョンを保ち、上流修正版・実行時capability/ライブラリ利用を隔離環境で再検証する。

### 4. 認証、認可、公開前情報漏えい
- HTTP公開経路の認証は `pvpoke_mcp_remote.py` の `do_POST` が先に検証する。認証方式は十分な長さのAPIキー、単一Auth0 subject（設定時）、アプリ用Bearer、署名ブラウザCookie。Cookie-only MCPは不可、/app-api/sessionは強い認証が必要。所有者指定はサーバ内部BattleStoreの `owner_scope`（既定単一owner）。**一般マルチテナントの分離が実装済みという証明ではない**。
- Nginxはloopback 8788のgatewayへ代理接続。計算server 8765はloopbackのみ。既存の実Nginx合成HTTPテストでは未認証APIの拒否、CSRF Origin、ログアウトCookie失効、公開HTMLで合成秘密マーカーを含まないこと、X-Forwarded-For偽装拒否を確認。**Railwayの実edge/DNS/外部到達は未検証**。
- BrowserLogin cookieのHttpOnly/SameSite/secure属性、バックアップ資格情報の強い認証分岐、異常系の匿名401/403と認証済み汎用エラーの隔離は既存テスト・コードで確認。公開GETの静的UI表示は許可されるため、管理者限定試験では必ずネットワーク境界でも公開範囲を絞る。
- 認証前の実端末Network通信、実本番のHTML/初期API応答、旧セッション・ログアウト後のすべての端末Cookieの現地検証は未実施。合成環境での確認が実機・実公開の証明になるとは扱わない。
- Gitの到達可能履歴Gitleaks、Python依存pip-audit、CI合成ブラウザ、Nginxプロキシを検証。ログ/Artifactのすべての文字列を機密検査したわけではない。CIスキャンが成功しても漏えい不存在の証明ではない。

### 5. リソース枯渇のコード監査と軽減
**確認された設計上の負荷経路**：`pvpoke_observed_evidence.compare_observed` は入力探索IDを最大6件受け付け、`ObservedSearch._read` が各ジョブ最大4096件の完全な履歴receiptをJSON decode、checksum・damage検証、state再生する。1IDごとの上限はあっても**1HTTPリクエストの総再生量は制限されていなかった**。これはCPU/メモリ負荷の可能性を意味し、**サービス停止を実証したわけではない**。
- 今回の対策：`observed_evidence` に限って **最大1024件の累積receipt / 最大16MiBの保存receipt本文**をSQL集計で事前確認し、超過時は安全にValueErrorで拒否する。既存Sandboxの最大4096履歴、保存DB、ユーザー履歴は変更しない。保存済み履歴はSandbox側から参照できる。
- 同一battle_keyの正規化を1HTTPリクエスト内で再利用して、役割条件の重複による `sandbox.prepare` の不要な呼出を減らす。異常なIDの形式は64 hex、件数は1〜6、アプリJSONは64KiBが上限。
- gatewayの既存共通予算は `compute-owner` 最大12/分、`APP_REQUEST_SLOTS` 4、entry最大300/分。Nginx limit_conn 24、global/peer request rate 10r/s。時間上限はgateway HTTP request 90秒、内部backend呼出65秒。**内部処理をクライアント切断と同時に中断できるとは保証しない**。
- 1024 receiptのp50/p95/ピークRSS、複数スレッド連射・接続断継続・長時間jobの負荷実測は未実施。試験環境開始前に同一合成入力の低/高負荷測定と実効CPU・RSS監視が必要。

### 6. データ保護・バックアップ・復旧
- BattleStore: 明示的owner scope、32MiBのDB quota、通常キャッシュ書込の8MiBディスク予備、2MiB追加ヘッドルーム、SQLiteトランザクションの原子性とread-only rollback recovery。INSERT/UPDATEの失敗時はrollback。WALの異常増大は再計算記録を書かず安全停止する。
- 既存CIの **隔離2MiB tmpfsによる本物のENOSPC** はDELETE/WAL両モードで所有者履歴のatomic rollback、再試行、別owner不可視、integrity_check成功。新しい観測履歴の多重並列負荷下での全電源断・容量上限越えは未実証。
- `tools/cloud_migration_backup.py` は通常ファイルとSQLiteの整合スナップショット、ハッシュ検証・別ディレクトリrestoreを持つ。過去の合成テストは復元後整合を検証しているが、この第6段階で現本番の全DBを復元したわけではない。旧データは変更・削除していない。
- 合成データのみ使用、外部サービスを攻撃せず、コンテナ内パッケージ更新/Cloud Run/Railway操作や認証情報変更なし。

### 7. 管理者本人だけの限定試験: ゲートと手順（未実施）
**準備:** 本番とは別のアカウント/サービス/永続ボリューム/DB、別の合成認証情報を作る。DBは空から生成し、実所有履歴・設定・バックアップ資格情報をコピーしない。ローカルまたはVPN/private ingressのみ、外部公開のHTTPアクセスを拒否。イメージはこの監査済みcommitと同じdigestを指定、リソースCPU/RSS/容量/ネットワーク送信を制限。nonroot appuser・不要capabilityの排除を別途検証。単一ownerで運用し追加ユーザー登録は禁止。
**認証前に:** GET /app・/app/missing・/app/sandbox・/healthを取得し秘密の合成マーカーが見えないこと。未認証POST /app-api/missing-analysis、/app-api/sandbox、/mcp、/visual-backup/v1/*を401等で拒否。Origin偽装、別owner-ID、期限切れ/ログアウト後のCookie、Host/forwarded headers、不正JSON・巨大入力を隔離環境で再チェック。
**安全性に合格した後:** `PVP_OBSERVED_SEARCH_ENABLED=1` は試験インスタンス**だけ**に手動設定し、少量（1→8→32）の合成探索から開始。初期値OFFを維持し、本番へは絶対に伝搬させない。変更はユーザーの明示承認後に限定。
**監視:** HTTP401/403/429/5xx、リクエスト時間p50/p95、同時接続/active jobs、CPU・RSS・ファイル容量・SQLite integrity、バックアップ/復元検証時刻、レスポンス本文に合成機密マーカーがないか。リクエスト本文/Authorization/Cookie/IV履歴はログ記録しない。
**停止:** 異常5xx連続、RSS/CPU上限接近、ディスク予備容量不足、認証異常、データの破損・他owner漏えい疑いが起きたら試験フラグOFF、入口アクセス拒否/試験サービス停止、DBをread-only退避。再起動だけで続けず原因と履歴整合を確認。
**復旧:** 事前取得した試験用SQLite整合バックアップとmanifest/hashを verify。サービス停止か書込停止して隔離先にrestoreし、`PRAGMA integrity_check`、owner/history件数・ハッシュ・ログインの境界を確認。問題のある試験インスタンスを廃棄可能にする。DB削除・実本番へのrestoreは禁止。

### 8. 判定
**現時点は A（限定試験開始不可）。** 監査上確認できたのは「現行コード＋CIイメージ」であり、限定試験環境の独立性、入口アクセス制限、コンテナ能力とボリューム保存・監視の実測は未確認。25 CVE中に明確な到達可能な攻撃は**確認されていない**が、間接依存・環境設定を含む非到達も証明されていない。
**B（条件付き限定試験可能）に移行するには**上記の隔離・追加認証・実証されたリソース上限・合成データrestore・ネットワーク実効制限・重大到達性レビューを全て実施し、その証拠を記録してから管理者が明示承認する必要がある。C（一般公開可能）は対象外。未修正HIGHの数のみで機械的に判定しない。

### 9. 学習ポイント・代替案と効率
- 認証≠認可、静的HTMLとAPIレスポンスは別々に検査。データのserver-side owner scopeとHTTP利用者の識別は別レイヤー。
- 上限はIDの件数だけでは足りない：DBから復元する総件数×各行の長さ×同時実行数で評価する。SQLite集計で検証前に失敗するのが**fail-fast**。代替は永続化した要約・差分checkpointだが、証拠キャッシュの整合/版管理が複雑になり今回は採用しない。
- CVEスキャナは影響を受ける**パッケージ**を教える。攻撃経路を断定しない。未検出と到達不能の証明を混同しない。
- 本工程は1回の原子的コミットを目標とし、CIは最終SHAだけで確認する。実機・運用環境の再現は本番デプロイしない限り行わない。
