// Low-score UI regression checks. Run: node tests/test_app_ui_low_score.js
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
assert(fs.readFileSync('pvpoke_app_ui.py','utf8').includes('Show Evolutionary Line（進化系統を表示）」をオフ'), 'UI must warn to turn Evolutionary Line OFF');
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
 searchable_count:208,manual_review_count:1,preserved_by_other_roles:220,
 evolution_protected_count:2,evolution_high_cp_count:1,
 evolution_protected:[{name:'シュシュプ',evolves_to:['フレフワン']},{name:'ヒトツキ',evolves_to:['ニダンギル','ギルガルド']}],
 evolution_high_cp_exceptions:[{name:'メノクラゲ',minimum_cp:1333}],
 quick_query:'244,682&cp-1500&!favorite',
 quick_species_count:2,quick_covered_rows:3,quick_omitted_rows:208,
 queries:[{index:1,query:'Accelgor,Crabominable&!shadow&cp-1500&!favorite',species_count:2}],
 manual_review:[{name:'デオキシス (スピード)',overall:44,reason:'姿を区別できません'}],
};
const ctx={document:{getElementById(id){return els[id]??=element()},createElement:element},
 navigator,location:{hash:'',search:'?tool=low-score'},
 URLSearchParams,fetch:async(path,opts)=>{
  if(path==='/app-api/low-score'){
   requests.push(JSON.parse(opts.body));
   const {exclude_favorites}=JSON.parse(opts.body);
   return {ok:true,status:200,json:async()=>({...fake,
    quick_query:exclude_favorites?fake.quick_query:'244,682&cp-1500',
    excluded_favorites:exclude_favorites})};
  }
  return {ok:false,status:401,json:async()=>({error:'not authenticated'})};
 }};
vm.createContext(ctx);vm.runInContext(script,ctx);
(async()=>{
 for(const id of ['lowMode','lowThreshold','lowExcludeFavorites','lowScorePanel','lowSendAndroid','lowCopyQueue','lowEvolutionProtected','lowEvolutionNames'])ctx.document.getElementById(id);
 els.lowMode.value='practical';els.lowThreshold.value='70';els.lowExcludeFavorites.checked=true;
 await vm.runInContext('loadLowScores()',ctx);
 assert.equal(requests.length,1);
 assert.equal(requests[0].threshold,70);
 assert.equal(requests[0].exclude_favorites,true);
 assert(els.lowScoreSummary.textContent.includes('211件'));
 assert(els.lowScoreSummary.textContent.includes('2026-10-15'));
 assert.equal(els.lowSingleCard.hidden,false);
 assert.equal(els.lowSingleQuery.textContent,'244,682&cp-1500&!favorite');
 assert(els.lowSingleStatus.textContent.includes('除外 ON'));
 assert(els.lowScoreSummary.textContent.includes('進化先の評価で 2件'));
 assert(els.lowEvolutionProtected.hidden===false);
 assert(els.lowEvolutionNames.textContent.includes('シュシュプ'));
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
 assert.equal(payload.items[0].search,'244,682&cp-1500&!favorite');
 assert(!JSON.stringify(payload).includes('nickname'),'Cleanup searches must never introduce a nickname');
 await els.lowCopyQueue.onclick();
 assert.equal(JSON.parse(clipboard.at(-1)).format,'pokemoniv-search-queue-v1');
 await els.lowSendAndroid.onclick();
 assert.equal(JSON.parse(clipboard.at(-1)).format,'pokemoniv-search-queue-v1');
 els.lowExcludeFavorites.checked=false;
 await els.lowExcludeFavorites.onchange();
 assert.equal(requests.at(-1).exclude_favorites,false);
 assert.equal(els.lowSingleQuery.textContent,'244,682&cp-1500');
 assert(els.lowSingleStatus.textContent.includes('除外 OFF'));
 assert.equal(JSON.parse(vm.runInContext('scoreQueuePayload()',ctx)).items[0].search,
              '244,682&cp-1500');
 console.log('Single low-score search, favorites toggle, detailed fallback and Android overlay: PASS');
})().catch(err=>{console.error(err);process.exitCode=1});
