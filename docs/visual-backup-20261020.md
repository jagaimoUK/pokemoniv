# 見本のクラウド保存（2026-10-20 / 1.3.0）

## 利用方法

署名済みAPK v1.3.0（versionCode 9）に更新する。履歴の「見本のクラウド保存」→「接続コードを取得」を開き、既存の厳選Webアプリと同じ接続キーでログインする。発行したバックアップ専用コードをアプリに貼り付けて接続する。既存のWebログインCookieがあれば再入力不要。

接続後、見本の登録・訂正・削除でWi-Fiなどの非従量回線に自動保存を予約する。最短15秒後、OSの制約に従って実行し、15分間隔の再確認も行う。直ちに確認する場合は「今すぐバックアップ」を使う。再起動後も端末の見本と接続を保持する。接続状態はAndroid KeystoreのAES-GCMで暗号化し、noBackupFilesDirに保存する。

別端末や再インストール後は再接続して「クラウドから見本を復元」を実行する。クラウドに既存データがある初回接続では自動アップロードを止め、空の端末による上書きを防ぐ。復元は端末の見本と統合する。重複を除き、各姿24件・全体512件の上限内で手動登録を優先する。別端末の更新を検出した場合も自動保存を停止し、復元を案内する。手動の保存は確認画面でクラウドの置き換えを明示する。

## 保存内容・範囲

正解付きの224×224画像、1024次元の特徴、speciesId、manual/typesの登録元、日時だけをZIPに保存する。未確定の比較画像、CP、個体値、読み取り履歴は送らない。固定モデルの重みは更新しない。見本を復元すると以後の比較に使われる。見本が増えれば必ず正解する保証はなく、通常・地方両方の見本と既存の閾値条件が必要。

現段階は既存の単一所有者認証に結び付く非公開バックアップ。同じ所有者の接続コードを使う端末は一つの保存先を共有する。不特定多数への配布・他人との自動見本共有は実装していない。多数利用者向けにはユーザー認証、利用者別オブジェクトキー、容量制限を先に追加する。

## 構成

- Android: VisualMemoryBackup / VisualCloudBackup / VisualCloudControls、WorkManager 2.9.1。
- バックエンド: jagaimoUK/pokemoniv の visual_backup.py と pvpoke_mcp_remote.py。
- Railway: heroic-warmth / production、pokemonivサービスと同じiadリージョンのBucket iv-visual-backups。
- 非公開オブジェクト: visual-memory/v1/owner/latest.zip。標準ZIP＋JSON＋JPEG＋big-endian float32、上限16MiB、展開32MiB。
- 通信先: https://pokemoniv-production.up.railway.app/visual-backup/v1/ のPOST status/upload/download。接続画面 /reader-backup、既存認証によるコード発行 /app-api/visual-backup-token。
- 専用Bearerは365日有効。MCPや厳選APIには使えない。元の接続キー変更で無効化できる。Bucket秘密鍵をAPKに含めない。
- SHA256で転送を確認し、S3のETag条件付き書き込みで競合を拒否する。ZIPのパス・モデル・ラベル・件数・特徴の有限値を検証し、不正な復元は既存の見本を変更しない。

## 後でCloudflare R2へ移す

Androidの接続先URLとZIP形式は維持する。移行時に自動保存を停止し、上記プレフィックスをR2の非公開Bucketへコピーする。コピー前後のSHA256を照合し、元のBucketは動作確認まで残す。モデルは再学習せず、画像・特徴・ラベルをまとめて引き継ぐ。

バックエンドのVISUAL_BACKUP_S3_ENDPOINT / BUCKET / REGION / ACCESS_KEY_ID / SECRET_ACCESS_KEY / STYLEをR2へ切り替える。REGIONはauto、STYLEはpath。現在はRailway Bucketの変数参照を使い、秘密鍵の直書きを避ける。サービス起動時はテスト用オブジェクトで条件付き作成・更新、古いETagの拒否、取得・削除を確認する。healthのvisual_backup.storage_probeとログのPASSを確認する。

保存先が変わるとETagが変わり、端末の自動保存は競合として停止し得る。その場合は各端末で「復元」して同期基準を更新する。既存APIキーを維持すれば専用接続コードは継続可能。R2アカウントの作成や実際の移行は今回行わない。

## 検証と残る確認

ローカルでコア1,153項目、JUnit32件（新規バックアップ4件含む）、サーバーの保存・復元・認証を含む20件が成功。ZIP往復後の再起動・通常／ガラルの比較、破損ZIP時の既存保持、復元の件数上限・手動優先を検証した。Androidフルビルド・署名APK、Railway本番ストレージの結果はGitHub Actionsと本番healthで確認する。スマートフォンでの接続・Wi-Fiバックアップ・認識精度は実機確認が必要。

## Railway本番の確認結果

デプロイ117787fb-9b35-4e52-b332-2143699af639（コミット2477266）がSUCCESS。実Bucketで条件付き保存・取得・削除の起動プローブがPASS。公開healthはenabled=true / storage_probe=true、接続画面はHTTP 200、未認証の保存APIはHTTP 401を確認した。Bucket IDは17520f30-acc8-4394-b23e-a4084c7b50e8、環境production。検証用オブジェクトは削除済みで、利用者の見本はまだ端末から接続・保存していない。秘密鍵はBucket変数参照で管理する。

新規7件のバックアップテストをGitHub Actions「Visual reference backup」に追加。Androidのビルド状況は https://github.com/jagaimoUK/PokemonIVReader/actions/runs/39447857066 と https://github.com/jagaimoUK/PokemonIVReader/actions/runs/39447864213 。
