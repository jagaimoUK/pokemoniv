const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
const els={},calls=[],listeners={};function element(){return {value:'',hidden:false,children:[],append(x){this.children.push(x)},replaceChildren(){this.children=[]},scrollIntoView(){this.scrolled=true},focus(){this.focused=true}};}
const el=id=>els[id]??=element();el('workspace').hidden=true;
let authorized=false,importFail=false,imports=0;
const raw='個体値厳選\n# ヌオー\n0,11,12 CP717 | ウパー';
const job={candidate:{species:'quagsire',fast:'MUD_SHOT',charged1:'AQUA_TAIL',charged2:'STONE_EDGE'},ivs:'0,11,12',candidate_count:1,name:'ヌオー',warnings:[],source_records:[{ivs:'0/11/12',cp:717,species:'wooper',search_string:'Wooper&0attack&3defense&3hp&cp717'}],source_sections:[1]};
const context={URLSearchParams,Uint8Array,TextDecoder,atob,location:{hash:'#ivdata='+Buffer.from(raw).toString('base64url'),pathname:'/app',search:''},history:{replaceState(){context.location.hash=''}},window:{addEventListener:(name,fn)=>listeners[name]=fn},document:{getElementById:el,createElement:element},sessionStorage:{getItem:()=>null},fetch:async(path,opts)=>{
 calls.push(path);const data=JSON.parse(opts.body);
 if(!authorized)return {status:401};
 if(path.endsWith('/catalog'))return {ok:true,json:async()=>({ready:true,species:{quagsire:{name:'Quagsire',name_ja:'ヌオー',nickname_code:'Quag',fastMoves:['MUD_SHOT'],chargedMoves:['AQUA_TAIL','STONE_EDGE']}},app_presets:[job.candidate]})};
 if(path.endsWith('/meta-presets'))return {ok:true,json:async()=>({items:[{id:'legacy',name:'標準',rows:10,default:true,sha256:'a'.repeat(64)}],default_id:'legacy'})};
 if(path.endsWith('/import')){imports++;assert.equal(data.text,el('importText').value);if(importFail)return {status:400,ok:false,json:async()=>({error:'取り込み失敗'})};return {ok:true,json:async()=>({jobs:[job]})};}
 throw Error('Unexpected automatic action '+path);
}};
vm.createContext(context);vm.runInContext(script,context);
(async()=>{
 await new Promise(r=>setImmediate(r));
 assert.equal(imports,0,'Do not import before authentication');assert.equal(el('importText').value,raw);
 assert.equal(context.location.hash,'','Remove fragment promptly');
 authorized=true;await context.connect(true);
 assert.equal(imports,1,'Import once after catalog and meta load');
 assert.equal(el('ivs').value,'0,11,12');assert(el('comparisonSettings').scrolled&&el('comparisonSettings').focused);
 assert.equal(vm.runInContext('importedSingle.source_records[0].cp',context),717);
 assert(!calls.some(p=>p.endsWith('/run')),'Handoff must never start calculations');
 await context.autoImportReader();assert.equal(imports,1);
 vm.runInContext('active=true',context);el('importText').value='current draft';
 context.location.hash='#ivdata='+Buffer.from(raw+'\n1,2,3').toString('base64url');listeners.hashchange();
 assert.equal(el('importText').value,'current draft','An active calculation keeps its current input');
 assert.equal(imports,1);context.setBusy(false);await new Promise(r=>setImmediate(r));
 assert.equal(imports,2,'Deferred handoff imports after active work finishes');
 importFail=true;context.location.hash='#ivdata='+Buffer.from(raw).toString('base64url');listeners.hashchange();await new Promise(r=>setImmediate(r));
 assert(el('message').textContent.includes('取り込み失敗'));assert.equal(el('importText').value,raw);assert.equal(el('ivs').value,'0,11,12','A failed import preserves the previous imported IVs');
 console.log('Authenticated auto-import, jump, same-tab handoff, active deferral, CP preservation and error recovery: OK');
})();
