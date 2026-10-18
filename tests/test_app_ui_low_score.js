// Low-score UI regression checks. Run: node tests/test_app_ui_low_score.js
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
const els={},clipboard=[],requests=[];
function element(){
 const e={textContent:'',value:'',checked:false,hidden:false,disabled:false,children:[],
  append(c){this.children.push(c)},replaceChildren(){this.children=[]},
  scrollIntoView(){}};
 Object.defineProperty(e,'id',{set(v){els[v]=e}});
 return e;
}
const navigator={clipboard:{async writeText(t){clipboard.push(t)}}};
const fake={
 source_date:'2026-10-15',overall_under_threshold:431,selected_count:211,
 searchable_count:210,manual_review_count:1,preserved_by_other_roles:220,
 queries:[{index:1,query:'アギルダー,マケンカニ&!shadow&cp-1500&!favorite',species_count:2}],
 manual_review:[{name:'デオキシス (スピード)',overall:44,reason:'姿を区別できません'}],
};
const ctx={document:{getElementById(id){return els[id]??=element()},createElement:element},
 navigator,location:{hash:'',search:'?tool=low-score'},
 URLSearchParams,fetch:async(path,opts)=>{
  if(path==='/app-api/low-score'){
   requests.push(JSON.parse(opts.body));
   return {ok:true,status:200,json:async()=>fake};
  }
  return {ok:false,status:401,json:async()=>({error:'not authenticated'})};
 }};
vm.createContext(ctx);vm.runInContext(script,ctx);
(async()=>{
 for(const id of ['lowMode','lowThreshold','lowExcludeFavorites','lowScorePanel','lowSendAndroid','lowCopyQueue'])ctx.document.getElementById(id);
 els.lowMode.value='practical';els.lowThreshold.value='70';els.lowExcludeFavorites.checked=true;
 await vm.runInContext('loadLowScores()',ctx);
 assert.equal(requests.length,1);
 assert.equal(requests[0].threshold,70);
 assert.equal(requests[0].exclude_favorites,true);
 assert(els.lowScoreSummary.textContent.includes('211件'));
 assert(els.lowScoreSummary.textContent.includes('2026-10-15'));
 const card=els.lowScoreQueries.children[0];
 assert.equal(card.children[1].textContent,fake.queries[0].query);
 await card.children[2].onclick();
 assert.equal(clipboard[0],fake.queries[0].query);
 assert.equal(els.lowManual.hidden,false);
 assert(els.lowManualNames.textContent.includes('デオキシス'));
 assert(els.lowSearchRun.disabled===false);
 assert.equal(els.lowSendAndroid.disabled,false);
 const payload=JSON.parse(vm.runInContext('scoreQueuePayload()',ctx));
 assert.equal(payload.format,'pokemoniv-search-queue-v1');
 assert.equal(payload.items.length,1);
 assert.equal(payload.items[0].search,fake.queries[0].query);
 assert(!JSON.stringify(payload).includes('nickname'),'Cleanup searches must never introduce a nickname');
 await els.lowCopyQueue.onclick();
 assert.equal(JSON.parse(clipboard.at(-1)).format,'pokemoniv-search-queue-v1');
 await els.lowSendAndroid.onclick();
 assert.equal(JSON.parse(clipboard.at(-1)).format,'pokemoniv-search-queue-v1');
 console.log('Low-score reader deep link UI, search-only overlay payload and copying: PASS');
})().catch(err=>{console.error(err);process.exitCode=1});
