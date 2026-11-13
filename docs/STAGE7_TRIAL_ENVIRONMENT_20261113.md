# 第7段階：管理者本人専用・隔離試験環境の設計とゲート

作成日 2026-11-13 JST。正本は第6段階 `docs/STAGE6_SECURITY_RELEASE_GATE_20261113.md`。この資料は**準備指示であり、実際の公開・試験フラグONの承認ではない**。CI実行後の実測数値はPR #113の第7段階チェックポイントを正本とする。

## 1. 環境比較（実在ソースからの設計上の判断）
| 選択肢 | 既存アプリとの相性 | 隔離・費用 | 判断 |
|---|---|---|---|
| **ローカルDocker（推奨）** | Dockerfileとstart.shをそのまま使い、合成DBを専用volumeに閉じ込める | 新規クラウド課金なし。net=none/loopback検証、CPU/RAM/PID/capsをCLIで明示可能。ただし端末にDockerが必要 | 最初にCI使い捨てruntime smoke。管理者が承認後、PC上だけの試験 |
| Railway 新規プロジェクト | railway.jsonにDockerfileとhealthが定義済み。独立volumeが必要 | 継続稼働・volumeに料金が発生し得る。public domainを発行しなければ外部HTTP入口はないが、本人ブラウザのアクセス方法を別途設計する必要 | 第2候補。既存プロジェクトのサービスを使い回さない |
| Google Cloud Run 新規プロジェクト | Dockerfileを変更なく使うことは**永続性面で不可**。コンテナFSは一時的でSQLite履歴が消える | internal ingressとIAMは構成可能だが、永続DB/volumeとprivate接続に追加設計・費用・検証が必要 | 今回は選ばない。Cloud Run用の永続保存移行とセットで再検討 |

根拠：Docker公式 `https://docs.docker.com/engine/containers/run/`、Railway `https://docs.railway.com/networking/public-networking`、Google Cloud Run `https://docs.cloud.google.com/run/docs/securing/ingress` と `https://docs.cloud.google.com/run/docs/container-contract`。料金は地域・プラン・使用量で変化するため見積もりを確定額として記載しない。

## 2. 試験の必須分離
- 本番とは異なる名前とアカウント/プロジェクト、サービス、永続volume、空のDB、管理者の合成鍵。**本番のpvpoke DB、バックアップ、環境変数、Auth0 subject、cookie鍵を一切コピーしない**。
- 既存Git branchを参照し、コミットSHAとimage digestを固定する。新規ファイルは合成データだけ。マージ・PR状態・本番に触れない。
- 管理者本人のみ。マルチテナント対応なし。入口は原則ネットワークなしで `docker exec` からAPI検証し、ブラウザ試験を許す場合も明示承認後にloopback限定公開と追加認証を実際に検証する。
- できればCPU 1、memory 768MiB、swap制限、PID 128、cap-drop ALL、no-new-privileges。初期root不要の手順を使う。コンテナ内 `/tmp` と `/data` 以外のrootfs read-onlyは**現状未検証**で、実運用向けに無条件に要求しない。
- outboundは無効（`--network none`）。ゲームデータはDocker build時に検証・同梱される。CIでネット遮断下の起動/動作を確認する。ローカルの管理者ブラウザからの接続はこのモードでは不可（`docker exec`のみ）。

## 3. 承認後の手動コマンド例（**今は実行しない**）
以下は合成試験専用の例であり、Docker daemonへのアクセス権は本番データへのアクセス権と同様に慎重に扱う。

```sh
# 前提：管理者所有のPC、専用の空DB。別リポジトリは作らない。
git switch feature/missing-observed-integration-20261113
git status --short
git rev-parse HEAD
docker build -t pokemoniv-stage7-local .
# 秘密の鍵はシェル履歴に直書きせず、保護されたenv-fileを使用。
# envファイルには PVP_API_KEY、PVP_ARCHIVE_DIR=/data、
# PVP_MCP_URL=https://stage7.invalid/mcp を書き、
# PVP_OBSERVED_SEARCH_ENABLED=0 のままにする。
# 実行前に--env-fileのアクセス権を600にする。
docker volume create pokemoniv-stage7-data
docker run --rm --name pokemoniv-stage7-init --network none \
  -v pokemoniv-stage7-data:/data --entrypoint sh pokemoniv-stage7-local \
  -c 'mkdir -p /data/pvpoke_archives && chown -R 10001:10001 /data/pvpoke_archives'
docker run -d --name pokemoniv-stage7-only --network none \
  --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges \
  --memory 768m --memory-swap 768m --cpus 1 --pids-limit 128 \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 \
  --env-file /path/to/your/private-stage7.env \
  -v pokemoniv-stage7-data:/data --entrypoint /app/start.sh pokemoniv-stage7-local
docker exec pokemoniv-stage7-only python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8787/health').status)"
docker stats --no-stream pokemoniv-stage7-only
# 停止：volumeは検証・バックアップ後まで保持
docker stop pokemoniv-stage7-only
```

