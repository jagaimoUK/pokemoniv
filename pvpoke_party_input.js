// Name resolution is shared by cards and bulk import. Persist stable species IDs.
function normalizePartyName(value){return String(value||'').normalize('NFKC').trim().toLowerCase().replace(/[ぁ-ゖ]/g,c=>String.fromCharCode(c.charCodeAt(0)+0x60));}
function partyDisplay(id,cat=catalog){const p=cat[id];if(!p)return id;let ja=p.name_ja||p.name||id;if(id.split('_').includes('shadow')&&!ja.includes('シャドウ'))ja='シャドウ'+ja;return ja;}
function partySearch(query,cat=catalog){const q=normalizePartyName(query);if(!q)return [];return Object.entries(cat).map(([id,p])=>({id,p,terms:[id,p.name,p.name_ja,...(p.aliases||[])].filter(Boolean).map(normalizePartyName)})).filter(r=>r.terms.some(t=>t.includes(q))).sort((a,b)=>Number(b.terms.includes(q))-Number(a.terms.includes(q))||a.id.localeCompare(b.id)).slice(0,20);}
function resolvePartyName(value,cat=catalog){const q=normalizePartyName(value);if(!q)return '';if(cat[q])return q;const exact=Object.entries(cat).filter(([id,p])=>[id,p.name,p.name_ja,...(p.aliases||[])].some(t=>t&&normalizePartyName(t)===q));if(exact.length===1)return exact[0][0];throw Error(exact.length?'姿が複数あります。候補から姿を選んでください':'ポケモン名を確認し、候補から選んでください');}
function partyDefaultMoves(p){const d=p.default_moves;const valid=d&&p.fastMoves.includes(d.fast)&&p.chargedMoves.includes(d.charged1)&&p.chargedMoves.includes(d.charged2)&&d.charged1!==d.charged2;return {moves:valid?{...d}:{fast:p.fastMoves[0]||'',charged1:p.chargedMoves[0]||'',charged2:p.chargedMoves[1]||''},recommended:!!valid};}
function partyMoveLabel(id, moveNames=partyMoveNames){const p=moveNames[id];return p?.name_ja||p?.name||id;}
function resolvePartyMove(value, allowed, moveNames=partyMoveNames){
 const q=normalizePartyName(value);
 if(!q)throw Error('技名が空です');
 const exact=allowed.filter(id=>normalizePartyName(id)===q);
 if(exact.length===1)return exact[0];
 const matches=allowed.filter(id=>[moveNames[id]?.name_ja,moveNames[id]?.name]
   .some(name=>name&&normalizePartyName(name)===q));
 if(matches.length===1)return matches[0];
 throw Error(matches.length?'同じ名前の技が複数あります。英語名または技IDを指定してください':'技「'+value+'」は選択したポケモンの習得技にありません');
}
function isPartyMegaSpecies(id,p=catalog[id]){const s=String(id||'').toLowerCase();return Boolean(p&&((Array.isArray(p.tags)&&p.tags.includes('mega'))||/(?:_|-)(?:mega(?:_[xy])?|primal)$/.test(s)));}
function partyExtraChargedMoves(p){return Array.isArray(p?.extraChargedMoves)?p.extraChargedMoves:[];}
function createMon(data={}){
 const box=node('details',null,'mon'),summary=node('summary',data.species?partyDisplay(data.species):'ポケモンを選ぶ');box.append(summary);
 const body=node('div',null,'fields');box.append(body);
 const label=node('label','ポケモン名（日本語・英語）'),input=node('input');input.dataset.field='species';input.autocomplete='off';input.placeholder='例：サニーゴ / Corsola';input.value=data.species?partyDisplay(data.species):'';input.dataset.species=data.species||'';input.setAttribute('role','combobox');input.setAttribute('aria-expanded','false');
 const suggestions=node('div',null,'suggestions');suggestions.hidden=true;const hint=node('p');hint.style.gridColumn='1/-1';hint.style.fontSize='12px';label.append(input,suggestions);body.append(label);
 for(const [k,title] of [['fast','通常技'],['charged1','ゲージ技1'],['charged2','ゲージ技2']]){const l=node('label',title),select=node('select');select.dataset.field=k;select.setAttribute('aria-label',title);select.onchange=()=>{syncMoves();inputRevision++;};l.append(select);body.append(l);}
 const megaWrap=node('label','メガレベル'),megaSelect=node('select');megaWrap.dataset.megaWrap='mega_level';megaWrap.hidden=true;megaSelect.dataset.field='mega_level';megaSelect.setAttribute('aria-label','メガレベル');for(const [v,t] of [['1','1（基礎）'],['2','2（高レベル）'],['3','3（MAX）'],['4','4（スーパーMAX）']])megaSelect.append(new Option(t,v));megaSelect.value='3';megaSelect.onchange=()=>{inputRevision++;};megaWrap.append(megaSelect);body.append(megaWrap);
 const c3Wrap=node('label','追加ゲージ技（3つ目）'),c3Select=node('select');c3Wrap.dataset.megaWrap='charged3';c3Wrap.hidden=true;c3Select.dataset.field='charged3';c3Select.setAttribute('aria-label','追加ゲージ技（3つ目）');c3Select.append(new Option('なし',''));c3Select.onchange=()=>{syncMoves();inputRevision++;};c3Wrap.append(c3Select);body.append(c3Wrap);
 function syncMoves(){const one=body.querySelector('[data-field=charged1]'),two=body.querySelector('[data-field=charged2]');for(const s of [one,two])for(const o of s.options)o.disabled=o.value===(s===one?two.value:one.value);if(!c3Wrap.hidden){for(const o of c3Select.options)o.disabled=!!o.value&&(o.value===one.value||o.value===two.value);if(c3Select.value&&(c3Select.value===one.value||c3Select.value===two.value))c3Select.value='';}}
 function choose(id,preserve=false){const p=catalog[id];if(!p)return;input.value=partyDisplay(id);input.dataset.species=id;input.setCustomValidity('');summary.textContent=partyDisplay(id);const rec=partyDefaultMoves(p);for(const k of ['fast','charged1','charged2']){const select=body.querySelector('[data-field='+k+']');select.replaceChildren();for(const m of k==='fast'?p.fastMoves:p.chargedMoves)select.append(new Option(partyMoveLabel(m),m));select.value=preserve&&data[k]&&(k==='fast'?p.fastMoves:p.chargedMoves).includes(data[k])?data[k]:rec.moves[k];}if(isPartyMegaSpecies(id,p)){megaWrap.hidden=false;const defMl=Array.isArray(p.tags)&&p.tags.includes('supermega')?'4':'3';megaSelect.value=preserve&&data.mega_level!=null&&['1','2','3','4'].includes(String(data.mega_level))?String(data.mega_level):defMl;const extras=partyExtraChargedMoves(p);c3Select.replaceChildren(new Option('なし',''));if(extras.length){for(const m of extras)c3Select.append(new Option(partyMoveLabel(m),m));c3Wrap.hidden=false;c3Select.value=preserve&&data.charged3&&extras.includes(data.charged3)?data.charged3:'';}else{c3Wrap.hidden=true;c3Select.value='';}}else{megaWrap.hidden=true;c3Wrap.hidden=true;c3Select.replaceChildren(new Option('なし',''));c3Select.value='';}syncMoves();hint.textContent=rec.recommended?'初期技：スーパーリーグ推奨。大会・パーティによって最適な技は変わります。':'推奨構成が未登録のため、覚えられる技を仮入力しています。技を確認してください。';suggestions.hidden=true;input.setAttribute('aria-expanded','false');}
 let composing=false,picking=false,lockedPick=null,pickTimer=null;
 function clampPicked(){if(!lockedPick)return false;input.value=lockedPick.text;input.dataset.species=lockedPick.id;input.setCustomValidity('');suggestions.hidden=true;input.setAttribute('aria-expanded','false');return true;}
 function pickSuggestion(id){
  const text=partyDisplay(id);if(!catalog[id])return;
  picking=true;composing=false;lockedPick={id,text};
  if(pickTimer&&typeof clearTimeout==='function')clearTimeout(pickTimer);
  input.blur?.();
  choose(id);
  clampPicked();
  if(typeof inputRevision!=='undefined')inputRevision++;
  if(typeof setTimeout==='function'){
   setTimeout(()=>{clampPicked();},0);
   pickTimer=setTimeout(()=>{clampPicked();picking=false;lockedPick=null;pickTimer=null;},180);
  }else{picking=false;lockedPick=null;}
 }
 function suggest(){if(clampPicked())return;input.dataset.species='';const matches=partySearch(input.value);suggestions.replaceChildren();for(const r of matches){const b=node('button',partyDisplay(r.id)+' / '+(r.p.name||r.id));b.type='button';b.onmousedown=e=>{picking=true;e.preventDefault();};b.ontouchstart=()=>{picking=true;};b.onclick=()=>{pickSuggestion(r.id);};suggestions.append(b);}suggestions.hidden=!matches.length;input.setAttribute('aria-expanded',String(matches.length>0));}
 input.oncompositionstart=()=>{if(!clampPicked())composing=true;};
 input.oncompositionend=()=>{composing=false;if(clampPicked())return;suggest();};
 input.oninput=()=>{if(clampPicked())return;suggest();};
 input.onfocus=()=>{if(picking||lockedPick)return;if(!input.dataset.species)suggest();};
 input.onkeydown=e=>{if(e.isComposing||composing)return;if(e.key==='Escape'){suggestions.hidden=true;input.setAttribute('aria-expanded','false');}if(e.key==='ArrowDown'&&!suggestions.hidden){e.preventDefault();suggestions.querySelector('button')?.focus();}if(e.key==='Enter'){e.preventDefault();try{choose(resolvePartyName(input.value));}catch(err){hint.textContent=err.message;}}};
 input.onchange=()=>{if(picking||clampPicked())return;try{choose(resolvePartyName(input.value));}catch(err){input.setCustomValidity(err.message);hint.textContent=err.message;}};
 for(const [k,title] of [['atk','攻撃IV（任意）'],['def','防御IV（任意）'],['hp','HP IV（任意）'],['level_override','指定レベル（任意）']]){const l=node('label',title),x=node('input');x.type='number';x.dataset.field=k;x.value=data[k]??'';x.min=k==='level_override'?1:0;x.max=k==='level_override'?50:15;x.step=k==='level_override'?'.5':'1';l.append(x);body.append(l);}
 body.append(hint);const l=node('label'),locked=node('input');locked.type='checkbox';locked.dataset.field='locked';locked.checked=!!data.locked;l.append(locked,document.createTextNode(' 自動構築では固定'));body.append(l);if(data.species)choose(data.species,true);return box;
}
function parseCsv(source){return source.trim().split(/\r?\n/).map(x=>x.trim()).filter(Boolean).map((line,i)=>{const a=line.split(',').map(s=>s.trim());if(![1,4,7].includes(a.length))throw Error((i+1)+'行目は名前だけ、または従来の4・7列CSVで指定してください');const id=resolvePartyName(a[0]),p=catalog[id];const moves=a.length===1?partyDefaultMoves(p).moves:{
 fast:resolvePartyMove(a[1],p.fastMoves),charged1:resolvePartyMove(a[2],p.chargedMoves),charged2:resolvePartyMove(a[3],p.chargedMoves)};
 if(moves.charged1===moves.charged2)throw Error((i+1)+'行目: ゲージ技は異なる2種類を指定してください');const r={species:id,...moves};if(a.length===7)for(let n=4;n<7;n++){if(!/^(?:[0-9]|1[0-5])$/.test(a[n]))throw Error((i+1)+'行目のIVが不正です');r[['atk','def','hp'][n-4]]=Number(a[n]);}return r;});}
