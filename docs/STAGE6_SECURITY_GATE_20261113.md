# 第6段階 セキュリティ監査・限定試験ゲート（2026-11-13 JST）

**対象：** Draft PR #111/#112/#113を基礎としたDraft PR #114。第5段階の起点は87562be7779a626dd06da1984228042fa09976b0。監査用ブランチ audit/stage6-security-gate-20261113。main、本番、既存データには触れていない。接続されたPvPoke MCPは直接・間接とも使用していない。

**根拠資料：** GitHub Actions run 43368355869 の runtime-package-inventory artifact ID 14012015457（第5段階の正確なイメージ）。Trivy 0.76.1、Debian 13.7、Image ID sha256:a5de72f0c19b39e839aaeceb9a366a0c77b723f17aae87ed5d08be717daa7235。image-vulnerabilities.json、image-sbom.cdx.json、os-packages.txtを照合。第6段階の新HEADのCIと同一イメージであるとは推定しない。最終CIのイメージを別途照合する。過去の HIGH_PRIORITY_SECURITY_GATE / REMAINING_RISK_VALIDATION / AUTH_BOUNDARY_AND_IMAGE_AUDIT は削除・書換えしない。

## 1. 判定の意味

- **危険経路を確認**：外部・認証済み入力から影響機能への実行パスと成立条件を実証できたもの。
- **到達可能だが緩和あり**：到達した機能の防御策を確認済みのもの。
- **N（経路未確認）**：今回調査したアプリソース・テストの範囲では該当機能の呼出し／接続口がない。**不可能の証明ではない**。
- **I（情報不足）**：使用される共有ライブラリ、間接的呼出し、外部入力、運用環境などに不確定要素があり、安全と判定できないもの。
- **更新済み**：修正バージョンを最終イメージで確認したもの。本節で該当するHIGH CVEは0。

第5段階のTrivy報告は **HIGH 103検出行・25種類のCVE**。分類：Kerberos 56行14種、util-linux 36行4種、SQLite 3行3種、ncurses 4行1種、systemd 2行1種、libacl 1行1種、Perl 1行1種。該当するCVE行は全てそのイメージに存在する。TrivyのFixedVersion記載は25種類とも空欄で、24種類はstatus=affected、PerlのCVE-2026-9538のみstatus=fix_deferred。スキャナーが修正可能と判定したHIGH/CRITICALは0。**これは upstream に将来パッチが出ないという意味ではない**。

## 2. CVE別の機能・前提・到達性

