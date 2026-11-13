## 2026-11-13 JST 第5段階：不足分析への観測戦術リンクとモバイルUI（CI確認前）

対象：Draft PR #113、ブランチ `feature/missing-observed-integration-20261113`。第4段階の正本は `a9d6ee55a2b7745e8d82c28426d0feb2269feed1`、PR #111/#112はDraft・未マージ。GitHub上の修正ブランチで作業し、他の未コミット変更は確認できない。前回Work内の非永続な差分は回収していない。

| 工程 | 状態 | 確認済み | 残作業 |
|---|---|---|---|
| 現行ソース・PR・設計確認 | 完了 | #112 HEADと観測設計、欠損比較API、Sandbox画面を確認 | なし |
| 不足分析と観測結果の照合 | 実装済み・CI再検証中 | `pvpoke_observed_evidence.py`、`pvpoke_missing_comparison.py`。既存評価・保有者・版・ビルド・相手・初期状態の一致を確認。未対応Sandboxフォームは他の適用可能な一致を妨げない | CI全件、追加異常系 |
| モバイル操作・結果の分類 | 実装済み・CI再検証中 | `pvpoke_missing_ui.py` の候補別参考表示、固定戦術の横並び概要、フォームのセッション復元。Sandbox画面から観測IDを安全に引き継ぐ | 320/390px Chromium、実機未実施 |
| セキュリティ・保全 | 実装済み・CI再検証中 | ownerに束縛された認証API内の読み取り専用照合。通常の役割評価・所有状態・ランキングを変更せず、新規対戦計算0件。ユーザーデータを外部へ転送しない | 実容量・電源断、実機 |
| テスト | CI再検証中 | `tests/test_missing_observed_evidence.py` と `tests/browser_missing_analysis.cjs` を追加・更新。初回Python616件中1失敗・1スキップ。失敗原因は対戦上限を超える不正な合成IVで、合法な別IVケースへ修正済み | 最新コミットのCI確認 |
| 公開判断 | 未着手 | Draft PRのみ。main・本番・既存フラグは変更していない | 重大な問題がないか確認し、試験公開可否を判断 |

通常の固定戦術・観測方策・標準対戦は別証拠であり、後者2つで前者の判定を自動変更しない。同じBuildでもシールドや初期ゲージ・相手IVが異なれば別条件。通常役割と観測役割は勝敗・HP・ゲージ・残盾が同義のときに限って対応づける。観測方策の共有成功も宣言済み世界・controller・観測枝に限り、実戦保証ではない。

`information_fairness=not_established`、`live_reproducibility=not_verified`、`practical_role_covered=false` を維持。実機観測時刻・同値CMP・確率効果の実機検証は今回延期。性能p50/p95新規比較は未測定。ユーザー承認までPRをマージ・デプロイ・フラグ有効化しない。ChatGPT接続PvPoke MCP使用なし。

**次の操作**：PR #113の最新HEADに対するGitHub Actionsとブラウザ検証を確認する。失敗時はジョブログの原因だけを修正して回帰を再実行し、Draft維持。完了後この節に対する追記はPRコメントで行い、無駄なCI再実行を避ける。

---

## 2026-11-13 JST 第4段階：役割条件・相手候補・保存復旧

起点は `b06d3e0de9204105332cc40bdb7c2651fe995533`、CI 12/12 成功。PR #111/#112 はDraft。本節のSHAは `git log -1 --format=%H -- docs/ASTRA_REVIEW_CONTINUATION.md`、CIはPR #112のChecksで確認。

- `pvpoke_observed_roles.py` と `pvpoke_observed_search.py` に、許容結果と最低HP・盾・ゲージ、最大8役割の優先度、条件別の成立/未達/未確認を追加。時間切れは有限計算で観測した結果として明示指定できる。計算失敗・未探索とは区別し、未知が残る場合は最悪結果を確定しない。同一条件の方策を役割の優先度・成立集合、最悪結果、シナリオごとの資源のPareto優越で比較する。資源のトレードオフは優劣保留。
- 共有方策と観測入力は第3段階の構造を再利用。新しい役割条件は計画IDと版に含む。旧条件・旧探索IDは第3段階の計算版を再現して再開できる。既存テーブル・通常計算・不足個体判定・所有状態を変更しない。
- `pvpoke_sandbox_ui.py` は既存のポケモン・技編集を再利用。候補を追加/編集/削除でき、ターン上限、役割、進捗、候補別の結果、方策比較を表示する。相手の種族・フォルム・開始盾が共通の範囲を対象とする。不足個体分析から既存の試験画面リンクを利用する。通常の不足個体評価には加算しない。
- `pvpoke_sandbox_workspace.py` は既存の認証APIの開始操作に任意の役割条件を追加。試験フラグは既定で無効。既存の停止・取得・再開を再利用する。停止は作業単位間で適用。

合成データで、旧IDの継続、新条件と旧条件のID分離、再開、所有者分離、同一カーソルの並行要求、古い版と改変記録の拒否、計算失敗時の既知結果の維持を検証。新規ディレクトリへのバックアップ復元で進捗一致を確認。SQLiteページ上限を使った実際の `SQLITE_FULL` により、カーソルと記録の原子的なロールバックを確認した。物理ボリューム障害・電源断試験は今回未実施。

性能計測は3世界×2 controller×2観測枝、1ターンの合成fixture。12シナリオ・4方策を49回再生し、native p50/p95 52.1/64.9ms、保存込みstep 54.9/70.2ms、最大観測RSS 31,096 KiB、DB 49,152 bytes、レシート8,044 bytes。保存済みカーソル10回の再要求で再生0回（10/10再利用）。最大負荷・以前との同条件速度差は未測定。測定上、保存形式の最適化は追加していない。

ローカル回帰はPython 610件（602成功・8スキップ）、その後の最終変更に対する観測系51件成功。JS 28ファイル成功。標準324条件・Sandbox合成200例を含む。ブラウザの320/390px操作シナリオを追加したが、ローカルのChromiumはソケット作成制限で起動できない。Security and regression CIで実行する。Dockerビルドはローカル未実施。

実機確認は、同意済みの対戦画面を録画し、操作・受付・通知・盾入力・技名公開のフレームを別々に記録する。同値CMPは両順序の発生を、確率効果は発動・未発動の両方を確認する。遅延・見落としを含む観測列を合成再生と照合し、個人を識別する映像は外部へ送らない。検証完了まで `information_fairness=not_established`、`live_reproducibility=not_verified`、`practical_role_covered=false` を維持。公開判定は保留。マージ・本番デプロイ・接続PvPoke MCP利用なし。

---

## 2026-11-13 JST 第3段階：観測履歴方策の試験実装

起点は `3e1f426da6023839f54a26bc12c6f4b62ad0cc92`（CI 11/11成功）。PR #111/#112 はDraft。本節を追加したSHAは `git log -1 --format=%H -- docs/ASTRA_REVIEW_CONTINUATION.md` で確認できる。CIはそのSHAに対応するPR #112のChecksを参照。

- A：`pvpoke_observed_observation.py` に厳格な公開イベント、時刻区間、順序、自分の入力を含む履歴キーを追加。自身の開始ゲージと盾を宣言済みとする合成モデル。v1の入口は維持。
- B：`pvpoke_observed_native_runner.js` に合成時計に沿う操作機会、共有方策、未定義履歴停止、盾決定後の技公開、入力の受付と解決の記録を追加。相手通常技イベントの即時相当・遅延・初回欠落を指定できる。順序変更は同時配送の通常技バッチに限定され、盾と技公開の因果順は維持する。乱数seedを固定して再生し、確率効果・動的フォーム・同値CMPの可能性は保守的に除外する。vendor・通常計算は未変更。
- C：`pvpoke_observed_search.py` と `pvpoke_observed_audit.py` で、宣言済み世界×controller×観測枝を同じ履歴テーブルで評価。異なる世界の個別最適手の合算を反例で検出。候補を上限で切った場合は不存在を報告しない。初版の役割述語は自己KO勝利。残量を併記する。一般の役割ベクトルとPareto比較は未実装。
- D：BattleStoreのownerと書き込み枠を使用し、`observed_jobs_v2` と `observed_work_v2` を追加。再生1件ごとに結果とカーソルを原子的に保存し、保存済みの同じカーソルを再実行しない。未コミットの処理が中断・失敗した場合はその1件を再生し直す。版、作業ID、公開履歴、結果のHP・ゲージ・盾収支を検証する。改変者による一貫した全記録の書換えへの真正性保証は含まない。
- E：`pvpoke_sandbox_workspace.py`、`pvpoke_mcp_remote.py`、Sandbox/不足分析UI、Dockerfileを更新。既存認証・Origin・計算枠を使い、`PVP_OBSERVED_SEARCH_ENABLED=1` で試験機能を有効化できる。Sandbox画面は現在指定した相手1個体から開始し、複数候補はAPIで宣言する。不足分析から試験画面を開ける。既存の役割判定には接続しない。停止は次の処理単位から有効。

