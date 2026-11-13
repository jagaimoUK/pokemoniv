# 観測履歴に基づく戦術探索：第2段階の設計契約

2026-11-13 JST。起点 `790c461419edb40f69171d9d43af6255eaa510f3`。
本書は第3段階の実装仕様であり、完成した探索機能・実戦での勝利保証ではない。
元要求仕様の「代替不能な重要役割」「保有を推測しない」「未計算を不要にしない」を維持する。
既存ソース・同梱PvPokeを正本とし、Claudeのレビュー成果は参照していない。

## 1. 決定と検証の境界

採用：**有限の観測履歴方策を、全候補世界で共有して評価する有界探索**。
相手の世界ごとに最善手を計算して勝利を合算する方式は禁止する。
探索対象は完全状態ではなく「公開履歴と自分の過去の入力から識別できる情報集合」。
初版は1対1・交代なし・既知の自分の個体と技構成・限定した相手候補集合。
パーティ全体、変身・特殊フォルム、未対応の確率効果、通信遅延への保証は含めない。

- A：既存の固定台本が特定条件で勝つ。`pvpoke_tactic_search.py` / `pvpoke_tactic_evidence.py`。
- B：同じ入力履歴に同じ行動を返し、nativeで意図と実行を照合できる。現在は限定したv1入力の実験だけ。
- C：実機でその観測と操作が可能。未検証。BからCへ自動昇格しない。

`information_fairness=not_established`、`live_reproducibility=not_verified`、
`practical_role_covered=false` を今回の全成果で維持する。
有限サンプルの非干渉テストが成功しても、観測の取得根拠は別途必要。

## 2. 観測情報の正式な契約（v2設計、未実装）

画面で直接見える値、公開イベントから推定する値、シミュレータ専用値を分離する。
以下は**保守的な入力契約**。実機UIの表示時刻や認識精度を確認済みとは扱わない。

| 情報 | 方策へ渡す値と時点 | 禁止・不明時の処理 |
|---|---|---|
| 時間 | 公開イベントの連番 `seq` とローカル観測時刻の区間。ターン推定は候補集合 | engineの `getTurns()` を実機の正確な時計として使わない。通信や演出で曖昧なら区間を広げる |
| 自分の個体・技 | 対戦前に自分が登録したbuildとGM上のコスト | 所持を推測せず、明示した個体のみ。自分の技コストは相手の情報ではない |
| 自分のゲージ | 開始値の根拠と確認済み通常技・発動による可能値集合、ボタン表示の観測 | 正確な数値表示を仮定しない。履歴が欠けた途中開始は0を仮定しない |
| 両者シールド | 開始時に観測・宣言した数と、使用を確認したイベント | 内部の使用予定・未来の消費は不可。不明なら候補数を保持 |
| 相手通常技 | 観測した使用回数の区間、識別できた技候補 | nativeの解決イベントは画面アニメーションの観測時刻の証明にならない。未識別の技を断定しない |
| 相手ゲージ技通知 | `charge_announced`、技IDを含めない | シールド判断前に、incoming move・ダメージ予測の実値・乱数結果を渡さない |
| 相手ゲージ技名 | シールド選択を確定した後の `charge_revealed` | 初版は保守的に解決後へ遅延してよい。公開時点を実機で検証するまで早めない |
| 行動受付 | 画面のボタン状態、入力した操作、受付確認の観測を別イベントにする | `ActionLogic` が呼ばれたことを操作受付可能の証拠にしない。受付不明は再推定 |
| 能力変化 | 公開された変化の対象・方向・観測時点。段階は履歴から導ける場合だけ | 実際の隠れた攻撃値・防御値、未発動のbuff判定を渡さない |
| HP | 表示されたHPバーの区間・未知。表示方式と誤差幅の版を保存 | `hp/max_hp` の生の小数を丸めただけでは十分でない。実画面解像度・アニメ中の不確実性を定義できるまで初版の分岐に使わない |
| 種族・姿 | 画面で確認した種族・姿とその識別候補 | 見えないCP/IV/レベル・技構成を既知扱いしない。見せ合い等で公開された構成は別の事前条件として明示 |
| CMP | 同時発動後に公開された実行順序 | 事前の相手攻撃実値・内部priority・次の選択を使用しない |

v1の `own_energy`、`turn`、`own_can_act` は **idealized-native-v1** の値であり、
v2の実機入力へ暗黙に変換しない。v1の64イベント上限超過は安全に停止し、
古いイベントを黙って捨てない（first_announcementや同値性が変わる）。
第3段階初版も完全履歴を上限内で保持し、圧縮は同値性の証明後に導入する。