| CVE | 実イメージの検出パッケージ/版 | 危険な処理 | 攻撃経路成立に必要な条件 | 判定 |
|---|---|---|---|---|
| CVE-2026-119373 | libsqlite3-0 3.46.1-7+deb13u2 | FTS5 detail=none prefix索引の負rowidを伴う結合でheap破壊 | 細工されたFTS5テーブルとMATCH実行が必要 | I:情報不足で保留 |
| CVE-2026-119374 | libsqlite3-0 3.46.1-7+deb13u2 | 壊れたFTS5 secure-deleteの索引操作 | 不正なFTS5 DBの読込・削除が必要 | I:情報不足で保留 |
| CVE-2026-119379 | libsqlite3-0 3.46.1-7+deb13u2 | session changeset適用時のheap破壊 | 攻撃者製changesetを適用する入口が必要 | I:情報不足で保留 |
| CVE-2026-107364 | MIT krb5 libraries 1.21.3-5+deb13u1 | KDC ASN.1 decode read overrun / 停止 | KDCへ未認証要求。サービス起動経路未確認 | N:調査範囲で到達経路未確認 |
| CVE-2026-112315 | MIT krb5 libraries 1.21.3-5+deb13u1 | kadmind RPCSEC_GSS XDR decode memory leak | kadmindへの未認証細工RPCが必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-112316 | MIT krb5 libraries 1.21.3-5+deb13u1 | kadmind tl_data decode memory leak | kadmindへの認証済み細工RPCが必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-112317 | MIT krb5 libraries 1.21.3-5+deb13u1 | KDC/kadmind keytab処理 memory leak | KDC/kadmindに失敗処理を繰り返す必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-112318 | MIT krb5 libraries 1.21.3-5+deb13u1 | kadmind policy名NULL参照 / 停止 | 認証済みkadmin RPCとNULL policyが必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-112319 | MIT krb5 libraries 1.21.3-5+deb13u1 | kadmind GSS-RPC XDR 無制限割当 | kadmind認証済み細工RPCが必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-112320 | MIT krb5 libraries 1.21.3-5+deb13u1 | kadmind認証方式切替によるcontext leak | kadmindへの複数RPC方式が必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-112321 | MIT krb5 libraries 1.21.3-5+deb13u1 | kadmind AUTH_GSSAPI_INIT decode leak | kadmind未認証細工要求が必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-112322 | MIT krb5 libraries 1.21.3-5+deb13u1 | kadmind client cleanup二乗CPU DoS | 大量のGSSAPIクライアント状態が必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-112323 | MIT krb5 libraries 1.21.3-5+deb13u1 | kadmind failed AUTH_GSSAPI_INIT状態蓄積 | kadmindへ失敗要求を繰り返す必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-118380 | MIT krb5 libraries 1.21.3-5+deb13u1 | RPCSEC_GSS通信改変/応答平文化 | RPCSEC_GSSを使うネットワーク通信への介入が必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-119079 | MIT krb5 libraries 1.21.3-5+deb13u1 | KDC ASN.1 SEQUENCE OF decode CPU DoS | KDCへの未認証AS/TGS要求が必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-71199 | MIT krb5 libraries 1.21.3-5+deb13u1 | CAMMAC認証indicator要件回避 | Kerberos主張/検証と認証済み主体が必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-71200 | MIT krb5 libraries 1.21.3-5+deb13u1 | PKINIT KDC NULL参照 / 停止 | PKINITを有効にしたKDCに未認証要求が必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-76642 | util-linux 2.41.5-0+deb13u1（login系の表示は別版文字列） | 失敗したmount helper後にX-mount posthookを実行 | 特権mount・fstab権限・ローカルアクセスが必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-78408 | util-linux 2.41.5-0+deb13u1（login系の表示は別版文字列） | nsenter --join-cgroupの特権FD引継ぎ | 特権nsenterとローカルnamespace操作が必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-78409 | util-linux 2.41.5-0+deb13u1（login系の表示は別版文字列） | X-mount.subdirで中間symlinkを越えて解決 | fstabで認可された特権mountとsymlink制御が必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-78410 | util-linux 2.41.5-0+deb13u1（login系の表示は別版文字列） | 制限bind mountのsource swap/権限昇格 | fstab・書込可能祖先パス・特権mountが必要 | N:調査範囲で到達経路未確認 |
| CVE-2025-69720 | ncurses 6.5+20250216-2 | infocmpのanalyze_string stack overflow | infocmpが攻撃者入力を解析する必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-16742 | libsystemd0/libudev1 257.13-1~deb13u1 | systemd-homed署名検証欠落によるローカル権限昇格 | homed管理ユーザーとsystemd-homed操作が必要 | N:調査範囲で到達経路未確認 |
| CVE-2026-54369 | libacl1 2.3.2-2+b1 | libacl path APIのsymlink越境 | 特権ACL操作と攻撃者制御のパスが必要 | I:情報不足で保留 |
| CVE-2026-9538 | perl-base 5.40.1-6+deb13u1 | Perl Archive::Tarのtar size読取でメモリ枯渇 | Perl Archive::Tarに攻撃者製tarを渡す必要 | N:調査範囲で到達経路未確認 |

**共通の到達性検証：** ownerに紐づくSQLite通常テーブル操作は現に実行されるが、主要15モジュール（約5,567行：BattleStore/Auth/Ownership/Role/Missing/IVSearch/Sandbox/Observed/Tactic/Web/Gateway/VisualBackup/オフライン復元）の静的確認ではFTS5仮想テーブル作成・MATCH、session changeset適用、load_extension、Kerberos KDC/kadmind、特権mount/nsenter、infocmp、systemd-homed、Perl Archive::TarのHTTP起動経路を確認できなかった。正規表現中心の静的調査であり、依存ライブラリ内部や任意の破損DBを介した間接実行を否定できない。

