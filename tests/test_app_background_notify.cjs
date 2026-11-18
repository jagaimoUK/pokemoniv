const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
const elems={},local=new Map(),session=new Map(),requests=[],announcements=[];
const item=()=>({value:'',children:[],hidden:false,disabled:false,checked:false,
 textContent:'',append(x){this.children.push(x)},replaceChildren(){this.children=[]},
 setAttribute(){},scrollIntoView(){},focus(){}});
const storage=m=>({getItem:k=>m.get(k)||null,setItem:(k,v)=>m.set(k,v),
 removeItem:k=>m.delete(k)});
let permissionRequests=0;
const ctx={
 document:{hidden:false,getElementById:id=>elems[id]??=item(),createElement:item},
 URLSearchParams,location:{hash:'',search:''},localStorage:storage(local),
 sessionStorage:storage(session),setTimeout:fn=>fn(),clearTimeout(){},
 navigator:{serviceWorker:{register:async()=>({showNotification:async(...a)=>announcements.push(a)}),
 getRegistration:async()=>({showNotification:async(...a)=>announcements.push(a)})}},
 Notification:{permission:'granted',requestPermission:async()=>{permissionRequests++;return 'granted';}},
 SpeechSynthesisUtterance:function(message){this.text=message;},
 speechSynthesis:{speak:utterance=>announcements.push(['voice',utterance.text])},
 fetch:async()=>({status:401,ok:false,json:async()=>({error:'auth'})})
};
vm.createContext(ctx);vm.runInContext(script,ctx);
(async()=>{
 assert.equal(permissionRequests,0,'never request notification permission at page load');
 await elems.notifyEnable.onclick();
 assert.equal(permissionRequests,1,'permission requests must come from user action');
 elems.voiceNotify.checked=true;elems.voiceNotify.onchange();
 await ctx.notifyBatchDone('a'.repeat(32));
 await ctx.notifyBatchDone('a'.repeat(32));
 assert.equal(announcements.filter(a=>a[0]!=='voice').length,1,'notify once per batch');
 assert.equal(announcements.filter(a=>a[0]==='voice').length,1,'voice is opt-in and once');
 assert.equal(local.get('pvpoke-app-notify-voice-v1'),'true');

 let tries=0;
 ctx.fetch=async(url,opts)=>{
  const data=JSON.parse(opts.body);requests.push({url,data});
  if(url.endsWith('/batch-start')){
   if(++tries===1)throw TypeError('Failed to fetch');
   return {ok:true,json:async()=>({state:'running',batch_id:'b'.repeat(32)})};
  }
  if(url.endsWith('/batch-status')){
   return {ok:true,json:async()=>({batch_id:'b'.repeat(32),state:'paused',index:0,total:1,
    error:'計算エンジンが一時停止しました',...(data.include_results?{results:[]}: {})})};
  }
  throw Error('unexpected route '+url);
 };
 vm.runInContext("batchState={jobs:[{name:'ヌオー',candidate:{species:'quagsire',fast:'MUD_SHOT',charged1:'AQUA_TAIL',charged2:'STONE_EDGE'},ivs:'0,11,12'}],index:0,results:[],batch_mode:'simple',report_format:'app',policy:{meaningful_win_lead:20},meta_sha256:'"+'a'.repeat(64)+"'}",ctx);
 await assert.rejects(ctx.executeBatch(),/一時停止/);
 assert.equal(tries,2,'safe retried start after lost response');
 assert.equal(requests[0].data.request_id,requests[1].data.request_id);
 assert.equal(local.get('pvpoke-app-server-batch-v1'),'b'.repeat(32));
 ctx.handleCalculationError(Error('temporary connection error'));
 assert(vm.runInContext('!!batchState.batch_id',ctx),'network error must not clear server batch');
 console.log('Durable batch idempotent retry, paused recovery, permission and notification dedup: OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