## 3. 情報集合と非公開状態

`Context` は自分のbuild、公開された対戦条件、候補生成ルール、観測モデル版。
**実際の相手の隠れた設定を読む前に**方策選択とContextを固定する。
相手候補を作る際も実際の相手だけを正解として選別しない。

`H_t = (Context, o_0, a_0, o_1, a_1, ..., o_t)`。
同値性は正規化された公開イベントの順序・値と過去の自分の入力が等しいこと。
同じターンのイベントも `seq` で順序を保持する。ターンでソートし直さない。
方策 `pi(H_t)` は決定的。初版にランダム方策は入れない。
同じHなら、相手IV・技・ゲージ・次の行動・世界ID・探索順序にかかわらず同じa。
合法手一覧・候補集合の並び順・タイムアウト時のフォールバックにも非公開情報を混ぜない。

`BeliefSupport` は確率分布ではなく、履歴と矛盾しない世界/経路の集合。
世界の初期状態は相手IV/技構成/初期ゲージ等の仮説、以後の状態はnative遷移で作る。
区間の直積だけにすると「技とゲージ」「IVとHP」の相関を失うため、
有限初版では具体的世界と経路の組を保持する。候補数不足は `scope_incomplete`。

更新：全生存経路に自分の同一入力と許可された相手応答を適用し、
公開投影が観測の誤差区間と整合する経路だけ残す。
相手のゲージ技通知だけなら発動できるいずれかの技を残し、正解の技コストを引かない。
技名公開後に当該技を持つ経路へ絞り、各経路のnative消費値で状態を更新する。
未知の通常技や見落としは複数回数/技の可能性を残す。
集合が空になった場合は `observation_model_mismatch` として停止。隠れた真の状態を注入して復旧しない。
途中参加・不明な初期ゲージは明示された範囲（必要なら0〜100）。
広すぎて計算不能なら部分結果とし、便宜的に0へ狭めない。

## 4. 行動とnative連携

行動は `fast`、装備済みゲージ技slot 0/1、`wait_one_window`、prompt時のshield yes/no。
`wait_one_window` は公開された1操作機会に入力しないこと。通常技入力とは別で、
無入力をnative AIの通常技フォールバックに置換しないことを受入テストにする。
確実に使用可能と観測できないゲージ技は、初版では選択候補から除外する。
選択肢はBeliefSupportの共通安全集合を公開情報から算出し、真の世界で絞らない。
これは「確実に実行可能な入力だけを選ぶ」保守的な方策クラスの制限であり、
実際には実行不確実なボタン入力も可能。初版の探索で見つからないことは、
そのような入力試行を含む実戦方策の不存在を意味しない。
入力・キュー受付・有効判定・解決・消費・取消を別記録にする。
相手のKOによる取消、同時KO、シールド残数不足を勝利した操作として数えない。

再利用するもの：`pvpoke_observed_native_runner.js` の分離されたBattleラッパー、
`pvpoke_node_matrix.js` のGM/固定vendorロード、`pvpoke_sandbox.py` の入力正規化と
trace検証パターン、`pvpoke_child_env.py` の環境変数許可リスト。
`pvpoke_battle_policy.js` の詳細state/ダメージは監査オラクル用で、方策入力へ直結しない。
通常対戦/Sandboxのデータ形式とvendor本体は変更しない。

確認済みの注意：`Battle.js` は `getTurnAction()` の後で前ターンのゲージ技による
入力抑制を適用する。現runnerの `own_can_act=true` は受付保証ではない。
また解決hookはダメージ適用後であり、画面表示時刻を表さない。
第3段階は「提案hook」と「入力受付確認」を分け、観測v2の受付モデルを先にテストする。
**方策の呼出しスケジュールも観測モデルの一部**とする。nativeのgetTurnActionは
cooldown/hasActedで呼出しを制限するため、呼ばれた回数や時刻自体が情報になる。
v2では公開されたローカル観測clockとpromptイベントからdecision windowを作り、
そのwindowで意図を選んでからnativeへ入力する。エンジンの都合だけでwindowを増減しない。
受付・解決の内部監査は常に残すが、公開根拠がない受付通知を方策の次の履歴に入れない。

