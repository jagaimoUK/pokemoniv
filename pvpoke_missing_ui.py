"""Mobile-first, owner-scoped missing Pokémon analysis page."""

HTML = r'''<!doctype html>
<html lang="ja">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>不足ポケモン分析</title>
<style>
:root{color-scheme:dark;font:16px/1.55 system-ui,sans-serif;color:#e7f4ec;background:#122126;--muted:#b5cdc2;--border:#4e7066;--surface:#203438;--inset:#172a2e;--accent:#bdebd0}
[hidden]{display:none!important}*{box-sizing:border-box}body{margin:0}main{max-width:48rem;margin:auto;padding:1rem max(12px,env(safe-area-inset-right)) 3rem max(12px,env(safe-area-inset-left))}main>*+*{margin-top:1rem}
h1,h2,h3,p{margin:0}h1{font-size:clamp(1.75rem,6vw,2.25rem)}h2{font-size:1.15rem}h3{font-size:1rem}header p,.intro,.muted,legend,small{color:var(--muted)}header p,.intro{margin-top:.4rem}
nav,.actions,.tags{display:flex;flex-wrap:wrap;gap:.55rem;align-items:center}a{color:var(--accent)}nav a{padding:.5rem .25rem;min-height:44px}
section,.panel{min-width:0;padding:clamp(.75rem,3vw,1.2rem);background:var(--surface);border:1px solid var(--border);border-radius:1rem}.stack{display:grid;gap:.75rem}.stack>*{min-width:0}
fieldset{border:0;padding:0;margin:0;min-width:0}legend{font-size:.875rem;padding:0}label{display:grid;min-width:0;gap:.2rem;font-size:.875rem;font-weight:600}
input,select,button{font:inherit;color:inherit;min-height:44px;border:1px solid #698f81;border-radius:.65rem}input,select{width:100%;min-width:0;padding:.45rem .55rem;background:var(--inset);font-size:1rem}button{background:#35594d;padding:.45rem .75rem;cursor:pointer}button:disabled{opacity:.55;cursor:default}button.primary{background:var(--accent);color:#112b23;font-weight:700;border-color:var(--accent)}button.quiet{background:var(--inset)}
:focus-visible{outline:2px solid #d4f8a9;outline-offset:3px}summary{min-height:44px;padding:.58rem 0;cursor:pointer;font-weight:650;overflow-wrap:anywhere}summary+*{margin-top:.35rem}
.grid{display:grid;gap:.55rem;grid-template-columns:repeat(2,minmax(0,1fr))}.ivs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.55rem}.wide{grid-column:1/-1}
.edit,.role,.candidate,.match{border:1px solid var(--border);border-radius:.8rem;background:var(--inset);padding:0 .7rem}.edit[open],.role[open],.candidate[open],.match[open]{padding-bottom:.7rem}.role,.match{background:#263f40}
.tag{display:inline-block;border:1px solid #74978b;border-radius:99px;padding:.12rem .5rem;font-size:.85rem}.tag.good{color:#c9fad6}.tag.wait{color:#f7e0a7}.tag.fail{color:#ffc6c0}
.status{padding:.65rem .85rem;border-left:3px solid var(--accent);background:var(--inset);white-space:pre-wrap}.status[data-error=true]{border-color:#ffaaa2;color:#ffd5d1}
.check{display:flex;align-items:center;gap:.6rem;min-height:44px}.check input{width:1.15rem;height:1.15rem;min-height:0;flex:none}.comparisons,.inventory{padding-left:1.1rem;margin:0}.comparisons li+li,.inventory li+li{margin-top:.55rem}
.record{padding:.45rem 0}.record summary{font-size:.875rem}.break{overflow-wrap:anywhere}.results{scroll-margin-top:1rem}
@media(min-width:40rem){.moves{grid-template-columns:repeat(3,minmax(0,1fr))}.moves .wide{grid-column:auto}}
@media(max-width:24rem){.actions button{max-width:100%}.match{padding-left:.45rem;padding-right:.45rem}}
</style></head>
<body><main>
<nav aria-label="アプリ内ナビゲーション"><a href="/app">← 個体値厳選</a><a href="/app/party">パーティ作成</a></nav>
<header><h1>不足ポケモン分析</h1><p>スーパーリーグで必要な役割を決め、探したい個体と手持ちの候補を、同じ対面条件で比べます。</p></header>
<section id="login" hidden><form id="login-form" class="stack"><h2>アプリに接続</h2><label>接続キー<input id="credential" type="password" autocomplete="off" required></label><div class="actions"><button class="primary" data-action>接続する</button></div></form></section>
<p id="status" class="status" role="status" aria-live="polite">接続を確認しています。</p>
<div id="workspace" class="stack" hidden>
<form id="analysis-form" class="stack">
<section class="stack"><div><h2>探したいポケモンと役割</h2><p class="intro">基準にする個体のフォルム・個体値・レベル・技を指定します。</p></div>
<div id="reference"></div><div class="grid"><label>役割<select id="role"><option value="lead">初手</option><option value="safe_switch">引き先</option><option value="closer">締め</option><option value="coverage">苦手対面の補完</option></select></label><label>優先度<select id="priority"><option value="1">標準</option><option value="2">高い</option><option value="3">最優先</option></select></label></div></section>
<section class="stack"><div><h2>確認する対面</h2><p class="intro">相手の構成と、自分が果たす条件を指定します。最大6件です。</p></div><div id="scenarios" class="stack"></div><div class="actions"><button id="add-scenario" type="button" class="quiet" data-action>対面を追加</button></div></section>
<section class="stack"><div><h2>比較する個体</h2><p class="intro">同じポケモンの別個体や、別のポケモンを最大7体追加できます。手持ちの確認は結果から行えます。</p></div><div id="alternatives" class="stack"></div><div class="actions"><button id="add-alternative" type="button" class="quiet" data-action>比較する個体を追加</button></div></section>
<div class="actions"><button id="evaluate" class="primary" data-action>保存済みの対面結果を照合</button></div>
</form>
<section id="tactic-evidence-panel" class="results stack" hidden><h2>Sandbox戦術の根拠</h2>
<p>標準計算と指定戦術は別の結果です。実戦再現性は未検証で、所持・役割の判定は変更しません。</p>
<div class="actions"><button id="tactic-evidence-read" type="button" data-action>保存済み戦術を不足分析と照合</button></div>
<div id="tactic-evidence-results" class="stack"></div></section>
<section id="results" class="results stack" aria-labelledby="results-heading" hidden><h2 id="results-heading" tabindex="-1">不足分析の結果</h2><p id="edited" class="muted" hidden>入力が変更されました。表示中の結果は前回の条件です。</p><div id="result-tree"></div></section>
</div>
<datalist id="pokemon-list"></datalist>
</main><script>
'use strict';
const $=id=>document.getElementById(id);
const maxAlternatives=7,maxScenarios=6;
const roles={lead:'初手',safe_switch:'引き先',closer:'締め',coverage:'苦手対面の補完'};
const priorities={1:'標準',2:'高い',3:'最優先'};
const metrics={hp:['自分の残りHP',10000],energy:['自分の残りゲージ',100],fast_damage:['通常技の総ダメージ',10000],charged_damage:['ゲージ技の総ダメージ',10000],charged_moves_resolved:['ゲージ技を撃った回数',2000],shields_forced:['相手に使わせたシールド',2],shields_remaining:['自分の残りシールド',2]};
const assessment={sufficient:['条件を満たす','good'],conditional:['開始ゲージ条件付きで達成','wait'],unavailable:['条件を満たさない','fail'],pending:['未評価の対面あり','wait']};
const gaps={covered:['所持確認済みの個体で充足','good'],gap:['比較した範囲で不足','fail'],ownership_confirmation_needed:['所持確認待ち','wait'],evidence_pending:['対戦証拠待ち','wait']};
const substitutes={sufficient:['十分に代替（この役割）','good'],conditional:['条件付き代替','wait'],unavailable:['代替不可（指定条件）','fail'],pending:['判定保留','wait']};
const outcomes={self_win:'勝ち',opponent_win:'負け',simultaneous_ko:'同時ひんし'};
const ownership={confirmed_owned:'所持確認済み',confirmed_absent:'所持していないことを確認済み',unknown:'未確認'};
const builds={exact:'個体値・CP・Lv・技が一致',unverified:'一致の判定に必要な情報が不足',different:'CP・Lv・技のいずれかが異なる'};
let credential='',catalog=Object.create(null),moves={},speciesNames=new Map(),busy=false,editRevision=0,displayed=null;
let reference;
const alternatives=[],scenarios=[];
const tacticLinkKey='pokemoniv:tactic-evidence-link-v1';

function node(tag,text,parent,cls){
 const el=document.createElement(tag);
 if(text!=null)el.textContent=text;
 if(cls)el.className=cls;
 if(parent)parent.append(el);
 return el;
}
function button(parent,text,handler,cls){
 const el=node('button',text,parent,cls);
 el.type='button';el.dataset.action='';el.disabled=busy;el.addEventListener('click',handler);
 return el;
}
function detail(parent,label,cls,open=false){
 const el=node('details',null,parent,cls);el.open=open;node('summary',label,el);return el;
}
function input(parent,label,properties,cls){
 const wrap=node('label',label,parent,cls);
 const field=node('input',null,wrap);Object.assign(field,properties);return field;
}
function select(parent,label,options,cls){
 const field=node('select',null,node('label',label,parent,cls));
 setOptions(field,options);return field;
}
function setOptions(field,options,value){
 field.replaceChildren(...options.map(([id,text])=>{const o=node('option',text);o.value=id;return o;}));
 if(options.some(([id])=>id===value))field.value=value;
}
function tag(parent,text,tone){return node('span',text,parent,'tag'+(tone?' '+tone:''));}
function announce(text,error=false){$('status').textContent=text;$('status').dataset.error=String(error);}
function setBusy(value){
 busy=value;
 document.querySelectorAll('[data-action]').forEach(el=>{el.disabled=value;});
 $('add-scenario').disabled=value||scenarios.length>=maxScenarios;
 $('add-alternative').disabled=value||alternatives.length>=maxAlternatives;
 $('results').setAttribute('aria-busy',String(value));
}
async function api(path,body){
 const headers={'Content-Type':'application/json'};
 if(credential)headers.Authorization='Bearer '+credential;
 const response=await fetch('/app-api/'+path,{method:'POST',headers,credentials:'same-origin',body:JSON.stringify(body)});
 const result=await response.json().catch(()=>null);
 if(!response.ok||!result){
  const message=result?.error?.message||result?.error||'サーバー応答を読み取れませんでした。';
  const error=new Error(message);error.status=response.status;throw error;
 }
 return result;
}
async function perform(task){
 if(busy)return;
 setBusy(true);
 try{await task();}catch(error){announce(error.message,true);}finally{setBusy(false);}
}
const normalize=value=>String(value).normalize('NFKC').trim().toLowerCase();
const name=id=>catalog[id]?.name_ja||catalog[id]?.name||id;
const nameWithId=id=>name(id)+' / '+id;
const move=id=>moves[id]?.name_ja||moves[id]?.name||id;
function resolveSpecies(value){
 const found=speciesNames.get(normalize(value));
 return found?.size===1?[...found][0]:'';
}
function speciesList(entries){
 catalog=Object.assign(Object.create(null),entries);
 speciesNames=new Map();
 const options=[];
 for(const id of Object.keys(catalog).sort((a,b)=>name(a).localeCompare(name(b),'ja'))){
  const pokemon=catalog[id];
  const option=node('option',null);option.value=nameWithId(id);options.push(option);
  for(const alias of [id,pokemon.name,pokemon.name_ja,option.value,...(pokemon.aliases||[])].filter(Boolean)){
   const key=normalize(alias);
   if(!speciesNames.has(key))speciesNames.set(key,new Set());
   speciesNames.get(key).add(id);
  }
 }
 $('pokemon-list').replaceChildren(...options);
}
const ivText=ivs=>[ivs.attack,ivs.defense,ivs.hp].join('/');
const moveText=build=>[build.moves.fast,...build.moves.charged].map(move).join('・');
const buildText=build=>name(build.species_id)+' '+ivText(build.ivs)+(build.level==null?'':' / Lv'+build.level);

function buildEditor(parent,title,{open=false,removable,initial}={}){
 const el=detail(parent,title,'edit',open);
 const body=node('div',null,el,'stack');
 const species=input(body,'ポケモン・フォルム',{type:'text',required:true,placeholder:'例：マリルリ',autocomplete:'off'});
 species.setAttribute('list','pokemon-list');
 const ivGroup=node('fieldset',null,body);node('legend','個体値',ivGroup);
 const ivFields=node('div',null,ivGroup,'ivs');
 const ivs=Object.fromEntries([['attack','攻撃'],['defense','防御'],['hp','HP']].map(([id,label])=>[id,input(ivFields,label,{type:'number',min:0,max:15,step:1,required:true})]));
 const level=input(body,'対戦時のレベル（1〜50、0.5刻み）',{type:'number',min:1,max:50,step:.5,required:true});
 const moveFields=node('div',null,body,'grid moves');
 const fast=select(moveFields,'通常技',[['','ポケモンを指定']],'wide');
 const charged=[select(moveFields,'ゲージ技1',[['','ポケモンを指定']]),select(moveFields,'ゲージ技2',[['','ポケモンを指定']])];
 for(const field of [fast,...charged])field.required=true;
 let speciesId='';
 function updateSpecies(preferred){
  const id=resolveSpecies(species.value);
  if(id!==speciesId||preferred){
   speciesId=id;
   const pokemon=catalog[id]||{};
   const defaults=pokemon.default_moves||{};
   const fastPool=(pokemon.fastMoves||[]).map(id=>[id,move(id)]);
   const chargePool=(pokemon.chargedMoves||[]).map(id=>[id,move(id)]);
   setOptions(fast,[['','通常技を選ぶ'],...fastPool],preferred?.fast||defaults.fast);
   setOptions(charged[0],[['','ゲージ技を選ぶ'],...chargePool],preferred?.charged[0]||defaults.charged1);
   setOptions(charged[1],[['','ゲージ技を選ぶ'],...chargePool],preferred?.charged[1]||defaults.charged2);
  }
  species.setCustomValidity(species.value&&!id?'一覧からフォルムまで選択してください。':'');
  el.firstElementChild.textContent=title+(id?' · '+name(id):'');
 }
 function validateMoves(){charged[1].setCustomValidity(charged[0].value&&charged[0].value===charged[1].value?'異なるゲージ技を選んでください。':'');}
 species.addEventListener('input',()=>{updateSpecies();validateMoves();});
 species.addEventListener('change',()=>{updateSpecies();validateMoves();});
 for(const field of charged)field.addEventListener('change',validateMoves);
 if(initial){
  species.value=nameWithId(initial.species_id);
  for(const [id,field] of Object.entries(ivs))field.value=initial.ivs[id];
  level.value=initial.level;
  updateSpecies(initial.moves);
 }
 if(removable)button(body,'この項目を削除',()=>removable(el),'quiet');
 return {el,body,species,fields:[species,...Object.values(ivs),level,fast,...charged],read:()=>({species_id:speciesId,ivs:Object.fromEntries(Object.entries(ivs).map(([id,field])=>[id,field.valueAsNumber])),level:level.valueAsNumber,moves:{fast:fast.value,charged:charged.map(field=>field.value)}})};
}
function removeEditor(list,el){list.splice(list.findIndex(item=>item.el===el),1);el.remove();markEdited();setBusy(false);}
function addAlternative(){
 if(alternatives.length>=maxAlternatives)return;
 const candidate=reference.fields.every(field=>field.validity.valid)?reference.read():null;
 const editor=buildEditor($('alternatives'),'比較個体',{open:true,initial:candidate,removable:el=>removeEditor(alternatives,el)});
 alternatives.push(editor);markEdited();setBusy(false);editor.species.focus();
}
function addScenario(focus){
 if(scenarios.length>=maxScenarios)return;
 const editor=buildEditor($('scenarios'),'対面の相手',{open:true,removable:el=>removeEditor(scenarios,el)});
 const grid=node('div',null,editor.body,'grid');
 const shields=[[0,'0枚'],[1,'1枚'],[2,'2枚']];
 const selfShield=select(grid,'自分のシールド',shields);
 const opponentShield=select(grid,'相手のシールド',shields);
 selfShield.value='1';opponentShield.value='1';
 const result=select(editor.body,'必要な結果',[['win','勝ち'],['win_or_tie','勝ちか引き分け'],['minimum','勝敗を問わず数値条件で判断']]);
 const advanced=detail(editor.body,'開始ゲージ・数値条件');
 const extra=node('div',null,advanced,'grid');
 const energy=input(extra,'自分の開始ゲージ',{type:'number',min:0,max:100,step:1,value:0,required:true},'wide');
 const metric=select(extra,'最低限必要な指標',[['','指定なし'],...Object.entries(metrics).map(([id,[label]])=>[id,label])]);
 const minimum=input(extra,'最低値',{type:'number',min:0,max:10000,step:1,required:true,disabled:true});
 function validateMinimum(){
  minimum.disabled=!metric.value;
  minimum.max=metrics[metric.value]?.[1]??10000;
  metric.setCustomValidity(result.value==='minimum'&&!metric.value?'数値条件を選んでください。':'');
 }
 result.addEventListener('change',()=>{if(result.value==='minimum')advanced.open=true;validateMinimum();});
 metric.addEventListener('change',validateMinimum);
 editor.scenario=()=>{
  const requirement={};
  if(result.value==='win')requirement.outcomes=['self_win'];
  if(result.value==='win_or_tie')requirement.outcomes=['self_win','simultaneous_ko'];
  if(metric.value)requirement.minimum={[metric.value]:minimum.valueAsNumber};
  return {opponent:editor.read(),shields:[Number(selfShield.value),Number(opponentShield.value)],energy:energy.valueAsNumber,requirement};
 };
 scenarios.push(editor);
 if(focus){markEdited();editor.species.focus();}
 setBusy(false);
}
function markEdited(){editRevision+=1;if(displayed)$('edited').hidden=editRevision===displayed.revision;}

function conditionKey(condition){
 return JSON.stringify([condition.spec?.combatants?.[1]||condition.opponent,condition.shields,condition.spec?.combatants?.[0]?.initial?.energy]);
}
function conditionResult(condition){
 if(condition.state==='stale')return ['計算データ更新・再確認が必要','wait'];
 if(condition.meets===true)return ['条件達成','good'];
 if(condition.meets===false)return ['条件未達','fail'];
 return ['未計算・結果なし','wait'];
}
function heldLabel(candidate){
 if(candidate.owned_instances.some(record=>record.state==='confirmed_owned'&&record.build_match==='exact'))return '条件どおりの個体を所持確認済み';
 if(candidate.owned_instances.some(record=>record.state==='confirmed_owned'))return '同じ個体値の所持記録あり';
 if(candidate.owned_instances.some(record=>record.state==='confirmed_absent'))return '所持していない確認記録あり';
 return '所持未確認';
}
function requirementText(requirement){
 const parts=(requirement?.outcomes||[]).map(id=>outcomes[id]||id);
 const limits=Object.entries(requirement?.minimum||{}).map(([id,value])=>(metrics[id]?.[0]||id)+' '+value+'以上');
 return [parts.join('または'),...limits].filter(Boolean).join('、');
}
function battleFacts(parent,facts){
 if(!facts)return;
 const outcome=outcomes[facts.outcome]||facts.outcome;
 const own=facts.terminal?.[0];
 const other=facts.terminal?.[1];
 const damage=facts.damage?.[0];
 const stats=[['判定',outcome],['バトル評価',facts.rating],['残りHP（自分 / 相手）',own&&other?own.hp+' / '+other.hp:null],['通常技 / ゲージ技のダメージ',damage?damage.fast+' / '+damage.charged:null],['消費シールド（自分 / 相手）',facts.shields_used?.join(' / ')]];
 for(const [label,value] of stats)if(value!=null)node('p',label+'　'+value,parent);
}
function comparisonLabel(candidate,baseline){
 if(candidate.build_id===baseline.build_id)return '基準個体';
 return candidate.comparison==='same_species'?'同種の別個体':'別種の代替候補';
}
function renderMatch(parent,condition,current,result,request){
 const shieldLabel=condition.shields.join(' / ');
 const box=detail(parent,buildText(condition.opponent)+' · シールド '+shieldLabel,'match');
 const body=node('div',null,box,'stack');
 const status=node('div',null,body,'tags');tag(status,...conditionResult(condition));
 const start=condition.spec?.combatants?.[0]?.initial?.energy;
 const scenario=request.scenarios.find(row=>row.opponent.species_id===condition.opponent.species_id
  && ivText(row.opponent.ivs)===ivText(condition.opponent.ivs)
  && row.opponent.level===(condition.opponent.level??condition.spec?.combatants?.[1]?.level)
  && row.opponent.moves.fast===condition.opponent.moves.fast
  && row.opponent.moves.charged.join()===condition.opponent.moves.charged.join()
  && row.shields.join()===condition.shields.join()&&row.energy===start);
 node('p','相手の技　'+moveText(condition.opponent),body,'muted');
 if(start!=null)node('p','自分の開始ゲージ　'+start,body,'muted');
 const requirement=requirementText(condition.requirement||scenario?.requirement);
 if(requirement)node('p','必要な結果　'+requirement,body);
 if(condition.facts){
  const facts=node('div',null,body);battleFacts(facts,condition.facts);
 }else if(result.can_calculate&&condition.spec&&condition.state==='unknown'){
  const actions=node('div',null,body,'actions');
  button(actions,'この対面だけ計算',()=>simulate(condition,request),'quiet');
 }
 if(result.can_sandbox&&condition.spec){
  const actions=node('div',null,body,'actions');
  button(actions,'Sandboxで対面を開く',()=>{
   try{
    sessionStorage.setItem('pokemoniv:sandbox-input-v1',JSON.stringify(condition.spec));
    let old=null;try{old=JSON.parse(sessionStorage.getItem(tacticLinkKey)||'null');}catch{}
    const search_ids=old?.evaluation_id===result.evaluation_id&&Array.isArray(old.search_ids)
      ?old.search_ids.filter(id=>/^[a-f0-9]{64}$/.test(id)).slice(-6):[];
    sessionStorage.setItem(tacticLinkKey,JSON.stringify({evaluation_id:result.evaluation_id,
      build_id:current.build_id,search_ids}));
    location.assign('/app/sandbox');
   }catch(error){announce('対戦条件を一時保存できませんでした。',true);}
  },'quiet');
 }
 const peers=result.candidates.filter(candidate=>candidate.build_id!==current.build_id);
 if(peers.length){
  const comparison=detail(body,'この対面の手持ち・代替候補と比較');
  const list=node('ul',null,comparison,'comparisons');
  for(const peer of peers){
   const other=peer.conditions.find(item=>conditionKey(item)===conditionKey(condition));
   const row=node('li',null,list);
   node('strong',buildText(peer),row);
   node('p',comparisonLabel(peer,result.reference)+' ／ '+(other?conditionResult(other)[0]:'同じ条件の結果なし'),row);
   node('p',heldLabel(peer),row,'muted');
  }
 }
}
function checkbox(parent,text){
 const label=node('label',null,parent,'check');
 const check=node('input',null,label);check.type='checkbox';check.required=true;label.append(document.createTextNode(text));return check;
}
function registerInventory(parent,candidate,request){
 const box=detail(parent,'実物を確認して所持を記録');
 const form=node('form',null,box,'stack');
 const fields=node('div',null,form,'grid');
 const cp=input(fields,'現在のCP',{type:'number',min:10,max:10000,step:1,required:true});
 const level=input(fields,'現在のLv（任意）',{type:'number',min:1,max:51,step:.5});
 const currentMoves=checkbox(form,'現在の技がこの候補の技構成と一致している');currentMoves.required=false;
 checkbox(form,'ゲーム内で、このフォルムと個体値の所持を確認した');
 const submit=node('button','所持を記録する',node('div',null,form,'actions'),'quiet');submit.dataset.action='';submit.disabled=busy;
 const instanceId=crypto.randomUUID();
 let previous='',eventId;
 form.addEventListener('submit',event=>{
  event.preventDefault();
  const observation={species_id:candidate.species_id,ivs:candidate.ivs,current_cp:cp.valueAsNumber};
  if(level.value)observation.current_level=level.valueAsNumber;
  if(currentMoves.checked)observation.current_moves=candidate.moves;
  const encoded=JSON.stringify(observation);
  if(previous!==encoded){previous=encoded;eventId=crypto.randomUUID();}
  confirmOwnership({instance_id:instanceId,event_id:eventId,expected_revision:0,state:'confirmed_owned',observation},request,form);
 });
}
function renderInventory(parent,candidate,request){
 const box=node('div',null,parent,'stack');
 node('h3','手持ちの確認',box);node('p',heldLabel(candidate),box);
 if(candidate.owned_instances.length){
  const list=node('ul',null,box,'inventory');
  for(const record of candidate.owned_instances){
   const row=node('li',null,list);
   node('p',(ownership[record.state]||'未確認')+' ／ '+(builds[record.build_match]||'構成の一致は未確認'),row);
   if(record.state==='confirmed_absent')continue;
   const panel=detail(row,'この所持記録を更新','record');
   node('small','記録ID '+record.instance_id,panel,'break');
   const form=node('form',null,panel,'stack');
   checkbox(form,'ゲーム内で、この個体を所持していないことを確認した');
   const submit=node('button','所持していないと記録',node('div',null,form,'actions'),'quiet');submit.dataset.action='';submit.disabled=busy;
   const eventId=crypto.randomUUID();
   form.addEventListener('submit',event=>{
    event.preventDefault();confirmOwnership({instance_id:record.instance_id,event_id:eventId,expected_revision:record.revision,state:'confirmed_absent'},request,form);
   });
  }
 }
 registerInventory(box,candidate,request);
}
function renderOpponentBoundaries(panel,result){
 if(!result.can_calculate)return;
 const candidate=result.candidates.find(row=>row.build_id===result.reference.build_id);
 const conditions=(candidate?.conditions||[]).filter(row=>row.battle_key);
 if(!conditions.length)return;
 const area=node('div',null,panel,'stack');
 node('p','相手の攻撃・防御・HP個体値について、CMPと技ダメージの静的な境界を探します。対戦勝敗・実戦での役割は未検証です。',area,'muted');
 const selector=node('select',null,area);selector.setAttribute('aria-label','相手IV境界を調べる対面');
 for(const [i,row] of conditions.entries()){
  const choice=node('option','対面'+(i+1)+'：'+name(row.opponent.species_id),selector);
  choice.value=row.battle_key;
 }
 const report=node('p',null,area,'break');
 const preview=node('p',null,area,'break');
 const labels={hp:'HP',cmp:'CMP',breakpoint:'通常技与ダメージ',bulkpoint:'通常技被ダメージ',
  charged_1:'ゲージ1与ダメージ',charged_2:'ゲージ2与ダメージ',
  incoming_charged_1:'ゲージ1被ダメージ',incoming_charged_2:'ゲージ2被ダメージ'};
 button(area,'相手IV境界を確認',()=>perform(async()=>{
  const data=await api('missing-analysis',{action:'opponent_boundaries',
   evaluation_id:result.evaluation_id,build_id:candidate.build_id,battle_key:selector.value});
  report.textContent='静的境界のみ（勝敗未検証）：相手IV '+data.profiled_iv_count+' / '+data.raw_iv_count+
   '通りを評価 ／ 静的プロファイル '+data.distinct_static_profile_count+
   '種類 ／ '+Object.entries(data.boundary_counts).map(([kind,n])=>(labels[kind]||kind)+n+'件').join('・');
  preview.textContent='代表例（最大32件・勝敗未検証）：'+data.representatives.map(
   row=>row.attack+'/'+row.defense+'/'+row.hp).join('、');
  announce('相手IVの静的な境界候補を表示しました。対戦勝敗は未検証です。');
 }), 'quiet');
}
function renderExploration(parent,result){
 const panel=detail(parent,'重要IVを探索');
 const info=node('p','保存済みの対戦を照合し、役割の全条件を満たす個体値を確認します。',panel,'muted');
 const examples=node('p',null,panel,'break');
 const actions=node('div',null,panel,'actions');
 async function read(budget){
  const data=await api('missing-analysis',{action:'explore',evaluation_id:result.evaluation_id,build_id:result.reference.build_id,budget});
  info.textContent='全条件を計算済み '+data.completed_iv_count+' / '+data.eligible_iv_count+'通り ／ 達成確認済み '+data.qualifying_count+'通り ／ 全条件の検証が未完了 '+data.not_fully_tested_iv_count+'通り';
  examples.textContent=data.qualifying.length?'達成を確認したIV'+(data.qualifying_count>data.qualifying.length?'（一部）':'')+'　'+data.qualifying.map(ivText).join('、'):'';
  announce(budget?'新規対戦 '+data.new_battles+'件。探索の進捗を更新しました。':'保存済みの探索範囲を確認しました。');
 }
 button(actions,'探索範囲を確認',()=>perform(()=>read(0)),'quiet');
 if(result.can_calculate)button(actions,'1対面を追加検証',()=>perform(()=>read(1)),'quiet');
 renderOpponentBoundaries(panel,result);
}
function renderResult(result,request,revision){
 const tree=$('result-tree');tree.replaceChildren();
 const species=detail(tree,name(result.reference.species_id),'edit',true);
 const role=detail(species,roles[result.role.role_id]||result.role.role_id,'role',true);
 const cards=node('div',null,role,'stack');
 tag(node('div',null,cards,'tags'),...(gaps[result.state]||gaps.evidence_pending));
 renderExploration(cards,result);
 const conditions=result.candidates.flatMap(item=>item.conditions);
 node('p','優先度 '+(priorities[result.role.priority]||result.role.priority)+' ／ 確認済みの対面 '+conditions.filter(item=>item.state==='complete').length+' / '+conditions.length,cards,'muted');
 const sorted=[...result.candidates].sort((a,b)=>Number(b.build_id===result.reference.build_id)-Number(a.build_id===result.reference.build_id));
 for(const candidate of sorted){
  const baseline=candidate.build_id===result.reference.build_id;
  const card=detail(cards,buildText(candidate)+' · '+comparisonLabel(candidate,result.reference),'candidate',baseline);
  const body=node('div',null,card,'stack');
  const tags=node('div',null,body,'tags');
  const badges=baseline?assessment:substitutes;
  tag(tags,...(badges[candidate.status]||badges.pending));
  if(candidate.party_substitution==='pending')tag(tags,'パーティでの入替は未評価','wait');
  node('p','技構成　'+moveText(candidate),body,'muted');
  node('h3','対面ごとの結果',body);
  for(const condition of candidate.conditions)renderMatch(body,condition,candidate,result,request);
  renderInventory(body,candidate,request);
 }
 displayed={revision};$('edited').hidden=editRevision===revision;$('results').hidden=false;
}
async function evaluate(request,revision){
 const result=await api('missing-analysis',request);
 if(!result.reference||!Array.isArray(result.candidates))throw Error('分析結果を読み取れませんでした。');
 renderResult(result,request,revision);
}
function simulate(condition,request){
 const revision=displayed.revision;
 perform(async()=>{
  announce('指定した1対面を計算しています。');
  const result=await api('battles/simulate',condition.spec);
  if(result.status!=='complete')throw Error(result.error?.message||'対面の結果を確定できませんでした。');
  await evaluate(request,revision);announce('対面を計算し、保存済みの結果を照合しました。');
 });
}
function confirmOwnership(change,request,form){
 const revision=displayed.revision;
 perform(async()=>{
  announce('所持の確認を記録しています。');
  await api('missing-analysis',{action:'ownership',...change});
  form.hidden=true;
  try{await evaluate(request,revision);announce('所持の確認を記録しました。');}
  catch(error){announce('所持の確認は記録しました。結果の更新に失敗しました。もう一度照合してください。',true);}
 });
}
function linkedTactics(){
 try{
  const link=JSON.parse(sessionStorage.getItem(tacticLinkKey)||'null');
  if(/^[a-f0-9]{64}$/.test(link?.evaluation_id)&&Array.isArray(link.search_ids)&&
     link.search_ids.length>=1&&link.search_ids.length<=6&&
     link.search_ids.every(id=>typeof id==='string'&&/^[a-f0-9]{64}$/.test(id)))return link;
 }catch{}
 return null;
}
async function compareSavedTactics(){
 const link=linkedTactics();if(!link)throw Error('保存済みの戦術探索が見つかりません。');
 const data=await api('missing-analysis',{action:'tactic_evidence',
  evaluation_id:link.evaluation_id,search_ids:link.search_ids});
 if(data.schema!=='missing-tactic-evidence-v1'||!Array.isArray(data.builds))
  throw Error('戦術証拠の形式が異なります。');
 const root=$('tactic-evidence-results');root.replaceChildren();
 node('p','標準状態：'+(gaps[data.standard_state]?.[0]||'不明')+
  ' ／ 新規対戦 '+data.new_battles+'件',root,'muted');
 node('p','理論上の戦術であり、観測情報に基づく実戦再現性は未検証です。',root,'muted');
 node('p','以下は保存済み戦術だけの参考順です。既存の推薦順・所持判定・不足判定は変更しません。',root,'muted');
 for(const build of [...data.builds].sort((a,b)=>
  (a.advisory?.evidence_order??999)-(b.advisory?.evidence_order??999))){
  if(!build.conditions.length)continue;
  const advisory=build.advisory;
  const group=detail(root,(advisory?'参考'+advisory.evidence_order+'位 · ':'')+
   '候補 '+build.build_id.slice(0,12)+'…','candidate');
  node('p',build.theoretical_all_conditions?'全指定対面に理論上の勝ち筋があります。実戦の充足は未確認です。':
   '全指定対面での役割充足は証明できていません。',group);
  if(advisory){
   node('p','指定条件 '+advisory.required_conditions+'件 ／ 実際に確認 '+advisory.tested_conditions+
    '件 ／ 固定戦術で条件達成 '+advisory.theoretical_supported_conditions+'件 ／ 不利シールドで達成 '+
    advisory.unfavorable_shield_conditions+'件',group,'muted');
   if(advisory.only_observed_complete_build)
    node('p','今回選んだ個体・保存済み戦術の範囲では、全条件を満たした候補はこの個体だけです。未探索個体との比較ではありません。',group,'muted');
   node('p','代替の実用性：未検証（相手の判断・非公開情報への依存は排除できていません）',group,'muted');
  }
  for(const condition of build.conditions){
   const box=detail(group,'重要対面：検証 '+condition.tested_scripts+'／条件達成 '+condition.matching_scripts,'match');
   node('p','標準計算：'+(condition.standard.meets===true?'条件達成':condition.standard.meets===false?'条件未達':'証拠不足'),box);
   for(const path of condition.paths){
    node('p',path.strategy+' ／ 相手の反応 '+path.opponent_response+' ／ '+
      (path.meets===true?'戦術で条件達成':path.meets===false?'条件未達':'未実行・未確定')+
      ' ／ 実戦再現性は未検証',box,'muted');
   }
   if(condition.truncated)node('p','表示は8件まで。件数は全件を集計しています。',box,'muted');
  }
 }
 announce('標準対戦・保有状態を変更せず、保存済み戦術を照合しました。');
}
async function connect(manual){
 if(manual)credential=$('credential').value.trim();
 announce('ポケモンと技の一覧を読み込んでいます。');
 try{
  const data=await api('catalog',{});
  if(!data.ready||!data.species)throw Error(data.error||'ポケモンの一覧を準備中です。');
  moves=data.moves||{};speciesList(data.species);
  $('credential').value='';$('login').hidden=true;$('workspace').hidden=false;
  reference=buildEditor($('reference'),'基準個体',{open:true});addScenario(false);
   $('tactic-evidence-panel').hidden=!linkedTactics();
  announce('基準個体と対面を入力してください。');
 }catch(error){
  credential='';$('login').hidden=false;
  if(error.status===401)announce(manual?'接続キーを確認してください。':'接続キーを入力してください。',manual);
  else announce(error.message,true);
 }
}
$('login-form').addEventListener('submit',event=>{event.preventDefault();perform(()=>connect(true));});
$('analysis-form').addEventListener('input',markEdited);
$('analysis-form').addEventListener('invalid',event=>{
 for(let el=event.target.parentElement;el;el=el.parentElement)if(el.tagName==='DETAILS')el.open=true;
},true);
$('analysis-form').addEventListener('submit',event=>{
 event.preventDefault();
 if(!scenarios.length){announce('確認する対面を1件以上追加してください。',true);$('add-scenario').focus();return;}
 const candidates=[reference,...alternatives].map(item=>item.read());
 if(new Set(candidates.map(item=>JSON.stringify(item))).size!==candidates.length){announce('同じ個体が複数あります。比較する個体の個体値・レベル・技を確認してください。',true);return;}
 const request={action:'evaluate',candidates,scenarios:scenarios.map(item=>item.scenario()),role:{role_id:$('role').value,revision:1,priority:Number($('priority').value)}};
 const revision=editRevision;
 perform(async()=>{
  announce('保存済みの結果を照合しています。');await evaluate(request,revision);
  announce('保存済みの結果を照合しました。');$('results-heading').focus();
 });
});
$('tactic-evidence-read').addEventListener('click',()=>perform(compareSavedTactics));
$('add-scenario').addEventListener('click',()=>addScenario(true));
$('add-alternative').addEventListener('click',addAlternative);
perform(()=>connect(false));
</script></body></html>'''