**最小限のenvの追加**：`PVP_BATTLE_API_ENABLED=1`、`PVP_SANDBOX_ENABLED=1`、`PVP_MISSING_ANALYSIS_ENABLED=1` は合成テスト時のみ。 `PVP_OBSERVED_SEARCH_ENABLED` は承認前0。本番のrootキーを再利用しない。 `PVP_ARCHIVE_DIR=/data` の配下に `pvpoke_archives` が作成される。マウント先を上書きしない。停止後 `docker volume rm` はバックアップを別隔離先へ検証復旧できたときだけ実施。

## 4. 実効検証の完了条件と証拠分類
- **CIで可能**：非root/uid10001、cap全削除、NoNewPrivs、network noneで起動とAPI拒否、合成トークンの公開HTML非混入、HTTP制限、CPU/RSS/PID/cgroupの実数、正常な保存評価の20回程度の多重読取、1024件集計・1025件上限拒否、隔離ENOSPC/WAL/DELETE、バックアップ/復元既存テスト。
- **CIだけでは不十分**：管理者PCのファイアウォール、Railway ingress、クラウドIAMと課金、常設volumeの権限・失敗復旧、NAT/route、実ユーザーブラウザの通信、外部ネットからの拒否実測、32〜4096本の合法native履歴のp95/RSS、異常切断中のbackend停止保証、独立担当の安全性レビュー。
- 一部の検証をCI実施済みと主張するのは、対象commitのワークフロー結果・ログに証拠がある場合に限る。

## 5. バックアップ、停止、復旧（合成データ）
- 既存 `tools/cloud_migration_backup.py` と `tests/test_cloud_migration_backup.py`、`tests/test_real_enospc.py` を再利用。混在ファイルを含むSQLite/WAL snapshotとmanifest/hash/内容検証、別の隔離directoryにrestoreし `PRAGMA integrity_check`、owner/history/観測/設定のハッシュと件数を比較。停電相当の`SIGKILL`や保存中停止の実環境試験は未完了。
- 安全停止手順：`docker stop pokemoniv-stage7-only`。合成データ検証が必要なら先にコピーを読み取り専用の別ボリュームへ取り、DBを直接上書きしない。volumeは自動削除しない。失敗/不一致なら試験中断、入口遮断、原本保存と再検証。異常時の監視項目：5xx/429、CPU/RSS、OOM、p50/p95、ディスク空きとWAL、ジョブ数、所有状態と保存イベント。
- 復元は止めた試験サービスの**別ボリューム**で行い、既存スクリプトの`verify`/`restore`後にSQLiteの`integrity_check`・件数/owner/hash一致を確認する。成功前にデータを消去しない。

## 6. 公開ゲート
- **A（現状の既定判定）**：合成CIは本番と独立した実クラウド/管理者PC上の永続環境、安全なブラウザ入口、別レビュアーをまだ証明しない。
- **Bへ進む必要条件**：試験インスタンスの作成に管理者が明示承認、上の全境界と復元の実証、CPU/RSS/ディスク/通信制御の実測、25未修正CVEの重大な間接到達性の再審査、独立レビューに加え、止める手順の実施ログ。
- **Cは対象外**。一般向けのユーザー登録/認可や実機戦術の保証は認めない。

## 7. 第7段階の追加修正：事前容量確認とリプレイを同じスナップショットへ

コード上確認したTOCTOU（確認と使用の間の状態変化）：第6段階の`compare_observed`は、1024件/16MiBの累積上限をSQLite読取トランザクションで確認したあと、そのトランザクションを閉じて、別の読取トランザクションで`ObservedSearch._read`を呼び出していた。並行`observed_step`で新しいreceiptsが追加されると、確認したcheckpointと実際に展開されるcheckpointが異なる可能性があった。

**対策**：同一`store._reader()`によるSQLiteスナップショット内で累積予算検証と保存ジョブの読込・検証を一括実施し、読込後の計算・表示は確定済みのメモリ上のスナップショットだけを参照する。サイズ・件数上限、既存テーブル、Job保存形式、通常PvPoke計算、所有者判定は変更しない。

**新しい合成回帰**：1024件・16MiBのちょうど境界は許可、1025件・16MiB+1Bは読込前に拒否、foreign owner不可視、事前確認と読込が同一DB connectionであること、複数読取スレッドで同じ判定になること。**並行writerが実際に書込み中の全インターリーブの実証ではない**。証拠は当該コミットのCIの`tests/test_missing_observed_evidence.py`で確認すること。 
