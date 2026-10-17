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
 assert.equal(buttons.length,2, 'Single result and all results sharing are both present');
 await buttons[0].onclick();
 assert.equal(shared.length,1);
 const expected='Quagsire&0attack&3defense&3hp\\nAQuag>Cor01\\nQuagsire&1attack&3defense&3hp\\nAQuag>Cor01';
 assert.equal(shared[0].text,expected);
 assert.equal(shared[0].title,'厳選コピーリスト');
 assert.equal(copied.length,0);
 await elements.allCopyActions.children[1].onclick();
 assert.equal(shared.length,2);
 assert.equal(shared[1].text,expected+'\\nQuagsire&0attack&3defense&3hp\\nAQuag>Cor01');
 assert.equal(shared[1].text.split('\\n').length,6);
 navigator.share=undefined;
 await buttons[0].onclick();
 assert.equal(copied.at(-1),expected,'Unsupported share must retain legacy copy fallback');
 navigator.share=async()=>{let e=Error('user cancelled');e.name='AbortError';throw e};
 const beforeCount=copied.length;
 await buttons[0].onclick();
 assert.equal(copied.length,beforeCount,'Cancel must not silently replace clipboard');
 navigator.share=async()=>{throw Error('blocked')};
 await buttons[0].onclick();
 assert(elements.message.textContent.includes('共有を開始できません'));
 const bad=result([{...row('0/11/12',null)}]);
 context.bad=bad;
 await vm.runInContext('shareRecommendations([bad],{})',context);
 assert.equal(shared.length,2,'Invalid search must never be shared');
 assert(elements.message.textContent.includes('検索式'));
 console.log('Android Web Share: exact pairs, multi-result, duplicate, fallback, cancel, error: PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
