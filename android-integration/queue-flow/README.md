# 厳選コピー：完了後に消す・前後移動・最後の整理用検索式

対象は、厳選コピーオーバーレイ統合済みの元プロジェクトです。

- 検索式と名前を両方コピーすると行が消え、次の個体が上へ詰まります。片方だけなら残ります。
- 「前に戻す」で、完了・スキップした直前の個体を戻せます。繰り返して戻れます。コピー履歴と回数は消しません。完了した個体を戻すと再作業用のチェック表示から始まり、検索式と名前をもう一度両方コピーするまで残ります。
- 「次へ」で現在の個体を飛ばせます。コピー済み扱いにはしません。
- コピー済みボタンのタップでチェック解除、長押しで再コピーする既存操作は維持します。
- 前後の移動状態は取り込み履歴ごとに保存します。アプリ再起動後も戻せます。
- 一覧の最後に、ポケモン・地方フォーム・区分の組み合わせごとに、`…&favorite`、`…&!favorite`、`…` のコピー欄を表示します。全個体が消えた後も残ります。
- 整理用はIVとCP、お気に入り条件を取り除き、地方・shadow/purified・通常の除外条件などを保持します。通常は既存の `!shadow&!purified` も残します。古い `(Alolan)` 等も地方キーワードへ変換します。複合OR等の未対応検索式から整理用は生成しません。
- コピーだけを行います。ゲーム内の博士送りは利用者が操作します。
- OCR、履歴の一括区分変更、Webの計算・共有・OneTap取り込み、既存ドラッグ・サイズ変更・コピー履歴は変更しません。

## 元プロジェクトへ適用

Android Studioを閉じ、ZIPを `C:\new_folder\code` に保存してください。以下は **PowerShell** で実行します。

```powershell
$zip=Get-ChildItem -LiteralPath 'C:\new_folder\code' -File -Filter 'PokemonIVReader_QueueFlow_20261018*.zip' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if(!$zip){throw '更新ZIPが見つかりません'}
$dir=Join-Path 'C:\new_folder\code' ('QueueFlow_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
Expand-Archive -LiteralPath $zip.FullName -DestinationPath $dir
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dir 'Apply-QueueFlow.ps1')
```

## 2026-10-18 互換性修正版

前のZIPで出た `Unsupported controller source` は、ユーザーの最新版に入っているごみ箱終了・スクロール位置保存・外側タップで閉じない操作を、旧版用の部分一致が認識できなかったためです。前の処理は変更前に停止しており、その失敗でソースを書き換えてはいません。

今回はユーザーが提供した `QueueFlow_CurrentSource.zip` 内のControllerに合わせた修正版を用意しました。適用前にファイル全体のSHA256を照合し、一致する検証済みの版だけを更新します。ユーザー提供版では、ごみ箱へのドラッグ終了・スクロール保存・外側タップの通過・OneTap受信・移動とサイズ変更を保持します。古いコンパクト版とOneTap版にもそれぞれの操作を保った専用の修正版を選びます。未知の版を強制上書きしません。

Controller・新規helper・既存Store/Parserを変更前に検証します。バックアップ後に元プロジェクトをビルドし、失敗したら元のソースのバイト列へ復元し、今回作ったhelperを削除します。再適用時は適用済みと判定します。`-VerifyOnly` は照合だけを行い、プロジェクトの変更やバックアップ作成は行いません。

ZIPは必ず今回ダウンロードしたものを新しいフォルダへ展開してください。前の展開フォルダのスクリプトは使わないでください。

`BUILD SUCCESSFUL` 後、`C:\Users\kuros\AndroidStudioProjects\PokemonIVReader` を開き、Runで端末へ反映してください。アンインストールは不要です。

実機では、両方コピーで消える／片方なら残る／前へ戻して再コピー／次へスキップして戻す／最後の3検索式／再起動後の継続を確認してください。Windows適用と実機確認はこの環境からは未実施です。
