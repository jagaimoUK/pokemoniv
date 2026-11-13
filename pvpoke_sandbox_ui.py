"""The authenticated, mobile-first editor for native Sandbox battles."""

HTML = r'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>対戦サンドボックス</title>
<style>
:root{color-scheme:dark;font:16px/1.55 system-ui,sans-serif;color:#edf4fa;background:#101a22;--panel:#192831;--inset:#122029;--edge:#3c5663;--text-muted:#b4c6d1;--self:#a0edda;--other:#ffd099;--warn:#ffd1a5;--error:#ffc2ba}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0}
main{max-width:48rem;margin:auto;padding:.75rem max(.75rem,env(safe-area-inset-right)) 3rem max(.75rem,env(safe-area-inset-left))}
h1,h2,h3,p{margin:0;overflow-wrap:anywhere}
h1{font-size:clamp(1.65rem,7vw,2.4rem);letter-spacing:.025em}
h2{font-size:1.15rem}
h3{font-size:1rem}
small,.muted,legend{color:var(--text-muted)}
.stack{display:grid;gap:.85rem}
.tight{gap:.5rem}
.panel,.inset{min-width:0;border:1px solid var(--edge);border-radius:.9rem;padding:clamp(.65rem,3vw,1.1rem);background:var(--panel)}
.inset{background:var(--inset);border-radius:.6rem;padding:.65rem}
.conditions{border-top:1px solid var(--edge)}
.conditions summary{font-size:.85rem;color:var(--text-muted)}
.row{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.6rem}
.three{grid-template-columns:repeat(3,minmax(0,1fr))}
.wide{grid-column:1/-1}
.grid>*{min-width:0}
nav a{padding:.6rem 0;min-height:44px}
a{color:var(--self)}
input,select,button{font:inherit;color:inherit;background:var(--inset);min-width:0;min-height:44px;border:1px solid #627f8e;border-radius:.5rem}
input,select{width:100%;padding:.35rem .5rem}
button{padding:.4rem .65rem;cursor:pointer;overflow-wrap:anywhere}
button:disabled{opacity:.5;cursor:default}
button.primary{color:#10251f;background:var(--self);border-color:var(--self);font-weight:700}
label{display:grid;gap:.2rem;min-width:0;font-size:.875rem;font-weight:650}
input,select{font-size:1rem}
:focus-visible{outline:2px solid #f8e4a8;outline-offset:2px}
fieldset{border:0;padding:0;margin:0;min-width:0}
legend{padding:0;font-size:.82rem}
summary{min-height:44px;padding:.6rem 0;cursor:pointer;font-weight:650;overflow-wrap:anywhere}
summary+*{margin-top:.4rem}
.notice{border-inline-start:3px solid var(--self);padding:.45rem .65rem;background:var(--inset)}
.notice[data-tone=warning]{color:var(--warn);border-color:var(--warn)}
.notice[data-tone=error]{color:var(--error);border-color:var(--error)}
.side-0{--side:var(--self)}
.side-1{--side:var(--other)}
.side-title{color:var(--side);font-weight:700}
.turn-scroll{position:relative;overflow-x:auto;padding-bottom:.35rem}
.turn-grid{display:grid;grid-template-columns:3.1rem repeat(8,minmax(7rem,1fr));gap:.3rem;align-items:stretch}
.turn-label{align-self:center;font-variant-numeric:tabular-nums;text-align:center;color:var(--text-muted);font-size:.82rem}
.turn-side{position:sticky;left:0;z-index:1;display:grid;place-items:center;background:var(--panel);border-inline-end:1px solid var(--edge);font-size:.82rem}
.turn-cell{min-height:48px;text-align:start;padding:.28rem .4rem;border-inline-start:3px solid var(--side);font-size:.86rem;line-height:1.35}
.turn-cell[aria-pressed=true]{background:#304752;outline:1px solid var(--side);outline-offset:-1px}
.turn-cell[data-rejected=true]{border-top-color:var(--warn);border-bottom-color:var(--warn);border-right-color:var(--warn)}
.cell-note{display:block;color:var(--text-muted);font-size:.75rem;margin-top:.15rem}
.turn-jump{display:flex;gap:.45rem;align-items:end}
.turn-jump label{width:5rem}
.turn-jump button{flex:none}
table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:.875rem;font-variant-numeric:tabular-nums}
th,td{padding:.35rem .2rem;text-align:start;border-bottom:1px solid var(--edge);overflow-wrap:anywhere;vertical-align:top}
th{color:var(--text-muted);font-weight:600}
.state{border-inline-start:2px solid var(--side)}
.state p{font-size:.84rem;font-variant-numeric:tabular-nums}
.event{padding:.4rem .6rem;border:1px solid var(--edge);border-inline-start:3px solid var(--side);border-radius:.5rem;background:var(--inset)}
.event summary{padding:.4rem 0}
.event[open]{padding-bottom:.65rem}
.events{display:grid;gap:.4rem;padding:0;margin:0;list-style:none}
.outcome{font-weight:700}
@media(max-width:23rem){.panel{padding:.65rem}.grid{gap:.45rem}.turn-grid{gap:.2rem;grid-template-columns:2.6rem repeat(8,minmax(6.45rem,1fr))}.turn-cell{padding:.26rem .32rem}}
</style>
</head>
<body>
<main class="stack">
<nav class="row" aria-label="アプリ内ナビゲーション"><a href="/app">← 個体値厳選</a><!--MISSING_ANALYSIS_NAV--></nav>
<header><h1>対戦サンドボックス</h1><p class="muted">スーパーリーグ（CP 1500）で、両者の技とシールドをターンごとに試せます。</p></header>
<p id="notice" class="notice" role="status" aria-live="polite">接続を確認しています。</p>
<section id="connection" class="panel" hidden>
<form id="login-form" class="stack"><h2>アプリに接続</h2><label>接続キー<input id="credential" type="password" autocomplete="off"></label><div class="row"><button class="primary" type="submit">接続する</button></div></form>
</section>
<div id="workspace" class="stack" hidden>
<section class="panel stack">
<h2>対戦の開始状態</h2>
<form id="setup" class="stack tight"></form>
<div id="initial" class="grid" hidden></div>
</section>
<section class="panel stack" aria-labelledby="timeline-title">
<div class="stack tight">
<h2 id="timeline-title">ターンの編集と記録</h2>
<p class="muted">指定のないターンは、行動できる側が通常技を使います。止めたいターンには「待機」を指定してください。</p>
<div class="row"><button id="simulate" type="button" class="primary" data-request>全ターンを計算</button><button id="undo" type="button" data-request>元に戻す</button><button id="redo" type="button" data-request>やり直す</button></div>
<p id="script-status" class="notice" aria-live="polite">ターンの記録は計算後に表示します。</p>
</div>
<div class="row" aria-label="ターン移動">
<button id="previous-turn" type="button" aria-label="前のターン">前</button>
<form class="turn-jump" id="jump-form"><label>ターン<input id="jump-turn" type="number" min="1" max="500" step="1" required value="1"></label><button type="submit">移動</button></form>
<button id="next-turn" type="button" aria-label="次のターン">次</button>
</div>
<div id="turn-state" class="grid" hidden></div>
<div id="turn-scroll" class="turn-scroll" tabindex="0" aria-label="ターン表（左右にスクロール）"><div id="timeline" class="turn-grid"></div></div>
<div class="row" aria-label="行動への移動"><button id="previous-action" type="button">前の行動</button><button id="next-action" type="button">次の行動</button></div>
<div class="inset stack tight">
<h3 id="selected-turn" tabindex="-1"></h3>
<form id="action-form" class="stack tight">
<fieldset id="action-controls" class="grid">
<label class="wide">指定する行動<select id="action-choice" required></select></label>
<label class="wide" id="shield-label" hidden><span id="defender"></span><select id="shield-choice"><option value="">選択してください</option><option value="no">使わない</option><option value="yes">使う</option></select></label>
</fieldset>
<p id="edit-hint" class="muted"></p>
<div class="row"><button id="apply-action" class="primary" type="submit" data-request>この指定で計算</button><button id="remove-action" type="button" data-request>指定を解除</button></div>
</form>
<div id="action-result"></div>
</div>
<div class="stack tight">
<h3 id="event-title">このターンの記録</h3>
<ol id="turn-events" class="events" aria-labelledby="event-title"></ol>
</div>
</section>
<section class="panel stack">
<h2>通常対戦と比較</h2>
<p class="muted">同じ個体・技・開始状態で、PvPokeが技とシールドを選ぶ通常対戦と比べます。</p>
<p class="muted">確率で発動する能力変化は、通常対戦ではPvPokeの累積ルールで適用され、Sandboxでは発動しません。結果の差には、この処理の違いも含まれます。</p>
<div class="row"><button id="standard" type="button" data-request>通常対戦を計算</button></div>
<div id="comparison"></div>
</section>
<section id="tactic-search-panel" class="panel stack" data-tactic-search="0" hidden>
<details class="stack tight">
<summary>戦術自動探索（候補・計算数に上限あり）</summary>
<p class="muted">現在の個体・技・開始状態から最大64通りの戦術を候補にします。相手のシールド判断や別のゲージ技への変更も含みます。理論上のシミュレーションであり、実戦で必ず再現できる勝ち方ではありません。</p>
<div class="row"><button id="search-start" type="button" data-request>現在の条件で候補を作成</button><button id="search-step" type="button" data-request disabled>最大4件を検証</button></div>
<p id="search-status" class="notice" role="status" aria-live="polite">候補を作成していません。</p>
<div id="search-results" class="stack tight" aria-label="直近の探索結果"></div>
<a id="search-to-missing" href="/app/missing" hidden>不足分析へ戻って戦術証拠を照合</a>
</details>
</section>
<section id="observed-panel" class="panel stack" data-observed-search="0" hidden>
<details class="stack tight" id="observed-details">
<summary>観測履歴で戦術を探索（試験版）</summary>
<p class="muted">現在の相手設定に対し、即時観測と通常技の通知が遅れる条件で、同じ方策を検証します。実機での再現性は未確認です。不足分析の判定には反映しません。</p>
<div class="row">
<button id="observed-start" type="button" data-request>現在の条件で開始</button>
<button id="observed-step" type="button" data-request>最大8回を検証</button>
<button id="observed-stop" type="button" data-request>一時停止</button>
<button id="observed-resume" type="button" data-request>再開</button>
<button id="observed-get" type="button" data-request>前回の探索を取得</button>
</div>
<p id="observed-status" class="notice" role="status" aria-live="polite">探索を開始してください。</p>
</details>
</section>
<section class="panel stack">
<h2>戦術の保存と復元</h2>
<form id="save-form" class="stack tight"><label>戦術名<input id="tactic-name" maxlength="64" required autocomplete="off"></label><p id="save-status" class="muted"></p><div class="row"><button id="save" type="submit" class="primary" data-request>戦術を保存</button></div></form>
<div class="row"><button id="list" type="button" data-request>保存一覧を取得</button></div>
<form id="load-form" class="stack tight" hidden>
<div class="grid"><label class="wide">保存済みの戦術<select id="tactics" required></select></label><label>版（空欄＝最新版）<input id="revision" type="number" min="1" step="1"></label></div>
<div class="row"><button type="submit" data-request>戦術を復元</button></div>
</form>
</section>
</div>
<datalist id="species-list"></datalist>
</main>
<script>
'use strict';
const $=id=>document.getElementById(id);
const sides=['自分','相手'];
const phaseNames={start:'開始',resolve:'ダメージ解決',effects:'効果適用後'};
const kindNames={fast:'通常技',charged:'ゲージ技',wait:'待機'};
const outcomes={self_win:'自分の勝ち',opponent_win:'相手の勝ち',simultaneous_ko:'同時ひんし'};
const statuses={partial:'途中まで計算・勝敗未確定',invalid:'入力エラー',unsupported:'未対応の条件',failed:'計算に失敗',cancelled:'計算を中止'};
const reasons={
 fast_move_cooldown:'前の通常技の動作中',post_charged_lock:'ゲージ技の直後で行動できない',
 insufficient_energy:'ゲージ不足',knocked_out:'先にひんしになった',
 battle_ended:'そのターンより前に対戦が終了',simulation_timeout:'計算上限でそのターンに到達しなかった',
 no_shields:'残りシールドなし',unshieldable:'シールドを使えない技',action_not_resolved:'技が解決しなかった'
};
const importKey='pokemoniv:sandbox-input-v1';
const tacticLinkKey='pokemoniv:tactic-evidence-link-v1';
const defaultRules={league:'great',cp_cap:1500,max_level:50,cup_id:'all'};
const clone=value=>JSON.parse(JSON.stringify(value));
const normalize=value=>String(value).normalize('NFKC').trim().toLowerCase();
const newId=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
const newCombatant=()=>({species:'',ivs:{attack:'',defense:'',hp:''},level:'',moves:{fast:'',charged:['','']},
 initial:{hp:'',energy:'0',shields:'1',stages:['0','0']}});
const newDraft=()=>({tacticId:newId(),historicalRevision:null,rules:clone(defaultRules),
 combatants:[newCombatant(),newCombatant()],actions:[],shield_decisions:[]});
let credential='',catalog=Object.create(null),moves=Object.create(null),aliases=new Map();
let draft=newDraft(),turn=1,actor=0,busy=false,scripted=null,standard=null;
let tacticSearchId='',tacticSearchKey='';
let setupEditors=[];
const undo=[],redo=[],saved=new Map();
const name=id=>catalog[id]?.name_ja||catalog[id]?.name||id;
const nameWithId=id=>name(id)+' / '+id;
const moveName=id=>moves[id]?.name_ja||moves[id]?.name||id;
const sideName=i=>sides[i]+(speciesId(draft.combatants[i].species)?' · '+name(speciesId(draft.combatants[i].species)):'');
const buildHeading=i=>[sideName(i),Object.values(draft.combatants[i].ivs).every(Boolean)?
 '個体値 '+Object.values(draft.combatants[i].ivs).join('/'):''].filter(Boolean).join(' · ');
const describe=item=>item.kind==='wait'?'待機':kindNames[item.kind]+' · '+moveName(item.move_id);
const reasonText=reason=>reasons[reason]||reason||'理由なし';
const compareAction=(a,b)=>a.turn-b.turn||a.actor-b.actor;
const scriptKey=()=>JSON.stringify([draft.rules,draft.combatants,draft.actions,draft.shield_decisions]);
const standardKey=()=>JSON.stringify([draft.rules,draft.combatants]);
const currentScript=()=>scripted?.key===scriptKey()?scripted:null;
const currentStandard=()=>standard?.key===standardKey()?standard.result:null;

function node(tag,text,parent,cls){
 const el=document.createElement(tag);
 if(text!=null)el.textContent=text;
 if(cls)el.className=cls;
 if(parent)parent.append(el);
 return el;
}
function button(parent,text,handler){
 const el=node('button',text,parent);
 el.type='button';
 el.addEventListener('click',handler);
 return el;
}
function input(parent,label,attributes){
 return Object.assign(node('input',null,node('label',label,parent)),attributes);
}
function options(field,values,selected){
 field.replaceChildren(...values.map(([value,label])=>Object.assign(node('option',label),{value:String(value)})));
 if(values.some(([value])=>String(value)===selected))field.value=selected;
}
function announce(message,tone=''){
 $('notice').textContent=message;
 $('notice').dataset.tone=tone;
}
function setBusy(value){
 busy=value;
 document.querySelectorAll('[data-request]').forEach(el=>{el.disabled=value;});
 $('setup').querySelectorAll('fieldset').forEach(el=>{el.disabled=value;});
 $('action-controls').disabled=value;
 $('login-form').querySelector('button').disabled=value;
 $('tactics').disabled=value;
 $('revision').disabled=value;
 $('tactic-name').disabled=value;
 refreshButtons();
}
function refreshButtons(){
 const action=selectedAction();
 $('undo').disabled=busy||!undo.length;
 $('redo').disabled=busy||!redo.length;
 $('remove-action').disabled=busy||!action;
 $('search-step').disabled=busy||!tacticSearchId||tacticSearchKey!==scriptKey();
 $('previous-turn').disabled=turn===1;
 $('next-turn').disabled=turn===500;
 $('previous-action').disabled=!neighborAction(-1);
 $('next-action').disabled=!neighborAction(1);
}
async function api(path,payload){
 const headers={'Content-Type':'application/json'};
 if(credential)headers.Authorization='Bearer '+credential;
 const response=await fetch('/app-api/'+path,{method:'POST',credentials:'same-origin',headers,body:JSON.stringify(payload)});
 const result=await response.json().catch(()=>null);
 if(!response.ok||!result){
  const message=typeof result?.error==='string'?result.error:result?.error?.message;
  const error=Error(message||'サーバー応答を読み取れませんでした。');
  error.status=response.status;
  throw error;
 }
 return result;
}
async function perform(task){
 if(busy)return;
 setBusy(true);
 try{await task();}
 catch(error){
  if(error.status===401){
   credential='';
   $('connection').hidden=false;
   announce('接続キーを再入力してください。編集中の指定は画面に残っています。','warning');
  }else if(error.status===409){
   announce('別の処理が実行中か、保存した版が更新されています。再試行するか、保存一覧から最新版を確認してください。','warning');
  }else announce(error.message,'error');
 }finally{setBusy(false);}
}

function indexCatalog(entries,moveEntries){
 catalog=Object.assign(Object.create(null),entries);
 moves=Object.assign(Object.create(null),moveEntries);
 aliases=new Map();
 for(const id of Object.keys(catalog)){
  const pokemon=catalog[id];
  for(const alias of [pokemon.name,pokemon.name_ja,nameWithId(id),...(pokemon.aliases||[])].filter(Boolean)){
   const key=normalize(alias);
   if(!aliases.has(key))aliases.set(key,new Set());
   aliases.get(key).add(id);
  }
 }
 $('species-list').replaceChildren(...Object.keys(catalog)
  .sort((a,b)=>name(a).localeCompare(name(b),'ja')).map(id=>Object.assign(node('option'),{value:nameWithId(id)})));
}
function speciesId(value){
 const key=normalize(value);
 if(Object.hasOwn(catalog,key))return key;
 const ids=aliases.get(key);
 return ids?.size===1?[...ids][0]:'';
}
function fromSpec(spec,tacticId=newId(),historicalRevision=null){
 if(spec?.schema!=='battle-spec-v1'||spec.combatants?.length!==2||
    spec.rules?.league!=='great'||spec.rules.cp_cap!==1500||(spec.rules.max_level??50)!==50||(spec.rules.cup_id??'all')!=='all'){
  throw Error('対応するスーパーリーグの対戦条件を読み込めませんでした。');
 }
 return {tacticId,historicalRevision,rules:clone(spec.rules),
  combatants:spec.combatants.map(side=>({
   species:nameWithId(side.species_id),ivs:Object.fromEntries(Object.entries(side.ivs).map(([key,value])=>[key,String(value)])),
   level:String(side.level),moves:clone(side.moves),initial:{hp:side.initial.hp==='full'?'':String(side.initial.hp),
    energy:String(side.initial.energy),shields:String(side.initial.shields),stages:side.initial.stages.map(String)}
  })),
  actions:spec.mode==='sandbox'?clone(spec.actions||[]):[],shield_decisions:spec.mode==='sandbox'?clone(spec.shield_decisions||[]):[]
 };
}
function makeBuildEditor(parent,i){
 const initial=draft.combatants[i];
 const details=node('details',null,parent,'inset side-'+i);
 details.open=!initial.species;
 const heading=node('summary',buildHeading(i),details,'side-title');
 const fields=node('fieldset',null,details,'stack tight');
 const species=input(fields,'ポケモン・フォルム',{type:'text',required:true,autocomplete:'off',value:initial.species,placeholder:'例：マリルリ'});
 species.setAttribute('list','species-list');
 const ivGroup=node('div',null,fields,'grid three');
 const ivs=Object.fromEntries([['attack','攻撃個体値'],['defense','防御個体値'],['hp','HP個体値']].map(([key,label])=>[key,input(ivGroup,label,
  {type:'number',required:true,min:0,max:15,step:1,value:initial.ivs[key]})]));
 const level=input(fields,'対戦時のレベル',{type:'number',required:true,min:1,max:50,step:.5,value:initial.level});
 const moveFields=node('div',null,fields,'grid');
 const fast=node('select',null,node('label','通常技',moveFields,'wide'));
 const charged=[1,2].map(n=>node('select',null,node('label','ゲージ技'+n,moveFields)));
 for(const field of [fast,...charged])field.required=true;
 const conditions=node('details',null,fields,'conditions');
 const conditionHeading=node('summary',null,conditions);
 const stateFields=node('div',null,conditions,'grid');
 const hp=input(stateFields,'開始HP（空欄＝満タン）',{type:'number',min:1,max:10000,step:1,value:initial.initial.hp});
 const energy=input(stateFields,'開始ゲージ',{type:'number',required:true,min:0,max:100,step:1,value:initial.initial.energy});
 const shields=node('select',null,node('label','開始シールド',stateFields));
 options(shields,[[0,'0枚'],[1,'1枚'],[2,'2枚']],initial.initial.shields);
 const stages=['攻撃ランク','防御ランク'].map((label,n)=>input(stateFields,label,
  {type:'number',required:true,min:-4,max:4,step:1,value:initial.initial.stages[n]}));
 let priorId;
 function renderMoves(preferred,defaults){
  const id=speciesId(species.value);
  species.setCustomValidity(species.value&&!id?'一覧からフォルムまで選択してください。':'');
  if(!preferred&&(!id||id===priorId))return;
  const pokemon=catalog[id]||{};
  const suggested=defaults?pokemon.default_moves||{}:{};
  const names=[preferred?.fast||suggested.fast,preferred?.charged[0]||suggested.charged1,preferred?.charged[1]||suggested.charged2];
  const pools=[pokemon.fastMoves||[],pokemon.chargedMoves||[],pokemon.chargedMoves||[]];
  [fast,...charged].forEach((field,n)=>{
   const pool=pools[n],desired=names[n];
   const choices=[['','選択してください'],...pool.map(id=>[id,moveName(id)])];
   if(desired&&!pool.includes(desired))choices.push([desired,moveName(desired)+'（装備できません）']);
   options(field,choices,desired);
  });
  priorId=id;
 }
 function validate(){
  const pokemon=catalog[speciesId(species.value)]||{};
  for(const [field,pool] of [[fast,pokemon.fastMoves],...charged.map(field=>[field,pokemon.chargedMoves])]){
   field.setCustomValidity(field.value&&!pool?.includes(field.value)?'このポケモンが装備できる技を選んでください。':'');
  }
  if(charged[0].value&&charged[0].value===charged[1].value)charged[1].setCustomValidity('異なるゲージ技を2つ選んでください。');
 }
 function read(){
  return {species:species.value,ivs:Object.fromEntries(Object.entries(ivs).map(([key,field])=>[key,field.value])),
   level:level.value,moves:{fast:fast.value,charged:charged.map(field=>field.value)},
   initial:{hp:hp.value,energy:energy.value,shields:shields.value,stages:stages.map(field=>field.value)}};
 }
 function summarize(){
  heading.textContent=buildHeading(i);
  conditionHeading.textContent='開始条件 · HP '+(hp.value||'満タン')+' · ゲージ '+energy.value+
   ' · シールド '+shields.value+' · 攻防 '+stages.map(field=>field.value).join('/');
 }
 species.addEventListener('input',()=>{renderMoves(null,true);validate();});
 fields.addEventListener('change',()=>{
  renderMoves(null,true);validate();
  const next={...draft,combatants:draft.combatants.map((side,n)=>n===i?read():side)};
  if(commitDraft(next)){
   summarize();
   render();
  }
 });
 renderMoves(initial.moves,false);
 validate();
 summarize();
 return {details,validate};
}
function renderSetup(preserveOpen=true){
 const open=setupEditors.map(editor=>editor.details.open);
 $('setup').replaceChildren();
 setupEditors=sides.map((_,i)=>makeBuildEditor($('setup'),i));
 if(preserveOpen)setupEditors.forEach((editor,i)=>{editor.details.open=open[i]??editor.details.open;});
}
function buildSpec(mode){
 for(const editor of setupEditors)editor.validate();
 if(!$('setup').reportValidity())return null;
 const spec={schema:'battle-spec-v1',rules:clone(draft.rules),mode,combatants:draft.combatants.map(side=>({
  species_id:speciesId(side.species),ivs:Object.fromEntries(Object.entries(side.ivs).map(([key,value])=>[key,Number(value)])),
  level:Number(side.level),moves:clone(side.moves),initial:{hp:side.initial.hp===''?'full':Number(side.initial.hp),
   energy:Number(side.initial.energy),shields:Number(side.initial.shields),stages:side.initial.stages.map(Number)}
 }))};
 if(mode==='sandbox'){
  const incompatible=draft.actions.find(action=>action.kind!=='wait'&&
   (action.kind==='fast'?action.move_id!==spec.combatants[action.actor].moves.fast:!spec.combatants[action.actor].moves.charged.includes(action.move_id)));
  if(incompatible)throw Error(incompatible.turn+'ターン目の'+sides[incompatible.actor]+'に、装備していない技が指定されています。指定を選び直すか解除してください。');
  spec.actions=clone(draft.actions);
  spec.shield_decisions=clone(draft.shield_decisions);
 }
 return spec;
}
function withSpec(mode,task){
 if(busy)return;
 try{
  const spec=buildSpec(mode);
  if(spec)perform(()=>task(spec));
 }catch(error){announce(error.message,'error');}
}

function commitDraft(next){
 if(JSON.stringify(draft)===JSON.stringify(next))return false;
 undo.push(draft);
 if(undo.length>100)undo.shift();
 redo.length=0;
 draft=next;
 return true;
}
function changeHistory(from,to){
 if(busy||!from.length)return;
 const last=draft.tacticId;
 to.push(draft);
 draft=from.pop();
 if(last!==draft.tacticId)$('tactic-name').value=saved.get(draft.tacticId)?.name||'';
 renderSetup();
 render();
}
function selectedAction(){return draft.actions.find(item=>item.turn===turn&&item.actor===actor);}
function neighborAction(direction){
 const selected={turn,actor};
 const specified=neighbor(draft.actions);
 const observed=neighbor(currentScript()?.starts||[]);
 if(!specified||!observed)return specified||observed;
 return compareAction(specified,observed)*direction<=0?specified:observed;
 function neighbor(items){
  if(direction<0){
   for(let i=items.length-1;i>=0;i--)if(compareAction(items[i],selected)<0)return items[i];
   return null;
  }
  return items.find(item=>compareAction(item,selected)>0);
 }
}
function goTo(newTurn,newActor=actor,focus=false){
 if(!Number.isInteger(newTurn)||newTurn<1||newTurn>500)return;
 turn=newTurn;
 actor=newActor;
 renderTimeline();
 renderEditor();
 refreshButtons();
 if(focus)$('selected-turn').focus();
}
function visitAction(action){if(action)goTo(action.turn,action.actor,true);}
function actionReport(id,record){return record?.actions.get(id);}
function phaseReport(id,record){return record?.byAction.get(id)||[];}
function chooseAction(){
 const current=selectedAction();
 const value=$('action-choice').value;
 const charged=value.startsWith('charged:');
 $('shield-label').hidden=!charged;
 $('shield-choice').required=charged;
 const prior=current&&('charged:'+current.move_id===value)?
  draft.shield_decisions.find(decision=>decision.action_id===current.id):null;
 $('shield-choice').value=prior?(prior.use_shield?'yes':'no'):'';
}
function editAction(event){
 event.preventDefault();
 if(busy)return;
 const [kind,move_id]=$('action-choice').value.split(':');
 if(!Object.hasOwn(kindNames,kind)||!$('action-form').reportValidity())return;
 const prior=selectedAction();
 const next={...draft,actions:draft.actions.filter(item=>item!==prior),
  shield_decisions:draft.shield_decisions.filter(item=>item.action_id!==prior?.id)};
 const action={id:prior?.id||newId(),actor,turn,kind};
 if(kind!=='wait')action.move_id=move_id;
 next.actions.push(action);
 next.actions.sort(compareAction);
 if(kind==='charged')next.shield_decisions.push({action_id:action.id,defender:1-actor,use_shield:$('shield-choice').value==='yes'});
 next.shield_decisions.sort((a,b)=>a.action_id.localeCompare(b.action_id));
 commitDraft(next);
 render();
 withSpec('sandbox',spec=>simulate(spec,action.id));
}
function removeAction(){
 if(busy)return;
 const prior=selectedAction();
 if(!prior)return;
 commitDraft({...draft,actions:draft.actions.filter(item=>item!==prior),
  shield_decisions:draft.shield_decisions.filter(item=>item.action_id!==prior.id)});
 render();
 announce('行動の指定を解除しました。全ターンを計算すると記録が更新されます。');
}

function indexedResult(result,key){
 const byTurn=new Map(),byAction=new Map();
 const starts=[];
 function add(map,id,event){
  if(!map.has(id))map.set(id,[]);
  map.get(id).push(event);
 }
 for(const event of result.trace||[]){
  add(byTurn,event.turn,event);
  if(event.action_id)add(byAction,event.action_id,event);
  if(event.phase==='start')starts.push(event);
 }
 return {result,key,byTurn,byAction,starts:starts.sort(compareAction),
  actions:new Map((result.summary?.action_results||[]).map(item=>[item.action_id,item])),
  shields:new Map((result.shield_results||[]).map(item=>[item.action_id,item]))};
}
function displayStatus(result){
 if(result?.status==='complete')return outcomes[result.outcome]||'計算完了';
 return statuses[result?.status]||'未計算';
}
async function simulate(spec,actionId){
 const key=scriptKey();
 announce('指定したターンの対戦を計算しています。');
 const result=await api('sandbox',{action:'simulate',spec});
 if(result.schema!=='sandbox-result-v1')throw Error('ターンの記録を読み取れませんでした。');
 scripted=indexedResult(result,key);
 render();
 const rejected=result.summary?.action_results?.filter(item=>item.status!=='executed')||[];
 const requested=rejected.find(item=>item.action_id===actionId);
 if(requested){announce('指定は編集欄に残っています。'+reasonText(requested.reason)+'。','warning');return;}
 if(result.status==='partial'){announce('途中まで計算しました。勝敗は未確定です。','warning');return;}
 if(result.status!=='complete'){announce(displayStatus(result)+'。'+(result.error?.message||''),'error');return;}
 announce(rejected.length?'計算しました。実行できなかった指定が'+rejected.length+'件あります。':'ターンの記録を更新しました。',rejected.length?'warning':'');
}
async function simulateStandard(spec){
 const key=standardKey();
 announce('同じ開始状態で通常対戦を計算しています。');
 const result=await api('sandbox',{action:'standard',spec:{...spec,mode:'sandbox'}});
 if(result.schema!=='battle-result-v1')throw Error('通常対戦の結果を読み取れませんでした。');
 standard={key,result};
 renderComparison();
 const tone=result.status==='complete'?'':result.status==='partial'?'warning':'error';
 announce('通常対戦：'+displayStatus(result)+'。'+(result.error?.message||''),tone);
}
function statLine(state){
 const stage=n=>n>0?'+'+n:String(n);
 return ['HP '+state.hp+'/'+state.max_hp,'ゲージ '+state.energy_points+'／シールド '+state.shields+'枚',
  '攻撃 '+stage(state.buffs[0])+'／防御 '+stage(state.buffs[1])];
}
function stateCards(parent,states,title){
 parent.replaceChildren();
 parent.hidden=!states;
 if(!states)return;
 states.forEach((state,i)=>{
  const card=node('div',null,parent,'inset state side-'+i);
  node('p',sides[i]+' · '+title,card,'side-title');
  for(const line of statLine(state))node('p',line,card);
 });
}
function eventState(parent,event){
 const table=node('table',null,parent);
 const head=node('tr',null,node('thead',null,table));
 for(const label of ['項目','直前','直後'])node('th',label,head).scope='col';
 const body=node('tbody',null,table);
 for(const [i,after] of event.after.entries()){
  const before=event.before[i];
  for(const [label,from,to] of [
   ['HP',before.hp,after.hp],['ゲージ',before.energy_points,after.energy_points],
   ['シールド',before.shields,after.shields],['攻撃ランク',before.buffs[0],after.buffs[0]],
   ['防御ランク',before.buffs[1],after.buffs[1]]
  ]){
   if(from===to)continue;
   const row=node('tr',null,body);
   node('th',sides[i]+' '+label,row).scope='row';
   node('td',from,row);
   node('td',to,row);
  }
 }
 if(!body.childElementCount){table.remove();node('p','HP・ゲージ・シールド・能力ランクの変化なし',parent,'muted');}
}
function renderTimeline(){
 const record=currentScript();
 const timeline=$('timeline');
 timeline.replaceChildren();
 const scroller=$('turn-scroll');
 node('span','T',timeline,'turn-label turn-side');
 $('jump-turn').value=turn;
 const first=Math.floor((turn-1)/8)*8+1;
 if(timeline.dataset.first!==String(first)){
  timeline.dataset.first=first;
  scroller.scrollLeft=0;
 }
 const turns=Array.from({length:Math.min(8,501-first)},(_,index)=>first+index);
 for(const t of turns)node('span',t,timeline,'turn-label');
 for(let index=turns.length;index<8;index++)node('span',null,timeline);
 const byCell=new Map(draft.actions.map(action=>[action.turn*2+action.actor,action]));
 let selectedCell;
 for(const [i,side] of sides.entries()){
  node('span',side,timeline,'turn-side side-title side-'+i);
  for(const t of turns){
   const requested=byCell.get(t*2+i);
   const phases=(record?.byTurn.get(t)||[]).filter(event=>event.actor===i);
   const report=requested&&actionReport(requested.id,record);
   const rejected=report&&report.status!=='executed';
   const firstPhase=phases[0];
   const label=requested?describe(requested):firstPhase?describe(firstPhase):'—';
   const cell=button(timeline,label,()=>goTo(t,i,true));
   cell.className='turn-cell side-'+i;
   const selected=t===turn&&i===actor;
   cell.setAttribute('aria-pressed',String(selected));
   if(selected)selectedCell=cell;
   cell.setAttribute('aria-label',t+'ターン '+side+' '+label);
   if(rejected){
    cell.dataset.rejected='true';
    node('span',reasonText(report.reason),cell,'cell-note');
   }
   if(phases.length){
    const sequence=phases.map(event=>{
     const phase=event.phase==='start'?'開始':event.phase==='resolve'?'解決':'効果';
     if(requested?event.action_id!==requested.id:event.move_id!==firstPhase.move_id){
      return phase+' '+(event.action_id?'':'自動 ') +(event.move_id?moveName(event.move_id):kindNames[event.kind]);
     }
     return phase;
    });
    node('span',sequence.join(' · '),cell,'cell-note');
   }else if(requested&&!report)node('span','指定あり',cell,'cell-note');
  }
  for(let index=turns.length;index<8;index++)node('span',null,timeline);
 }
 const visible=scroller.getBoundingClientRect();
 const selected=selectedCell.getBoundingClientRect();
 const left=visible.left+timeline.firstElementChild.offsetWidth;
 if(selected.right>visible.right)scroller.scrollLeft+=selected.right-visible.right;
 if(selected.left<left)scroller.scrollLeft-=left-selected.left+4;
}
function renderEditor(){
 const record=currentScript();
 const action=selectedAction();
 $('selected-turn').textContent=turn+'ターン · '+sideName(actor);
 $('defender').textContent=sides[1-actor]+'のシールド';
 const build=draft.combatants[actor];
 const choices=[['','行動を選ぶ'],['wait','待機']];
 if(build.moves.fast)choices.push(['fast:'+build.moves.fast,describe({kind:'fast',move_id:build.moves.fast})]);
 for(const id of new Set(build.moves.charged.filter(Boolean))){
  const cost=moves[id]?.energy;
  choices.push(['charged:'+id,describe({kind:'charged',move_id:id})+(Number.isFinite(cost)?'（ゲージ '+cost+'）':'')]);
 }
 const actionValue=action?(action.kind==='wait'?'wait':action.kind+':'+action.move_id):'';
 if(action&&actionValue&&!choices.some(([value])=>value===actionValue))choices.push([actionValue,describe(action)+'（装備外）']);
 options($('action-choice'),choices,actionValue);
 chooseAction();
 const events=record?.byTurn.get(turn)||[];
 let opening;
 if(turn<=record?.result.summary?.turns){
  opening=events[0]?.before;
  for(let previous=turn-1;!opening&&previous>=1;previous--)opening=record.byTurn.get(previous)?.at(-1)?.after;
  opening||=record.result.initial;
 }
 stateCards($('turn-state'),opening,'最初の記録前');
 $('edit-hint').textContent=opening?'最初の記録前のゲージ '+opening[actor].energy_points+'／防御側シールド '+opening[1-actor].shields+'枚。行動できるかは計算で確認します。':
  '技の動作中・ゲージ不足・ひんしなどで行動できない場合は、計算後に理由を表示します。';
 const actionResult=$('action-result');
 actionResult.replaceChildren();
 if(action){
  const report=actionReport(action.id,record);
  const label=report?.status==='executed'?'指定した行動を開始しました。':report?'指定を実行できませんでした。'+reasonText(report.reason)+'。':'指定済み。現在の入力での実行結果は未計算です。';
  const status=node('p',label,actionResult,'notice');
  status.dataset.tone=report&&report.status!=='executed'?'warning':'';
  if(action.kind==='charged'){
   const plan=draft.shield_decisions.find(item=>item.action_id===action.id);
   const applied=record?.shields.get(action.id);
   const choice=plan?(plan.use_shield?'使う':'使わない'):'指定なし';
   const used=applied?.used===true?'使用':applied?.used===false?'未使用':applied?'適用されず':'未計算';
   node('p',sides[1-actor]+'のシールド　指定 '+choice+'／結果 '+used+
    (applied?.reason?'（'+reasonText(applied.reason)+'）':''),actionResult);
  }
  const phases=phaseReport(action.id,record);
  if(phases.length){
   const links=node('div',null,actionResult,'row');
   for(const event of phases)button(links,phaseNames[event.phase]+' T'+event.turn,()=>goTo(event.turn,event.actor,true));
   if(action.kind!=='wait'&&!phases.some(event=>event.phase==='resolve'))node('p','ダメージ解決の記録なし',actionResult,'muted');
  }
 }
 const list=$('turn-events');
 list.replaceChildren();
 if(!events.length)node('li',record?.result.trace?'このターンの記録はありません。':'現在の入力の記録は計算後に表示します。',list,'muted');
 for(const event of events){
  const detail=node('details',null,node('li',null,list),'event side-'+event.actor);
  const origin=event.action_id?'指定':'自動';
  const damage=event.actual_damage!=null?' · ダメージ '+event.actual_damage:'';
  node('summary',sides[event.actor]+' · '+phaseNames[event.phase]+' · '+describe(event)+'（'+origin+'）'+damage,detail);
  eventState(detail,event);
  const linked=draft.actions.find(item=>item.id===event.action_id);
  if(linked&&linked.turn!==turn)button(detail,'指定した T'+linked.turn+' へ',()=>visitAction(linked));
 }
}
function renderComparison(){
 const parent=$('comparison');
 parent.replaceChildren();
 const script=currentScript()?.result;
 const normal=currentStandard();
 if(!script&&!normal){node('p','計算すると結果を表示します。',parent,'muted');return;}
 const sandbox=script?.summary;
 const table=node('table',null,parent);
 const head=node('tr',null,node('thead',null,table));
 for(const text of ['結果','サンドボックス','通常対戦'])node('th',text,head).scope='col';
 const body=node('tbody',null,table);
 const moveDamage=(result,kind)=>result?.damage?.map(side=>side[kind]).join(' / ');
 for(const [label,left,right] of [
  ['判定',script?.status==='complete'?displayStatus(sandbox):displayStatus(script),displayStatus(normal)],
  ['評価',script?.status==='complete'?sandbox.rating:null,normal?.status==='complete'?normal.rating:null],
  ['残りHP（自分 / 相手）',sandbox?.terminal.map(side=>side.hp).join(' / '),normal?.terminal?.map(side=>side.hp).join(' / ')],
  ['消費シールド（自分 / 相手）',sandbox?.shields_used.join(' / '),normal?.shields_used?.join(' / ')],
  ['通常技ダメージ（自分 / 相手）',moveDamage(sandbox,'fast'),moveDamage(normal,'fast')],
  ['ゲージ技ダメージ（自分 / 相手）',moveDamage(sandbox,'charged'),moveDamage(normal,'charged')],
  ['計算ターン',sandbox?.turns,normal?.turns]
 ]){
  const row=node('tr',null,body);
  node('th',label,row).scope='row';
  node('td',left??'—',row);
  node('td',right??'—',row);
 }
 if(script?.status==='partial'||normal?.status==='partial')node('p','途中経過の数値を含みます。',parent,'muted');
 if(normal?.error)node('p',normal.error.message,parent,'muted');
}
function renderSave(){
 const meta=saved.get(draft.tacticId);
 const historical=draft.historicalRevision;
 const dirty=!meta||meta.key!==scriptKey()||meta.name!==$('tactic-name').value.trim();
 $('save').textContent=historical?'別の戦術として保存':meta?'新しい版を保存':'戦術を保存';
 $('save-status').textContent=historical?'過去の版 '+historical+' を編集中。別の戦術として保存できます。':
  meta?'保存済みの版 '+meta.revision+(dirty?' · 未保存の変更あり':''):'未保存の戦術';
}
function render(){
 const record=currentScript();
 const status=$('script-status');
 const result=record?.result;
 const rejected=result?.summary?.action_results.filter(item=>item.status!=='executed').length||0;
 const refused=result?.shield_results?.filter(item=>item.reason).length||0;
 status.textContent=result?(result.status==='complete'?displayStatus(result.summary):displayStatus(result))+
  (result.summary?' · '+result.summary.turns+'ターン':'')+
  (rejected?' · 未実行 '+rejected+'件':'')+(refused?' · シールド適用なし '+refused+'件':''):
  scripted?'入力が変わりました。全ターンを再計算してください。':'ターンの記録は計算後に表示します。';
 status.dataset.tone=result&&result.status!=='complete'?(result.status==='partial'?'warning':'error'):rejected||refused?'warning':'';
 stateCards($('initial'),result?.initial,'開始状態');
 renderTimeline();
 renderEditor();
 renderComparison();
 renderSave();
 refreshButtons();
}

function showTacticProgress(data){
 const coverage=data.coverage;
 if(!data.search_id||!coverage||data.live_reproducibility!=='not_verified')
  throw Error('探索結果の形式を確認できませんでした。');
 $('search-status').textContent='候補 '+coverage.planned_scripts+'件 · 検証 '+coverage.attempted_scripts+
  '件 · 完全な計算 '+coverage.complete_scripts+'件 · 指定どおり実行 '+coverage.fully_executed_scripts+
  '件 · 残り '+coverage.remaining_scripts+'件'+
  (data.state==='blocked'?' · 検証停止':data.state==='stale'?' · 計算条件が古くなりました':'');
 $('search-status').dataset.tone=data.state==='blocked'||data.state==='stale'?'warning':'';
 const list=$('search-results');list.replaceChildren();
 const titles={original:'元の戦術',shield_no:'相手はシールドを使わない',shield_yes:'相手はシールドを使う',
  alternate_charged:'相手が別のゲージ技を指定',
  alternate_charged_self_shield:'相手の別技に自分のシールドを指定'};
 for(const item of data.results.slice(-8)){
  const line=node('p',null,list,'inset');
  const label=Object.hasOwn(titles,item.response)?titles[item.response]:item.response;
  line.textContent=(item.index+1)+'件目 · '+item.strategy+' · '+label+' · '+
   (item.status==='complete'?(outcomes[item.outcome]||item.outcome):'未完了')+
   (item.all_self_executed&&item.opponent_response_executed&&item.all_requested_shields_honored
    ?' · 指定動作・シールドを確認':' · 指定動作またはシールドが未実行');
 }
 if(coverage.attempted_scripts>8)node('p','直近8件を表示しています。',list,'muted');
 if(data.state==='blocked')announce('探索を安全に停止しました。'+data.incomplete_reason,'warning');
 else if(data.state==='stale')announce('探索開始時と計算バージョンが異なります。候補を作り直してください。','warning');
 refreshButtons();
}
const observedStorage='pokemoniv:observed-search-v2';
let observedJob=null;
function renderObserved(data){
 observedJob=data;
 const reason={policy_limit:'方策数の上限',work_limit:'再生回数の上限',
  incomplete:'未対応または未完了のシナリオあり',policy_found:'宣言範囲の検証を完了',
  no_policy_in_declared_class:'宣言した方策範囲の探索を完了'};
 const role=data.role===true?'宣言した全シナリオで成立':
  data.role===false?'宣言した方策範囲で成立せず':'未確定';
 const status=data.status==='stale'?'計算バージョンが変わりました。新しく開始してください。':
  role+' · 再生 '+data.work+' 回 · '+data.scenario_count+' シナリオ'+
  (data.paused?' · 一時停止中':data.stop_reason?' · '+(reason[data.stop_reason]||'停止'):' · 検証を続けられます');
 $('observed-status').textContent=status;
 try{sessionStorage.setItem(observedStorage,data.search_id);}catch{}
}
async function beginObserved(spec){
 const {actions,shield_decisions,policies,...battle}=spec;
 const data=await api('sandbox',{action:'observed_start',worlds:[battle],horizon:500,
  controllers:[{attack:'standard',shield:'standard'},{attack:'charge_if_ready',shield:'never'}],
  branches:[{fast_delay:0,miss_first_fast:false,reverse_fast_batch:false},
   {fast_delay:1,miss_first_fast:true,reverse_fast_batch:false}]});
 renderObserved(data);
}
async function observedOperation(action){
 let search_id=observedJob?.search_id;
 if(!search_id){try{search_id=sessionStorage.getItem(observedStorage);}catch{}}
 if(!/^[a-f0-9]{64}$/.test(search_id||''))throw Error('保存済み探索がありません。');
 const args={action,search_id};
 if(action==='observed_step'){
  if(!observedJob||observedJob.status!=='pending')throw Error('探索を取得して、停止中なら再開してください。');
  Object.assign(args,{expected_work:observedJob.work,budget:8});
 }
 renderObserved(await api('sandbox',args));
}
async function beginTacticSearch(spec){
 announce('戦術候補を作成しています。この操作では対戦計算しません。');
 const key=scriptKey();
 const data=await api('sandbox',{action:'search_start',spec});
 if(!/^[a-f0-9]{64}$/.test(data.search_id))throw Error('探索IDを読み取れませんでした。');
 tacticSearchId=data.search_id;tacticSearchKey=key;
 showTacticProgress(data);
 try{
  const old=JSON.parse(sessionStorage.getItem(tacticLinkKey)||'null');
  if(/^[a-f0-9]{64}$/.test(old?.evaluation_id)&&Array.isArray(old.search_ids)){
   const search_ids=[...new Set([...old.search_ids,data.search_id])].slice(-6);
   sessionStorage.setItem(tacticLinkKey,JSON.stringify({...old,search_ids}));
   $('search-to-missing').hidden=false;
  }
 }catch{}
 announce('候補ができました。必要な件数だけ検証してください。');
}
async function advanceTacticSearch(){
 if(!tacticSearchId||tacticSearchKey!==scriptKey())
  throw Error('対戦条件が変わっています。候補を作り直してください。');
 announce('候補を最大4件検証しています。途中結果は保存します。');
 const data=await api('sandbox',{action:'search_step',search_id:tacticSearchId,budget:4});
 showTacticProgress(data);
 if(data.state!=='blocked'&&data.state!=='stale')
  announce('探索記録を更新しました。理論上の戦術であり、実戦再現性は未検証です。','warning');
}
async function saveTactic(spec){
 const name=$('tactic-name').value.trim();
 if(!name||[...name].length>64)throw Error('戦術名は1〜64文字で入力してください。');
 const fork=draft.historicalRevision!=null;
 const id=fork?newId():draft.tacticId;
 const revision=fork?0:saved.get(id)?.revision||0;
 announce('戦術を保存しています。');
 const record=await api('sandbox',{action:'save',tactic_id:id,expected_revision:revision,name,spec});
 if(record.tactic_id!==id||!Number.isInteger(record.revision))throw Error('保存した戦術の版を読み取れませんでした。');
 draft={...draft,tacticId:id,historicalRevision:null};
 saved.set(id,{revision:record.revision,name:record.name,key:scriptKey()});
 $('tactic-name').value=record.name;
 renderSave();
 announce('戦術「'+record.name+'」を版 '+record.revision+' として保存しました。');
}
async function listTactics(){
 announce('保存した戦術を読み込んでいます。');
 const data=await api('sandbox',{action:'list'});
 if(!Array.isArray(data.items))throw Error('保存一覧を読み取れませんでした。');
 options($('tactics'),[['','戦術を選ぶ'],...data.items.map(item=>[item.tactic_id,item.name+'（最新版 '+item.revision+'）'])],$('tactics').value);
 data.items.forEach((item,index)=>{$('tactics').options[index+1].dataset.revision=item.revision;});
 $('load-form').hidden=!data.items.length;
 updateRevision();
 announce(data.items.length?'復元する戦術を選んでください。':'保存した戦術はまだありません。');
}
function updateRevision(){
 $('revision').value='';
 const max=$('tactics').selectedOptions[0]?.dataset.revision;
 if(max)$('revision').max=max;
 else $('revision').removeAttribute('max');
}
async function loadTactic(tacticId,revision){
 announce('戦術を復元しています。');
 const record=await api('sandbox',{action:'load',tactic_id:tacticId,...(revision?{revision}:{})});
 const historical=record.revision<record.latest_revision;
 const next=fromSpec(record.spec,record.tactic_id,historical?record.revision:null);
 commitDraft(next);
 if(!historical)saved.set(record.tactic_id,{revision:record.revision,name:record.name,key:scriptKey()});
 $('tactic-name').value=record.name;
 turn=draft.actions[0]?.turn||1;
 actor=draft.actions[0]?.actor||0;
 renderSetup(false);
 render();
 announce('戦術「'+record.name+'」の版 '+record.revision+' を復元しました。'+
  (record.current?'全ターンを計算すると記録を確認できます。':'計算データが更新されています。現在のデータで再計算してください。'),
  record.current?'':'warning');
}
function importSpec(){
 let raw;
 try{raw=sessionStorage.getItem(importKey);}
 catch{return false;}
 if(!raw)return false;
 sessionStorage.removeItem(importKey);
 const spec=JSON.parse(raw);
 if(spec.mode!=='standard')throw Error('不足分析の通常対戦を読み込めませんでした。');
 commitDraft(fromSpec(spec));
 return true;
}
async function connect(manual){
 if(manual)credential=$('credential').value.trim();
 announce('ポケモンと技の一覧を読み込んでいます。');
 try{
  const data=await api('catalog',{});
  if(!data.ready||!data.species)throw Error(data.error||'一覧の準備中です。接続するを押して再試行してください。');
  indexCatalog(data.species,data.moves||{});
 }catch(error){
  credential='';
  $('connection').hidden=false;
  if(error.status===401)announce('接続キーを入力してください。',manual?'warning':'');
  else announce(error.message,'error');
  return;
 }
 $('credential').value='';
 $('connection').hidden=true;
 $('workspace').hidden=false;
 $('tactic-search-panel').hidden=$('tactic-search-panel').dataset.tacticSearch!=='1';
 $('observed-panel').hidden=$('observed-panel').dataset.observedSearch!=='1';
 if(!$('observed-panel').hidden&&new URLSearchParams(location.search).get('observed')==='1')
  $('observed-details').open=true;
 let imported=false,importError=false;
 try{imported=importSpec();}
 catch{importError=true;}
 renderSetup(!imported);
 render();
 if(importError)announce('不足分析から対戦条件を読み込めませんでした。入力欄から条件を指定できます。','warning');
 else announce(imported?'不足分析から両者の個体・技・開始状態を読み込みました。':'両者の個体・技・開始状態を入力してください。');
}
$('login-form').addEventListener('submit',event=>{event.preventDefault();perform(()=>connect(true));});
$('setup').addEventListener('submit',event=>event.preventDefault());
$('setup').addEventListener('invalid',event=>{
 for(let element=event.target.parentElement;element;element=element.parentElement){
  if(element.tagName==='DETAILS')element.open=true;
 }
},true);
$('jump-form').addEventListener('submit',event=>{event.preventDefault();goTo($('jump-turn').valueAsNumber);});
$('previous-turn').addEventListener('click',()=>goTo(turn-1));
$('next-turn').addEventListener('click',()=>goTo(turn+1));
$('previous-action').addEventListener('click',()=>visitAction(neighborAction(-1)));
$('next-action').addEventListener('click',()=>visitAction(neighborAction(1)));
$('action-choice').addEventListener('change',chooseAction);
$('action-form').addEventListener('submit',editAction);
$('remove-action').addEventListener('click',removeAction);
$('simulate').addEventListener('click',()=>withSpec('sandbox',simulate));
$('standard').addEventListener('click',()=>withSpec('standard',simulateStandard));
$('observed-start').addEventListener('click',()=>withSpec('standard',spec=>beginObserved({...spec,mode:'sandbox'})));
for(const operation of ['step','stop','resume','get']){
 $('observed-'+operation).addEventListener('click',()=>perform(()=>observedOperation('observed_'+operation)));
}
$('search-start').addEventListener('click',()=>withSpec('sandbox',beginTacticSearch));
$('search-step').addEventListener('click',()=>perform(advanceTacticSearch));
$('undo').addEventListener('click',()=>changeHistory(undo,redo));
$('redo').addEventListener('click',()=>changeHistory(redo,undo));
$('tactic-name').addEventListener('input',renderSave);
$('save-form').addEventListener('submit',event=>{event.preventDefault();withSpec('sandbox',saveTactic);});
$('list').addEventListener('click',()=>perform(listTactics));
$('tactics').addEventListener('change',updateRevision);
$('load-form').addEventListener('submit',event=>{
 event.preventDefault();
 const id=$('tactics').value,revision=$('revision').valueAsNumber;
 if(id)perform(()=>loadTactic(id,revision));
});
perform(()=>connect(false));
</script>
</body>
</html>'''
