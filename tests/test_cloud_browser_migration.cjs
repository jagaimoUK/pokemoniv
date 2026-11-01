const assert=require('node:assert/strict');
const M=require('../pvpoke_browser_migration.js');
const make=()=>({format:M.FORMAT,local:{'pvpoke-app-movesets-v1':null},session:{'pvpoke-app-batch':null,'pvpoke-app-run':null},flashcards:{kv:[],reviews:[]}});
const current=make(),incoming=make();
incoming.local['pvpoke-app-movesets-v1']='{"quagsire":[{"fast":"MUD_SHOT"}]}';
incoming.session['pvpoke-app-batch']='{"jobs":[],"results":[]}';
incoming.flashcards.kv=[['session',{deck:'custom',index:3}],['undo',{id:'previous'}]];
incoming.flashcards.reviews=[['a',{due:123,seen:true}]];
M.validate(incoming);
assert.deepEqual(M.conflicts(current,incoming),[]);
assert.equal(M.covers(current,incoming),false);
assert.equal(M.covers(incoming,incoming),true);
assert.deepEqual(M.conflicts(incoming,incoming),[]);
const other=structuredClone(incoming);other.flashcards.reviews[0][1].due=456;
assert.equal(M.conflicts(other,incoming).length,1);
assert.equal(M.covers(other,incoming),false);
for(const mutate of [
 x=>x.format='unknown',x=>x.local.token='secret',x=>x.local['pvpoke-app-movesets-v1']={},
 x=>x.flashcards.reviews.push(['a',{}]),x=>delete x.flashcards.kv,
 x=>x.flashcards.kv=[[123,{}]],x=>x.session={},
]){const invalid=structuredClone(incoming);mutate(invalid);assert.throws(()=>M.validate(invalid));}
assert(!require('fs').readFileSync('pvpoke_browser_migration.js','utf8').includes('document.cookie'));
console.log('Browser migration schema, allowlist, conflict and completeness checks: PASS');
