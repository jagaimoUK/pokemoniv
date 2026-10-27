const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
const elements={},calls=[];
function element(){const e={value:'',textContent:'',hidden:false,disabled:false,children:[],style:{},setAttribute(){},append(x){this.children.push(x)},replaceChildren(){this.children=[]}};Object.defineProperty(e,'id',{set(v){elements[v]=e}});return e;}
const el=id=>elements[id]??=element();
const original='quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n';
const items=[{id:'legacy',name:'既存',rows:87,source:'legacy',sha256:'a'.repeat(64),default:true},
 {id:'pvpoke:fantasy',name:'ファンタジーカップ',rows:27,source:'pvpoke',sha256:'b'.repeat(64)},
 ...Array.from({length:5},(_,i)=>({id:'pvpoke:'+i,name:'Cup '+i,rows:20,sha256:'b'.repeat(64)})),
 {id:'pvpoke:bad',name:'未完成',rows:1,available:false,unavailable_reason:'通常技なし'}];
let state={revision:0,default_id:'legacy',retrieved:'2026-10-27',items};let failSave=false;
const context={document:{getElementById:el,createElement:element},navigator:{clipboard:{async writeText(){}}},URLSearchParams,location:{hash:''},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}},
fetch:async(path,opts)=>{
 const data=JSON.parse(opts.body);calls.push({path,data});
 if(path==='/app-api/catalog')return {status:401,ok:false};
 let out;
 if(path==='/app-api/meta-presets')out=structuredClone(state);
 else if(path==='/app-api/meta-preview')out={rows:1,sha256:'c'.repeat(64),changed:false};
 else if(path==='/app-api/meta-preset-save'){
  if(failSave)return {status:400,ok:false,json:async()=>({error:'別の画面で更新'})};
  assert.equal(data.revision,state.revision);
  if(data.action==='create'){
   assert.equal(data.csv,original);assert.equal(data.expected_sha256,'c'.repeat(64));
   state.items.push({id:'custom:1',name:data.name,rows:1,source:'custom',sha256:'c'.repeat(64)});state.saved_id='custom:1';
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
 context.chooseMeta('pvpoke:fantasy');assert(el('selectedMeta').textContent.includes('ファンタジー'));
 assert.equal(calls.filter(x=>x.path.includes('save')).length,0,'selection is local and sends no write');
 await el('metaFavorite').onclick();assert(el('metaFavorite').textContent.includes('解除'));
 assert(el('metaQuick').children.some(b=>b.textContent.includes('ファンタジー')));
 await el('metaDefault').onclick();await context.refreshMetaStatus(true);
 assert(el('selectedMeta').textContent.includes('ファンタジー'));assert(el('selectedMeta').textContent.includes('デフォルト'));
 vm.runInContext("active=true",context);context.chooseMeta('legacy');assert(el('selectedMeta').textContent.includes('ファンタジー'));vm.runInContext("active=false",context);
 context.chooseMeta('pvpoke:bad');assert(el('selectedMeta').textContent.includes('ファンタジー'));
 el('metaFile').files=[{name:'日常メタ.txt',size:original.length,async text(){return original}}];await el('metaFile').onchange();
 assert.equal(el('metaApply').disabled,false,'identical content can be saved under another name');
 assert.equal(el('metaName').value,'日常メタ');assert(el('metaPreview').textContent.includes('上書きしません'));
 await el('metaApply').onclick();assert(el('metaNotice').textContent.includes('保存完了'));assert(el('selectedMeta').textContent.includes('日常メタ'));
 assert.equal(state.default_id,'pvpoke:fantasy','create must not overwrite default');
 failSave=true;await el('metaDefault').onclick();assert(el('metaNotice').textContent.includes('別の画面'));
 assert(el('selectedMeta').textContent.includes('日常メタ'));
 console.log('Meta presets: quick 4, default, favorites, named upload, read-only selection, failures OK');
})();
