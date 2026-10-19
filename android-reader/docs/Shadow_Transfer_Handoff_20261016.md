# シャドウのコピー出力・受け渡し修正

基準: PokemonIVReader_Current_Source.zip（2026-10-15に保存された実ソース）。古い参考用Handoff ZIPは編集対象にしなかった。

標準出力:

```text
個体値厳選

# シャドウキバニア シャドウサメハダー
15,11,11
7,11,14
```

## 原因と変更

読み取り側の `ShadowRecognizer.targetName` は `キバニア (シャドウ)` を生成していた。一方、厳選側の日本語別名は接頭語中心で、日本語の括弧表記が未登録だった。出力側と入力側を別々に確認し、この受け渡し例を接続するテストが不足していた。

- 新規 `IvSelectionText.kt` をコピー・共有用のテキスト生成に使用。
- `AutoIvRecords.prompt` は準備完了・シャドウ区分・ランキングの検証後、各種名の末尾 `(シャドウ)` を先頭 `シャドウ` に変換する。
- 手入力の `MainActivity.buildPrompt` も単一種名に同じ変換を使用する。
- 内部の保存名、図鑑名、ランキング照合名は変更しない。ランキングJSONは依然として括弧形式を使用するため、`ShadowRecognizer.targetName` 自体を単純に変えてはいけない。
- 厳選側は以前の括弧表記も互換入力として受理する。各種を正しい `_shadow` IDに割り当て、通常種や地域を推測で置換しない。

## 再発防止

共通仕様・8例は `contracts/iv-text-v1.tsv`。同じファイルを厳選リポジトリにも配置する。
Androidの `IvSelectionTextTest.kt` はこの例で出力を確認する。
厳選リポジトリのCIではAndroidと同一のKotlin生成コードを実行し、実際のテキストをPythonパーサーで読み込む。

リリース前:

```text
python tools/check_selection_contract.py --selection-root /path/to/pokemoniv
gradlew testDebugUnitTest
```

形式変更時は共通仕様・例・両アプリのテストを同時に更新する。Android実機でコピー・共有した内容も確認する。

## 適用と検証範囲

既存Android Studioプロジェクトへ、このZIPの `app/src`、`contracts`、`tools` の変更を反映する。Gradle設定は元のプロジェクトを使用する。このZIP自体にはGradleビルド設定が含まれていないため、完成APKではない。

Python側の既存回帰と受け渡しテスト、および両側のKotlinソース・共通例の一致確認を実施。Kotlin実行の結果は厳選リポジトリの `IV text transfer contract` を参照。Android全体のビルド、JVM JUnit、実機操作はこの環境では未実施。

今回の結果: Python回帰159テスト成功。厳選リポジトリのコミット `0e29262b2b9e00f4f2030a6f0e6c85ceb68cbf8d`、GitHub Actions run `38762596039` でKotlinコンパイル・実出力のPython取り込み・関連回帰がすべて成功した。これはAndroidのAPKビルドや実機操作完了を意味しない。

技未指定の扱いは別問題。キバニアは現在のGL推奨技に含まれず、厳選アプリから技指定を求められる場合がある。種名解析エラーとは区別し、勝手な技補完で回避しない。
