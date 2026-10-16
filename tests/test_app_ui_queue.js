const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
function element(){const e={children:[],value:'',textContent:'',disabled:false,hidden:false,append(x){this.children.push(x);},replaceChildren(){this.children=[];}};Object.defineProperty(e,'id',{set(v){els[v]=e;}});return e;}
const els={},storage=new Map(),calls=[],copied=[];
const job=(species,name,ivs)=>({candidate:{species,fast:'FAST',charged1:'CHARGE1',charged2:'CHARGE2'},name,ivs,candidate_count:1,warnings:[]});
const jobs=[job('swadloon','クルマユ','1,2,3'),job('leavanny','ハハコモリ','1,2,3')];
const result=j=>({state:'done',complete:true,meta_sha256:'a'.repeat(64),candidate:j.candidate,batch_mode:'simple',selection:{english_name:j.name,recommendations:[{ivs:'1/2/3',rank:1,grade:'A候補',role:'対応型',reason:'測定済み',search_string:j.candidate.species+'&1attack&1defense&1hp',equivalent_candidates:[],evidence_count:1,evidence:[{opponent:'Other',mode:'default',shield:'s1',rating:510,next_best:490}]}],unmatched_focus:[],review_candidates:[],dominated_by:{},excluded:0}});
const context={document:{getElementById(id){return els[id]??=element();},createElement:element},navigator:{clipboard:{async writeText(t){copied.push(t);}}},URLSearchParams,location:{hash:''},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},fetch:async(path,options)=>{if(path==='/app-api/catalog')return {ok:false,status:401,json:async()=>({error:'not logged in'})};const data=JSON.parse(options.body);calls.push({path,data});const index=calls.filter(c=>c.path.endsWith('/run')).length-1;return {ok:true,json:async()=>path.endsWith('/run')?{state:'running',run_ref:'ref-'+index}:result(jobs[index])};}};
vm.createContext(context);vm.runInContext(script,context);context.jobs=jobs;
vm.runInContext("catalog={swadloon:{name:'Swadloon',name_ja:'クルマユ',nickname_code:'Swd'},leavanny:{name:'Leavanny',name_ja:'ハハコモリ',nickname_code:'Lea'},other:{name:'Other',name_ja:'相手',nickname_code:'Oth'}};prepareLabels();batchState={jobs,index:0,results:[],run_ref:null,batch_mode:'simple',focus:[],report_format:'app',policy:{meaningful_win_lead:20}};setImportedJobs(jobs)",context);
(async()=>{
 await vm.runInContext('executeBatch()',context);
 assert.deepEqual(calls.map(c=>c.path),['/app-api/run','/app-api/result','/app-api/run','/app-api/result']);
 assert.deepEqual(calls.filter(c=>c.path.endsWith('/run')).map(c=>c.data.candidate.species),['swadloon','leavanny']);
 assert.equal(calls[2].data.expected_meta_sha256,'a'.repeat(64));
 function flat(x){return [x,...x.children.flatMap(flat)];}let nodes=flat(els.results);assert(nodes.some(x=>x.textContent==='クルマユ'));assert(nodes.some(x=>x.textContent==='ハハコモリ'));
 assert.equal(nodes.filter(x=>x.textContent==='検索式とニックネームをすべてコピー').length,2);
 assert(!nodes.some(x=>/重要個体値（コピペ用）|この個体値をコピー/.test(x.textContent)));
 assert.equal(els.allCopyActions.hidden,false);
 for(const b of nodes.filter(x=>x.textContent==='検索式とニックネームをすべてコピー'))await b.onclick();
 assert.equal(copied[0],'swadloon&1attack&1defense&1hp\nASwd>Oth11');assert.equal(copied[1],'leavanny&1attack&1defense&1hp\nALea>Oth11');
 assert.equal(nodes.filter(x=>x.textContent==='検索式をコピー').length,2);
 await els.allCopyActions.children[0].onclick();assert.equal(copied[2],copied[0]+'\n'+copied[1]);
 for(const b of nodes.filter(x=>x.textContent==='ニックネームをコピー'))await b.onclick();
 assert.deepEqual(copied.slice(3),['ASwd>Oth11','ALea>Oth11']);
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

 // Two names in one imported section share the same exact physical IV.
 // Preserve both stages while using the winning matchup with the highest Rating.
 vm.runInContext("catalog.naclstack={name:'Naclstack',name_ja:'ジオヅム',nickname_code:'Nal'};"+
  "catalog.garganacl={name:'Garganacl',name_ja:'キョジオーン',nickname_code:'Gag'};"+
  "catalog.winner={name:'Winner',name_ja:'高レート対面',nickname_code:'Win'};prepareLabels()",context);
 const staged=(sid,ivs,rating,op,shield,section,grade='A候補')=>({
  state:'done',complete:true,candidate:{species:sid,fast:'FAST',charged1:'C1',charged2:'C2'},
  source_sections:[section],selection:{english_name:sid,unmatched_focus:[],excluded:0,
  review_candidates:[],dominated_by:{},
  recommendations:[{ivs,search_string:sid+'&1attack&1defense&1hp',rank:1,grade,
    role:'対応',equivalent_candidates:[],evidence_count:1,
    evidence:[{opponent:op,mode:'default',shield,rating,next_best:490}]}]}})
 context.stageA=staged('naclstack','1/2/3',540,'Other','s1',99);
 context.stageB=staged('garganacl','1/2/3',680,'Winner','s2',99,'S候補');
 vm.runInContext('render(stageA)',context);
 assert(!/anal/i.test(vm.runInContext('nicknameFor(stageA,stageA.selection.recommendations[0]).text',context)));
 vm.runInContext('render(stageB,true)',context);
 const bothA=vm.runInContext('nicknameFor(stageA,stageA.selection.recommendations[0])',context);
 const bothB=vm.runInContext('nicknameFor(stageB,stageB.selection.recommendations[0])',context);
 assert.equal(bothA.text,bothB.text,'One physical IV must have one shared nickname');
 assert(bothA.text.endsWith('>Win22'),'Use the higher actual winning Rating (680)');
 assert(bothA.text.length<=12&&!/anal|ass|sex|fuck/i.test(bothA.text));
 assert(bothA.description.includes('ジオヅム')&&bothA.description.includes('キョジオーン'));
 assert(bothA.description.includes('680'));
 let buttons=flat(els.results).filter(x=>x.textContent==='ニックネームをコピー');
 assert.equal(buttons.length,2);
 await buttons[0].onclick();await buttons[1].onclick();
 assert.deepEqual(copied.slice(-2),[bothA.text,bothA.text],'Existing buttons must refresh when next stage finishes');
 const joined=vm.runInContext('displayedResults.map(recommendationExport).join("\\n")',context);
 assert.equal((joined.match(new RegExp(bothA.text,'g'))||[]).length,2,'All-copy uses the same resolved nickname');
 context.stageC=staged('garganacl','1/2/4',900,'Winner','s2',99,'S候補');
 vm.runInContext('render(stageC,true)',context);
 const still=vm.runInContext('nicknameFor(stageA,stageA.selection.recommendations[0])',context);
 assert.equal(still.text,bothA.text,'Different exact IVs must never be merged');
 assert.equal(vm.runInContext("validNickname('ANal>Oth11')",context),false);
 console.log('Safe nicknames, shared stages, strongest Rating, precise IV and refreshed copies: OK');

})();
