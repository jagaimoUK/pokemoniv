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
.mon{padding:10px;border-radius:16px;background:#29413f;border:1px solid #557769}
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
<div class="tabs"><button data-tab="compose" aria-pressed="true">構築</button><button data-tab="weakness">弱点・補完</button><button data-tab="selection">相手と選出</button><button data-tab="settings">保存・設定</button></div>
<div id="compose"><section><h2>自分の6体</h2><p>各枠をタップして技と個体値を編集。IV省略時はPvPoke標準値を使用します。CP1500/Lv50。</p><div class="grid" id="members"></div></section>
<section><h2>自動構築</h2><p>候補を7列CSVで入力。固定枠を残して最大48候補から探索します。</p>
<textarea id="pool" placeholder="azumarill,BUBBLE,ICE_BEAM,PLAY_ROUGH,0,15,15"></textarea><button id="build">候補から6体を提案</button></section></div>
<div id="weakness" hidden><section><h2>弱点・補完</h2><div id="weakResult">分析後に表示します。</div></section></div>
<div id="selection" hidden><section><h2>相手6体</h2><p>種ID・通常技・ゲージ技2つ（必要ならIV3つ）を1行ずつ指定してください。</p><textarea id="enemy" placeholder="clodsire,POISON_STING,STONE_EDGE,EARTHQUAKE"></textarea><button id="select">相手6体への選出を比較</button>
<p>双方ともチーム全体のシールドは2枚。静的な近似であり、実際の3対3勝率ではありません。</p><div id="selectionResult"></div></section></div>
<div id="settings" hidden><section><h2>保存・分析条件</h2><label for="meta">メタプリセット</label><select id="meta"></select>
<label for="partyName">パーティ名</label><input id="partyName" value="新しいパーティ" maxlength="60">
<div class="tools"><button id="save">保存する</button><select id="saved"><option value="">保存済みを選ぶ</option></select><button id="load">読み込む</button></div>
<label for="weights">重要度（種ID:数値を1行ずつ）</label><textarea id="weights" placeholder="clodsire:4"></textarea>
<p>技違いは同種内で重要度を分配します。ブラフ・受け・交代後の詳細モデルは未対応です。</p></section></div>
<section><h2>計算状況と結果</h2><div id="status" role="status" aria-live="polite">接続を確認しています。</div><div id="result"></div></section>
</div></main><footer><div class="tools"><button id="analyze" disabled>6体を分析</button><button id="cancel" disabled>計算を中止</button></div></footer>
<datalist id="speciesList"></datalist><script>
'use strict';
const $=id=>document.getElementById(id);
let key='',catalog={},metaItems=[],partyId=null,revision=0,activeJob=null,latest=null;
const name=id=>catalog[id]?.name||id;
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n}
function status(text){$('status').textContent=text}
function tab(target){['compose','weakness','selection','settings'].forEach(id=>$(id).hidden=id!==target);document.querySelectorAll('[data-tab]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.tab===target)))}
document.querySelectorAll('[data-tab]').forEach(x=>x.onclick=()=>tab(x.dataset.tab));
async function api(path,body={}){
 const h={'Content-Type':'application/json'};if(key)h.Authorization='Bearer '+key;
 const r=await fetch('/app-api/'+path,{method:'POST',headers:h,body:JSON.stringify(body),credentials:'same-origin'});
 const data=await r.json().catch(()=>({error:'サーバー応答を読み取れません'}));if(!r.ok)throw Error(data.error||'HTTP '+r.status);return data;
}
function createMon(data={}){
 const box=node('details',null,'mon'),s=node('summary',data.species?name(data.species):'ポケモンを選ぶ');
 box.append(s);const body=node('div',null,'fields');
 for(const [k,title,type] of [['species','種ID','text'],['fast','通常技','text'],['charged1','ゲージ技1','text'],['charged2','ゲージ技2','text'],['atk','攻撃IV','number'],['def','防御IV','number'],['hp','HP IV','number'],['level_override','指定レベル（任意）','number']]){
 const l=node('label',title);const input=node('input');input.dataset.field=k;input.type=type;input.value=data[k]??'';
 if(type==='number'){input.min=k==='level_override'?1:0;input.max=k==='level_override'?50:15;input.step=k==='level_override'?.5:1}if(k==='species'){input.setAttribute('list','speciesList');input.onchange=()=>{const id=input.value.trim().toLowerCase();s.textContent=name(id);let p=catalog[id];if(p){body.querySelector('[data-field=fast]').value ||=p.fastMoves[0]||'';body.querySelector('[data-field=charged1]').value ||=p.chargedMoves[0]||'';body.querySelector('[data-field=charged2]').value ||=p.chargedMoves[1]||''}}}
 l.append(input);body.append(l)}
 const l=node('label');const locked=node('input');locked.type='checkbox';locked.dataset.field='locked';locked.checked=!!data.locked;l.append(locked,document.createTextNode(' 自動構築では固定'));body.append(l);box.append(body);return box;
}
function renderMon(rows=[]){$('members').replaceChildren();for(let i=0;i<6;i++)$('members').append(createMon(rows[i]||{}))}
function getMon(){return [...$('members').children].map(box=>{const item={};box.querySelectorAll('[data-field]').forEach(x=>{if(x.dataset.field==='locked'||!x.value.trim())return;item[x.dataset.field]=x.type==='number'?Number(x.value):x.value.trim()});return item})}
function locks(){return [...$('members').children].flatMap((box,i)=>box.querySelector('[data-field=locked]').checked?[i]:[])}
function parseCsv(source){const lines=source.trim().split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
 return lines.map((line,i)=>{const p=line.split(',').map(x=>x.trim());if(![4,7].includes(p.length))throw Error((i+1)+'行目は4列または7列です');
 const x={species:p[0].toLowerCase(),fast:p[1].toUpperCase(),charged1:p[2].toUpperCase(),charged2:p[3].toUpperCase()};
 if(p.length===7){for(let n=4;n<7;n++){if(!/^(?:[0-9]|1[0-5])$/.test(p[n]))throw Error((i+1)+'行目のIVが不正です');x[['atk','def','hp'][n-4]]=Number(p[n])}}return x})}
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
 addLine(root,'未対応 D0 '+pct(t.d0)+' / 担当1体 D1 '+pct(t.d1)+' / 未計算 '+pct(t.unknown_weight));
 root.append(node('h3','未対応の重要相手'));const u=node('ul');t.critical.forEach(x=>u.append(node('li',label(x.opponent)+' / 最良Rating '+x.best_rating)));root.append(u);
 root.append(node('h3','相手の危険な2体の組み合わせ'));const threats=node('ul');(result.danger_pairs||[]).slice(0,10).forEach(x=>threats.append(node('li',x.opponents.map(label).join(' + ')+' / 担当集中 '+x.assignment_deficit+' / 釣り出し警告 '+x.trap_risk)));root.append(threats);
 root.append(node('h3','全15ペアの相互補完'));const pairs=node('ul');result.pairs.forEach(x=>pairs.append(node('li',x.members.map(label).join(' + ')+' / 補完 '+x.balance.toFixed(3)+' / 穴 '+pct(x.hole))));root.append(pairs);
 root.append(node('h3','20組の3体別の穴'));const triples=node('ul');result.triples.forEach(x=>triples.append(node('li',x.members.map(label).join(' / ')+' D0 '+pct(x.summary.d0)+' D1 '+pct(x.summary.d1))));root.append(triples);
 const sel=$('selectionResult');sel.replaceChildren();if(result.selection.status==='計算済み'){sel.append(node('h3','推奨選出（先頭が初手）'));result.selection.recommendations.forEach((x,i)=>{const b=node('div',null,'result');b.append(node('strong',(i+1)+'案: '+x.selection.map(label).join(' → ')));addLine(b,'保守的な静的比較値 '+x.worst+' / 危険な相手選出 '+x.worst_opponent.map(label).join(' / '));sel.append(b)})}else addLine(sel,result.selection.missing_condition||result.selection.status);
 $('result').replaceChildren(node('p','キャッシュ再利用 '+result.cache.hits+' / 新規セル '+result.cache.computed+' / '+result.elapsed_seconds+'秒'),
 node('p','未計算: '+result.not_calculated.join('、')));tab(result.selection.status==='計算済み'?'selection':'weakness')}
async function run(mode){if(activeJob)return;
 const request={mode,members:getMon(),locked_slots:locks(),meta_preset_id:$('meta').value,meta_sha256:metaItems.find(x=>x.id===$('meta').value)?.sha256,group_weights:getWeights(),ruleset:'cp1500-lv50'};
 if(mode==='build')request.candidate_pool=parseCsv($('pool').value);
 if(mode==='select')request.opponents=parseCsv($('enemy').value);
 const r=await api('party/start',request);activeJob=r.job_id;$('cancel').disabled=false;$('analyze').disabled=true;status('計算中...');
 for(;;){await new Promise(resolve=>setTimeout(resolve,2000));let s=await api('party/status',{job_id:activeJob});
 if(s.status==='done'){show(s.result);status('計算完了。実戦勝率ではなく静的近似です。');break}
 if(s.status==='error'||s.status==='cancelled'){status(s.message||s.status);break}
 status('計算中 '+(s.progress||0)+'% / '+(s.message||''))}
 activeJob=null;$('cancel').disabled=true;$('analyze').disabled=false;
}
async function wrap(mode){try{await run(mode)}catch(e){status(e.message);activeJob=null;$('cancel').disabled=true;$('analyze').disabled=false}}
$('analyze').onclick=()=>wrap('analyze');$('build').onclick=()=>wrap('build');$('select').onclick=()=>wrap('select');
$('cancel').onclick=()=>activeJob&&api('party/cancel',{job_id:activeJob}).then(()=>status('中止要求を送信しました'));
function populateSaved(items){$('saved').replaceChildren(new Option('保存済みから読み込む',''));items.forEach(x=>$('saved').append(new Option(x.name,x.id)))}
async function setup(){
 const [cat,presets,saved]=await Promise.all([api('catalog'),api('meta-presets'),api('party/list')]);
 if(!cat.ready)throw Error('ゲームデータがまだ準備中です');catalog=cat.species;metaItems=presets.items;
 for(const [id,p] of Object.entries(catalog)){let o=node('option');o.value=id;o.label=p.name||id;$('speciesList').append(o)}
 for(const m of metaItems.filter(x=>x.available!==false)){let o=new Option(m.name+' ('+m.rows+'件)',m.id);$('meta').append(o)}$('meta').value=presets.default_id;
 populateSaved(saved.items);renderMon();$('workspace').hidden=false;$('auth').hidden=true;$('analyze').disabled=false;status('6体を入力すると分析できます')}
$('login').onclick=async()=>{key=$('key').value.trim();try{await setup();if(key)await api('session',{}).catch(()=>{})}catch(e){$('workspace').hidden=false;status(e.message)}};
$('save').onclick=async()=>{try{const obj={id:partyId,revision,name:$('partyName').value,members:getMon(),locked_slots:locks(),meta_preset_id:$('meta').value,meta_sha256:metaItems.find(x=>x.id===$('meta').value)?.sha256,group_weights:getWeights(),opponents:parseCsv($('enemy').value),candidate_pool:parseCsv($('pool').value)};
 const r=await api('party/save',obj);partyId=r.id;revision=r.revision;populateSaved((await api('party/list')).items);status('保存済み。revision '+revision)}catch(e){status(e.message)}};
$('load').onclick=async()=>{try{const p=await api('party/get',{id:$('saved').value});partyId=p.id;revision=p.revision;$('partyName').value=p.name;
 renderMon((p.members||[]).map((m,i)=>({...m,locked:(p.locked_slots||[]).includes(i)})));
 if(metaItems.some(x=>x.id===p.meta_preset_id))$('meta').value=p.meta_preset_id;
 $('weights').value=Object.entries(p.group_weights||{}).map(x=>x.join(':')).join('\n');
 const csv=rows=>(rows||[]).map(x=>[x.species,x.fast,x.charged1,x.charged2,...(['atk','def','hp'].every(k=>k in x)?[x.atk,x.def,x.hp]:[])].join(',')).join('\n');
 $('enemy').value=csv(p.opponents);$('pool').value=csv(p.candidate_pool);status('読み込みました')}catch(e){status(e.message)}};
setup().catch(()=>{status('ログインが必要です。接続キーを入力してください。')});
</script></body></html>'''
