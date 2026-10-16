const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
const els={};function element(){const e={children:[],value:'',textContent:'',hidden:false,append(x){this.children.push(x)},replaceChildren(){this.children=[]}};Object.defineProperty(e,'id',{set(v){els[v]=e}});return e;}
const context={document:{getElementById(id){return els[id]??=element()},createElement:element},navigator:{clipboard:{async writeText(t){context.copied=t}}},URLSearchParams,location:{hash:''}};
vm.createContext(context);vm.runInContext(script,context);
vm.runInContext(`catalog={quagsire:{name:'Quagsire',name_ja:'ヌオー',nickname_code:'Quag'},corviknight:{name:'Corviknight',name_ja:'アーマーガア',nickname_code:'Cor'},feraligatr_shadow:{name:'Feraligatr (Shadow)',name_ja:'オーダイル(シャドウ)',nickname_code:'Fers'}};prepareLabels()`,context);
const event=(opponent,rating,shield='i0y1')=>({opponent,rating,shield,mode:'default',next_best:490});
const draw=event('Corviknight SdA+AC/Pbk 4/12/14',500);
const win=event('Feraligatr (Shadow) SC+HC/IB 5/11/14',510,'i1y2');
const row={ivs:'0/11/12',rank:1,grade:'S候補',role:'不利シールド対応型',reason:'English old reason',search_string:'Quagsire&0attack&3defense&3hp',equivalent_candidates:[{ivs:'1/11/12',search_string:'Quagsire&1attack&3defense&3hp'}],evidence:[draw,win],evidence_count:2,tradeoff:{...draw,rating:450,best_iv:'3/13/8',best_rating:520}};
const result={candidate:{species:'quagsire',fast:'F',charged1:'C1',charged2:'C2'},selection:{recommendations:[row],excluded:0,unmatched_focus:[],review_candidates:[{ivs:'5/5/5',reason:'保留',equivalent_candidates:[]}],dominated_by:{'6/6/6':['0/11/12']}}};
context.result=result;context.draw=draw;
assert.equal(vm.runInContext("nicknameFor(result,result.selection.recommendations[0]).text",context),'SQuag>Fers12');
assert.equal(vm.runInContext("nicknameFor(result,{grade:'A候補',evidence:[draw]}).text",context),'AQuag=Cor01');
assert.equal(vm.runInContext("opponentLabel('Feraligatr (Shadow) SC+HC/IB 5/11/14').name",context),'オーダイル(シャドウ)');
assert.equal(vm.runInContext("nicknameFor(result,{evidence:[{opponent:'Unknown',rating:510}]} )",context),null);
vm.runInContext('render(result)',context);
const flat=e=>[e,...e.children.flatMap(flat)];const nodes=flat(els.results);
assert(nodes.some(n=>n.textContent==='オーダイル(シャドウ)：勝ち（標準IV・自分シールド1 / 相手2）'));
assert(nodes.some(n=>n.textContent==='アーマーガア：引き分け（標準IV・自分シールド0 / 相手1）'));
assert(!nodes.some(n=>n.textContent.includes('English old reason')||n.textContent.includes('Corviknight')));
const exported=vm.runInContext('recommendationExport(result)',context);
assert.equal(exported,'Quagsire&0attack&3defense&3hp\nSQuag>Fers12\nQuagsire&1attack&3defense&3hp\nSQuag>Fers12');
assert.equal(nodes.filter(n=>n.textContent==='検索式をコピー').length,2);
assert(!exported.includes('\t')&&!exported.includes('\n\n'));
assert.throws(()=>vm.runInContext('recommendationExport({candidate:result.candidate,selection:{recommendations:[{...result.selection.recommendations[0],search_string:null}]}})',context),/検索式/);
assert(!exported.includes('5,5,5')&&!exported.includes('6,6,6'));
assert.equal(els.allCopyActions.hidden,true);
// At most three distinct opponents total, across wins and draws. Full evidence
// remains inside details; repeated shields/moves do not crowd the summary.
context.many={...row,evidence:[win,{...win,shield:'s2'},draw,event('Quagsire MS+AT/SE',510),event('Fourth',520)]};
assert.equal(vm.runInContext('summaryEvidence(many).length',context),3);
assert.equal(vm.runInContext('summaryEvidence(many).map(e=>opponentLabel(e.opponent).name).join(",")',context),'オーダイル(シャドウ),アーマーガア,ヌオー');
const coveredResult={...result,selection:{...result.selection,covered_candidates:[{ivs:'2/2/2',covered_by:row.ivs,equivalent_candidates:[]}]}};
context.coveredResult=coveredResult;
vm.runInContext('render(coveredResult)',context);
const coveredNodes=flat(els.results);
assert(coveredNodes.some(n=>n.textContent==='役割が重複する個体（1）'));
assert.equal(vm.runInContext('recommendationExport(coveredResult)',context),exported);
assert(!vm.runInContext('recommendationExport(coveredResult)',context).includes('2/2/2'));
// The old summary could repeat a Kingdra win despite a different real role.
const overlapRow={...row,ivs:'4/10/6',rank:2,comparison_peer:'5/13/4',
 comparison_differences:[{opponent:'Quagsire MS+AT/SE',mode:'default',
  shield:'i0y1',rating:530,peer_rating:490}],comparison_difference_count:1,
 evidence:[{opponent:'Feraligatr (Shadow) SC+HC/IB',mode:'default',shield:'i0y1',rating:511,next_best:511}]};
const overlapResult={...result,selection:{...result.selection,explanation_version:'pairwise-v1',
 recommendations:[overlapRow],review_candidates:[],dominated_by:{}}};
context.overlapResult=overlapResult;
vm.runInContext('render(overlapResult)',context);
const overlapNodes=flat(els.results);
assert(overlapNodes.some(n=>n.textContent.includes('最も似た上位個体 5/13/4')));
assert(overlapNodes.some(n=>n.textContent.includes('ヌオー：勝ち')&&n.textContent.includes('5/13/4：負け')));
assert(!overlapNodes.some(n=>n.textContent.includes('オーダイル(シャドウ)：勝ち')),
 'Shared Rating=511 must not hide the real reason for retaining the IV.');
assert.equal(vm.runInContext('recommendationExport(overlapResult)',context).split('\n').length,2,
 'Search/nickname copy must stay intact.');
(async()=>{for(const b of nodes.filter(n=>n.textContent==='検索式をコピー')){await b.onclick();assert(['Quagsire&0attack&3defense&3hp','Quagsire&1attack&3defense&3hp'].includes(context.copied));}console.log('Japanese matchups, restored search copies, exact search/nickname pairs and alternatives: OK');})();

