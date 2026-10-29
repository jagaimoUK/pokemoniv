const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('pvpoke_app_ui.py','utf8'),script=html.split('<script>')[1].split('</script>')[0];
const els={};function element(){return {value:'',hidden:false,children:[],append(x){this.children.push(x)},replaceChildren(){this.children=[]}};}
const ctx={URLSearchParams,location:{hash:''},document:{getElementById:id=>els[id]??=element(),createElement:element},sessionStorage:{getItem:()=>null},fetch:async()=>({status:401})};
vm.createContext(ctx);vm.runInContext(script,ctx);
vm.runInContext("catalog={ursaluna_shadow:{name:'Ursaluna (Shadow)',name_ja:'ガチグマ (シャドウ)',nickname_code:'Ursa',fastMoves:['SCRATCH','TACKLE','SCRATCH'],chargedMoves:['THUNDER_PUNCH','ICE_PUNCH','SWIFT','HIGH_HORSEPOWER']}}",ctx);
const base={candidate:{species:'ursaluna_shadow',fast:'SCRATCH',charged1:'THUNDER_PUNCH',charged2:'HIGH_HORSEPOWER'},ivs:'0,15,15\n1,15,15',name:'ガチグマs',source_sections:[7],source_records:[{ivs:'0/15/15',cp:500,species:'teddiursa',search_string:'Teddiursa&0attack&4defense&4hp&cp500&shadow'}]};
ctx.base=base;
const plan=vm.runInContext('planMovesets([base])',ctx);
assert.equal(plan.length,12,'2 fast × C(4 charged,2), without duplicates');
assert.equal(new Set(plan.map(j=>[j.candidate.fast,j.candidate.charged1,j.candidate.charged2].join('|'))).size,12);
assert(plan.some(j=>j.candidate.fast==='SCRATCH'&&[j.candidate.charged1,j.candidate.charged2].includes('SWIFT')&&[j.candidate.charged1,j.candidate.charged2].includes('ICE_PUNCH')));
assert.equal(plan[0].candidate.charged1,'HIGH_HORSEPOWER','Default ordering is canonical charged order');
assert(plan.every(j=>j.source_records===base.source_records&&j.ivs===base.ivs&&j.moveset_group===0));
function result(charged2,mean,wins,ivMeans={"0/15/15":mean,"1/15/15":mean},ivs=['0/15/15']){
 const candidate={...base.candidate,charged2};
 return {...base,candidate,complete:true,calculation_version:'e'.repeat(64),meta_sha256:'f'.repeat(64),selection:{
  candidate_ivs:['0/15/15','1/15/15'],unmatched_focus:[],review_candidates:[],
  moveset_summary:{version:1,axis_sha256:'a'.repeat(64),available_wins:wins,mean_rating:mean,iv_mean_ratings:ivMeans,rating_count:24},
  recommendations:ivs.map((iv,i)=>({ivs:iv,rank:i+1,grade:'Sランク',search_string:'Ursaluna&0attack&4defense&4hp&shadow',role:'推薦',evidence:[],equivalent_candidates:[]}))}};
}
const defaultLow=result('HIGH_HORSEPOWER',420,'100'),swift=result('SWIFT',530,'110'),ice=result('ICE_PUNCH',490,'001');
ctx.profiles=[defaultLow,swift,ice];
const combined=vm.runInContext('combineMovesets(profiles,450)',ctx);
assert.deepEqual(Array.from(combined.moveset_comparison.profiles,p=>p.retained),[false,true,true],'Do not assume default is strong');
assert.equal(combined.selection.recommendations.length,1,'One physical IV copied once');
assert.equal(combined.selection.recommendations[0].chosen_moves.charged2,'SWIFT');
assert.equal(combined.selection.total_ratings_checked,72);
ctx.combined=combined;
const nick=vm.runInContext('nicknameFor(combined,combined.selection.recommendations[0])',ctx);
assert(nick.text.endsWith('ScTPSw')&&nick.text.length<=12,nick.text);
assert(nick.description.includes('THUNDER_PUNCH')&&nick.description.includes('SWIFT'));
ctx.low=[result('HIGH_HORSEPOWER',400,'100'),result('SWIFT',390,'010')];
assert(vm.runInContext('combineMovesets(low,450).moveset_comparison.profiles.every(p=>p.retained)',ctx),'Keep a unique actual win even below threshold');
ctx.low=[result('HIGH_HORSEPOWER',400,'000'),result('SWIFT',390,'000')];
assert.deepEqual(Array.from(vm.runInContext('combineMovesets(low,450).moveset_comparison.profiles.map(p=>p.retained)',ctx)),[true,false],'Keep best as explicit fallback');
ctx.profiles[1].selection.moveset_summary.axis_sha256='different';
assert.throws(()=>vm.runInContext('combineMovesets(profiles,450)',ctx),/比較条件/);
// Equivalent IVs in one build may differ in another. Pick each physical IV separately.
const p=result('SWIFT',510,'10',{'0/15/15':500,'1/15/15':520});
p.selection.recommendations[0].equivalent_candidates=[{ivs:'1/15/15',search_string:'Ursaluna&1attack&4defense&4hp&shadow'}];
ctx.equivs=[p,result('ICE_PUNCH',515,'11',{'0/15/15':530,'1/15/15':500},['0/15/15','1/15/15'])];
const individual=vm.runInContext('combineMovesets(equivs,450).selection.recommendations',ctx);
assert.equal(individual.length,2);
assert.equal(individual.find(r=>r.ivs==='0/15/15').chosen_moves.charged2,'ICE_PUNCH');
assert.equal(individual.find(r=>r.ivs==='1/15/15').chosen_moves.charged2,'SWIFT');
assert(html.indexOf('id="moveSettings"')<html.indexOf('自動推薦の基準を調整'));
assert(html.indexOf('1. ポケモンと個体値')>html.indexOf('id="metaManager"'));
assert(!html.includes('合法な通常技'));
assert(html.indexOf('<label for="fast">')>html.indexOf('id="moveSettings"'));
console.log('Exhaustive legal profiles, actual Rating selection, unique wins, safe move nicknames and per-IV adoption: OK');
(async()=>{
 const jobs=plan.slice(0,2),old=result('SWIFT',510,'10');
 ctx.queued=jobs;ctx.old=old;
 const calls=[];let inFlight=0,maxInFlight=0;
 ctx.fetch=async(path,opts)=>{
  const data=JSON.parse(opts.body);calls.push({path,data});inFlight++;maxInFlight=Math.max(maxInFlight,inFlight);
  await new Promise(r=>setImmediate(r));inFlight--;
  const out=result(data.candidate.charged2,500+calls.length,'10');out.candidate=data.candidate;out.state='done';out.run_ref='auto'+calls.length;
  return {ok:true,json:async()=>out};
 };
 ctx.sessionStorage={setItem(){},removeItem(){},getItem(){return null}};
 vm.runInContext("batchState={jobs:queued,auto_moves:true,move_threshold:450,index:0,results:[],batch_mode:'simple',focus:[],report_format:'app',policy:{},meta_sha256:'f'.repeat(64),force_recalculate:true}",ctx);
 await ctx.executeBatch();
 assert.equal(maxInFlight,1);assert.equal(calls.length,2);assert(calls.every(c=>c.data.force_recalculate&&c.data.expected_meta_sha256==='f'.repeat(64)));
 assert.equal(vm.runInContext('displayedResults.length',ctx),1,'Group all completed profiles into one species result');
 assert.equal(vm.runInContext('displayedResults[0].moveset_comparison.profiles.length',ctx),2);
 // A resumed group cannot mix pre-update and post-update engine data.
 ctx.fetch=async(path,opts)=>{const out=result('SWIFT',520,'10');out.state='done';out.calculation_version='d'.repeat(64);return {ok:true,json:async()=>out}};
 vm.runInContext("batchState={jobs:queued,auto_moves:true,move_threshold:450,index:1,results:[old],calculation_version:'e'.repeat(64),batch_mode:'simple',focus:[],policy:{},report_format:'app'}",ctx);
 await assert.rejects(ctx.executeBatch(),/更新されました/);
 assert.equal(vm.runInContext('batchState.results.length',ctx),1);
 assert.equal(vm.runInContext('batchState.index',ctx),1);
 console.log('Sequential exhaustive queue, frozen reuse/meta flags, combined results and update-safe resume: OK');
})();
