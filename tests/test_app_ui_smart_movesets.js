const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('pvpoke_app_ui.py','utf8'),script=html.split('<script>')[1].split('</script>')[0];
const storage=new Map(),els={};
function element(){return {value:'',hidden:false,children:[],append(x){this.children.push(x)},replaceChildren(){this.children=[]},scrollIntoView(){this.scrolled=true},focus(){this.focused=true}};}
const ctx={URLSearchParams,location:{hash:''},document:{getElementById:id=>els[id]??=element(),createElement:element},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},fetch:async()=>({status:401})};
vm.createContext(ctx);vm.runInContext(script,ctx);
const species={name:'Example',name_ja:'テスト',types:['normal'],fastMoves:['FAST','WEAK','ALT'],chargedMoves:['MAIN','DUP','ICE','FIRE','BUFF','CHEAP','WEAK_C'],default_moves:{fast:'FAST',charged1:'MAIN',charged2:'ICE'}};
const move=(type,power,energy,extra={})=>({type,power,energy,...extra});
const stats={FAST:{type:'normal',power:6,energyGain:8,cooldown:1000},WEAK:{type:'normal',power:3,energyGain:5,cooldown:1000},ALT:{type:'ghost',power:5,energyGain:9,cooldown:1000},MAIN:move('normal',90,50),DUP:move('normal',90,50),ICE:move('ice',85,50),FIRE:move('fire',85,50),BUFF:move('normal',60,40,{buffs:[1,0],buffTarget:'self',buffApplyChance:1}),CHEAP:move('normal',55,35),WEAK_C:move('normal',20,60)};
ctx.speciesFixture=species;ctx.statsFixture=stats;
vm.runInContext('catalog={test:speciesFixture,other:speciesFixture};moveCatalog=statsFixture',ctx);
const base={name:'テスト',candidate:{species:'test',fast:'FAST',charged1:'MAIN',charged2:'ICE'},ivs:'0,15,15\n1,14,15',source_records:[{ivs:'0/15/15',cp:717,species:'test'}],source_sections:[7]};ctx.base=base;
for(const id of ['species','fast','charged1','charged2'])ctx.document.getElementById(id);
const all=ctx.planMovesets([base],'all'),smart=ctx.planMovesets([base],'smart');
assert.equal(all.length,63);
assert(smart.length<=7&&smart.length<all.length/3,smart.length);
assert.equal(smart[0].candidate.charged1,'MAIN');
assert(smart.every(j=>j.ivs===base.ivs&&j.source_records===base.source_records));
assert(smart.every(j=>j.candidate.fast!=='WEAK'&&![j.candidate.charged1,j.candidate.charged2].includes('WEAK_C')));
assert(smart.some(j=>[j.candidate.charged1,j.candidate.charged2].includes('FIRE')),'Preserve strong alternate coverage');
assert(smart.some(j=>[j.candidate.charged1,j.candidate.charged2].includes('BUFF')),'Consider stat-changing role');
assert(smart.every(j=>j.moveset_plan.omitted===63-smart.length));
// UI registration, persistence and reversed charge deduplication.
els.species.value='test';els.fast.value='WEAK';els.charged1.value='MAIN';els.charged2.value='WEAK_C';ctx.document.getElementById('addMoveset').onclick();
assert(storage.size===1);assert.equal(ctx.readSavedMovesets().test.length,1);
els.charged1.value='WEAK_C';els.charged2.value='MAIN';ctx.document.getElementById('addMoveset').onclick();
assert.equal(ctx.readSavedMovesets().test.length,1);
els.fast.value='ALT';els.charged1.value='ICE';els.charged2.value='FIRE';ctx.document.getElementById('addMoveset').onclick();
assert.equal(ctx.readSavedMovesets().test.length,2);
const manual=ctx.planMovesets([base],'manual');assert.equal(manual.length,2);
assert(ctx.planMovesets([base],'smart').some(j=>j.candidate.fast==='WEAK'),'Explicit registrations bypass heuristic strength cutoff');
vm.runInContext('savedMovesets.test[0].enabled=false',ctx);assert.equal(ctx.planMovesets([base],'manual').length,1);
// Targeted editing for a multi-species import, keeping each source CP separate.
ctx.other={...base,name:'別種',candidate:{...base.candidate,species:'other'},source_records:[{ivs:'0/15/15',cp:500,species:'other'}]};
vm.runInContext('setImportedJobs([base,other])',ctx);assert.equal(els.movesetTargetRow.hidden,false);assert(!els.fast.disabled);
els.movesetTarget.value='other';els.fast.value='ALT';els.charged1.value='MAIN';els.charged2.value='FIRE';els.addMoveset.onclick();
assert.equal(ctx.readSavedMovesets().other.length,1);assert.equal(ctx.readSavedMovesets().test.length,2);
const mixed=vm.runInContext("planMovesets([base,other],'manual')",ctx);assert.equal(mixed.length,2);assert.equal(mixed[1].source_records[0].cp,500);
const same=ctx.planMovesets([base,{...base,candidate:{...base.candidate,charged2:'FIRE'}}],'all');assert.equal(same.length,63,'Same-source inputs deduplicate profiles');
const different=ctx.planMovesets([base,{...base,ivs:'2,13,14'}],'manual');assert.equal(new Set(different.map(j=>j.moveset_group)).size,2,'Different input IVs never merge');
// Unsupported metadata never silently restores exhaustive calculations.
vm.runInContext('moveCatalog={};savedMovesets={}',ctx);const missing=ctx.planMovesets([base],'smart');assert.equal(missing.length,1);assert(missing[0].moveset_plan.incomplete);
vm.runInContext("savedMovesets={test:[{species:'test',fast:'REMOVED',charged1:'MAIN',charged2:'ICE'}]}",ctx);assert.throws(()=>ctx.planMovesets([base],'smart'),/登録構成/);
assert(html.indexOf('id="results"')<html.indexOf('id="metaManager"'));assert.equal((html.match(/id="results"/g)||[]).length,1);
assert(html.includes('value="smart"')&&html.includes('value="all"'));
console.log(`Smart planning: ${all.length} → ${smart.length} fixture profiles; coverage/effects, explicit override, persistent multi-species UI and source isolation: OK`);
