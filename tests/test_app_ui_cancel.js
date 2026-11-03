const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('pvpoke_app_ui.py','utf8');
assert.match(html,/id="autoMoves" type="checkbox">/);
assert.match(html,/id="cancelRun".*hidden>/);
const script=html.split('<script>')[1].split('</script>')[0],els={};
const element=()=>({value:'',hidden:false,disabled:false,append(){},replaceChildren(){},scrollIntoView(){},focus(){}});
const ctx={URLSearchParams,location:{hash:''},document:{getElementById:id=>els[id]??=element(),createElement:element},sessionStorage:{setItem(){},removeItem(){},getItem(){return null}},fetch:async()=>({status:401})};
vm.createContext(ctx);vm.runInContext(script,ctx);
ctx.jobs=[{candidate:{species:'quagsire',fast:'MUD_SHOT',charged1:'AQUA_TAIL',charged2:'STONE_EDGE'},ivs:'0,11,12',name:'Quagsire',moveset_group:0}];
ctx.calls=[];
ctx.fetch=async(path,opts)=>{
 const data=JSON.parse(opts.body);ctx.calls.push({path,data});
 if(path.endsWith('/run')){vm.runInContext('stopRequested=true',ctx);return {ok:true,json:async()=>({run_ref:'job123',state:'running'})};}
 if(path.endsWith('/cancel'))return {ok:true,json:async()=>({state:'cancelling',cancelled:true,run_ref:'job123'})};
 if(path.endsWith('/result'))return {ok:true,json:async()=>({state:'cancelled',run_ref:'job123'})};
 throw Error(path);
};
vm.runInContext("batchState={jobs,auto_moves:false,index:0,results:[],batch_mode:'simple',focus:[],report_format:'app',policy:{},force_recalculate:false}",ctx);
(async()=>{
 await assert.rejects(ctx.executeBatch(),/計算を中止しました/);
 assert.equal(ctx.calls.filter(x=>x.path.endsWith('/run')).length,1);
 assert.equal(ctx.calls.filter(x=>x.path.endsWith('/cancel')).length,1);
 assert.equal(ctx.calls.find(x=>x.path.endsWith('/cancel')).data.run_ref,'job123');
 assert.equal(vm.runInContext('batchState.results.length',ctx),0);
 console.log('Default OFF and exact-run cancellation: OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
