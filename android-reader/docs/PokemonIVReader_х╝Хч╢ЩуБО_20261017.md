# Pokémon GO 個体値読み取りAndroidアプリ 引継ぎ（最新版）

**引継ぎ確認日：2026-10-17（JST）**  
**ソース基準：ユーザーから受領した `PokemonIVReader_CURRENT_FOR_GPT.zip`（実PCエクスポート）**  
**元ZIPのSHA256：`8cce72f1bcc5d07eb0a8fe691661dcd886d5c900513b9f3c717d0b05caa260c2`**

## 1. 今回確定した状態

- Android読み取りアプリの正式な作業基準は、**2026-10-17に受領した実PCソースのZIP**。旧 `PokemonIVReader_Code_Handoff_20261015.zip` は参考資料であり、現行コードの上書きに使用しない。
- 元ZIPの `handoff/SOURCE_MANIFEST.json` には `kind=ACTUAL_PC_PROJECT_SOURCE`、エクスポート日時 `2026-10-16T15:14:31.9744211Z`、Gitブランチ `master`、Git HEAD `89285c0c0c506b8765ab5142bfd9c743b1e187cb`、`git_dirty=true`、`git_remote` 空、`github_push_performed=false` と記録されている。UTC日時は日本時間2026-10-17 00:14頃に当たる。
- マニフェストに列挙された61ファイルの SHA256 が、元ZIPに入っている実際のファイルバイトとすべて一致した。※マニフェスト・引継ぎ文書2件は61ファイルの対象外である。
- Android Gradleプロジェクト一式（`gradlew.bat`、`settings.gradle.kts`、`app/build.gradle.kts`、`AndroidManifest.xml` 等）あり。Kotlin、Jetpack Compose、Android minSdk 28、targetSdk 37、Gradle wrapper 9.6.0。
- 辞書 `pokemon_catalog.json` は **1,145エントリ**。`pvpoke_overall_1500.json` は **1,153エントリ**、総合スコア70点以上のデータ。ランキングと全種の両方の対象モードがソースに存在する。
- 共有テキスト契約 `contracts/iv-text-v1.tsv` と `IvSelectionText.kt` は、2026-10-17にGitHubで確認した厳選Webアプリ `jagaimoUK/pokemoniv` の `contracts/iv-text-v1.tsv` および `contracts/reader/IvSelectionText.kt` と**Git blob SHAが完全一致**した。標準契約の8事例はKotlinの単独テストで通過。ただし厳選Webアプリの本番投入状態やAndroid全体の動作を保証するものではない。
- **Android全体のGradleビルド・実機テスト・GitHub pushは未実施**。ZIPとGitHubが同期済みとは言わない。ZIPは未コミットの変更も含む作業ツリーのスナップショットである。コミットIDだけでZIPの中身を特定できない。

## 2. プロジェクトの目的と分離

`Pokémon GO` → 評価画面取得（MediaProjection + フロートUI）→ IV3本のバーを認識 → 名前/CPをOCR → 複数の読み取り結果を記録 → 進化・フォルム・性別・シャドウ区分とCP1500条件を確認 → 厳選Webアプリ/ChatGPTへ「個体値厳選」テキストを渡す。

- IVの順は **攻撃,防御,HP**、各0～15。
- IVバーは画像の色・形状で判定する。名前とCPのOCRは別処理。CP認識失敗とIV認識失敗を混同しない。
- Android読み取りアプリと、Railway/PvPoke基盤の個体値厳選Webアプリは**別プロジェクト**。後者の `jagaimoUK/pokemoniv` にAndroidコードをpushしない。
- GPTの有料API利用を必須にせず、コピー/Android共有を基本とする。

## 3. 現行ソースで存在を確認した主な機能（動作は未保証）

| 機能 | 関連ファイル / 静的確認 |
|---|---|
| 画面キャプチャ・フロートUI | `ScreenCaptureService.kt`, `MainActivity.kt` / MediaProjection の処理あり |
| IVバー解析 | `IvBarRecognizer.kt` |
| CP・名前OCR | `ScreenTextRecognizer.kt`、`OverlayIvProcessor.kt` / 非同期処理あり |
| 仮保存・記録とコピー | `AutoIvRecords.kt`、`MainActivity.kt` / 未確認状態やCP未認識を扱う分岐あり |
| 横スワイプ時の重複対策・キュー | `CaptureGate.kt`, `ScreenCaptureService.kt` / 画像署名、安定フレーム、4件までの処理管理あり |
| 性別判定 / 進化先の扱い | `GenderRecognizer.kt`、`PokemonCatalog.kt`、`EvolutionMath.kt` |
| シャドウ状態の判定 | `ShadowRecognizer.kt`、`ShadowBurst.kt` / 自動・通常固定・シャドウ固定のモードあり |
| 特殊なフォーム | `PumpkinForms.kt`, `PumpkinHeightClassifier.kt` |
| 対象選択（70点以上/全種） | `RankingEligibility.kt` とJSONアセット |
| 厳選Web側との共通テキスト契約 | `IvSelectionText.kt`、`contracts/iv-text-v1.tsv`、`IvSelectionTextTest.kt` |

## 4. 絶対に維持する入力・出力仕様

- 出力形式例（各IVは独立行）：

```text
個体値厳選

# シャドウキバニア シャドウサメハダー
15,11,11
7,11,14
```