再現：`python -m unittest discover -s tests -p 'test_*.py'` と `for f in tests/test_*.js tests/test_*.cjs; do node "$f" || exit; done`。新規試験は `tests/test_observed_observation.py`、`tests/test_observed_v2_native.py`、`tests/test_observed_search.py`。既存の `tests/test_sandbox_workspace.py` にAPIの認証・起動・再開を追加。標準324条件とSandbox合成200例の回帰を含む。ローカルのDockerビルドと実機検証は未実施。

合成2世界、4操作窓、20再生の保存込み実測はp50 55.7ms、p95 78.0ms、子プロセスのサンプリング最高RSS 31,144 KiB、保存レシート9,652 bytes（SQLiteページ等を除く）。開始3.4ms。高速化比較ではない。上限は世界32、controller 8、観測枝4、方策64、500ターン、1ステップ8回・ネイティブ再生の合計5秒目安、1ジョブ4,096回。256 MiB RSSはLinux監視による停止目標であり、瞬間的な超過を防ぐ厳密なOS上限ではない。

次の作業は、実機での操作窓・通知と解決の観測時刻・遅延・見落とし・HP表示の校正、一般の役割評価、同値CMPと確率枝、複数世界の画面入力、最大負荷・実容量不足・バックアップ復元・ブラウザ動作の確認。公開判定は保留。`information_fairness=not_established`、`live_reproducibility=not_verified`、`practical_role_covered=false` を維持。Draft、マージなし、デプロイなし、接続PvPoke MCP不使用。

---

## 2026-11-13 JST 第2段階：観測方策の設計と限定試作

起点 `790c461419edb40f69171d9d43af6255eaa510f3` のCIは11/11成功。開始時の作業ツリーはクリーン、PR #111/#112はDraft。新しい仕様の正本は [観測戦術設計](OBSERVED_TACTIC_DESIGN_20261113.md)。この節と設計書を追加したコミットが最新チェックポイント。SHAは `git log -1 --format=%H -- docs/OBSERVED_TACTIC_DESIGN_20261113.md` で取得する（自己参照SHAを文書内に捏造しない）。

採用設計は、全ての宣言世界で共有する観測履歴方策の有界探索。世界ごとの最善台本を合算しない。相手状態は相関を保持した候補集合として管理し、役割評価は最悪ケースとtrue/false/unknownを使う。未知の相手選択を等確率と仮定しない。初版は1対1・交代なし・有限controller集合。観測v2、データ構造、探索停止/再開、保存版、実装順序、受入テストを設計書に記載。

今回の実装は内部監査だけ。`pvpoke_observed_audit.py` を追加し、同じ完全な観測prefixに異なる行動が混ざる場合を拒否。`pvpoke_observed_native_runner.js` に通常判断と盾判断の発生順traceを追加。`pvpoke_observed_policy.py` とrunnerに `information_fairness=not_established` を明示し、live未検証・practical falseを維持。追加テストは `tests/test_observed_audit.py`、`tests/test_observed_native_runner.py`。通常計算、vendor、DB、UI、既存役割判定は変更していない。

独立検証：Astra Highを1体、読み取り専用で限定使用。公開入力だけでなく**方策を呼ぶタイミング自体**にも非公開情報が入りうること、観測配送遅延と入力受付の区別、未知の行動試行を除外した有限方策クラスという制約、探索失敗≠不存在を指摘。設計に反映し、文書の第2〜7節も再確認した。Astraはコード編集・テスト・GitHub・CIを担当していない。実機観測の正しさや完成機能の独立承認ではない。Claudeレビュー成果は使用していない。

検証結果：関連37テスト成功。全Python 595件中587成功・8スキップ（47.430秒）。JS 28ファイル成功、変更Python/Node構文検査とgit diff --check成功。固定engineの標準/詳細/Sandbox、通常厳選・メタ・パーティ・履歴・認証・保存の既存回帰を含む。合成の相手IV/ゲージ/未公開技を変更したnative対戦で全共有prefixを照合し、盾判断の同一公開入力も確認。意図的に世界別の行動へ改変したnegative controlは拒否された。これは監査が異常を検出するテストであり、本番の漏えい発生を意味しない。

性能：同一fixtureを新Nodeプロセスで各9回実行した中央値は変更前64.47ms、変更後66.66ms。最大73.55/72.54ms。高速化ではなく小標本の追加監査コスト測定（OS起動変動含む）。32判断のJSONは25,835→44,451 bytesで、順序trace追加による増加あり。既存512KiB出力上限は維持。64trace×500判断の監査は0.597秒、共有prefix31,500件。実機性能・大規模探索・peak RSSは未測定。第3段階で重複traceの保存を減らすことを検討するが、今回既存出力を削除しない。

第3段階は設計書§9の順序で実装する。特にengine turn/energy/own_can_actは実機観測の証明にならない。native hookが呼ばれた後もcharge lock等で入力が取り消される。公開decision windowと不確実な観測配送を先に定義し、正解世界で方策や合法手を選別しない。未定義history・空候補・予算停止・未対応確率効果はunknown。有限範囲内の方策成立と、実ゲームの再現性を区別する。

新SHAのCI結果はGitHubで別確認する。ローカルDocker/実機ビルドは未実施。PRはDraftを維持し、マージ・デプロイ・CI手動再実行・接続PvPoke MCPの利用はゼロ。使用枠残量は取得できない。最新HEADのCIを確認後、設計書に従って第3段階を開始する。

---

## 2026-11-13 JST 第1段階の修正と第2段階への引き継ぎ

作業起点は `6003d038e3a13d1af04af363b5ed84d87ec521c0`。開始時点で PR #111・#112 は Draft、作業ツリーはクリーン。起点の CI 11件すべて成功し、Security and regression の実容量不足試験、モバイル Chromium、依存関係監査も成功した。この節を追加したコミットを第1段階の最終点とし、公開前の確認は PR #112 の現在の SHA に対して行う。

| 優先順と分類 | 結果・残る判断 |
|---|---|
| 1. 既存コードで解決 | `IVSearch.step` が失敗・部分結果を `attempt_outcomes` に記録し、完了済み証拠と再開位置を保持していたが、`_explore` が試行結果をUIへ伝えていなかった。APIに安全な `retry_needed` と `fully_tested_nonqualifying_iv_count` を追加。`pvpoke_missing_ui.py` が停止理由と再開操作を案内し、達成・全条件検証済み未達成・未完了を区別する。生の例外メッセージは送らない。 |
| 2. 新設計が必要 | `pvpoke_tactic_search.py` は固定行動列を有界探索。`pvpoke_tactic_evidence.py` は実際に解決した技・シールドと対戦条件を照合し、理論証拠を通常評価から分離する。`pvpoke_observed_policy.py` は観測スナップショットを使う内部試作。実戦適用や安全な役割昇格は未検証。 |
| 3. 実機・本番相当で検証 | Motorola edge 50 の表示・操作、実戦の同値CMP・行動観測タイミング・確率効果、公開環境の認証入口、実データを使わない電源断・復旧、OS依存パッケージの到達性。CIの模擬環境で成功した項目と区別する。 |
| 4. 公開を直接妨げない改善 | 探索の全候補読み直しを減らす索引・集計を、複数対面の測定で必要性を確認してから検討。4096候補の全対面を事前計算することは既存の有界探索の必須要件にしない。 |

