const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
const els={},storage=new Map(),calls=[];
const element=()=>({value:'',children:[],hidden:false,disabled:false,textContent:'',append(x){this.children.push(x)},replaceChildren(){this.children=[]},setAttribute(){},scrollIntoView(){},focus(){}});
const ctx={document:{getElementById:id=>els[id]??=element(),createElement:element},URLSearchParams,location:{hash:''},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},setTimeout:fn=>fn(),fetch:async()=>({status:401})};
vm.createContext(ctx);vm.runInContext(script,ctx);
(async()=>{
 let runTries=0,resultTries=0;
 ctx.fetch=async(path,opts)=>{const data=JSON.parse(opts.body);calls.push({path,data});
  if(path.endsWith('/run')){if(++runTries===1)throw TypeError('Failed to fetch');return {ok:true,json:async()=>({state:'running',run_ref:'same-job'})};}
  if(path.endsWith('/result')){if(++resultTries===1)return {status:502,ok:false,json:async()=>({error:'gateway'})};return {ok:true,json:async()=>({state:'done',complete:true,run_ref:'same-job'})};}
  return {status:401};
 };
 const first=await ctx.api('run',{candidate:{species:'nidoran_female'},ivs:'0,15,15'});
 assert.equal(first.run_ref,'same-job');assert.equal(calls[0].data.request_id,calls[1].data.request_id);
 const result=await ctx.api('result',{run_ref:'same-job',wait_seconds:2});assert(result.complete);assert.equal(resultTries,2);
 let saves=0;ctx.fetch=async()=>{saves++;throw TypeError('Failed to fetch')};
 await assert.rejects(ctx.api('meta-preset-save',{action:'update'}),/Failed to fetch/);assert.equal(saves,1,'mutations must not be blindly replayed');
 let unauthorized=0;ctx.fetch=async()=>{unauthorized++;return {status:401}};
 await assert.rejects(ctx.api('result',{run_ref:'same-job'}),/有効期限/);assert.equal(unauthorized,1);
 assert.equal(ctx.normalizedRegionalSearch('Nidoran♀&0attack&cp100'),'Nidoran&female&0attack&cp100');
 ctx.fetch=async()=>{throw TypeError('Failed to fetch')};
 vm.runInContext("batchState={jobs:[{name:'Nidoran',candidate:{species:'nidoran_female',fast:'FAST',charged1:'A',charged2:'B'},ivs:'0,15,15'}],index:0,results:[],report_format:'app',policy:{},batch_mode:'simple'}",ctx);
 await assert.rejects(ctx.executeBatch(),/Failed to fetch/);
 ctx.handleCalculationError(Error('Failed to fetch'));
 assert(vm.runInContext('!!batchState.start_request_id',ctx),'lost start replies retain the request identity for Resume');
 assert(storage.has('pvpoke-app-batch'));
 console.log('Transient run/result recovery, stable request IDs, mutation and auth boundaries: OK');
})().catch(e=>{console.error(e);process.exitCode=1});
