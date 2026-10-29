(async function(){
'use strict';
const C=Flashcards,$=id=>document.getElementById(id),ORIGIN='https://pokemoniv-production.up.railway.app';
const native=window.FlashcardAndroid;
let db,catalog,decks=[],reviews={},session=null,undo=null,limit=10,revealed=false,busy=false,draft=null,editingSpecies=null,syncing=false,updated=0;
function message(value,error=false){delete $('status').dataset.grade;$('status').textContent=value;$('status').className=error?'error':'quiet';}
function transaction(stores,fn){return new Promise((resolve,reject)=>{const tx=db.transaction(stores,'readwrite');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('保存できません'));fn(tx);});}
function read(store,key){return new Promise((resolve,reject)=>{const req=db.transaction(store).objectStore(store).get(key);req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});}
function put(tx,key,value){tx.objectStore('kv').put(value,key);}
function show(id){for(const view of ['home','study','editor'])$(view).hidden=view!==id;$('homeBtn').hidden=id==='home';window.scrollTo(0,0);}
function moveName(id){return catalog.moves[id]?.ja||catalog.moves[id]?.name||id;}
function questionName(c){const ids=C.sequence(c);return c.sequence?ids.map(moveName).join(' → '):moveName(c.charged);}
function monName(id){return catalog.species[id]?.ja||catalog.species[id]?.name||id;}
function currentDeck(){return decks.find(d=>d.id===$('deck').value);}
function updateNotify(){const info=C.dueInfo(decks,catalog,reviews);if(native){native.setSchedule($('notify').checked,info.next||0,+$('hour').value);$('notifyInfo').textContent='アプリを閉じていても通知します。省電力設定により通知時刻が遅れる場合があります。';}else{$('notify').disabled=true;$('notifyInfo').textContent='復習通知は読み取りアプリのサイドボタンから使えます。';}}
window.flashcardNotificationState=function(enabled){$('notify').checked=!!enabled;};
function home(){show('home');const selected=$('deck').value;$('deck').replaceChildren();for(const d of decks){const option=document.createElement('option');option.value=d.id;option.textContent=d.name;$('deck').append(option);}if(decks.some(d=>d.id===selected))$('deck').value=selected;
 $('resume').hidden=!session||session.index>=session.cards.length;$('start').disabled=!decks.length;deckInfo();updateNotify();}
function deckInfo(){const d=currentDeck();if(!d)return;const result=C.deckCards(d,catalog);const due=result.items.filter(c=>{const s=C.reviewState(c,reviews,catalog.moves);return s.seen&&s.due<=Date.now();}).length;
 $('deckInfo').textContent=`${result.items.length}枚・復習 ${due}枚`+(result.invalid?`・技データを確認中 ${result.invalid}件`:'');$('start').disabled=!result.items.length;}
function notifyDate(){const info=C.dueInfo(decks,catalog,reviews);return info.next?new Date(info.next).toLocaleString('ja-JP'):'';}
function draw(){show('study');const c=session.cards[session.index];$('undo').disabled=!undo||busy;$('completed').hidden=!!c;
 if(!c){$('card').hidden=true;$('grades').hidden=true;$('progress').textContent=`${session.cards.length}問 おつかれさま`;$('sessionInfo').textContent='次の復習：'+(notifyDate()||'未設定');return;}
 $('card').hidden=false;$('grades').hidden=!revealed;$('reveal').hidden=revealed;$('progress').textContent=`${session.index+1} / ${session.cards.length}`;
 $('species').textContent=monName(c.species);$('fast').textContent=moveName(c.fast)+'（'+catalog.moves[c.fast].turns+'ターン）';$('charged').textContent=questionName(c);
 const values=C.answer(c,catalog.moves);$('answer').textContent=values.join(' → ');$('answer').hidden=!revealed;
 $('turnAnswers').replaceChildren();$('turnAnswers').hidden=!revealed||catalog.moves[c.fast].turns!==1;
 if(revealed&&catalog.moves[c.fast].turns===1){
  for(const turns of [2,3,4,5]){const row=document.createElement('span');row.className='turn-row';const label=document.createElement('span'),counts=document.createElement('strong');label.textContent='自分の技1：'+turns+'ターン';counts.textContent=C.relativeCounts(values,turns).join(' → ');row.append(label,counts);$('turnAnswers').append(row);}
  const note=document.createElement('small');note.textContent='技1の完了回数で換算。端数は次へ持ち越し。ゲージ技の発動・待ち時間は含みません。';$('turnAnswers').append(note);
 }
 $('hint').textContent=revealed?'':'タップで答え';$('hint').hidden=revealed;
 $('card').setAttribute('aria-label',revealed?'左半分で見直し、右半分で正解':'技カウントカード');$('again').disabled=$('correct').disabled=!revealed||busy;
 $('sessionInfo').textContent='答えを表示したら、左半分をタップで見直し、右半分をタップで正解。';}
async function start(replay=false){if(busy)return;busy=true;try{const cards=replay?C.shuffle(C.deduplicate(session.cards,catalog.moves)):C.select(C.deckCards(currentDeck(),catalog).items,reviews,catalog.moves,limit);if(!cards.length)return;const next={deck:replay?session.deck:currentDeck().id,cards,index:0};await transaction(['kv'],tx=>{put(tx,'session',next);put(tx,'undo',null);} );session=next;undo=null;revealed=false;draw();message('');}catch(e){message('保存できません。学習は開始していません。',true);}finally{busy=false;}}
async function grade(correct){if(busy||!revealed||!session?.cards[session.index])return;busy=true;draw();const c=session.cards[session.index],id=C.key(c),previous=reviews[id],oldSession=structuredClone(session),next=C.review(C.reviewState(c,reviews,catalog.moves),correct);
 const nextSession={...session,index:session.index+1};try{await transaction(['kv','reviews'],tx=>{tx.objectStore('reviews').put(next,id);put(tx,'session',nextSession);put(tx,'undo',{id,previous:previous||null,session:oldSession});});reviews[id]=next;undo={id,previous:previous||null,session:oldSession};session=nextSession;revealed=false;message(correct?'前の問題を「正解」で保存しました':'前の問題を「見直し」で保存しました');$('status').dataset.grade=correct?'correct':'again';updateNotify();}catch(e){message('保存に失敗しました。同じカードでもう一度記録してください。',true);}finally{busy=false;draw();}}
async function undoGrade(){if(!undo||busy)return;busy=true;try{const u=undo;await transaction(['kv','reviews'],tx=>{if(u.previous)tx.objectStore('reviews').put(u.previous,u.id);else tx.objectStore('reviews').delete(u.id);put(tx,'session',u.session);put(tx,'undo',null);});if(u.previous)reviews[u.id]=u.previous;else delete reviews[u.id];session=u.session;undo=null;revealed=true;message('直前の記録を戻しました');updateNotify();}catch(e){message('記録を戻せませんでした',true);}finally{busy=false;draw();}}
async function saveDecks(next){await transaction(['kv'],tx=>put(tx,'decks',next));decks=next;}
function populateEditor(maxVisible=80){const result=C.deckCards(draft,catalog);$('editCount').textContent=result.items.length+'枚';$('entries').replaceChildren();for(const c of result.items.slice(0,maxVisible)){const row=document.createElement('div');row.className='entry';const label=document.createElement('span');label.textContent=`${monName(c.species)} · ${moveName(c.fast)} → ${questionName(c)}`;const remove=document.createElement('button');remove.textContent='外す';remove.onclick=()=>{draft.excluded=[...new Set([...(draft.excluded||[]),C.key(c),C.key({...c,species:c.species.endsWith('_shadow')?c.species.replace(/_shadow$/,''):c.species+'_shadow'})])];populateEditor();};row.append(label,remove);$('entries').append(row);}if(result.items.length>maxVisible){const more=document.createElement('button');more.textContent=`さらに表示（残り${result.items.length-maxVisible}枚）`;more.onclick=()=>populateEditor(maxVisible+80);$('entries').append(more);}}
function edit(create){draft=create?{id:'custom:'+crypto.randomUUID(),name:'新しいデッキ',source:'custom',rows:[],extra:[],excluded:[]}:structuredClone(currentDeck());if(!draft)return;
 $('deckName').value=draft.name;$('deckName').disabled=draft.source!=='custom';$('search').value='';$('moveEditor').hidden=true;$('results').replaceChildren();$('source').replaceChildren();for(const l of catalog.leagues){const o=document.createElement('option');o.value=l.id;o.textContent=l.name;$('source').append(o);}show('editor');populateEditor();}
function chooseSpecies(id){editingSpecies=id;$('moveEditor').hidden=false;$('editingSpecies').textContent=monName(id);const p=catalog.species[id],active=C.deckCards(draft,catalog).items.filter(c=>c.species===id);
 for(const [kind,elem] of [['fast','fastOptions'],['charged','chargedOptions']]){$(elem).replaceChildren();const selected=new Set(active.map(c=>c[kind]));if(!selected.size){const def=(catalog.leagues.find(l=>l.id===$('source').value)?.rows||[]).find(r=>r.species===id);for(const m of def?.[kind]||p[kind].slice(0,kind==='fast'?1:2))selected.add(m);}
 for(const id of p[kind]){const label=document.createElement('label');label.className='check';const check=document.createElement('input');check.type='checkbox';check.value=id;check.checked=selected.has(id);label.append(check,document.createTextNode(moveName(id)));$(elem).append(label);}}
 $('sequenceOptions').replaceChildren();
 for(let step=0;step<4;step++){const select=document.createElement('select');select.setAttribute('aria-label','使用順の技 '+(step+1));
  for(const move of p.charged){const option=document.createElement('option');option.value=move;option.textContent=moveName(move);select.append(option);}
  const preferred=[...$('chargedOptions').querySelectorAll('input:checked')].map(c=>c.value);select.value=preferred[step<2?0:1]||preferred[0]||p.charged[0];$('sequenceOptions').append(select);
 }
}
function search(){const q=$('search').value.trim().normalize('NFKC').toLocaleLowerCase();$('results').replaceChildren();if(!q)return;const league=catalog.leagues.find(l=>l.id===$('source').value),allowed=new Set(league?.rows.map(r=>r.species)||Object.keys(catalog.species));let count=0;
 for(const [id,p] of Object.entries(catalog.species)){if(!allowed.has(id)||![id,p.ja,p.name,...p.aliases||[]].join(' ').normalize('NFKC').toLocaleLowerCase().includes(q))continue;const b=document.createElement('button');b.textContent=`${p.ja||p.name} · ${p.name}`;b.onclick=()=>chooseSpecies(id);$('results').append(b);if(++count>=40)break;}}
async function api(path,args){const headers={'Content-Type':'application/json'};const key=$('key').value.trim();if(key)headers.Authorization='Bearer '+key;const response=await fetch(path,{method:'POST',headers,body:JSON.stringify(args),credentials:'same-origin',signal:AbortSignal.timeout(12000)});if(!response.ok)throw Error(response.status===401?'接続キーを確認してください':'同期できませんでした');return response.json();}
async function sync(force=false){if(syncing||session?.index<session?.cards.length)return;syncing=true;try{
 const last=await read('kv','catalogChecked');if(force||!last||Date.now()-last>86400000){const response=await fetch('/reader-api/v1/flashcards',{headers:{'If-None-Match':'"'+catalog.revision+'"'},signal:AbortSignal.timeout(12000)});if(response.status!==304){if(!response.ok)throw Error('ランキングを更新できませんでした');const next=await response.json();validateCatalog(next);catalog=next;decks=C.mergeDecks(decks,catalog.decks);await transaction(['kv'],tx=>{put(tx,'catalog',catalog);put(tx,'decks',decks);});}await transaction(['kv'],tx=>put(tx,'catalogChecked',Date.now()));}
 try{const data=await api('/app-api/flashcards',{});const privateIds=new Set(data.decks.map(d=>d.id));decks=decks.filter(d=>d.source!=='meta'||privateIds.has(d.id));decks=C.mergeDecks(decks,data.decks);await saveDecks(decks);$('login').hidden=true;$('syncInfo').textContent=`ランキング：${catalog.retrieved}／カスタムメタも同期済み。`+(data.augmentation?.running?'技構成の自動評価中です。':'');const failed=data.augmentation?.jobs?.find(j=>j.state==='failed');if(failed)$('syncInfo').textContent+='自動評価を完了できなかったメタがあります：'+failed.error;}catch(e){$('login').hidden=false;$('syncInfo').textContent=`ランキング：${catalog.retrieved}。カスタムメタは接続後に同期します。`;}
 updated=Date.now();await transaction(['kv'],tx=>put(tx,'updated',updated));if(!$('home').hidden)home();if(force)message('更新しました');
 }catch(e){message('保存済みデッキで利用できます。'+e.message,true);}finally{syncing=false;}}
function validateCatalog(d){if(d?.version!==1||!d.species||!d.moves||!Array.isArray(d.decks)||!Array.isArray(d.leagues))throw Error('データ形式が不正です');}
function validateBackup(data){if(data?.version!==1||!Array.isArray(data.decks)||!Array.isArray(data.reviews))throw Error('バックアップ形式が不正です');for(const d of data.decks){if(typeof d.id!=='string'||typeof d.name!=='string'||!Array.isArray(d.rows)||!Array.isArray(d.extra||[])||!Array.isArray(d.excluded||[]))throw Error('デッキ形式が不正です');for(const r of [...d.rows,...d.extra||[]])if(typeof r.species!=='string'||!Array.isArray(r.fast)||!Array.isArray(r.charged)||r.sequences!==undefined&&(!Array.isArray(r.sequences)||!r.sequences.length||r.sequences.some(ids=>!Array.isArray(ids)||ids.length!==4||ids.some(id=>typeof id!=='string'))))throw Error('技の指定が不正です');}
 for(const r of data.reviews)if(typeof r.id!=='string'||typeof r.signature!=='string'||!['due','seen','lapses','reps','interval','ease'].every(k=>Number.isFinite(r[k])&&r[k]>=0))throw Error('復習記録が不正です');}
try{db=await new Promise((resolve,reject)=>{const req=indexedDB.open('pokemon-move-flashcards',1);req.onupgradeneeded=()=>{req.result.createObjectStore('kv');req.result.createObjectStore('reviews');};req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);req.onblocked=()=>reject(Error('別の画面を閉じてください'));});
 catalog=await read('kv','catalog')||window.FLASHCARD_BOOTSTRAP;validateCatalog(catalog);
 // Older saved catalogs lack move durations. Fill only metadata from bundled source;
 // preserve their energy values and the user's private decks and review records.
 for(const [id,move] of Object.entries(catalog.moves))if(!move.turns&&window.FLASHCARD_BOOTSTRAP.moves[id]?.turns)move.turns=window.FLASHCARD_BOOTSTRAP.moves[id].turns;
decks=C.mergeDecks(await read('kv','decks')||[],catalog.decks);session=await read('kv','session')||null;if(session){const d=decks.find(d=>d.id===session.deck);if(d){const contexts=new Map(C.deckCards(d,catalog).items.map(c=>[C.key(c),c]));session.cards=session.cards.map(c=>contexts.get(C.key(c))||contexts.get(C.key({...c,species:c.species.replace(/_shadow$/,'')}))||c);}}undo=await read('kv','undo')||null;
 const all=await new Promise((resolve,reject)=>{const r=db.transaction('reviews').objectStore('reviews').getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});reviews=Object.fromEntries(all.map(r=>[r.id,r]));await saveDecks(decks);
 $('deck').onchange=deckInfo;$('start').onclick=()=>start(false);$('replay').onclick=()=>start(true);$('finishHome').onclick=()=>{home();sync();};$('resume').onclick=()=>{revealed=false;draw();};$('homeBtn').onclick=()=>{if(busy)return;if(!$('editor').hidden){draft=null;home();return;}home();sync();};
 for(const button of document.querySelectorAll('[data-size]'))button.onclick=()=>{limit=+button.dataset.size;for(const b of document.querySelectorAll('[data-size]'))b.setAttribute('aria-pressed',String(b===button));};
 let suppressTap=false,down=null;
 const ignored=e=>busy||(suppressTap&&e.detail!==0);
 $('reveal').onclick=e=>{if(ignored(e)||!session?.cards[session.index])return;revealed=true;draw();};
 $('again').onclick=e=>{if(!ignored(e))grade(false);};$('correct').onclick=e=>{if(!ignored(e))grade(true);};$('undo').onclick=undoGrade;
 $('card').onpointerdown=e=>{suppressTap=false;down=e.isPrimary&&e.button===0?{x:e.clientX,y:e.clientY,id:e.pointerId,revealed}:null;};
 $('card').onpointercancel=()=>{down=null;suppressTap=true;};
 $('card').onpointerup=e=>{const start=down;down=null;if(!start||start.id!==e.pointerId)return;const dx=e.clientX-start.x,dy=e.clientY-start.y;
 if(Math.hypot(dx,dy)>10)suppressTap=true;
 if(start.revealed&&!busy&&Math.abs(dx)>=Math.min(90,Math.max(56,$('card').clientWidth*.2))&&Math.abs(dx)>Math.abs(dy)*1.5){e.preventDefault();grade(dx>0);}};
 $('edit').onclick=()=>edit(false);$('create').onclick=()=>edit(true);$('cancelEdit').onclick=home;$('search').oninput=search;$('source').onchange=search;
 $('addLeague').onclick=()=>{const l=catalog.leagues.find(l=>l.id===$('source').value);draft.extra.push(...structuredClone(l.rows));populateEditor();};
 $('addMon').onclick=()=>{const fast=[...$('fastOptions').querySelectorAll('input:checked')].map(x=>x.value),charged=[...$('chargedOptions').querySelectorAll('input:checked')].map(x=>x.value);if(!fast.length||!charged.length){message('通常技とゲージ技を1つ以上選んでください',true);return;}
 const existing=C.deckCards(draft,catalog).items.filter(c=>c.species===editingSpecies&&!c.sequence);draft.excluded=[...new Set([...(draft.excluded||[]),...existing.map(C.key)])];draft.extra=draft.extra.filter(r=>r.species!==editingSpecies||r.sequences);draft.extra.push({species:editingSpecies,fast,charged});const keys=new Set(C.cards([{species:editingSpecies,fast,charged}],catalog).items.map(C.key));draft.excluded=draft.excluded.filter(k=>!keys.has(k));populateEditor();message('技の選択を反映しました。最後に保存してください。');};
 $('addSequence').onclick=()=>{const fast=[...$('fastOptions').querySelectorAll('input:checked')].map(x=>x.value),ids=[...$('sequenceOptions').querySelectorAll('select')].map(x=>x.value);
  if(!fast.length){message('通常技を1つ以上選んでください',true);return;}
  const row={species:editingSpecies,fast,charged:[...new Set(ids)],sequences:[ids]};
  const compiled=C.cards([row],catalog);if(compiled.invalid||!compiled.items.length){message('使用順の技を確認してください',true);return;}
  draft.extra.push(row);const keys=new Set(compiled.items.map(C.key));draft.excluded=(draft.excluded||[]).filter(k=>!keys.has(k));populateEditor();message('使用順を別問題に追加しました。最後に保存してください。');
 };
 $('saveDeck').onclick=async()=>{if(busy)return;busy=true;try{draft.name=$('deckName').value.trim();if(!draft.name)throw Error('デッキ名を入力してください');const next=decks.filter(d=>d.id!==draft.id).concat(draft);await saveDecks(next);home();$('deck').value=draft.id;deckInfo();message('デッキを保存しました');}catch(e){message(e.message,true);}finally{busy=false;}};
 $('sync').onclick=()=>sync(true);$('connect').onclick=async()=>{try{await api('/app-api/session',{});$('key').value='';await sync(true);}catch(e){message(e.message,true);}};
 $('notify').onchange=updateNotify;$('hour').onchange=updateNotify;if(native){$('notify').checked=native.isEnabled();$('hour').value=String(native.notificationHour());}
 $('export').onclick=async()=>{const content=JSON.stringify({version:1,decks,reviews:Object.values(reviews)});if(native){native.exportBackup(content);return;}const url=URL.createObjectURL(new Blob([content],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='move-count-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);};
 $('restore').onchange=async()=>{try{const data=JSON.parse(await $('restore').files[0].text());validateBackup(data);if(!confirm('同じIDのデッキ・復習記録をバックアップの内容で置き換えますか？'))return;const replacements=new Map(decks.map(d=>[d.id,d]));for(const d of data.decks)replacements.set(d.id,d);const next=[...replacements.values()];await transaction(['kv','reviews'],tx=>{put(tx,'decks',next);put(tx,'session',null);put(tx,'undo',null);for(const r of data.reviews)tx.objectStore('reviews').put(r,r.id);});decks=next;for(const r of data.reviews)reviews[r.id]=r;session=null;undo=null;home();message('復元しました');}catch(e){message('復元できません。'+e.message,true);}finally{$('restore').value='';}};
 home();message('');sync();setInterval(()=>{if(!$('home').hidden)sync();},300000);
}catch(e){message('学習データを開けません。保存データを消さずにアプリを開き直してください。'+e.message,true);}
})();
