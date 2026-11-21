"""Mobile web client for saved-party practice battles."""

HTML = r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>練習対戦</title><style>
:root{font:16px system-ui,sans-serif;color-scheme:dark;background:#122126;color:#e2f1e9}
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0}main{max-width:700px;margin:auto;padding:16px}
a{color:#bbebd4}h1{font-size:1.6rem;margin:12px 0}h2{font-size:1.15rem;margin:0 0 12px}
h3,p,ul{margin:8px 0}h3{font-size:1rem}p,li{overflow-wrap:anywhere}
section{margin:12px 0;padding:14px;border:1px solid #47645d;border-radius:16px;background:#203138}
label{display:block}select,input[type=password]{display:block;width:100%;margin:5px 0 12px}
button,select,input[type=password]{min-height:44px;border:1px solid #76a797;border-radius:10px;padding:8px 10px;font:inherit;color:inherit;background:#12252b}
button{background:#385c50;cursor:pointer;overflow-wrap:anywhere}button:disabled{opacity:.48;cursor:default}
:focus-visible{outline:2px solid #baf4c9;outline-offset:2px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.pick{min-height:44px;display:flex;gap:7px;align-items:center;padding:4px 0}
.pick input{width:20px;height:20px;flex:none;margin:2px}fieldset{min-width:0;border:0;padding:0;margin:8px 0}
ul{padding-inline-start:20px}li{margin:4px 0}
#status{min-height:1.5em;color:#cde9d9}#controls{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
#actions{margin:10px 0}#result{font-weight:bold;font-size:1.25rem}
</style></head><body><main>
<nav><a href="/app/party">← パーティ作成</a></nav>
<h1>練習対戦</h1>
<p id="status" role="status" aria-live="polite"></p>
<section id="login" hidden><h2>ログイン</h2>
<form id="login-form"><label for="key">接続キー</label><input id="key" type="password" required>
<button>接続</button></form></section>
<section id="setup" hidden><h2>保存パーティ</h2>
<label for="own">自分</label><select id="own"></select>
<label for="opponent">CPU</label><select id="opponent"></select>
<button id="start">見せ合いを始める</button></section>
<section id="preview" hidden><h2>3体と先発を選ぶ</h2>
<h3>CPUの見せ合い6体</h3><ul id="preview-enemy"></ul>
<fieldset><legend id="selection-count">選出 0 / 3</legend><div class="grid" id="picks"></div></fieldset>
<label for="lead">先発</label><select id="lead"></select>
<button id="select-three">対戦開始</button></section>
<section id="battle" hidden><h2 id="phase" aria-live="polite"></h2><p id="clock"></p>
<div id="actions" class="grid" aria-label="この局面でできる操作"></div>
<div class="grid"><div><h3 id="own-heading"></h3><ul id="own-team"></ul></div>
<div><h3 id="enemy-heading"></h3><ul id="enemy-team"></ul></div></div>
<p id="last-move"></p></section>
<section id="end" hidden><h2>対戦結果</h2><p id="result" role="status"></p><p id="result-clock"></p></section>
<div id="controls" hidden><button id="refresh" hidden>状態を取得し直す</button><button id="close">対戦を終了</button></div>
</main><script>
'use strict';
const $ = id => document.getElementById(id);
const route = 'team-battle/';
let key='', catalog={}, moves={}, current=null, loaded=false, busy=false, stale=false;
const picks = new Set();
let lead = '';

function message(text){$('status').textContent=text;}
function name(id){return catalog[id]?.name_ja || catalog[id]?.name || id;}
function move(id){return moves[id]?.name_ja || moves[id]?.name || id;}
function list(id, values){
  $(id).replaceChildren(...values.map(value=>{
    const row=document.createElement('li');
    row.textContent=value;
    return row;
  }));
}
async function api(path, payload={}){
  const headers={'Content-Type':'application/json'};
  if(key) headers.Authorization='Bearer '+key;
  const response=await fetch('/app-api/'+path,{method:'POST',headers,credentials:'same-origin',
    body:JSON.stringify(payload)});
  const data=await response.json().catch(()=>null);
  if(!response.ok || !data){
    const error=Error(data?.error || (response.status===401 ? '接続キーを入力してください。' : '通信に失敗しました。'));
    error.status=response.status;
    throw error;
  }
  return data;
}
function selectionAction(){
  return [...picks].sort((a,b)=>a-b).join(',')+'|'+lead;
}
function selectionControls(){
  $('selection-count').textContent='選出 '+picks.size+' / 3';
  for(const box of $('picks').querySelectorAll('input')){
    box.disabled=busy||stale||(!box.checked&&picks.size===3);
  }
  $('lead').replaceChildren(new Option('選択してください',''),...[...picks].sort((a,b)=>a-b)
    .map(slot=>new Option(name(current.observation.own_six[slot].species),String(slot))));
  $('lead').value=lead;
  $('lead').disabled=busy||stale||!picks.size;
  $('select-three').disabled=busy||stale||picks.size!==3||
    !current.observation.legal_actions.includes(selectionAction());
}
function renderPreview(view){
  list('preview-enemy',view.opponent_public_six.map(row=>name(row.species)));
  $('picks').replaceChildren(...view.own_six.map((row,slot)=>{
    const label=document.createElement('label');
    label.className='pick';
    const box=document.createElement('input');
    box.type='checkbox';
    box.checked=picks.has(slot);
    box.addEventListener('change',()=>{
      if(box.checked) picks.add(slot);
      else {
        picks.delete(slot);
        if(lead===String(slot)) lead='';
      }
      selectionControls();
    });
    label.append(box,name(row.species));
    return label;
  }));
  selectionControls();
}
function renderBattle(view){
  const {own, opponent}=view;
  const active=own.team[own.active_slot];
  $('phase').textContent=({turn:'戦術を選ぶ', shield:'シールド', replace:'交代'})[view.phase]||'対戦中';
  $('clock').textContent='ターン '+view.turn+' · 経過 '+(view.elapsed_ms/1000)+'秒';
  $('own-heading').textContent='自分 · シールド '+own.shields;
  $('enemy-heading').textContent='CPU · シールド '+opponent.shields;
  list('own-team',own.team.map((row,i)=>(i===own.active_slot?'場：':'')+name(row.species)+
    ' · HP '+row.hp+'/'+row.max_hp+(i===own.active_slot?' · ゲージ '+row.energy_points:'')));
  list('enemy-team',opponent.revealed.map(row=>(row.species===opponent.active_species?'場：':'')+
    name(row.species)+' · '+(row.fainted?'ひんし':'HP 約'+row.hp_bucket_5pct*5+'%')));
  const latest=[...view.recent_events].reverse().find(event=>event.move_id);
  $('last-move').textContent=latest?'直前の技：'+name(latest.species)+'の'+move(latest.move_id):'';
  const labels={wait:'待機', fast:move(active.fast_move), shield_yes:'シールドを使う', shield_no:'シールドを使わない'};
  for(const [i,row] of own.team.entries()) labels['switch_'+i]=name(row.species)+'に交代';
  for(const [i,charged] of active.charged_moves.entries()) labels['charge_'+i]=move(charged.move_id);
  $('actions').replaceChildren(...view.legal_actions.map(action=>{
    const button=document.createElement('button');
    button.dataset.action=action;
    button.textContent=labels[action]||action;
    button.disabled=busy||stale;
    button.addEventListener('click',()=>step(action));
    return button;
  }));
}
function render(){
  const view=current?.observation;
  $('login').hidden=loaded;
  $('setup').hidden=!loaded||!!current;
  $('preview').hidden=current?.status!=='select_three';
  $('battle').hidden=current?.status!=='battle';
  $('end').hidden=!current||!!view;
  $('controls').hidden=!current;
  $('refresh').hidden=!stale;
  $('refresh').disabled=busy;
  $('close').disabled=busy;
  $('close').textContent=view?'対戦を終了':'パーティ選択に戻る';
  $('start').disabled=busy||!$('own').value;
  $('own').disabled=busy;
  $('opponent').disabled=busy;
  $('login-form').querySelector('button').disabled=busy;
  if(current?.status==='select_three') renderPreview(view);
  if(current?.status==='battle') renderBattle(view);
  if(current&&!view){
    const labels={self_ko_win:'勝利',opponent_ko_win:'敗北',simultaneous_ko:'引き分け（同時KO）',
      timeout:'時間切れ',unsupported:'未対応の対戦条件',unavailable:'対戦エンジンに接続できません'};
    $('result').textContent=labels[current.result?.outcome || current.status]||'対戦終了';
    $('result-clock').textContent=current.result
      ? current.result.turns+'ターン · 経過 '+(current.result.elapsed_ms/1000)+'秒':'';
  }
}
function clearBattle(){
  current=null;
  stale=false;
  picks.clear();
  lead='';
}
async function perform(task){
  if(busy) return;
  busy=true;
  render();
  message('');
  try{await task();}
  catch(error){message(error.message);}
  finally{busy=false;render();}
}
async function loadParties(){
  const {items}=await api('party/list');
  const options=()=>items.map(party=>new Option(party.name,party.id));
  $('own').replaceChildren(new Option('選択してください',''),...options());
  $('opponent').replaceChildren(new Option('自分のパーティに保存した相手',''),...options());
  loaded=true;
  if(!items.length) message('パーティ作成で6体のパーティを保存してください。');
  const data=await api('catalog').catch(()=>null);
  catalog=data?.species||{};
  moves=data?.moves||{};
}
async function syncState(battle_id){
  stale=true;
  try{
    current=await api(route+'state',{battle_id});
    stale=false;
  }catch(error){
    if(error.status===404){
      clearBattle();
      message('対戦セッションが見つかりません。パーティ選択からやり直してください。');
      return;
    }
    throw Error('状態を取得できませんでした。「状態を取得し直す」を押してください。');
  }
}
function step(action){
  perform(async()=>{
    const {battle_id,revision}=current;
    try{current=await api(route+'step',{battle_id,revision,action});}
    catch(error){
      if(error.status!==409 && error.status && error.status<500) {
        if(error.status===404) clearBattle();
        throw error;
      }
      await syncState(battle_id);
      if(current?.observation) message('対戦状態を更新しました。現在の操作を選んでください。');
    }
  });
}
$('login-form').addEventListener('submit',event=>{
  event.preventDefault();
  if(busy) return;
  key=$('key').value.trim();
  $('key').value='';
  perform(loadParties);
});
$('own').addEventListener('change',()=>{$('start').disabled=busy||!$('own').value;});
$('start').addEventListener('click',()=>perform(async()=>{
  const payload={party_id:$('own').value};
  if($('opponent').value) payload.opponent_party_id=$('opponent').value;
  current=await api(route+'start',payload);
}));
$('lead').addEventListener('change',()=>{lead=$('lead').value;selectionControls();});
$('select-three').addEventListener('click',()=>step(selectionAction()));
$('refresh').addEventListener('click',()=>perform(()=>syncState(current.battle_id)));
$('close').addEventListener('click',()=>perform(async()=>{
  const {battle_id}=current;
  try{await api(route+'close',{battle_id});}
  catch(error){
    if(error.status===409){await syncState(battle_id);return;}
    if(error.status!==404) throw error;
  }
  clearBattle();
}));
perform(loadParties);
</script></body></html>'''
