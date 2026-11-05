const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0],els={},calls=[];
function element(tag='div'){const e={tag,children:[],value:'',textContent:'',hidden:false,disabled:false,style:{},attrs:{},setAttribute(k,v){this.attrs[k]=v},getAttribute(k){return this.attrs[k]},append(x){this.children.push(x)},replaceChildren(){this.children=[]}};Object.defineProperty(e,'id',{set(v){els[v]=e}});return e;}
const get=id=>els[id]??=element();
const ctx={document:{getElementById:get,createElement:element},URLSearchParams,location:{hash:''},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}},fetch:async()=>({status:401})};
vm.createContext(ctx);vm.runInContext(script,ctx);
vm.runInContext("catalog={corviknight:{name:'Corviknight',name_ja:'アーマーガア',fastMoves:['SAND_ATTACK','STEEL_WING'],chargedMoves:['IRON_HEAD','AIR_CUTTER']},corsola_galarian:{name:'Corsola (Galarian)',name_ja:'サニーゴ（ガラル）',fastMoves:['ASTONISH'],chargedMoves:['NIGHT_SHADE','POWER_GEM']}};moveCatalog={SAND_ATTACK:{name:'Sand Attack',name_ja:'すなかけ'},STEEL_WING:{name:'Steel Wing',name_ja:'はがねのつばさ'}};metaState={revision:3,items:[{id:'official',name:'テストメタ',source:'pvpoke',sha256:'a'.repeat(64),rows:2}],default_id:'official'};selectedMetaId='official'",ctx);
const csv='corviknight,SAND_ATTACK,IRON_HEAD,AIR_CUTTER\ncorsola_galarian,ASTONISH,NIGHT_SHADE,POWER_GEM\n';let conflict=true;
ctx.fetch=async(path,opts)=>{const data=JSON.parse(opts.body);calls.push({path,data});let out;
 if(path.endsWith('/meta-preset-export'))out={id:'official',sha256:'a'.repeat(64),csv};
 else if(path.endsWith('/meta-preview'))out={rows:1,sha256:'b'.repeat(64)};
 else if(path.endsWith('/meta-preset-save')){if(conflict)return {status:400,ok:false,json:async()=>({error:'競合'})};out={revision:4,saved_id:'custom:edited',items:[{id:'custom:edited',name:'編集',source:'custom',rows:1,sha256:'b'.repeat(64)}]};}
 else throw Error(path);return {ok:true,json:async()=>out};};
(async()=>{
 await ctx.openMetaEditor();assert.equal(get('metaEditorRows').children.length,2);
 assert.equal(ctx.metaResolveSpecies('サニーゴ(ガラル)'),'corsola_galarian');
 const card=get('metaEditorRows').children[0],fields=card.children.find(e=>e.className==='meta-edit-fields');
 const fast=fields.children.find(e=>e.textContent==='技1').children[0];fast.value='Steel Wing';fast.oninput();fast.onchange();
 assert.equal(vm.runInContext('metaDraft.rows[0].fast',ctx),'STEEL_WING');
 get('metaEditorRows').children[1].children.find(e=>e.className==='secondary meta-edit-remove').onclick();
 assert.equal(vm.runInContext('metaDraft.rows.length',ctx),1);
 get('metaEditorUndo').onclick();assert.equal(vm.runInContext('metaDraft.rows.length',ctx),2);
 get('metaEditorRows').children[1].children.find(e=>e.className==='secondary meta-edit-remove').onclick();
 await ctx.saveMetaEditor();assert(get('metaEditorStatus').textContent.includes('編集内容は残っています'));assert(!get('metaEditor').hidden);
 conflict=false;await ctx.saveMetaEditor();assert(get('metaEditor').hidden);
 const saved=calls.filter(c=>c.path.endsWith('/meta-preset-save')).at(-1).data;
 assert.equal(saved.csv,'corviknight,STEEL_WING,IRON_HEAD,AIR_CUTTER\n');assert.equal(saved.action,'create');assert.equal(saved.exact_rows,true);assert.equal(saved.revision,3);
 assert(!calls.some(c=>c.path.endsWith('/run')));
 console.log('Meta editor: bilingual candidate resolution, draft moves, delete/undo, exact copy save, conflict retention: OK');
})().catch(e=>{console.error(e);process.exitCode=1});