**CVE群ごとの既存防御と残留リスク・推奨策：**

1. SQLite 3件：通常の所有履歴・対戦記録・認証DBは実利用。HTTPで任意SQLやFTS索引、changesetを入力する経路は発見していない。DBファイルはサーバーが管理し、オフラインのバックアップ復元は検証対象。ただし汚染されたローカルDB、管理者が持ち込んだDB、ライブラリ内部の機能到達性は未解明。任意SQLiteのアップロード・復元は禁止し、バックアップは隔離した同一アプリ産物のみ検証・復旧。修正版が配布された時点でbase imageを固定し直して全回帰する。
2. MIT krb5 14件：危険機能は主としてKDC/kadmind、GSS-RPC、PKINIT、CAMMAC。start.shはローカルWebエンジン・gateway・nginxを起動し、Kerberos daemonを起動しない。HTTP→該当daemonへの経路は見つからない。ただし依存ライブラリ・container外の認証基盤・管理者操作までは監査していない。インバウンドを管理者だけに制限し、不要なdaemonを起動しない。
3. util-linux 4件：特権mount/nsenter、fstab、ローカルユーザー権限などが前提。Webの入力パスで起動する箇所は見つからない。コンテナ起動時はrootによる限定的ボリューム準備を経てgosuでappuserへ落とすが、ホストcapability・no-new-privileges・mount設定は未検証。限定試験時はprivileged実行を使わず、利用できる場合はcapability削減とno-new-privilegesを構成・検証する。
4. ncurses 1件：infocmpコマンドが悪意あるterminfo相当を処理する必要がある。通常のAPIワーカーは呼び出さない。運用/診断時にも外部由来のterminfoを解析させない。
5. systemd 1件：systemd-homedにおけるローカル権限昇格。該当ライブラリは存在するがdaemonの稼働経路は未確認。限定試験ではsystemd-homedを起動しない構成を確認する。
6. libacl 1件：特権でのpathname ACL操作と可変symlinkが必要。アプリのroot bootstrapはmkdir/chownであり、libacl APIを直接呼ぶ経路は見つからない。間接呼出し・悪意あるボリュームsymlinkを未完全監査。volume所有者/モードとsymlinkを試験時に点検する。
7. Perl Archive::Tar 1件：悪意あるtar headerをPerl parserへ渡す必要がある。オンラインの見本バックアップはPython ZIP処理、移行バックアップはローカルディレクトリ方式。外部tarをPerlで展開するWeb機能は見つからない。perl-baseへの検出が実際のArchive::Tar呼出しを意味するわけではない。運用で未知tarを処理しない。

**実際に成立した25件のCVE攻撃経路：確認0件。** ただし「経路がないと証明済み」も0件。NとIを誤って「修正完了」に読み替えない。

## 3. 認証・認可・情報漏えい

- 既存コード：nginxは127.0.0.1:8788のgatewayへ転送。計算エンジンは127.0.0.1:8765のみ。実Nginx＋実gatewayの隔離テストで /api/status の直公開は拒否。Railwayのedge ingress、TLS、Firewall、Host/forwarded header挙動は未検証。
- 認証：root bearer／許可されたAuth0主体／短命アプリtoken／署名Cookieは各々検証される。単一所有者構成であり、DB owner_scopeだけでは一般向けマルチテナント認証は完成しない。
- 未認証：実Nginx＋gatewayの試験で公開HTML・healthの合成秘密マーカー不在、匿名のapp/party/missing/sandbox/battles/backup/MCPが401。画面のネットワーク初期通信全てが実本番で安全という保証ではない。
- Cookie：HttpOnly・SameSite=Strict、HTTPS APP_ORIGINのときSecure。複製Cookieのlogout後拒否、古いtokenのrevoke・別ownerのID・重複JSON・NaN・不正Content-Type、悪意あるOrigin、なりすましX-Forwarded-Forに対する既存回帰あり。
- サーバー間：gatewayの内部接続Errorの本文や内部URLをブラウザへ返さず定型文へ置換。子プロセスへ最小環境変数を渡し、認証秘密やS3秘密は渡さない。gitleaks --allと合成秘密マーカーテストは通過。ただし実運用の全ログ・成果物・セッションCookie保管場所の独立確認は未実施。
- 許可：ownerはリクエストボディの任意フィールドでは選べない。違うownerの同一探索ID・評価IDは失敗する合成テストあり。別所有者のオンライン利用権限分離や本番上での試験は行っていない。
- 入力：不足APIは64KiB JSON、重複キー・非有限値を拒否。MCPは1MB、VisualBackupは別認証トークン・16MiB archive上限・回数/同時実行上限。Originを欠いた非ブラウザbearer要求は認証済みなら受ける設計。CSRFの主防御はCookie SameSiteとapplication/json＋Origin検証であり、ホスト構成を変える際は再確認が必要。

