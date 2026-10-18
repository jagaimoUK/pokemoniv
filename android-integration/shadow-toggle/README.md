# 読み取り履歴の一括変更・丸いオーバーレイ

## 履歴の一括変更

自動読み取り履歴の上部に「全○件を通常に」「全○件をシャドウに」を追加します。

- 何もチェックしていなければ、履歴すべてを変更。
- チェックした個体があれば、「選択○件を通常に」「選択○件をシャドウに」と表示され、選択分だけを変更。
- 個体値・CP・性別・サイズ・その他の履歴情報は保持し、対象の進化先候補を再評価。
- 全対象を準備してから一度に保存。削除済みの個体が混ざる場合や再評価が失敗する場合は、一部だけを保存しない。
- 個別変更ボタンも引き続き利用可能。

## オーバーレイ

外枠と読み取りボタンを十分に丸いカプセル形に変更。スイッチのつまみは円、トラックも丸くします。外枠からはみ出さないようにクリップし、四角いスイッチ背景を除去。低彩度の灰緑と控えめな灰茶色を使い、保存後の緑やエラー時のオレンジも強い色から変更します。

次の読み取りに通常／シャドウを指定する機能、自動判定、ドラッグ、CP・IV表示は維持します。

## 適用（Windows PowerShell）

`PokemonIVReader_BulkShadow_Rounded_20261018.zip` を `C:\new_folder\code` に保存。Android Studioを閉じ、PowerShellへ以下を一度に貼り付けます。

```powershell
$zip='C:\new_folder\code\PokemonIVReader_BulkShadow_Rounded_20261018.zip'; $dir='C:\new_folder\code\PokemonIVReader_BulkShadow_Rounded_20261018'; Expand-Archive -LiteralPath $zip -DestinationPath $dir -Force; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dir 'Apply-BulkShadowRounded.ps1')
```

元の `C:\Users\kuros\AndroidStudioProjects\PokemonIVReader` を更新します。直前のShadowToggle版を適用済みでも、まだ未適用でも使えます。新しいプロジェクトは作りません。過去のReaderUX・コンパクト表示・厳選コピーリストには対象箇所の差分だけを適用し、無関係のコードを上書きしません。

全変更箇所を事前検証し、未知のソースは書き換えず停止。元ファイルをバックアップしてビルドし、失敗すれば復元します。`BUILD SUCCESSFUL` の後、元のプロジェクトをAndroid Studioで開いてRunしてください。アンインストールは不要です。

## 検証

Kotlinで新規ヘルパーをコンパイルし、選択分・全件変更、IV/CP等の保持、候補再評価、対象不一致・重複ID・途中例外時に変更されないことをテスト済み。元の版／直前の版／再適用で同じ修正結果になることを確認。`verification` 配下はCI専用の読み取り専用参照ソースであり、適用スクリプトはコピーしません。

Androidアプリ全体のビルド、Windows上での適用、端末での表示・操作は未確認です。実機で一括変更の対象件数と、角や色合いの見え方を確認してください。