- 旧表記 `# キバニア (シャドウ) サメハダー (シャドウ)`、全角括弧表記も転送契約上の互換入力として扱う。
- シャドウ接頭辞を重複させない。通常/シャドウと地方の姿・性別で取り違えない。
- 技名は入力必須にしない。複数進化先や複数種グループのテキストを維持。
- **厳選Webアプリの検索式を削除しない**。各個体について検索式→改行→ニックネームを繰り返す形式。一括コピーも必要。
- Pokémon GO上のコンパクトな結果オーバーレイは、検索式とニックネーム別にコピー済みチェックを付け、**コピー済みでも何度でも再コピー可能**にする（両アプリ連携時の要件。現行読み取りアプリへの完全実装は未確定）。
- メタ対面、唯一勝利、不利シールドでの改善、完全劣後排除などの既存厳選ロジックを、読み取りアプリの高速化の名目で勝手に変更しない。

## 5. 未解決事項と優先度

1. **P0：IV/CP/名前それぞれの読取ステータスをUIで明示**。CP未認識の再確認作業を減らす。OCR失敗時は誤登録せず仮保存・再判定する。
2. **P0：連続・高速スワイプ時の読み落とし、二重登録、フレーム混線を実機で検証**。処理を速くしつつ精度を落とさない。バッチ処理の実装存在だけで解決済みにしない。
3. **P0：フロートボタンを押してから読み取り完了するまでの速度測定**。各段階を分離して計測し、精度や対象を削減しない。
4. **P1：MediaProjectionの再許可とクリップボード/削除ポップアップ**。OSの制約を守り、減らせる手動操作を減らす。
5. **P1：シャドウ・性別・地方の姿・パンプジンのサイズ等の識別確認**。性別で進化条件や能力が異なる種を混同しない。種族値差などを未検証のまま決めつけない。
6. **P1：Android読み取りアプリとWeb厳選アプリの最新の受渡し契約を維持**。両側の同時更新が必要な場合は双方のテストを実施。
7. **P0：ビルド・単体テスト・実機での画面共有とゲーム画面読み取りの受入テスト**。Gradle動作未確認。Android Studioの実機環境で確認する。

## 6. GitHubの状態と初回登録

2026-10-17の接続済みGitHubリポジトリ一覧に、Android専用 `PokemonIVReader` リポジトリは確認できなかった。ローカル `master` の `origin` も空である。よって、**GitHubへの最新ソース反映は未完了**。

### まずPCの現在のソースを保全

ユーザーが今回送ったZIPが最新の受領データ。以後の編集前に、PC上でさらに変更がないか確認し、必要なら再エクスポートする。バックアップと`.git`履歴を消さない。

### GitHubの空のPrivateリポジトリを作った後のコマンド例

```powershell
$project = "$env:USERPROFILE\AndroidStudioProjects\PokemonIVReader"
git -C $project remote -v
# origin が存在しない場合だけ。GitHub上に空のPrivateリポジトリ作成後に実行
git -C $project remote add origin https://github.com/jagaimoUK/PokemonIVReader.git
# 引継ぎ書をこのリポジトリの docs/ に配置した場合は、それも含めて登録
git -C $project add -A -- app gradle gradlew gradlew.bat gradle.properties build.gradle.kts settings.gradle.kts tools contracts docs .gitignore
# ここで .idea/、backups/、資格情報が紛れ込んでいないか必ず確認
git -C $project diff --cached --name-only
git -C $project commit -m "Sync Android reader source and handoff"
git -C $project push -u origin master
git -C $project status -sb
```

**注意**：`origin` が登録済みの場合は `remote add` を繰り返さない。`git add` に列挙したパスが存在しない場合は、付属の `Sync-PokemonIVReader.ps1 -Push` を使用する方が安全。ステージ済み危険ファイルや認証情報を確認せずコミットしない。`git reset --hard`、`git clean -fd`、`git push --force` はしない。`git pull --rebase` も闇雲に実行しない。

### 現時点の同期状態

| 同期対象 | 状態 |
|---|---|
| PC → GPT | **受領ZIPの全61ソースファイルについて整合性確認済み**（アップロード時点） |
| Androidアプリ → 厳選Webアプリの転送契約 | **2ファイルのGit blob SHA一致**（受領時点） |
| PC → GitHub（Android専用） | **未完了**（`origin`未設定） |
| AndroidアプリのGradleビルド | **未検証** |
| 実機動作 | **未検証** |

## 7. これからの標準引継ぎ手順

1. PC上の最新版を `Sync-PokemonIVReader.ps1` でエクスポートし、`SOURCE_MANIFEST.json` とSHA256付きZIPをGPTへ渡す。
2. GPTは**最新受領ZIPを唯一のソース基準**として扱い、過去の参考ZIPで上書きしない。最新仕様・修正履歴・検証結果を `handoff/引継ぎ_YYYYMMDD.md` に更新する。
3. GPTがコードを修正した場合は、差分の説明と**完全なプロジェクトZIP**を渡す。PC適用前にバックアップし、既存変更との差分を確認する。
4. Android StudioでGradle同期・ビルド・必要な単体/実機テストを行い、確認済みの項目だけを報告する。
5. GitHubへ通常pushした後で再エクスポートし、新しいGit HEADと作業ツリー状態、ZIP SHA256を記録する。GitHubとZIPの一致はGitがクリーンで対象ファイルが一致することを検査して初めて認定する。

## 8. 改修時の固定ルール

- 指定されていない機能・計算・表示・コピー形式を消さない。
- 精度維持を優先し、高速化で対象や計算条件を減らさない。
- 修正に関連する回帰テストを行い、実機未確認の項目を成功と報告しない。
- 引継ぎ文書を更新してソースZIPに同梱し、次回のチャットで繰り返し説明させない。
- この文書の「確認済み」は、受領ZIPのコード存在・ハッシュ一致・局所テストを意味する。全体の実装完成や品質保証を意味しない。
