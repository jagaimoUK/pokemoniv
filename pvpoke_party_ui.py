"""Mobile-first Party Builder page, protected by the existing app session."""
HTML = r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>パーティ作成</title><style>
:root{font:16px system-ui,sans-serif;background:#122126;color:#e2f1e9;color-scheme:dark}*{box-sizing:border-box}
body{margin:0}main{max-width:1040px;margin:auto;padding:16px 14px 110px}h1{margin:9px 0}h2{font-size:19px;margin:0 0 12px}h3{font-size:16px}
p{line-height:1.65;color:#b6cac4}a{color:#bbebd4}
section{margin-top:15px;padding:17px;border:1px solid #47645d;border-radius:20px;background:#203138}
nav,.tools,.tabs{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
button,nav a{border:1px solid #76a797;border-radius:16px;min-height:48px;padding:11px 15px;background:#385c50;color:#edf8f1;font:inherit;cursor:pointer;text-decoration:none}
button:disabled{opacity:.45}input,select,textarea{width:100%;border:1px solid #67887d;border-radius:12px;padding:11px;min-height:45px;background:#12252b;color:inherit;font:inherit}
input[type=checkbox]{width:auto;min-height:unset}label{font-size:13px;display:block;margin:10px 0 5px}
textarea{min-height:95px;resize:vertical}summary{cursor:pointer;min-height:44px;padding:10px 0;font-weight:bold}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.suggestions{display:flex;flex-direction:column;gap:6px;margin-top:6px;max-height:260px;overflow:auto}.suggestions button{text-align:left;width:100%;font-size:13px}.mon{padding:10px;border-radius:16px;background:#29413f;border:1px solid #557769}
.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.fields label:first-child{grid-column:1/-1}
.tabs{margin:14px 0}.tabs button[aria-pressed=true]{background:#638b72}section[hidden],div[hidden]{display:none}
#status{white-space:pre-wrap;border-radius:14px;background:#2a4140;padding:12px;overflow-wrap:anywhere}
#swapAdvice,#weakResult,#selectionResult{scroll-margin-top:16px}
#metaWeights{display:flex;flex-direction:column;gap:7px;margin-top:10px}
.weight-row{display:flex;gap:12px;align-items:center;justify-content:space-between;border:1px solid #4c6a5f;border-radius:14px;padding:8px 10px;background:#2a4140}
.weight-row span{flex:1;min-width:0;overflow-wrap:anywhere}
.weight-row select{width:115px;flex:0 0 115px;min-height:44px}
.weight-row small{display:block;color:#abc8bd;font-size:11px;margin-top:3px}
#metaWeightStatus{font-size:13px;margin-top:8px}
#metaFilter{margin-top:5px}
footer{position:fixed;bottom:0;left:0;right:0;background:#172d2cf5;border-top:1px solid #638276;padding:10px}
footer .tools{max-width:700px;margin:auto}footer button{flex:1}
.result{padding-top:10px;border-top:1px solid #557769;margin-top:10px}li{padding:4px 0}
.completion-card{padding:12px;margin:10px 0;border:1px solid #6a9586;border-radius:16px;background:#29413f}
.heat-scroll{overflow-x:auto;max-width:100%;margin:12px 0}
.heatmap{border-collapse:separate;border-spacing:3px;text-align:center;font-size:12px;width:100%}
.heatmap th{padding:7px 3px;min-width:51px;max-width:95px;overflow-wrap:anywhere}
.heatmap th:first-child{min-width:95px;position:sticky;left:0;background:#203138;z-index:1;text-align:left}
.heatmap td{white-space:pre-line;font-variant-numeric:tabular-nums;padding:8px 2px;border-radius:8px}
.heat-win{background:#236e96;color:#fff}.heat-mid{background:#85819e;color:#fff}.heat-loss{background:#953276;color:#fff}.heat-unknown{background:#52615d;color:#fff}
@media(max-width:550px){main{padding:12px 10px 110px}section{padding:12px}.mon{padding:8px}.fields{grid-template-columns:1fr}}
</style></head><body><main><nav><a href="/app">← 個体値厳選</a><a href="/flashcards">フラッシュカード</a></nav>
<h1>見せ合い6体・選出3体</h1><p>重要メタへの穴、15ペアの補完、20組の3体、相手6体への選出を分析するにぇ。Battle Ratingは実戦勝率ではありません。</p>
<section id="auth"><h2>アプリに接続</h2><p>ログイン済みのブラウザでは自動接続します。</p><div class="tools"><input id="key" type="password" autocomplete="off" placeholder="接続キー"><button id="login">接続する</button></div></section>
<div id="workspace" hidden>
<section id="partyLibrary"><details open><summary>パーティを保存・切り替え</summary>
<p>自分6体と相手6体、技・個体値、詳細戦略の相手と条件をパーティごとに保存できます。保存済みは最大32件です。</p>
<label for="partyName">パーティ名</label><input id="partyName" value="新しいパーティ" maxlength="60">
<p id="partyState" role="status">新規パーティ（未保存）</p>
<div class="tools"><button id="save">保存・上書き</button><button id="saveAs">別パーティとして保存</button></div>
<label for="saved">保存済みのパーティ</label><select id="saved"><option value="">読み込むパーティを選ぶ</option></select>
<button id="load">選んだパーティを読み込む</button>
</details></section>
<div class="tabs"><button data-tab="compose" aria-pressed="true">構築</button><button data-tab="weakness">弱点・補完</button><button data-tab="selection">相手と選出</button><button data-tab="strategy">詳細戦略</button><button data-tab="settings">保存・設定</button></div>
<div id="compose"><section><h2>自分の6体</h2><p>各枠をタップして技と個体値を編集。IV省略時はPvPoke標準値を使用します。CP1500/Lv50・同一図鑑番号は1枠。</p><div class="grid" id="members"></div></section>
<section><h2>自動構築</h2><p>名前から候補を追加します。固定枠を残して最大48候補から探索します。</p>
<textarea id="pool" placeholder="azumarill,BUBBLE,ICE_BEAM,PLAY_ROUGH,0,15,15"></textarea>
<div class="tools"><button id="autoComplete">自動補完を最後まで実行</button><button id="recommend">1体だけ入れ替え候補を探す</button><button id="build">候補から6体を提案</button></div>
<p>自動補完は最大10回の1体交換を繰り返し探索し、最大3案と相性表を表示します。改善が止まっても全対面への完全対応は保証しません。候補欄が空ならメタから最大24種の仮候補を利用（所持・技・IVの確認が必要）。追加探索はシールド2-2の静的比較です。</p></section></div>
<div id="weakness" hidden><section><h2>弱点・補完</h2><div id="swapAdvice"></div><div id="weakResult">分析後に表示します。</div></section></div>
<div id="selection" hidden><section><h2>相手6体</h2><p>名前から選ぶと推奨技が入ります。技をタップして変更できます。</p><textarea id="enemy" placeholder="clodsire,POISON_STING,STONE_EDGE,EARTHQUAKE"></textarea><button id="select">相手6体への選出を比較</button>
<p>双方ともチーム全体のシールドは2枚。静的な近似であり、実際の3対3勝率ではありません。</p><div id="selectionResult"></div></section></div>
<div id="strategy" hidden>
<section><h2>詳細戦略の結果</h2><div id="strategyResult" aria-live="polite">対象と条件を指定して計算してください。未計算はunknownです。</div></section>
<section id="strategyConfig"><h2>比較する対面</h2><p>自分の6体は「構築」で指定。相手は名前から1体または6体を追加できます。通常技限定・受け後の仕事・シールド方針を一度に比較します。</p>
<label for="strategyEnemy">相手のポケモン</label><textarea id="strategyEnemy" placeholder="clodsire,POISON_STING,STONE_EDGE,EARTHQUAKE"></textarea>
<button id="copyEnemy">相手と選出の入力を使う</button><div class="fields">
<label>対象の自分（後追い分岐では引き先）<select id="strategySelf"></select></label>
<label>対象の相手（分岐では相手初手）<select id="strategyOpponent"></select></label></div>
<details open><summary>受けた後に果たす仕事</summary><p>自分シールド0枚・開始HP100%と75%・相手2枚。相手の最初のゲージ技が当たった後の行動だけを数えます。</p>
<label>計算前に固定する条件<select id="workKind"><option value="charged">指定ゲージ技を撃つ</option><option value="fast_damage">通常技で指定割合を削る</option><option value="force_shield">相手のシールドを使わせる</option></select></label>
<label>指定するゲージ技<select id="workMove"></select></label>
<label>通常技で削る相手最大HPの割合（%）<input id="workFraction" type="number" min="1" max="100" value="15"></label></details>
<details><summary>シールドとブラフの詳細</summary><p>標準・ブラフ有無の4条件・観測温存・手動を別々に比較。通常技限定以外は双方が通常の攻撃方針です。</p>
<label>相手の技構成<select id="publicMoves"><option value="1">公開チームシート（指定技が既知）</option><option value="0">非公開（公開習得技と観測履歴で判断）</option></select></label>
<div class="fields"><label>温存・手動時の自分ブラフ<select id="selfBait"><option value="1">選択的に使う</option><option value="0">使わない</option></select></label><label>温存・手動時の相手ブラフ<select id="opponentBait"><option value="1">選択的に使う</option><option value="0">使わない</option></select></label></div>
<p>観測温存：可能な技のダメージ上限がHPの危険閾値以上なら貼る。それ以外は初回を受け、2回目以降は温存枚数を超え、HPの半分以上の被害があり得る場合に貼ります。危険時は温存枚数より生存を優先。ダメージ上限は公開種族値からの保守的な上界で、実測確率は使いません。</p>
<div class="fields"><label>危険閾値（現在HPに対する比率）<input id="dangerRatio" type="number" min="0.5" max="1" step="0.05" value="0.95"></label><label>平常時に温存する枚数<input id="reserve" type="number" min="0" max="2" value="1"></label></div>
<label>自分の手動方針（受ける=0、貼る=1、相手ゲージ技の順）<input id="manualSelf" value="0,1,0,1"></label><label>相手の手動方針<input id="manualOpponent" value="0,1,0,1"></label><p>指定が尽きた後は受けます。攻撃技の正体を見る前に決める方針です。</p></details>
<details><summary>初手→交代→後追い（限定モデル）</summary>
<label><input id="includeBranch" type="checkbox"> 相手6体の合法な後追い候補を計算する</label>
<div class="fields"><label>自分の初手<select id="strategyLead"></select></label><label>残り1体<select id="strategyCloser"></select></label><label>初手の経過ターン（最短）<input id="leadTurns" type="number" min="0" max="12" value="2"></label><label>相手の後追い遅延ターン（最短）<input id="chaseDelay" type="number" min="0" max="12" value="2"></label></div>
<p>双方合計2枚から消費を引き継ぎます。交代に1ターンを使い、未処理の通常技がなくなる境界まで待つため、実際の遅延も結果に表示します。次の交代・引き直し・残り2体の実対戦はunknown。完全な3対3ではありません。</p></details>
<button id="runStrategy">詳細条件を比較する</button></section></div>
<div id="settings" hidden><section><h2>分析条件</h2><label for="meta">メタプリセット</label><select id="meta"></select>
<p>パーティの保存・切り替えは画面上部から操作できます。</p>
<h3>メタポケモン別の重要度</h3>
<p>選択したメタに登録されているポケモンを表示します。同じポケモンの技違いはまとめて扱い、値1が標準・0は評価対象外・大きいほど重視します。</p>
<label for="metaFilter">ポケモンを絞り込む（日本語・英語）</label><input id="metaFilter" type="search" placeholder="例：ドオー、Clodsire">
<p id="metaWeightStatus" role="status">メタのポケモン一覧を読み込みます。</p>
<div id="metaWeights" aria-label="メタポケモン別の重要度"></div>
<p id="metaWeightSaveStatus" role="status"></p>
<p>重要度はポケモンごとに自動保存し、別のメタや再読み込み後も引き継ぎます。パーティ保存時には現在の値も記録します。詳細戦略では重要度は使用しません。メタは最大500技構成に対応します。</p></section></div>
<section><h2>計算状況と結果</h2><div id="status" role="status" aria-live="polite">接続を確認しています。</div><div id="result"></div></section>
</div></main><footer><div class="tools"><button id="analyze" disabled>6体を分析</button><button id="cancel" disabled>計算を中止</button></div></footer>
<datalist id="speciesList"></datalist><script>
'use strict';
const $=id=>document.getElementById(id);
let key='',catalog={},metaItems=[],partyId=null,revision=0,activeJob=null,latest=null,inputRevision=0,lastReportRevision=-1,currentTab='compose';
const name=id=>partyDisplay(id);
let partyMoveNames={},rosterEditors={};
let metaWeightRows=[],metaWeightValues={},metaWeightCache=new Map(),metaWeightTicket=0,metaWeightReady=false;
let metaWeightDefaults={},pendingMetaWeights={},metaWeightSaving=null,metaWeightSaveTimer;
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n}
function status(text){$('status').textContent=text}
function tab(target){currentTab=target;$('analyze').textContent=target==='strategy'?'詳細条件を比較':'6体を分析';if(target==='strategy')strategyTargets();['compose','weakness','selection','strategy','settings'].forEach(id=>$(id).hidden=id!==target);document.querySelectorAll('[data-tab]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.tab===target)))}
document.querySelectorAll('[data-tab]').forEach(x=>x.onclick=()=>tab(x.dataset.tab));
async function api(path,body={}){
 const h={'Content-Type':'application/json'};if(key)h.Authorization='Bearer '+key;
 const r=await fetch('/app-api/'+path,{method:'POST',headers:h,body:JSON.stringify(body),credentials:'same-origin'});
 const data=await r.json().catch(()=>({error:'サーバー応答を読み取れません'}));if(!r.ok)throw Error(data.error||'HTTP '+r.status);return data;
}
/*PARTY_INPUT*/
function renderMon(rows=[]){$('members').replaceChildren();for(let i=0;i<6;i++)$('members').append(createMon(rows[i]||{}))}
function getMon(){return [...$('members').children].map(readPartyCard)}
function locks(){return [...$('members').children].flatMap((box,i)=>box.querySelector('[data-field=locked]').checked?[i]:[])}
function normalizeMetaId(value){
 const s=String(value||'').trim().toLowerCase();
 return s.endsWith('_shadow-shadow')?s.slice(0,-7):s;
}
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
function restoreMetaWeightValues(saved){
 metaWeightValues={...metaWeightDefaults};
 for(const [key,value] of Object.entries(saved||{})){
  const id=catalog[key]?key:(()=>{try{return resolvePartyName(key)}catch(_){return key}})();
  if(typeof value==='number'&&Number.isFinite(value)&&value>=0)metaWeightValues[id]=value;
 }
}
function renderMetaWeightRows(){
 const root=$('metaWeights');root.replaceChildren();
 if(!metaWeightReady){$('metaWeightStatus').textContent='メタのポケモン一覧を確認できません。設定を再読み込みしてください。';return;}
 const query=normalizePartyName($('metaFilter').value),filtered=metaWeightRows.filter(id=>!query||
  [id,catalog[id]?.name,catalog[id]?.name_ja,...(catalog[id]?.aliases||[])]
   .some(x=>x&&normalizePartyName(x).includes(query)));
 $('metaWeightStatus').textContent='メタ登録 '+metaWeightRows.length+'種 / 表示 '+filtered.length+'種。重要度は各ポケモンのメニューで変更できます。';
 if(!filtered.length){root.append(node('p','一致するポケモンはありません'));return;}
 for(const id of filtered){
  const div=node('div',null,'weight-row'),span=node('span'),ja=node('strong',partyDisplay(id));
  const english=node('small',catalog[id]?.name||id);span.append(ja,english);
  const select=node('select');select.dataset.species=id;select.setAttribute('aria-label',partyDisplay(id)+' の重要度');
  let options=[0,1,2,3,4,5,10,20],value=metaWeightValues[id]??1;
  if(!options.includes(value))options=[...options,value].sort((a,b)=>a-b);
  for(const n of options)select.append(new Option(n===0?'0（対象外）':n===1?'1（標準）':String(n)+'（重視）',String(n)));
  select.value=String(value);
  select.onchange=()=>{
   const value=Number(select.value);metaWeightValues[id]=value;pendingMetaWeights[id]=value;inputRevision++;
   $('metaWeightSaveStatus').textContent='重要度を自動保存中…';
   clearTimeout(metaWeightSaveTimer);metaWeightSaveTimer=setTimeout(()=>flushMetaWeights().catch(()=>{}),250);
  };
  div.append(span,select);root.append(div);
 }
}
async function flushMetaWeights(){
 clearTimeout(metaWeightSaveTimer);
 if(metaWeightSaving){await metaWeightSaving;return flushMetaWeights();}
 if(!Object.keys(pendingMetaWeights).length)return;
 metaWeightSaving=(async()=>{
  while(Object.keys(pendingMetaWeights).length){
   const changes=pendingMetaWeights;pendingMetaWeights={};
   try{
    await api('party/meta-weights',{changes});Object.assign(metaWeightDefaults,changes);
    $('metaWeightSaveStatus').textContent='重要度を自動保存しました（別メタにも引き継ぎます）';
   }catch(e){
    pendingMetaWeights={...changes,...pendingMetaWeights};
    $('metaWeightSaveStatus').textContent='重要度の自動保存に失敗しました。次の変更・計算・パーティ保存時に再試行します: '+e.message;
    throw e;
   }
  }
 })();
 try{await metaWeightSaving}finally{metaWeightSaving=null;}
}
async function loadMetaWeightRows(){
 const selected=metaItems.find(x=>x.id===$('meta').value),ticket=++metaWeightTicket;
 metaWeightReady=false;metaWeightRows=[];$('metaWeights').replaceChildren();
 $('metaWeightStatus').textContent='メタ登録ポケモンを読み込み中…';
 if(!selected){$('metaWeightStatus').textContent='メタプリセットを選択してください';return;}
 const key=selected.id+'|'+selected.sha256;
 try{
  let rows=metaWeightCache.get(key);
  if(!rows){
   const data=await api('meta-preset-export',{id:selected.id,expected_sha256:selected.sha256});
   rows=parseMetaWeightRows(data.csv);metaWeightCache.set(key,rows);
  }
  if(ticket!==metaWeightTicket)return;
  metaWeightRows=rows;metaWeightReady=true;renderMetaWeightRows();
 }catch(e){
  if(ticket!==metaWeightTicket)return;
  $('metaWeightStatus').textContent='メタの一覧を取得できません: '+e.message;
  status('重要度一覧の読み込みに失敗: '+e.message);
 }
}
function getWeights(){
 if(!metaWeightReady)throw Error('メタの重要度一覧が準備できていません。メタプリセットを確認してください');
 const result={};
 for(const id of metaWeightRows){const value=metaWeightValues[id]??1;if(value!==1)result[id]=value;}
 if(metaWeightRows.every(id=>(metaWeightValues[id]??1)===0))throw Error('重要度がすべて0です。少なくとも1体を対象にしてください');
 return result;
}
$('meta').addEventListener('change',()=>{inputRevision++;loadMetaWeightRows()});
$('metaFilter').addEventListener('input',e=>{e.stopPropagation();renderMetaWeightRows()});
const pct=v=>(v*100).toFixed(1)+'%';
function label(id){const r=latest?.labels?.[id];return r?name(r.species)+' '+r.ivs.join('/')+' CP'+r.cp:id.slice(0,8)}
function addLine(parent,text){parent.append(node('p',text))}
function showReplacements(r){
 const root=$('swapAdvice');root.replaceChildren();root.append(node('h3','次に何をすればよい？'));
 const info=r.recommendations;
 if(!info){addLine(root,'まだ入れ替え候補は比較していません。候補を自動探索すると、改善した1体交換案と理由が表示されます。');
  const btn=node('button','入れ替え候補を探す');btn.onclick=()=>wrap('analyze',true);root.append(btn);return}
 const source=info.source==='registered'?'登録済みの候補から':info.source==='meta_provisional'?'メタプリセットから仮候補を抽出して':'';
 addLine(root,source+info.candidate_count+'体を比較。指標は同じメタに対する2-2の静的なBattle Ratingで、実戦勝率ではありません。');
 if(info.source==='meta_provisional')addLine(root,'仮候補は所持個体ではありません。実際に使う前に所持・技・IV・CPを確認してください。');
 if(info.status==='unknown'){addLine(root,'計算できない対面があるため入れ替えを断定できません。');return}
 if(!info.items?.length){addLine(root,'この候補集合では改善する1体交換がありません。候補を追加するか、メタや固定枠を見直してください。');return}
 const fmt=v=>(v*100).toFixed(1)+'%';
 for(const [i,item] of info.items.entries()){
  const el=node('div',null,'result');
  const old=r.labels[item.out],replacement=r.labels[item.in];if(!old||!replacement)continue;
  el.append(node('strong',(i+1)+'案: '+name(old.species)+' → '+name(replacement.species)+'（'+(item.slot+1)+'枠目）'));
  addLine(el,'D0 未対応: '+fmt(info.baseline.d0)+' → '+fmt(item.after.d0)+' / D1 担当1体のみ: '+fmt(info.baseline.d1)+' → '+fmt(item.after.d1));
  addLine(el,'深刻度: '+info.baseline.severity0.toFixed(3)+' → '+item.after.severity0.toFixed(3)+' / 補完度: '+fmt(info.baseline.coverage)+' → '+fmt(item.after.coverage));
  if(item.resolved.length)addLine(el,'新たに対応できる相手: '+item.resolved.map(x=>name(r.labels[x]?.species||x)).join('、'));
  if(item.new_holes.length)addLine(el,'注意: 新たな未対応相手 '+item.new_holes.map(x=>name(r.labels[x]?.species||x)).join('、'));
  addLine(el,'入れ替え先の仮構成: '+repl…3161 tokens truncated…,autoComplete=false){try{await run(mode,findSwaps,autoComplete)}catch(e){status(e.message);activeJob=null;$('cancel').disabled=true;$('analyze').disabled=false}}
$('analyze').onclick=()=>{if(currentTab==='strategy')strategyTargets();wrap(currentTab==='strategy'?'strategy':'analyze')};
$('recommend').onclick=()=>wrap('analyze',true);
$('autoComplete').onclick=()=>wrap('analyze',false,true);
$('build').onclick=()=>wrap('build');$('select').onclick=()=>wrap('select');
$('cancel').onclick=()=>activeJob&&api('party/cancel',{job_id:activeJob}).then(()=>status('中止要求を送信しました'));
function populateSaved(items,selected=partyId){$('saved').replaceChildren(new Option('読み込むパーティを選ぶ',''));items.forEach(x=>$('saved').append(new Option(x.name,x.id)));$('saved').value=selected||'';}
async function setup(){
 const [cat,presets,saved,defaults]=await Promise.all([api('catalog'),api('meta-presets'),api('party/list'),api('party/meta-weights')]);
 metaWeightDefaults=defaults.weights||{};restoreMetaWeightValues();
 if(!cat.ready)throw Error('ゲームデータがまだ準備中です');catalog=cat.species;partyMoveNames=cat.moves||{};metaItems=presets.items;
 for(const m of metaItems.filter(x=>x.available!==false)){let o=new Option(m.name+' ('+m.rows+'件)',m.id);$('meta').append(o)}$('meta').value=presets.default_id;
 populateSaved(saved.items);renderMon();await loadMetaWeightRows();if(!rosterEditors.enemy){rosterEditors.enemy=partyRosterEditor('enemy',6);rosterEditors.pool=partyRosterEditor('pool',48);rosterEditors.strategyEnemy=partyRosterEditor('strategyEnemy',6);}$('workspace').hidden=false;$('auth').hidden=true;$('analyze').disabled=false;status('6体を入力すると分析できます')}
$('login').onclick=async()=>{key=$('key').value.trim();try{await setup();if(key)await api('session',{}).catch(()=>{})}catch(e){$('workspace').hidden=false;status(e.message)}};
async function saveParty(asNew=false){try{
 await flushMetaWeights();
 const obj={id:asNew?null:partyId,revision:asNew?0:revision,name:$('partyName').value,members:getMon(),locked_slots:locks(),
  meta_preset_id:$('meta').value,meta_sha256:metaItems.find(x=>x.id===$('meta').value)?.sha256,group_weights:getWeights(),
  strategy:{...getStrategy(),enemy_csv:$('strategyEnemy').value},opponents:partyRosterRows('enemy'),candidate_pool:partyRosterRows('pool')};
 const r=await api('party/save',obj);partyId=r.id;revision=r.revision;
 $('partyState').textContent='保存中のパーティ: '+obj.name+'（revision '+revision+'）';
 status('保存済み。自分・相手・詳細戦略を記録しました。revision '+revision);
 try{populateSaved((await api('party/list')).items,partyId)}catch(e){status('保存は完了しましたが一覧の更新に失敗: '+e.message)}
}catch(e){status(e.message)}}
$('save').onclick=()=>saveParty(false);
$('saveAs').onclick=()=>saveParty(true);
$('load').onclick=async()=>{try{
 const id=$('saved').value;if(!id)throw Error('読み込むパーティを選んでください');
 const p=await api('party/get',{id});partyId=p.id;revision=p.revision;$('partyName').value=p.name;
 renderMon((p.members||[]).map((m,i)=>({...m,locked:(p.locked_slots||[]).includes(i)})));
 if(metaItems.some(x=>x.id===p.meta_preset_id))$('meta').value=p.meta_preset_id;
 restoreMetaWeightValues(p.group_weights);await loadMetaWeightRows();
 const csv=rows=>(rows||[]).map(x=>[x.species,x.fast,x.charged1,x.charged2,...(['atk','def','hp'].every(k=>k in x)?[x.atk,x.def,x.hp]:[])].join(',')).join('\n');
 $('enemy').value=csv(p.opponents);$('pool').value=csv(p.candidate_pool);
 rosterEditors.enemy.refresh(p.opponents||[]);rosterEditors.pool.refresh(p.candidate_pool||[]);
 restoreStrategy(p.strategy,csv(p.opponents));
 latest=null;lastReportRevision=-1;$('swapAdvice').replaceChildren();$('weakResult').replaceChildren();$('selectionResult').replaceChildren();
 $('strategyResult').replaceChildren();delete $('strategyResult').dataset.calculated;
 inputRevision++;$('partyState').textContent='保存中のパーティ: '+p.name+'（revision '+revision+'）';
 status('読み込みました。自分・相手・詳細戦略を復元しました')
}catch(e){status(e.message)}};
$('workspace').addEventListener('input',()=>{
 inputRevision++;
 const root=$('strategyResult');if(root.dataset.calculated&&!root.querySelector('[data-stale]')){const msg=node('p','入力が変更されています。以下は以前の条件の結果です。再計算してください。');msg.dataset.stale='true';root.prepend(msg)}
});
setup().catch(()=>{status('ログインが必要です。接続キーを入力してください。')});
/*STRATEGY_UI*/
</script></body></html>'''


from pathlib import Path
HTML = HTML.replace('/*STRATEGY_UI*/', Path(__file__).with_name('pvpoke_party_strategy_ui.js').read_text(encoding='utf-8'))

HTML = HTML.replace('/*PARTY_INPUT*/', Path(__file__).with_name('pvpoke_party_input.js').read_text(encoding='utf-8'))