保存形式、計算バージョン、探索ID、PvPokeエンジンは維持。`pvpoke_iv_search.py` の既存の再開・保存処理を利用し、進捗の件数は既存の集計値から算出するため追加の計算・DB照会はない。回帰テストは、確定済みの未達成IVが1件ある状態で次戦を失敗させ、未達成件数が増えず、再開で1戦だけ増えることを確認する。`tests/test_missing_comparison.py` と `tests/browser_missing_analysis.cjs` を更新した。

第2段階では、(1) 各ターンで観測可能な情報と同一視する履歴の定義、(2) 非公開状態に対する相手行動の候補と仮定、(3) 期待値・最悪値など何を最適化するか、(4) 探索上限と中断後の証拠の扱い、(5) 理論結果から実戦再現性へ進めるための証拠要件、の順で設計する。同じ観測履歴で非公開状態だけを変えた場合に、自分の意思決定が変わらないことを先に検証する。既存の標準324条件・native Sandbox合成200ケース、`tests/test_iv_search.py`、`tests/test_tactic_evidence.py` を回帰基準とする。固定行動列の結果から通常の役割評価を昇格させない。

ローカル検証は Python 589件中581成功・8スキップ、JS 28ファイル成功。Chromiumはソケット作成権限の制限で起動不可、Dockerは利用不可。32戦の1件あたりp50 2.12 ms、p95 3.79 ms、4096候補の静的計算0.243秒。既存経路の計測であり、速度向上を示す比較ではない。

---

## 2026-11-13 JST 独立レビュー再開記録

この節を追加したコミットが再開点。親コミットは `6fce372882e4162c40ad09b2145fbfaae4bbbee7`。PR #112 の `fix/tactic-review-recovery-20261112` は、PR #111 の `bbc0619f830704da3c626b5682c3c4b58cf211b8` 上の Draft。開始時の CI は #111 が 5/5、#112 が 11/11 成功。作業ツリーに残っていた前回の修正4ファイルと検証2ファイルを引き継いだ。元要求仕様、セキュリティ資料、固定された vendor PvPoke を基準に判断した。Claude のレビュー成果は使用していない。

前回の Astra engine / Astra data による調査と合成テストを再利用。今回は GPT-6.1 Sol が再現、実装確認、回帰、測定、統合、GitHub 操作を担当。Astra High は1体だけ起動し、CMP・同時KO・未実行の技やシールド・確率効果の差が、実戦評価に誤って反映されないかを限定レビューした。Astra はこの再開工程でコード編集、テスト実行、CI操作を行っていない。使用枠の残量は取得不可。

| 問題 | 重大度・担当 | 再現と原因 | 修正・確認 |
|---|---|---|---|
| ASTRA-01 例外ログへの詳細記録 | P1、Sol | `pvpoke_mcp_remote.py` の `Handler.app_request` と `do_GET` の Reader cleanup で、予期しない例外の本文・スタックが `logging.exception` で記録される。合成マーカーが修正前ログに残ることを再現。実データの漏えいは確認していない。 | 固定の処理名と例外クラスだけを記録。HTTP 500/503 は維持。`tests/test_security_regressions.py` で両経路の本文・ログを検証。 |
| ASTRA-02 IV下限の不整合 | P1、前回 Astra data が発見、Sol が再検証 | `IVSearch.start` と `opponent_boundaries` が RETURN と指定下限だけを参照。交換不可の合成種族で自分側 4096 件（期待216件）、相手側の指定 `[0,14,15]` がそのまま通る（期待 `[10,14,15]`）。 | `pvpoke_iv_modes.py` の既存ルールを `species_iv_floor` へ抽出し、`pvpoke_iv_search.py` の両経路で各軸の指定下限と大きい方を採用。既存の RETURN の優先順位を維持。`tests/test_astra_iv_eligibility.py` で216件・相手側12件・シャドウ伝説・旧探索の stale と保持を確認。既存の計算キャッシュはソース識別子の変更により再計算が必要になる場合がある。 |
| ASTRA-03 確率効果モデルの表示 | P2、前回 Astra engine の比較を Sol が再現し、今回 Astra が判定 | `Battle.js` の通常対戦では確率効果の累積判定が働く。`pvpoke_sandbox_runner.js` は `buffs: false` で、確率効果の発動を指定しない。合成ケースで相手終端HP 35 と 74 に分かれた。 | `pvpoke_sandbox_ui.py` の比較欄に説明を追加。固定した engine の挙動を維持。`tests/test_astra_independent_engine_20261112.cjs` に合成反例を保存。同攻撃値CMPの実機挙動は別途確認。 |

この範囲でP0とP3の新規不具合は確認されなかった。Astra の限定判定では、`pvpoke_tactic_evidence.py` が双方の指定技とシールド判断を解決イベントで照合し、未履行なら `meets=None`。同時KOは自分の勝利に変換されず、固定台本の結果は `counterfactual_only`、`live_reproducibility=not_verified`、`practical_role_covered=False`。実戦で観測できる履歴だけを使う適応戦術の妥当性は未確認。

| 要求領域 | 今回の確認 | 残る範囲 |
|---|---|---|
| 共通対戦計算・Sandbox | 標準324条件の既存値と一致。直接構成した native Sandbox と200合成ケースでイベント、ターン、終端状態、ゲージ収支を照合。1〜5ターン技の必要エネルギーと1不足の境界を追加。既存テストのCMP、同時KO、シールド消費、能力変化も成功。 | 実機の同値CMP、行動認識タイミング、確率分布は未確認。 |
| 戦術探索・証拠統合 | 同じ観測条件に対する非公開IV・ゲージ・技の変化を既存テストで確認。固定台本から通常評価を書き換える経路を限定レビュー。 | 同じ観測履歴に対する適応行動の実戦での再現性は未確認。 |
| 不足個体・重要IV | テスト範囲で未計算は保留、保有は明示情報のみ、必要条件は同一個体・技構成で評価。種族をまたいだ部分勝ちの合算を拒否。探索中断、再開、既存証拠の再利用を確認。 | 4096静的候補の全対面をネイティブ計算する検証と、全入手経路の例外確認は未実施。 |
| 認証・保存 | 合成データによる匿名拒否、Origin、所有者スコープ、子プロセス環境、SQLite失敗時ロールバック、バックアップ・復元の回帰。 | サービスは単一所有者構成。実データ環境での複数ユーザー分離、本番入口、電源断、OS依存パッケージの到達性は未確認。 |
| 既存機能とUI | 通常厳選、メタ、技構成、パーティ、履歴・設定の既存回帰を実行。 | Chromium はローカルのソケット作成制限で停止。Docker・Nginxなしのため、本コミットのイメージ・物理 ENOSPC・ブラウザは CI で確認する。Motorola edge 50 実機は未確認。 |

