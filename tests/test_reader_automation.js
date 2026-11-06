const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/../pvpoke_app_ui.py','utf8');
const code=source.slice(source.indexOf('let readerAutomation=null;'),source.indexOf('// Reader-to-browser handoff is kept'));
const saved=new Map();const c={sessionStorage:{getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)},batchState:null,xxlProtectedSearch:s=>s,statusSearch:s=>s,URLSearchParams,Map};
vm.createContext(c);vm.runInContext(code,c);
function result(extra={}){return {source_records:[{ivs:'0/15/15',search_string:'Stunky&0attack&3defense&3hp&cp131'}],selection:{complete:true,dominated_by:{'0/15/15':['1/15/15']},recommendations:[],review_candidates:[],additional_candidates:[]},...extra};}
assert.equal(c.readerDiscardQueries([result()]).length,1);
assert.equal(c.readerDiscardQueries([result(),result({selection:{complete:true,dominated_by:{}}})]).length,0);
for(const key of ['recommendations','review_candidates','additional_candidates']){
 const r=result();r.selection[key]=[{ivs:'0/15/15'}];assert.equal(c.readerDiscardQueries([r]).length,0);
}
const r=result();r.selection.recommendations=[{ivs:'1/15/15',equivalent_candidates:[{ivs:'0/15/15'}]}];assert.equal(c.readerDiscardQueries([r]).length,0);
assert.throws(()=>c.configureReaderAutomation(new URLSearchParams('automation=bad&digest=bad')));
c.configureReaderAutomation(new URLSearchParams('automation='+'a'.repeat(64)+'&digest='+'b'.repeat(64)));
c.batchState={jobs:[]};assert.throws(()=>c.configureReaderAutomation(new URLSearchParams('automation='+'a'.repeat(64)+'&digest='+'c'.repeat(64))));
console.log('Reader automation correlation and conservative discard classification: PASS');
c.TextEncoder=TextEncoder;c.btoa=s=>Buffer.from(s,'binary').toString('base64');c.displayedResults=[];
let navigated='',button=null;c.node=()=>button={};c.el=()=>({});c.message=()=>{};c.window={location:{assign:x=>navigated=x}};
c.returnReaderAutomation([result()]);assert(navigated.startsWith('intent://automation?payload='));assert.equal(typeof button.onclick,'function');
const encoded=navigated.split('payload=')[1].split('#Intent')[0];const payload=JSON.parse(Buffer.from(encoded,'base64url').toString('utf8'));
assert.equal(payload.nonce,'a'.repeat(64));assert.equal(payload.digest,'b'.repeat(64));assert.equal(payload.discard.length,1);assert.equal(payload.keep.items.length,0);
assert.equal(vm.runInContext('readerAutomation',c),null,'Completed automation must not apply to a later manual run');
console.log('Correlated return payload, manual return fallback and stale-session clearing: PASS');

const keptFavorite=result();keptFavorite.source_records[0].search_string+='&favorite';keptFavorite.selection.recommendations=[{ivs:'0/15/15'}];
assert.equal(c.readerDiscardQueries([result(),keptFavorite]).length,0,'favorite filters must be removed BEFORE classifying colliding source identities');
console.log('Favorite-filter canonical collision protection: PASS');
