const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
const elements={},calls=[];
function element(){const e={value:'',textContent:'',hidden:false,disabled:false,children:[],style:{},append(x){this.children.push(x)},replaceChildren(){this.children=[]}};Object.defineProperty(e,'id',{set(v){elements[v]=e}});return e;}
const el=id=>elements[id]??=element();
const original='quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n';
let status={source:'bundled',rows:87,sha256:'a'.repeat(64)};
let catalogCount=0;
const context={
 document:{getElementById:el,createElement:element},navigator:{clipboard:{async writeText(){}}},
 URLSearchParams,location:{hash:''},
 sessionStorage:{getItem(){return null},setItem(){},removeItem(){}},
 fetch:async(path,opts)=>{
  const data=JSON.parse(opts.body);
  calls.push({path,data});
  if(path==='/app-api/catalog'){
   if(++catalogCount===1)return {status:401,ok:false};
   return {status:200,ok:true,json:async()=>({ready:true,species:{quagsire:{name:'Quagsire',name_ja:'ヌオー',fastMoves:['MUD_SHOT'],chargedMoves:['STONE_EDGE','AQUA_TAIL']}},presets:[],app_presets:[]})};
  }
  if(path==='/app-api/meta-status')return {status:200,ok:true,json:async()=>status};
  if(path==='/app-api/meta-preview')return {status:200,ok:true,json:async()=>({
   rows:1,sha256:'b'.repeat(64),previous_sha256:'a'.repeat(64),changed:true,
   current_rows:87,added_count:1,removed_count:87,added:[original.trim()],removed:[],
   diff_limit:30,
  })};
  if(path==='/app-api/meta-apply'){
   assert.equal(data.expected_previous_sha256,'a'.repeat(64));
   assert.equal(data.expected_sha256,'b'.repeat(64));
   assert.equal(data.csv,original);
   status={source:'project_synced',rows:1,sha256:'b'.repeat(64)};
   return {status:200,ok:true,json:async()=>({...status,changed:true})};
  }
  throw Error('unexpected '+path);
 }
};
vm.createContext(context);vm.runInContext(script,context);
(async()=>{
 await Promise.resolve();
 assert.equal(calls.filter(x=>x.path==='/app-api/meta-preview').length,0);
 assert.equal(calls.filter(x=>x.path==='/app-api/meta-apply').length,0);
 assert.equal(el('metaApply').disabled,false===true);
 el('metaFile').files=[{name:'pvpokeメタポケモン.txt',size:original.length,async text(){return original}}];
 await el('metaFile').onchange();
 assert.equal(calls.filter(x=>x.path==='/app-api/meta-preview').length,1);
 assert.equal(calls.filter(x=>x.path==='/app-api/meta-apply').length,0);
 assert.equal(el('metaApply').disabled,false);
 assert(el('metaPreview').textContent.includes('追加 1件'));
 await el('metaApply').onclick();
 assert.equal(calls.filter(x=>x.path==='/app-api/meta-apply').length,1);
 assert.equal(el('metaApply').disabled,true);
 assert(el('metaStatus').textContent.includes('アップロード済みメタ'));
 assert(el('metaNotice').textContent.includes('保存完了'));
 console.log('Default meta untouched, opt-in preview then explicit apply: OK');
})();