Sol のローカル結果は Python 588件中580成功、8スキップ（Nginxと専用 ENOSPC 環境）。JS 29ファイルと Python/Node/シェルの構文検査は成功。隔離した親コミットのツリーで3件の回帰が修正前に失敗することも確認。親コミットの [Security and regression](https://github.com/jagaimoUK/pokemoniv/actions/runs/43240571644) は Docker、Nginx、実 ENOSPC、モバイル Chromium、依存関係監査まで成功。本コミットは別途 CI の SHA を照合する。

合成データの測定では、4096 IV の静的境界計算は 0.344 秒。32件の対戦計算は1件あたり p50 2.10 ms、p95 2.78 ms。戦術プラン作成は p50 7.82 ms、p95 10.04 ms、進捗読取は p50 1.76 ms、p95 2.09 ms（各21試行、対戦実行0件）。対戦APIの小標本で Python/Node のピークRSSは約37 MiBずつ。修正前後の性能差や本番負荷、実機応答の保証には使わない。

公開判定は保留。次の実行では PR #112 のこのコミットに対応する CI を確認し、イメージ監査・匿名レスポンス・実 ENOSPC・モバイルの各ステップを確認する。再現コマンドは `python -m unittest discover -s tests -p 'test*.py'` と `node tests/test_astra_independent_engine_20261112.cjs`。残る実機・容量・観測ベース戦術を未検証のまま公開しない。コミットを1回にまとめ、CIの手動再実行、本番反映、マージ、接続PvPoke MCPの利用はゼロ。

---

## Current authoritative checkpoint (2026-11-12, supersedes historical pending statements below)

**Scope:** Draft PR #112 stacked on Draft PR #111, head
`af1516cc73f3ba901ccc8ac92e0c73f2e3fa573c` **before this documentation-only update**.
GitHub Actions on that exact source SHA: **11 / 11 success**, including:
Python **583 tests (1 skipped)**, JS regression, image build, Chromium
CSP/mobile initialization, dependency/secret checks, and Docker-based
**real filesystem ENOSPC test on an isolated 2 MiB tmpfs in DELETE and WAL modes**.
The real-Nginx-to-gateway HTTP authentication regression also ran in the
production Docker image. Synthetic data only; no production DB or credentials.

That confirms the stated **specific tests**, not live railway ingress,
production load, a power-loss crash, external-writer capacity, exhaustive
vulnerability reachability, complete 4096-IV × matchup native results, or
observation-conditioned real-match strategy. Fixed scripts remain
counterfactual, not practical role coverage.

The last image scan reported **103 HIGH entries, 25 unique CVEs, 0 scanner-
reported fixable HIGH/CRITICAL**. Not security clearance and not 103
separately proven exploitable bugs. Independent Astra code review has **not
been performed or signed off**. Release assessment D; PRs stay Draft
and unmerged; no production deployment.

**Historical note:** The chronological material below records earlier
RED/green investigations and at-the-time pending statements, for audit
traceability. Where those statements say 'CI pending', 'real ENOSPC
not run', 'Docker proxy not verified' or list earlier head SHAs, use
this checkpoint and `docs/ASTRA_INDEPENDENT_REVIEW_BRIEF_20261112.md`
instead. Do not erase evidence of previous failures.

---

# Astra review continuation: recover, repair, and verify

Updated: 2026-11-12 JST. This is a **checkpoint, not a final review sign-off**.

## Trusted starting point and recovery constraints
- Repository: `jagaimoUK/pokemoniv`.
- PR #111 (Draft, unmerged) head at start: `bbc0619f830704da3c626b5682c3c4b58cf211b8`.
- Separate child branch: `fix/tactic-review-recovery-20261112`, stacked on #111. Do not merge or deploy.
- Previous Work/Astra stated it edited 3 files and updated "Astra review" / "Astra storage security", but no saved patch or file from that Work environment was accessible to this chat. GitHub PR #111 had not advanced. Previous changes **were not recovered**, and have not been claimed as recovered.
- This continuation independently reimplemented the **reported** fixes against PR #111, without any ChatGPT-connected PvPoke MCP tools.
- The quoted old "503 tests, 0 failures, 4 skipped" is a **previous Work report, not a test result of the new changes**.

## Checkpoint table
| Stage | State | Evidence and changes | What remains |
|---|---|---|---|
| 0. Recover Work changes | Blocked | GitHub and Project/Library checked; Work-local edits unavailable | Recover original Work patch only if separately accessible. Do not overwrite these changes blindly |
| 1. Opponent action execution | Implemented, CI pending | Track all native opponent action IDs (including seeded actions and alternate+self-shield case); require actual resolved charged-move events as well as action-start statuses; new failing-case tests | Verify tests/CI, examine non-observable opponent behavior |
| 2. Saved Sandbox integrity | Implemented, CI pending | Revalidate cached results on read: action status/trace, terminal vs outcome, initial values, shield and damage totals, event consistency, JSON canonical encoding; rehashed invalid-record tests | Verify native trace compatibility, test more adversarial synthetic cases |
| 3. Capacity separation | Implemented, CI pending | Reserve 1/8 SQLite page quota and 8 MiB disk free for user-authored records; prioritize ownership events, role evaluations, analysis definitions, saved tactics. No eviction, no schema migration | Verify small-database saturation, free-space simulation, real storage capacity and external disk consumers |
| 4. Remaining independent review | Not started in this chat | Previous Work reported some boundary tests, no portable artifacts | Complete legal timings, hidden-information fairness, other algorithms independently |
| 5. Post-fix regression + CI | Not started | Prior PR #111 passed 503 tests and 5 workflows *before* changes | Verify exact new HEAD: Python, JS, browser, 324 golden, security, build |
| 6. Saved changes | In progress | Source changes committed on a child branch; no production changes | Create Draft PR; report final head and CI |

## Changed modules
- `pvpoke_tactic_search.py` and `pvpoke_tactic_evidence.py`: all requested opponent actions must be executed and charged moves must have matching native resolution events (action ID, actor, move). Previously just the new alternate was checked, and some variants were missed.
- `pvpoke_sandbox.py`: cached data must be semantically valid even when the checksum has been recalculated. No automatic re-simulation on invalid saved data.
- `pvpoke_battle_store.py`: two-tier writer with quota headroom and physical-disk guard; critical writes use reserve.
- `pvpoke_ownership.py`, `pvpoke_missing_analysis.py`, `pvpoke_role_evaluation.py`, `pvpoke_sandbox_workspace.py`: important writes use the critical quota.
- `tests/test_tactic_search.py`, `tests/test_tactic_evidence.py`, `tests/test_sandbox.py`, `tests/test_battle_store.py`, `tests/test_ownership.py`: regression tests.

## Explicit limitations
- Fixed scripts remain theoretical counterfactuals. Live reproducibility **not verified**. No promotion into normal coverage or ownership.
- Reserve protects the app's own quota and defers expendable writes at low physical free space; it **cannot guarantee** important writes succeed if external processes fill the volume, if WAL grows unexpectedly, or if the reserved area also runs out.
- No actual production SQLite data, credentials, keys or user holdings were read, altered or copied.
- No real device test, exhaustive 4096-IV or 3v3 policy fairness validation in this continuation.
- Changing the search source hash makes existing saved search checkpoints stale; they are retained rather than rewritten. Cached Sandbox results remain separate and verified by key/version.

## Next steps, in order
1. Check PR creation and the exact branch SHA.
2. Run CI tests on the exact branch head; fix reproducible regressions first without touching main.
3. Record test totals, any failures and whether native Sandbox and mobile browser tests passed.
4. Perform additional independent review of rules, resource fairness, owner boundaries and capacity under real volume constraints.
5. Leave branch/PR Draft, and write a user-visible handoff with concrete commit SHA and residual risk.

GitHub edits in this session were made through the connector; no local git checkout was available. Git status of the old Work container therefore remains **unknown**, not clean.


---

## GPT-6 independent review checkpoint (2026-11-12 JST, stage 1)

This section supplements earlier handoffs. It does **not** endorse their conclusions. Source of truth: original missing-analysis/Sandbox requirements and pinned in-repository PvPoke battle engine. Previous review summaries are only hypotheses.

### GitHub verified initial state
- PR #112: **open Draft**, base \`feature/tactic-search-role-advisory-20261112\` (PR #111), head branch \`fix/tactic-review-recovery-20261112\`.
- Start HEAD: \`3d793b9d2a63599ef2d25b4f6a99ec5eeabe7521\` (unchanged from supplied previous checkpoint).
- 14 files changed in PR #112. Its exact start HEAD has 5/5 successful workflow runs: IV contract, recommendation, 24-mode, meta/image, security/regression. The reported 510 Python tests are not yet independently reconstructed locally.
- No local Git checkout exists in this execution environment; uncommitted Work-local edits cannot be inspected or recovered. The connector tracks committed branch changes only.
- Production untouched. The ChatGPT PvPoke MCP was not used.

### Spec-first falsification matrix (expectations before accepting code fixes)

| Independent condition | Counterexample / expected rejection or uncertainty |
|---|---|
| Charge energy 0–100 | At 0 or one point below cost, charge never resolves; exact cost permits firing if otherwise legal; energy never exceeds 100 |
| Fast move duration 1–5 turns | A charge scheduled during unresolved fast-move cooldown cannot count as executed; damage lands at engine-defined turn, not request turn |
| Repeated and mixed charged moves | Each move must be independently paid for and resolved; actor, action ID and equipped move ID must match actual native events |
| CMP and simultaneous actions | Native priority and KO order decide legality; a started but non-resolved action cannot satisfy a role; simultaneous KO must retain both terminal HP=0 |
| Shields 0–2 | No shield usable after depletion; requested and actual shield events, defender, and shield totals must agree |
| Buffs and debuffs | Effects apply only when native engine resolves them; initial stages, timeline transitions and terminal stages must agree |
| Opponent response | Requested original and generated alternate scripts must independently resolve; missing response means counterfactual evidence unsupported |
| Fair information set | Two histories with the same *observations* must lead to the same selected action despite different hidden enemy IV, charge move, energy or shield intent; otherwise label as theoretical |
| Saved proof consistency | Recompute digest after mutating one inner trace/terminal field: load must still reject impossible state transition, not just malformed JSON |
| Required role and IV | Only one exact legal build covering *all* required matchups is eligible; separate IV wins must not be unioned; incomplete IV search is unknown |
| Inventory independence | Calculation, candidate retention, confirmation and unknown ownership are separate states; absence of an ownership record is not proof of unowned |
| Disk capacity | Disposable writes must not starve crucial records; test tiny quotas, WAL/disk exhaustion, failed transaction rollback, restart and recovery, without production data |
| Default calculation | Standard mode golden results must remain identical, including hand-specified move sets and meta presets |

Sources and current limits: the original Japanese request document defines these expected behaviors. The pinned PvPoke \`Battle.js\` uses 500ms turns and cooldown, and \`ActionLogic.js\` reasons from energy and priority, but individual oracle outcomes still require native runner fixtures. The matrix is not a claim that the code passes.

### Progress states

| Stage | State | Completed | Remaining |
|---|---|---|---|
| Latest source / Git / CI | 完了 | PR refs, 14 changed paths, 5 current successful workflows verified | Compare individual workflow job evidence as needed; local Work state unavailable |
| Spec-driven battle review | 作業中 | Independent falsification matrix and vendor code entry points identified | Native test fixtures, red/green tests for new failures |
| Live reproducibility | 未着手 | Observable-history equivalence specified | Run two-hidden-state tests and check UI labels |
| Missing roles / IV | 未着手 | Per-exact-build invariant specified | Audit code and coverage |
| Security / storage | 作業中 | Owner/digest/disk risk conditions specified | Mutation fuzz cases, capacity and WAL audit |
| Repairs | 未着手 | None from this independent pass | Demonstrate failures before targeted fixes |
| Regression / build | 未着手 | Initial pre-review CI 5/5 confirmed | Exact post-fix workflows, tests and image |
| GitHub checkpoint | 完了 | This checkpoint, Draft PR maintained | Save subsequent findings, remediation and final SHA |

### Checkpoint metadata
- Current stage: spec-first battle and stored-proof review.
- Confirmed defects **in this pass**: none yet; hypotheses must not be called confirmed.
- Previous fixes: maintained untouched; no endorsement.
- Unfixed / unverified: full policy fairness, end-to-end native timeline, storage exhaustion and recovery, Trivy HIGH=103 (historical report), 4096-IV coverage.
- Changed paths in this pass: documentation checkpoint only.
- Initial HEAD: \`3d793b9d2a63599ef2d25b4f6a99ec5eeabe7521\`; branch \`fix/tactic-review-recovery-20261112\`. A new documentation commit will advance HEAD.
- Uncommitted changes: unknown outside GitHub; connector edits commit directly.
- Tests: 5/5 existing Actions passed at initial HEAD. No new local tests executed. Do not conflate with the prior 510-test count.
- Next operation: inspect cached-state validation against native trace shape, add a precise red regression test, only then patch the defect and verify CI.


### Independent finding G6-001: forged opening Sandbox state (P1)
- **Reproduction (confirmed red, not an assumption):** on test-only SQLite data, alter the first native trace event's \`before[0].hp\` while preserving the stored \`initial\`; recalculate canonical JSON + SHA256 digest. Prior cache validation accepted the contradiction.
- **Red CI at commit \`f02d55754067e387f0631dc32dd8614e741fc403\`:** Python suite \`511 run / 510 passed / 1 failed\`. New test \`test_rehashed_first_trace_state_must_match_initial\` failed exactly with \`AssertionError: BattleStoreError not raised\`; three workflows running the suite reported the same failure. This is an intentional red test, **not** a previously passing build.
- **Root cause:** \`_validate_cached_sandbox()\` only bounds individual trace states; it did not require the first event's \`before\` snapshot to equal the validated initial state. The SHA256 digest is not an authenticity proof after rehashing.
- **Targeted fix (in this checkpoint's paired source change):** reject any nonempty complete trace whose first \`before\` state differs from \`initial\`; malformed saved facts fail closed, without rerunning native PvPoke or deleting data.
- **Green status:** pending exact-HEAD CI. A later, independent test must still address intermediate trace-state transitions and terminal/effects linkage. No production change.

### Current progress after G6-001 remediation commit
| Stage | State | Evidence | Remaining |
|---|---|---|---|
| Latest source | 完了 | PR #112, Draft, base #111; prior HEAD \`f02d557...\`; original 5/5 initial CI | New head/CI |
| Battle independent review | 作業中 | Native runner semantics reviewed; forged initial timeline contradiction reproduced | Additional energy/CMP/fast action fixtures |
| Live reproducibility | 未着手 | Still counterfactual fixed scripts | Observational-equivalence policies/tests |
| Missing IV / roles | 作業中 | Exact-build intersection and unknown-ownership state inspected, no new failure proven | Full IV coverage and alternative substitution tests |
| Security / storage | 作業中 | P1 cache contradiction proven; capacity reserve code inspected | WAL, tiny quota, crash/repair, owner HTTP, Trivy reachability |
| Repairs | 作業中 | Minimal cache fix and regression test committed together | Verify post-fix CI; further inconsistent trace cases |
| Regression | 作業中 | Red run: 511/510/1 | Green 511+ golden/JS/browser/build checks |
| GitHub saving | 完了 | Source, test, handoff on existing Draft branch | Record exact final commit in visible handoff |

- Previous Work-local unsaved 3 files remain inaccessible; do not overwrite or claim recovered.
- No local working tree available for inspection; uncommitted changes in the previous Work environment remain unknown.
- Changed in this pass: \`tests/test_sandbox.py\`, \`pvpoke_sandbox.py\`, \`docs/ASTRA_REVIEW_CONTINUATION.md\`.
- Initial PR #112 head was \`3d793b9...\`; red test commit \`f02d557...\`. This checkpoint is paired with a new remediation commit on branch \`fix/tactic-review-recovery-20261112\`; its exact GitHub-generated SHA is reported in the review handoff.
- No production merge/deploy/configuration/DB changes. No ChatGPT PvPoke MCP calls.
- Next: confirm new commit's Actions, read any failures, fix only reproducible regressions, then document remaining uncertainty and do not approve publication prematurely.


### Independent finding G6-002: started-but-unresolved native fast action (P1)
- **Red test at \`b78e78ec0e317ac1e2a5a53d26930f9ec4aa1a97\` (confirmed):** \`test_fast_move_tap_without_resolution_is_not_success\` fails with \`AssertionError: True is not false\`. Synthetic fast request is marked "executed" but has no resolved native damage event. Positive fixture \`test_native_fast_start_and_resolution_are_independently_linked\` independently checks that legal native fast moves have a linked \`action_id\`, \`actor\`, \`kind\`, \`move_id\` event.
- **Source of truth:** pinned vendor \`Battle.js\` queues fast attacks to resolve after their cooldown, and \`pvpoke_sandbox_runner.js\` documents that a tap may start even when KO prevents damage. The previous helper only enforced resolution for charged attacks.
- **Root cause:** \`_requested_actions_completed()\` accepted an \`executed\` fast start without requiring resolution.
- **Targeted fix in paired commit:** require matching native resolved event for *both* fast and charged requests; wait still requires only executed-start status. This is conservative: a queued but unlanded tap cannot establish tactical role support.
- **Post-fix state:** pending exact-head CI (expect the prior red test plus positive native fixture to pass). Native GameMaster, vendor Battle.js, standard calculation, ownership and production remain untouched.

### Security triage checkpoint
- Earlier exact-head security workflow recorded Trivy **HIGH 103** with no fixable HIGH/CRITICAL at the then-available package versions. At least \`libsqlite3-0\` appears in HIGH rows (e.g. CVE-2026-119373/119374/119379), so these findings cannot all be dismissed as unused packages: SQLite is exercised by app record storage.
- Also affected packages in the report include Kerberos libraries and utilities such as \`mount\`/ \`login\`; whether they are reachable from untrusted web requests is not established from package names alone.
- This is **triage, not exploit confirmation or a clean security audit**. OS/package advisory verification and individual path review are still required. Do not release solely because no vendor fix is listed.

### Updated work state
- Latest source: 完了; tests and native semantics: 作業中; live information-fairness policy: 未着手; role/IV coverage: 作業中; security/capacity: 作業中; G6-001 source fix: 作業中 (green verification outstanding); G6-002 source fix: 作業中 (green verification outstanding); full regression/build: 作業中; GitHub save: 完了.
- Changed this stage: \`tests/test_tactic_search.py\`, \`pvpoke_tactic_search.py\`, \`docs/ASTRA_REVIEW_CONTINUATION.md\`. Parent red SHA \`b78e78ec0e317ac1e2a5a53d26930f9ec4aa1a97\`, branch \`fix/tactic-review-recovery-20261112\`. Exact new commit SHA appears in PR #112 / final handoff.
- Previous Work uncommitted edits: unknown/unrecoverable; this environment uses direct GitHub commits, no local checkout.
- Remaining: green CI + 324 golden + browser smoke, owner boundary, WAL and true disk exhaustion, information fairness, full IV search, performance comparison; do not mark the feature publishable.
- Next concrete action: read CI conclusions on new HEAD, retrieve failure logs if any, only then finalize the Draft checkpoint and report commit SHA.


---

## GPT-6 independent continuation, stage II (2026-11-12 JST, red-test checkpoint)

**Original sources inspected before proposing a repair:** the uploaded missing-analysis / Sandbox / common-battle-engine requirements and security instructions; pinned native \`pvpoke_sandbox_runner.js\` and \`vendor/pvpoke/src/js/battle/Battle.js\`. Prior stage conclusions are not treated as proof.

**Git/CI verified at start:** Draft PR #112 still open and stacked on #111; branch \`fix/tactic-review-recovery-20261112\`, starting HEAD \`e7cdb07b5ac4b6fcf0ab09832b9f9302692558c2\`; its 5/5 Actions succeeded, 513/513 Python tests passed. GitHub is updated via explicit parent-checked connector commits; the prior Work-local uncommitted state cannot be inspected.

### Independent invariants to challenge (pre-repair)
- A complete native battle starts from the saved \`initial\`, emits sequential \`start/resolve/effects\` state snapshots, and ends in \`summary.terminal\`.
- Each \`start\` has the same \`before\` and \`after\`, since starting/tapping a move does not apply damage or buffs.
- Every adjacent trace event must preserve state continuity (unless a separately verified native transition is identified).
- Native \`onMoveResolved\` emits a move's \`target_hp\` equal to the defender's HP after the resolve; the change in HP on resolution equals applied damage.
- State continuity and target HP are not implied by a matching JSON checksum. A rehashed inconsistent row must be rejected with no native rerun.
- Hidden opponent IV/energy/move/shield preferences must not be treated as known at decision time; a fixed-script result stays \`counterfactual_only\`, \`live_reproducibility=not_verified\` until observable-history policies are separately tested.
- Exact legal build and owner confirmation remain separate; untested IVs are not missing/losing, and absence of an inventory entry is unknown.

### Checkpoint status (this commit deliberately adds red tests *before* source repair)
| Stage | State | Verified this stage | Remaining |
|---|---|---|---|
| Latest source/PR/CI | 完了 | PR #112 head/stack, 5/5 initial CI, 513 Python | Reverify head after edits |
| Native battle/trace review | 作業中 | Trace runner callbacks examined; new normal-native and rehashed-mutation tests added | Read exact CI failures, patch only confirmed defects |
| Information fairness | 作業中 | Counterfactual metadata and lack of observable policy confirmed in code | Hidden-state equivalence fixtures; real-play reproducibility not established |
| Role / IV coverage | 作業中 | Existing exact-build/unknown status verified by source | Exotic substitutes, incomplete 4096 IV coverage |
| Security / capacity | 作業中 | Mutated cache fail-closed test cases added | WAL/disk exhaustion and restart, owner route reachability, Trivy HIGH 103 |
| Defect fixes | 未着手 | Stage-II code untouched, awaiting red-test result | Minimal fix to validated failures |
| Regression/build | 未着手 | 513/513 and 5/5 are **starting** HEAD results | New red and green, JS, Docker, browser |
| GitHub checkpoint | 完了 | Documentation and test-only stage committed to existing Draft branch | Record failing assertions, fixes, final SHA/status |

**Changed files at this checkpoint:** \`tests/test_sandbox.py\` and \`docs/ASTRA_REVIEW_CONTINUATION.md\`. Current branch remains \`fix/tactic-review-recovery-20261112\`; this is a test-only commit on top of \`e7cdb07b...\`. No local checkout, so Work-local uncommitted changes unknown; no production changes, no PvPoke MCP calls.

**Next precise action:** inspect actual new-head CI, distinguish a violation of the native trace contract from an invalid proposed invariant, then repair narrowly and verify a green exact head. Do not promote previous or new tests to live-play proof.


### Stage-II RED checkpoint (first run \`0da16f10aa2536b63044317e90c2eb8b7672dd8d\`)
- CI \`Meta preset regression and image build\`: **515 Python tests, 4 failing subtests**. Good native trace oracle \`test_native_complete_trace_state_chain_matches_terminal\` passed.
- Confirmed missing rejection for **three distinct rehashed cache mutations**: changed \`executed_moves[0].target_hp\`; changed \`trace[0].after\` at a move start; changed \`effects.before\` energy.
- Fourth \`change_last_hp\` failed for a **bad test assumption**: the native fixture legitimately KO'd side 0, whose HP was 0 rather than >1. This is **not** a fourth confirmed cache defect. The paired test-only commit updates the test to mutate the surviving side without altering outcome.
- No source repair yet. Avoid reporting all 4 as independently reproduced vulnerabilities. Next check corrected red run then patch native trace integrity; never adjust the expected failure assertion to hide defects.


### Stage-II confirmed defect G6-003: cached native trace falsification (P1)
- Corrected pre-fix RED at \`ad15b6066a229740e895541f6c812244bcff39c4\`: **515 Python tests, four failing corruption subcases** in \`test_rehashed_trace_state_and_target_hp_must_fail_closed\`; each failed with \`AssertionError: BattleStoreError not raised\`. A separate positive oracle \`test_native_complete_trace_state_chain_matches_terminal\` passed for normal native PvPoke battles.
- Four proven contradictions after canonical rehash: (1) terminal surviving HP changed without trace change; (2) resolved move target HP no longer matches native damage state; (3) a move start improperly changes HP; (4) an effects event starts from an impossible energy state.
- Root cause: prior cache validation verified JSON digest, action links, event counts/IDs, and aggregate damage, but not full state continuity, terminal vs last trace, start-phase immutability, or resolution target HP/damage consistency.
- Paired source repair in \`pvpoke_sandbox.py\`: fail closed on empty complete trace; ensure each event begins at the previous event's \`after\`, start does not mutate state, final state matches terminal; for each resolve, ensure target HP and HP decrement match the native event's applied damage. No replay, no data eviction, no vendor/standard engine changes.
- Exact post-fix CI is **pending**; neither 515 tests nor green workflows should be claimed for this new head until verified. Full cryptographic authenticity of a deliberately rehashed and *internally consistent* forged transcript remains unestablished. Hidden opponent information and live policy correctness remain unverified.
- Current stage: P1 remediation committed, verify exact CI next. Work-local uncommitted files still inaccessible; GitHub direct updates only. No production changes and no ChatGPT PvPoke MCP access.


---

## GPT-6 independent continuation, stage III: falsification before repair (2026-11-12 JST)

**Starting PR state (verified):** #112 open Draft, stacked on Draft #111; HEAD \`c4f9d3c87adc0184ce7800dcbee6b8eb5ff563d7\`; earlier 515 Python and 5/5 workflows passed. Previous Work-local unsaved modifications cannot be inspected. No deploy, merge, credential or production data operation. ChatGPT PvPoke MCP prohibited and not used.

### Native and checkpoint contracts under test
- \`pvpoke_sandbox_runner.js\` always emits \`effects\` for each \`resolve\` via wrapped \`battle.useMove\`, **even if** the effect is a no-op. A trace with the effects event deleted and sequences repaired is not a native complete record, despite valid digest, HP continuity and aggregate damage.
- \`TacticSearch._progress\` displays \`fully_executed_scripts\` as verified evidence. A rehashed checkpoint with \`opponent_response_executed=True\` must not be allowed to promote a charged move that was explicitly rejected as \`insufficient_energy\`, even if the separate role-advisory route revalidates native Sandbox.
- Both test cases use temporary owner-scoped SQLite; neither calls the ChatGPT MCP.
- Fair-information counterexamples to test next: same visible history but hidden opponent charged move, IV, energy and shield response. Native scripts may vary under hidden states, but **practical evidence must remain unavailable**; no automatic promotion into roles.

### Stage III status
| Area | Status | Evidence | Next |
|---|---|---|---|
| Latest code/PR/CI | 完了 | Source SHA and Draft stack verified; last head 5/5 and 515 tests | Recheck new head |
| Information fairness | 作業中 | Theoretical-only output and UI restriction confirmed from source | Independent hidden-state fixtures |
| Native replay / trace | 作業中 | No-op \`effects\` native contract; red test committed | Confirm red, patch only if actual failure |
| Tactical checkpoint | 作業中 | Rehashed unexecuted opponent action fixture | Confirm red, correct verified counts |
| Storage | 作業中 | No explicit WAL journal_mode configuration in BattleStore; 1/8 pages + 8MiB reserve | Confirm actual mode on isolated DB; injected disk/transaction failures |
| IV / alternatives | 作業中 | 4096 bitset and one-build intersection inspected | Adversarial multi-condition + unrelated species |
| Security | 作業中 | Last Trivy HIGH 103 | Source/package reachability triage and auth tests |
| Performance | 未着手 | Previous generic benchmark (not paired) | Same-environment baseline |
| Final verdict | D | No release until critical unknowns resolved | Preserve Draft |

**Stage III files committed in RED checkpoint:** \`tests/test_sandbox.py\`, \`tests/test_tactic_search.py\`, this document. CI red failure must be inspected before source repair. Do not classify hypotheses as proven.


### Stage III independently confirmed RED and targeted remediation
- **RED CI commit \`92009d3083a245f8fedaab37ac428d3203b25bf8\`:** Python suite **517 run, 515 passed, 2 failed**, both expected new tests (native no-op effects omission accepted and a rehashed opponent nonexecution flag accepted). Failures were \`AssertionError: BattleStoreError not raised\` and \`AssertionError: TacticSearchError not raised\`. No pre-existing tests failed in that run.
- **G6-004 (P1):** No-op native \`effects\` event could be removed/reindexed without breaking trace continuity/damage metrics. Fix \`pvpoke_sandbox.py\`: require a matching immediately adjacent \`effects\` for every native \`resolve\`, and never permit an orphan \`effects\`.
- **G6-005 (P1):** Rehashed tactic cell could inflate the UI's \`fully_executed_scripts\` despite native \`insufficient_energy\` rejection; earlier role-advisory read checked but the checkpoint progress did not. Fix \`pvpoke_tactic_search.py\`: when the version is current, compare all previously saved complete cells with their already saved and fully revalidated native Sandbox result in a single owner-scoped read transaction. Verify actor/action execution and shield/terminal facts without re-running battle calculations. Partial and stale results never prove practical reproducibility.
- **Versioning:** both module sources affect native/search version hashes, so past searches may become \`stale\`, but rows are retained, not rewritten/deleted. No production data changes.
- **Current state:** patch committed; **green CI pending confirmation**. Previous 515 test/5-workflow success belongs to older head, not this patch.
- **Storage and security:** BattleStore doesn't configure WAL; new SQLite files default to DELETE mode but rollback journals and externally configured WAL still require scrutiny. Prior Trivy image report's 103 HIGH package rows group into 22 package names and 25 distinct CVEs. SQLite findings 119373 (special FTS5 prefix), 119374 (corrupt FTS5 secure-delete), 119379 (untrusted SQLite session changeset) have special preconditions not demonstrated in reviewed battle DB DDL. Whole-image reachability is unconfirmed, so do not mark security risk resolved. Full ENOSPC/rollback/restart and paired p95 performance comparisons remain unmeasured.


### Stage IV independent positive oracles and safety boundaries
- Positive native-only fixtures added: priority-based CMP where a losing charged request may be rejected, same-species simultaneous charged-move knockout, and guaranteed \`ICY_WIND\` debuff. For each, require result to be complete and the saved result to be identical on a second cache-only read without spawning a Node simulation.
- Fixed-script information-fairness test added: four opponent hidden conditions (reference, alternative energy, IV, second charged move order). Original self-action schedules must be invariant, native battles must not be launched during planning, and all outputs must remain \`fixed_script_counterfactual / not_verified\`. This checks **absence of unjustified promotion**; it does **not** implement/verify a full observation-based strategy.
- Real local SQLite new-database \`PRAGMA journal_mode\` and synthetic low free-space test added. Important writes may use reserved space while noncritical writes reject. Does not prove real-world full-disk operation. Separate non-production isolated Python WAL experiment: 4,096-byte DB, 337,872-byte WAL file with max_page_count=64; this proves max_page_count does not cap WAL physical usage. The application itself does not enable WAL in a fresh DB.
- Source audit: \`Dockerfile\` temporarily uses root for Railway volume ownership initialization but \`volume_bootstrap.sh\` ends with \`exec gosu appuser /app/start.sh\`. Do not misclassify the runtime application as running as root merely from the Dockerfile final USER line.
- Existing gateway tests cover unauthenticated 401 and origin 403, HTML has CSP and no gateway API key, and scoped owners deny cross-owner data in tested storage. Do not infer a real production network penetration test from unit fixtures.
- Security historical Trivy report: 103 HIGH package findings = 22 binary package labels, 25 unique CVEs. Three SQLite advisories require the FTS5 \`detail=none\` prefix path, malformed FTS5 secure-delete, or the session changeset API. Reviewed battle DB tables are ordinary SQL tables, but full deployment exposure and applicability are not conclusively audited. No blind dependency update.
- This stage adds **tests and evidence notes only**. New CI results are required on the exact resulting SHA, previous green results apply only to the preceding source-fix commit. Verdict remains D; no merge/deploy.


### Stage V: IV completeness and cross-species independent review (RED checkpoint, 2026-11-12)
- Base head \`59687963d12c5d7e953311acc1830d88a18ca541\`, Draft PR #112 stacked on #111, prior 520/520 and 5/5 green. Pinned requirement §4.3: if 4096 IVs are not actually tested, **do not represent the scan as exhaustive**; §4.1: cross-species one-matchup substitution must not imply whole-party substitution.
- **G6-006 candidate defect (P1 UX/contract; awaiting test):** \`pvpoke_missing_comparison._explore\` returns \`qualifying_count=0\` even before *any* battle has been verified, and \`pvpoke_missing_ui.renderExploration\` displays “条件達成 0通り” without labelling the number as *confirmed* or explicitly counting IVs whose all conditions remain unverified. Although the adjacent completed count shows \`0 / 4096\`, this ambiguous phrasing may be misread as proof that no IV qualifies. Add \`not_fully_tested_iv_count\` to the API and show “全条件の検証が未完了” separately. This is a contract/display hardening, not new battle science; source patch **must await RED**.
- Independent **positive oracle**: two candidate species / two matchup conditions, with one completed win for each different build, must remain \`evidence_pending\` / per-build \`pending\`, cross-species noted and \`party_substitution=pending\`. No combining wins from different builds. No live games or ChatGPT PvPoke MCP.
- After RED confirmation, minimal patch only and exact-head CI. Root requirement leaves all 4096 exploration optional and bounded. Current UI does only one battle per manual click; performance usability remains unoptimized and should not be misreported as a complete exhaustive exploration.
- All work in temporary, test-owned DB; no data deletion/production/merge/deploy. Release verdict stays D.


### Stage V RED confirmed; G6-006 proof-of-absence UI bug corrected
- **Red commit \`3bdd8eccfece6ef4bbb3779bec89b6ad67f225b4\`:** 522 Python tests; 521 passed, **1 expected KeyError** in \`test_unplayed_iv_space_is_explicitly_unverified_not_a_proven_zero\`. Actual failure: missing \`not_fully_tested_iv_count\` while the UI reported “条件達成 0通り” at 0/4096 completed. **Cross-species positive test passed**: separate species each with one saved win among two required conditions did **not** combine into a practical role; both remain pending.
- **G6-006 (P1 user-decision clarity):** \`pvpoke_missing_comparison._explore\` now computes \`not_fully_tested_iv_count = eligible_iv_count - all_completed_iv_count\` using existing coverage (no new simulations). Precise semantics: “not fully tested” includes partially tested IVs, even if an observed individual matchup already fails; the count is **not** an upper bound on qualification and must not be treated as positive candidates.
- \`pvpoke_missing_ui\` now uses “達成確認済み” alongside explicit “全条件の検証が未完了” rather than ambiguous “条件達成0通り”. Existing \`qualifying_count\` API key and completion state remain backward compatible.
- Native positive test added after 0/4096 assertion: one budgeted matchup leads to 1 completed IV and 4095 not-fully-tested IVs; no game engine or vendor changes, and no new repository.
- **New-head CI is pending**; verify Python suite, browser, JS and Docker before declaring green. Distinguish engine PVP standard test coverage from exhaustive evaluation of all 4096 IVs. The 1-battle-per-click UI remains a user-experience/throughput limitation, to optimize only with explicit rate/cost policy and relevant tests.
- **Verdict D** until live observational-equivalence policy, real opponent IV boundary search, ENOSPC and security CVE reachability are independently verified. Draft PR #112 stays open/unmerged. No prod changes and no ChatGPT PvPoke MCP.


### Stage VI: opponent-side IV discovery, failing proof and browser regression (2026-11-12)
- PR #112 remains Draft, head at start \`5143c82ac542a41d33b3ec8d3950ead78c546e33\`. Its Security and regression CI is **FAILURE**, despite Python 522/522 and 4/5 workflows green. Exact cause: \`tests/browser_missing_analysis.cjs\` continued waiting for old text “達成したIV　0/15/15” after Stage V deliberately renamed it to “達成を確認したIV　0/15/15”; Playwright TimeoutError 30 seconds. This is an outdated browser assertion, **not evidence of a new engine defect**. The browser fixture and literal text are updated in this checkpoint, before relying on later CI.
- Pinned requirement §4.3 asks to find important **opponent-side** IV breakpoints/bulkpoints/HP/CMP beyond the four preset modes. Existing \`IVSearch.start\` varies **self** IV while holding opponent IV fixed. \`pvpoke_iv_boundaries.js\` already computes pinned native PvPoke static move damage/CMP/HP for up to 4096 candidates, without full battle simulations.
- **New falsification tests (RED expected):** explicit \`IVSearch.opponent_boundaries\` on the enemy-side candidate for a selected standard matchup, with 4-IV and single-IV floors, accurate boundary bitsets/counts, owner-scoped authenticated API anchored to saved evaluation/build/battle keys, and strict rejection of malformed IV floors. Require \`native_battles_run=0\`, \`battle_outcomes_verified=False\`, \`evidence_class='static_boundaries_only'\`. The method/API do not exist at the start of this checkpoint: do not label success until CI confirms RED and implementation is subsequently validated.
- Proposed minimal implementation: reverse combatant orientation solely for a **static profiler preview** through already pinned \`_pool/_profiles/_prioritize\`. Keep named boundary kinds relative to **opponent as candidate**. Validate full starting HP and approved matchup. Return 4096-eligibility counts, bounded representatives and exact boundary bits; mark **static signatures do not establish equal battle outcomes or practical substitution**. No new battle history/cache/owner records and no vendor changes. UI should only request a selected authorized matchup on user click. No bulk 4096 native battle runs.
- Status after this checkpoint: browser regression fix and failing tests committed; engine/API changes pending a confirmed RED CI. Final release verdict D; no merge/deploy/production operations or ChatGPT PvPoke MCP.


### Stage VI RED confirmed and scoped opponent-side static profiler implementation
- RED SHA \`127ed22d0f5232c778f5a93b5ad9e9723be14455\`, **525 Python tests, 518 pass, 1 fail and 6 test errors**. New \`test_opponent_iv_static_boundary_profiles_use_native_not_new_battles\` and bad-floor subtests showed \`AttributeError: IVSearch has no attribute opponent_boundaries\`; authenticated API test returned 400 rather than expected 200. These failures are *new feature absence only*. Prior Stage V browser regression used a stale string; its mock and expected text were updated in the same RED commit.
- Implemented narrow \`IVSearch.opponent_boundaries\`: normalize trusted fixed standard battle; require full opponent HP; compute up to 4096 enemy IV tuples at highest legal level using existing CP/level constraints and purified-IV floors; swap opponent to native profiler's candidate side **only for stat/damage/CMP computation**. Restore initial stat-stage orientation; compute exact per-kind adjacent-IV boundary bitsets/counts, distinct static signatures, up to 32 representative IVs; check the pinned input version before/after. **No full native battle execution, no writes, no match outcomes or role coverage claimed**. A matching static signature is **not proof of matching battle outcome**.
- Authenticated API action \`opponent_boundaries\` only accepts saved evaluation ID, build ID and exact saved battle key, all filtered via the server's owner-scoped stored evidence, plus strict optional IV floors; requires feature + computation enabled. Unknown IDs and extra \`owner_scope\` rejected. Uses existing compute-owner rate limit and one compute slot; Node static profiler hard timeout 20 seconds.
- UI: only an explicit per-matchup click loads the static frontier, clearly labelled **静的境界のみ（勝敗未検証）**, and counts/representatives. Browser synthetic fixture now tests the new button under authenticated permitted context, with no horizontal overflow on mobile.
- Files changed: \`pvpoke_iv_search.py\`, \`pvpoke_missing_comparison.py\`, \`pvpoke_missing_ui.py\`, \`tests/browser_missing_analysis.cjs\`, this document. No vendor, no Battle.js, no auth secret, no history migration or deletion.
- This stage **does not** provide full opponent IV battle-result search, guarantee physical possession eligibility, or infer full-party substitute roles. Representative ranking is heuristic based on native static signatures, not outcome ranking. Further native verification is explicitly required.
- Exact post-commit CI still pending at time of this write. If green, update PR comment with exact SHA; release verdict D, keep Draft, do not deploy or merge.
