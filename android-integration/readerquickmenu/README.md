# 読み取りオーバーレイ「⋯」メニュー（段階導入用）

## 機能

- 通常表示は **⋯** の44dp角の角丸ボタンだけ。「その他」という表示文字列は作らない。
- タップ時のみ「厳選」「全体」「非厳選個体をコピー」を展開。非厳選検索式が複数の場合だけ前後切り替えを表示。
- モード変更とコピー成功時は閉じる。OCR開始・オーバーレイ終了時にも `collapse()` を呼ぶ。
- コピーはAndroidの`ClipboardManager`で読み取りオーバーレイ内から直接実行し、検索式キューには渡さない。
- Webの`pokemoniv-search-queue-v1`共有形式のみ`ReaderCleanupStore`に保存。検索式／名前の履歴やOCR履歴から独立させる。
- 低スコア検索は削除対象の自動判定ではない。ゲーム上で検索結果を手動確認する。

## 正式Androidアプリへの組み込み（**未実施**）

正本はユーザーPCの`C:\Users\kuros\AndroidStudioProjects\PokemonIVReader`。
このリポジトリはAndroid完全ソースを含まないため、OCRボタンの親レイアウト、既存モード設定の読み書き、キャプチャ開始処理の正確なフックを検証できていない。**正式プロジェクトを推測して上書きしない。**

1. `ReaderCleanupStore.kt` と `ReaderQuickMenu.kt` を`app/src/main/java/com/example/pokemonivreader/readerquickmenu/`に配置する。
2. 既存の読み取りオーバーレイの **IVボタンがあるLinearLayout** へ`ReaderQuickMenu.attachTo(toolbar)`を追加。別のフローティングボタンを作らない。
3. 既存の厳選／全体モードの **本物のgetter/setter** を`readMode`、`writeMode`に渡す。別のSharedPreferencesキーを増やしてモードを二重管理しない。
4. OCR撮影の直前、外側タップ、オーバーレイ終了時に`collapse()`を呼び、キャプチャ領域にメニューが残らないようにする。外側タップについては既存のタッチ処理に統合し、ゲーム側のタップを妨げない。
5. `OverlayCopyQueueImportActivity.kt` の共有受信をこのブランチ版に更新する（従来の名前付き検索式の分岐は変更しない）。他のAndroid Share入口がある場合は同じ`ReaderCleanupStore.isCleanupPayload()`で低スコアデータを判別する。
6. 追加前に元ソースのバックアップとGit差分を作成し、Gradleビルド・実機でOCR、モード同期、外側タップ、CP読取、別の検索式キューと履歴を確認する。

**安全上の重要事項:** `ReaderQuickMenu`は現状コンポーネントとして作成済みだが、正式な読み取りオーバーレイのホストには未接続。Webで生成・共有したJSONが端末に到着しても、正式APKが更新されるまでは「⋯」からコピーできると扱わない。既存APKをアンインストールしない。

## テスト

`.github/workflows/reader-minimal-menu.yml` にWeb表示の回帰、Kotlinコンパイル、Robolectricでの非厳選JSON永続化／誤データ保護／モードボタン／直接コピーを登録。
このCIは**デモ用テストハーネス**をビルドするだけで、OCR本体の正式APKは生成しない。

## 設計判断

Web上の低スコア検索は`?tool=low-score`だけに表示し、普段の厳選画面では非表示。計算APIとWeb版の安全性警告、既存の推薦計算と共有は残す。Webで計算した低スコア検索式を一度Androidローカルに保存すれば、コピー操作そのものはオフラインで可能になる。
