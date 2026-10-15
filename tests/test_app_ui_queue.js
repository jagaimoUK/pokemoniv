const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
function element(){return {children:[],value:'',textContent:'',disabled:false,hidden:false,append(x){this.children.push(x);},replaceChildren(){this.children=[];}};}
const els={},storage=new Map(),calls=[],copied=[];
const job=(species,name,ivs)=>({candidate:{species,fast:'FAST',charged1:'CHARGE1',charged2:'CHARGE2'},name,ivs,candidate_count:1,warnings:[]});
const jobs=[job('swadloon','クルマユ','1,2,3'),job('leavanny','ハハコモリ','1,2,3')];
const result=j=>({state:'done',complete:true,meta_sha256:'a'.repeat(64),candidate:j.candidate,batch_mode:'simple',selection:{english_name:j.name,recommendations:[{ivs:'1/2/3',rank:1,grade:'A候補',role:'対応型',reason:'測定済み',search_string:'Search',equivalent_candidates:[],evidence_count:1,evidence:[{opponent:'Other',mode:'default',shield:'s1',rating:510,next_best:490}]}],unmatched_focus:[],review_candidates:[],dominated_by:{},excluded:0}});
const context={document:{getElementById(id){return els[id]??=element();},createElement:element},navigator:{clipboard:{async writeText(t){copied.push(t);}}},URLSearchParams,location:{hash:''},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},fetch:async(path,options)=>{const data=JSON.parse(options.body);calls.push({path,data});const index=calls.filter(c=>c.path.endsWith('/run')).length-1;return {ok:true,json:async()=>path.endsWith('/run')?{state:'running',run_ref:'ref-'+index}:result(jobs[index])};}};
vm.createContext(context);vm.runInContext(script,context);context.jobs=jobs;
vm.runInContext("batchState={jobs,index:0,results:[],run_ref:null,batch_mode:'simple',focus:[],report_format:'app',policy:{meaningful_win_lead:20}};setImportedJobs(jobs)",context);
(async()=>{
 await vm.runInContext('executeBatch()',context);
 assert.deepEqual(calls.map(c=>c.path),['/app-api/run','/app-api/result','/app-api/run','/app-api/result']);
 assert.deepEqual(calls.filter(c=>c.path.endsWith('/run')).map(c=>c.data.candidate.species),['swadloon','leavanny']);
 assert.equal(calls[2].data.expected_meta_sha256,'a'.repeat(64));
 function flat(x){return [x,...x.children.flatMap(flat)];}let nodes=flat(els.results);assert(nodes.some(x=>x.textContent==='クルマユ'));assert(nodes.some(x=>x.textContent==='ハハコモリ'));
 assert.equal(nodes.filter(x=>x.textContent==='重要個体値をまとめてコピー').length,2);
 for(const b of nodes.filter(x=>x.textContent==='ポケモン・技も含めてコピー'))await b.onclick();
 assert(copied[0].includes('swadloon,FAST'));assert(copied[1].includes('leavanny,FAST'));
 assert(!storage.has('pvpoke-app-batch'));assert(els.resume.hidden);
 console.log('Sequential grouped execution, retained per-species results, frozen meta and copies: OK');
 // Resume after the first completed species; do not restart it.
 calls.length=0;context.saved=result(jobs[0]);context.saved.display_name='クルマユ';
 vm.runInContext("render(saved);batchState={jobs,index:1,results:[saved],run_ref:'resumed-ref',meta_sha256:'a'.repeat(64),batch_mode:'simple',focus:[],report_format:'app',policy:{}}",context);
 context.fetch=async(path,options)=>{calls.push({path,data:JSON.parse(options.body)});return {ok:true,json:async()=>result(jobs[1])};};
 await vm.runInContext('executeBatch()',context);
 assert.equal(calls.length,1);assert.equal(calls[0].path,'/app-api/result');assert.equal(calls[0].data.run_ref,'resumed-ref');
 console.log('Resume polls existing job without recalculating completed species: OK');
 // A failure on the second species must preserve the first result.
 let starts=0;context.fetch=async(path,options)=>{if(path.endsWith('/run')&&++starts===2)throw Error('test failure');return {ok:true,json:async()=>path.endsWith('/run')?{state:'running',run_ref:'once'}:result(jobs[0])};};
 vm.runInContext("batchState={jobs,index:0,results:[],run_ref:null,batch_mode:'simple',focus:[],report_format:'app',policy:{}}",context);
 await assert.rejects(vm.runInContext('executeBatch()',context),/test failure/);
 assert.equal(vm.runInContext('batchState.results.length',context),1);assert.equal(vm.runInContext('batchState.index',context),1);
 console.log('Partial failure keeps completed result and stops subsequent work: OK');
})();
