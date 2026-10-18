# 読み取りアプリ：通常／シャドウ切り替え

- 読み取り用フロートの下にスイッチを追加。オンでシャドウ、オフで通常（リトレーン済みを含む）。次に読み取る個体に適用し、設定を保存します。
- 既存の自動判定設定を使っていた場合、最初は「自動判定」と表示します。スイッチを操作するまでは自動判定を維持します。アプリの設定から自動判定へ戻せます。
- 読み取りを押した時点の設定を固定し、解析中のスイッチ変更は次の個体へ適用します。
- 履歴の「通常に変更」「シャドウに変更」で各個体の登録区分を修正。個体値・CP・性別・サイズを保ち、進化先の候補を再判定します。遅れて完了したOCRで手動修正を上書きしません。
- 既存の厳選コピーオーバーレイ、ドラッグ、サイズ変更、共有機能への変更はありません。

## 適用（Windows PowerShell）

ZIPを `C:\new_folder\code` に保存。Android Studioを閉じ、以下をPowerShellへ一度に貼り付けてください。

```powershell
$zip='C:\new_folder\code\PokemonIVReader_ShadowToggle_20261018.zip'; $dir='C:\new_folder\code\PokemonIVReader_ShadowToggle_20261018'; Expand-Archive -LiteralPath $zip -DestinationPath $dir -Force; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dir 'Apply-ShadowToggle.ps1')
```

更新対象は元の `C:\Users\kuros\AndroidStudioProjects\PokemonIVReader`。新しいプロジェクトは作りません。4ファイルの該当箇所だけを更新し、`ReaderShadowControls.kt` を追加します。全置換箇所を先に検査し、未知の版は書き換えず停止します。バックアップ後にビルドし、失敗した場合は元のソースに戻します。

`BUILD SUCCESSFUL` の後、Android Studioで元のプロジェクトを開いてRunしてください。アプリのアンインストールは不要です。既存履歴を残してください。

## 検証状態

手動指定のKotlinコードをコンパイルし、通常指定が画像判定より優先すること、シャドウ指定、自動判定の保持を実行確認。4ファイルへの差分適用と再実行時の同一結果を確認。Androidアプリ全体のビルド、Windows PowerShellでの実行、実機テストは未実施です。

実機で、通常→シャドウ→通常の読み取り、履歴の通常への訂正、再起動後の保持、読取ボタンの移動、スイッチを含む範囲がOCR領域と重なる際の検出を確認してください。
