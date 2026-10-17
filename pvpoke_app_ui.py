"""Browser-only entry point. Root credentials are never persisted in the browser.
An optional HttpOnly app-only cookie supports remembered browser sessions.
"""
HTML = r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>個体値厳選</title><style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#e8eef9;background:#101723;color-scheme:dark}*{box-sizing:border-box}body{margin:0}main{max-width:820px;margin:auto;padding:28px 16px 64px}h1{font-size:30px;margin:4px 0 8px}h2{font-size:20px;margin:0 0 12px}p{line-height:1.65;color:#afc0d6}.eyebrow{color:#90ddbc;font-size:12px;letter-spacing:.15em}.card{background:#1a2637;border:1px solid #33465d;border-radius:16px;padding:20px;margin-top:18px}label{display:block;font-size:14px;margin:14px 0 6px}input,select,textarea,button{font:inherit;border-radius:9px}input,select,textarea{width:100%;padding:12px;border:1px solid #49627d;background:#101c2b;color:#ecf3ff}input[type=checkbox]{width:auto;margin:0 8px 0 0;accent-color:#90ddbc}.checkline{display:flex;align-items:center;gap:3px;cursor:pointer}textarea{min-height:142px;line-height:1.7}button{padding:12px 18px;border:1px solid #76b1dc;background:#266b9b;color:white;cursor:pointer}button:disabled{opacity:.5;cursor:wait}.row{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}.secondary{background:transparent;border-color:#597086}.note{font-size:13px}.status{background:#21374a;border-radius:10px;padding:14px;white-space:pre-wrap;line-height:1.7}.error{background:#5a303a}.badge{color:#96e8c4;font-size:13px}.recommendation{border-top:1px solid #3c5068;padding-top:18px;margin-top:18px}.search{display:block;background:#0d1726;padding:12px;border-radius:8px;overflow-wrap:anywhere;font-size:14px;color:#b1e5ff}summary{cursor:pointer;color:#a4cdff}details{margin-top:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;font-size:12px}[hidden]{display:none!important}@media(max-width:560px){.row{grid-template-columns:1fr}.card{padding:16px}main{padding-top:22px}.actions button{flex:1}}
</style></head><body><main>
<header><div class="eyebrow">PVP IV SELECTION</div><h1>役割から選ぶ、個体値厳選</h1><p>対戦計算からおすすめ・理由・検索式まで。アプリの自動推薦と、これまでのGPT評価を使い分けられます。</p></header>
<section class="card" id="login"><h2>アプリに接続</h2><p class="note">初回だけ接続キー、または有効なアクセストークンを入力してください。APIキー自体は端末へ保存しません。</p><label for="credential">接続キー</label><input id="credential" type="password" autocomplete="off"><label class="checkline" for="remember"><input id="remember" type="checkbox" checked>このブラウザのログインを30日間維持する</label><p class="note">共有端末ではチェックを外してください。ログアウトでこのブラウザの保存情報を削除できます。</p><div class="actions"><button id="connect">接続する</button></div></section>
<div id="message" class="status" role="status" aria-live="polite" hidden></div>
<div id="workspace" hidden>
<section class="card"><h2>まとめて貼り付け</h2><p class="note">ポケモン・技・個体値をまとめて取り込めます。読み取りCP付きの「0,11,12 CP717 | ヌオー」にも対応します。日本語の種名、技省略、複数の進化先を含む「個体値リスト」「個体値厳選」、CSVに対応します。</p><label for="importText">コマンドまたはCSV</label><textarea id="importText" spellcheck="false" placeholder="個体値厳選&#10;quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE&#10;0,11,12&#10;3,13,8&#10;2,15,13"></textarea><div class="actions"><button id="importInput" class="secondary">貼り付けた内容を取り込む</button></div><p class="note">取り込みだけでは計算を開始しません。# クルマユ ハハコモリ のような見出しは、次の個体値を両方へ割り当てます。省略した技は種類ごとに補って表示します。</p></section>
<section class="card" id="queuePanel" hidden><h2>連続計算するポケモン</h2><pre id="queuePreview"></pre><p class="note">表示した順にすべて計算します。複数種の内容は上の貼り付け欄から編集できます。</p><button id="singleForm" class="secondary">単一種のフォームに戻す</button></section>
<section class="card"><h2>1. ポケモンと個体値</h2><label for="preset">登録プリセット（任意）</label><select id="preset"></select><p class="note" id="presetHint"></p><label for="allSpecies">全ポケモンから選ぶ</label><select id="allSpecies"></select><label for="species">ポケモン名・英語ID（直接入力）</label><input id="species" list="speciesList" value="quagsire" autocomplete="off"><datalist id="speciesList"></datalist>
<div class="row"><div><label for="fast">通常技</label><select id="fast"></select></div><div><label for="charged1">ゲージ技1</label><select id="charged1"></select></div><div><label for="charged2">ゲージ技2</label><select id="charged2"></select></div></div>
<label for="ivs">攻撃,防御,HP（1行1体・最大150体）</label><textarea id="ivs" spellcheck="false" placeholder="0,11,12&#10;3,13,8&#10;2,15,13"></textarea></section>
<section class="card"><h2>2. 比較と推薦の設定</h2><label for="batchMode">計算条件</label><select id="batchMode"><option value="simple">簡易：Default × 6条件</option><option value="detailed">詳細：4つの相手IV × 6条件</option></select>
<label for="evaluation">評価方法</label><select id="evaluation"><option value="app">アプリで自動推薦</option><option value="gpt">GPTで評価（比較情報を作成）</option></select>
<label for="focus">重要な相手（英語名・1行1つ、省略可）</label><textarea id="focus" style="min-height:80px" placeholder="Corviknight&#10;Feraligatr"></textarea><p class="note">名前が一致する技構成をすべて重視します。省略時は独自の役割を全対面から探します。</p>
<details><summary>自動推薦の基準を調整</summary><label for="lead">勝ち方向で採用するRating差（既定20）</label><input id="lead" type="number" min="1" max="1000" step="1" value="20"><p class="note">500の境界を越える役割は差にかかわらず確認します。負けたままのRating差は自動推薦にしません。</p></details>
<div class="actions"><button id="run">計算して推薦を表示</button><button id="resume" class="secondary" hidden>前の計算を再開</button><button id="disconnect" class="secondary">接続を解除</button></div><p class="note">CP1500以下・最大Lv50。自分0/相手1、自分0/相手2、自分1/相手2も比較します。</p></section>
<details class="card" id="metaManager">
<summary>メタ管理（任意・普段は操作不要）</summary>
<p class="note">アップロードしなければ、現在保存されているメタを自動で使用します。新しいTXT・CSVを選んだ場合だけ、内容を確認して保存できます。</p>
<p class="note" id="metaStatus">現在のメタを確認しています。</p>
<label for="metaFile">メタ一覧（TXT / CSV、4列、最大500技構成）</label>
<input id="metaFile" type="file" accept=".txt,.csv,text/plain,text/csv">
<p class="note">species,fast,charged1,charged2 の4列です。ファイルを選んでも、確認して「このメタを保存」を押すまでは変更されません。</p>
<div id="metaPreview" class="status" hidden></div>
<div class="actions"><button id="metaApply" class="secondary" disabled>確認したメタを保存</button><button id="metaCancel" class="secondary" type="button">選択を取り消す</button></div>
<p id="metaNotice" class="note" aria-live="polite"></p>
</details>
<section class="card" id="results" hidden></section></div></main><script>
'use strict';
const el=id=>document.getElementById(id);let importedSingle=null;let credential='',catalog={},presets=[],active=false,runRef=null,lastResult=null,importedJobs=null,batchState=null,metaPending=null,metaWorking=false;
function message(s,error=false){const x=el('message');x.hidden=false;x.textContent=s;x.className='status'+(error?' error':'');}
async function api(path,data={}){const headers={'Content-Type':'application/json'};if(credential)headers.Authorization='Bearer '+credential;const r=await fetch('/app-api/'+path,{method:'POST',credentials:'same-origin',headers,body:JSON.stringify(data)});if(r.status===401){const e=Error('ログインの有効期限が切れました。接続キーで再接続してください。');e.status=401;throw e;}let out;try{out=await r.json();}catch{throw Error('応答を確認できません。接続を確認してください。');}if(!r.ok){const e=Error(out.error||'通信エラー');e.status=r.status;throw e;}return out;}
function option(select,values,selected){select.replaceChildren();for(const v of values){const o=document.createElement('option');o.value=v;o.textContent=v;select.append(o);}if(values.includes(selected))select.value=selected;}
function moves(row={}){const p=catalog[el('species').value]||{};option(el('fast'),p.fastMoves||[],row.fast);option(el('charged1'),p.chargedMoves||[],row.charged1);option(el('charged2'),p.chargedMoves||[],row.charged2);if(el('charged1').value===el('charged2').value){const alt=(p.chargedMoves||[]).find(x=>x!==el('charged1').value);if(alt)el('charged2').value=alt;}}
function presetKey(p){return p.key||[p.species,p.fast,p.charged1,p.charged2].join('|');}
function currentCandidate(){return {species:el('species').value.trim(),fast:el('fast').value,charged1:el('charged1').value,charged2:el('charged2').value};}
function setCandidate(p){el('species').value=p.species;el('allSpecies').value=p.species;moves(p);const found=presets.find(x=>['species','fast','charged1','charged2'].every(k=>x[k]===p[k]));el('preset').value=found?presetKey(found):'';}
function setPreset(){const p=presets.find(x=>presetKey(x)===el('preset').value);if(p)setCandidate(p);}
function resolveTypedSpecies(){const raw=el('species').value.normalize('NFKC').trim().toLowerCase();if(['gourgeist','pumpkaboo','パンプジン','バケッチャ'].includes(raw)){message('このポケモンはサイズごとに能力が異なります。こだましゅ/XS、ちゅうだましゅ/通常、おおだましゅ/XL、ギガだましゅ/XXLを指定してください。',true);return;}const found=Object.entries(catalog).filter(([sid,p])=>[sid,p.name,p.name_ja,...(p.aliases||[])].some(x=>x&&String(x).normalize('NFKC').trim().toLowerCase()===raw));if(found.length===1)el('species').value=found[0][0];else if(found.length>1)message('複数のフォルムが一致しました。サイズやフォルムを指定してください。',true);}

