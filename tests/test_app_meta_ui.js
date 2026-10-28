const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
const elements={},calls=[];
function element(){const e={value:'',textContent:'',hidden:false,disabled:false,children:[],style:{},attrs:{},setAttribute(k,v){this.attrs[k]=v},getAttribute(k){return this.attrs[k]},append(x){this.children.push(x)},replaceChildren(){this.children=[]}};Object.defineProperty(e,'id',{set(v){elements[v]=e}});return e;}
const el=id=>elements[id]??=element();
const original='quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n';
const items=[{id:'legacy',name:'既存',rows:87,source:'legacy',sha256:'a'.repeat(64),default:true},
 {id:'pvpoke:fantasy',name:'ファンタジーカップ',rows:27,source:'pvpoke',sha256:'b'.repeat(64)},
 ...Array.from({length:5},(_,i)=>({id:'pvpoke:'+i,name:'Cup '+i,rows:20,sha256:'b'.repeat(64)})),
 {id:'pvpoke:bad',name:'未完成',rows:1,available:false,unavailable_reason:'通常技なし'}];
let state={revision:0,default_id:'legacy',retrieved:'2026-10-27',items};let failSave=false,denyClipboard=false,exportRows=1,exportFail=false,exportDeferred=null,previewFail=false,previewDeferred=null,expectedCSV=original;const copied=[];
const context={document:{getElementById:el,createElement:element},navigator:{clipboard:{async writeText(text){if(denyClipboard)throw Error('clipboard denied');copied.push(text);}}},URLSearchParams,location:{hash:''},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}},
fetch:async(path,opts)=>{
 const data=JSON.parse(opts.body);calls.push({path,data});
 if(path==='/app-api/catalog')return {status:401,ok:false};
 let out;
 if(path==='/app-api/meta-presets')out=structuredClone(state);
 else if(path==='/app-api/meta-preset-export'){
  if(exportFail)return {status:400,ok:false,json:async()=>({error:'内容が更新されました'})};
  if(exportDeferred)await exportDeferred;
  const parts=Array.from({length:Math.ceil(exportRows/100)},(_,i)=>({start:i*100+1,end:Math.min((i+1)*100,exportRows),csv:('part'+i+','+original).trim()}));
  out={id:data.id,sha256:data.expected_sha256,name:'Export test',rows:exportRows,parts};
 }
 else if(path==='/app-api/meta-preview'){
  if(previewDeferred)await previewDeferred;
  if(previewFail)return {status:400,ok:false,json:async()=>({error:'メタ一覧の検証失敗'})};
  const count=data.csv.trim().split('\n').length;out={rows:1,input_rows:count,duplicate_count:count-1,duplicate_lines:count>1?[2]:[],sha256:'c'.repeat(64),changed:false};
 }
 else if(path==='/app-api/meta-preset-save'){
  if(failSave)return {status:400,ok:false,json:async()=>({error:'別の画面で更新'})};
  assert.equal(data.revision,state.revision);
  if(data.action==='create'){
   assert.equal(data.csv,expectedCSV);assert.equal(data.expected_sha256,'c'.repeat(64));
   const id='custom:'+(state.items.filter(p=>p.source==='custom').length+1);state.items.push({id,name:data.name,rows:1,source:'custom',sha256:'c'.repeat(64)});state.saved_id=id;
  }else if(data.action==='default'){
   state.default_id=data.id;state.items.forEach(p=>p.default=p.id===data.id);
  }else if(data.action==='favorite')state.items.find(p=>p.id===data.id).favorite=data.favorite;
  state.revision++;out=structuredClone(state);
 }else throw Error('unexpected '+path);
 return {status:200,ok:true,json:async()=>out};
}};
vm.createContext(context);vm.runInContext(script,context);
(async()=>{
 await context.refreshMetaStatus(true);
 assert(el('selectedMeta').textContent.includes('既存'));assert.equal(el('metaQuick').children.length,4);
 assert.equal(el('metaQuick').children.filter(b=>b.getAttribute('aria-pressed')==='true').length,1);
 assert.equal(el('metaDefault').disabled,true);
 context.chooseMeta('pvpoke:fantasy');assert(el('selectedMeta').textContent.includes('ファンタジー'));
 assert.equal(calls.filter(x=>x.path.includes('save')).length,0,'selection is local and sends no write');
 await el('metaFavorite').onclick();assert.equal(el('metaFavorite').getAttribute('aria-pressed'),'true');
 assert(el('metaQuick').children.some(b=>b.getAttribute('aria-label').includes('ファンタジー')));
 await el('metaDefault').onclick();await context.refreshMetaStatus(true);
 assert(el('selectedMeta').textContent.includes('ファンタジー'));assert(el('metaCurrentBadges').children.some(b=>b.textContent==='デフォルト'));assert.equal(el('metaDefault').disabled,true);
 vm.runInContext("active=true",context);context.chooseMeta('legacy');assert(el('selectedMeta').textContent.includes('ファンタジー'));vm.runInContext("active=false",context);
 context.chooseMeta('pvpoke:bad');assert(el('selectedMeta').textContent.includes('ファンタジー'));
 el('metaFile').files=[{name:'日常メタ.txt',size:original.length,async text(){return original}}];await el('metaFile').onchange();
 assert.equal(el('metaApply').disabled,false,'identical content can be saved under another name');
 assert.equal(el('metaName').value,'日常メタ');assert(el('metaPreview').textContent.includes('上書きしません'));
 await el('metaApply').onclick();assert(el('metaNotice').textContent.includes('保存完了'));assert(el('selectedMeta').textContent.includes('日常メタ'));
 assert.equal(state.default_id,'pvpoke:fantasy','create must not overwrite default');
 failSave=true;await el('metaDefault').onclick();assert(el('metaNotice').textContent.includes('別の画面'));
 assert(el('selectedMeta').textContent.includes('日常メタ'));
 // Export selected content; no save or calculation is triggered.
 const writes=calls.filter(c=>c.path==='/app-api/meta-preset-save').length;
 await el('metaExport').onclick();assert.equal(copied.length,1);
 assert(el('metaExportStatus').textContent.includes('コピーしました'));
 const request=calls.findLast(c=>c.path==='/app-api/meta-preset-export');
 assert.equal(request.data.id,'custom:1');assert.equal(request.data.expected_sha256,'c'.repeat(64));
 exportRows=101;await el('metaExport').onclick();assert.equal(copied.length,1,'split content needs explicit part selection');
 assert.equal(el('metaExportParts').children.length,2);await el('metaExportParts').children[1].onclick();assert(copied.at(-1).startsWith('part1,'));
 const staleButton=el('metaExportParts').children[0];context.chooseMeta('legacy');
 await staleButton.onclick();assert.equal(copied.length,2,'old part cannot be copied after selecting another meta');
 exportRows=1;denyClipboard=true;await el('metaExport').onclick();
 assert.equal(el('metaExportFallback').hidden,false);assert(el('metaExportText').value.includes(original.trim()));
 assert(el('metaExportStatus').textContent.includes('自動コピーできません'));
 denyClipboard=false;exportFail=true;await el('metaExport').onclick();assert(el('metaExportStatus').textContent.includes('内容が更新'));
 assert.equal(el('metaExportFallback').hidden,true);assert.equal(el('metaExport').disabled,false);
 exportFail=false;let release;exportDeferred=new Promise(resolve=>release=resolve);
 const pending=el('metaExport').onclick();assert.equal(el('metaExport').disabled,true);
 context.chooseMeta('pvpoke:fantasy');release();await pending;exportDeferred=null;
 assert.equal(copied.length,2,'discard slow response for previous selection');
 assert.equal(calls.filter(c=>c.path==='/app-api/meta-preset-save').length,writes);
 assert.equal(calls.filter(c=>c.path==='/app-api/run').length,0);
 // File-free paste uses the same preview/save and explains consolidation.
 failSave=false;expectedCSV=original+original;el('metaName').value='貼り付けメタ';el('metaText').value=expectedCSV;el('metaText').oninput();
 assert.equal(el('metaApply').disabled,true);
 const savesBeforePaste=calls.filter(c=>c.path==='/app-api/meta-preset-save').length;
 await el('metaTextPreview').onclick();assert.equal(el('metaApply').disabled,false);
 assert(el('metaPreview').textContent.includes('入力 2行 → 保存 1技構成'));
 assert(el('metaPreview').textContent.includes('重複 1行'));
 assert.equal(calls.filter(c=>c.path==='/app-api/meta-preset-save').length,savesBeforePaste,'preview is read-only');
 await el('metaApply').onclick();assert(el('selectedMeta').textContent.includes('貼り付けメタ'));
 assert(el('metaNotice').textContent.includes('重複1行を統合'));assert.equal(el('metaText').value,'');
 assert.equal(state.default_id,'pvpoke:fantasy');
 el('metaText').value=original;await el('metaTextPreview').onclick();
 el('metaText').value=original+'changed';await el('metaApply').onclick();assert.equal(el('metaApply').disabled,true);
 assert(el('metaNotice').textContent.includes('内容が確認後に変わりました'));
 el('metaText').value=original;previewFail=true;await el('metaTextPreview').onclick();
 assert.equal(el('metaApply').disabled,true);assert.equal(el('metaText').value,original);previewFail=false;
 let releasePreview;previewDeferred=new Promise(resolve=>releasePreview=resolve);
 const pendingPreview=el('metaTextPreview').onclick();assert.equal(el('metaText').disabled,true);
 el('metaText').value=original+'changed';el('metaText').oninput();releasePreview();await pendingPreview;previewDeferred=null;
 assert.equal(el('metaApply').disabled,true,'changed text invalidates slow preview');assert.equal(el('metaText').disabled,false);
 el('metaText').value='  ';const previews=calls.filter(c=>c.path==='/app-api/meta-preview').length;
 await el('metaTextPreview').onclick();assert.equal(calls.filter(c=>c.path==='/app-api/meta-preview').length,previews);
 assert(el('metaNotice').textContent.includes('貼り付けてください'));
 el('metaCancel').onclick();assert.equal(el('metaText').value,'');
 console.log('File-free meta paste: preview, duplicate notice, save, edit invalidation, errors, races and cancel OK');
 console.log('Meta CSV export: selected ID/hash, split parts, clipboard fallback, failures and stale responses OK');
 console.log('Meta presets: quick 4, default, favorites, named upload, read-only selection, failures OK');
})();
