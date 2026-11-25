const assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
const cat={corsola:{name:'Corsola',name_ja:'サニーゴ',aliases:['サニーゴ'],fastMoves:['A'],chargedMoves:['B','C','D'],default_moves:{fast:'A',charged1:'C',charged2:'D'}},corsola_galarian:{name:'Corsola (Galarian)',name_ja:'サニーゴ (ガラル)',aliases:['ガラルサニーゴ'],fastMoves:['X'],chargedMoves:['Y','Z']}};
const moveNames={A:{name:'Tackle',name_ja:'たいあたり'},B:{name:'Hydro Cannon',name_ja:'ハイドロカノン'},C:{name:'Ice Beam',name_ja:'れいとうビーム'},D:{name:'Play Rough',name_ja:'じゃれつく'},X:{name:'Astonish',name_ja:'おどろかす'},Y:{name:'Shadow Ball',name_ja:'シャドーボール'},Z:{name:'Night Shade',name_ja:'ナイトヘッド'}};
const context={catalog:cat,partyMoveNames:moveNames,module:{exports:{}}};vm.createContext(context);vm.runInContext(fs.readFileSync('pvpoke_party_input.js','utf8'),context);
const x=context.module.exports;
assert.equal(x.resolvePartyName('サニーゴ',cat),'corsola');assert.equal(x.resolvePartyName('さにーご',cat),'corsola');assert.equal(x.resolvePartyName('Ｃｏｒｓｏｌａ',cat),'corsola');assert.equal(x.resolvePartyName('ガラルサニーゴ',cat),'corsola_galarian');assert.equal(x.partySearch('サニーゴ',cat).length,2);
assert.equal(x.partyDefaultMoves(cat.corsola).moves.charged1,'C');assert.equal(x.partyDefaultMoves(cat.corsola_galarian).recommended,false);
assert.equal(context.parseCsv('サニーゴ')[0].charged1,'C');
assert.equal(x.partyMoveLabel('C',moveNames),'れいとうビーム');
assert.equal(vm.runInContext("['A','C','D'].map(id=>partyMoveLabel(id)).join(' / ')",context),'たいあたり / れいとうビーム / じゃれつく');
assert.equal(x.resolvePartyMove('れいとうびーむ',cat.corsola.chargedMoves,moveNames),'C');
assert.equal(x.resolvePartyMove('Ice Beam',cat.corsola.chargedMoves,moveNames),'C');
assert.equal(x.resolvePartyMove('Ｃ',cat.corsola.chargedMoves,moveNames),'C');
assert.equal(context.parseCsv('サニーゴ,たいあたり,れいとうビーム,じゃれつく,0,15,15')[0].charged2,'D');
assert.equal(context.parseCsv('サニーゴ,Tackle,Ice Beam,Play Rough')[0].fast,'A');
assert.throws(()=>context.parseCsv('サニーゴ,たいあたり,れいとうビーム,れいとうビーム'),/異なる2種類/);
assert.throws(()=>context.parseCsv('サニーゴ,たいあたり,未習得技,じゃれつく'),/習得技/);assert.equal(context.parseCsv('Corsola,A,B,C,0,15,15')[0].species,'corsola');
assert.throws(()=>x.resolvePartyName('サニ',cat));assert.throws(()=>context.parseCsv('未登録'));
cat.corsola_galarian.aliases.push('サニーゴ');assert.throws(()=>x.resolvePartyName('サニーゴ',cat),/複数/);
cat.corsola_galarian.aliases.pop();
function makeDomStub(){
 const makeEl=(tag)=>{
  let _val='';
  const el={
   tagName:String(tag||'div').toUpperCase(),className:'',textContent:'',type:'',placeholder:'',hidden:false,disabled:false,min:'',max:'',step:'',
   get value(){return _val;},set value(v){_val=v==null?'':String(v);},
   dataset:{},attrs:{},style:{},children:[],options:[],listeners:{},customValidity:'',blurred:0,
   setAttribute(k,v){el.attrs[k]=String(v);},
   setCustomValidity(m){el.customValidity=String(m||'');},
   blur(){el.blurred++;},
   focus(){},
   closest(sel){return sel==='.mon-card'?(el.className.includes('mon-card')?el:null):null;},
   addEventListener(ev,fn){(el.listeners[ev]??=[]).push(fn);},
   dispatch(ev,e={}){for(const fn of el.listeners[ev]||[])fn(e);if(typeof el['on'+ev]==='function')el['on'+ev](e);},
   append(...nodes){for(const n of nodes){if(typeof n==='string'){el.textContent+=n;continue;}if(el.tagName==='SELECT'&&n.tagName==='OPTION')el.options.push(n);el.children.push(n);}},
   replaceChildren(...nodes){el.children=[];if(el.tagName==='SELECT')el.options=[];el.append(...nodes);},
   querySelector(sel){return el.querySelectorAll(sel)[0]||null;},
   querySelectorAll(sel){
    const out=[];
    const match=(n)=>{
     if(!n||typeof n!=='object')return false;
     if(sel==='button')return n.tagName==='BUTTON';
     if(sel==='[data-field]')return !!(n.dataset&&n.dataset.field);
     const m=sel.match(/^\[data-field=([^\]]+)\]$/);
     if(m)return n.dataset&&n.dataset.field===m[1];
     const m2=sel.match(/^\.([^\s]+)$/);
     if(m2)return String(n.className||'').split(/\s+/).includes(m2[1]);
     return false;
    };
    const walk=(node)=>{for(const c of node.children||[]){if(match(c))out.push(c);walk(c);}};
    walk(el);return out;
   }
  };
  return el;
 };
 return{
  document:{createElement:(tag)=>makeEl(tag),createTextNode:(t)=>String(t)},
  Option:function(text,value){const o=makeEl('option');o.textContent=text;o.value=value===undefined?text:String(value);return o;}
 };
}
(async()=>{
 const dom=makeDomStub();
 const node=(tag,content,cls)=>{const el=dom.document.createElement(tag);if(cls)el.className=cls;if(Array.isArray(content))el.append(...content);else if(content!==undefined&&content!==null)el.append(content);return el;};
 const imeCtx={catalog:cat,partyMoveNames:moveNames,document:dom.document,Option:dom.Option,node,setTimeout,clearTimeout,module:{exports:{}}};
 vm.createContext(imeCtx);
 vm.runInContext(fs.readFileSync('pvpoke_party_input.js','utf8'),imeCtx);
 const card=imeCtx.createMon({level:50,atk:15,def:15,sta:15});
 const input=card.querySelector('[data-field=species]');
 const suggestions=card.querySelector('.suggestions');
 assert.ok(input&&suggestions);
 input.dispatch('compositionstart');
 input.value='さに';
 input.dispatch('input');
 assert.equal(suggestions.hidden,false);
 const corsolaBtn=suggestions.querySelectorAll('button').find(b=>b.textContent.startsWith('サニーゴ / '));
 assert.ok(corsolaBtn);
 corsolaBtn.dispatch('touchstart');
 corsolaBtn.dispatch('mousedown',{preventDefault(){}});
 corsolaBtn.dispatch('click');
 assert.equal(input.value,'サニーゴ');
 assert.equal(input.dataset.species,'corsola');
 assert.equal(suggestions.hidden,true);
 // Simulate delayed Android/Gboard IME flush appending uncommitted 'さに' after tap
 input.value='サニーゴさに';
 input.dispatch('input');
 input.value='サニーゴさに';
 input.dispatch('compositionend');
 assert.equal(input.value,'サニーゴ');
 assert.equal(input.dataset.species,'corsola');
 assert.equal(suggestions.hidden,true);
 await new Promise(r=>setTimeout(r,220));
 assert.equal(input.value,'サニーゴ');
 assert.equal(input.dataset.species,'corsola');
 assert.equal(imeCtx.readPartyCard(card).species,'corsola');
 console.log('Japanese/English species and move names, CSV validation, forms, defaults, and IME suggestion tap passed');
})().catch(err=>{console.error(err);process.exit(1);});