function setBusy(value){active=value;for(const id of ['run','resume','disconnect','importInput','singleForm'])el(id).disabled=value;el('metaFile').disabled=value;el('metaApply').disabled=value||!metaPending||metaWorking||!metaPending.preview.changed;el('run').textContent=value?'計算を確認中…':'計算して結果を表示';}
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
function individualSearches(result,iv){
 const records=(result.source_records||[]).filter(r=>r.ivs===iv.ivs);
 return records.length?records.map(r=>({search:r.search_string,cp:r.cp,species:r.species})):[{search:iv.search_string}];
}
function overlayExport(results){
 recommendationExportText(results); // Validate every pair before writing anything.
 const items=results.flatMap(result=>(result.selection?.recommendations||[]).flatMap(row=>
  [row,...(row.equivalent_candidates||[])].flatMap(iv=>individualSearches(result,iv).map(source=>({
   search:source.search,nickname:nicknameFor(result,row,iv.ivs).text,ivs:iv.ivs,
   cp:source.cp||null,species:source.species||result.candidate.species
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
async function shareRecommendations(results,button){
 let text;
 try{text=overlayExport(results);}catch(e){message(e.message,true);return;}
 if(typeof navigator.share!=='function'){
  await copy(text,button);
  message('このブラウザは直接共有に対応していません。コピーした内容をAndroidの「厳選コピーリスト」で貼り付けてください。');
  return;
 }
 try{
  await navigator.share({title:'厳選コピーリスト',text});
  message('Androidの共有先で「厳選コピーリスト」を選び、内容を確認して「取り込む」を押してください。');
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
 node('p',[result.candidate.fast,result.candidate.charged1,result.candidate.charged2].join(' / '),panel,'note');const selection=result.selection;
 if(!selection){node('h2','GPT評価用の比較情報',panel);node('p','今回の比較情報をコピーしてGPTに評価を依頼できます。',panel);const b=node('button','比較情報をコピー',panel);b.onclick=()=>copy('以下のPvPoke実測比較を、個体値厳選の基準で評価してください。おすすめ個体と英語検索式を示してください。\n'+JSON.stringify(result),b);return;}
 node('h2','おすすめ個体',panel);
 node('p','S/Aは入力した候補内での暫定評価です。勝ち・引き分けは記載したシールド・相手IV条件での計算結果です。',panel,'note');
 if(selection.policy?.version&&selection.explanation_version!=='pairwise-v1'){
  node('p','保存済みの結果は旧版の推薦説明です。ページを再読み込みし、同じ入力を再計算すると最新の重複判定と比較説明を確認できます。',panel,'note');
 }
 if(selection.recommendations.length){const actions=node('div','',panel,'actions');const b=node('button','検索式とニックネームをすべてコピー',actions);b.onclick=()=>copyRecommendations([result],b);const overlayCopy=node('button','オーバーレイ用にコピー',actions,'secondary');overlayCopy.onclick=()=>copyOverlay([result],overlayCopy);const share=node('button','Androidへ送る',actions,'secondary');share.onclick=()=>shareRecommendations([result],share);node('p','検索式→改行→ニックネームの順で、同じ性能の代替個体も含めてコピーします。Androidへの送信は共有先で「厳選コピーリスト」を選んでください。共有に非対応の端末ではコピーに切り替わります。個体値の見出しを引き継ぐ場合は「Androidへ送る」か「オーバーレイ用にコピー」を使ってください。',panel,'note');}
 if(selection.excluded&&(!Array.isArray(selection.excluded)||selection.excluded.length))node('p','計算対象から除外された対面があります：'+JSON.stringify(selection.excluded),panel);
 const searchCounts=new Map();for(const r of selection.recommendations)for(const item of [r,...(r.equivalent_candidates||[])]){for(const source of individualSearches(result,item)){const v=searchCounts.get(source.search)||new Set();v.add(item.ivs);searchCounts.set(source.search,v);}}if([...searchCounts.values()].some(x=>x.size>1))node('p','注意：同じ検索式に異なる個体値が含まれます。検索式は範囲指定なので、名前を付ける前に各個体の攻撃・防御・HPを確認してください。',panel,'note');
 if(selection.unmatched_focus.length)node('p','一致しなかった重要相手：'+selection.unmatched_focus.map(x=>opponentLabel(x).name).join('、'),panel);
 if(!selection.recommendations.length)node('p','自動推薦の根拠が十分な個体はありません。下の保留個体を確認してください。',panel);
 for(const row of selection.recommendations){
  const card=node('article','',panel,'recommendation');node('h2',row.rank+'位｜'+row.ivs+'｜'+row.grade,card);node('div',row.role,card,'badge');
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
 if(selection.review_candidates.length){const d=node('details','',panel);node('summary','保留：'+selection.review_candidates.length+'個体',d);for(const row of selection.review_candidates){node('p',row.ivs+'：'+row.reason,d);if(row.equivalent_candidates.length)node('p','同じ性能：'+row.equivalent_candidates.map(x=>x.ivs).join(', '),d);}}
 const rejected=Object.entries(selection.dominated_by);if(rejected.length){const d=node('details','',panel);node('summary','全条件で他候補以下の個体（'+rejected.length+'）',d);for(const [iv,rivals] of rejected)node('p',iv+' → '+rivals.join(', '),d);}
 refreshNicknames();
}
function metaNotice(text,error=false){el('metaNotice').textContent=text;el('metaNotice').style.color=error?'#ffb6b6':'';}
function resetMetaUpload(){metaPending=null;el('metaApply').disabled=true;el('metaPreview').hidden=true;el('metaPreview').textContent='';el('metaFile').value='';}
async function refreshMetaStatus(){
 try{const state=await api('meta-status');el('metaStatus').textContent='現在：'+state.rows+'技構成 / '+(state.source==='bundled'?'標準メタ':'アップロード済みメタ')+' / SHA256 '+state.sha256.slice(0,12)+'…';}
 catch(e){el('metaStatus').textContent='現在のメタ状態を取得できません：'+e.message;}
}
async function refreshMetaPresets(){
 const cat=await api('catalog');catalog=cat.species;prepareLabels();presets=cat.app_presets||cat.presets;
 const previous=el('preset').value,opts=el('preset');opts.replaceChildren();
 const direct=document.createElement('option');direct.value='';direct.textContent='直接指定・貼り付け';opts.append(direct);
 for(const p of presets){const o=document.createElement('option');o.value=presetKey(p);o.textContent=p.name+' / '+p.fast+' / '+p.charged1+' / '+p.charged2;opts.append(o);}
 if(presets.some(p=>presetKey(p)===previous))opts.value=previous;
 el('presetHint').textContent='登録済みの技構成 '+presets.length+'件。プリセット外も、全ポケモンの選択・CSV貼り付けから計算できます。';
}
el('metaFile').onchange=async()=>{
 resetMetaUploadPreviewOnly();
 const selected=el('metaFile').files?.[0];
 if(!selected){metaNotice('');return;}
 if(active||metaWorking){metaNotice('計算中はメタを更新できません。',true);return;}
 if(!/\.(txt|csv)$/i.test(selected.name)){metaNotice('TXTまたはCSVファイルを選んでください。',true);return;}
 if(!selected.size||selected.size>80000){metaNotice('ファイルは空でない80KB以下のものを選んでください。',true);return;}
 metaWorking=true;metaNotice('ファイルの内容・技・変更点を確認中です。');
 try{
  const content=await selected.text();
  if(el('metaFile').files?.[0]!==selected)return;
  const preview=await api('meta-preview',{csv:content});
  if(el('metaFile').files?.[0]!==selected)return;
  metaPending={content,preview};
  const lines=['現在 '+preview.current_rows+'構成 → 新規 '+preview.rows+'構成',
   '追加 '+preview.added_count+'件 / 削除 '+preview.removed_count+'件',
   '追加：'+(preview.added.length?preview.added.join('\n'):'なし'),
   '削除：'+(preview.removed.length?preview.removed.join('\n'):'なし')];
  if(preview.added_count>preview.diff_limit||preview.removed_count>preview.diff_limit)lines.push('※変更内容の表示は各30件まで');
  el('metaPreview').textContent=lines.join('\n');
  el('metaPreview').hidden=false;
  metaNotice(preview.changed?'内容を確認し、更新するときだけ保存ボタンを押してください。':'現在のメタと同じ内容です。保存は不要です。');
 }catch(e){metaPending=null;metaNotice(e.message+'（元のメタは変更されていません）',true);}
 finally{metaWorking=false;el('metaApply').disabled=active||!metaPending||!metaPending.preview.changed;}
};
function resetMetaUploadPreviewOnly(){metaPending=null;el('metaApply').disabled=true;el('metaPreview').hidden=true;el('metaPreview').textContent='';}
el('metaCancel').onclick=()=>{if(metaWorking)return;resetMetaUpload();metaNotice('メタの更新を取り消しました。現在のメタをそのまま使用します。');};
el('metaApply').onclick=async()=>{
 if(active||metaWorking||!metaPending||!metaPending.preview.changed)return;
 const {content,preview}=metaPending;
 metaWorking=true;el('metaApply').disabled=true;el('metaFile').disabled=true;el('metaCancel').disabled=true;
 metaNotice('確認済みのメタを保存しています。');
 try{
  const saved=await api('meta-apply',{csv:content,expected_previous_sha256:preview.previous_sha256,expected_sha256:preview.sha256});
  resetMetaUpload();await refreshMetaStatus();
  try{await refreshMetaPresets();}catch(e){metaNotice('メタは保存されましたが、プリセットの再取得に失敗しました。ページを再読込してください。',true);return;}
  metaNotice('保存完了：'+saved.rows+'技構成。次の計算からこのメタを使います。');
 }catch(e){metaNotice(e.message+'（保存されていない場合は元のメタを維持します。状態を確認してください）',true);await refreshMetaStatus();}
 finally{metaWorking=false;el('metaFile').disabled=active;el('metaCancel').disabled=false;el('metaApply').disabled=active||!metaPending||!metaPending.preview.changed;}
};
function cacheBatch(){try{sessionStorage.setItem('pvpoke-app-batch',JSON.stringify(batchState));}catch{message('再開情報を保存できませんでした。計算が終わるまで画面を開いておいてください。',true);}}
function setImportedJobs(jobs){importedSingle=jobs?.length===1?jobs[0]:null;importedJobs=jobs&&jobs.length>1?jobs:null;el('queuePanel').hidden=!importedJobs;for(const id of ['preset','allSpecies','species','fast','charged1','charged2','ivs'])el(id).disabled=!!importedJobs;if(importedJobs)el('queuePreview').textContent=jobs.map((j,i)=>(i+1)+'. '+j.name+'：'+j.candidate_count+'個体\n   '+[j.candidate.fast,j.candidate.charged1,j.candidate.charged2].join(' / ')+'\n'+j.warnings.join('\n')).join('\n\n');}
async function finish(result){while(result.state==='running'){message('全対面を計算中です。'+(batchState?' '+(batchState.index+1)+' / '+batchState.jobs.length+'種類':''));result=await api('result',{run_ref:runRef,wait_seconds:12});}if(result.state!=='done'||!result.complete)throw Error(result.message||'計算が完了していません。');return result;}
async function executeBatch(){for(;batchState.index<batchState.jobs.length;){const job=batchState.jobs[batchState.index];message(job.name+'を計算します（'+(batchState.index+1)+' / '+batchState.jobs.length+'）。');let result;if(batchState.run_ref){runRef=batchState.run_ref;result=await api('result',{run_ref:runRef,wait_seconds:12});}else{const data={candidate:job.candidate,ivs:job.ivs,batch_mode:batchState.batch_mode,focus_opponents:batchState.focus,report_format:batchState.report_format,selection_policy:batchState.policy,wait_seconds:0};if(batchState.meta_sha256)data.expected_meta_sha256=batchState.meta_sha256;result=await api('run',data);runRef=result.run_ref;batchState.run_ref=runRef;sessionStorage.setItem('pvpoke-app-run',runRef);cacheBatch();}result=await finish(result);result.display_name=job.name;result.source_sections=job.source_sections||[];result.source_records=job.source_records||[];batchState.meta_sha256=result.meta_sha256;batchState.results.push(result);render(result,batchState.index>0);batchState.index++;batchState.run_ref=null;runRef=null;sessionStorage.removeItem('pvpoke-app-run');cacheBatch();}message(batchState.jobs.length+'種類すべての計算と推薦が完了しました。');sessionStorage.removeItem('pvpoke-app-batch');batchState=null;runRef=null;el('resume').hidden=true;}
async function connect(auto=false){credential=auto?'':el('credential').value.trim();if(!auto&&!credential){message('接続キーを入力してください。',true);return;}el('connect').disabled=true;try{if(!auto&&el('remember').checked){await api('session');credential='';}const cat=await api('catalog');if(!cat.ready)throw Error(cat.error||'ゲームデータを読込中です。少し待って接続してください。');catalog=cat.species;prepareLabels();presets=cat.app_presets||cat.presets;el('credential').value='';el('login').hidden=true;el('workspace').hidden=false;const opts=el('preset');opts.replaceChildren();const custom=document.createElement('option');custom.value='';custom.textContent='直接指定・貼り付け';opts.append(custom);for(const p of presets){const o=document.createElement('option');o.value=presetKey(p);o.textContent=p.name+' / '+p.fast+' / '+p.charged1+' / '+p.charged2;opts.append(o);}el('presetHint').textContent='登録済みの技構成 '+presets.length+'件。プリセット外も、全ポケモンの選択・CSV貼り付けから計算できます。';const speciesOptions=Object.keys(catalog).sort((a,b)=>(catalog[a].name_ja||catalog[a].name||a).localeCompare(catalog[b].name_ja||catalog[b].name||b,'ja'));el('allSpecies').replaceChildren();el('speciesList').replaceChildren();for(const sid of speciesOptions){const label=(catalog[sid].name_ja||catalog[sid].name||sid)+' ('+sid+')';const o=document.createElement('option');o.value=sid;o.textContent=label;el('allSpecies').append(o);const hint=document.createElement('option');hint.value=sid;hint.label=label;el('speciesList').append(hint);}const preferred=presets.find(p=>p.species==='quagsire'&&p.charged2==='STONE_EDGE')||presets[0];if(preferred)setCandidate(preferred);runRef=sessionStorage.getItem('pvpoke-app-run');try{batchState=JSON.parse(sessionStorage.getItem('pvpoke-app-batch')||'null');}catch{batchState=null;}if(batchState?.jobs)setImportedJobs(batchState.jobs);if(batchState?.results?.length)batchState.results.forEach((r,i)=>render(r,i>0));el('resume').hidden=!(runRef||batchState);message('接続できました。');await refreshMetaStatus();}catch(e){credential='';if(!auto||e.status!==401)message(e.message,true);}finally{el('connect').disabled=false;}}
el('connect').onclick=()=>connect(false);
el('preset').onchange=setPreset;el('species').onchange=()=>{resolveTypedSpecies();el('allSpecies').value=el('species').value;el('preset').value='';moves();};
el('allSpecies').onchange=()=>{el('species').value=el('allSpecies').value;el('preset').value='';moves();};
el('singleForm').onclick=()=>{if(!active){setImportedJobs(null);message('単一種のフォームに切り替えました。貼り付けた元の入力は上の欄に残っています。');}};
el('importInput').onclick=async()=>{if(active)return;setBusy(true);try{const parsed=await api('import',{text:el('importText').value,current:currentCandidate()});const jobs=parsed.jobs||[parsed];setCandidate(jobs[0].candidate);el('ivs').value=jobs[0].ivs;if(parsed.batch_mode)el('batchMode').value=parsed.batch_mode;setImportedJobs(jobs);message(jobs.map(j=>j.name+'：'+j.candidate_count+'個体 / '+[j.candidate.fast,j.candidate.charged1,j.candidate.charged2].join(' / ')+'\n'+j.warnings.join('\n')).join('\n\n'));}catch(e){message(e.message,true);}finally{setBusy(false);}};
el('evaluation').onchange=()=>{el('run').textContent=el('evaluation').value==='app'?'計算して推薦を表示':'GPT評価用の比較情報を作成';};
el('run').onclick=async()=>{if(active)return;setBusy(true);el('results').hidden=true;try{const current=currentCandidate();const keep=importedSingle?.candidate.species===current.species&&importedSingle.ivs.trim()===el('ivs').value.trim();const jobs=importedJobs||[{candidate:current,ivs:el('ivs').value,name:catalog[el('species').value]?.name_ja||el('species').value,source_records:keep?importedSingle.source_records:[],source_sections:keep?importedSingle.source_sections:[]}];batchState={jobs,index:0,results:[],run_ref:null,batch_mode:el('batchMode').value,focus:el('focus').value.split('\n').map(x=>x.trim()).filter(Boolean),report_format:el('evaluation').value==='app'?'app':'decision',policy:{meaningful_win_lead:Number(el('lead').value)}};cacheBatch();await executeBatch();}catch(e){message(e.message+'\n完了済みの結果は表示を保持しています。後続の対象は未実行です。',true);el('resume').hidden=!(runRef||batchState);}finally{setBusy(false);}};
el('resume').onclick=async()=>{if(active||!(runRef||batchState))return;setBusy(true);try{if(batchState){await executeBatch();}else{render(await finish(await api('result',{run_ref:runRef,wait_seconds:12})));runRef=null;sessionStorage.removeItem('pvpoke-app-run');el('resume').hidden=true;message('計算と結果の確認が完了しました。');}}catch(e){message(e.message,true);}finally{setBusy(false);}};
el('disconnect').onclick=async()=>{try{await api('logout');}catch(e){message('ログアウトできませんでした。再試行してください。',true);return;}credential='';catalog={};nameEntries=[];opponentLabels.clear();displayedResults=[];nicknameBindings=[];presets=[];lastResult=null;setImportedJobs(null);batchState=null;el('results').replaceChildren();el('workspace').hidden=true;el('login').hidden=false;resetMetaUpload();message('接続を解除しました。このブラウザのログイン情報も削除しました。');};
const access=new URLSearchParams(location.hash.slice(1)).get('access');
if(access){history.replaceState(null,'',location.pathname);el('credential').value=access;connect(false);}else{connect(true);}
</script></body></html>'''