ObservationModelは公開イベントの配送遅延・見落とし・順序曖昧性を具体的な有限枝として
定義する。初版の理想観測はdelay=0/miss=0という明示仮定であり実機保証はない。
実機用モデルでは同一native履歴から複数の観測履歴が生じうる。合法な順序だけを保持し、
不明な順番を真のengine順で確定しない。観測枝も世界/相手応答と同じく評価の全称対象。
同時行動では片側の入力を決めた後、その未公開入力をもう片側へ見せない。
CMPのnative攻撃値は順序検証専用とし、方策を呼ぶ引数には入れない。

確率効果：標準nativeの累積buff判定とSandboxの指定buffは実ゲームの確率分布ではない。
初版はそのモデル名を必須で記録。確率buff・同値CMPの全分岐を再現できない対面は
`unsupported_uncertainty` とし、頑健な役割成立の対象外。乱数seedだけを保存して
「全ての場合」を検証した扱いにしない。攻撃のミニゲームは最大成功という仮定を明記。

## 5. 探索方式の比較と選択

| 方式 | 利点 | 初版での扱い |
|---|---|---|
| 完全状態の有界探索 | 小さい問題の比較オラクルに使える | 隠れた世界ごとの最善手はstrategy fusionになるため採用しない |
| Minimax | 明示した相手応答に対する最悪値を評価できる | 情報集合を共有した方策候補の評価に採用。完全状態木の単純Minimaxは禁止 |
| Monte Carlo/MCTS | 多数の対面を近似しやすい | 希少な負けを見落とし、未知の事前確率を導入しがち。後続の順位付け用途のみ |
| 観測履歴の有限方策探索 | 情報公平性を構造で制約でき、決定的再実行が可能 | 採用。上限到達はunknown。巨大な最適方策の保証はしない |
| 固定戦術探索の拡張 | 既存キャッシュとテストを活用しやすい | 候補行動/方策テンプレートの種としてのみ利用。台本の集合を方策に昇格しない |

初版手順（exact within declared finite domain、最適化は後回し）：

1. 自分の同一build、役割条件、候補世界、相手応答モデル、観測版、行動順を固定。
2. 方策テーブルは `history_key -> intent`。全世界・全経路で同じテーブルを利用。
3. 各世界を初期状態からnativeで再生し、初めて遭遇した未定義historyで停止。
4. そのhistoryで許可する各行動に対しテーブルを複製し、一つの行動を追加。
   一つの世界だけで選んだ手を別世界に都合よく変更しない。history出現順は正規順。
5. すべての世界・相手応答経路を同じテーブルで再生/評価し、未定義historyを展開。
   相手はworld IDではなく、そのプレイヤーに許す情報と応答規則に従う。
6. 完全な葉だけ評価を確定。途中打切りはunknown。全葉が役割成立した場合だけ
   「宣言した有限シナリオ内で成立」。探索しなかった世界や相手行動への保証は付けない。
7. 全候補探索が終わった時だけ、この有限方策クラスでの最適性を記録。
   一つの方策の評価が終わったことと、より良い方策がないことは別。

量化条件は `存在する同一方策 pi / 全ての宣言world・相手controller・確率枝・観測枝 /
役割predicate成立（有限horizon内）`。候補方策を一つ反例で棄却しても、
探索全体は `no_policy_found_within_budget`。有限方策クラスを完全に尽くした場合だけ
`no_policy_in_declared_class` とし、実戦一般の「勝ち筋なし」と表示しない。

初版相手モデル：standard native AI（内部情報を使う比較相手と表示）、
即撃ちslot 0/1、通常技を0/1/2回追加して撃つ、盾never/always/firstを
固定した組合せの決定的controller集合。これは全ブラフ/任意タイミングを網羅しない。
複数の相手controllerを評価しただけなら `opponent_response_complete=false`。
全応答木を後に実装する場合は、到達した全情報集合の合法行動を列挙し、
途中で相手controllerを恣意的に切替える評価とは区別する。

再生方式を選ぶ理由：nativeの内部キュー、cooldown、buff meter等を独自に複製すると
遷移を壊しやすい。初版は決定的な初期状態からprefixを再生し、任意状態復元を避ける。
再生時に同じprefixと同じモデルでイベントが変われば `nondeterministic_replay` として停止。

## 6. 評価と不足個体への接続

優先順位は、(1) 重要役割の成立、(2) その最悪ケース、(3) 残り盾・HP・ゲージ。
役割ごとに `true / false / unknown`。全ての宣言シナリオで検証済みtrueならscope内true、
一つでも検証済みfalseならscope内false、falseなしで未完了があればunknown。
falseとunknown件数は別々に返す。勝利、同時KO、timeout、未対応を分け、drawを勝ちにしない。