## 4. 確認・修正した負荷リスク

**コード上の再現あり、サービス停止の悪用実証はなし。** 第5段階の pvpoke_observed_evidence.compare_observed は同一ownerの探索IDを最大6個受け取り、各IDの全保存レシートを観測再生監査で先頭から再構成していた。Sandbox自体の1ジョブ4096回という上限を、最大6 ID分の参照に合算する制約はなかった。認証済みの重い要求が最大65秒のgateway timeoutや後段の単一計算枠を占有する危険があった。

**test-first negative control：** 合成cursor1025件と、一件480KiBの記録18件（合計8.44MiB）を作り、重い ObservedSearch._read に到達すればAssertionErrorとなるテストを追加。修正前のCIは619テスト中2件の期待した失敗を検出。修正は参照専用APIに限り、
- **6 ID全体で1024レシート以下**
- **6 ID全体の保存レシート合計8MiB以下**
- **owner一致かつID存在確認 → SQLiteのlength/cursorで事前審査 → 同じ読み取りスナップショットで完全チェックサム・結果監査**
の順にする。SQLはバインド引数のみを使う。上限超過は再生前に失敗し、Sandboxの既存4096回枠・途中結果・通常評価・DBスキーマは変えない。上限超過のジョブはSandbox個別画面で見る。gateway側にはcompute-owner 12/分、app同時4枠、backendは一度に1計算という既存防御もある。

**参考測定（本番/アプリ全体とは異なる）：** 独立した一時SQLiteで1024行×4096B、総4MiBを作り、owner+ID別のcursorとSUM(LENGTH(receipt))による事前照会のみを60回測定。p50 2.427ms、p95 3.495ms、DB約4.8MB。実アプリの同時負荷・比較API総時間・本番RAMのp95・修正前後の同条件測定は未実施。

## 5. 永続化・バックアップ・復旧

既存の合成テスト：ObservedSearchのレシートとカーソルの原子的保存、同一カーソル再要求で重複再生をしない、pause/resume、owner切替、旧版stale拒否。専用の cloud_migration_backup は元のデータからSQLite online backupを作り、manifestに各テーブルの行数・ハッシュを記録、検証、新規ディレクトリへの実復元、復元後の整合性確認を実施する。既存テストに試験保存量・未コミット書込み失敗・DB復元後の検索状態確認を含む。実容量不足試験はCI Dockerの**2MiB専用tmpfs**でDELETE/WALを走らせ、DBの復旧、履歴不変、owner分離、再試行成功を確認する。

**未検証：** 実ホストの電源断、DB外ファイルとDBの完全同時スナップショット、悪意ある管理者持込みSQLite、実際のクラウドボリューム故障、機密バックアップの保管環境と削除手順。復元ツールは既存ディレクトリを上書きしない。これらを本番データで試してはいけない。

## 6. 限定試験ゲート・手順（今は実行禁止）

**現在の判定：A（現時点では開始不可）**。下記すべてに実測と証跡がそろえば、管理者本人だけのB（条件付き限定試験）へ移行を検討できる。一般公開Cは別途独立監査・マルチユーザー設計・運用監視が必要で、今回は不可。

