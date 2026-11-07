const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('pvpoke_app_ui.py','utf8'),script=source.split('<script>')[1].split('</script>')[0];
const els={},saved=new Map(),calls=[];
function element(){return {value:'',children:[],hidden:false,disabled:false,checked:false,append(e){this.children.push(e);},replaceChildren(){this.children=[];},setAttribute(){},focus(){}};}
const context={URLSearchParams,location:{hash:''},document:{getElementById:id=>els[id]??=element(),createElement:element},
 localStorage:{getItem:k=>saved.get(k)??null,setItem:(k,v)=>saved.set(k,v)},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},
 fetch:async()=>({status:401})};
vm.createContext(context);vm.runInContext(script,context);
vm.runInContext("catalog={quagsire:{name:'Quagsire',name_ja:'ヌオー'},corsola:{name:'Corsola',name_ja:'サニーゴ'},corsola_galarian:{name:'Corsola (Galarian)',name_ja:'ガラルサニーゴ'}}",context);
assert.equal(vm.runInContext("speciesSelectionMode('corsola')",context),'simple');
assert.equal(vm.runInContext("setSpeciesSelectionMode('corsola',true)",context),true);
assert.equal(vm.runInContext("speciesSelectionMode('corsola_galarian')",context),'simple');
assert.equal(JSON.parse(saved.get('pvpoke-app-selection-modes-v1')).corsola,'detailed');
vm.runInContext("el('selectionSettingsOpen').onclick();el('selectionModeFilter').value='サニーゴ';el('selectionModeFilter').oninput()",context);
assert.equal(els.selectionModeRows.children.length,2);
const jobs=['quagsire','corsola'].map(species=>({name:species,candidate:{species,fast:'F',charged1:'C1',charged2:'C2'},ivs:'0,15,15'}));
context.jobs=jobs;vm.runInContext('jobs=freezeSelectionModes(jobs)',context);
assert.deepEqual(Array.from(context.jobs,j=>j.batch_mode),['simple','detailed']);
vm.runInContext("setSpeciesSelectionMode('corsola',false)",context);
assert.equal(context.jobs[1].batch_mode,'detailed','frozen jobs survive later preference edits');
assert.equal(JSON.parse(saved.get('pvpoke-app-selection-modes-v1')).corsola,undefined);
// Execute the mixed queue and prove the actual HTTP requests use each frozen job mode.
context.fetch=async(path,options)=>{const data=JSON.parse(options.body);calls.push({path,data});return {ok:true,json:async()=>({state:'done',complete:true,selection:{recommendations:[],review_candidates:[],dominated_by:{},additional_candidates:[]},candidate:data.candidate,batch_mode:data.batch_mode})};};
vm.runInContext("renderBatchResults=()=>{};batchState={jobs,index:0,results:[],run_ref:null,batch_mode:'simple',focus:[],report_format:'app',policy:{}}",context);
(async()=>{
 await vm.runInContext('executeBatch()',context);
 assert.deepEqual(calls.map(x=>x.data.batch_mode),['simple','detailed']);
 // Legacy pending calculations retain their explicitly selected mode on resume.
 calls.length=0;context.legacy={...jobs[0]};delete context.legacy.batch_mode;
 vm.runInContext("batchState={jobs:[legacy],index:0,results:[],run_ref:null,batch_mode:'detailed',focus:[],report_format:'app',policy:{}}",context);
 await vm.runInContext('executeBatch()',context);assert.equal(calls[0].data.batch_mode,'detailed');
 saved.set('pvpoke-app-selection-modes-v1','{"corsola":"simple","quagsire":"bad","__proto__":"detailed"}');
 assert.equal(Object.keys(vm.runInContext('readSelectionModes()',context)).length,0);
 saved.set('pvpoke-app-selection-modes-v1','not-json');assert.equal(Object.keys(vm.runInContext('readSelectionModes()',context)).length,0);
 assert(source.includes('role="dialog"'));assert(source.includes('ポケモンごとの厳選設定'));
 console.log('Species mode defaults, forms, persistence, settings UI, frozen mixed HTTP queue and legacy resume: PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
