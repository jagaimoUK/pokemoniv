const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const content=fs.readFileSync('pvpoke_app_ui.py','utf8');
assert(content.includes('<nav class="quick-nav" aria-label="ページ内の移動">'));
assert(content.includes('<a href="#pageTop" aria-label="ページ上部に戻る">'));
assert(content.includes('<main id="pageTop">'));
assert(content.includes('top:44vh'),'Desktop return-to-top should be near the middle');
assert(content.includes('top:58vh;bottom:auto'),
  'Mobile return button should stay at the current thumb-height position');
assert(content.includes('min-height:48px;min-width:48px'),'Touch target must remain comfortably tappable');
const receiver=content.match(/function receiveReaderInput\(\)\{[\s\S]*?\n\}\nconst access=/);
assert(receiver,'Reader receiver must be defined before access handling');
const values={importText:{value:''}};
let hash='',url='',notice='',error=false;
const ctx={URLSearchParams,Uint8Array,TextDecoder,atob,active:false,readerInputText:null,readerImportPending:false,
  location:{get hash(){return hash},pathname:'/app',search:'?from=android'},
  history:{replaceState(a,b,c){url=c}},
  el:id=>values[id],
  message:(s,b)=>{notice=s;error=Boolean(b)}
};
vm.createContext(ctx);
vm.runInContext(receiver[0].replace(/\nconst access=$/,''),ctx);
const raw='個体値厳選\n\n# ヌオー\n0,11,12 CP717 | ウパー';
const encoded=Buffer.from(raw,'utf8').toString('base64url');
hash='#ivdata='+encoded;
assert(vm.runInContext('receiveReaderInput()',ctx));
assert.strictEqual(values.importText.value,raw);
assert.strictEqual(url,'/app?from=android');
assert(!error&&notice.includes('受け取りました'));
hash='#ivdata='+Buffer.from('bad','utf8').toString('base64url');
assert(!vm.runInContext('receiveReaderInput()',ctx));
assert(error);
const large='個体値厳選\n# ヌオー\n'+Array.from({length:4096},(_,i)=>`${i>>8},${(i>>4)&15},${i&15} CP717 | ウパー`).join('\n');
hash='#ivdata='+Buffer.from(large,'utf8').toString('base64url');
assert(vm.runInContext('receiveReaderInput()',ctx));
assert.strictEqual(values.importText.value,large);
const prior=values.importText.value;
hash='#ivdata='+Buffer.from('個体値厳選\n# ヌオー\n'+'あ'.repeat(128001),'utf8').toString('base64url');
assert(!vm.runInContext('receiveReaderInput()',ctx));
assert.strictEqual(values.importText.value,prior,'Oversized input must not replace or truncate existing text');
hash='#pageTop'; assert(!vm.runInContext('receiveReaderInput()',ctx));
console.log('Reader IV handoff / invalid payload / back-to-top accessibility: OK');