1. **独立した隔離環境**：本番Railway/Cloud Runとは別service/project、別ボリューム、別ログ、別シークレット、合成個体/所有履歴だけ。公開URLを作る場合は追加のprivate ingress/VPN/IP制限と管理者認証を二重化し、無認証の直URLでAPIにアクセスできないことを確認。一般ユーザー登録はしない。
2. **構成**：固有の強い管理者secret。PVP_OBSERVED_SEARCH_ENABLEDは既定OFFを維持し、フラグONやdeployは別途明示承認後に限る。trial時だけ PVP_SANDBOX_ENABLED / PVP_MISSING_ANALYSIS_ENABLED / PVP_BATTLE_API_ENABLED との整合を確認。Auth0使用時は許可主体を管理者1名に固定し、TLS/secure Cookie/Origin/Hostの経路を確認。S3とproductionバックアップ設定は流用しない。
3. **権限・ネットワーク**：コンテナ起動後appuser、ローカル計算ポート外部非公開、余分なLinux capabilityなし、可能ならno-new-privileges／読取専用root filesystem（書込に必要な /tmp と専用ボリュームのみ例外）を確認。stdout/stderrやtraceにマーカーを出さない。
4. **負荷**：admin1名のみ、先に1world/1controller/1branchの小ケース。1回8 replay以下、最大4096/ジョブ、参照比較1024 receipts/8MiB、gateway 12計算/分、同時backend1。CPU/RSS/volume空き/WALサイズ/429・503・unknown比率を確認。計算の実時間・ピークRSSが暫定許容値を超えれば停止。大量の同時実行や本番負荷試験は禁止。
5. **バックアップと復旧訓練**：trial合成DBの保存停止→既存backupで取得→verify→空の別試験ディレクトリへrestore→sqlite integrity_check/件数・履歴・owner分離の一致を確認。試験前の復旧イメージSHAと復旧手順を記録。実本番データは持ち込まない。
6. **停止・復旧**：異常な429/503/5xxの増加、RSS/CPU・ディスク/WALの急増、他owner参照・機密マーカー検出、checkpoint不整合を停止条件にする。探索のobserved_stopは単位処理の間で停止するだけなので、漏えい疑い時は試験ingressを遮断しserviceを停止。合成DBを隔離保全し、同じ環境の直前イメージへ戻す。復元は空の試験領域にだけ行い、元データを上書きしない。
7. **手続き**：以上の運用確認・CVE residual-risk承認・試験目的/期間/最大件数を書面に残した後、管理者の明示承認を得る。承認前にデプロイ、認証情報変更、フラグON、PR mergeを行わない。

## 7. 次回に残す技術的検証と品質

- 25種類のCVEについてDebianセキュリティ追跡・実際の実行環境のプロセス/ライブラリ利用を定期再確認。現在のN/I判定を「悪用不可能」に昇格しない。
- クラウド実装時のネットワーク入口（実Host・TLS・X-Forwarded-For、127.0.0.1の公開不可）とcapabilityを、試験環境へ許可付きで配置した後に検査。
- 複数ownerはDBレベルの合成テストのみ。単一ユーザーAuth0構成を複数ユーザー公開へ拡張しない。
- 実機観測モデル、全相手非公開状態、特殊CMP、確率効果、live再現性は対象外。常に information_fairness=not_established、live_reproducibility=not_verified、practical_role_covered=false。
- コミット/CIはPR #114にだけ記録する。対象HEADのCI成功前は本修正を検証済みと呼ばない。性能ベースラインと負荷上限は実serviceの隔離環境で測り直す。
- 今回の設計意義：読み取り専用でもDoSになり得る。**保存済みレコードの検証はDBから読む前に廉価なコスト見積りを行い、owner境界と同じスナップショットで検証する**。全面的な検索上限を狭めず、危険な投影処理だけを制限した。代替は全履歴を再構築せず安全な署名付き要約をキャッシュする方法だが、キャッシュ失効/改ざん監査が必要なため今回は採用しない。