役割は重要度付きのベクトルで返し、主要役割の欠落を平均得点で打ち消さない。
比較はまず要求した重要役割の包含関係、次に各役割での最悪outcome、
同条件同buildの残り資源ベクトルのPareto優越。非比較なら優劣保留。
重み付き和は任意の参考表示で、重みと根拠を保存する。
最悪値も未探索枝があれば確定しない。成功済みの一部枝だけの最小値は `sample_min`。
残量はオラクルによる評価値として取得可能だが、対戦中の次の判断へ逆流させない。

確率の根拠がない候補集合を等確率としない。期待勝率は既定で `null`。
利用者が事前分布を明示した場合だけ、対象・重み・根拠・版を付けた「仮定付き期待値」。
乱数効果の確率と相手がその技構成/行動を選ぶ確率は別物。

不足個体へ接続する際は、同一 `build_id` と技構成、同一の事前Contextで固定した方策が
要求条件を満たす必要がある。公開された対面種族などは方策の分岐にできるが、
見えない相手IVごとに別の方策を採用して勝ちを合算することは禁止。
代替不能性は検証済み比較集合の中だけ。未計算IVや未保有不明は反証にならない。
今回 `pvpoke_tactic_evidence.py` と通常RoleEvaluationは変更しない。

## 7. データ構造・保存・上限（第3段階）

```text
ObservationV2 = {schema, seq, phase, public_events, self_knowledge,
                 timing_candidates, observation_model_id}
PublicEvent = {seq, observed_time_range, kind, payload_allowlisted}
Intent = {kind, own_move_slot? / use_shield?}
Policy = {schema, context_hash, observation_model_id, table, fallback:"stop_unknown"}
Support = {hypothesis_ids, surviving_path_ids, coverage, mismatch_reason?}
Evaluation = {policy_hash, build_id, role_condition_ids, scenario_manifest_hash,
              tested, failed, unknown, role_vector, resource_vectors,
              expected_value:null, scope_complete, opponent_response_complete,
              information_fairness:"not_established",
              live_reproducibility:"not_verified", practical_role_covered:false}
Checkpoint = {owner_scope, search_hash, version_hashes, frontier,
              completed_evaluation_ids, next_work_id, budgets, stop_reason}
```

`PublicEvent` は種別ごとの厳密なフィールド許可リスト。世界ID、native state、正確な相手HP、
技公開前のID、乱数、診断ログを含めない。監査用の全状態は別の内部オブジェクト。
履歴keyはschema/Contextと順序付き履歴を正規化してSHA-256。浮動小数のHP比は禁止。
区間は整数単位・端点規約固定。nullと空集合を区別。過去の自分の操作も含める。

初期上限（設定案、負荷試験で減らしてよい）：世界32、相手controller8、観測配送枝4、方策64、
1対戦500 engineターン、1trace512決定、公開イベント64（v1試作互換の小規模段階）、
1step native再生8回・5秒、1job新規再生4096回、worker peak RSS 256 MiB。
時間制限とメモリ上限はホスト側で監視し、実行中の子を安全に終了して未完了にする。
これらは今回のrunnerに新たに実装した制限ではない。
候補世界の直積が上限を超えても黙って先頭32だけで網羅済みとしない。

方策数P、世界W、相手controllerR、観測配送枝O、対戦長Tで評価 O(P W R O T)。
未定義history数I、分岐Aで最悪方策数 A^I。再生によるprefix探索は深さDで
さらに最大O(D)程度の再評価コストがかかるため、job再生上限を必ず全段階で数える。
相手全応答木は別途指数的。初版は有限controller集合を選び、その制約を表示する。

キャッシュkeyはengine/GM/adapter/観測モデル/policy/正規化初期状態/相手controller/
buff・CMPモデル/役割評価版を含む。ownerはサーバー認証から導出。
固定Sandbox結果は同じ行動・イベント・版の再生補助にのみ使い、方策評価への横流しは禁止。
監査履歴に基づく更新前の結果と新方策を混ぜない。保存JSONのハッシュだけでなく意味を再検証。
未知・取消・時間切れは勝敗キャッシュを作らずcheckpointに残す。

新しいowner別namespaceで保存し、既存表を書き換えない。既存BattleStoreのtransaction・
容量予約・child envを再利用。実行単位の結果と次位置を原子的に保存し、
同じwork IDの再試行は重複作成しない。再開時に版・Context・owner・manifestを検証。
staleでも旧履歴を削除しない。認証前のHTML/APIにstate/trace/秘密情報を埋め込まない。

## 8. 今回の小規模試作とテスト基準

