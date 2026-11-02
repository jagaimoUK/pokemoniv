# Cloud Run 検証環境準備（読み取り専用の事前確認）

更新：2026-11-02。対象は **jagaimoUK/pokemoniv** の
`migration/cloud-run-20261101`、PR #88。Railway本番環境、DNS、メタ、
SQLite、認証失効データ、個体値、学習見本、Androidバックアップの
**変更・削除・本番切り替えは禁止**。

## 現時点で確認済み

- Cloud Run用Dockerfile、`pvpoke_cloud_runtime.py` の fail-closed ガード、
  `cloudbuild.cloudrun.yaml` の費用承認ゲートは実装・既存CIで検証済み。
- Railway本番は `main` / `/data` volume / private visual-backup bucket で稼働中。
- Google CloudのプロジェクトID、請求アカウント、IAM、予算、Cloud Shell認証状態は未確認。
  このチャットからGoogle Cloudを操作できる連携も現時点では利用できない。
- 検証サービスの実URL、Google Cloud上のリソース作成実績は未確認。

## 1. ユーザー本人が行う操作（無料で確認可能な範囲）

スマートフォンChromeで [Google Cloud Console](https://console.cloud.google.com/)
を開き、上部のプロジェクト選択からテスト用プロジェクトを選択する。
**プロジェクト名ではなくプロジェクトID**を確認する。
既存の本番用途があるプロジェクトは流用せず、必要な場合は別プロジェクトを検討する。
新規作成や請求紐付けを今すぐ行う必要はない。

Google Cloud Shellが利用でき、`gcloud` のログインが完了している場合、
このGitHubブランチをCloud Shellで取得して次の読み取り専用コマンドを実行する。
`PROJECT_ID` は自分で確認した値に置き換える。

```sh
python3 tools/cloud_run_validation_preflight.py --project PROJECT_ID --region us-central1
```

**このコマンドは読み取り専用**。請求の有効化、API有効化、IAM変更、
秘密の取得、Registry作成、Cloud Runデプロイは一切行わない。
終了コード2は未準備、0は既存リソースの簡易確認を通過した意味。
Cloud Runサービスが private か、ラベルが validation かもチェックする。
  IAMのallUsers許可に加え、Invoker IAMチェック無効化も公開として拒否する。
JSONの `ready_for_review=true` は本番移行・実デプロイを許可する意味ではない。

結果にある `unknown_or_denied` は権限不足または取得失敗の可能性があり、
`missing_or_denied` を「存在しない」と断定しない。
アカウント識別子や認証情報は出力しないが、プロジェクトIDが含まれるので
結果の公開投稿は避ける。

## 2. リソース作成前の承認ゲート

請求アカウントが必要な操作は、費用・権限を利用者が理解したうえで
**個別承認後**に実行する。Cloud Run無料枠は0円保証ではない。

1. 請求方法を確認して予算アラートを設定する。例：USD 1/月、
   50% / 90% / 100% アラート。アラートは課金停止装置ではない。
   Cloud Runで使える *spend cap budgets* は現在利用できる場合があるが、
   Cloud Build・Artifact Registry・Secret Managerまで全てを停止するものではない。
2. リージョンを選ぶ（初期候補 `us-central1`、東京とも比較）。
   請求/無料枠の有効条件、通信料金、同リージョンの利用可能サービスを確認する。
3. 必要なAPI（Cloud Run / Cloud Build / Artifact Registry / Secret Manager）
   の有効化、Registryの新規作成、検証用の独立したサービスアカウントと
   権限付与をレビューする。Firebase/Firestoreは現段階では不要。
4. 検証専用の Secret Manager APIキーを作り、
   **Railway本番のAPIキー・S3/visual-backup認証情報を決して再利用しない**。
5. 使い捨てCloud Runサービス `pokemoniv-validation` を
   IAM非公開・`pokemoniv_role=validation` ラベル付きで事前作成する。
   `min=0`, `max=1`, リクエスト課金、1 vCPU/2 GiBを初期検証候補にする。
   アプリの長時間計算を本番相当として認める設定ではない。

**ここまでのリソースは現時点では未作成・未確認。**
前提条件が揃ってから、既存 `cloudbuild.cloudrun.yaml` を使う。
`_COST_APPROVAL` の既定値は `NOT_APPROVED` で、
承認していない状態ではビルド自体を開始しない（起動だけでも費用発生の可能性）。

## 3. 検証環境の合格条件

- 本番と異なる Cloud Run private URL を取得し、匿名アクセス拒否を確認。
- テスト用の鍵と**合成データのみ**で `/health` と必要なAPIを確認。
- 非認証のリクエストとログイン前画面が情報を露出しない。
- コールドスタート・再起動・0インスタンスからの再開を確認。
- SQLite・ジョブ・結果を一時領域に置いたデモでは、
  データ永続化の保証と誤認しない。複数リクエスト・計算中断は別途設計。
- Google Cloudの課金・ログ・レートを検証し、
  不要なリビジョンやビルドを増やさない。
- 検証失敗時は Cloud Run 側のみ停止。Railwayは継続稼働する。

**Cloud Run本番切り替えは別途承認があるまで禁止。**
Firestoreの保存アダプター、永続Jobs、過去結果のオブジェクト保存、
最終差分の照合が必要である。詳細は `docs/CLOUD_RUN_MIGRATION.md` を参照。

参考：Google Cloud公式 Cloud Run IAM、請求・予算（必ず実施直前に条件確認）
https://docs.cloud.google.com/run/docs/authenticating/overview
https://docs.cloud.google.com/run/docs/triggering/https-request
https://docs.cloud.google.com/billing/docs/how-to/budgets
https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps
