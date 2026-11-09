const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('pvpoke_app_ui.py','utf8');
const fn=source.match(/function xxlProtectedSearch\(search\)\{([\s\S]*?)\n\}/)[0];
const ctx={};vm.createContext(ctx);vm.runInContext(fn,ctx);
assert.equal(ctx.xxlProtectedSearch('Teddiursa&cp500&!xxl&!shadow'),'Teddiursa&cp500&!shadow');
assert.equal(ctx.xxlProtectedSearch('Teddiursa&cp500'),'Teddiursa&cp500');
assert.equal(ctx.xxlProtectedSearch('Gourgeist&xxl&shadow'),'Gourgeist&xxl&shadow');
assert(!source.includes('<option value="gpt">'));
const els={},storage=new Map();
function element(){return {value:'',hidden:false,children:[],append(x){this.children.push(x)},replaceChildren(){this.children=[]}};}
const app={URLSearchParams,location:{hash:''},document:{getElementById:id=>els[id]??=element(),createElement:element},sessionStorage:{getItem:()=>null},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},fetch:async()=>({status:401})};
vm.createContext(app);vm.runInContext(source.split('<script>')[1].split('</script>')[0],app);
vm.runInContext("active=true;el('evaluation').value='gpt';startSelection()",app);
assert.equal(els.evaluation.value,'app');
console.log('XXL individuals retained; selection uses app evaluation: OK');
