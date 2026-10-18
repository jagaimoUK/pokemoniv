const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
const els={};function element(){return {value:'',textContent:'',hidden:false,disabled:false,children:[],append(x){this.children.push(x)},replaceChildren(){this.children=[]}}}
const c={document:{getElementById(k){return els[k]??=element()},createElement:element},location:{hash:''},URLSearchParams};vm.createContext(c);vm.runInContext(script,c);
vm.runInContext(`catalog={};for(const id of ['wooper','wooper_shadow','quagsire','quagsire_shadow','mew'])catalog[id]={name:id,fastMoves:['FAST'],chargedMoves:['C1','C2'],default_moves:{fast:'FAST',charged1:'C1',charged2:'C2'}};`,c);
const job=(id,cp)=>({candidate:{species:id,fast:'FAST',charged1:'C1',charged2:'C2'},name:id,ivs:'0,11,12',candidate_count:1,warnings:[],source_sections:[1],source_records:[{species:'wooper_shadow',ivs:'0/11/12',cp,search_string:'Wooper&shadow&0attack&3defense&3hp&cp'+cp}]});
c.jobs=[job('wooper_shadow',451),job('quagsire_shadow',451)];
vm.runInContext('setImportedJobs(jobs);applyBulkStatus("normal")',c);
assert.deepEqual(Array.from(vm.runInContext('importedJobs.map(j=>j.candidate.species)',c)),['wooper','quagsire']);
assert(vm.runInContext('importedJobs.every(j=>j.ivs==="0,11,12"&&j.source_records[0].cp===451)',c));
assert(vm.runInContext('importedJobs.every(j=>j.source_records[0].search_string.endsWith("&!shadow&!purified"))',c));
els.bulkStatusUndo.onclick();assert.equal(vm.runInContext('importedJobs[0].candidate.species',c),'wooper_shadow');
vm.runInContext('applyBulkStatus("purified")',c);assert.equal(vm.runInContext('importedJobs[1].pokemon_status',c),'purified');
assert(vm.runInContext('importedJobs[0].source_records[0].search_string.includes("&purified")',c));
vm.runInContext('applyBulkStatus("shadow");applyBulkStatus("shadow")',c);assert.equal(vm.runInContext('importedJobs[0].source_records[0].search_string.match(/&shadow/g).length',c),1);
// Unsupported variants must leave ALL jobs unchanged.
c.bad=[job('wooper',451),job('mew',450)];vm.runInContext('setImportedJobs(bad);applyBulkStatus("shadow")',c);
assert.equal(vm.runInContext('importedJobs[0].candidate.species',c),'wooper');assert(els.message.textContent.includes('全体の変更を中止'));
// Source species also require a valid variant, even when a final evolution exists.
vm.runInContext('delete catalog.wooper_shadow;setImportedJobs([jobs[1]]);applyBulkStatus("shadow")',c);assert.equal(vm.runInContext('importedSingle.candidate.species',c),'quagsire_shadow');
// Single-form data and copied searches preserve IV and CP; status survives the run job.
vm.runInContext('setImportedJobs(null);setCandidate({species:"wooper",fast:"FAST",charged1:"C1",charged2:"C2"});el("ivs").value="1,2,3";applyBulkStatus("purified")',c);
assert.equal(vm.runInContext('inputPokemonStatus',c),'purified');assert.equal(els.ivs.value,'1,2,3');
c.result={pokemon_status:'purified',source_records:[{species:'wooper',ivs:'1/2/3',cp:500,search_string:'Wooper&shadow&1attack&1defense&1hp&cp500'}]};c.iv={ivs:'1/2/3',search_string:'Quagsire&shadow&1attack&1defense&1hp'};
assert.equal(vm.runInContext('individualSearches(result,iv)[0].search',c),'Wooper&1attack&1defense&1hp&cp500&purified');
assert.equal(vm.runInContext('individualSearches({pokemon_status:"normal"},iv)[0].search',c),'Quagsire&1attack&1defense&1hp&!shadow&!purified');
vm.runInContext('active=true;applyBulkStatus("normal")',c);assert.equal(vm.runInContext('inputPokemonStatus',c),'purified');
console.log('Bulk status: normal/shadow/purified, undo, atomic failure, source CP, exports, busy guard: PASS');
