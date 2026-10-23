# Pokémon GO 検索式・ニックネーム入力（開発検証版）

この機能は、厳選オーバーレイの既存「検索式」「名前」コピーボタンを残したまま、**「検索入力」「名前入力」**を追加するものです。勝手にバックグラウンドで操作せず、毎回ユーザーのボタン押下に応じて実行します。

## できること・未確認のこと

- Pokémon GOの画面が前面にあるときのみ処理する。他のアプリの入力欄は操作しない。
- 検索欄がAndroidアクセシビリティに公開されていれば検索式を一括入力する。
- 名前の編集欄が公開されていれば現在の文字列をまるごと新しいニックネームに置換する（追記ではない）。
- 「Search」や「名前を変更」がアクセシビリティ上で認識できる場合、編集欄を開くクリックを試みる。認識できなければ、ユーザーが検索欄や鉛筆マークを**手動で開いてから**入力ボタンを再実行する。
- GOの画面座標に対する推測タップ、ゲーム内部APIアクセス、ゲームファイル改変、名前変更の最終確定は行わない。
- 自動入力成功時も**コピー済み・ニックネーム変更完了の記録は自動で付けない**。従来のコピー・チェック・履歴・スキップはそのまま使用できる。
- GO実機でのSearch/鉛筆マークのアクセス可能性と、入力後の表示反映は**未確認**。動作することを保証しない。

## Android元プロジェクトへの適用

正式なAndroid Studioプロジェクト:
`C:\Users\kuros\AndroidStudioProjects\PokemonIVReader`

1. GitHubの開発ブランチ `feature/go-text-input-guarded-20261023` から **Download ZIP** で取得する（private repositoryなのでログインが必要）。
2. ZIPを `C:\new_folder\code` に保存する。
3. **Android Studioを閉じてからPowerShell** で以下を実行する（CMDには貼り付けない）。

```powershell
$zip=Get-ChildItem -LiteralPath 'C:\new_folder\code' -Filter 'pokemoniv-feature-go-text-input-guarded-20261023*.zip' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if(!$zip){throw 'GitHubのブランチZIPが見つかりません'}
$dir=Join-Path 'C:\new_folder\code' ('GoTextInput_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
Expand-Archive -LiteralPath $zip.FullName -DestinationPath $dir
$patch=Get-ChildItem -LiteralPath $dir -Recurse -File -Filter 'Apply-GoTextInput.ps1' | Select-Object -First 1
if(!$patch){throw 'Apply-GoTextInput.ps1が見つかりません'}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $patch.FullName -VerifyOnly
if($LASTEXITCODE -ne 0){throw '照合に失敗したので元のコードは変更していません'}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $patch.FullName
```

- スクリプトは**既存ファイルの構造を確認してから**修正する。未知のControllerなら停止する。強制上書きしない。
- 元コード・Manifestをバックアップする。Gradleでビルドに失敗したら新規コードとManifest変更を元に戻す。
- `BUILD SUCCESSFUL` が出たら元のAndroid Studioプロジェクトを開き、Runで実機へ反映する。実機APK反映は未実施。
- 端末の設定→ユーザー補助から「厳選テキスト入力」を有効にする必要がある（Androidの設定によっては追加確認が必要）。
- 操作できない場合は、従来の「検索式」「名前」コピーを使う。コピー以外の作業を勝手に進めない。

## 確認項目

1. GOの検索画面で「検索入力」を押したとき、既存の検索語が残らず完全置換されるか。
2. ポケモンの評価画面で「名前入力」を押し、鉛筆マークを経て編集欄に名前が入るか。表示上の鉛筆がアクセシビリティから読めない場合は手動で開く。
3. 編集画面の文字列が追記ではなく全置換になるか。ユーザー操作で確定した後、ポケモンの名前を確認する。
4. 対象がGO以外のアプリなら動作しないか。
5. 自動入力後もコピー済み/履歴が勝手に変更されず、OCRや再コピー・既存検索式などが壊れていないか。

## 利用規約

第三者製ソフトからのゲーム操作は、Pokémon GOの不正行為規定に抵触する可能性がある。公式の明示的な許可は未確認。ユーザー補助の権限は任意であり、利用前に本人が判断する。BANされないことは保証できない。
