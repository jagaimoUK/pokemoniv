/* Known browser stores only. Never reads cookies, passwords or access tokens. */
(function(root){
'use strict';
const FORMAT='pokemoniv-browser-backup-v1', MAX_BYTES=20*1024*1024;
const LOCAL=['pvpoke-app-movesets-v1'];
const SESSION=['pvpoke-app-batch','pvpoke-app-run'];
const DB='pokemon-move-flashcards', STORES=['kv','reviews'];
function fail(){throw Error('バックアップの形式が不正です。元のファイルを確認してください。');}
function validate(data){
 if(!data||data.format!==FORMAT||!data.local||!data.session||!data.flashcards)fail();
 if(new TextEncoder().encode(JSON.stringify(data)).byteLength>MAX_BYTES)fail();
 for(const [area,keys] of [[data.local,LOCAL],[data.session,SESSION]]){
  if(Object.keys(area).length!==keys.length||Object.keys(area).some(k=>!keys.includes(k)))fail();
  for(const key of keys)if(area[key]!==null&&typeof area[key]!=='string')fail();
 }
 if(data.integrity!==undefined){const i=data.integrity;
  if(!i||i.algorithm!=='SHA-256'||!Number.isSafeInteger(i.bytes)||i.bytes<0||!(/^[a-f0-9]{64}$/).test(i.value))fail();
 }
 if(Object.keys(data.flashcards).length!==STORES.length)fail();
 for(const store of STORES){
  const rows=data.flashcards[store];if(!Array.isArray(rows)||rows.length>100000)fail();
  const seen=new Set();
  for(const row of rows){
   if(!Array.isArray(row)||row.length!==2||typeof row[0]!=='string'||row[0].length>2048||seen.has(row[0]))fail();
   seen.add(row[0]);
  }
 }
 return data;
}
function conflicts(current,incoming){
 const out=[];
 for(const area of ['local','session'])for(const key of Object.keys(incoming[area])){
  const before=current[area][key],after=incoming[area][key];
  if(before!==null&&after!==null&&before!==after)out.push(area+':'+key);
 }
 for(const store of STORES){
  const existing=new Map(current.flashcards[store]);
  for(const [key,value] of incoming.flashcards[store])
   if(existing.has(key)&&JSON.stringify(existing.get(key))!==JSON.stringify(value))out.push('flashcards:'+store+':'+key);
 }
 return out;
}
function covers(current,incoming){
 for(const area of ['local','session'])for(const key of Object.keys(incoming[area]))
  if(incoming[area][key]!==null&&current[area][key]!==incoming[area][key])return false;
 for(const store of STORES){const rows=new Map(current.flashcards[store]);
  for(const [key,value] of incoming.flashcards[store])if(!rows.has(key)||JSON.stringify(rows.get(key))!==JSON.stringify(value))return false;
 }
 return true;
}
function openDB(){return new Promise((resolve,reject)=>{
 const request=indexedDB.open(DB,1);
 request.onupgradeneeded=()=>{for(const store of STORES)request.result.createObjectStore(store);};
 request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
 request.onblocked=()=>reject(Error('フラッシュカードを開いた別の画面を閉じてください。'));
});}
function entries(db){return new Promise((resolve,reject)=>{
 const result={kv:[],reviews:[]},tx=db.transaction(STORES,'readonly');
 for(const store of STORES){const request=tx.objectStore(store).openCursor();request.onsuccess=()=>{
  const cursor=request.result;if(cursor){result[store].push([cursor.key,cursor.value]);cursor.continue();}
 };}
 tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);
});}
async function capture(){
 const db=await openDB();
 try{return validate({format:FORMAT,origin:location.origin,created:new Date().toISOString(),
  local:Object.fromEntries(LOCAL.map(key=>[key,localStorage.getItem(key)])),
  session:Object.fromEntries(SESSION.map(key=>[key,sessionStorage.getItem(key)])),flashcards:await entries(db)});
 }finally{db.close();}
}

async function seal(data){
 validate(data);
 const bytes=new TextEncoder().encode(JSON.stringify(data));
 const digest=await crypto.subtle.digest('SHA-256',bytes);
 const value=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
 return validate({...data,integrity:{algorithm:'SHA-256',bytes:bytes.byteLength,value}});
}
async function verifyIntegrity(data){
 validate(data);
 if(!data.integrity)return data; // Legacy version 1 files remain importable.
 const {integrity,...unsigned}=data;
 const bytes=new TextEncoder().encode(JSON.stringify(unsigned));
 if(bytes.byteLength!==integrity.bytes||(await seal(unsigned)).integrity.value!==integrity.value)fail();
 return data;
}
function previewText(data){
 const local=Object.values(data.local).filter(x=>x!==null).length;
 const session=Object.values(data.session).filter(x=>x!==null).length;
 return 'ブラウザ内：技構成 '+local+'項目、計算再開情報 '+session+'項目、フラッシュカード設定 '+data.flashcards.kv.length+'件、復習記録 '+data.flashcards.reviews.length+'件。サーバーのSQLite・ZIPやAndroidの読み取り履歴は含みません。';
}
function download(data){
 const blob=new Blob([JSON.stringify(data)],{type:'application/json'}),url=URL.createObjectURL(blob);
 const link=document.createElement('a');link.href=url;link.download='pokemoniv-browser-backup-'+Date.now()+'.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
}
async function restore(data){
 await verifyIntegrity(data);
 // Close other tabs first. Another document's Web Storage is not transactional.
 const previous=await capture();
 if(conflicts(previous,data).length)throw Error('移行先に異なる保存データがあります。安全のため上書きしていません。移行先もバックアップしてから内容を確認してください。');
 const db=await openDB();
 try{
  // Storage quota failure must happen BEFORE committing IndexedDB. Roll back
  // only changes made by this import; never remove unrelated browser keys.
  const written=[];
  try{
   for(const [name,store] of [['local',localStorage],['session',sessionStorage]])for(const key of Object.keys(data[name])){
    if(data[name][key]!==null&&previous[name][key]===null){store.setItem(key,data[name][key]);written.push([store,key,data[name][key]]);}
   }
   await new Promise((resolve,reject)=>{
    const tx=db.transaction(STORES,'readwrite');
    tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('保存できません。'));
    for(const store of STORES)for(const [key,value] of data.flashcards[store]){
     // Recheck within the actual write transaction so another flashcard tab
     // cannot overwrite a newer review between capture and commit.
     const object=tx.objectStore(store),request=object.get(key);
     request.onsuccess=()=>{
      if(request.result===undefined)object.add(value,key);
      else if(JSON.stringify(request.result)!==JSON.stringify(value))tx.abort();
     };
    }
   });
  }catch(error){for(const [store,key,value] of written)if(store.getItem(key)===value)store.removeItem(key);throw error;}
 }finally{db.close();}
 const result=await capture();
 if(!covers(result,data))throw Error('復元後の照合に失敗しました。元のバックアップは保持してください。');
 return result;
}
const api={FORMAT,MAX_BYTES,validate,conflicts,covers,capture,restore,seal,verifyIntegrity,previewText};
if(typeof module==='object'&&module.exports)module.exports=api;
root.PokemonIVBrowserMigration=api;
if(typeof document==='undefined')return;
const $=id=>document.getElementById(id),say=(text)=>{$('migrationStatus').textContent=text;};
$('migrationPreview').onclick=async()=>{try{say(previewText(await capture()));}catch(error){say('保存対象を確認できませんでした。'+error.message);}};
$('migrationExport').onclick=async()=>{try{const data=await seal(await capture());download(data);say(previewText(data)+' SHA256付きファイルの保存を開始しました。Androidのダウンロード一覧でも確認してください。');}catch(error){say('保存データを書き出せませんでした。'+error.message);}};
$('migrationFile').onchange=async()=>{
 const file=$('migrationFile').files[0];$('migrationImport').disabled=true;root.migrationPending=null;
 if(!file)return;
 try{
  if(file.size>MAX_BYTES)throw Error('ファイルは20MB以下にしてください。');
  const data=await verifyIntegrity(validate(JSON.parse(await file.text()))),current=await capture();
  if(conflicts(current,data).length)throw Error('移行先のデータと競合しています。上書きせず停止しました。');
  root.migrationPending=data;$('migrationImport').disabled=false;
  say('ファイルを検証しました。'+previewText(data)+' 復元ボタンを押すまで現在のデータは変更されません。');
 }catch(error){say(error.message);}
};
$('migrationImport').onclick=async()=>{
 const data=root.migrationPending;if(!data)return;$('migrationImport').disabled=true;
 try{await restore(data);root.migrationPending=null;say('復元と照合が完了しました。このタブで「厳選アプリへ」を開いてください。ログインは接続キーでやり直してください。');}
 catch(error){say('復元できませんでした。'+error.message);}
};
})(typeof globalThis==='object'?globalThis:this);
