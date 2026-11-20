"""Mobile-first Party Builder page, protected by the existing app session."""
HTML = r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>パーティ作成</title><style>
:root{font:16px system-ui,sans-serif;background:#122126;color:#e2f1e9;color-scheme:dark;overflow-x:clip}*{box-sizing:border-box}
body{margin:0;overflow-x:clip}main{max-width:980px;margin:auto;padding:16px 14px 100px;min-width:0}h1{margin:6px 0;font-size:21px;display:flex;align-items:center;gap:8px}h2{font-size:18px;margin:0 0 10px}h3{font-size:15px;margin:12px 0 6px}
p{line-height:1.6;color:#b6cac4;margin:6px 0;overflow-wrap:anywhere}a{color:#bbebd4}
section{margin-top:18px;padding:18px;border:1px solid #3d5852;border-radius:20px;background:#1a2a30;min-width:0;max-width:100%;overflow-wrap:anywhere}
.section-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}
.section-head h2{margin:0}
.info-btn{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;min-height:unset;padding:0;border-radius:50%;font-size:12px;font-weight:700;border:1px solid #578577;background:#203834;color:#aee0d0;cursor:pointer;flex-shrink:0}
.info-btn:hover{background:#30524a}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
nav,.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;min-width:0}
button,nav a{border:1px solid #76a797;border-radius:14px;min-height:44px;padding:9px 13px;background:#385c50;color:#edf8f1;font:inherit;cursor:pointer;text-decoration:none;max-width:100%;overflow-wrap:anywhere}
button.primary{background:#4b7f6b;border-color:#98cdb9;font-weight:700}
button.secondary{background:#294743;border-color:#6a9688}
button.small-btn{min-height:38px;padding:6px 12px;font-size:14px;border-radius:12px}
button.danger{background:#663344;border-color:#b06880}
button:disabled{opacity:.45;cursor:not-allowed}
.primary-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:16px}
.big-action-btn{min-height:52px;font-size:16px;font-weight:700;border-radius:16px;box-shadow:0 4px 12px rgba(0,0,0,0.25)}
input,select,textarea{width:100%;min-width:0;max-width:100%;border:1px solid #67887d;border-radius:12px;padding:10px;min-height:44px;background:#12252b;color:inherit;font:inherit}
input[type=checkbox]{width:auto;min-height:unset}label{font-size:13px;display:block;margin:8px 0 4px;min-width:0;max-width:100%;overflow-wrap:anywhere}
textarea{min-height:90px;resize:vertical}details{min-width:0;max-width:100%}summary{cursor:pointer;min-height:42px;padding:8px 0;font-weight:bold;overflow-wrap:anywhere}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;min-width:0;max-width:100%}
.suggestions{display:flex;flex-direction:column;gap:5px;margin-top:6px;max-height:240px;overflow:auto}.suggestions button{text-align:left;width:100%;font-size:13px}
.mon{border-radius:16px;background:#233735;border:1px solid #4a6c62;min-width:0;max-width:100%;overflow:hidden;transition:border-color .15s,box-shadow .15s}
.mon[data-locked=true]{border-color:#9edbc2;box-shadow:0 0 0 1px #9edbc2 inset}
.mon-summary{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 12px;cursor:pointer;min-height:64px;list-style:none;user-select:none}
.mon-summary::-webkit-details-marker{display:none}
.mon-header-main{display:flex;flex-direction:column;gap:3px;min-width:0;flex:1}
.mon-name{font-size:15px;font-weight:600;color:#edf8f1;overflow-wrap:anywhere}
.mon-badges{display:flex;flex-wrap:wrap;gap:4px}
.move-badge{font-size:11px;padding:1px 6px;background:#2d4841;border:1px solid #577d71;border-radius:6px;color:#d0ebd0}
.lock-toggle{display:inline-flex;align-items:center;gap:4px;padding:6px 9px;border-radius:10px;background:#182827;border:1px solid #4c7267;font-size:12px;cursor:pointer;flex-shrink:0}
.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;min-width:0;max-width:100%}
.fields label:first-child{grid-column:1/-1}
.card-footer{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;gap:6px;flex-wrap:wrap;margin-top:10px;min-width:0}
.card-clear{min-height:36px;padding:4px 12px;font-size:13px;background:#3a3542;border-color:#7d718c}
dialog.mon-modal{position:fixed;inset:0;margin:auto;width:min(440px,calc(100vw - 24px));max-height:86dvh;overflow-y:auto;border:1px solid #639282;border-radius:20px;padding:18px;background:#192c31;color:#e2f1e9;z-index:50}
dialog.mon-modal::backdrop{background:rgba(8,18,22,0.75);backdrop-filter:blur(3px)}
dialog.info-modal{position:fixed;inset:0;margin:auto;width:min(440px,calc(100vw - 24px));max-height:80dvh;overflow-y:auto;border:1px solid #558575;border-radius:20px;padding:20px;background:#192c31;color:#e2f1e9;z-index:60}
dialog.info-modal::backdrop{background:rgba(8,18,22,0.7);backdrop-filter:blur(3px)}
.modal-header{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:12px}
.modal-header h3{margin:0;font-size:17px}
section[hidden],div[hidden],details[hidden],label[hidden],button[hidden]{display:none}
#status{white-space:pre-wrap;border-radius:12px;background:#2a4140;padding:10px 12px;overflow-wrap:anywhere;font-size:14px}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;background:#355952;border:1px solid #6fa192;margin:2px 4px 2px 0}
.badge.warn{background:#5c4529;border-color:#c9a267;color:#ffedd2}
.badge.unknown{background:#4b555a;border-color:#93a6ae;color:#edf5f8}
.badge.danger{background:#663042;border-color:#cc7591;color:#ffe3ec}
.meta-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.compare-checks{display:flex;flex-wrap:wrap;gap:10px;margin:6px 0}
.compare-checks label{display:inline-flex;align-items:center;gap:5px;margin:0;padding:6px 10px;border:1px solid #4c6a5f;border-radius:12px;background:#192d33}
#metaWeights{display:flex;flex-direction:column;gap:7px;margin-top:10px}
.weight-row{display:flex;gap:10px;align-items:center;justify-content:space-between;border:1px solid #4c6a5f;border-radius:12px;padding:7px 9px;background:#2a4140}
.weight-row span{flex:1;min-width:0;overflow-wrap:anywhere}
.weight-row select{width:115px;flex:0 0 115px;min-height:42px}
.weight-row small{display:block;color:#abc8bd;font-size:11px;margin-top:2px}
.evidence-box{border:1px solid #4c6a5f;border-radius:12px;padding:10px;background:#182a30;margin-top:8px;font-size:13px;min-width:0;max-width:100%;overflow-wrap:anywhere}
.obs-table{width:100%;border-collapse:collapse;font-size:12px;margin:6px 0}
.obs-table th,.obs-table td{border-bottom:1px solid #3c5952;padding:5px 4px;text-align:right;white-space:nowrap}
.obs-table th:first-child,.obs-table td:first-child{text-align:left}
.obs-scroll{overflow-x:auto;max-width:100%}
.alert-box{border:1px solid #c9a267;background:#3a2f20;color:#ffedd2;border-radius:12px;padding:10px 12px;margin:8px 0;font-size:13px;min-width:0;max-width:100%;overflow-wrap:anywhere}
.result-card{padding:14px;margin:10px 0;border:1px solid #5c8376;border-radius:16px;background:#233a3a;min-width:0;max-width:100%;overflow-wrap:anywhere}
.triple-card{padding:12px;margin:8px 0;border:1px solid #4d7066;border-radius:14px;background:#1d3236;min-width:0;max-width:100%;overflow-wrap:anywhere}
.triple-card.unfavorable{border-color:#8a5568;background:#2c222a}
.triples-carousel-wrapper{margin:12px 0}
.carousel-tabs{display:flex;gap:8px;margin-bottom:10px}
.carousel-tab-btn{flex:1;min-height:42px;padding:6px 12px;font-size:14px;border-radius:12px;border:1px solid #537a6e;background:#223835;color:#d6ebe3;cursor:pointer;transition:background .15s,border-color .15s}
.carousel-tab-btn.active{background:#3d6859;border-color:#8acbb3;font-weight:700;color:#fff}
.carousel-track{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;gap:12px;padding-bottom:6px;-webkit-overflow-scrolling:touch}
.carousel-slide{flex:0 0 100%;min-width:100%;scroll-snap-align:start;box-sizing:border-box}
.matrix-card{border:1px solid #4f7367;border-radius:14px;padding:12px;margin:8px 0;background:#203538}
.matrix-cols{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:6px}
.matrix-win-box{background:#1a322e;border:1px solid #3f6e5e;border-radius:10px;padding:8px}
.matrix-loss-box{background:#36232c;border:1px solid #6f3b4f;border-radius:10px;padding:8px}
.generator-box{border:1px solid #527c6f;border-radius:14px;padding:12px;background:#22373a;margin:12px 0}
#strategyResult,#weakResult,#summaryResult,#swapAdvice,#recommendedThree,#allTriplesPanel{min-width:0;max-width:100%;overflow-wrap:anywhere}
footer{position:fixed;bottom:0;left:0;right:0;background:#172d2cf5;border-top:1px solid #638276;padding:10px;z-index:20}
footer .tools{max-width:700px;margin:auto}footer button{flex:1}
.result{padding-top:10px;border-top:1px solid #557769;margin-top:10px}li{padding:3px 0}
.completion-card{padding:12px;margin:10px 0;border:1px solid #6a9586;border-radius:16px;background:#29413f}
dialog.party-drawer{width:min(460px,calc(100vw - 20px));max-height:88dvh;overflow-y:auto;border:1px solid #6a9586;border-radius:18px;padding:16px;background:#1a2e33;color:#e2f1e9}
dialog.party-drawer::backdrop{background:#091316cc}
dialog.party-comparison{position:fixed;inset:0;margin:0;width:100%;max-width:100%;height:100dvh;max-height:100dvh;border:0;border-radius:0;padding:0;background:#122126;color:#e2f1e9;overflow-y:auto;overscroll-behavior:contain;font-size:16px}
.party-comparison::backdrop{background:#122126}
.compare-header{position:sticky;top:0;z-index:5;background:#122126;padding:12px max(12px,env(safe-area-inset-right)) 12px max(12px,env(safe-area-inset-left));display:flex;justify-content:space-between;align-items:center;gap:12px;border-bottom:1px solid #47645d}.compare-header h2{margin:0;font-size:20px}.compare-header button{flex-shrink:0}
.compare-content{max-width:900px;margin:auto;padding:12px 12px max(24px,env(safe-area-inset-bottom))}.compare-content>p{font-size:16px;margin:12px 0}
.compare-controls{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.compare-controls label{margin:3px 0;font-size:16px}.compare-controls select{font-size:16px;min-height:48px;padding:10px 6px}
.party-comparison .compare-heatmap{table-layout:fixed;font-size:16px;width:100%;border-spacing:6px}
.party-comparison .compare-heatmap th,.party-comparison .compare-heatmap td{min-width:0;max-width:none;white-space:normal;overflow-wrap:anywhere;padding:12px 8px}
.party-comparison .compare-heatmap th{font-size:17px;position:static;text-align:center;background:#203138;border-radius:12px}
.party-comparison .compare-heatmap th:first-child{min-width:0;width:auto;position:static}
.party-comparison .compare-heatmap td{border-radius:14px;vertical-align:top}
.party-comparison .compare-heatmap td strong{display:block;font-size:18px;line-height:1.5;font-weight:600}
.party-comparison .compare-heatmap td span{display:block;padding:8px 0 2px;font-size:22px;line-height:1.4}
.party-comparison .compare-heatmap td small{display:block;font-size:16px;line-height:1.5}
.compare-scroll{overflow:visible;max-height:none;margin:12px 0}.compare-opponent{font-size:22px;line-height:1.5;margin:16px 0 8px}.compare-paging{justify-content:space-between;margin:14px 0}.compare-paging span{font-size:16px}
.heatmap{border-collapse:separate;border-spacing:3px;text-align:center;font-size:12px;width:100%}
.heatmap th{padding:7px 3px;min-width:51px;max-width:95px;overflow-wrap:anywhere}
.heatmap th:first-child{min-width:95px;position:sticky;left:0;background:#203138;z-index:1;text-align:left}
.heatmap td{white-space:pre-line;font-variant-numeric:tabular-nums;padding:8px 2px;border-radius:8px}
.heat-win{background:#236e96;color:#fff}.heat-mid{background:#85819e;color:#fff}.heat-loss{background:#953276;color:#fff}.heat-unknown{background:#52615d;color:#fff}
@media(max-width:550px){main{padding:10px 8px 110px}section{padding:14px}.fields{grid-template-columns:1fr}.meta-row{grid-template-columns:1fr}.matrix-cols{grid-template-columns:1fr}}
</style></head><body><main>
<div class="topbar">
 <nav><a href="/app">← 個体値厳選</a><a href="/flashcards">フラッシュカード</a></nav>
 <button id="partyMenuBtn" type="button" class="small-btn secondary" hidden>パーティ</button>
</div>
<h1>見せ合い6体・未来メタ補完 <button id="infoBtnMain" type="button" class="info-btn" data-info="main" title="ヘルプ">ⓘ</button></h1>

<section id="auth"><h2>アプリに接続</h2><p>ログイン済みのブラウザでは自動接続します。</p><div class="tools"><input id="key" type="password" autocomplete="off" placeholder="接続キー"><button id="login">接続する</button></div></section>

<div id="workspace" hidden>
 <section>
  <div class="section-head"><h2>自分の6体</h2><button id="infoBtnRoster" type="button" class="info-btn" data-info="roster" title="ヘルプ">ⓘ</button></div>
  <div class="grid" id="members"></div>
  <div class="primary-actions">
   <button id="autoComplete" class="primary big-action-btn" disabled>自動補完</button>
   <button id="evaluate" class="secondary big-action-btn" disabled>パーティ評価</button>
  </div>
 </section>

 <section>
  <div class="section-head"><h2>メタ・未来メタ選択</h2><button id="infoBtnMeta" type="button" class="info-btn" data-info="meta" title="ヘルプ">ⓘ</button></div>
  <div class="meta-row">
   <label>基準メタ（現行）<select id="meta"></select></label>
   <label>評価シナリオ<select id="scenario"></select></label>
  </div>
  <details id="compareScenariosDetails"><summary>複数シナリオを比較（平均＋最悪ケース）</summary>
   <p>選択したシナリオを同じ対面キャッシュで同時評価し、平均と最悪ケースを表示します。</p>
   <div id="compareScenarios" class="compare-checks"></div>
  </details>
  <details id="scenarioEditorDetails"><summary>未来メタの重み編集・根拠・シナリオ管理</summary>
   <div id="scenarioEvidence" class="evidence-box"></div>
   <div class="generator-box">
    <h3 style="margin-top:0">選択中メタから未来シナリオを自動生成</h3>
    <div class="fields">
     <label>軸にするポケモン<select id="genSpecies"></select></label>
     <label>変化予測<select id="genTrend"><option value="rise">台頭・増加（対策枠も連鎖増加）</option><option value="counters">対策枠の台頭（鋼・耐性枠等）</option><option value="decline">減少・下火</option></select></label>
    </div>
    <div class="tools" style="margin-top:8px">
     <button id="generateScenarioBtn" type="button" class="small-btn primary">この条件で未来シナリオを生成</button>
    </div>
   </div>
   <label for="metaFilter">ポケモンを絞り込む（日本語・英語）</label><input id="metaFilter" type="search" placeholder="例：メルメタル、Florges、ミミッキュ">
   <p id="metaWeightStatus" role="status">メタのポケモン一覧を読み込みます。</p>
   <div id="metaWeights" aria-label="シナリオ別の重要度"></div>
   <p id="metaWeightSaveStatus" role="status"></p>
   <div class="result">
    <h3>未来シナリオを独立保存</h3>
    <label for="scenarioName">シナリオ名（対象が分かる名前・現行メタ重複不可）</label>
    <input id="scenarioName" maxlength="60" placeholder="例：独自予測（鋼増加）">
    <label for="scenarioSummary">メモ・仮定（任意）</label>
    <input id="scenarioSummary" maxlength="200" placeholder="例：対策枠増加後の再適応を想定">
    <div class="tools">
     <button id="scenarioSave" type="button" class="small-btn">現在のシナリオを上書き保存</button>
     <button id="scenarioSaveAs" type="button" class="small-btn secondary">新しい未来シナリオとして保存</button>
     <button id="scenarioDelete" type="button" class="small-btn danger" hidden>削除</button>
    </div>
    <p id="scenarioManageStatus" role="status"></p>
   </div>
  </details>
 </section>

 <section>
  <details id="poolDetails"><summary>所持・候補ポケモン（任意・最大48体）</summary>
   <p>登録した候補を優先して自動補完します。未入力・不足分はメタから仮候補（所持未確認扱い）を補って探索します。</p>
   <textarea id="pool" placeholder="azumarill,BUBBLE,ICE_BEAM,PLAY_ROUGH,0,15,15"></textarea>
  </details>
  <details id="enemyDetails"><summary>相手6体（任意・入力すると相手別選出＆詳細戦術を設定可）</summary>
   <p>相手6体を入力すると、公開6体に対する合理的対策を踏まえた推奨3体選出と、相手構成別の詳細戦術設定が利用できます。</p>
   <textarea id="enemy" placeholder="clodsire,POISON_STING,STONE_EDGE,EARTHQUAKE"></textarea>
   <details id="opponentStrategyPanel" hidden><summary>相手構成別の詳細戦略（任意）</summary>
    <section id="strategyConfig" style="margin-top:8px">
     <p>相手6体が確定したときのみ、特定の1対1や後追い分岐の詳細条件を設定して比較できます。</p>
     <label for="strategyEnemy">詳細戦略の相手</label><textarea id="strategyEnemy" placeholder="clodsire,POISON_STING,STONE_EDGE,EARTHQUAKE"></textarea>
     <button id="copyEnemy" type="button" class="small-btn secondary">上の相手6体を反映</button>
     <div class="fields">
      <label>対象の自分（後追い分岐では引き先）<select id="strategySelf"></select></label>
      <label>対象の相手（分岐では相手初手）<select id="strategyOpponent"></select></label>
     </div>
     <details><summary>受けた後に果たす仕事</summary>
      <label>計算前に固定する条件<select id="workKind"><option value="charged">指定ゲージ技を撃つ</option><option value="fast_damage">通常技で指定割合を削る</option><option value="force_shield">相手のシールドを使わせる</option></select></label>
      <label>指定するゲージ技<select id="workMove"></select></label>
      <label>通常技で削る相手最大HPの割合（%）<input id="workFraction" type="number" min="1" max="100" value="15"></label>
     </details>
     <details><summary>シールドとブラフの詳細</summary>
      <label>相手の技構成<select id="publicMoves"><option value="1">公開チームシート（指定技が既知）</option><option value="0">非公開（公開習得技と観測履歴で判断）</option></select></label>
      <div class="fields"><label>温存・手動時の自分ブラフ<select id="selfBait"><option value="1">選択的に使う</option><option value="0">使わない</option></select></label><label>温存・手動時の相手ブラフ<select id="opponentBait"><option value="1">選択的に使う</option><option value="0">使わない</option></select></label></div>
      <div class="fields"><label>危険閾値（現在HP比）<input id="dangerRatio" type="number" min="0.5" max="1" step="0.05" value="0.95"></label><label>平常時に温存する枚数<input id="reserve" type="number" min="0" max="2" value="1"></label></div>
      <label>自分の手動方針（受ける=0、貼る=1）<input id="manualSelf" value="0,1,0,1"></label>
      <label>相手の手動方針<input id="manualOpponent" value="0,1,0,1"></label>
     </details>
     <details><summary>初手→交代→後追い（限定モデル）</summary>
      <label><input id="includeBranch" type="checkbox"> 相手6体の合法な後追い候補を計算する</label>
      <div class="fields"><label>自分の初手<select id="strategyLead"></select></label><label>残り1体<select id="strategyCloser"></select></label><label>初手の経過ターン<input id="leadTurns" type="number" min="0" max="12" value="2"></label><label>後追い遅延ターン<input id="chaseDelay" type="number" min="0" max="12" value="2"></label></div>
     </details>
     <button id="runStrategy" type="button" class="small-btn">詳細条件を比較する</button>
    </section>
   </details>
  </details>
  <details id="advancedCalcDetails"><summary>詳細計算オプション（任意・初期OFF）</summary>
   <label><input id="strategyRefinement" type="checkbox"> 詳細戦略を上位案比較へ反映する（追加計算）</label>
   <p>初期OFF。ONにすると上位最大3案を重要対面最大3条件の通常技圧力・受け後の仕事・温存・後追いで追加検証します。</p>
   <label><input id="opponentUncertainty" type="checkbox"> 相手の技・IV感度を比較する（追加計算）</label>
   <p>初期OFF。重要度上位2グループを複数技構成・IV条件で頑健性比較します。</p>
   <label for="hypotheses">追加する相手の技構成（任意・最大8件）</label>
   <textarea id="hypotheses" placeholder="名前から相手の別技構成を追加"></textarea>
  </details>
 </section>

 <section id="resultsSection">
  <h2>計算状況と結果</h2>
  <div id="status" role="status" aria-live="polite">接続を確認しています。</div>
  <div id="unknownBanner"></div>
  <div id="summaryResult"></div>
  <div id="swapAdvice"></div>
  <div id="recommendedThree"></div>
  <div id="weakResult"></div>
  <div id="allTriplesPanel"></div>
  <div id="strategyResult" aria-live="polite"></div>
 </section>
</div>
</main>

<dialog id="partyDialog" class="party-drawer" aria-label="パーティ保存・切り替え">
 <div class="topbar"><h2 style="margin:0">パーティ管理</h2><button id="closePartyDialog" type="button" class="small-btn secondary">閉じる</button></div>
 <p id="partyState" role="status">新規パーティ（未保存）</p>
 <label for="partyName">パーティ名</label>
 <input id="partyName" value="新しいパーティ" maxlength="60">
 <div class="tools" style="margin-top:8px">
  <button id="save" type="button" class="small-btn primary">保存・上書き</button>
  <button id="saveAs" type="button" class="small-btn secondary">別名保存</button>
  <button id="renameParty" type="button" class="small-btn secondary">名前変更</button>
  <button id="newParty" type="button" class="small-btn secondary">新規</button>
 </div>
 <div class="result">
  <label for="saved">保存済みのパーティ（最大32件）</label>
  <select id="saved"><option value="">読み込むパーティを選ぶ</option></select>
  <div class="tools" style="margin-top:8px"><button id="load" type="button" class="small-btn">切り替え</button></div>
 </div>
 <div id="unsavedGuard" class="alert-box" hidden>
  <p id="unsavedGuardMsg">未保存の変更があります。保存せずに続けますか？</p>
  <div class="tools">
   <button id="confirmDiscard" type="button" class="small-btn danger">保存せず切り替え</button>
   <button id="cancelDiscard" type="button" class="small-btn secondary">キャンセル</button>
  </div>
 </div>
</dialog>

<dialog id="infoDialog" class="info-modal" aria-label="説明">
 <div class="modal-header">
  <h3 id="infoTitle" style="margin:0">説明</h3>
  <button id="closeInfoDialog" type="button" class="small-btn secondary">閉じる</button>
 </div>
 <div id="infoBody" style="line-height:1.7;font-size:14px;color:#cde0d8;margin-top:10px"></div>
</dialog>

<div id="cancelContainer" style="max-width:980px;margin:10px auto;text-align:center" hidden>
 <button id="cancel" class="danger small-btn" disabled>計算を中止する</button>
</div>

<script>
'use strict';
const $=id=>document.getElementById(id);
let key='',catalog={},metaItems=[],scenarioItems=[],observations=null;
let partyId=null,revision=0,activeJob=null,latest=null,inputRevision=0,lastReportRevision=-1,dirty=false;
const name=id=>partyDisplay(id);
let partyMoveNames={},rosterEditors={};
let metaWeightRows=[],metaWeightValues={},metaWeightCache=new Map(),metaWeightTicket=0,metaWeightReady=false;
let pendingScopedWeights={},weightSaveTimer=null,weightSaving=null,pendingGuardAction=null;
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n}
function status(text){$('status').textContent=text}
function addLine(parent,text){parent.append(node('p',text))}
const pct=v=>(v*100).toFixed(1)+'%';
function label(id){const r=latest?.labels?.[id];return r?name(r.species)+' '+r.ivs.join('/')+' CP'+r.cp:id.slice(0,8)}
function tab(target){if(target==='strategy'){$('strategyResult').scrollIntoView({block:'start',behavior:'smooth'});}}
function markDirty(){
 dirty=true;
 $('partyMenuBtn').textContent='パーティ ●';
 $('partyState').textContent=(partyId?('編集中: '+$('partyName').value+'（未保存の変更あり / rev '+revision+'）'):'新規パーティ（未保存の変更あり）');
}
function clearDirty(stateText){
 dirty=false;
 $('partyMenuBtn').textContent='パーティ';
 if(stateText)$('partyState').textContent=stateText;
}
async function api(path,body={}){
 const h={'Content-Type':'application/json'};if(key)h.Authorization='Bearer '+key;
 const r=await fetch('/app-api/'+path,{method:'POST',headers:h,body:JSON.stringify(body),credentials:'same-origin'});
 const data=await r.json().catch(()=>({error:'サーバー応答を読み取れません'}));if(!r.ok)throw Error(data.error||'HTTP '+r.status);return data;
}
/*PARTY_INPUT*/
function renderMon(rows=[]){$('members').replaceChildren();for(let i=0;i<6;i++)$('members').append(createMon(rows[i]||{}))}
function getMonAll(){return [...$('members').children].map(readPartyCard)}
function getMon(){return getMonAll().filter(x=>x.species)}
function locks(){return [...$('members').children].flatMap((box,i)=>{const sp=box.querySelector('[data-field=species]');const lk=box.querySelector('[data-field=locked]');return sp?.dataset?.species&&lk?.checked?[i]:[]})}
function currentScopeKey(){const sc=$('scenario').value;return sc&&sc!=='current'?'scenario:'+sc:'meta:'+$('meta').value}
function currentScenarioObj(){const sc=$('scenario').value;return sc&&sc!=='current'?scenarioItems.find(x=>x.id===sc)||null:null}
function normalizeMetaId(value){const s=String(value||'').trim().toLowerCase();return s.endsWith('_shadow-shadow')?s.slice(0,-7):s}
function parseMetaWeightRows(csv){
 const unique=new Set(),rows=[];
 for(const line of String(csv||'').split(/\r?\n/)){
  if(!line.trim())continue;
  const id=normalizeMetaId(line.split(',')[0]);
  if(!id)continue;
  if(!catalog[id])throw Error('メタに未登録のポケモン: '+id);
  if(!unique.has(id)){unique.add(id);rows.push(id);}
 }
 if(!rows.length)throw Error('メタにポケモンが登録されていません');
 return rows;
}
function syncOpponentStrategyGate(){
 let enemies=[];try{enemies=partyRosterRows('enemy')}catch(_){}
 const ready=enemies.length===6;
 $('opponentStrategyPanel').hidden=!ready;
 if(ready){
  if(!$('strategyEnemy').value.trim()){$('strategyEnemy').value=$('enemy').value;rosterEditors.strategyEnemy?.refresh();}
  strategyTargets();
 }
}
function renderScenarioDropdown(selectedId='current'){
 const sel=$('scenario');sel.replaceChildren();
 sel.append(new Option('現行メタ（基準）','current'));
 for(const sc of scenarioItems){
  const tag=sc.builtin?'[標準予測] ':'[独自] ';
  sel.append(new Option(tag+sc.name,sc.id));
 }
 sel.value=[...sel.options].some(o=>o.value===selectedId)?selectedId:'current';
 renderCompareCheckboxes();
 updateScenarioEditorMeta();
}
function renderCompareCheckboxes(selectedIds=[]){
 const root=$('compareScenarios');
 const prev=new Set(selectedIds.length?selectedIds:[...root.querySelectorAll('input:checked')].map(x=>x.value));
 root.replaceChildren();
 const entries=[{id:'current',name:'現行メタ'},...scenarioItems.map(x=>({id:x.id,name:x.name}))];
 for(const item of entries){
  const l=node('label'),cb=node('input');cb.type='checkbox';cb.value=item.id;cb.checked=prev.has(item.id);
  cb.onchange=()=>{
   const checked=[...root.querySelectorAll('input:checked')];
   if(checked.length>4){cb.checked=false;status('比較シナリオは最大4件までです');return;}
   inputRevision++;
  };
  l.append(cb,document.createTextNode(' '+item.name));root.append(l);
 }
}
function getCompareScenarioIds(){return [...$('compareScenarios').querySelectorAll('input:checked')].map(x=>x.value)}
function updateScenarioEditorMeta(){
 const sc=currentScenarioObj();
 $('scenarioName').value=sc&&!sc.builtin?sc.name:'';
 $('scenarioSummary').value=sc?.summary||'';
 $('scenarioSave').disabled=!sc||sc.builtin;
 $('scenarioDelete').hidden=!sc||sc.builtin;
 renderScenarioEvidence(sc);
}
function renderScenarioEvidence(sc){
 const root=$('scenarioEvidence');root.replaceChildren();
 if(sc){
  root.append(node('strong','選択中の未来仮説: '+sc.name));
  if(sc.summary)addLine(root,sc.summary);
  if(sc.chain_steps?.length){
   const ol=node('ol');
   for(const st of sc.chain_steps){
    const li=node('li');
    li.append(node('strong','段階'+st.stage+' ['+(st.basis==='observed'?'観測':'仮説')+']: '+st.title+' — '),document.createTextNode(st.detail));
    ol.append(li);
   }
   root.append(ol);
  }
  if(sc.assumptions?.length){
   const ul=node('ul');
   sc.assumptions.forEach(a=>ul.append(node('li',a)));
   root.append(ul);
  }
 }else{
  root.append(node('strong','現行メタ（基準環境）'));
  addLine(root,'重複する「現行環境維持」シナリオは作らず、この基準メタと独立した未来シナリオを比較します。');
 }
 if(observations){
  const d=node('details');d.append(node('summary','実測データ（9/8–11/13・観測と仮説を分離）'));
  addLine(d,'左上日付を正本。集計期間が重複するため単純合算禁止。上位12圏外（—）は0%ではありません。採用率画像のみから共起は捏造しません。');
  const scroll=node('div',null,'obs-scroll'),table=node('table',null,'obs-table');
  const thead=node('thead'),hr=node('tr');
  hr.append(node('th','ポケモン'));
  for(const p of observations.periods)hr.append(node('th',p.label+' ('+p.teams+')'));
  thead.append(hr);table.append(thead);
  const tbody=node('tbody');
  for(const s of observations.series){
   const tr=node('tr');tr.append(node('td',s.label_ja));
   for(const r of s.rates)tr.append(node('td',r==null?'圏外':r+'%'));
   tbody.append(tr);
  }
  table.append(tbody);scroll.append(table);d.append(scroll);
  for(const u of observations.unconfirmed_observations||[]){
   addLine(d,'未確認の補助観測: '+u.label_ja+' — '+u.note);
  }
  root.append(d);
 }
}
function renderMetaWeightRows(){
 const root=$('metaWeights');root.replaceChildren();
 if(!metaWeightReady){$('metaWeightStatus').textContent='メタ一覧を確認できません。';return;}
 const sc=currentScenarioObj();
 const extraSpecies=Object.keys(sc?.weights||{}).filter(id=>!metaWeightRows.includes(id));
 const allIds=[...metaWeightRows,...extraSpecies];
 const query=normalizePartyName($('metaFilter').value);
 const filtered=allIds.filter(id=>!query||[id,catalog[id]?.name,catalog[id]?.name_ja,...(catalog[id]?.aliases||[])].some(x=>x&&normalizePartyName(x).includes(query)));
 $('metaWeightStatus').textContent='対象 '+allIds.length+'種 / 表示 '+filtered.length+'種（保存先: '+(sc?sc.name:'現行メタ')+' のみ独立保存）';
 if(!filtered.length){root.append(node('p','一致するポケモンはありません'));return;}
 for(const id of filtered){
  const div=node('div',null,'weight-row'),span=node('span');
  const ja=node('strong',partyDisplay(id));
  const sub=catalog[id]?.name||id;
  span.append(ja,node('small',sub+(id.startsWith('mimikyu')?' / ばけのかわ未検証(unknown)':'')));
  const select=node('select');select.dataset.species=id;select.setAttribute('aria-label',partyDisplay(id)+' の重要度');
  let options=[0,0.5,1,1.5,2,2.5,3,3.5,4,5,10,20],value=metaWeightValues[id]??1;
  if(!options.includes(value))options=[...options,value].sort((a,b)=>a-b);
  for(const n of options)select.append(new Option(n===0?'0（対象外）':n===1?'1（標準）':String(n)+'（重視）',String(n)));
  select.value=String(value);
  select.onchange=()=>{
   const v=Number(select.value);metaWeightValues[id]=v;pendingScopedWeights[id]=v;inputRevision++;
   $('metaWeightSaveStatus').textContent='このシナリオ専用の重要度を保存中…';
   clearTimeout(weightSaveTimer);weightSaveTimer=setTimeout(()=>flushScopedWeights().catch(()=>{}),200);
  };
  div.append(span,select);root.append(div);
 }
 updateGenSpeciesOptions();
}
function updateGenSpeciesOptions(){
 const select=$('genSpecies');if(!select)return;
 const cur=select.value;select.replaceChildren();
 for(const id of metaWeightRows){
  select.append(new Option(partyDisplay(id),id));
 }
 if(cur&&metaWeightRows.includes(cur))select.value=cur;
}
async function flushScopedWeights(){
 clearTimeout(weightSaveTimer);
 if(weightSaving){await weightSaving;return flushScopedWeights();}
 if(!Object.keys(pendingScopedWeights).length)return;
 const scopeKey=currentScopeKey();
 weightSaving=(async()=>{
  while(Object.keys(pendingScopedWeights).length){
   const changes=pendingScopedWeights;pendingScopedWeights={};
   try{
    await api('party/scoped-weights',{scope_key:scopeKey,changes});
    const sc=currentScenarioObj();
    if(sc)sc.weights={...(sc.weights||{}),...changes};
    $('metaWeightSaveStatus').textContent='保存済み（'+scopeKey+' のみに独立保存）';
   }catch(e){
    pendingScopedWeights={...changes,...pendingScopedWeights};
    $('metaWeightSaveStatus').textContent='重要度保存に失敗: '+e.message;
    throw e;
   }
  }
 })();
 try{await weightSaving}finally{weightSaving=null;}
}
async function loadMetaAndScenarioWeights(){
 const selected=metaItems.find(x=>x.id===$('meta').value),ticket=++metaWeightTicket;
 metaWeightReady=false;metaWeightRows=[];$('metaWeights').replaceChildren();
 $('metaWeightStatus').textContent='メタ一覧とシナリオ専用重要度を読み込み中…';
 if(!selected){$('metaWeightStatus').textContent='メタプリセットを選択してください';return;}
 const cacheKey=selected.id+'|'+selected.sha256;
 const scopeKey=currentScopeKey();
 try{
  let rows=metaWeightCache.get(cacheKey);
  const [exportData,scopedData]=await Promise.all([
   rows?Promise.resolve(null):api('meta-preset-export',{id:selected.id,expected_sha256:selected.sha256}),
   api('party/scoped-weights',{scope_key:scopeKey}),
  ]);
  if(exportData){rows=parseMetaWeightRows(exportData.csv);metaWeightCache.set(cacheKey,rows);}
  if(ticket!==metaWeightTicket)return;
  metaWeightRows=rows;
  const sc=currentScenarioObj();
  metaWeightValues={...(sc?.weights||{}),...(scopedData.weights||{})};
  metaWeightReady=true;
  renderMetaWeightRows();
  $('metaWeightSaveStatus').textContent='';
 }catch(e){
  if(ticket!==metaWeightTicket)return;
  $('metaWeightStatus').textContent='メタ一覧を取得できません: '+e.message;
 }
}
function getWeights(){
 if(!metaWeightReady)throw Error('メタの重要度一覧が準備できていません。メタ設定を確認してください');
 const result={};
 const sc=currentScenarioObj();
 const allIds=[...new Set([...metaWeightRows,...Object.keys(sc?.weights||{})])];
 for(const id of allIds){
  const v=metaWeightValues[id]??1;
  if(sc){result[id]=v;}else if(v!==1){result[id]=v;}
 }
 if(allIds.every(id=>(metaWeightValues[id]??1)===0))throw Error('重要度がすべて0です。少なくとも1体を対象にしてください');
 return result;
}
$('meta').addEventListener('change',async()=>{await flushScopedWeights().catch(()=>{});inputRevision++;await loadMetaAndScenarioWeights();});
$('scenario').addEventListener('change',async()=>{await flushScopedWeights().catch(()=>{});inputRevision++;updateScenarioEditorMeta();await loadMetaAndScenarioWeights();});
$('metaFilter').addEventListener('input',e=>{e.stopPropagation();renderMetaWeightRows()});

async function saveScenarioAction(asNew){
 try{
  await flushScopedWeights();
  const sc=currentScenarioObj();
  const nameVal=$('scenarioName').value.trim();
  if(!nameVal)throw Error('シナリオ名を入力してください');
  const selectedMeta=metaItems.find(x=>x.id===$('meta').value);
  const payload={
   id:asNew?null:(sc&&!sc.builtin?sc.id:null),
   revision:asNew?0:(sc&&!sc.builtin?sc.revision:0),
   name:nameVal,
   base_meta_id:$('meta').value,
   base_meta_sha256:selectedMeta?.sha256||'',
   summary:$('scenarioSummary').value.trim(),
   weights:getWeights(),
   chain_steps:sc?.chain_steps||[],
   assumptions:sc?.assumptions||['独自に調整した未来メタ予測シナリオ'],
  };
  const saved=await api('party/scenario-save',payload);
  const listed=await api('party/scenario-list');
  scenarioItems=listed.items||[];observations=listed.observations||observations;
  renderScenarioDropdown(saved.id);
  await loadMetaAndScenarioWeights();
  $('scenarioManageStatus').textContent='未来シナリオ「'+saved.name+'」を保存しました（rev '+saved.revision+'）';
 }catch(e){$('scenarioManageStatus').textContent=e.message;}
}
$('scenarioSave').onclick=()=>saveScenarioAction(false);
$('scenarioSaveAs').onclick=()=>saveScenarioAction(true);
$('scenarioDelete').onclick=async()=>{
 try{
  const sc=currentScenarioObj();if(!sc||sc.builtin)return;
  await api('party/scenario-delete',{id:sc.id,revision:sc.revision});
  const listed=await api('party/scenario-list');
  scenarioItems=listed.items||[];
  renderScenarioDropdown('current');
  await loadMetaAndScenarioWeights();
  $('scenarioManageStatus').textContent='シナリオを削除しました';
 }catch(e){$('scenarioManageStatus').textContent=e.message;}
};

function renderUnknownBanner(result){
 const root=$('unknownBanner');root.replaceChildren();
 const items=result.unverified_mechanics||[];
 if(!items.length)return;
 const box=node('div',null,'alert-box');
 box.append(node('strong','未検証メカニクス（unknown表示・勝敗未断定）'));
 for(const item of items){addLine(box,partyDisplay(item.species)+'：'+item.reason);}
 root.append(box);
}
function renderOverallSummary(result){
 const root=$('summaryResult');root.replaceChildren();
 const card=node('div',null,'result-card');
 const sc=result.scenario||{name:'現行メタ'};
 card.append(node('h3','総合評価（'+sc.name+'）'));
 const t=result.team;
 addLine(card,'未対応 D0 '+pct(t.d0)+' / 担当1体 D1 '+pct(t.d1)+' / 深刻度 '+t.severity0.toFixed(3)+' / 補完度 '+pct(t.coverage)+' / 未計算(unknown) '+pct(t.unknown_weight));
 addLine(card,'計算版: '+result.calculation_version+' / 評価版: '+result.evaluation_version+' / キャッシュ再利用 '+result.cache.hits+'・新規 '+result.cache.computed);
 if(result.scenario_comparison){
  const cmp=result.scenario_comparison;
  const box=node('div',null,'result');
  box.append(node('strong','複数シナリオ比較（'+cmp.count+'件・キャッシュ再利用）'));
  addLine(box,'平均: D0 '+pct(cmp.average.d0)+' / D1 '+pct(cmp.average.d1)+' / 補完度 '+pct(cmp.average.coverage)+' / unknown '+pct(cmp.average.unknown_weight));
  const wc=cmp.worst_case;
  const warn=node('p');
  warn.append(node('span','最悪ケース','badge danger'),document.createTextNode(' '+wc.scenario_name+' — D0 '+pct(wc.summary.d0)+' / 深刻度 '+wc.summary.severity0.toFixed(3)+' / unknown '+pct(wc.summary.unknown_weight)));
  box.append(warn);
  const ul=node('ul');
  for(const row of cmp.scenarios){
   ul.append(node('li',row.name+'：D0 '+pct(row.summary.d0)+' / D1 '+pct(row.summary.d1)+' / 補完度 '+pct(row.summary.coverage)+' / unknown '+pct(row.summary.unknown_weight)));
  }
  box.append(ul);card.append(box);
 }
 root.append(card);
}
function renderRecommendedThree(result){
 const root=$('recommendedThree');root.replaceChildren();
 const recs=result.recommended_three||[];
 const all=result.triples||[];
 if(!recs.length&&!all.length)return;
 const card=node('div',null,'result-card');
 card.append(node('h3','推奨3体選出と控えるべき選出（勝ち筋・負け筋の診断）'));

 const wrapper=node('div',null,'triples-carousel-wrapper');
 const nav=node('div',null,'carousel-tabs');
 const tabWin=node('button','🏆 推奨3体選出（勝ち筋 TOP3）','carousel-tab-btn active');
 const tabLoss=node('button','⚠️ 控えるべき選出（負け筋 ワースト3）','carousel-tab-btn');
 tabWin.type='button';tabLoss.type='button';
 nav.append(tabWin,tabLoss);
 wrapper.append(nav);

 const track=node('div',null,'carousel-track');
 const slideWin=node('div',null,'carousel-slide');
 const slideLoss=node('div',null,'carousel-slide');

 for(const item of recs){
  const box=node('div',null,'triple-card');
  const r=item.roles;
  box.append(node('strong','推奨'+item.rank+'：先発 '+label(r.lead)+' / 引き先 '+label(r.safe_switch)+' / 控え '+label(r.closer)));
  addLine(box,'D0 '+pct(item.summary.d0)+' / D1 '+pct(item.summary.d1)+' / 補完度 '+pct(item.summary.coverage)+(item.vs_enemy?' / 対相手6体 最悪比較値 '+item.vs_enemy.worst.toFixed(3):''));
  if(item.favorable?.length)addLine(box,'有利な場面: '+item.favorable.map(f=>name(result.labels[f.opponent]?.species||f.opponent)+'('+f.answers+'体対応)').join('、'));
  if(item.avoid_reasons?.length)addLine(box,'避ける場面・負け筋: '+item.avoid_reasons.map(x=>x.detail).join(' / '));
  slideWin.append(box);
 }

 const worstTriples=all.slice().reverse().slice(0,3);
 if(worstTriples.length){
  for(const item of worstTriples){
   const box=node('div',null,'triple-card unfavorable');
   const r=item.roles||{lead:item.members[0],safe_switch:item.members[1],closer:item.members[2]};
   const head=node('div');
   head.append(node('strong','ワースト#'+item.rank+' 先発 '+label(r.lead)+' / 引き先 '+label(r.safe_switch)+' / 控え '+label(r.closer)),document.createTextNode(' '),node('span','控えるべき3体','badge danger'));
   box.append(head);
   addLine(box,'D0 '+pct(item.summary.d0)+' / D1 '+pct(item.summary.d1)+' / 補完度 '+pct(item.summary.coverage)+' / unknown '+pct(item.summary.unknown_weight));
   if(item.avoid_reasons?.length)addLine(box,'控えるべき理由: '+item.avoid_reasons.map(x=>x.detail).join(' / '));
   slideLoss.append(box);
  }
 }else{
  addLine(slideLoss,'極端に不利な選出は見つかりませんでした。');
 }

 track.append(slideWin,slideLoss);
 wrapper.append(track);
 card.append(wrapper);

 tabWin.onclick=()=>{
  track.scrollTo({left:0,behavior:'smooth'});
  tabWin.className='carousel-tab-btn active';tabLoss.className='carousel-tab-btn';
 };
 tabLoss.onclick=()=>{
  track.scrollTo({left:track.scrollWidth/2,behavior:'smooth'});
  tabLoss.className='carousel-tab-btn active';tabWin.className='carousel-tab-btn';
 };
 track.onscroll=()=>{
  const isLoss=track.scrollLeft>track.clientWidth/3;
  tabLoss.className='carousel-tab-btn'+(isLoss?' active':'');
  tabWin.className='carousel-tab-btn'+(!isLoss?' active':'');
 };

 if(result.selection?.status==='計算済み'||(recs[0]&&recs[0].vs_enemy)){
  const d=node('details');d.style.marginTop='12px';d.open=true;
  d.append(node('summary','相手6体に対する詳細選出根拠（勝ち選出 vs 負け選出マトリクス）'));
  if(result.selection?.interpretation)addLine(d,result.selection.interpretation);
  for(const x of result.selection?.recommendations||[]){
   const mCard=node('div',null,'matrix-card');
   const enemyLabel=x.worst_opponent.map(label).join('・');
   mCard.append(node('strong','相手想定選出: '+enemyLabel));
   const cols=node('div',null,'matrix-cols');
   const winBox=node('div',null,'matrix-win-box');
   winBox.append(node('span','勝てる選出（推奨）','badge'));
   addLine(winBox,'先発 '+label(x.selection[0])+' / 控え '+label(x.selection[1])+'・'+label(x.selection[2])+'（最悪比較値 '+x.worst+'）');
   const lossBox=node('div',null,'matrix-loss-box');
   lossBox.append(node('span','危険な選出（回避）','badge danger'));
   const badOne=worstTriples[0];
   if(badOne){
    const br=badOne.roles||{lead:badOne.members[0],safe_switch:badOne.members[1],closer:badOne.members[2]};
    addLine(lossBox,'先発 '+label(br.lead)+' / 控え '+label(br.safe_switch)+'・'+label(br.closer)+'（穴が重なるため不利）');
   }else{
    addLine(lossBox,'極端に危険な選出はありません');
   }
   cols.append(winBox,lossBox);
   mCard.append(cols);
   d.append(mCard);
  }
  card.append(d);
 }
 root.append(card);
}
function renderAllTriples(result){
 const root=$('allTriplesPanel');root.replaceChildren();
 const all=result.triples||[];
 if(!all.length)return;
 const d=node('details');d.dataset.allTriples='true';
 d.append(node('summary','全'+all.length+'組の3体選出候補・不利選出の理由を見る'));
 for(const item of all){
  const box=node('div',null,'triple-card'+(item.unfavorable?' unfavorable':''));
  const r=item.roles||{lead:item.members[0],safe_switch:item.members[1],closer:item.members[2]};
  const head=node('div');
  head.append(node('strong','#'+item.rank+' 先発 '+label(r.lead)+' / 引き先 '+label(r.safe_switch)+' / 控え '+label(r.closer)));
  if(item.unfavorable)head.append(document.createTextNode(' '),node('span','不利注意','badge danger'));
  box.append(head);
  addLine(box,'D0 '+pct(item.summary.d0)+' / D1 '+pct(item.summary.d1)+' / 補完度 '+pct(item.summary.coverage)+' / unknown '+pct(item.summary.unknown_weight));
  if(item.avoid_reasons?.length)addLine(box,'理由・負け筋: '+item.avoid_reasons.map(x=>x.detail).join(' / '));
  d.append(box);
 }
 root.append(d);
}
function showCompletion(result){
 const opt=result.optimization,root=$('swapAdvice');root.replaceChildren();
 if(!opt)return;
 root.append(node('h3','自動補完の提案候補'));
 const srcLabel=opt.source==='registered'?'登録済み候補':opt.source==='mixed'?'登録候補＋メタ仮候補':opt.source==='all_locked'?'全枠固定（入れ替えなし）':'メタからの仮候補';
 addLine(root,srcLabel+'（候補 '+opt.candidate_count+'体・探索 '+opt.explored+'構成）。'+opt.scope);
 if(opt.provisional_ids?.length)addLine(root,'「仮候補」タグの個体は所持未確認です。実際に使う前に所持・技・IV・CPを確認してください。');
 if(!opt.finalists?.length){addLine(root,'到達可能な候補がありません。');return}
 const display=id=>name(result.labels[id]?.species||id);
 const comparison=node('dialog',null,'party-comparison');comparison.setAttribute('aria-label','パーティの相性比較');root.append(comparison);
 function heat(parent,index){
  parent.replaceChildren();
  const header=node('div',null,'compare-header'),close=node('button','比較を閉じる');
  header.append(node('h2','パーティの相性比較'),close);parent.append(header);
  const content=node('div',null,'compare-content');parent.append(content);
  const previousOverflow=document.body.style.overflow;
  close.onclick=()=>parent.close();
  parent.onclose=()=>{document.body.style.overflow=previousOverflow;};
  document.body.style.overflow='hidden';
  parent.showModal();
  const controls=node('div',null,'compare-controls');
  controls.addEventListener('input',e=>e.stopPropagation());
  function select(title,options,value){const l=node('label',title),x=node('select');
   x.setAttribute('aria-label',title);for(const [v,t] of options)x.append(new Option(t,String(v)));x.value=String(value);l.append(x);controls.append(l);return x;}
  const candidate=select('比較する提案',opt.finalists.map((p,i)=>[i,'候補 '+String.fromCharCode(65+i)]),index);
  const own=select('自分のシールド',[[0,'0枚'],[1,'1枚'],[2,'2枚']],2);
  const enemy=select('相手のシールド',[[0,'0枚'],[1,'1枚'],[2,'2枚']],2);
  const mode=select('比較表示',[['slots','ポケモン別の相性'],['summary','全体の対応力']],'slots');
  content.append(controls);
  const summary=node('p'),opponent=node('h3',null,'compare-opponent'),outer=node('div',null,'compare-scroll'),paging=node('div',null,'tools compare-paging');
  const previous=node('button','前へ'),next=node('button','次へ'),info=node('span');
  paging.append(previous,info,next);content.append(opponent,paging,outer,summary);let page=0;
  const symbol=v=>v==null?'?':v>=550?'○':v<=450?'×':'△';
  const tone=v=>v==null?'heat-unknown':v>=550?'heat-win':v<=450?'heat-loss':'heat-mid';
  function stats(row){const r=row?.ratings||[];return r.length!==6||r.some(x=>x==null)?{best:null,answers:null}:{best:Math.max(...r),answers:r.filter(x=>x>500).length};}
  function draw(){
   const plan=opt.finalists[Number(candidate.value)],k=own.value+'-'+enemy.value;
   const before=opt.baseline_by_shield?.[k]||(k==='2-2'?opt.baseline_heatmap:[])||[];
   const after=plan.by_shield?.[k]||(k==='2-2'?plan.heatmap:[])||[];
   const afterMap=new Map(after.map(r=>[r.opponent,r]));
   const rows=before.map(r=>({before:r,after:afterMap.get(r.opponent)}));
   let gained=0,lost=0,unknown=0;
   for(const r of rows){const a=stats(r.before),b=stats(r.after);if(a.best==null||b.best==null)unknown++;else{if(a.best<=500&&b.best>500)gained++;if(a.best>500&&b.best<=500)lost++;}}
   summary.textContent='表示対象 '+rows.length+'相手 / 新たに対応 '+gained+' / 対応を失う '+lost+' / 未計算(unknown) '+unknown;
   const table=node('table',null,'heatmap compare-heatmap'),thead=node('thead'),head=node('tr');
   table.dataset.shields=k;table.dataset.mode=mode.value;
   const slots=mode.value==='slots',size=slots?1:8;
   page=Math.max(0,Math.min(page,Math.ceil(rows.length/size)-1));
   if(slots)head.append(node('th','基準の6体'),node('th','提案後'));
   else head.append(node('th','相手'),node('th','基準の6体'),node('th','提案後'));
   thead.append(head);table.append(thead);const body=node('tbody');
   opponent.textContent=slots&&rows[page]?'対 '+display(rows[page].before.opponent):'全体の対応力';
   for(const r of rows.slice(page*size,page*size+size)){
    if(!slots){
     const tr=node('tr');tr.append(node('th',display(r.before.opponent)));
     for(const row of [r.before,r.after]){const v=stats(row),td=node('td');td.className=tone(v.best);
      td.append(node('span',v.best==null?'?':symbol(v.best)+' '+v.best),node('small',v.answers==null?'未計算':'勝てる担当 '+v.answers+'体'));tr.append(td);}
     body.append(tr);
    }else for(let i=0;i<6;i++){
     const tr=node('tr');
     for(const [roster,row] of [[opt.baseline_roster||result.roster,r.before],[plan.roster,r.after]]){
      const v=row?.ratings?.[i]??null,td=node('td');td.className=tone(v);
      td.append(node('strong',display(roster[i])),node('span',symbol(v)+' '+(v??'?')));tr.append(td);
     }
     body.append(tr);
    }
   }
   table.append(body);outer.replaceChildren(table);
   info.textContent=rows.length?(page*size+1)+'–'+Math.min(rows.length,page*size+size)+' / '+rows.length:'比較データなし';
   previous.textContent=slots?'前の相手':'前へ';next.textContent=slots?'次の相手':'次へ';
   previous.disabled=page===0;next.disabled=(page+1)*size>=rows.length;
  }
  for(const x of [candidate,own,enemy])x.onchange=()=>draw();
  mode.onchange=()=>{page=0;draw();};
  previous.onclick=()=>{page--;draw();};next.onclick=()=>{page++;draw();};draw();
 }
 for(const [i,plan] of opt.finalists.entries()){
  const box=node('div',null,'completion-card');
  box.append(node('h3','候補 '+String.fromCharCode(65+i)+(i===0?'（評価上位）':'')));
  const rosterLine=node('div');
  for(const mid of plan.roster){
   const info=result.labels[mid];
   const b=node('span',display(mid)+(info?.provisional?'（仮候補）':''),'badge'+(info?.provisional?' warn':''));
   rosterLine.append(b);
  }
  box.append(rosterLine);
  addLine(box,'D0 未対応 '+pct(plan.summary.d0)+' / D1 '+pct(plan.summary.d1)+' / 補完度 '+pct(plan.summary.coverage)+' / 変更枠 '+(plan.replaced_count??plan.steps?.length??0)+'体');
  const tools=node('div',null,'tools'),view=node('button','弱点を視覚化'),apply=node('button','この6体を反映');
  view.type='button';apply.type='button';
  tools.append(view,apply);box.append(tools);
  view.onclick=()=>heat(comparison,i);
  apply.onclick=()=>applyCompletedParty(result,plan);
  root.append(box);
 }
}
function applyCompletedParty(result,plan){
 if(activeJob||latest!==result||lastReportRevision!==inputRevision){status('入力が変わったため反映できません。再計算してください。');return;}
 const lockedIds=new Set(result.autocomplete?.locked||[]);
 const next=plan.roster.map(id=>{
  const p=result.labels[id];if(!p)throw Error('提案のデータが見つかりません');
  return {species:p.species,fast:p.moves[0],charged1:p.moves[1],charged2:p.moves[2],atk:p.ivs[0],def:p.ivs[1],hp:p.ivs[2],level_override:p.level,locked:lockedIds.has(id)};
 });
 renderMon(next);
 markDirty();inputRevision++;lastReportRevision=-1;latest=null;strategyTargets();
 $('swapAdvice').replaceChildren(node('p','提案の6体を反映しました。保存する場合は右上の「パーティ」から保存してください。'));
 status('6体を反映しました（未保存）。必要なら再評価・保存してください。');
 $('members').scrollIntoView({block:'start',behavior:'smooth'});
}
function showRefinement(result,root){
 const detail=result.refinement;if(!detail)return;
 const d=node('details');d.append(node('summary','詳細戦略の比較結果（任意オプション）'));
 addLine(d,detail.scope);
 addLine(d,'評価対象: '+detail.targets.map(label).join(' / '));
 for(const p of detail.finalists){
  addLine(d,'詳細比較 '+p.rank+'位（一次 '+p.static_rank+'位）: '+p.roster.map(label).join(' / ')+' / 役割指標 '+(p.detail.score==null?'未評価含む':p.detail.score.toFixed(3)));
 }
 root.append(d);
}
function showUncertainty(result,root){
 const r=result.uncertainty;if(!r)return;
 const d=node('details');d.dataset.uncertainty='true';d.append(node('summary','技・IV感度の比較結果（任意オプション）'));
 addLine(d,'最大'+r.budget.max_groups+'グループ・各'+r.budget.max_movesets+'技構成の標本内評価。勝率ではありません。');
 for(const plan of r.finalists){
  addLine(d,'最終推薦 '+plan.uncertainty_rank+'位: '+plan.roster.map(label).join(' / '));
 }
 root.append(d);
}
function show(result){
 latest=result;lastReportRevision=inputRevision;
 renderUnknownBanner(result);
 renderOverallSummary(result);
 showCompletion(result);
 renderRecommendedThree(result);
 const root=$('weakResult');root.replaceChildren();
 const weakCard=node('div',null,'result-card');
 weakCard.append(node('h3','主要弱点・危険ペア'));
 const t=result.team;
 if(t.critical?.length){
  const u=node('ul');
  t.critical.slice(0,8).forEach(x=>u.append(node('li',label(x.opponent)+'（最良Rating '+x.best_rating+'）')));
  weakCard.append(u);
 }else addLine(weakCard,'静的2-2基準での未対応相手はありません（unknownを除く）。');
 if(result.danger_pairs?.length){
  const th=node('details');th.append(node('summary','相手の危険な2体ペア（上位'+Math.min(6,result.danger_pairs.length)+'件）'));
  const ul=node('ul');
  result.danger_pairs.slice(0,6).forEach(x=>ul.append(node('li',x.opponents.map(label).join(' + ')+' / 担当集中 '+x.assignment_deficit+' / 釣り出し警告 '+x.trap_risk)));
  th.append(ul);weakCard.append(th);
 }
 const details=node('details');details.append(node('summary','シールド条件別・全15ペア補完の詳細'));
 const cases=node('ul');Object.entries(result.scenarios||{}).forEach(([k,v])=>cases.append(node('li',k+' : D0 '+pct(v.d0)+' / D1 '+pct(v.d1))));
 details.append(node('strong','シールド条件別'),cases);
 const pairs=node('ul');
 (result.pairs||[]).forEach(x=>pairs.append(node('li',x.members.map(label).join(' + ')+' / 補完度 '+x.balance.toFixed(3)+' / 穴 '+pct(x.hole))));
 details.append(node('strong','全15ペア補完'),pairs);
 weakCard.append(details);
 showUncertainty(result,weakCard);
 showRefinement(result,weakCard);
 root.append(weakCard);
 renderAllTriples(result);
 $('resultsSection').scrollIntoView({block:'start',behavior:'smooth'});
}
function partyCalculationRequest(mode){
 const scId=$('scenario').value;
 const enemies=partyRosterRows('enemy');
 const effectiveMode=(mode==='evaluate'?(enemies.length===6?'select':'analyze'):mode);
 const request={
  mode:effectiveMode,
  members:effectiveMode==='autocomplete'?getMonAll():getMon(),
  locked_slots:locks(),
  meta_preset_id:$('meta').value,
  meta_sha256:metaItems.find(x=>x.id===$('meta').value)?.sha256,
  scenario_id:scId==='current'?null:scId,
  compare_scenario_ids:getCompareScenarioIds(),
  group_weights:effectiveMode==='strategy'?{}:getWeights(),
  ruleset:'cp1500-lv50',
  strategy_refinement:$('strategyRefinement').checked,
 };
 if(effectiveMode==='autocomplete')request.candidate_pool=partyRosterRows('pool');
 if(enemies.length===6&&effectiveMode!=='strategy')request.opponents=enemies;
 if(effectiveMode==='strategy'){request.opponents=partyRosterRows('strategyEnemy');request.strategy=getStrategy();}
 if(effectiveMode!=='strategy'){
  request.opponent_uncertainty=$('opponentUncertainty').checked;
  if(request.opponent_uncertainty)request.opponent_hypotheses=partyRosterRows('hypotheses');
 }
 return request;
}
async function run(mode){
 if(activeJob)return;
 await flushScopedWeights();
 const request=partyCalculationRequest(mode),submitted=JSON.stringify(request);
 function inputsStillMatch(){try{return submitted===JSON.stringify(partyCalculationRequest(mode))}catch(_){return false}}
 const r=await api('party/start',request);
 activeJob=r.job_id;
 $('cancel').hidden=false;$('cancel').disabled=false;
 $('autoComplete').disabled=true;$('evaluate').disabled=true;
 status('計算中...');
 for(;;){
  await new Promise(resolve=>setTimeout(resolve,1200));
  const s=await api('party/status',{job_id:activeJob});
  if(s.status==='done'){
   if(!inputsStillMatch()){status('計算中に入力が変更されました。以前の入力の結果は表示しません。再計算してください。');}
   else{
    if(s.result.kind==='strategy')showStrategy(s.result);else show(s.result);
    status('計算完了。静的評価であり実戦3対3勝率ではありません。');
   }
   break;
  }
  if(s.status==='error'||s.status==='cancelled'){status(s.message||s.status);break;}
  status('計算中 '+(s.progress||0)+'% / '+(s.message||''));
 }
 activeJob=null;$('cancel').disabled=true;$('cancel').hidden=true;
 $('autoComplete').disabled=false;$('evaluate').disabled=false;
}
async function wrap(mode){
 try{await run(mode)}catch(e){
  status(e.message);activeJob=null;$('cancel').disabled=true;$('cancel').hidden=true;
  $('autoComplete').disabled=false;$('evaluate').disabled=false;
 }
}
$('autoComplete').onclick=()=>wrap('autocomplete');
$('evaluate').onclick=()=>wrap('evaluate');
$('cancel').onclick=()=>activeJob&&api('party/cancel',{job_id:activeJob}).then(()=>status('中止要求を送信しました'));

function populateSaved(items,selected=partyId){
 $('saved').replaceChildren(new Option('読み込むパーティを選ぶ',''));
 items.forEach(x=>$('saved').append(new Option(x.name,x.id)));
 $('saved').value=selected||'';
}
$('partyMenuBtn').onclick=()=>{$('unsavedGuard').hidden=true;$('partyDialog').showModal()};
$('closePartyDialog').onclick=()=>{$('unsavedGuard').hidden=true;$('partyDialog').close()};

function guardUnsaved(message,action){
 if(!dirty){action();return;}
 pendingGuardAction=action;
 $('unsavedGuardMsg').textContent=message;
 $('unsavedGuard').hidden=false;
}
$('confirmDiscard').onclick=()=>{const fn=pendingGuardAction;pendingGuardAction=null;$('unsavedGuard').hidden=true;if(fn)fn();};
$('cancelDiscard').onclick=()=>{pendingGuardAction=null;$('unsavedGuard').hidden=true;};

async function saveParty(asNew=false){
 try{
  await flushScopedWeights();
  const scId=$('scenario').value;
  const obj={
   id:asNew?null:partyId,revision:asNew?0:revision,name:$('partyName').value,
   members:getMonAll(),locked_slots:locks(),
   meta_preset_id:$('meta').value,meta_sha256:metaItems.find(x=>x.id===$('meta').value)?.sha256,
   scenario_id:scId==='current'?null:scId,compare_scenario_ids:getCompareScenarioIds(),
   group_weights:getWeights(),
   strategy:{...getStrategy(),enemy_csv:$('strategyEnemy').value},
   strategy_refinement:$('strategyRefinement').checked,
   opponents:partyRosterRows('enemy'),candidate_pool:partyRosterRows('pool'),
   opponent_uncertainty:$('opponentUncertainty').checked,
   opponent_hypotheses:partyRosterRows('hypotheses'),
  };
  const r=await api('party/save',obj);partyId=r.id;revision=r.revision;
  clearDirty('保存中: '+r.name+'（rev '+revision+'）');
  status('保存済み: '+r.name+'（rev '+revision+'）');
  populateSaved((await api('party/list')).items,partyId);
 }catch(e){status(e.message);$('partyState').textContent='保存エラー: '+e.message;}
}
$('save').onclick=()=>saveParty(false);
$('saveAs').onclick=()=>saveParty(true);
$('renameParty').onclick=async()=>{
 try{
  if(!partyId)throw Error('先に保存してから名前変更してください');
  const r=await api('party/rename',{id:partyId,name:$('partyName').value,revision});
  revision=r.revision;
  clearDirty('保存中: '+r.name+'（rev '+revision+'）');
  populateSaved((await api('party/list')).items,partyId);
  status('パーティ名を「'+r.name+'」に変更しました');
 }catch(e){status(e.message);$('partyState').textContent='名前変更エラー: '+e.message;}
};
$('newParty').onclick=()=>guardUnsaved('未保存の変更があります。保存せずに新規パーティを作成しますか？',()=>{
 partyId=null;revision=0;$('partyName').value='新しいパーティ';
 renderMon([]);$('enemy').value='';$('pool').value='';$('hypotheses').value='';
 rosterEditors.enemy.refresh([]);rosterEditors.pool.refresh([]);rosterEditors.hypotheses.refresh([]);
 $('strategyRefinement').checked=false;$('opponentUncertainty').checked=false;
 syncOpponentStrategyGate();
 latest=null;lastReportRevision=-1;$('unknownBanner').replaceChildren();$('summaryResult').replaceChildren();
 $('swapAdvice').replaceChildren();$('recommendedThree').replaceChildren();$('weakResult').replaceChildren();$('allTriplesPanel').replaceChildren();$('strategyResult').replaceChildren();
 clearDirty('新規パーティ（未保存）');inputRevision++;$('partyDialog').close();
 status('新規パーティを作成しました');
});
async function doLoadParty(){
 try{
  const id=$('saved').value;if(!id)throw Error('読み込むパーティを選んでください');
  const p=await api('party/get',{id});
  partyId=p.id;revision=p.revision;$('partyName').value=p.name;
  const rows=p.members||[];
  renderMon(rows.map((m,i)=>({...m,locked:Boolean(m.species&&(p.locked_slots||[]).includes(i))})));
  if(metaItems.some(x=>x.id===p.meta_preset_id))$('meta').value=p.meta_preset_id;
  renderScenarioDropdown(p.scenario_id||'current');
  renderCompareCheckboxes(p.compare_scenario_ids||[]);
  await loadMetaAndScenarioWeights();
  const csv=list=>(list||[]).map(x=>[x.species,x.fast,x.charged1,x.charged2,...(['atk','def','hp'].every(k=>k in x)?[x.atk,x.def,x.hp]:[])].join(',')).join('\n');
  $('enemy').value=csv(p.opponents);$('pool').value=csv(p.candidate_pool);
  rosterEditors.enemy.refresh(p.opponents||[]);rosterEditors.pool.refresh(p.candidate_pool||[]);
  restoreStrategy(p.strategy,csv(p.opponents));
  $('strategyRefinement').checked=p.strategy_refinement===true;
  $('opponentUncertainty').checked=p.opponent_uncertainty===true;
  $('hypotheses').value=csv(p.opponent_hypotheses);rosterEditors.hypotheses.refresh(p.opponent_hypotheses||[]);
  syncOpponentStrategyGate();
  latest=null;lastReportRevision=-1;$('unknownBanner').replaceChildren();$('summaryResult').replaceChildren();
  $('swapAdvice').replaceChildren();$('recommendedThree').replaceChildren();$('weakResult').replaceChildren();$('allTriplesPanel').replaceChildren();$('strategyResult').replaceChildren();
  clearDirty('保存中: '+p.name+'（rev '+revision+'）');inputRevision++;$('partyDialog').close();
  status('「'+p.name+'」を読み込みました');
 }catch(e){status(e.message);$('partyState').textContent='読込エラー: '+e.message;}
}
$('load').onclick=()=>guardUnsaved('未保存の変更があります。保存せずにパーティを切り替えますか？',doLoadParty);

async function setup(){
 const [cat,presets,saved,scList]=await Promise.all([api('catalog'),api('meta-presets'),api('party/list'),api('party/scenario-list')]);
 if(!cat.ready)throw Error('ゲームデータがまだ準備中です');
 catalog=cat.species;partyMoveNames=cat.moves||{};metaItems=presets.items;
 scenarioItems=scList.items||[];observations=scList.observations||null;
 $('meta').replaceChildren();
 for(const m of metaItems.filter(x=>x.available!==false)){$('meta').append(new Option(m.name+' ('+m.rows+'件)',m.id));}
 $('meta').value=presets.default_id;
 renderScenarioDropdown('current');
 populateSaved(saved.items);renderMon();
 await loadMetaAndScenarioWeights();
 if(!rosterEditors.enemy){
  rosterEditors.enemy=partyRosterEditor('enemy',6);
  rosterEditors.pool=partyRosterEditor('pool',48);
  rosterEditors.strategyEnemy=partyRosterEditor('strategyEnemy',6);
  rosterEditors.hypotheses=partyRosterEditor('hypotheses',8);
 }
 syncOpponentStrategyGate();
 $('workspace').hidden=false;$('auth').hidden=true;$('partyMenuBtn').hidden=false;
 $('autoComplete').disabled=false;$('evaluate').disabled=false;
 status('準備完了。0体から「自動補完」、または6体入力後に「パーティ評価」を実行できます。');
}
$('generateScenarioBtn').onclick=()=>{
 const targetId=$('genSpecies').value;if(!targetId)return;
 const trend=$('genTrend').value;
 const targetName=partyDisplay(targetId);
 const scenarioName=(trend==='rise'?'予測：'+targetName+'台頭':trend==='counters'?'予測：'+targetName+'対策強化':'予測：'+targetName+'減少');
 $('scenarioName').value=scenarioName;
 $('scenarioSummary').value='選択中のメタを基点に'+targetName+'の'+(trend==='rise'?'普及と対抗枠台頭':trend==='counters'?'対策枠増加':'減少')+'をシミュレート';
 const baseWeights={};
 for(const id of metaWeightRows)baseWeights[id]=1.0;
 if(trend==='rise'){
  baseWeights[targetId]=5.0;
  const others=metaWeightRows.filter(x=>x!==targetId).slice(0,4);
  others.forEach(id=>{baseWeights[id]=3.0;});
 }else if(trend==='counters'){
  baseWeights[targetId]=2.5;
  const others=metaWeightRows.filter(x=>x!==targetId).slice(0,5);
  others.forEach(id=>{baseWeights[id]=4.5;});
 }else if(trend==='decline'){
  baseWeights[targetId]=0.5;
  const others=metaWeightRows.filter(x=>x!==targetId).slice(0,4);
  others.forEach(id=>{baseWeights[id]=2.5;});
 }
 metaWeightValues=baseWeights;
 renderMetaWeightRows();
 $('scenarioManageStatus').textContent='「'+scenarioName+'」の重みを自動設定しました。「新しい未来シナリオとして保存」を押すと保存されます。';
};
const INFO_TEXTS={
 main:'【見せ合い6体・未来メタ補完】\n見せ合い6体の登録・自動補完・パーティ評価を行います。全20組の3体選出診断（推奨・回避理由）や未来シナリオの比較を同一の対面キャッシュで高速に計算します。\n※Battle Ratingは静的耐性診断であり実戦3v3勝率そのものではありません。',
 roster:'【自分の6体】\nカードをタップすると技や個体値（IV）を設定するモーダルが開きます。背景タップで素早く閉じられます。\n右上の「固定」を押すと、そのポケモンの技やIVを維持したまま残りの枠を「自動補完」できます。0体・一部・6体どれからでも実行可能です。',
 meta:'【メタ・未来メタ選択】\n基準メタ（現行環境）に対し、特定のポケモンが増加・対策された未来環境（シナリオ）を個別に設定・比較できます。重みの変更は選択中のシナリオにのみ保存され、他には波及しません。',
};
document.querySelectorAll('.info-btn').forEach(btn=>{
 btn.onclick=()=>{
  const k=btn.dataset.info||'main';
  $('infoTitle').textContent=btn.parentElement?.textContent?.replace('ⓘ','').trim()||'説明';
  $('infoBody').textContent=INFO_TEXTS[k]||INFO_TEXTS.main;
  $('infoDialog').showModal();
 };
});
$('closeInfoDialog').onclick=()=>$('infoDialog').close();
$('infoDialog').onclick=e=>{if(e.target===$('infoDialog'))$('infoDialog').close();};
$('login').onclick=async()=>{key=$('key').value.trim();try{await setup();if(key)await api('session',{}).catch(()=>{})}catch(e){$('workspace').hidden=false;status(e.message)}};
$('workspace').addEventListener('input',e=>{
 if(e.target.closest('#scenarioEditorDetails'))return;
 inputRevision++;markDirty();
 const root=$('strategyResult');
 if(root.dataset.calculated&&!root.querySelector('[data-stale]')){const msg=node('p','入力が変更されています。以下は以前の条件の結果です。再計算してください。');msg.dataset.stale='true';root.prepend(msg)}
});
setup().catch(()=>{status('ログインが必要です。接続キーを入力してください。')});
/*STRATEGY_UI*/
</script></body></html>'''


from pathlib import Path
HTML = HTML.replace('/*STRATEGY_UI*/', Path(__file__).with_name('pvpoke_party_strategy_ui.js').read_text(encoding='utf-8'))
HTML = HTML.replace('/*PARTY_INPUT*/', Path(__file__).with_name('pvpoke_party_input.js').read_text(encoding='utf-8'))