function partyRosterEditor(textareaId,max){
 let importError=null;const text=$(textareaId),editor=node('div'),cards=node('div',null,'grid'),add=node('button','ポケモンを追加');add.type='button';editor.append(cards,add);text.before(editor);
 const advanced=node('details');advanced.append(node('summary','まとめて入力・CSV（任意）'));text.before(advanced);advanced.append(text);text.placeholder='サニーゴ\nガラルサニーゴ\nAzumarill';
 function rows(){if(importError)throw importError;return [...cards.children].map(readPartyCard).filter(x=>x.species);}
 function write(){let selected;try{selected=rows();}catch(_){return;}const rowsToWrite=selected;text.value=rowsToWrite.map(r=>[r.species,r.fast,r.charged1,r.charged2,...(['atk','def','hp'].every(k=>k in r)?[r.atk,r.def,r.hp]:[])].join(',')).join('\n');add.disabled=cards.children.length>=max;if(textareaId==='strategyEnemy'){try{strategyTargets();}catch(_){}}}
 function append(row={}){const card=createMon(row);card.open=true;const remove=node('button','この枠を外す');remove.type='button';remove.onclick=()=>{card.remove();write();inputRevision++;};card.append(remove);card.addEventListener('input',write);card.addEventListener('change',write);card.addEventListener('click',e=>{if(e.target.closest('.suggestions button'))write();});cards.append(card);add.disabled=cards.children.length>=max;}
 add.onclick=()=>{append();inputRevision++;};
 function refresh(provided){cards.replaceChildren();importError=null;try{for(const r of Array.isArray(provided)?provided:parseCsv(text.value))append(r);}catch(err){importError=err;status(err.message);}add.disabled=cards.children.length>=max;}
 text.addEventListener('change',refresh);refresh();return {refresh,rows};
}
// Analysis requires six explicitly selected species; draft saves and auto-build remain permissive.
function validatePartyAnalysisMembers(rows,cat=catalog){
 if(!Array.isArray(rows)||rows.length!==6)throw Error('自分の6体を指定してください');
 for(const [i,p] of rows.entries()){
  const id=String(p?.species||'').trim();
  if(!id)throw Error('自分の候補: '+(i+1)+'枠目のポケモンが未選択です');
  if(!cat[id])throw Error('自分の候補: '+(i+1)+'枠目のポケモンが未登録です ('+id+')');
 }
 return rows;
}
function readPartyCard(box){const r={};box.querySelectorAll('[data-field]').forEach(x=>{const k=x.dataset.field;if(k==='locked')return;const wrap=x.closest?.('[data-mega-wrap]');if(wrap&&wrap.hidden)return;if(k==='species'){if(!x.value.trim())return;r.species=x.dataset.species||resolvePartyName(x.value);return;}if(x.value.trim())r[k]=(x.type==='number'||k==='mega_level')?Number(x.value):x.value;});return r;}
if(typeof module!=='undefined')module.exports={normalizePartyName,partyDisplay,partySearch,resolvePartyName,partyDefaultMoves,partyMoveLabel,resolvePartyMove,isPartyMegaSpecies,partyExtraChargedMoves,createMon,readPartyCard,validatePartyAnalysisMembers};

function partyRosterRows(id){return rosterEditors[id]?rosterEditors[id].rows():parseCsv($(id).value);}
