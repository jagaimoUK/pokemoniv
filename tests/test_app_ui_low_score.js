// Dedicated low-score page is for exclusion diagnostics, not manual copy.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('pvpoke_app_ui.py','utf8');
const script=html.split('<script>')[1].split('</script>')[0];
assert(html.includes('Show Evolutionary Line')&&html.includes('OFF推奨'));
for(const id of ['lowSendAndroid','lowCopyQueue','lowSingleCard','lowDetailedPanel']){
 assert(!html.includes('id="'+id+'"'),id+' should not be present');
}
const els={},requests=[];
function element(){
 const e={textContent:'',value:'',checked:false,hidden:false,disabled:false,children:[],
   append(x){this.children.push(x)},replaceChildren(){this.children=[]},scrollIntoView(){}};
 Object.defineProperty(e,'id',{set(v){els[v]=e}});return e;
}
const fake={
 source_date:'2026-10-15',selected_count:211,searchable_count:208,manual_review_count:1,
 evolution_protected_count:2,unranked_review_count:1,
 unranked_review:[{name:'Gothita',dex:574,evolves_to:['ゴチミル','ゴチルゼル'],reason:'ランキング未掲載。進化先は低スコアなので要確認'}],
 queries:[{query:'Gothorita&!shadow&cp-1500&!favorite'}],
 evolution_protected:[{name:'シュシュプ',evolves_to:['フレフワン'],reason:'進化先の評価で保護'}],
 manual_review:[{name:'デオキシス (スピード)',overall:44,reason:'姿を区別できません'}],
 exclusion_reasons:{specialist_preserved:220,evolution_protected:2,
 form_or_name_unsearchable:1,unranked_not_verified:87,unranked_manual_review:1}
};
const ctx={
 document:{getElementById(k){return els[k]??=element()},createElement:element},
 navigator:{clipboard:{async writeText(){throw Error('No raw search copy expected')}}},
 location:{hash:'',search:'?tool=low-score'},URLSearchParams,
 fetch:async(path,opts)=>{
  if(path!=='/app-api/low-score')return {ok:false,status:401,json:async()=>({error:'not authenticated'})};
  requests.push(JSON.parse(opts.body));return {ok:true,status:200,json:async()=>fake};
 }
};
vm.createContext(ctx);vm.runInContext(script,ctx);
(async()=>{
 for(const id of ['lowMode','lowThreshold','lowExcludeFavorites','lowScorePanel',
 'lowScoreSummary','lowExclusionSummary','lowUnrankedReview','lowUnrankedNames'])ctx.document.getElementById(id);
 els.lowMode.value='practical';els.lowThreshold.value='70';els.lowExcludeFavorites.checked=true;
 await vm.runInContext('loadLowScores()',ctx);
 assert.equal(requests.length,1);assert.equal(requests[0].threshold,70);
 assert.equal(requests[0].exclude_favorites,true);
 assert(els.lowScoreSummary.textContent.includes('211件'));
 assert(els.lowScoreSummary.textContent.includes('未掲載・要確認 1種類'));
 assert(els.lowExclusionSummary.textContent.includes('220件'));
 assert(els.lowExclusionSummary.textContent.includes('87種類'));
 assert.equal(els.lowUnrankedReview.hidden,false);
 assert(els.lowUnrankedNames.textContent.includes('Gothita'));
 assert(els.lowUnrankedNames.textContent.includes('ランキング未掲載'));
 assert.equal(els.lowEvolutionProtected.hidden,false);
 assert(els.lowEvolutionNames.textContent.includes('進化先の評価'));
 assert.equal(els.lowManual.hidden,false);
 assert(els.lowManualNames.textContent.includes('デオキシス'));
 els.lowExcludeFavorites.checked=false;
 await els.lowExcludeFavorites.onchange();
 assert.equal(requests.at(-1).exclude_favorites,false);
 console.log('Low-score diagnostics without obsolete one-query handoff: PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
