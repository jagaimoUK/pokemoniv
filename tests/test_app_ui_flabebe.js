const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
const elements={};
const context={document:{getElementById(id){return elements[id]??={value:'',hidden:false};}},
 URLSearchParams,location:{hash:''},sessionStorage:{getItem(){return null;}},
 fetch:async()=>({ok:false,status:401,json:async()=>({error:'login'})})};
vm.createContext(context);vm.runInContext(script,context);
vm.runInContext(`catalog={
 flabebe:{dex:669,name:'Flabébé'},
 flabebe_blue:{dex:669,name:'Flabébé (Blue)'},
 floette:{dex:670,name:'Floette'},
 wooper:{dex:194,name:'Wooper'},
 wooper_paldean:{dex:194,name:'Wooper (Paldean)'},
 nidoran_female:{dex:29,name:'Nidoran (Female)'},
 nidoran_male:{dex:32,name:'Nidoran (Male)'},
 rotom:{dex:479,name:'Rotom'},
 rotom_wash:{dex:479,name:'Rotom (Wash)'}
}`,context);
for(const name of ['Flabébé','Flabebe','Flabe\u0301be\u0301','FLABÉBÉ','669']){
 context.query=name+'&0attack&3defense&4hp&cp500&shadow';
 assert.equal(vm.runInContext('statusSearch(query,null)',context),
  'Flabébé&0attack&3defense&4hp&cp500&shadow');
 assert.equal(vm.runInContext("statusSearch(query,'purified')",context),
  'Flabébé&0attack&3defense&4hp&cp500&purified');
}
assert.equal(vm.runInContext("statusSearch('Floette&cp500',null)",context),'Floette&cp500');
assert.equal(vm.runInContext("statusSearch('194&paldea&cp500&!shadow',null)",context),
 'Wooper&paldea&cp500&!shadow');
assert.equal(vm.runInContext("statusSearch('29&0attack&cp500',null)",context),
 'Nidoran&female&0attack&cp500');
assert.equal(vm.runInContext("statusSearch('32&0attack&cp500',null)",context),
 'Nidoran&male&0attack&cp500');
assert.equal(vm.runInContext("statusSearch('479&cp500',null)",context),'Rotom&cp500');
assert.throws(()=>vm.runInContext("statusSearch('99999&cp500',null)",context),
 /英語名を一意に確認できません/);
// The reader's source species may differ from the evolved battle species.
// Use its original National Dex, not the battle candidate's species ID.
vm.runInContext(`archived={candidate:{species:'floette'},
 pokemon_status:'shadow',
 source_records:[{ivs:'0/11/15',species:'flabebe',cp:492,search_string:'669&0attack&3defense&4hp&cp492'}]};
 searchRow={ivs:'0/11/15',search_string:'669&0attack&3defense&4hp'}`,context);
const rows=vm.runInContext('individualSearches(archived,searchRow)',context);
assert.equal(rows.length,1);
assert.equal(rows[0].search,'Flabébé&0attack&3defense&4hp&cp492&shadow');
assert.equal(rows[0].cp,492);
console.log('English Pokémon GO names: new, archived, forms, CP, IV, shadow and unknown dex: OK');
