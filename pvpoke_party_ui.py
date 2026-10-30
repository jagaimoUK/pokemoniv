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
footer{position:fixed;bottom:0;left:0;right:0;background:#172d2cf5;border-top:1px solid #638276;padding:10px}
footer .tools{max-width:700px;margin:auto}footer button{flex:1}
.result{padding-top:10px;border-top:1px solid #557769;margin-top:10px}li{padding:4px 0}
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
<textarea id="pool" placeholder="azumarill,BUBBLE,ICE_BEAM,PLAY_ROUGH,0,15,15"></textarea><button id="build">候補から6体を提案</button></section></div>
<div id="weakness" hidden><section><h2>弱点・補完</h2><div id="weakResult">分析後に表示します。</div></section></div>
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
<label for="weights">重要度（種ID:数値を1行ずつ）</label><textarea id="weights" placeholder="clodsire:4"></textarea>
<p>技違いは同種内で重要度を分配します。詳細戦略は専用タブで条件を固定して比較します。</p></section></div>
<section><h2>計算状況と結果</h2><div id="status" role="status" aria-live="polite">接続を確認しています。</div><div id="result"></div></section>
</div></main><footer><div class="tools"><button id="analyze" disabled>6体を分析</button><button id="cancel" disabled>計算を中止</button></div></footer>
<datalist id="speciesList"></datalist><script>
'use strict';
const $=id=>document.getElementById(id);
let key='',catalog={},metaItems=[],partyId=null,revision=0,activeJob=null,latest=null,inputRevision=0,currentTab='compose';
const name=id=>partyDisplay(id);
let partyMoveNames={},rosterEditors={};
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
function getWeights(){const result={};for(const row of $('weights').value.split(/\r?\n/)){if(!row.trim())continue;const v=row.split(':');if(v.length!==2||!v[0].trim()||!Number.isFinite(Number(v[1]))||Number(v[1])<0)throw Error('重要度の形式が不正です');result[v[0].trim().toLowerCase()]=Number(v[1])}return result}
const pct=v=>(v*100).toFixed(1)+'%';
function label(id){const r=latest?.labels?.[id];return r?name(r.species)+' '+r.ivs.join('/')+' CP'+r.cp:id.slice(0,8)}
function addLine(parent,text){parent.append(node('p',text))}
function show(result){latest=result;
 if(result.search){const fixed=new Set(result.search.locked||[]);
 renderMon(result.roster.map(id=>{const p=result.labels[id];return {
 species:p.species,fast:p.moves[0],charged1:p.moves[1],charged2:p.moves[2],
 atk:p.ivs[0],def:p.ivs[1],hp:p.ivs[2],level_override:p.level,
 locked:fixed.has(id)}}));}
 let t=result.team;const root=$('weakResult');root.replaceChildren();
 root.append(node('h3','メタに対する6体の対応力'));
 addLine(root,'未対応 D0 '+pct(t.d0)+' / 担当1体 D1 '+pct(t.d1)+' / 深刻度 '+t.severity0.toFixed(3)+' / 未計算 '+pct(t.unknown_weight));
 root.append(node('h3','シールド条件別の未対応'));const cases=node('ul');Object.entries(result.scenarios||{}).forEach(([k,v])=>cases.append(node('li',k+' : D0 '+pct(v.d0)+' / D1 '+pct(v.d1))));root.append(cases);
 root.append(node('h3','未対応の重要相手'));const u=node('ul');t.critical.forEach(x=>u.append(node('li',label(x.opponent)+' / 最良Rating '+x.best_rating)));root.append(u);
 root.append(node('h3','相手の危険な2体の組み合わせ'));const threats=node('ul');(result.danger_pairs||[]).slice(0,10).forEach(x=>threats.append(node('li',x.opponents.map(label).join(' + ')+' / 担当集中 '+x.assignment_deficit+' / 釣り出し警告 '+x.trap_risk)));root.append(threats);
 root.append(node('h3','全15ペアの相互補完'));const pairs=node('ul');result.pairs.forEach(x=>pairs.append(node('li',x.members.map(label).join(' + ')+' / 補完 '+x.balance.toFixed(3)+' / 穴 '+pct(x.hole))));root.append(pairs);
 root.append(node('h3','注目ペアのCore Breaker'));const cb=node('ul');result.pairs.slice(0,5).forEach(x=>{if(x.core_breakers.length)cb.append(node('li',x.members.map(label).join(' + ')+' に共通して有利: '+x.core_breakers.slice(0,3).map(z=>label(z.opponent)).join('、')))});root.append(cb);
 root.append(node('h3','20組の3体別の穴'));const triples=node('ul');result.triples.forEach(x=>triples.append(node('li',x.members.map(label).join(' / ')+' D0 '+pct(x.summary.d0)+' D1 '+pct(x.summary.d1))));root.append(triples);
 const sel=$('selectionResult');sel.replaceChildren();if(result.selection.status==='計算済み'){sel.append(node('h3','推奨選出（先頭が初手）'));result.selection.recommendations.forEach((x,i)=>{const b=node('div',null,'result');b.append(node('strong',(i+1)+'案: '+x.selection.map(label).join(' → ')));addLine(b,'保守的な静的比較値 '+x.worst+' / 危険な相手選出 '+x.worst_opponent.map(label).join(' / '));sel.append(b)})}else addLine(sel,result.selection.missing_condition||result.selection.status);
 $('result').replaceChildren(node('p','キャッシュ再利用 '+result.cache.hits+' / 新規セル '+result.cache.computed+' / '+result.elapsed_seconds+'秒'),
 node('p','未計算: '+result.not_calculated.join('、')));tab(result.selection.status==='計算済み'?'selection':'weakness')}
async function run(mode){if(activeJob)return;
 const request={mode,members:getMon(),locked_slots:locks(),meta_preset_id:$('meta').value,meta_sha256:metaItems.find(x=>x.id===$('meta').value)?.sha256,group_weights:mode==='strategy'?{}:getWeights(),ruleset:'cp1500-lv50'};
 if(mode==='build')request.candidate_pool=partyRosterRows('pool');
 if(mode==='select')request.opponents=partyRosterRows('enemy');
 if(mode==='strategy'){request.opponents=partyRosterRows('strategyEnemy');request.strategy=getStrategy()}
 const submittedRevision=inputRevision;
 const r=await api('party/start',request);activeJob=r.job_id;$('cancel').disabled=false;$('analyze').disabled=true;status('計算中...');
 for(;;){await new Promise(resolve=>setTimeout(resolve,2000));let s=await api('party/status',{job_id:activeJob});
 if(s.status==='done'){if(submittedRevision!==inputRevision){status('計算中に入力が変更されました。以前の入力の結果は表示しません。再計算してください。')}else{if(s.result.kind==='strategy')showStrategy(s.result);else show(s.result);status('計算完了。実戦勝率ではありません。')}break}
 if(s.status==='error'||s.status==='cancelled'){status(s.message||s.status);break}
 status('計算中 '+(s.progress||0)+'% / '+(s.message||''))}
 activeJob=null;$('cancel').disabled=true;$('analyze').disabled=false;
}
async function wrap(mode){try{await run(mode)}catch(e){status(e.message);activeJob=null;$('cancel').disabled=true;$('analyze').disabled=false}}
$('analyze').onclick=()=>{if(currentTab==='strategy')strategyTargets();wrap(currentTab==='strategy'?'strategy':'analyze')};$('build').onclick=()=>wrap('build');$('select').onclick=()=>wrap('select');
$('cancel').onclick=()=>activeJob&&api('party/cancel',{job_id:activeJob}).then(()=>status('中止要求を送信しました'));
function populateSaved(items,selected=partyId){$('saved').replaceChildren(new Option('読み込むパーティを選ぶ',''));items.forEach(x=>$('saved').append(new Option(x.name,x.id)));$('saved').value=selected||'';}
async function setup(){
 const [cat,presets,saved]=await Promise.all([api('catalog'),api('meta-presets'),api('party/list')]);
 if(!cat.ready)throw Error('ゲームデータがまだ準備中です');catalog=cat.species;partyMoveNames=cat.moves||{};metaItems=presets.items;
 for(const m of metaItems.filter(x=>x.available!==false)){let o=new Option(m.name+' ('+m.rows+'件)',m.id);$('meta').append(o)}$('meta').value=presets.default_id;
 populateSaved(saved.items);renderMon();if(!rosterEditors.enemy){rosterEditors.enemy=partyRosterEditor('enemy',6);rosterEditors.pool=partyRosterEditor('pool',48);rosterEditors.strategyEnemy=partyRosterEditor('strategyEnemy',6);}$('workspace').hidden=false;$('auth').hidden=true;$('analyze').disabled=false;status('6体を入力すると分析できます')}
$('login').onclick=async()=>{key=$('key').value.trim();try{await setup();if(key)await api('session',{}).catch(()=>{})}catch(e){$('workspace').hidden=false;status(e.message)}};
async function saveParty(asNew=false){try{
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
 $('weights').value=Object.entries(p.group_weights||{}).map(x=>x.join(':')).join('\n');
 const csv=rows=>(rows||[]).map(x=>[x.species,x.fast,x.charged1,x.charged2,...(['atk','def','hp'].every(k=>k in x)?[x.atk,x.def,x.hp]:[])].join(',')).join('\n');
 $('enemy').value=csv(p.opponents);$('pool').value=csv(p.candidate_pool);
 rosterEditors.enemy.refresh(p.opponents||[]);rosterEditors.pool.refresh(p.candidate_pool||[]);
 restoreStrategy(p.strategy,csv(p.opponents));
 latest=null;$('weakResult').replaceChildren();$('selectionResult').replaceChildren();
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
