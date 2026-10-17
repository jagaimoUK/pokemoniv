// Android Web Share bridge contract. Run: node tests/test_app_ui_share.js
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
const elements={},copied=[],shared=[];
function node(){const e={children:[],textContent:'',hidden:false,value:'',disabled:false,append(v){this.children.push(v)},replaceChildren(){this.children=[]}};Object.defineProperty(e,'id',{set(v){elements[v]=e}});return e;}
const navigator={clipboard:{async writeText(value){copied.push(value)}},async share(payload){shared.push(payload)}};
const context={document:{getElementById(k){return elements[k]??=node()},createElement:node},navigator,URLSearchParams,location:{hash:''}};
vm.createContext(context);vm.runInContext(script,context);
vm.runInContext("catalog={quagsire:{name:'Quagsire',name_ja:'ヌオー',nickname_code:'Quag'},corviknight:{name:'Corviknight',name_ja:'アーマーガア',nickname_code:'Cor'}};prepareLabels()",context);
const row=(ivs,search)=>({ivs,rank:1,grade:'A候補',role:'対応型',search_string:search,evidence:[{opponent:'Corviknight',rating:515,mode:'default',shield:'i0y1',next_best:480}],equivalent_candidates:[]});
const result=(rows)=>({candidate:{species:'quagsire',fast:'MUD_SHOT',charged1:'AQUA_TAIL',charged2:'STONE_EDGE'},selection:{recommendations:rows,unmatched_focus:[],excluded:0,dominated_by:{},review_candidates:[]}});
const first=result([row('0/11/12','Quagsire&0attack&3defense&3hp'),row('1/11/12','Quagsire&1attack&3defense&3hp')]);
const second=result([row('0/11/12','Quagsire&0attack&3defense&3hp')]);
function flatten(e){return [e,...e.children.flatMap(flatten)];}
(async()=>{
 context.first=first; context.second=second;
 vm.runInContext('render(first);render(second,true)',context);
 const buttons=flatten(elements.results).filter(e=>e.textContent==='Androidへ送る');
 assert.equal(buttons.length,3, 'Two single-result buttons and one all-results button are present');
 await buttons[1].onclick();
 assert.equal(shared.length,1);
 const expected='Quagsire&0attack&3defense&3hp\nAQuag>Cor01\nQuagsire&1attack&3defense&3hp\nAQuag>Cor01';
 const payload=JSON.parse(shared[0].text);assert.equal(payload.format,'pokemoniv-overlay-v2');assert.equal(payload.items.length,2);assert.equal(payload.items[0].ivs,'0/11/12');assert.equal(payload.items.map(x=>x.search+'\n'+x.nickname).join('\n'),expected);
 assert.equal(shared[0].title,'厳選コピーリスト');
 assert.equal(copied.length,0);
 await elements.allCopyActions.children.find(x=>x.textContent==='Androidへ送る').onclick();
 assert.equal(shared.length,2);
 assert.equal(JSON.parse(shared[1].text).items.map(x=>x.search+'\n'+x.nickname).join('\n'),expected+'\nQuagsire&0attack&3defense&3hp\nAQuag>Cor01');
 assert.equal(JSON.parse(shared[1].text).items.length,3);
 navigator.share=undefined;
 await buttons[1].onclick();
 assert.equal(copied.at(-1),shared[0].text,'Fallback preserves exact IV metadata');await vm.runInContext('copyRecommendations([first],{})',context);assert.equal(copied.at(-1),expected,'Legacy two-line copy is preserved');
 navigator.share=async()=>{let e=Error('user cancelled');e.name='AbortError';throw e};
 const beforeCount=copied.length;
 await buttons[1].onclick();
 assert.equal(copied.length,beforeCount,'Cancel must not silently replace clipboard');
 navigator.share=async()=>{throw Error('blocked')};
 await buttons[1].onclick();
 assert(elements.message.textContent.includes('共有を開始できません'));
 const bad=result([{...row('0/11/12',null)}]);
 context.bad=bad;
 await vm.runInContext('shareRecommendations([bad],{})',context);
 assert.equal(shared.length,2,'Invalid search must never be shared');
 assert(elements.message.textContent.includes('検索式'));
 first.source_records=[{ivs:'0/11/12',cp:717,species:'wooper',search_string:'Wooper&0attack&3defense&3hp&cp717'},{ivs:'0/11/12',cp:625,species:'wooper',search_string:'Wooper&0attack&3defense&3hp&cp625'}];const cp=JSON.parse(vm.runInContext('overlayExport([first])',context));assert.equal(cp.items.length,3);assert.equal(cp.items[0].cp,717);assert(cp.items[0].search.startsWith('Wooper&'));assert.equal(cp.items[1].cp,625);assert.equal(cp.items[2].cp,null);assert(vm.runInContext('recommendationExport(first)',context).includes('&cp717'));
 const oldRegional=result([row('13/8/11','Wooper (Paldean)&3attack&2defense&3hp')]);
 oldRegional.source_records=[{ivs:'13/8/11',cp:458,species:'wooper_paldean',search_string:'Wooper (Paldean)&3attack&2defense&3hp&cp458'}];
 const migrated=JSON.parse(vm.runInContext('overlayExport([oldRegional])',Object.assign(context,{oldRegional})));
 assert.equal(migrated.items[0].search,'Wooper&paldea&3attack&2defense&3hp&cp458');
 assert(vm.runInContext('recommendationExport(oldRegional)',context).startsWith('Wooper&paldea&3attack&2defense&3hp&cp458'));
 for(const [name,region] of [['Raichu (Alolan)','alola'],['Zigzagoon (Galarian)','galar'],['Growlithe (Hisuian)','hisui']]){
  const fixed=vm.runInContext('normalizedRegionalSearch('+JSON.stringify(name+'&1attack')+')',context);
  assert.equal(fixed,name.split(' (')[0]+'&'+region+'&1attack');
 }
 console.log('Android Web Share: exact pairs, multi-result, duplicate, fallback, cancel, error: PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