`pvpoke_observed_audit.py` はv1限定のオフライン監査。全traceで共有する履歴keyに対し
行動の一致を検証し、過去観測の書換え・非公開フィールド・不正な操作を拒否する。
過去の自分の選択もkeyに含み、現在の選択は照合後にkeyへ加える。
世界IDは入力しない。同一履歴で後知恵の行動を混ぜる反例を失敗させる。
入力が本当に観測されたことや操作受付を証明するモジュールではない。
policy引数はv1の自分の技・入力検証用で、与えたtraceがその方策を実行した証明ではない。
nativeテストでは各decisionを独立にproposeへ再入力して、その別の条件を照合する。
一般の方策では実行前にpolicy hashを固定し、再評価記録とContext/engine/GM/観測版/
scenario manifestを結び付ける。漏えいで全履歴が一意になれば監査は自明に通るため、
`repeated_histories`と意図的に同じ公開prefixを持たせた反例を必須にする。

native runnerに、通常判断とシールド判断の発生順を保持する `decision_trace` を追加。
隠れた相手IV・ゲージ・装備技を変えたnative試験で、共通prefixの行動を比較する。
将来の分岐後に履歴が異なるなら行動が異なることは許される。
PythonとJSの既存単純方策をtraceの各判断で照合し、実行結果は既存native testsで確認。

第3段階の必須受入テスト：

1. 全共有historyの非干渉。相手IV/エネルギー/未公開技/乱数seed/列挙順を変更。
   テストは同じsnapshotを2回呼ぶだけでなく、native投影から履歴を作る。
2. 同じhistoryに異なる最善手を持つ2世界で、両方に勝てると誤報しない。
   別方策を世界ごとに選ぶnegative controlを必ず失敗させる。
3. ゲージ通知時は技未公開、盾確定後だけ技公開。既知の過去技と今回の未知技を分離。
4. 実際の新規公開情報後にのみ方策分岐可能。過去の選択は変えられない。
5. 1〜5ターン技、ゲージ閾値±1、100上限、CMP高低/同値、同時KO、
   charge後の入力抑制、取消、盾0/1/2、初期HP/ゲージ/能力変化、確率効果の未対応拒否。
6. 未探索/時間切れ/空supportはunknown。保存再開は順序・結果・計算回数が連続実行と一致。
7. phase/順序/区間の不正値、未来イベント、他owner ID、過大入力、古いcacheを拒否。
8. 324標準golden・200 native Sandbox合成例・不足個体/通常厳選/メタ/パーティ/保存の回帰。
9. 実機録画等の合成・許諾済み資料で通知/技名/HP/ゲージ/受付の観測可能時点を照合。
   私的対戦映像や識別情報を外部へ送らない。通信遅延・見落としを含む再現率を別記。

## 9. 第3段階の変更順序

1. 新 `pvpoke_observed_observation.py`：v2型・公開イベント許可リスト・history key。
   `pvpoke_observed_policy.py` のv1は互換維持し、v2を別入口にする。
2. `pvpoke_observed_native_runner.js`：観測投影、共通方策tableの読取、未定義history停止、
   入力受付/取消の監査、決定的prefix再生。vendor/通常runnerは変更しない。
3. 新 `pvpoke_observed_search.py`：有限controller/世界manifest、共有table探索、tri-state評価。
   `pvpoke_observed_audit.py` をv2用に別schemaで拡張し、v1と取り違えない。
4. 既存 `pvpoke_battle_store.py` のAPIを使う新保存namespace、checkpointと版照合。
   `tests/test_observed_search.py` にstrategy fusion、予算停止/再開、cache無効化を追加。
5. 以上のCLI/内部試験が成立してから認証済みAPI、最後に `pvpoke_missing_ui.py` /
   `pvpoke_sandbox_ui.py`。`pvpoke_tactic_evidence.py` にscope付き別区分を追加しても
   通常の実戦役割フラグは維持。Cの検証完了と別レビューまで役割昇格を実装しない。

公開前の未解決：実機観測v2の校正、nativeの確率効果・同値CMPの実戦対応、
相手応答の網羅範囲、branch数の実測、障害復旧と認証境界。UI・大規模探索は未実装。

## 10. 検証記録

起点CIは11/11成功、PR #111/#112はDraft。今回の結果とコミットは
`ASTRA_REVIEW_CONTINUATION.md` の先頭に記録する。本書を変更したコミット自体が
第2段階チェックポイント（`git log -1 --format=%H -- docs/OBSERVED_TACTIC_DESIGN_20261113.md`）。
