"""Browser-only entry point. Root credentials are never persisted in the browser.
An optional HttpOnly app-only cookie supports remembered browser sessions.
"""
HTML = r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>個体値厳選</title><style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#e8eef9;background:#101723;color-scheme:dark}*{box-sizing:border-box}body{margin:0}html{scroll-behavior:smooth;scroll-padding-top:16px}
.quick-nav{position:fixed;right:12px;top:44vh;z-index:30;display:flex;flex-direction:column;gap:6px;align-items:center}
.quick-nav a{display:flex;align-items:center;justify-content:center;min-height:48px;min-width:54px;padding:8px 7px;border:1px solid #76b1dc;border-radius:12px;background:#1d4768;color:#fff;font-size:12px;font-weight:650;text-decoration:none;box-shadow:0 4px 14px #0008}
.quick-nav a:focus-visible{outline:3px solid #90ddbc;outline-offset:3px}
@media(max-width:560px){.quick-nav{right:6px;top:58vh;bottom:auto}.quick-nav a{min-height:48px;min-width:48px;padding:9px 5px;font-size:11px}}
main{max-width:820px;margin:auto;padding:28px 16px 64px}h1{font-size:30px;margin:4px 0 8px}h2{font-size:20px;margin:0 0 12px}p{line-height:1.65;color:#afc0d6}.eyebrow{color:#90ddbc;font-size:12px;letter-spacing:.15em}.card{background:#1a2637;border:1px solid #33465d;border-radius:16px;padding:20px;margin-top:18px}label{display:block;font-size:14px;margin:14px 0 6px}input,select,textarea,button{font:inherit;border-radius:9px}input,select,textarea{width:100%;padding:12px;border:1px solid #49627d;background:#101c2b;color:#ecf3ff}input[type=checkbox]{width:auto;margin:0 8px 0 0;accent-color:#90ddbc}.checkline{display:flex;align-items:center;gap:3px;cursor:pointer}textarea{min-height:142px;line-height:1.7}button{padding:12px 18px;border:1px solid #76b1dc;background:#266b9b;color:white;cursor:pointer}button:disabled{opacity:.5;cursor:wait}.row{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}.secondary{background:transparent;border-color:#597086}.note{font-size:13px}.status{background:#21374a;border-radius:10px;padding:14px;white-space:pre-wrap;line-height:1.7}.error{background:#5a303a}.badge{color:#96e8c4;font-size:13px}.recommendation{border-top:1px solid #3c5068;padding-top:18px;margin-top:18px}.search{display:block;background:#0d1726;padding:12px;border-radius:8px;overflow-wrap:anywhere;font-size:14px;color:#b1e5ff}summary{cursor:pointer;color:#a4cdff}details{margin-top:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;font-size:12px}[hidden]{display:none!important}@media(max-width:560px){.row{grid-template-columns:1fr}.card{padding:16px}main{padding-top:22px}.actions button{flex:1}}
.low-score-list{display:grid;gap:12px;margin-top:14px}.low-score-item{padding:12px;border-radius:16px;background:#202f3d;border:1px solid #41594f}.low-score-item code{white-space:pre-wrap;overflow-wrap:anywhere;color:#d1ebd8;display:block;margin:8px 0}.low-score-item button{border-radius:999px;background:#536e61;border-color:#749783}.low-score-tools{display:grid;grid-template-columns:2fr 1fr;gap:10px}@media(max-width:560px){.low-score-tools{grid-template-columns:1fr}}

.meta-presets{margin-bottom:18px}.meta-current{display:flex;align-items:center;flex-wrap:wrap;gap:6px 9px;padding:0 0 10px}.meta-caption{font-size:12px;color:#afc0d6}.meta-current-name{font-size:16px;font-weight:650;line-height:1.5;margin:0;color:#ecf3ff;overflow-wrap:anywhere}.meta-count{font-size:12px;color:#afc0d6;white-space:nowrap}.meta-badges{display:inline-flex;align-items:center;flex-wrap:wrap;gap:5px}.meta-tag{display:inline-flex;align-items:center;font-size:11px;font-weight:600;line-height:1.5;padding:2px 7px;border-radius:999px;background:#263d3a;color:#b9e6cf;white-space:nowrap}.meta-star{color:#e8cc85;background:#3c372b}
.meta-toolbar,.meta-quick,.meta-settings{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.meta-toolbar button,.meta-settings button{flex:0 1 auto;min-height:44px;padding:9px 12px;font-size:13px;border-radius:12px;max-width:100%}.meta-toolbar{margin-bottom:8px}.meta-settings{margin-top:12px}.meta-settings button[aria-pressed=true],.meta-settings .is-set{border-color:#83bba5;background:#233d35;color:#caeedb}.meta-presets button:focus-visible{outline:3px solid #b9e6cf;outline-offset:3px}.meta-presets button:not(:disabled):active{filter:brightness(1.18)}
.meta-chooser{margin-top:10px;padding:14px;border:1px solid #41586b;border-radius:16px;background:#142130}.meta-hint{font-size:12px;line-height:1.5;margin:0 0 9px;color:#afc0d6}.meta-quick{align-items:flex-start}.meta-chip{display:inline-flex;align-items:center;justify-content:flex-start;gap:7px;flex:0 1 auto;max-width:100%;min-height:44px;padding:9px 11px;border:1px solid #526979;border-radius:13px;background:#1b2d3d;color:#e8eef9;text-align:left;font-size:13px;line-height:1.5}.meta-chip[aria-pressed=true]{border-color:#91cbb0;background:#29483c;color:#e4f8eb}.meta-chip-mark{flex:none;width:15px;color:#b1c5d4;text-align:center}.meta-chip[aria-pressed=true] .meta-chip-mark{color:#c5f2d8}.meta-chip-name{min-width:0;overflow-wrap:anywhere}.meta-chip .meta-tag{font-size:10px;padding:1px 6px;flex:none}.meta-all-row{display:flex;align-items:center;gap:8px}.meta-all-row select{min-width:0;flex:1;font-size:13px}.meta-all-row button{flex:none;width:44px;min-height:44px;padding:8px;border-radius:12px;font-size:21px}.meta-help{margin:8px 0;font-size:12px}.meta-help summary{color:#afc0d6}.meta-presets .note:empty{display:none}.meta-presets .note{line-height:1.6}
</style></head><body><nav class="quick-nav" aria-label="ページ内の移動"><a href="#pageTop" aria-label="ページ上部に戻る">↑<br>上へ</a></nav><main id="pageTop">
<header><div class="eyebrow">PVP IV SELECTION</div><h1>役割から選ぶ、個体値厳選</h1><p>対戦計算からおすすめ・理由・検索式まで。アプリの自動推薦と、これまでのGPT評価を使い分けられます。</p></header>
<section class="card" id="login"><h2>アプリに接続</h2><p class="note">初回だけ接続キー、または有効なアクセストークンを入力してください。APIキー自体は端末へ保存しません。</p><label for="credential">接続キー</label><input id="credential" type="password" autocomplete="off"><label class="checkline" for="remember"><input id="remember" type="checkbox" checked>このブラウザのログインを30日間維持する</label><p class="note">共有端末ではチェックを外してください。ログアウトでこのブラウザの保存情報を削除できます。</p><div class="actions"><button id="connect">接続する</button></div></section>
<div id="message" class="status" role="status" aria-live="polite" hidden></div>
<div id="workspace" hidden>
<section class="card" id="lowScorePanel" hidden>
<h2>非厳選判定の内訳（診断）</h2>
<p class="note">読み取りアプリの「⋯ → 非厳選を取得・コピー」から直接検索式を生成・コピーします。この画面は除外理由の確認専用で、検索式の手動転送は不要です。候補は博士送りの保証ではありません。</p>
<div class="low-score-tools"><div><label for="lowMode">判定基準</label><select id="lowMode"><option value="practical">推奨：総合＋実戦5役割すべて70未満</option><option value="overall">総合スコアだけ70未満</option><option value="battle">総合＋先発・終盤・交代すべて70未満</option><option value="strict">全7項目すべて70未満</option></select></div>
<div><label for="lowThreshold">スコア未満</label><input id="lowThreshold" type="number" value="70" min="1" max="100" step="0.1"></div></div>
<label class="checkline" for="lowExcludeFavorites"><input id="lowExcludeFavorites" type="checkbox">診断用：お気に入り除外（任意）</label>
<div class="actions"><button id="lowSearchRun">判定理由を確認</button></div>
<p class="note">Pokémon GOの「Show Evolutionary Line」はOFF推奨。ランキング未掲載の個体は低スコアと断定できません。進化先が低スコアでも、元の個体が未評価なら別の要確認候補です。</p>
<p id="lowScoreSummary" class="note" aria-live="polite">データの判定内容を確認できます。</p>
<p id="lowExclusionSummary" class="note"></p>
<details id="lowEvolutionProtected" hidden><summary>進化先を考慮して保護した個体</summary><div id="lowEvolutionNames" class="note" style="white-space:pre-wrap"></div></details>
<details id="lowManual" hidden><summary>姿・検索名などで安全に検索できない個体</summary><div id="lowManualNames" class="note" style="white-space:pre-wrap"></div></details>
<details id="lowUnrankedReview" hidden><summary>ランキング未掲載の要確認候補（ゴチム等）</summary><div id="lowUnrankedNames" class="note" style="white-space:pre-wrap"></div></details>
</section>
<section class="card"><h2>まとめて貼り付け</h2><p class="note">ポケモン・技・個体値をまとめて取り込めます。読み取りCP付きの「0,11,12 CP717 | ヌオー」にも対応します。日本語の種名、技省略、複数の進化先を含む「個体値リスト」「個体値厳選」、CSVに対応します。</p><label for="importText">コマンドまたはCSV</label><textarea id="importText" spellcheck="false" placeholder="個体値厳選&#10;quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE&#10;0,11,12&#10;3,13,8&#10;2,15,13"></textarea><div class="actions"><button id="importInput" class="secondary">貼り付けた内容を取り込む</button></div><p class="note">取り込みだけでは計算を開始しません。# クルマユ ハハコモリ のような見出しは、次の個体値を両方へ割り当てます。省略した技は種類ごとに補って表示します。</p></section>
<section class="card" id="queuePanel" hidden><h2>連続計算するポケモン</h2><pre id="queuePreview"></pre><p class="note">表示した順にすべて計算します。複数種の内容は上の貼り付け欄から編集できます。</p><button id="singleForm" class="secondary">単一種のフォームに戻す</button></section>
<section class="card"><h2>1. ポケモンと個体値</h2><label for="preset">登録プリセット（任意）</label><select id="preset"></select><p class="note" id="presetHint"></p><label for="allSpecies">全ポケモンから選ぶ</label><select id="allSpecies"></select><label for="species">ポケモン名・英語ID（直接入力）</label><input id="species" list="speciesList" value="quagsire" autocomplete="off"><datalist id="speciesList"></datalist>
<div class="actions" role="group" aria-label="登録区分を一括変更"><button id="bulkNormal" class="secondary">すべて通常に変更</button><button id="bulkShadow" class="secondary">すべてシャドウに変更</button><button id="bulkPurified" class="secondary">すべてリトレーンに変更</button><button id="bulkStatusUndo" class="secondary" hidden>区分変更を元に戻す</button></div><p class="note" id="bulkStatusNote">対象：フォーム、または取り込み済みの全種類。区分だけを修正し、個体値・CPは変えません。リトレーン済みの個体値・CPを入力してください。変更後に再計算します。</p>
<label for="ivs">攻撃,防御,HP（1行1体・最大4,096通り）</label><textarea id="ivs" spellcheck="false" placeholder="0,11,12&#10;3,13,8&#10;2,15,13"></textarea></section>
<section class="card" id="comparisonSettings" tabindex="-1"><h2>2. 比較と推薦の設定</h2>
<div class="meta-presets"><div class="meta-current"><span class="meta-caption">使用中</span><p id="selectedMeta" class="meta-current-name" aria-live="polite">メタプリセットを読み込み中です。</p><span id="metaCurrentCount" class="meta-count"></span><span id="metaCurrentBadges" class="meta-badges"></span></div>
<div class="meta-toolbar"><button id="metaChoose" class="secondary" aria-expanded="false" aria-controls="metaChooser">プリセットを選ぶ</button><button id="metaExport" class="secondary" disabled>PvPoke用にコピー</button></div>
<p id="metaExportStatus" class="note" aria-live="polite"></p><div id="metaExportParts" class="actions" hidden></div>
<div id="metaExportFallback" hidden><label for="metaExportText">PvPoke貼り付け用（手動コピー）</label><textarea id="metaExportText" readonly spellcheck="false"></textarea></div>
<details class="meta-help"><summary>PvPokeへの貼り付け方</summary><p class="note">PvPokeのBattle → Multi／Matrixで、対戦相手一覧のImport/Exportへ貼り付けてImportを押します。リーグはCP1500にしてください。100件超は分割して確認します。編集後は下の「カスタムメタを追加」へ直接貼り付けるか、TXT・CSVで読み込めます。レベル・個体値付きの8列も種と技だけを保存します。</p></details>
<div id="metaChooser" class="meta-chooser" hidden>
<p class="meta-hint">よく使うプリセット</p><div id="metaQuick" class="meta-quick" role="group" aria-label="よく使うメタ"></div>
<label for="metaAll">すべてのメタプリセット</label><div class="meta-all-row"><select id="metaAll"></select><button id="metaReload" class="secondary" aria-label="一覧を再取得" title="一覧を再取得">↻</button></div>
<div class="meta-settings"><button id="metaFavorite" class="secondary" aria-pressed="false">☆ お気に入り</button><button id="metaDefault" class="secondary">デフォルトにする</button></div>
<p id="metaPresetNote" class="note"></p>
</div><p class="note">カップ別の対戦相手一覧を切り替えます。CP1500対応。出場できるポケモンかどうかはカップのルールも確認してください。</p></div><label for="batchMode">計算条件</label><select id="batchMode"><option value="simple">簡易：Default × 6条件</option><option value="detailed">詳細：4つの相手IV × 6条件</option></select>
<label for="evaluation">評価方法</label><select id="evaluation"><option value="app">アプリで自動推薦</option><option value="gpt">GPTで評価（比較情報を作成）</option></select>
<label for="focus">重要な相手（英語名・1行1つ、省略可）</label><textarea id="focus" style="min-height:80px" placeholder="Corviknight&#10;Feraligatr"></textarea><p class="note">名前が一致する技構成をすべて重視します。省略時は独自の役割を全対面から探します。</p>
<details><summary>自動推薦の基準を調整</summary><label for="lead">勝ち方向で採用するRating差（既定20）</label><input id="lead" type="number" min="1" max="1000" step="1" value="20"><p class="note">500の境界を越える役割は差にかかわらず確認します。負けたままのRating差は自動推薦にしません。</p></details>
<label class="checkline" for="forceRecalculate"><input type="checkbox" id="forceRecalculate"> 保存結果を使わず再計算</label><p class="note">同じ対戦条件では過去の結果を再利用します。ゲームデータ・計算コードの更新時は自動で再計算します。</p>
<div class="actions"><button id="run">計算して推薦を表示</button><button id="resume" class="secondary" hidden>前の計算を再開</button><button id="disconnect" class="secondary">接続を解除</button></div><p class="note">CP1500以下・最大Lv50。自分0/相手1、自分0/相手2、自分1/相手2も比較します。</p></section>
<details class="card" id="metaManager">
<summary>カスタムメタを追加</summary>
<p class="note">貼り付けたメタやTXT・CSVを名前付きで最大50件保存できます。これまでのメタや他のプリセットは上書きしません。普段使うメタは選択欄からデフォルトに指定してください。</p>
<p class="note" id="metaStatus">現在のメタを確認しています。</p>
<label for="metaName">保存するプリセット名</label><input id="metaName" maxlength="60" placeholder="普段使うメタ">
<label for="metaText">メタを貼り付け</label><textarea id="metaText" spellcheck="false" aria-describedby="metaInputHelp" placeholder="quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE"></textarea>
<div class="meta-toolbar"><button id="metaTextPreview" class="secondary" type="button">貼り付けた内容を確認</button></div>
<details><summary>ファイルから読み込む（TXT／CSV）</summary><label for="metaFile">メタ一覧（最大80KB）</label><input id="metaFile" type="file" accept=".txt,.csv,text/plain,text/csv"></details>
<p class="note" id="metaInputHelp">species,fast,charged1,charged2 の4列、または level,atk,def,hp を加えた8列を貼り付けできます。保存するのは種と技だけです。入力のレベル・個体値は使わず、計算時は選択した対戦相手の個体値条件を使います。同じ種と技構成はまとめ、最大500技構成まで。「内容を確認」→「別のプリセットとして保存」の順に操作してください。</p>
<div id="metaPreview" class="status" hidden></div>
<div class="actions"><button id="metaApply" class="secondary" disabled>別のプリセットとして保存</button><button id="metaCancel" class="secondary" type="button">選択を取り消す</button></div>
<p id="metaNotice" class="note" aria-live="polite"></p>
</details>
<section class="card" id="results" hidden></section>
<details class="card" id="moveSettings"><summary>技の設定</summary>
<label class="checkline" for="autoMoves"><input id="autoMoves" type="checkbox" checked> 強い技構成をすべて比較</label>
<p class="note">合法な通常技 × ゲージ技2個をすべて実測します。入力個体・メタ全体の平均Ratingと、他構成にない勝ち対面で候補を残します。構成数に応じて時間がかかります。</p>
<label for="moveThreshold">残す平均Ratingの下限（500付近の目安）</label><input id="moveThreshold" type="number" min="0" max="1000" value="450" step="1">
<p class="note">全構成が下限未満でも最高平均の構成は表示します。OFFの場合は下の技だけを計算します。個体ごとのコピー名には、推薦された構成のうち平均Ratingが最も高い技の略号を付けます。</p>
<div class="row"><div><label for="fast">通常技</label><select id="fast"></select></div><div><label for="charged1">ゲージ技1</label><select id="charged1"></select></div><div><label for="charged2">ゲージ技2</label><select id="charged2"></select></div></div>
</details></div></main><script>
'use strict';
const el=id=>document.getElementById(id);let importedSingle=null;let credential='',catalog={},presets=[],active=false,runRef=null,lastResult=null,importedJobs=null,batchState=null,metaPending=null,metaWorking=false;let metaState=null,selectedMetaId=null,metaExportWorking=false;let moveCatalog={},readerImportPending=false,readerImportInFlight=false,readerInputText=null;
function message(s,error=false){const x=el('message');x.hidden=false;x.textContent=s;x.className='status'+(error?' error':'');}
async function api(path,data={}){const headers={'Content-Type':'application/json'};if(credential)headers.Authorization='Bearer '+credential;const r=await fetch('/app-api/'+path,{method:'POST',credentials:'same-origin',headers,body:JSON.stringify(data)});if(r.status===401){const e=Error('ログインの有効期限が切れました。接続キーで再接続してください。');e.status=401;throw e;}let out;try{out=await r.json();}catch{throw Error('応答を確認できません。接続を確認してください。');}if(!r.ok){const e=Error(out.error||'通信エラー');e.status=r.status;throw e;}return out;}
// Keep the legacy cleanup tool accessible by explicit URL only.
// The ordinary IV selection screen no longer advertises low-score cleanup.
function updateLowScorePanelVisibility(){
 el('lowScorePanel').hidden=new URLSearchParams(location.search||'').get('tool')!=='low-score';
}
let lowScoreResults=null;
async function loadLowScores(){
 const button=el('lowSearchRun');button.disabled=true;button.textContent='確認中…';
 try{
  const result=await api('low-score',{mode:el('lowMode').value,threshold:Number(el('lowThreshold').value),exclude_favorites:el('lowExcludeFavorites').checked});
  lowScoreResults=result;
  el('lowScoreSummary').textContent='保存データ '+result.source_date+' / 評価済みの対象 '+result.selected_count+'件 / 検索可能 '+result.searchable_count+'件（内部検索式 '+result.queries.length+'個） / 未掲載・要確認 '+(result.unranked_review_count||0)+'種類。';
  const why=result.exclusion_reasons||{};
  el('lowExclusionSummary').textContent='対象から保護・除外した理由：他の実戦役割で70点以上 '+(why.specialist_preserved||0)+'件 / 進化先が高スコア・未評価 '+(why.evolution_protected||0)+'件 / 姿・英語名の検索が不確実 '+(why.form_or_name_unsearchable||0)+'件 / 未掲載で低評価を確認できない '+(why.unranked_not_verified||0)+'種類 / 未掲載で進化先に高評価あり '+(why.unranked_strong_evolution||0)+'種類 / 未掲載で姿・名前を区別できない '+(why.unranked_uncertain_form_or_name||0)+'種類。未掲載候補は低スコア確定ではありません。';
  el('lowEvolutionProtected').hidden=!result.evolution_protected_count;
  el('lowEvolutionNames').textContent=(result.evolution_protected||[]).map(x=>x.name+' → '+x.evolves_to.join('、')+'：'+x.reason).join('\n');
  el('lowManual').hidden=!result.manual_review_count;
  el('lowManualNames').textContent=(result.manual_review||[]).map(x=>x.name+'（総合'+x.overall+'）：'+x.reason).join('\n');
  el('lowUnrankedReview').hidden=!(result.unranked_review_count>0);
  el('lowUnrankedNames').textContent=(result.unranked_review||[]).map(x=>x.name+'（No.'+x.dex+'）→ '+x.evolves_to.join('、')+'：'+x.reason).join('\n');
 }catch(e){el('lowScoreSummary').textContent='判定理由を取得できませんでした：'+e.message;}
 finally{button.disabled=false;button.textContent='判定理由を確認';}
}
el('lowSearchRun').onclick=()=>loadLowScores();
el('lowExcludeFavorites').onchange=()=>loadLowScores();
function option(select,values,selected){select.replaceChildren();for(const v of values){const o=document.createElement('option');o.value=v;o.textContent=v;select.append(o);}if(values.includes(selected))select.value=selected;}
function moves(row={}){const p=catalog[el('species').value]||{};option(el('fast'),p.fastMoves||[],row.fast);option(el('charged1'),p.chargedMoves||[],row.charged1);option(el('charged2'),p.chargedMoves||[],row.charged2);if(el('charged1').value===el('charged2').value){const alt=(p.chargedMoves||[]).find(x=>x!==el('charged1').value);if(alt)el('charged2').value=alt;}}
function presetKey(p){return p.key||[p.species,p.fast,p.charged1,p.charged2].join('|');}
function currentCandidate(){return {species:el('species').value.trim(),fast:el('fast').value,charged1:el('charged1').value,charged2:el('charged2').value};}
function setCandidate(p){inputPokemonStatus=null;el('species').value=p.species;el('allSpecies').value=p.species;moves(p);const found=presets.find(x=>['species','fast','charged1','charged2'].every(k=>x[k]===p[k]));el('preset').value=found?presetKey(found):'';}
function setPreset(){const p=presets.find(x=>presetKey(x)===el('preset').value);if(p)setCandidate(p);}
function resolveTypedSpecies(){const raw=el('species').value.normalize('NFKC').trim().toLowerCase();if(['gourgeist','pumpkaboo','パンプジン','バケッチャ'].includes(raw)){message('このポケモンはサイズごとに能力が異なります。こだましゅ/XS、ちゅうだましゅ/通常、おおだましゅ/XL、ギガだましゅ/XXLを指定してください。',true);return;}const found=Object.entries(catalog).filter(([sid,p])=>[sid,p.name,p.name_ja,...(p.aliases||[])].some(x=>x&&String(x).normalize('NFKC').trim().toLowerCase()===raw));if(found.length===1)el('species').value=found[0][0];else if(found.length>1)message('複数のフォルムが一致しました。サイズやフォルムを指定してください。',true);}

function setBusy(value){active=value;for(const id of ['bulkNormal','bulkShadow','bulkPurified','bulkStatusUndo'])el(id).disabled=value;for(const id of ['run','resume','disconnect','importInput','singleForm','forceRecalculate','autoMoves','moveThreshold','fast','charged1','charged2'])el(id).disabled=value;for(const id of ['preset','allSpecies','species','fast','charged1','charged2','ivs'])el(id).disabled=value||!!importedJobs;el('metaFile').disabled=value;el('metaApply').disabled=value||!metaPending||metaWorking;el('run').textContent=value?'計算を確認中…':'計算して結果を表示';syncMetaControls();if(!value&&readerImportPending&&!readerImportInFlight)Promise.resolve().then(autoImportReader);}
function node(tag,text,parent,cls=''){const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;parent.append(n);return n;}
async function copy(text,button){try{await navigator.clipboard.writeText(text);button.textContent='コピーしました';}catch{const root=el('message');message('コピーできませんでした。下の欄から選択してコピーしてください。',true);const area=node('textarea',text,root);area.value=text;area.readOnly=true;area.focus();area.select();}}
// Result labels are resolved against the active catalog, including form names.
let nameEntries=[],displayedResults=[],opponentLabels=new Map(),nicknameBindings=[];
function prepareLabels(){opponentLabels.clear();nameEntries=Object.entries(catalog).map(([sid,p])=>({sid,...p})).sort((a,b)=>(b.name||'').length-(a.name||'').length);}
function opponentLabel(value){const text=String(value||'');if(opponentLabels.has(text))return opponentLabels.get(text);const found=nameEntries.find(p=>p.name&&(text===p.name||text.startsWith(p.name+' ')));const label=found?{name:found.name_ja||found.name,code:found.nickname_code||null,detail:text.slice(found.name.length)}:{name:text,code:null,detail:''};opponentLabels.set(text,label);return label;}
function shieldCode(shield){return {s0:'00',s1:'11',s2:'22',i0y1:'01',i0y2:'02',i1y2:'12'}[shield]||'';}
function conditionLabel(e){const code=shieldCode(e.shield);const mode={default:'標準IV',rank1:'SCP1位IV',attack:'攻撃重視IV',defense:'防御重視IV'}[e.mode]||e.mode;return mode+'・'+(code?'自分シールド'+code[0]+' / 相手'+code[1]:e.shield);}
function outcome(e){return e.rating>500?'勝ち':e.rating===500?'引き分け':'負け';}
function evidenceText(e){const label=opponentLabel(e.opponent);return label.name+label.detail+'｜'+conditionLabel(e)+'｜'+outcome(e)+'・Rating '+e.rating+'（他候補の最高 '+(e.next_best??'比較なし')+'）';}
function matchupNames(row,win){return [...new Set((row.evidence||[]).filter(e=>win?e.rating>500:e.rating===500).map(e=>opponentLabel(e.opponent).name))];}
function primaryEvidence(row){return (row.evidence||[]).find(e=>e.rating>500)||(row.evidence||[])[0];}
function summaryEvidence(row){
 const seen=new Set(),summary=[];
 // Evidence is already ordered by focus, uniqueness and shield relevance.
 for(const e of row.evidence||[]){
  if(e.rating<500)continue;
  const name=opponentLabel(e.opponent).name;
  if(seen.has(name))continue;
  seen.add(name);summary.push(e);
  if(summary.length===3)break;
 }
 return summary;
}
// Check assembled nicknames as well as individual codes; reject unknown patterns.
const blockedNickname=/(anal|ass|bitch|cunt|dick|fuck|nazi|porn|sex|shit|slut)/i;
function validNickname(t){return t.length<=12&&/^[A-Za-z0-9><=]+$/.test(t)&&!blockedNickname.test(t.replace(/[^A-Za-z]/g,''));}
function codeChoices(sid,width){
 const seed=String(catalog[sid]?.nickname_code||'').replace(/[^A-Za-z0-9]/g,'');
 const name=sid.split('_')[0].replace(/[^A-Za-z]/g,'');
 if(!seed||!name)return [];
 const opts=[seed.slice(0,width),name.slice(0,width),
  seed[0]+seed.slice(1).slice(-Math.max(0,width-1)),
  name[0]+name.slice(1).slice(-Math.max(0,width-1)),
  seed[0]+seed.slice(2,2+width-1),name[0]+name.slice(2,2+width-1)];
 return [...new Set(opts.filter(x=>x.length>=Math.min(2,width)&&x.length<=width&&/^[A-Za-z0-9]+$/.test(x)))];
}
function nicknameMembers(result,row,ivs){
 const members=[{result,row,sid:result.candidate.species}];
 const sections=result.source_sections||[];
 if(!sections.length)return members;
 for(const other of displayedResults){
  if(other===result||other.candidate?.species===result.candidate.species||
   !(other.source_sections||[]).some(x=>sections.includes(x)))continue;
  const match=(other.selection?.recommendations||[]).find(r=>
   r.ivs===ivs||(r.equivalent_candidates||[]).some(x=>x.ivs===ivs));
  if(match)members.push({result:other,row:match,sid:other.candidate.species});
 }
 members.sort((a,b)=>displayedResults.indexOf(a.result)-displayedResults.indexOf(b.result));
 return members;
}
function nicknameFor(result,row,ivs=row.ivs){
 const members=nicknameMembers(result,row,ivs);
 if(members.some(m=>m.row.chosen_moves))return movesetNickname(members);
 // Only documented PvPoke evidence is compared; unseen battles are not inferred.
 const matches=members.flatMap(member=>(member.row.evidence||[])
  .filter(e=>Number.isFinite(e.rating)&&opponentLabel(e.opponent).code&&shieldCode(e.shield))
  .map(e=>({member,e,opponent:opponentLabel(e.opponent)})))
  .sort((a,b)=>(b.e.rating>500)-(a.e.rating>500)||b.e.rating-a.e.rating||
    Number(String(b.member.row.grade||'').startsWith('S'))-Number(String(a.member.row.grade||'').startsWith('S')));
 const best=matches[0];
 if(!best||members.length>3)return null;
 const grade=String(best.member.row.grade||'?').startsWith('S')?'S':String(best.member.row.grade||'?').startsWith('A')?'A':'?';
 const sign=best.e.rating>500?'>':best.e.rating===500?'=':'<', suffix=sign+best.opponent.code+shieldCode(best.e.shield);
 // Two stages: 3 letters for the best-Rating stage, 2 for the other.
 // Three stages: 2 per stage, grade omitted to retain opponent and shields.
 const labelBudget=12-grade.length-suffix.length;
 const primaryWidth=Math.min(3,labelBudget-2);
 const widths=members.length===1?[4]:members.length===2?
  members.map(m=>m===best.member?primaryWidth:2):[2,2,2];
 if(members.length===2&&primaryWidth<2)return null;
 const candidates=members.map((m,i)=>codeChoices(m.sid,members.length===1?
  Math.min(4,String(catalog[m.sid]?.nickname_code||'').length):widths[i]));
 if(candidates.some(x=>!x.length))return null;
 const prefix=members.length===3?'':grade;
 function select(i,codes){
  if(i===members.length){
   if(new Set(codes.map(x=>x.toLowerCase())).size!==codes.length)return null;
   const text=prefix+codes.join('')+suffix;
   return validNickname(text)?{text,codes}:null;
  }
  for(const code of candidates[i]){
   const picked=select(i+1,[...codes,code]);
   if(picked)return picked;
  }
  return null;
 }
 const picked=select(0,[]);
 if(!picked)return null;
 const stages=members.map((m,i)=>picked.codes[i]+'＝'+(catalog[m.sid]?.name_ja||catalog[m.sid]?.name||m.sid));
 return {text:picked.text,description:grade+'＝優先候補評価 / '+stages.join(' / ')+
  ' / '+sign+'＝'+outcome(best.e)+' / '+best.opponent.code+'＝'+best.opponent.name+
  ' / '+conditionLabel(best.e)+' / Rating '+best.e.rating+
  (members.length>1?'（同じ個体値・同じ入力区間の'+members.length+'種類を比較）':'')};
}
// Source records describe the physical Pokemon before powering up/evolving.
// Repair old saved selection results too, without changing the source CP or IV.
// New server-generated searches already use &alola / &galar / &hisui / &paldea.
function normalizedRegionalSearch(search){
 if(typeof search!=='string')return search;
 const terms={alolan:'alola',galarian:'galar',hisuian:'hisui',paldean:'paldea'};
 return search.replace(/^flab(?:é|e\u0301|e)b(?:é|e\u0301|e)(?=&|$)/i,'669').replace(/^(.+?)\s*\(\s*(Alolan|Galarian|Hisuian|Paldean)\s*\)(?:\s*\(\s*Shadow\s*\))?(?=&|$)/i,
  (_match,base,adjective)=>base.trim()+'&'+terms[adjective.toLowerCase()]);
}
function statusSearch(search,status){
 if(!status)return normalizedRegionalSearch(search);
 const parts=normalizedRegionalSearch(search).split('&').filter(x=>!['shadow','!shadow','purified','!purified'].includes(x.toLowerCase()));
 if(status==='shadow')parts.push('shadow');
 else if(status==='purified')parts.push('purified');
 else parts.push('!shadow','!purified');
 return parts.join('&');
}
function xxlProtectedSearch(search){
 if(!search||typeof search!=='string')return search;
 const terms=search.toLowerCase().split('&').map(x=>x.trim());
 // Pumpkin/Gourgeist super-size is a distinct battle form and requires &xxl.
 // Never create the impossible &xxl&!xxl combination.
 if(terms.includes('xxl')||terms.includes('!xxl'))return search;
 return search+'&!xxl';
}
function individualSearches(result,iv){
 const records=(result.source_records||[]).filter(r=>r.ivs===iv.ivs);
 return records.length?records.map(r=>({search:xxlProtectedSearch(statusSearch(r.search_string,result.pokemon_status)),cp:r.cp,species:r.species})):[{search:xxlProtectedSearch(statusSearch(iv.search_string,result.pokemon_status))}];
}
function overlayExport(results){
 recommendationExportText(results); // Validate every pair before writing anything.
 const items=results.flatMap(result=>(result.selection?.recommendations||[]).flatMap(row=>
  [row,...(row.equivalent_candidates||[])].flatMap(iv=>individualSearches(result,iv).map(source=>({
   search:source.search,nickname:nicknameFor(result,row,iv.ivs).text,ivs:iv.ivs,
   cp:source.cp||null,species:source.species||result.candidate.species,
   target_species:result.candidate.species,
   target_name:catalog[result.candidate.species]?.name_ja||result.display_name||catalog[result.candidate.species]?.name||result.candidate.species
  })))));
 return JSON.stringify({format:'pokemoniv-overlay-v2',items});
}
async function copyOverlay(results,button){try{await copy(overlayExport(results),button);}catch(e){message(e.message,true);}}
function recommendationExport(result){
 return (result.selection?.recommendations||[]).flatMap(row=>
  [row,...(row.equivalent_candidates||[])].flatMap(iv=>{
   const nick=nicknameFor(result,row,iv.ivs);
   if(!nick)throw Error('ニックネームを安全に生成できません。種名・略号を確認してください。');
   if(!iv.search_string)throw Error('検索式を確認できない個体があります。結果を再取得してください。');
   return individualSearches(result,iv).map(source=>{
    if(!source.search)throw Error('検索式が欠けています。再度取り込んでください。');
    return source.search+'\n'+nick.text;
   });
  })).join('\n');
}
function recommendationExportText(results){
 const available=results.filter(r=>r.selection?.recommendations?.length);
 if(!available.length)throw Error('共有する推薦個体がありません。');
 return available.map(recommendationExport).join('\n');
}
async function copyRecommendations(results,button){try{await copy(recommendationExportText(results),button);}catch(e){message(e.message,true);}}
// Chrome on Android can open an installed reader directly from the user's click.
// Keep the Sharesheet path for other browsers and payloads that are too long for an Intent URL.
function launchAndroidOverlay(text){
 if(!/Android/i.test(navigator.userAgent||'')||!/Chrome|EdgA/i.test(navigator.userAgent||''))return false;
 if(typeof window==='undefined'||typeof window.location?.assign!=='function'||typeof TextEncoder==='undefined'||typeof btoa!=='function')return false;
 const bytes=new TextEncoder().encode(text);
 if(bytes.length>26000)return false;
 let binary='';
 for(let i=0;i<bytes.length;i+=4096)binary+=String.fromCharCode(...bytes.subarray(i,i+4096));
 const payload=btoa(binary).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
 const url='intent://import?payload='+payload+
  '#Intent;scheme=pokemonivreader;package=com.example.pokemonivreader;end';
 window.location.assign(url);
 return true;
}
async function shareRecommendations(results,button){
 let text;
 try{text=overlayExport(results);}catch(e){message(e.message,true);return;}
 try{if(launchAndroidOverlay(text))return;}catch(e){/* use the standard Sharesheet */}
 if(typeof navigator.share!=='function'){
  await copy(text,button);
  message('このブラウザは直接共有に対応していません。コピーした内容をAndroidの「厳選コピーリスト」で貼り付けてください。');
  return;
 }
 try{
  await navigator.share({title:'厳選コピーリスト',text});
  message('Androidの共有先で「厳選コピーリスト」を選ぶと、自動保存してオーバーレイを表示します。');
 }catch(e){
  if(e?.name==='AbortError')return;
  message('Androidへの共有を開始できませんでした。既存の「すべてコピー」ボタンから取り込めます。',true);
 }
}
function renderSearch(row,parent,result){if(!row.search_string)return;for(const source of individualSearches(result||{},row)){node('label',source.cp?'検索式（読み取り時CP'+source.cp+'）':'検索式',parent);node('code',source.search,parent,'search');const b=node('button','検索式をコピー',parent);b.onclick=()=>copy(source.search,b);}}
function refreshNicknames(){
 for(const item of nicknameBindings){
  const nick=nicknameFor(item.result,item.row,item.ivs);
  item.label.textContent=nick?'ニックネーム（'+nick.text.length+'/12文字）':'ニックネーム（自動生成不可）';
  item.code.textContent=nick?nick.text:'';
  item.button.disabled=!nick;
  item.button.textContent='ニックネームをコピー';
  item.note.textContent=nick?nick.description:'安全な12文字以内の略号を生成できません。個体値と略号を確認してください。';
 }
}
function renderNickname(result,row,parent,ivs=row.ivs){
 const label=node('label','',parent),code=node('code','',parent,'search');
 const button=node('button','ニックネームをコピー',parent);
 const explanation=node('details','',parent);node('summary','ニックネームの意味',explanation);
 const note=node('p','',explanation,'note');
 nicknameBindings.push({result,row,ivs,label,code,button,note});
 button.onclick=()=>{const nick=nicknameFor(result,row,ivs);if(nick)copy(nick.text,button);};
 refreshNicknames();
}
function updateAllCopy(){const box=el('allCopyActions');const available=displayedResults.filter(r=>r.selection?.recommendations?.length);box.hidden=available.length<2;}
function render(result,append=false){
 lastResult=result;const root=el('results');
 if(!append){root.replaceChildren();displayedResults=[];nicknameBindings=[];const all=node('div','',root,'actions');all.id='allCopyActions';all.hidden=true;const b=node('button','全種類の検索式とニックネームをコピー',all);b.onclick=()=>copyRecommendations(displayedResults,b);const overlayCopy=node('button','オーバーレイ用にコピー',all,'secondary');overlayCopy.onclick=()=>copyOverlay(displayedResults,overlayCopy);const share=node('button','Androidへ送る',all,'secondary');share.onclick=()=>shareRecommendations(displayedResults,share);}
 displayedResults.push(result);updateAllCopy();root.hidden=false;
 const panel=node('div','',root),sid=result.candidate.species;
 node('h2',result.display_name||catalog[sid]?.name_ja||result.selection?.english_name||sid,panel);
 if(result.result_cache?.reused)node('p','過去の対戦結果を再利用しました。推薦は今回の条件で確認しています。',panel,'note');
 if(result.meta_preset)node('p','対戦メタ：'+result.meta_preset.name+' / SHA256 '+result.meta_sha256.slice(0,12)+'…',panel,'note');
 node('p',[result.candidate.fast,result.candidate.charged1,result.candidate.charged2].join(' / '),panel,'note');const selection=result.selection;
 if(!selection){node('h2','GPT評価用の比較情報',panel);node('p','今回の比較情報をコピーしてGPTに評価を依頼できます。',panel);const b=node('button','比較情報をコピー',panel);b.onclick=()=>copy('以下のPvPoke実測比較を、個体値厳選の基準で評価してください。おすすめ個体と英語検索式を示してください。\n'+JSON.stringify(result),b);return;}
 if(result.moveset_comparison)renderMovesetComparison(result,panel);
 node('h2','おすすめ個体',panel);
 node('p','検索式ではXXLの実際の身長を比較できないため、通常の検索式からXXLを除外します。XXLは手動で比較し、最大の個体を残してください。サイズがフォルムそのものを表す場合は例外です。',panel,'note');
 if(selection.input_notices)selection.input_notices.forEach(n=>node('p',n,panel,'note'));
 if(selection.minior_experimental)node('p','メテノの戦術比較（試験版）：流星で即撃ち／コアまで温存／状況判断を同じ条件で比較。表示Ratingは各対面で最良の戦術を選んだ上限値です。実機のCP・レベル調整が未検証のため、この結果だけで個体を博士に送らないでください。',panel,'note');
 node('p',(result.moveset_comparison?'技ごとの推薦を統合しています。同じ個体値は1回だけ表示し、その個体の採用技を名前に略します。':'')+'Sは総合本命、Aはその本命にない実戦上の役割を補う個体です。1構成では通常最大4体に絞ります。S/Aは入力候補内の暫定評価で、実際の勝敗を保証するものではありません。',panel,'note');
 if(selection.policy?.version&&selection.policy.version!=='box-first-v3'){
  node('p','保存済みの結果は以前の推薦基準です。最新のS本命・少数厳選を使うには、同じ入力を再計算してください。',panel,'note');
 }
 if(selection.recommendations.length){const actions=node('div','',panel,'actions');const b=node('button','検索式とニックネームをすべてコピー',actions);b.onclick=()=>copyRecommendations([result],b);const overlayCopy=node('button','オーバーレイ用にコピー',actions,'secondary');overlayCopy.onclick=()=>copyOverlay([result],overlayCopy);const share=node('button','Androidへ送る',actions,'secondary');share.onclick=()=>shareRecommendations([result],share);node('p','検索式→改行→ニックネームの順で、同じ性能の代替個体も含めてコピーします。Androidへの送信は共有先で「厳選コピーリスト」を選んでください。Android Chromeではインストール済みの読み取りアプリを直接開きます。その他は共有メニューを使います。個体値の見出しを引き継ぐ場合は「Androidへ送る」か「オーバーレイ用にコピー」を使ってください。',panel,'note');}
 if(selection.excluded&&(!Array.isArray(selection.excluded)||selection.excluded.length))node('p','計算対象から除外された対面があります：'+JSON.stringify(selection.excluded),panel);
 const searchCounts=new Map();for(const r of selection.recommendations)for(const item of [r,...(r.equivalent_candidates||[])]){for(const source of individualSearches(result,item)){const v=searchCounts.get(source.search)||new Set();v.add(item.ivs);searchCounts.set(source.search,v);}}if([...searchCounts.values()].some(x=>x.size>1))node('p','注意：同じ検索式に異なる個体値が含まれます。検索式は範囲指定なので、名前を付ける前に各個体の攻撃・防御・HPを確認してください。',panel,'note');
 if(selection.unmatched_focus.length)node('p','一致しなかった重要相手：'+selection.unmatched_focus.map(x=>opponentLabel(x).name).join('、'),panel);
 if(!selection.recommendations.length)node('p','自動推薦の根拠が十分な個体はありません。下の保留個体を確認してください。',panel);
 for(const row of selection.recommendations){
  const card=node('article','',panel,'recommendation');node('h2',row.rank+'位｜'+row.ivs+'｜'+row.grade,card);node('div',row.role,card,'badge');
  if(row.chosen_moves)node('p','採用技：'+moveLabel(row.chosen_moves)+' / 平均Rating '+row.moveset_mean.toFixed(1),card,'note');
  if(row.minior_strategy){
   const m=row.minior_strategy,parts=[];
   if(m.hold_win_flip_count)parts.push('コアまでゲージ温存で新たに勝ち '+m.hold_win_flip_count+'条件');
   if(m.adaptive_win_flip_count)parts.push('状況判断で新たに勝ち '+m.adaptive_win_flip_count+'条件');
   if(parts.length){
    node('p',parts.join(' ／ ')+'（戦術選択の試験的評価）',card,'note');
    if(m.hold_win_flip_examples?.length){
     const details=node('details','',card);
     node('summary','ゲージ温存で逆転する対面（例）',details);
     for(const e of m.hold_win_flip_examples)node('p',opponentLabel(e.opponent).name+'・'+e.shield+'：即撃ち '+e.instant+' → 温存 '+e.hold,details,'note');
    }
   }
  }
  // Prefer the actual WIN/DRAW differences from a similar higher-ranked IV.
  // Sharing a displayed opponent or even Rating 511 is not a distinct role.
  const comparison=Boolean(row.comparison_peer),seenNames=new Set(),summary=[];
  for(const e of comparison?(row.comparison_differences||[]):summaryEvidence(row)){
   const name=opponentLabel(e.opponent).name;
   if(seenNames.has(name))continue;
   seenNames.add(name);summary.push(e);
   if(summary.length===3)break;
  }
  if(comparison)node('p','最も似た上位個体 '+row.comparison_peer+' と勝敗が異なる条件（最大3件）',card,'note');
  if(summary.length){const list=node('ul','',card,'matchup-summary');
   for(const e of summary){
    const relative=comparison?'［'+row.comparison_peer+'：'+outcome({rating:e.peer_rating})+'］':'';
    node('li',opponentLabel(e.opponent).name+'：'+outcome(e)+'（'+conditionLabel(e)+'）'+relative,list);
   }
  }
  if(comparison&&!summary.length)node('p','比較根拠を表示できません。結果の再計算をお願いします。',card,'note');
  renderSearch(row,card,result);
  renderNickname(result,row,card);
  if(row.equivalent_candidates.length){const d=node('details','',card);node('summary','全条件で同じ性能の代替個体',d);for(const e of row.equivalent_candidates){node('p',e.ivs,d);renderSearch(e,d,result);renderNickname(result,row,d,e.ivs);}}
  const details=node('details','',card);node('summary','推薦根拠をすべて見る（'+row.evidence_count+'条件）',details);node('pre',row.evidence.map(evidenceText).join('\n'),details);
  if(row.tradeoff){const e=row.tradeoff;node('p','苦手になる対面：'+opponentLabel(e.opponent).name+'・'+conditionLabel(e)+' は '+outcome(e)+'（Rating '+e.rating+' / '+e.best_iv+' は '+e.best_rating+'）。',details,'note');}
 }
 if(selection.covered_candidates?.length){const d=node('details','',panel);node('summary','役割が重複する個体（'+selection.covered_candidates.length+'）',d);for(const row of selection.covered_candidates){node('p',row.ivs+' → '+row.covered_by+'で全条件をカバー',d);if(row.equivalent_candidates?.length)node('p','同じ性能：'+row.equivalent_candidates.map(x=>x.ivs).join(', '),d);}}
 if(selection.additional_candidates?.length){const d=node('details','',panel);node('summary','参考：今回は保存を見送る候補（'+selection.additional_candidates.length+'）',d);node('p','細かな勝敗差も計算していますが、ボックス整理を優先して一括コピーには含めません。',d,'note');for(const row of selection.additional_candidates){node('p',row.ivs+'：'+row.reason+(row.new_viable_conditions?'（追加の互角以上 '+row.new_viable_conditions+'条件）':''),d);if(row.equivalent_candidates?.length)node('p','同じ性能：'+row.equivalent_candidates.map(x=>x.ivs).join(', '),d);}}
 if(selection.review_candidates.length){const d=node('details','',panel);node('summary','保留：'+selection.review_candidates.length+'個体',d);for(const row of selection.review_candidates){node('p',row.ivs+'：'+row.reason,d);if(row.equivalent_candidates.length)node('p','同じ性能：'+row.equivalent_candidates.map(x=>x.ivs).join(', '),d);}}
 const rejected=Object.entries(selection.dominated_by);if(rejected.length){const d=node('details','',panel);node('summary','全条件で他候補以下の個体（'+rejected.length+'）',d);for(const [iv,rivals] of rejected)node('p',iv+' → '+rivals.join(', '),d);}
 refreshNicknames();
}
function metaNotice(text,error=false){el('metaNotice').textContent=text;el('metaNotice').style.color=error?'#ffb6b6':'';}
function resetMetaUpload(){metaPending=null;el('metaApply').disabled=true;el('metaPreview').hidden=true;el('metaPreview').textContent='';el('metaFile').value='';el('metaText').value='';}
function chosenMeta(){return metaState?.items.find(p=>p.id===selectedMetaId);}
function syncMetaControls(){
 el('metaDefault').disabled=!!chosenMeta()?.default||active||metaWorking||!!batchState||!!runRef;
 el('metaExport').disabled=metaExportWorking||!chosenMeta()||chosenMeta().available===false;
 const blocked=active||metaWorking||!!batchState||!!runRef;
 for(const id of ['metaChoose','metaAll','metaFavorite','metaName','metaFile','metaText','metaTextPreview','metaApply'])el(id).disabled=blocked;
 for(const button of el('metaQuick').children)button.disabled=blocked;
 el('metaReload').disabled=active||metaWorking;
 el('metaApply').disabled=blocked||!metaPending||!metaState;
 el('run').disabled=active||metaWorking||!metaState;
}
function renderMetaChoices(){
 if(!metaState)return;
 const current=chosenMeta();
 el('selectedMeta').textContent=current?current.name:'メタプリセットを選択してください';
 el('metaCurrentCount').textContent=current?current.rows+'構成':'';
 el('metaCurrentBadges').replaceChildren();
 if(current?.default)node('span','デフォルト',el('metaCurrentBadges'),'meta-tag');
 if(current?.favorite)node('span','★ お気に入り',el('metaCurrentBadges'),'meta-tag meta-star');
 el('metaStatus').textContent='公式プリセット取得日：'+metaState.retrieved+' / カスタム '+metaState.items.filter(p=>p.source==='custom').length+'件';
 el('metaFavorite').textContent=current?.favorite?'★ お気に入り':'☆ お気に入り';
 el('metaFavorite').setAttribute?.('aria-pressed',String(!!current?.favorite));
 el('metaFavorite').setAttribute?.('aria-label',current?.favorite?'お気に入りから外す':'お気に入りに追加');
 el('metaDefault').textContent=current?.default?'✓ デフォルト':'デフォルトにする';
 el('metaDefault').className='secondary'+(current?.default?' is-set':'');
 el('metaPresetNote').textContent=current?.note||'デフォルトは次回接続時の初期値です。今回だけ選び替えてもデフォルトは変わりません。';
 const ordered=metaState.items.filter(p=>p.available!==false).slice().sort((a,b)=>Number(b.default)-Number(a.default)||Number(b.favorite)-Number(a.favorite));
 el('metaQuick').replaceChildren();
 for(const p of ordered.slice(0,4)){
  const button=document.createElement('button');button.type='button';button.className='meta-chip';button.title=p.name;
  const mark=node('span',p.id===selectedMetaId?'✓':'○',button,'meta-chip-mark');mark.setAttribute?.('aria-hidden','true');
  node('span',p.name,button,'meta-chip-name');
  if(p.default)node('span','既定',button,'meta-tag');
  if(p.favorite)node('span','★',button,'meta-tag meta-star');
  button.setAttribute?.('aria-label',p.name+(p.default?'、デフォルト':'')+(p.favorite?'、お気に入り':''));
  button.setAttribute?.('aria-pressed',String(p.id===selectedMetaId));button.onclick=()=>chooseMeta(p.id);el('metaQuick').append(button);
 }
 el('metaAll').replaceChildren();
 for(const p of [...ordered,...metaState.items.filter(p=>p.available===false)]){
  const option=document.createElement('option');option.value=p.id;option.textContent=(p.default?'既定 · ':p.favorite?'★ ':'')+p.name+' / '+p.rows+'構成'+(p.available===false?'（利用不可：'+p.unavailable_reason+'）':'');option.disabled=p.available===false;el('metaAll').append(option);
 }
 el('metaAll').value=selectedMetaId||'';syncMetaControls();
}
function chooseMeta(id){
 if(active||metaWorking||batchState||runRef)return;
 const p=metaState?.items.find(x=>x.id===id);
 if(!p||p.available===false)return;
 selectedMetaId=id;clearMetaExport();renderMetaChoices();el('metaChooser').hidden=true;el('metaChoose').setAttribute?.('aria-expanded','false');
}
async function refreshMetaStatus(initial=false){
 try{
  const previous=chosenMeta();const next=await api('meta-presets');
  metaState=next;
  if(initial||!next.items.some(p=>p.id===selectedMetaId))selectedMetaId=next.default_id;
  if(batchState?.meta_preset_id)selectedMetaId=batchState.meta_preset_id;
  if(previous?.id!==selectedMetaId||previous?.sha256!==chosenMeta()?.sha256)clearMetaExport();
  renderMetaChoices();
 }catch(e){el('selectedMeta').textContent='メタ一覧を取得できません：'+e.message;throw e;}
}
el('metaChoose').onclick=()=>{if(active||metaWorking||batchState||runRef)return;el('metaChooser').hidden=!el('metaChooser').hidden;el('metaChoose').setAttribute?.('aria-expanded',String(!el('metaChooser').hidden));};
el('metaAll').onchange=()=>chooseMeta(el('metaAll').value);
el('metaReload').onclick=async()=>{try{await refreshMetaStatus();metaNotice('一覧を再取得しました。');}catch(e){metaNotice(e.message,true);}};
async function saveMetaPreference(action){
 if(active||metaWorking||batchState||runRef||!chosenMeta()||(action==='default'&&chosenMeta().default))return;
 metaWorking=true;syncMetaControls();
 try{metaState=await api('meta-preset-save',{action,id:selectedMetaId,favorite:!chosenMeta().favorite,revision:metaState.revision});renderMetaChoices();metaNotice('設定を保存しました。');}
 catch(e){metaNotice(e.message,true);}
 finally{metaWorking=false;syncMetaControls();}
}
el('metaFavorite').onclick=()=>saveMetaPreference('favorite');
el('metaDefault').onclick=()=>saveMetaPreference('default');
function clearMetaExport(){
 el('metaExport').textContent='PvPoke用にコピー';el('metaExportStatus').textContent='';
 el('metaExportParts').replaceChildren();el('metaExportParts').hidden=true;
 el('metaExportFallback').hidden=true;el('metaExportText').value='';
}
async function copyMetaPart(csv,button,label){
 el('metaExportFallback').hidden=true;el('metaExportText').value='';
 try{await navigator.clipboard.writeText(csv);button.textContent='コピーしました';el('metaExportStatus').textContent=label+'をコピーしました。PvPokeのImport/Exportに貼り付けてください。';}
 catch{button.textContent='手動コピー欄を表示中';el('metaExportFallback').hidden=false;const area=el('metaExportText');area.value=csv;area.focus?.();area.select?.();el('metaExportStatus').textContent='自動コピーできませんでした。下の欄を選択してコピーしてください。';}
}
el('metaExport').onclick=async()=>{
 if(metaExportWorking||!chosenMeta()||chosenMeta().available===false)return;
 const selected={...chosenMeta()};clearMetaExport();metaExportWorking=true;syncMetaControls();
 el('metaExportStatus').textContent='PvPoke用のデータを準備しています。';
 try{
  const data=await api('meta-preset-export',{id:selected.id,expected_sha256:selected.sha256});
  if(selectedMetaId!==selected.id||chosenMeta()?.sha256!==selected.sha256)return;
  if(data.id!==selected.id||data.sha256!==selected.sha256)throw Error('コピー内容が選択中のメタと一致しません。再取得してください。');
  if(!Array.isArray(data.parts)||!data.parts.length||data.parts.some(p=>typeof p.csv!=='string'||!p.csv.trim()))throw Error('コピー用データが不完全です。一覧を再取得してください。');
  if(data.parts.length===1){await copyMetaPart(data.parts[0].csv,el('metaExport'),data.name+'（'+data.rows+'件）');}
  else{
   el('metaExportStatus').textContent=data.name+'は'+data.rows+'件です。PvPokeの取り込み上限に合わせ、'+data.parts.length+'組に分けています。各組を別のグループとして確認してください。';
   el('metaExportParts').hidden=false;
   data.parts.forEach((part,i)=>{
    const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=(i+1)+' / '+data.parts.length+'（'+part.start+'〜'+part.end+'件）をコピー';
    button.onclick=()=>{if(chosenMeta()?.id!==selected.id||chosenMeta()?.sha256!==selected.sha256){el('metaExportStatus').textContent='メタが変わりました。もう一度PvPoke用にコピーしてください。';return;}return copyMetaPart(part.csv,button,data.name+' '+(i+1)+' / '+data.parts.length+'組目');};el('metaExportParts').append(button);
   });
  }
 }catch(e){if(selectedMetaId===selected.id)el('metaExportStatus').textContent='コピーできませんでした：'+e.message;}
 finally{metaExportWorking=false;syncMetaControls();}
};
async function previewMetaInput(file=null){
 if(active||metaWorking||batchState||runRef){metaNotice('計算中はメタを更新できません。',true);return;}
 resetMetaUploadPreviewOnly();metaWorking=true;syncMetaControls();metaNotice('メタの内容と技を確認中です。');
 try{
  let content=file?await file.text():el('metaText').value;
  if(file&&el('metaFile').files?.[0]!==file)return;
  if(file){el('metaText').value=content;content=el('metaText').value;} // Textareas normalize CRLF/CR to LF.
  if(!content.trim())throw Error('メタの内容を貼り付けてください。');
  const preview=await api('meta-preview',{csv:content});
  if(el('metaText').value!==content||(file&&el('metaFile').files?.[0]!==file))return;
  metaPending={content,preview};
  if(file&&!el('metaName').value.trim())el('metaName').value=file.name.replace(/\.(txt|csv)$/i,'').slice(0,60);
  const lines=['入力 '+(preview.input_rows??preview.rows)+'行 → 保存 '+preview.rows+'技構成','既存のメタは上書きしません。'];
  if(preview.duplicate_count){
   lines.push('重複 '+preview.duplicate_count+'行を統合しました。');
   if(preview.duplicate_lines?.length)lines.push('重複した行：'+preview.duplicate_lines.join(', ')+(preview.duplicate_count>preview.duplicate_lines.length?' ほか':''));
  }
  if(preview.custom_stats_count){
   lines.push('レベル・個体値付き '+preview.custom_stats_count+'行：種と技だけを保存します。入力のレベル・個体値は保存・計算に使いません。計算時は選択した対戦相手の個体値条件を使います。');
   if(preview.custom_stats_lines?.length)lines.push('対象行：'+preview.custom_stats_lines.join(', ')+(preview.custom_stats_count>preview.custom_stats_lines.length?' ほか':''));
  }
  el('metaPreview').textContent=lines.join('\n');el('metaPreview').hidden=false;
  metaNotice('内容と名前を確認し、別のプリセットとして保存してください。');
 }catch(e){metaPending=null;metaNotice(e.message+'（元のメタは変更されていません）',true);}
 finally{metaWorking=false;syncMetaControls();}
}
el('metaTextPreview').onclick=()=>previewMetaInput();
el('metaText').oninput=()=>{resetMetaUploadPreviewOnly();el('metaFile').value='';metaNotice('内容を変更しました。「貼り付けた内容を確認」を押してください。');};
el('metaFile').onchange=async()=>{
 if(active||metaWorking||batchState||runRef)return;
 const selected=el('metaFile').files?.[0];resetMetaUploadPreviewOnly();
 if(!selected){metaNotice('');return;}
 if(!/\.(txt|csv)$/i.test(selected.name)){metaNotice('TXTまたはCSVファイルを選んでください。',true);return;}
 if(!selected.size||selected.size>80000){metaNotice('ファイルは空でない80KB以下のものを選んでください。',true);return;}
 await previewMetaInput(selected);
};
function resetMetaUploadPreviewOnly(){metaPending=null;el('metaApply').disabled=true;el('metaPreview').hidden=true;el('metaPreview').textContent='';}
el('metaCancel').onclick=()=>{if(metaWorking)return;resetMetaUpload();metaNotice('メタの更新を取り消しました。現在のメタをそのまま使用します。');};
el('metaApply').onclick=async()=>{
 if(active||metaWorking||batchState||runRef||!metaPending||!metaState)return;
 if(el('metaText').value!==metaPending.content){resetMetaUploadPreviewOnly();metaNotice('内容が確認後に変わりました。もう一度確認してください。',true);return;}
 if(!el('metaName').value.trim()){metaNotice('プリセット名を入力してください。',true);return;}
 const {content,preview}=metaPending;
 metaWorking=true;syncMetaControls();el('metaCancel').disabled=true;
 try{
  const saved=await api('meta-preset-save',{action:'create',name:el('metaName').value.trim(),csv:content,expected_sha256:preview.sha256,revision:metaState.revision});
  metaState=saved;selectedMetaId=saved.saved_id;clearMetaExport();resetMetaUpload();el('metaName').value='';renderMetaChoices();
  metaNotice('保存完了：'+preview.rows+'技構成'+(preview.duplicate_count?'（重複'+preview.duplicate_count+'行を統合）':'')+'。今回の計算に選択しました。普段使う場合はデフォルトに指定してください。');
 }catch(e){metaNotice(e.message+'（既存のメタは維持されます。一覧を再取得して確認してください）',true);}
 finally{metaWorking=false;el('metaCancel').disabled=false;syncMetaControls();}
};
let inputPokemonStatus=null,bulkStatusUndo=null;
function statusLabel(status){return {normal:'通常',shadow:'シャドウ',purified:'リトレーン'}[status];}
function variantSpecies(sid,status){
 const base=sid.replace(/_shadow$/, '');
 const target=status==='shadow'?base+'_shadow':base;
 if(status==='purified'&&!catalog[base+'_shadow'])throw Error((catalog[sid]?.name_ja||sid)+'：リトレーン可能なシャドウのデータがありません。全体の変更を中止しました。');
 if(!catalog[target])throw Error((catalog[sid]?.name_ja||sid)+'：'+statusLabel(status)+'のデータがありません。全体の変更を中止しました。');
 return target;
}
function statusJob(job,status){
 const target=variantSpecies(job.candidate.species,status),p=catalog[target];
 let candidate={...job.candidate,species:target};
 const valid=c=>p.fastMoves.includes(c.fast)&&p.chargedMoves.includes(c.charged1)&&p.chargedMoves.includes(c.charged2)&&c.charged1!==c.charged2;
 let warnings=[...(job.warnings||[])];
 if(!valid(candidate)){
  const fallback=p.default_moves||presets.find(x=>x.species===target);
  if(!fallback||!valid(fallback))throw Error((p.name_ja||target)+'：変更先の技構成を確認できません。全体の変更を中止しました。');
  candidate={...candidate,fast:fallback.fast,charged1:fallback.charged1,charged2:fallback.charged2};
  warnings.push('区分変更に伴い技を変更：'+[candidate.fast,candidate.charged1,candidate.charged2].join(' / '));
 }
 const records=(job.source_records||[]).map(r=>({...r,species:variantSpecies(r.species,status),search_string:statusSearch(r.search_string,status)}));
 return {...job,candidate,name:(p.name_ja||p.name||target)+'［'+statusLabel(status)+'］',pokemon_status:status,source_records:records,warnings};
}
function applyBulkStatus(status){
 if(active)return;
 try{
  if(batchState||runRef)throw Error('再開待ちの計算があります。再開して完了してから区分を変更してください。');
  const current=currentCandidate();
  const keep=importedSingle?.candidate.species===current.species&&importedSingle.ivs.trim()===el('ivs').value.trim();
  const jobs=importedJobs||[{...(keep?importedSingle:{}),candidate:current,ivs:el('ivs').value,candidate_count:el('ivs').value.split('\n').filter(x=>x.trim()).length,warnings:keep?importedSingle.warnings:[],source_records:keep?importedSingle.source_records:[]}];
  const next=jobs.map(job=>statusJob(job,status));
  bulkStatusUndo={jobs:JSON.parse(JSON.stringify(jobs)),status:inputPokemonStatus};
  setCandidate(next[0].candidate);el('ivs').value=next[0].ivs;setImportedJobs(next);inputPokemonStatus=status;
  el('bulkStatusUndo').hidden=false;el('results').hidden=true;
  el('bulkStatusNote').textContent=next.length+'種類を'+statusLabel(status)+'に変更しました。個体値・CPはそのままです。変更後に再計算してください。';
  message(el('bulkStatusNote').textContent+next.flatMap(j=>j.warnings).filter(x=>x.startsWith('区分変更')).map(x=>'\n'+x).join(''));
 }catch(e){message(e.message,true);}
}
el('bulkNormal').onclick=()=>applyBulkStatus('normal');
el('bulkShadow').onclick=()=>applyBulkStatus('shadow');
el('bulkPurified').onclick=()=>applyBulkStatus('purified');
el('bulkStatusUndo').onclick=()=>{
 if(active||!bulkStatusUndo)return;
 if(batchState||runRef){message('再開待ちの計算を完了してから元に戻してください。',true);return;}
 const old=bulkStatusUndo;
 setCandidate(old.jobs[0].candidate);el('ivs').value=old.jobs[0].ivs;setImportedJobs(old.jobs);inputPokemonStatus=old.status;
 bulkStatusUndo=null;el('bulkStatusUndo').hidden=true;el('results').hidden=true;el('bulkStatusNote').textContent='直前の区分変更を元に戻しました。';message(el('bulkStatusNote').textContent);
};

function cacheBatch(){try{sessionStorage.setItem('pvpoke-app-batch',JSON.stringify(batchState));}catch{message('再開情報を保存できませんでした。計算が終わるまで画面を開いておいてください。',true);}}
function setImportedJobs(jobs){importedSingle=jobs?.length===1?jobs[0]:null;importedJobs=jobs&&jobs.length>1?jobs:null;el('queuePanel').hidden=!importedJobs;for(const id of ['preset','allSpecies','species','fast','charged1','charged2','ivs'])el(id).disabled=!!importedJobs;if(importedJobs)el('queuePreview').textContent=jobs.map((j,i)=>(i+1)+'. '+j.name+'：'+j.candidate_count+'個体\n   '+[j.candidate.fast,j.candidate.charged1,j.candidate.charged2].join(' / ')+'\n'+j.warnings.join('\n')).join('\n\n');}
async function finish(result){while(result.state==='running'){message('全対面を計算中です。'+(batchState?' '+(batchState.index+1)+' / '+batchState.jobs.length+'構成':''));result=await api('result',{run_ref:runRef,wait_seconds:12});}if(result.state!=='done'||!result.complete)throw Error(result.message||'計算が完了していません。');return result;}
// Exhaustive legal combinations. Freeze the full plan before starting one worker.
function planMovesets(jobs){
 const planned=[];
 jobs.forEach((job,group)=>{
  const p=catalog[job.candidate.species],fast=[...new Set(p?.fastMoves||[])].sort(),charged=[...new Set(p?.chargedMoves||[])].sort();
  if(!fast.length||charged.length<2)throw Error(job.name+'の合法な技一覧が不足しています。技の設定で直接指定してください。');
  const profiles=[];
  for(const f of fast)for(let i=0;i<charged.length;i++)for(let j=i+1;j<charged.length;j++)profiles.push({species:job.candidate.species,fast:f,charged1:charged[i],charged2:charged[j]});
  // Default first is an execution order only, never a strength estimate.
  const key=c=>[c.fast,...[c.charged1,c.charged2].sort()].join('|'),preferred=key(job.candidate);
  profiles.sort((a,b)=>Number(key(b)===preferred)-Number(key(a)===preferred));
  for(const candidate of profiles)planned.push({...job,candidate,moveset_group:group});
 });
 return planned;
}
function moveLabel(c){return [c.fast,c.charged1,c.charged2].map(id=>moveCatalog[id]?.name||id).join(' / ');}
function moveAliases(c){
 const p=catalog[c.species]||{},ids=[...new Set([...(p.fastMoves||[]),...(p.chargedMoves||[]),c.fast,c.charged1,c.charged2])].sort();
 const preferred={SCRATCH:'Sc',THUNDER_PUNCH:'TP',ICE_PUNCH:'IP',SWIFT:'Sw',HIGH_HORSEPOWER:'HH'};
 const codes={},used=new Set();
 // Reserve recognizable codes before assigning alternatives, case-insensitively.
 for(const id of ids.filter(x=>preferred[x])){codes[id]=preferred[id];used.add(preferred[id].toLowerCase());}
 for(const id of ids.filter(x=>!preferred[x])){
  const words=id.split('_'),suggested=words.length>1?words[0][0]+words[1][0]:id.slice(0,2);
  const choices=[suggested];
  for(let n=0;n<1296;n++)choices.push(n.toString(36).padStart(2,'0').toUpperCase());
  const code=choices.find(x=>/^[A-Za-z0-9]{2}$/.test(x)&&!used.has(x.toLowerCase()));
  if(!code)throw Error('技の略号を作成できません');codes[id]=code;used.add(code.toLowerCase());
 }
 return codes;
}
function movesetNickname(members){
 // One physical IV shared by evolutions keeps the first target's adopted build.
 const primary=members.find(m=>m.row.chosen_moves),c=primary.row.chosen_moves,aliases=moveAliases(c);
 const ids=[c.fast,c.charged1,c.charged2],suffix=ids.map(id=>aliases[id]).join('');
 const grade=String(primary.row.grade||'').startsWith('S')?'S':'A';
 for(const width of [4,3,2])for(const code of codeChoices(primary.sid,width)){
  const text=grade+code+suffix;
  if(validNickname(text))return {text,description:grade+'＝候補評価 / '+code+'＝'+(catalog[primary.sid]?.name_ja||primary.sid)+' / '+ids.map(id=>aliases[id]+'＝'+(moveCatalog[id]?.name||id)).join(' / ')+' / 個体別平均Rating '+primary.row.moveset_mean.toFixed(1)+(members.length>1?' / 共通個体：'+members.map(m=>catalog[m.sid]?.name_ja||m.sid).join('、')+'（技略号は最初の進化先）':'')};
 }
 return null;
}
function combineMovesets(results,threshold){
 const summaries=results.map(r=>r.selection?.moveset_summary),first=summaries[0];
 if(results.some(r=>r.meta_sha256!==results[0].meta_sha256||r.calculation_version!==results[0].calculation_version||r.batch_mode!==results[0].batch_mode||r.candidate.species!==results[0].candidate.species)||!first||summaries.some(s=>!s||s.version!==1||s.axis_sha256!==first.axis_sha256||s.available_wins.length!==first.available_wins.length||!Number.isFinite(s.mean_rating)))throw Error('技の比較条件が一致しません。同じメタ・条件で再計算してください。');
 const counts=Array.from(first.available_wins,(_,i)=>summaries.reduce((n,s)=>n+Number(s.available_wins[i]==='1'),0));
 const best=Math.max(...summaries.map(s=>s.mean_rating));
 const profiles=results.map((r,i)=>({candidate:r.candidate,mean_rating:summaries[i].mean_rating,
  unique_win_count:counts.filter((n,k)=>n===1&&summaries[i].available_wins[k]==='1').length,
  retained:summaries[i].mean_rating>=threshold||summaries[i].mean_rating===best||counts.some((n,k)=>n===1&&summaries[i].available_wins[k]==='1')}));
 const chosen=new Map();
 results.forEach((result,i)=>{
  if(!profiles[i].retained)return;
  for(const row of result.selection.recommendations)for(const item of [row,...(row.equivalent_candidates||[])]){
   const mean=summaries[i].iv_mean_ratings[item.ivs];
   if(!Number.isFinite(mean))throw Error('個体別Ratingが不足しています。再計算してください。');
   const previous=chosen.get(item.ivs);
   if(previous&&previous.moveset_mean>=mean)continue;
   // Equivalence is specific to one profile. Never reuse it across configurations.
   chosen.set(item.ivs,{...row,ivs:item.ivs,search_string:item.search_string,equivalent_candidates:[],chosen_moves:result.candidate,moveset_mean:mean,comparison_peer:null,comparison_differences:[],comparison_difference_count:0});
  }
 });
 const rows=[...chosen.values()].sort((a,b)=>Number(String(b.grade).startsWith('S'))-Number(String(a.grade).startsWith('S'))||b.moveset_mean-a.moveset_mean||a.ivs.localeCompare(b.ivs));
 rows.forEach((r,i)=>r.rank=i+1);
 const bestIndex=summaries.findIndex(s=>s.mean_rating===best),base=results[bestIndex];
 const candidateIvs=base.selection.candidate_ivs||Object.keys(first.iv_mean_ratings);
 const additional=candidateIvs.filter(iv=>!chosen.has(iv)).map(ivs=>({ivs,reason:'採用した技構成では保存候補に選ばれませんでした。',equivalent_candidates:[]}));
 return {...base,moveset_comparison:{threshold,profiles},selection:{...base.selection,
  recommendations:rows,review_candidates:[],additional_candidates:additional,covered_candidates:[],dominated_by:{},
  total_ratings_checked:summaries.reduce((n,s)=>n+s.rating_count,0)}};
}
function renderMovesetComparison(result,parent){
 const info=result.moveset_comparison,kept=info.profiles.filter(p=>p.retained);
 node('p',info.profiles.length+'構成を実測 / 採用 '+kept.length+'構成 / 平均Ratingの目安 '+info.threshold+'以上',parent,'note');
 const d=node('details','',parent);node('summary','技構成の比較を見る',d);
 for(const p of info.profiles)node('p',(p.retained?'採用｜':'参考｜')+moveLabel(p.candidate)+'｜平均 '+p.mean_rating.toFixed(1)+(p.unique_win_count?'｜この構成だけで勝てる対面条件 '+p.unique_win_count:'') ,d,'note');
}
function renderBatchResults(){
 if(!batchState?.auto_moves){batchState.results.forEach((r,i)=>render(r,i>0));return;}
 const completed=[];
 for(const group of [...new Set(batchState.jobs.map(j=>j.moveset_group))]){
  const jobs=batchState.jobs.filter(j=>j.moveset_group===group),results=batchState.results.filter(r=>r.moveset_group===group);
  if(results.length===jobs.length)completed.push(combineMovesets(results,batchState.move_threshold));
 }
 completed.forEach((r,i)=>render(r,i>0));
}

async function executeBatch(){
 for(;batchState.index<batchState.jobs.length;){
  const job=batchState.jobs[batchState.index];
  message(job.name+'｜'+moveLabel(job.candidate)+'（'+(batchState.index+1)+' / '+batchState.jobs.length+'構成）');
  let result;
  if(batchState.run_ref){runRef=batchState.run_ref;result=await api('result',{run_ref:runRef,wait_seconds:12});}
  else{
   const data={candidate:job.candidate,ivs:job.ivs,batch_mode:batchState.batch_mode,focus_opponents:batchState.focus,report_format:batchState.report_format,selection_policy:batchState.policy,force_recalculate:batchState.force_recalculate===true,wait_seconds:0};
   if(batchState.meta_sha256)data.expected_meta_sha256=batchState.meta_sha256;
   if(batchState.meta_preset_id)data.meta_preset_id=batchState.meta_preset_id;
   result=await api('run',data);runRef=result.run_ref;batchState.run_ref=runRef;
   sessionStorage.setItem('pvpoke-app-run',runRef);cacheBatch();
  }
  result=await finish(result);
  if(batchState.auto_moves){
   if(!/^[a-f0-9]{64}$/.test(result.calculation_version||''))throw Error('計算データの更新版を識別できません。全技比較をOFFにして直接指定するか、計算環境の設定を確認してください');
   if(batchState.calculation_version&&batchState.calculation_version!==result.calculation_version)throw Error('計算中にゲームデータまたは計算処理が更新されました。古い結果を混ぜず、新しく計算し直してください');
   batchState.calculation_version=result.calculation_version;
  }
  result.display_name=job.name;
  result.source_sections=job.source_sections||[];result.source_records=job.source_records||[];result.pokemon_status=job.pokemon_status;
  result.moveset_group=job.moveset_group;
  batchState.meta_sha256=result.meta_sha256;batchState.results.push(result);batchState.index++;
  batchState.run_ref=null;runRef=null;sessionStorage.removeItem('pvpoke-app-run');cacheBatch();
  renderBatchResults();
 }
 message(batchState.jobs.length+'構成すべての計算と推薦が完了しました。');
 sessionStorage.removeItem('pvpoke-app-batch');batchState=null;runRef=null;el('resume').hidden=true;
}
async function connect(auto=false){credential=auto?'':el('credential').value.trim();if(!auto&&!credential){message('接続キーを入力してください。',true);return;}el('connect').disabled=true;try{if(!auto&&el('remember').checked){await api('session');credential='';}const cat=await api('catalog');if(!cat.ready)throw Error(cat.error||'ゲームデータを読込中です。少し待って接続してください。');catalog=cat.species;moveCatalog=cat.moves||{};prepareLabels();presets=cat.app_presets||cat.presets;el('credential').value='';el('login').hidden=true;el('workspace').hidden=false;updateLowScorePanelVisibility();const opts=el('preset');opts.replaceChildren();const custom=document.createElement('option');custom.value='';custom.textContent='直接指定・貼り付け';opts.append(custom);for(const p of presets){const o=document.createElement('option');o.value=presetKey(p);o.textContent=p.name+' / '+p.fast+' / '+p.charged1+' / '+p.charged2;opts.append(o);}el('presetHint').textContent='登録済みの技構成 '+presets.length+'件。プリセット外も、全ポケモンの選択・CSV貼り付けから計算できます。';const speciesOptions=Object.keys(catalog).sort((a,b)=>(catalog[a].name_ja||catalog[a].name||a).localeCompare(catalog[b].name_ja||catalog[b].name||b,'ja'));el('allSpecies').replaceChildren();el('speciesList').replaceChildren();for(const sid of speciesOptions){const label=(catalog[sid].name_ja||catalog[sid].name||sid)+' ('+sid+')';const o=document.createElement('option');o.value=sid;o.textContent=label;el('allSpecies').append(o);const hint=document.createElement('option');hint.value=sid;hint.label=label;el('speciesList').append(hint);}const preferred=presets.find(p=>p.species==='quagsire'&&p.charged2==='STONE_EDGE')||presets[0];if(preferred)setCandidate(preferred);runRef=sessionStorage.getItem('pvpoke-app-run');try{batchState=JSON.parse(sessionStorage.getItem('pvpoke-app-batch')||'null');}catch{batchState=null;}if(batchState?.jobs){const jobs=batchState.auto_moves?batchState.jobs.filter((j,i,a)=>a.findIndex(x=>x.moveset_group===j.moveset_group)===i):batchState.jobs;setImportedJobs(jobs);if(batchState.auto_moves!==undefined)el('autoMoves').checked=batchState.auto_moves;if(batchState.move_threshold!==undefined)el('moveThreshold').value=batchState.move_threshold;}if(batchState?.results?.length)renderBatchResults();el('resume').hidden=!(runRef||batchState);message('接続できました。');if(new URLSearchParams(location.search||'').get('tool')==='low-score'){el('lowScorePanel').scrollIntoView?.();await loadLowScores();}await refreshMetaStatus(true);await autoImportReader();}catch(e){credential='';if(!auto||e.status!==401)message(e.message,true);}finally{el('connect').disabled=false;}}
el('connect').onclick=()=>connect(false);
el('preset').onchange=()=>{bulkStatusUndo=null;el('bulkStatusUndo').hidden=true;setPreset();};el('species').onchange=()=>{inputPokemonStatus=null;bulkStatusUndo=null;el('bulkStatusUndo').hidden=true;resolveTypedSpecies();el('allSpecies').value=el('species').value;el('preset').value='';moves();};
el('allSpecies').onchange=()=>{inputPokemonStatus=null;bulkStatusUndo=null;el('bulkStatusUndo').hidden=true;el('species').value=el('allSpecies').value;el('preset').value='';moves();};
el('singleForm').onclick=()=>{if(!active){inputPokemonStatus=null;bulkStatusUndo=null;el('bulkStatusUndo').hidden=true;setImportedJobs(null);message('単一種のフォームに切り替えました。貼り付けた元の入力は上の欄に残っています。');}};
async function importInput(){
 if(active)return false;
 setBusy(true);
 try{
  const parsed=await api('import',{text:el('importText').value,current:currentCandidate()});
  const jobs=parsed.jobs||[parsed];
  if(!jobs.length)throw Error('取り込む個体値がありません');
  setCandidate(jobs[0].candidate);el('ivs').value=jobs[0].ivs;
  if(parsed.batch_mode)el('batchMode').value=parsed.batch_mode;
  setImportedJobs(jobs);bulkStatusUndo=null;el('bulkStatusUndo').hidden=true;
  message(jobs.map(j=>j.name+'：'+j.candidate_count+'個体'+(j.warnings?.length?'\n'+j.warnings.join('\n'):'')).join('\n')+'\n取り込みました。メタを確認して計算してください。');
  el('comparisonSettings').scrollIntoView?.({block:'start'});el('comparisonSettings').focus?.({preventScroll:true});
  return true;
 }catch(e){message(e.message,true);return false;}finally{setBusy(false);}
}
async function autoImportReader(){
 if(!readerImportPending||readerImportInFlight||active||el('workspace').hidden)return;
 readerImportPending=false;readerImportInFlight=true;
 try{el('importText').value=readerInputText;await importInput();}finally{readerImportInFlight=false;if(readerImportPending)Promise.resolve().then(autoImportReader);}
}
el('importInput').onclick=importInput;
el('evaluation').onchange=()=>{el('run').textContent=el('evaluation').value==='app'?'計算して推薦を表示':'GPT評価用の比較情報を作成';};
el('run').onclick=async()=>{if(active||metaWorking)return;if(!chosenMeta()){message('メタプリセットを選択してください。',true);return;}setBusy(true);el('results').hidden=true;try{const current=currentCandidate();const keep=importedSingle?.candidate.species===current.species&&importedSingle.ivs.trim()===el('ivs').value.trim();const inputJobs=importedJobs||[{candidate:current,ivs:el('ivs').value,name:catalog[el('species').value]?.name_ja||el('species').value,source_records:keep?importedSingle.source_records:[],source_sections:keep?importedSingle.source_sections:[],pokemon_status:inputPokemonStatus}];const auto_moves=el('autoMoves').checked===true;const threshold=Number(el('moveThreshold').value);if(auto_moves&&(!Number.isFinite(threshold)||threshold<0||threshold>1000))throw Error('技の平均Rating下限は0〜1000で指定してください');if(auto_moves&&el('evaluation').value!=='app')throw Error('全技比較は「アプリで自動推薦」で使用してください');const jobs=auto_moves?planMovesets(inputJobs):inputJobs;batchState={jobs,auto_moves,move_threshold:threshold,index:0,results:[],run_ref:null,meta_preset_id:selectedMetaId,meta_sha256:chosenMeta().sha256,batch_mode:el('batchMode').value,focus:el('focus').value.split('\n').map(x=>x.trim()).filter(Boolean),report_format:el('evaluation').value==='app'?'app':'decision',force_recalculate:el('forceRecalculate').checked===true,policy:{meaningful_win_lead:Number(el('lead').value)}};cacheBatch();await executeBatch();}catch(e){if(batchState&&!batchState.results.length&&!batchState.run_ref){batchState=null;sessionStorage.removeItem('pvpoke-app-batch');}message(e.message+'\n完了済みの結果は表示を保持しています。後続の対象は未実行です。',true);el('resume').hidden=!(runRef||batchState);}finally{setBusy(false);}};
el('resume').onclick=async()=>{if(active||!(runRef||batchState))return;setBusy(true);try{if(batchState){await executeBatch();}else{render(await finish(await api('result',{run_ref:runRef,wait_seconds:12})));runRef=null;sessionStorage.removeItem('pvpoke-app-run');el('resume').hidden=true;message('計算と結果の確認が完了しました。');}}catch(e){message(e.message,true);}finally{setBusy(false);}};
el('disconnect').onclick=async()=>{try{await api('logout');}catch(e){message('ログアウトできませんでした。再試行してください。',true);return;}credential='';catalog={};metaState=null;selectedMetaId=null;clearMetaExport();nameEntries=[];opponentLabels.clear();displayedResults=[];nicknameBindings=[];presets=[];lastResult=null;setImportedJobs(null);batchState=null;el('results').replaceChildren();el('workspace').hidden=true;el('login').hidden=false;resetMetaUpload();message('接続を解除しました。このブラウザのログイン情報も削除しました。');};
// Reader-to-browser handoff is kept in a URL fragment, never sent in an HTTP request.
function receiveReaderInput(){
 const params=new URLSearchParams(location.hash.slice(1));
 const encoded=params.get('ivdata');
 if(!encoded)return false;
 // Remove imported data from the address bar before parsing or showing it.
 history.replaceState(null,'',location.pathname+location.search);
 try{
  if(encoded.length>512000||!/^[A-Za-z0-9_-]+$/.test(encoded))throw Error('Invalid payload');
  const pad='='.repeat((4-encoded.length%4)%4);
  const bytes=Uint8Array.from(atob(encoded.replace(/-/g,'+').replace(/_/g,'/')+pad),c=>c.charCodeAt(0));
  const value=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
  if(bytes.length>384000||!value.startsWith('個体値厳選')||!/(?:^|\n)#\s*\S/.test(value))throw Error('Invalid IV input');
  readerInputText=value;readerImportPending=true;
  if(!active)el('importText').value=value;
  message('読み取りアプリから個体値を受け取りました。接続後に取り込み、比較と推薦の設定へ移動します。');
  return true;
 }catch(e){message('読み取りデータを自動入力できませんでした。コピーした内容を手動で貼り付けてください。',true);return false;}
}
const access=new URLSearchParams(location.hash.slice(1)).get('access');
if(access){history.replaceState(null,'',location.pathname+location.search);el('credential').value=access;connect(false);}else{receiveReaderInput();connect(true);}
if(typeof window!=='undefined')window.addEventListener('hashchange',()=>{if(receiveReaderInput())autoImportReader();});
</script></body></html>'''



