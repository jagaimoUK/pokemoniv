const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('pvpoke_app_ui.py','utf8').split('<script>')[1].split('</script>')[0];
const elements={};
const context={document:{getElementById(id){return elements[id]??={value:'',hidden:false};}},
 URLSearchParams,location:{hash:''},sessionStorage:{getItem(){return null;}},
 fetch:async()=>({ok:false,status:401,json:async()=>({error:'login'})})};
vm.createContext(context);vm.runInContext(script,context);
for(const name of ['Flabébé','Flabebe','Flabe\u0301be\u0301','FLABÉBÉ']){
 context.query=name+'&0attack&3defense&4hp&cp500&shadow';
 assert.equal(vm.runInContext('statusSearch(query,null)',context),'669&0attack&3defense&4hp&cp500&shadow');
 assert.equal(vm.runInContext("statusSearch(query,'purified')",context),'669&0attack&3defense&4hp&cp500&purified');
}
context.query='Floette&cp500';
assert.equal(vm.runInContext('statusSearch(query,null)',context),'Floette&cp500');
console.log('Flabébé saved-result searches: accents, CP, IVs, status and evolution names: PASS');
