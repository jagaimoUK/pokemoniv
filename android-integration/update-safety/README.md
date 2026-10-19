# PokemonIVReader APK継続更新・図鑑自動対応 引継ぎ（2026-10-19）

**状態：互換性維持の手順のみ記録。APK・メテノ対応・自動更新の実装は未完了。**

## 既存アプリを守る条件
- 正式なPCソース：`C:\Users\kuros\AndroidStudioProjects\PokemonIVReader`。GitHubには現時点で正式Android Studioプロジェクト全体がなく、`android-integration`は部分コード／検証用。
- アプリの`applicationId`、APK署名証明書、`versionCode`をチェックする。既存APKより新しい番号で、同一ID／署名を維持。アプリのアンインストール禁止（履歴消失リスク）。
- `demo/app/build.gradle.kts`の`com.example.pokemonivreader.overlayqueuedemo`は独立デモであり、正式読み取りアプリの更新用ではない。
- OCR、IV、CP、シャドウ、性別／フォーム、履歴SQLite／Preferences、コピーリスト、Android共有、ポケGO上の操作を維持。
- 既存のAndroid StudioとGitHub Actionsが、**同じ正式ソース・同じ署名鍵**を利用する。秘密鍵・パスワード・個人情報はGitHubリポジトリに直接コミットしない。

## スマホのみの期間
署名済みAPKをスマホでダウンロードしてインストールすることは可能。ただし正式Android本体ソースと現在の署名鍵がクラウドにないため、今すぐ既存アプリを安全に上書きできるAPKは未生成。デモAPKを正式アプリ扱いしない。今のアプリを削除しない。

## PC再開時
1. 既存プロジェクトを丸ごとバックアップ。完全なGradle／AndroidManifest／本体Kotlin／リソース／PokemonCatalogをGitHub管理へ統合する。秘密鍵、local.properties、端末データは除く。
2. PCと端末でアプリIDと署名を確認。Android Studioのdebug.keystoreはPCごとに異なることがある。端末の現在のAPKと、新規APKを`Test-ApkUpdateCompatibility.ps1`で比較する。
3. 同一アプリID、同一署名、増加versionCodeでビルド。非破壊データ移行を検証してから**上書きインストール**。アンインストール不要。
4. GitHub Actionsで完全な本体APKをビルドする場合、署名鍵はGitHubの暗号化Secrets等で管理し、チェックに失敗すれば公開しない。PCでも同じ署名とコードを使用。
5. **自動図鑑更新**：種族日本語／英語名・フォーム・性別・GO固有データをデータとして配布。差分取得＋バージョン／真正性チェック＋オフラインキャッシュ＋ロールバック。未知種族もOCR生文字列・CP・IVを失わず一時保存し後日再判定。まずメテノ（Minior）でテスト。
6. OCR精度と図鑑に存在しないケースは別原因として切り分ける。PvPoke Webへの出力名の対応を契約テストで検証。

## 現時点の状態
- APK互換性チェックの独立スクリプト：追加済み（**実機・Windows未検証**）
- 正式Androidソースのクラウド同期：未完了
- 新規種族対応の本体コード：未実装
- 既存端末と同じ署名によるAPK：未生成

READMEの記録・チェックツールは既存のアプリ挙動を変更しない。
